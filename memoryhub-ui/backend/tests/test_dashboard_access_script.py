"""Scenarios for memoryhub-ui/deploy/dashboard-access.sh against a stub `oc` (#744).

No cluster is touched. On macOS run with the system shell to cover Bash 3.2:
    HUMAN_ACCESS_BASH=/bin/bash pytest tests/test_dashboard_access_script.py
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "dashboard-access.sh"
BASH = os.environ.get("HUMAN_ACCESS_BASH", "bash")

# A tiny in-memory OpenShift: Roles, RoleBindings, one legacy Secret and
# ClusterRoleBindings, persisted in a JSON file between calls.
STUB = textwrap.dedent("""\
    import base64, json, os, sys
    path = os.environ["OC_STATE"]
    state = json.load(open(path)) if os.path.exists(path) else {}
    for key in ("roles", "rolebindings", "crbs"):
        state.setdefault(key, {})
    state.setdefault("secret", None)
    args = sys.argv[1:]
    with open(path + ".log", "a") as log:
        log.write(json.dumps(args) + "\\n")
    if args[:1] == ["--context"]:
        args = args[2:]

    def save():
        json.dump(state, open(path, "w"))

    def opt(name):
        return args[args.index(name) + 1] if name in args else ""

    out = opt("-o")
    if args[0] == "whoami":
        print(os.environ.get("OC_WHO", "katya")); sys.exit(0)
    if args[0] == "apply":
        text = sys.stdin.read()
        if "ClusterRoleBinding" in text and not text.lstrip().startswith("{"):
            state["crbs"]["delegator"] = True; save(); sys.exit(0)
        doc = json.loads(text)
        for item in doc["items"] if doc["kind"] == "List" else [doc]:
            name = item["metadata"]["name"]
            if item["kind"] == "Role":
                old = state["roles"].get(name, {})
                item["metadata"]["annotations"] = old.get("metadata", {}).get("annotations", {})
                state["roles"][name] = item
            elif item["kind"] == "RoleBinding":
                state["rolebindings"][name] = item
            elif item["kind"] == "Secret":
                old = state["secret"] or {}
                state["secret"] = {**item["data"], "annotations": old.get("annotations", {})}
        save(); sys.exit(0)
    if args[0] == "create" and args[1] == "secret":
        data = dict(a.split("=", 1)[1].split("=", 1) for a in args if a.startswith("--from-literal="))
        print(json.dumps({"kind": "Secret", "metadata": {"name": args[3]}, "data": data})); sys.exit(0)
    if args[0] == "label":
        sys.exit(0)
    if args[0] == "create" and args[1] == "clusterrolebinding":
        print("kind: ClusterRoleBinding"); sys.exit(0)
    if args[0] == "delete":
        kind, name = args[1], args[2]
        if kind == "rolebinding":
            state["rolebindings"].pop(name, None)
        elif kind == "clusterrolebinding":
            state["crbs"].pop("delegator", None)
        save(); sys.exit(0)
    if args[0] == "annotate":
        kind, name = args[1], args[2]
        pairs = dict(a.split("=", 1) for a in args[3:] if "=" in a and not a.startswith("-"))
        target = state["roles"][name]["metadata"] if kind == "role" else state["secret"]
        target.setdefault("annotations", {}).update(pairs)
        save(); sys.exit(0)
    if args[0] == "get":
        kind = args[1]
        if kind == "rolebindings":
            for name, rb in sorted(state["rolebindings"].items()):
                subjects = "".join(f"{s['kind']}:{s['name']}|" for s in rb["subjects"])
                print(f"{rb['roleRef']['name']}\\t{name}\\t{subjects}")
            sys.exit(0)
        name = args[2]
        if kind == "rolebinding":
            sys.exit(0 if name in state["rolebindings"] else 1)
        if kind == "group":
            for member in state.get("groups", {}).get(name, []):
                print(member)
            sys.exit(0)
        if kind == "role":
            if name not in state["roles"]:
                sys.exit(1)
            ann = state["roles"][name]["metadata"].get("annotations", {})
            print(ann.get("memoryhub.io/bootstrapped-at", ""), end=""); sys.exit(0)
        if kind == "secret":
            secret = state["secret"]
            if secret is None:
                sys.exit(1)
            if "migrated-to-rbac-at" in out:
                print(secret.get("annotations", {}).get("memoryhub.io/migrated-to-rbac-at", ""), end="")
            for key in ("MEMORYHUB_UI_ADMIN_USERS", "MEMORYHUB_UI_ALLOWED_USERS"):
                if key in out:
                    print(base64.b64encode(secret[key].encode()).decode(), end="")
            sys.exit(0)
    sys.exit(0)
    """)


@pytest.fixture
def oc(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "oc.py").write_text(STUB)
    stub = bin_dir / "oc"
    stub.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(bin_dir / "oc.py"))} "$@"\n')
    stub.chmod(0o755)
    state_file = tmp_path / "state.json"

    def run(*command, env=None, who="katya", state=None):
        if state is not None:
            state_file.write_text(json.dumps(state))
        full_env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "OC_STATE": str(state_file),
                    "OC_WHO": who, **(env or {})}
        done = subprocess.run([BASH, str(SCRIPT), "--context", "ctx", "--namespace", "ns", *command],
                              env=full_env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        current = json.loads(state_file.read_text()) if state_file.exists() else {}
        return done, current

    return run


def subjects(state, role_suffix):
    return sorted(
        (s["kind"], s["name"])
        for rb in state.get("rolebindings", {}).values()
        if rb["roleRef"]["name"].endswith(role_suffix)
        for s in rb["subjects"]
    )


def test_bootstrap_with_explicit_initial_admin_group_and_configured_groups(oc):
    done, state = oc("bootstrap", env={"MEMORYHUB_UI_INITIAL_ADMIN_GROUP": "platform-admins",
                                       "MEMORYHUB_UI_USER_GROUPS": "corp-ai, corp-research"})
    assert done.returncode == 0, done.stderr
    assert set(state["roles"]) == {"memoryhub-dashboard-user", "memoryhub-dashboard-admin",
                                   "memoryhub-ui-access-reader"}
    assert state["roles"]["memoryhub-dashboard-admin"]["rules"][0]["verbs"] == ["use", "admin"]
    assert state["roles"]["memoryhub-dashboard-user"]["rules"][0]["verbs"] == ["use"]
    assert subjects(state, "-admin") == [("Group", "platform-admins")]
    assert subjects(state, "-user") == [("Group", "corp-ai"), ("Group", "corp-research")]
    ann = state["roles"]["memoryhub-dashboard-admin"]["metadata"]["annotations"]
    assert ann["memoryhub.io/bootstrap-source"] == "initial-admin-group"
    assert ann["memoryhub.io/bootstrapped-by"] == "katya"
    reader = state["rolebindings"]["memoryhub-ui-access-reader"]
    assert reader["subjects"] == [{"kind": "ServiceAccount", "name": "memoryhub-ui", "namespace": "ns"}]


def test_bootstrap_without_terminal_or_explicit_admin_refuses(oc):
    done, state = oc("bootstrap")
    assert done.returncode != 0
    assert "MEMORYHUB_UI_INITIAL_ADMIN_GROUP" in done.stderr
    assert not subjects(state, "-admin")


def test_bootstrap_deployer_only_when_asked_and_never_a_service_account(oc):
    done, state = oc("bootstrap", env={"MEMORYHUB_UI_BOOTSTRAP_DEPLOYER": "1"})
    assert done.returncode == 0, done.stderr
    assert subjects(state, "-admin") == [("User", "katya")]
    done, _ = oc("bootstrap", env={"MEMORYHUB_UI_BOOTSTRAP_DEPLOYER": "1"}, who="system:serviceaccount:ci:bot",
                 state={})
    assert done.returncode != 0 and "no human deployer" in done.stderr


def test_bootstrap_runs_once_and_removing_every_binding_is_not_undone(oc):
    oc("bootstrap", env={"MEMORYHUB_UI_INITIAL_ADMIN_USER": "alice"})
    done, _ = oc("revoke", "--admin", "--person", "alice")
    assert done.returncode == 0, done.stderr
    assert "no Admin binding is left" in done.stdout
    done, state = oc("bootstrap", env={"MEMORYHUB_UI_INITIAL_ADMIN_USER": "mallory",
                                       "MEMORYHUB_UI_BOOTSTRAP_DEPLOYER": "1"})
    assert done.returncode == 0, done.stderr
    assert "Not re-bootstrapping" in done.stdout
    assert subjects(state, "-admin") == []


def test_bootstrap_migrates_the_legacy_lists(oc):
    legacy = {"MEMORYHUB_UI_ADMIN_USERS": "alice", "MEMORYHUB_UI_ALLOWED_USERS": "bob,carol"}
    done, state = oc("bootstrap", state={"secret": legacy})
    assert done.returncode == 0, done.stderr
    assert subjects(state, "-admin") == [("User", "alice")]
    assert subjects(state, "-user") == [("User", "bob"), ("User", "carol")]
    assert "memoryhub.io/migrated-to-rbac-at" in state["secret"]["annotations"]
    assert state["roles"]["memoryhub-dashboard-admin"]["metadata"]["annotations"][
        "memoryhub.io/bootstrap-source"] == "migrated-lists"
    again, _ = oc("migrate")
    assert again.returncode == 0 and "already migrated" in again.stdout


def test_migrate_validates_every_name_before_writing(oc):
    legacy = {"MEMORYHUB_UI_ADMIN_USERS": "alice", "MEMORYHUB_UI_ALLOWED_USERS": "bob;rm -rf"}
    done, state = oc("migrate", state={"secret": legacy})
    assert done.returncode != 0 and "Invalid OpenShift username" in done.stderr
    assert not state.get("rolebindings")


def test_grant_is_idempotent_keeps_provenance_and_revoke_removes(oc):
    done, state = oc("grant", "--user", "--group", "Data Science")
    assert done.returncode == 0, done.stderr
    (name, binding), = state["rolebindings"].items()
    assert binding["metadata"]["annotations"]["memoryhub.io/granted-by"] == "katya"
    assert binding["subjects"][0] == {"apiGroup": "rbac.authorization.k8s.io", "kind": "Group",
                                      "name": "Data Science"}
    assert name.startswith("mh-user-group-data-science-")
    again, state2 = oc("grant", "--user", "--group", "Data Science", who="someone-else")
    assert "already has user" in again.stdout
    assert state2["rolebindings"][name]["metadata"]["annotations"]["memoryhub.io/granted-by"] == "katya"
    done, state3 = oc("revoke", "--user", "--group", "Data Science")
    assert done.returncode == 0 and not state3["rolebindings"]


def test_similar_names_do_not_collide(oc):
    oc("grant", "--user", "--person", "a.b")
    _, state = oc("grant", "--user", "--person", "a_b")
    assert len(state["rolebindings"]) == 2


@pytest.mark.parametrize("command", [
    ("grant", "--admin", "--person", "al ice"),
    ("grant", "--admin", "--group", "x;y"),
    ("grant", "--admin"),
    ("grant", "--person", "alice"),
    ("revoke", "--admin", "--person", "nobody"),
    ("frobnicate",),
])
def test_bad_input_writes_nothing(oc, command):
    done, state = oc(*command)
    assert done.returncode != 0
    assert not state.get("rolebindings")


def test_list_shows_only_dashboard_bindings_and_says_they_are_assignments(oc):
    oc("grant", "--admin", "--person", "alice")
    oc("grant", "--user", "--group", "corp")
    done, _ = oc("list", state=None)
    assert done.returncode == 0, done.stderr
    assert "not expanded" in done.stdout
    assert "User:alice" in done.stdout and "Group:corp" in done.stdout


def test_delegated_mode_binds_auth_delegator_and_self_mode_removes_it(oc):
    _, state = oc("apply-roles", env={"MEMORYHUB_UI_RBAC_CHECK": "delegated"})
    assert state["crbs"] == {"delegator": True}
    _, state = oc("apply-roles")
    assert state["crbs"] == {}


def test_every_call_uses_the_explicit_context(oc, tmp_path):
    oc("bootstrap", env={"MEMORYHUB_UI_INITIAL_ADMIN_USER": "alice"})
    calls = [json.loads(line) for line in (tmp_path / "state.json.log").read_text().splitlines()]
    assert calls and all(call[:2] == ["--context", "ctx"] for call in calls)



def test_export_lists_snapshots_bindings_for_a_rollback(oc):
    oc("grant", "--admin", "--person", "alice")
    oc("grant", "--user", "--group", "Data Science")
    oc("grant", "--user", "--person", "alice")
    _, state = oc("list")
    state["groups"] = {"Data Science": ["bob", "b64:a3ViZTphZG1pbg==", "bad name"]}
    done, state = oc("export-lists", state=state)
    assert done.returncode == 0, done.stderr
    assert state["secret"]["MEMORYHUB_UI_ADMIN_USERS"] == "alice"
    assert state["secret"]["MEMORYHUB_UI_ALLOWED_USERS"] == "bob,kube:admin"
    assert state["secret"]["annotations"]["memoryhub.io/human-access-source"] == "rbac-export"
    assert "snapshot" in done.stdout and "skipping 'bad name'" in done.stdout


def test_export_lists_refuses_to_lock_out_every_admin(oc):
    oc("grant", "--user", "--person", "bob")
    done, state = oc("export-lists")
    assert done.returncode != 0 and "no Admin" in done.stderr
    assert state.get("secret") is None
