"""The egress proxy is where the allowlist stops being a request."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from quickstarted.net.proxy import EgressProxy, host_matches
from quickstarted.trace import Trace


@pytest.fixture
def upstream():
    """A real HTTP origin server to prove the proxy forwards, not just allows."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = b"upstream-ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _proxy_get(proxy_port: int, url: str) -> "tuple[int, bytes]":
    host, port = "127.0.0.1", proxy_port
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.sendall(f"GET {url} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n".encode())
        chunks = []
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
    raw = b"".join(chunks)
    status = int(raw.split(b" ", 2)[1])
    return status, raw


def test_host_matches_subdomains_but_not_suffix_collisions():
    assert host_matches("docs.example.com", ["example.com"])
    assert host_matches("example.com", ["example.com"])
    assert not host_matches("notexample.com", ["example.com"])
    assert not host_matches("example.com.evil.net", ["example.com"])


def test_docs_hosts_are_refused_to_the_shell():
    """The core attribution guarantee: docs are readable only via read_docs."""
    trace = Trace()
    proxy = EgressProxy(
        network_allow=("docs.example.com",),  # even if also network-allowed
        docs_hosts=("docs.example.com",),
        trace=trace,
    )
    allowed, reason = proxy.decide("docs.example.com")
    assert not allowed
    assert reason == "docs_host_requires_read_docs"


def test_unlisted_host_is_refused():
    proxy = EgressProxy(network_allow=("pypi.org",))
    assert proxy.decide("evil.test") == (False, "not_allowlisted")
    assert proxy.decide("pypi.org")[0] is True
    assert proxy.decide("files.pypi.org")[0] is True


def test_allowed_request_is_forwarded_and_recorded(upstream):
    trace = Trace()
    host = upstream.split(":")[0]
    with EgressProxy(network_allow=(host,), trace=trace) as proxy:
        status, raw = _proxy_get(proxy.port, f"http://{upstream}/x")
    assert status == 200
    assert b"upstream-ok" in raw
    assert [e.data["host"] for e in trace.of_type("egress_allowed")] == [host]


def test_blocked_request_is_refused_and_recorded(upstream):
    trace = Trace()
    with EgressProxy(network_allow=("pypi.org",), trace=trace) as proxy:
        status, raw = _proxy_get(proxy.port, f"http://{upstream}/x")
    assert status == 403
    assert b"BLOCKED by quickstarted" in raw
    assert b"upstream-ok" not in raw
    blocked = trace.of_type("egress_blocked")
    assert blocked and blocked[0].data["reason"] == "not_allowlisted"


def test_docs_bypass_attempt_is_counted(upstream):
    trace = Trace()
    host = upstream.split(":")[0]
    with EgressProxy(network_allow=(host,), docs_hosts=(host,), trace=trace) as proxy:
        status, _ = _proxy_get(proxy.port, f"http://{upstream}/x")
        assert status == 403
        assert proxy.blocked_docs_attempts == 1


def test_explicit_network_allow_beats_the_docs_rule():
    """PyPI can be both documentation and a registry; the author decides."""
    proxy = EgressProxy(
        network_allow=("pypi.org",),
        docs_hosts=("pypi.org",),
        explicit_allow=("pypi.org",),
    )
    allowed, reason = proxy.decide("pypi.org")
    assert allowed is True
    assert reason == "explicit_network_override"
