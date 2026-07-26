"""Execution backends, and whether their isolation claims survive contact."""

import os
from pathlib import Path

import pytest

from quickstarted.exec import (
    LocalExecutor,
    available_backends,
    make_executor,
    needs_host_proxy,
    resolve_backend,
)
from quickstarted.exec.base import ExecutorError
from quickstarted.exec.seatbelt import SeatbeltExecutor, build_profile
from quickstarted.exec.seatbelt import available as seatbelt_available
from quickstarted.net.proxy import EgressProxy
from quickstarted.trace import Trace

darwin_only = pytest.mark.skipif(
    not seatbelt_available(), reason="seatbelt backend needs macOS sandbox-exec"
)


def test_local_executor_is_marked_unenforced():
    ex = LocalExecutor()
    try:
        assert ex.enforced is False
    finally:
        ex.cleanup()


def test_auto_prefers_an_enforced_backend():
    resolved = resolve_backend("auto")
    enforced_available = [b for b in available_backends() if b != "local"]
    if enforced_available:
        assert resolved != "local"
    assert resolved in available_backends()


def test_unknown_backend_rejected():
    with pytest.raises(ExecutorError):
        resolve_backend("vm")


def test_docker_runs_its_own_proxy():
    assert needs_host_proxy("docker") is False
    assert needs_host_proxy("seatbelt") is True


def test_profile_denies_home_and_limits_network():
    profile = build_profile(Path("/tmp/ws"), 9999, Path("/Users/someone"))
    assert '(deny file-read* (subpath "/Users/someone"))' in profile
    assert '(allow network-outbound (remote ip "localhost:9999"))' in profile
    assert "(deny default)" in profile


def test_profile_without_proxy_grants_no_network():
    profile = build_profile(Path("/tmp/ws"), None, Path("/Users/someone"))
    assert "network-outbound" not in profile


@darwin_only
def test_seatbelt_confines_reads_and_writes():
    ex = SeatbeltExecutor()
    try:
        assert ex.enforced is True
        assert ex.run("echo hi > f.txt && cat f.txt", timeout=30).output.strip() == "hi"
        home = os.path.expanduser("~")
        denied = ex.run(f"ls {home} >/dev/null 2>&1; echo exit=$?", timeout=30)
        assert denied.output.strip() == "exit=1"
    finally:
        ex.cleanup()


@darwin_only
@pytest.mark.skipif(not os.environ.get("QUICKSTARTED_NETWORK_TESTS"), reason="hits the network")
def test_seatbelt_blocks_egress_that_skips_the_proxy():
    trace = Trace()
    proxy = EgressProxy(network_allow=("pypi.org",), docs_hosts=("docs.example.com",), trace=trace)
    proxy.start()
    ex = make_executor("seatbelt", proxy_url=proxy.url)
    try:
        direct = ex.run(
            "curl -s --noproxy '*' -o /dev/null -w '%{http_code}' https://example.com/; echo \" exit=$?\"",
            timeout=60,
        )
        assert "exit=7" in direct.output  # kernel refused the connection
    finally:
        ex.cleanup()
        proxy.stop()


@darwin_only
def test_seatbelt_scrubs_the_environment():
    ex = make_executor("seatbelt", proxy_url="http://127.0.0.1:9")
    try:
        out = ex.run("env | sort", timeout=30).output
        assert "QUICKSTARTED_ANTHROPIC_API_KEY" not in out
        assert "ANTHROPIC_API_KEY" not in out
        assert "HTTP_PROXY=http://127.0.0.1:9" in out
    finally:
        ex.cleanup()


def test_loopback_bypasses_the_proxy():
    """Journeys start a local server and then query it.

    Without NO_PROXY the request goes to the harness proxy, which refuses
    localhost as an unlisted host, and a working journey fails on policy.
    """
    ex = LocalExecutor(proxy_url="http://127.0.0.1:9")
    try:
        env = ex.env()
        assert env["NO_PROXY"] == "localhost,127.0.0.1,::1"
        assert env["no_proxy"] == env["NO_PROXY"]
    finally:
        ex.cleanup()


def test_no_proxy_is_absent_without_a_proxy():
    ex = LocalExecutor()
    try:
        assert "NO_PROXY" not in ex.env()
    finally:
        ex.cleanup()
