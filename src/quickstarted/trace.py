"""Run traces: an append-only event log, written as JSONL.

The trace is the product's raw material: it is what lets a failure be
attributed to the docs page the agent was reading when things went wrong.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class Event:
    ts: float
    type: str
    data: dict[str, Any]


@dataclass
class Trace:
    events: list[Event] = field(default_factory=list)
    # The egress proxy appends from its own threads while the agent loop
    # appends from the main one.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    #: Called with each event as it happens, for anything that wants to watch a
    #: run rather than read it afterwards. A run used to print nothing until it
    #: finished, so a slow model and a hung container looked identical.
    listener: Callable[[Event], None] | None = None

    def add(self, type: str, **data: Any) -> Event:
        event = Event(ts=time.time(), type=type, data=data)
        with self._lock:
            self.events.append(event)
        if self.listener is not None:
            # Never let a broken watcher take down a run that is costing money.
            with contextlib.suppress(Exception):
                self.listener(event)
        return event

    def of_type(self, *types: str) -> list[Event]:
        with self._lock:
            return [e for e in self.events if e.type in types]

    def pages_read(self) -> list[str]:
        # `docs_fetch` is what 0.4.0 wrote for the same event, so a trace from
        # that release still reads back rather than reporting no pages at all.
        return [
            e.data["url"]
            for e in self.events
            if e.type in ("docs_read", "docs_fetch")
        ]

    def last_page_read(self) -> str | None:
        urls = self.pages_read()
        return urls[-1] if urls else None

    def write_jsonl(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for e in self.events:
                fh.write(json.dumps({"ts": e.ts, "type": e.type, **e.data}) + "\n")
