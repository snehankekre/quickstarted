"""The harness-owned egress proxy.

Every packet an agent's shell sends leaves through here, which buys three
things the v0 design only hoped for:

1. **Enforcement.** The task's network allowlist is applied by the proxy,
   not by asking the agent nicely to use the `read_docs` tool.
2. **Attribution.** Documentation hosts are deliberately *not* reachable from
   the shell. An agent that tries `curl https://docs.example.com/...` is
   refused and the attempt is recorded, so the set of pages the agent read is
   the set the trace knows about. Failure attribution stops being a guess.
3. **Honest infrastructure signals.** A connection refused by us and a
   connection that failed upstream are different events, which is what lets a
   run be classified as a docs failure rather than a flaky network.

The split matters: `docs.allow` hosts are readable only through `read_docs`,
while `network.allow` hosts (package registries and the like) are what a
shell may talk to in order to install things.
"""

from __future__ import annotations

import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# Package registries and source hosts a quickstart legitimately needs.
DEFAULT_NETWORK_ALLOW = (
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
    "github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "crates.io",
    "static.crates.io",
    "proxy.golang.org",
)

_RELAY_CHUNK = 65536


def host_matches(host: str, entries) -> bool:
    host = (host or "").lower().strip(".")
    for entry in entries:
        entry = entry.lower().strip(".")
        if host == entry or host.endswith("." + entry):
            return True
    return False


class EgressProxy:
    """A minimal forward proxy: CONNECT tunnels plus absolute-URI HTTP."""

    #: Overridden to "0.0.0.0" when running as a sidecar for a container.
    bind_host = "127.0.0.1"

    def __init__(self, network_allow, docs_hosts=(), trace=None, explicit_allow=()):
        self.network_allow = tuple(network_allow)
        self.docs_hosts = tuple(docs_hosts)
        #: Hosts the task named under `network.allow` by hand. A host can be
        #: both documentation and a package registry (PyPI is the obvious
        #: case), and when an author says so explicitly, installs win over
        #: attribution for that host. The override is recorded, not silent.
        self.explicit_allow = tuple(explicit_allow)
        self.trace = trace
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.blocked_docs_attempts = 0

    # -- policy ---------------------------------------------------------
    def decide(self, host: str) -> tuple[bool, str]:
        """(allowed, reason). Docs hosts lose to keep attribution complete."""
        if host_matches(host, self.explicit_allow):
            return True, "explicit_network_override"
        if host_matches(host, self.docs_hosts):
            return False, "docs_host_requires_read_docs"
        if host_matches(host, self.network_allow):
            return True, "allowlisted"
        return False, "not_allowlisted"

    def record(self, event: str, **data) -> None:
        if self.trace is not None:
            self.trace.add(event, **data)

    # -- lifecycle ------------------------------------------------------
    @property
    def url(self) -> str:
        if not self._server:
            raise RuntimeError("proxy not started")
        _host, port = self._server.server_address[:2]
        return f"http://127.0.0.1:{port}"

    @property
    def port(self) -> int:
        if not self._server:
            raise RuntimeError("proxy not started")
        return int(self._server.server_address[1])

    def start(self, port: int = 0) -> str:
        proxy = self

        class Handler(_ProxyHandler):
            pass

        Handler.proxy = proxy
        self._server = ThreadingHTTPServer((self.bind_host, port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
        )
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> EgressProxy:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


class _ProxyHandler(BaseHTTPRequestHandler):
    proxy: EgressProxy
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # -- helpers --------------------------------------------------------
    def _refuse(self, host: str, reason: str, method: str) -> None:
        self.proxy.record(
            "egress_blocked", host=host, reason=reason, method=method
        )
        if reason == "docs_host_requires_read_docs":
            self.proxy.blocked_docs_attempts += 1
            body = (
                f"BLOCKED by quickstarted: {host} is a documentation host. "
                "Read documentation with the read_docs tool, not the shell, so "
                "that every page you read is recorded.\n"
            ).encode()
        else:
            allowed = ", ".join(self.proxy.network_allow) or "(none)"
            body = (
                f"BLOCKED by quickstarted: {host} is not on this task's network "
                f"allowlist ({allowed}).\n"
            ).encode()
        self.send_response(403)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _upstream_failed(self, host: str, exc: Exception, method: str) -> None:
        self.proxy.record(
            "egress_error", host=host, error=str(exc), method=method
        )
        body = f"quickstarted proxy: upstream connection to {host} failed: {exc}\n".encode()
        self.send_response(502)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    # -- CONNECT (https) -------------------------------------------------
    def do_CONNECT(self) -> None:
        target = self.path
        host, _, port_s = target.partition(":")
        port = int(port_s or 443)
        allowed, reason = self.proxy.decide(host)
        if not allowed:
            self._refuse(host, reason, "CONNECT")
            return
        try:
            upstream = socket.create_connection((host, port), timeout=30)
        except OSError as exc:
            self._upstream_failed(host, exc, "CONNECT")
            return
        self.proxy.record("egress_allowed", host=host, port=port, method="CONNECT")
        self.send_response(200, "Connection established")
        self.end_headers()
        try:
            self.wfile.flush()
        except OSError:
            upstream.close()
            return
        self._relay(self.connection, upstream)

    def _relay(self, client: socket.socket, upstream: socket.socket) -> None:
        sockets = [client, upstream]
        try:
            while True:
                readable, _, errored = select.select(sockets, [], sockets, 60)
                if errored or not readable:
                    break
                for sock in readable:
                    other = upstream if sock is client else client
                    try:
                        data = sock.recv(_RELAY_CHUNK)
                    except OSError:
                        return
                    if not data:
                        return
                    try:
                        other.sendall(data)
                    except OSError:
                        return
        finally:
            upstream.close()

    # -- plain HTTP ------------------------------------------------------
    def _forward(self) -> None:
        parsed = urlparse(self.path)
        host = parsed.hostname or ""
        if not host:
            self._refuse(host or "(relative-url)", "not_allowlisted", self.command)
            return
        allowed, reason = self.proxy.decide(host)
        if not allowed:
            self._refuse(host, reason, self.command)
            return
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        try:
            upstream = socket.create_connection((host, port), timeout=30)
        except OSError as exc:
            self._upstream_failed(host, exc, self.command)
            return
        self.proxy.record(
            "egress_allowed", host=host, port=port, method=self.command, path=path
        )
        try:
            request = [f"{self.command} {path} HTTP/1.1", f"Host: {parsed.netloc}"]
            for key, value in self.headers.items():
                if key.lower() in ("proxy-connection", "connection", "host"):
                    continue
                request.append(f"{key}: {value}")
            request.append("Connection: close")
            blob = ("\r\n".join(request) + "\r\n\r\n").encode() + body
            upstream.sendall(blob)
            while True:
                chunk = upstream.recv(_RELAY_CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except OSError:
            pass
        finally:
            upstream.close()
        self.close_connection = True

    do_GET = _forward
    do_POST = _forward
    do_HEAD = _forward
    do_PUT = _forward
    do_DELETE = _forward
    do_PATCH = _forward
