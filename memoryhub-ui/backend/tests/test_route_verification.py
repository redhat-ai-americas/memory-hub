"""The deployment verifies the public Route's TLS chain in the selected context."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "verify-route.sh"


@pytest.fixture
def route(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    scripts = {
        "oc": '''import json, os, sys
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps({"tool": "oc", "args": sys.argv[1:]}) + "\\n")
sys.stdout.write(os.environ.get("TEST_INGRESS_CA", ""))
''',
        "curl": '''import json, os, pathlib, stat, sys
args = sys.argv[1:]
record = {"tool": "curl", "args": args}
if "--cacert" in args:
    path = pathlib.Path(args[args.index("--cacert") + 1])
    record.update(ca=path.read_text(), mode=stat.S_IMODE(path.stat().st_mode))
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps(record) + "\\n")
sys.stdout.write(os.environ.get("TEST_HTTP_CODE", "200"))
sys.exit(int(os.environ.get("TEST_CURL_EXIT", "0")))
''',
        "sleep": "import sys\nsys.exit(0)\n",
    }
    for name, source in scripts.items():
        python_file = bin_dir / f"{name}.py"
        python_file.write_text(source)
        command = bin_dir / name
        command.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(python_file))} \"$@\"\n")
        command.chmod(0o755)

    def run(**env):
        full_env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "TEST_LOG": str(log), **env}
        done = subprocess.run(["/bin/bash", str(SCRIPT), "--context", "selected", "--host", "dash.apps.test"],
                              env=full_env, capture_output=True, text=True, timeout=30)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return done, calls

    return run


def test_ingress_ca_comes_from_explicit_context_and_temp_file_is_removed(route):
    done, calls = route(TEST_INGRESS_CA="TRUSTED INGRESS CA\n")
    assert done.returncode == 0, done.stderr
    oc, curl = calls
    assert oc["tool"] == "oc" and "default-ingress-cert" in oc["args"]
    assert oc["args"][oc["args"].index("--context") + 1] == "selected"
    assert oc["args"][oc["args"].index("-n") + 1] == "openshift-config-managed"
    assert curl["ca"] == "TRUSTED INGRESS CA\n" and curl["mode"] == 0o600
    assert not Path(curl["args"][curl["args"].index("--cacert") + 1]).exists()
    assert curl["args"][-1] == "https://dash.apps.test/healthz"
    assert "-k" not in curl["args"] and "--insecure" not in curl["args"]


def test_explicit_route_ca_is_preserved_and_needs_no_cluster_read(route, tmp_path):
    ca = tmp_path / "custom.pem"
    ca.write_text("CUSTOM CA")
    done, calls = route(MEMORYHUB_ROUTE_CA_FILE=str(ca))
    assert done.returncode == 0, done.stderr
    assert [call["tool"] for call in calls] == ["curl"]
    assert calls[0]["ca"] == "CUSTOM CA" and ca.read_text() == "CUSTOM CA"


def test_missing_ingress_ca_uses_system_trust_without_disabling_tls(route):
    done, calls = route()
    assert done.returncode == 0, done.stderr
    args = calls[-1]["args"]
    assert "--cacert" not in args and "-k" not in args and "--insecure" not in args


@pytest.mark.parametrize("env", [{"TEST_HTTP_CODE": "503"}, {"TEST_CURL_EXIT": "60"}])
def test_http_or_certificate_failure_cannot_report_a_healthy_route(route, env):
    done, calls = route(**env)
    assert done.returncode != 0
    assert "TLS verification enabled" in done.stderr
    assert len([call for call in calls if call["tool"] == "curl"]) == 12


def test_unreadable_explicit_ca_fails_before_any_connection(route, tmp_path):
    done, calls = route(MEMORYHUB_ROUTE_CA_FILE=str(tmp_path / "missing.pem"))
    assert done.returncode != 0
    assert "not readable" in done.stderr and calls == []
