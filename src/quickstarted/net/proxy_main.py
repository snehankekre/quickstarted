"""Entrypoint for running the egress proxy as a sidecar container.

Kept dependency-free and importable as a bare script so it can run in a stock
`python:*-alpine` image with only this directory mounted: the sidecar must not
need quickstarted's own dependencies installed.

Events are written to stdout as JSONL; the harness collects them with
`docker logs` and merges them into the run trace.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from proxy import EgressProxy


class StdoutTrace:
    """Duck-types Trace.add, emitting one JSON object per event."""

    def add(self, type: str, **data) -> None:
        sys.stdout.write(json.dumps({"ts": time.time(), "type": type, **data}) + "\n")
        sys.stdout.flush()


def _hosts(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    return tuple(h for h in (x.strip() for x in raw.split(",")) if h)


def main() -> int:
    port = int(os.environ.get("QUICKSTARTED_PROXY_PORT", "8080"))
    proxy = EgressProxy(
        network_allow=_hosts("QUICKSTARTED_NETWORK_ALLOW"),
        docs_hosts=_hosts("QUICKSTARTED_DOCS_HOSTS"),
        trace=StdoutTrace(),
    )
    # Bind on all interfaces inside the sidecar so the sandbox container can
    # reach it; the container is on an internal network with no route out.
    proxy.bind_host = "0.0.0.0"
    proxy.start(port=port)
    threading.Event().wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
