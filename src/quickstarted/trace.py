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

    def session_output(self) -> str:
        """What the agent's commands printed. Never what the agent typed.

        Handed to the success check so a task can assert on what a reader would
        have seen. Many quickstarts end at a value on a terminal rather than a
        file on disk, and a check that could only look at the filesystem forced
        its author to invent an artefact the documentation never mentions.

        Two things are deliberately excluded, and both were bugs first.

        **The commands themselves.** Writing `$ {command}` above each result put
        the agent's own keystrokes in the text the check greps, and `grep` cannot
        tell a heredoc from a result. A run that wrote `INSERT INTO test VALUES
        (42)` into a file and then died on `ModuleNotFoundError` satisfied
        `expect_output: {contains: "42"}`. Three tasks in this repository were
        vacuous that way.

        **Output from commands that failed.** Otherwise a stack trace quoting
        the source line counts as the program having printed it.

        `setup` is excluded too: those commands are the harness's, not the
        reader's, so a task whose setup happens to print the expected string
        would pass without the agent doing anything.
        """
        chunks: list[str] = []
        with self._lock:
            events = list(self.events)
        for event in events:
            if event.type != "tool_result" or event.data.get("tool") != "bash":
                continue
            if event.data.get("exit_code") != 0:
                continue
            output = str(event.data.get("output", ""))
            if output:
                chunks.append(output if output.endswith("\n") else output + "\n")
        return "".join(chunks)

    def write_jsonl(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for e in self.events:
                fh.write(json.dumps({"ts": e.ts, "type": e.type, **e.data}) + "\n")
