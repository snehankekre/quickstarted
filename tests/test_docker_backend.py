"""Docker orchestration, verified against a fake `docker` binary.

No daemon runs here. What is checked is the topology, because that is what the
enforcement claim rests on: the sandbox container must be attached only to an
`--internal` network, and the proxy sidecar must be the single container with a
route to the outside.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from quickstarted.exec import docker as docker_mod
from quickstarted.exec.docker import DockerExecutor
from quickstarted.trace import Trace

FAKE_DOCKER = """#!/usr/bin/env python3
import json, os, sys

log = os.environ["FAKE_DOCKER_LOG"]
with open(log, "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")

args = sys.argv[1:]
if args and args[0] == "logs":
    print(json.dumps({"ts": 1.0, "type": "egress_blocked", "host": "evil.test",
                      "reason": "not_allowlisted", "method": "CONNECT"}))
elif args and args[0] == "exec":
    print("fake-output")
sys.exit(0)
"""


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    path = bin_dir / "docker"
    path.write_text(FAKE_DOCKER)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    log = tmp_path / "docker.log"
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def _commands(log: Path):
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_sandbox_is_isolated_and_only_the_proxy_is_bridged(fake_docker):
    executor = DockerExecutor(
        network_allow=("pypi.org",), docs_hosts=("docs.example.com",)
    )
    try:
        commands = _commands(fake_docker)
        network = next(c for c in commands if c[:2] == ["network", "create"])
        assert "--internal" in network, "sandbox network must have no route out"

        runs = [c for c in commands if c[0] == "run"]
        proxy_run, sandbox_run = runs[0], runs[1]

        # Exactly one container gets bridged, and it is the proxy.
        connects = [c for c in commands if c[:2] == ["network", "connect"]]
        assert len(connects) == 1
        assert connects[0][2] == "bridge"
        assert connects[0][3] == executor.proxy_name

        assert executor.container in sandbox_run
        assert "bridge" not in sandbox_run
        assert sandbox_run[sandbox_run.index("--network") + 1] == executor.network

        # Policy reaches the sidecar as configuration, not as trust.
        assert "QUICKSTARTED_NETWORK_ALLOW=pypi.org" in proxy_run
        assert "QUICKSTARTED_DOCS_HOSTS=docs.example.com" in proxy_run
    finally:
        executor.cleanup()


def test_sandbox_container_is_dropped_of_privileges(fake_docker):
    executor = DockerExecutor()
    try:
        sandbox_run = [c for c in _commands(fake_docker) if c[0] == "run"][1]
        assert sandbox_run[sandbox_run.index("--cap-drop") + 1] == "ALL"
        assert "no-new-privileges" in sandbox_run
    finally:
        executor.cleanup()


def test_proxy_traffic_is_visible_to_the_shell_via_env(fake_docker):
    executor = DockerExecutor()
    try:
        sandbox_run = [c for c in _commands(fake_docker) if c[0] == "run"][1]
        proxy_url = f"http://{executor.proxy_name}:{docker_mod.PROXY_PORT}"
        assert f"HTTP_PROXY={proxy_url}" in sandbox_run
        assert f"https_proxy={proxy_url}" in sandbox_run
    finally:
        executor.cleanup()


def test_commands_run_inside_the_container(fake_docker):
    executor = DockerExecutor()
    try:
        result = executor.run("echo hi", timeout=10)
        assert result.exit_code == 0
        assert "fake-output" in result.output
        exec_cmd = [c for c in _commands(fake_docker) if c[0] == "exec"][-1]
        assert executor.container in exec_cmd
        assert exec_cmd[-3:] == ["bash", "-c", "echo hi"]
    finally:
        executor.cleanup()


def test_sidecar_events_are_merged_into_the_trace(fake_docker):
    trace = Trace()
    executor = DockerExecutor(trace=trace)
    executor.cleanup()  # collects logs on teardown
    blocked = trace.of_type("egress_blocked")
    assert blocked and blocked[0].data["host"] == "evil.test"


def test_teardown_removes_containers_and_network(fake_docker):
    executor = DockerExecutor()
    names = (executor.container, executor.proxy_name, executor.network)
    executor.cleanup()
    commands = _commands(fake_docker)
    removed = {c[-1] for c in commands if c[:2] == ["rm", "-f"]}
    assert {names[0], names[1]} <= removed
    assert ["network", "rm", names[2]] in commands


# -- live daemon -------------------------------------------------------
# These need a real Docker daemon. They deliberately do NOT need the public
# internet: the proxy refuses a blocked host before it resolves or dials it.

docker_only = pytest.mark.skipif(
    not docker_mod.available(), reason="needs a running Docker daemon"
)

PROBE = r'''
python3 - <<"EOF"
import socket, urllib.request, urllib.error

def via_proxy(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            print("proxy", r.status)
    except urllib.error.HTTPError as e:
        print("proxy", e.code)
    except Exception as e:
        print("proxy", type(e).__name__, e)

def direct(host, port=443):
    try:
        socket.create_connection((host, port), timeout=10).close()
        print("direct CONNECTED")
    except Exception as e:
        print("direct", type(e).__name__)

via_proxy("https://docs.example.com/page")
direct("93.184.215.14")
EOF
'''


@docker_only
def test_live_container_cannot_leave_except_through_the_proxy():
    trace = Trace()
    executor = DockerExecutor(
        network_allow=("pypi.org",), docs_hosts=("docs.example.com",), trace=trace
    )
    try:
        output = executor.run(PROBE, timeout=180).output
    finally:
        executor.cleanup()

    # Refused by policy, with the reason, rather than by accident. A refused
    # CONNECT is not an HTTP response, so urllib reports it as a URLError
    # wrapping the tunnel's status rather than as an HTTPError.
    assert "403" in output, output
    # No route to the internet at all: not merely no DNS.
    assert "direct OSError" in output, output
    blocked = [e.data for e in trace.of_type("egress_blocked")]
    assert any(
        b["host"] == "docs.example.com"
        and b["reason"] == "docs_host_requires_read_docs"
        for b in blocked
    ), blocked


@docker_only
@pytest.mark.skipif(
    not os.environ.get("QUICKSTARTED_NETWORK_TESTS"), reason="hits the network"
)
def test_live_container_reaches_an_allowlisted_registry():
    trace = Trace()
    executor = DockerExecutor(network_allow=("pypi.org",), trace=trace)
    try:
        out = executor.run(
            'python3 -c "import urllib.request;'
            "print('status', urllib.request.urlopen('https://pypi.org/simple/',"
            ' timeout=30).status)"',
            timeout=120,
        ).output
    finally:
        executor.cleanup()
    assert "status 200" in out, out
    assert any(e.data["host"] == "pypi.org" for e in trace.of_type("egress_allowed"))
