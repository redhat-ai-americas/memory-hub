"""Scenarios for memoryhub-ui/deploy/human-access.sh, run against a stub `oc`.

No cluster is touched. On macOS run these with the system shell to cover
Bash 3.2:  HUMAN_ACCESS_BASH=/bin/bash pytest tests/test_human_access_script.py
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

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "human-access.sh"
BASH = os.environ.get("HUMAN_ACCESS_BASH", "bash")

# The stub records each call and keeps the Secret in a JSON file. It runs via a
# /bin/sh wrapper: a shebang cannot hold a path with spaces (such as a checkout
# under "~/ui for memoryhub"), so the Python path is quoted in the wrapper instead.
STUB = textwrap.dedent("""\
    import base64, json, os, sys
    state = os.environ["OC_STATE"]
    args = sys.argv[1:]
    with open(state + ".log", "a") as log:
        log.write(json.dumps(args) + "\\n")
    secret = json.load(open(state)) if os.path.exists(state) else None
    if "whoami" in args:
        print(os.environ.get("OC_WHO", "katya")); sys.exit(0)
    if args[:2] == ["get", "secret"] or (len(args) > 3 and args[2:4] == ["get", "secret"]):
        if secret is None:
            sys.exit(1)
        path = next((a for a in args if a.startswith("jsonpath=")), "")
        for key in ("MEMORYHUB_UI_ADMIN_USERS", "MEMORYHUB_UI_ALLOWED_USERS"):
            if key in path:
                sys.stdout.write(base64.b64encode(secret[key].encode()).decode())
        sys.exit(0)
    if "create" in args:
        data = dict(a.split("=", 1)[1].split("=", 1) for a in args if a.startswith("--from-literal="))
        json.dump(data, open(state, "w"))
        print("kind: Secret"); sys.exit(0)
    if "apply" in args:
        sys.stdin.read(); sys.exit(0)
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
    state = tmp_path / "secret.json"

    def run(env=None, existing=None, who="katya"):
        if existing is not None:
            state.write_text(json.dumps(existing))
        full_env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "OC_STATE": str(state),
                    "OC_WHO": who, **(env or {})}
        done = subprocess.run([BASH, str(SCRIPT), "--context", "ctx", "--namespace", "ns"],
                              env=full_env, capture_output=True, text=True, timeout=60)
        secret = json.loads(state.read_text()) if state.exists() else None
        log = state.with_name(state.name + ".log")
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return done, secret, calls

    return run


def test_clean_install_makes_the_deployer_the_first_admin(oc):
    done, secret, calls = oc()
    assert done.returncode == 0, done.stderr
    assert secret == {"MEMORYHUB_UI_ADMIN_USERS": "katya", "MEMORYHUB_UI_ALLOWED_USERS": ""}
    annotate = next(c for c in calls if "annotate" in c)
    assert "memoryhub.io/human-access-updated-by=katya" in annotate
    assert "memoryhub.io/human-access-source=bootstrap-deployer" in annotate


def test_admins_only_with_empty_users(oc):
    """The case that failed on macOS Bash 3.2 (empty array under set -u)."""
    done, secret, _ = oc({"MEMORYHUB_UI_ADMIN_USERS": "alice"})
    assert done.returncode == 0, done.stderr
    assert secret == {"MEMORYHUB_UI_ADMIN_USERS": "alice", "MEMORYHUB_UI_ALLOWED_USERS": ""}


def test_lists_are_trimmed_and_deduplicated(oc):
    done, secret, _ = oc({"MEMORYHUB_UI_ADMIN_USERS": " alice, bob@corp.com ,alice,",
                          "MEMORYHUB_UI_ALLOWED_USERS": "carol"})
    assert done.returncode == 0, done.stderr
    assert secret == {"MEMORYHUB_UI_ADMIN_USERS": "alice,bob@corp.com", "MEMORYHUB_UI_ALLOWED_USERS": "carol"}
    assert "2 admin(s), 1 user(s)" in done.stdout


def test_users_only_is_accepted(oc):
    done, secret, _ = oc({"MEMORYHUB_UI_ALLOWED_USERS": "carol"})
    assert done.returncode == 0, done.stderr
    assert secret == {"MEMORYHUB_UI_ADMIN_USERS": "", "MEMORYHUB_UI_ALLOWED_USERS": "carol"}


def test_existing_secret_is_kept_without_input(oc):
    existing = {"MEMORYHUB_UI_ADMIN_USERS": "alice", "MEMORYHUB_UI_ALLOWED_USERS": "carol,dan"}
    done, secret, calls = oc(existing=existing)
    assert done.returncode == 0, done.stderr
    assert secret == existing
    assert "keeping existing" in done.stdout and "1 admin(s), 2 user(s)" in done.stdout
    assert not any("create" in c or "annotate" in c for c in calls)


@pytest.mark.parametrize("env, message", [
    ({"MEMORYHUB_UI_ADMIN_USERS": "al ice"}, "Invalid OpenShift username"),
    ({"MEMORYHUB_UI_ADMIN_USERS": "alice;rm"}, "Invalid OpenShift username"),
    ({"MEMORYHUB_UI_ADMIN_USERS": "", "MEMORYHUB_UI_ALLOWED_USERS": " , "}, "both human access lists are empty"),
])
def test_bad_input_writes_nothing(oc, env, message):
    done, secret, calls = oc(env)
    assert calls, "the stub oc never ran: " + done.stderr
    assert done.returncode != 0
    assert message in done.stdout + done.stderr
    assert secret is None


def test_a_service_account_cannot_become_the_first_admin(oc):
    done, secret, calls = oc(who="system:serviceaccount:ci:deployer")
    assert ["--context", "ctx", "whoami"] in calls, "the stub oc never ran: " + done.stderr
    assert done.returncode != 0
    assert "no human deployer" in done.stdout
    assert secret is None
