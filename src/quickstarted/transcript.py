"""Reading a run back: a terminal transcript, and a page you can send someone.

The trace holds everything worth knowing about a run and nobody outside this
repository reads JSONL. Both renderers here are lossy on purpose. They answer
"what did the agent do, and where was it when it stopped", which is the question
a documentation maintainer has; `jq` over the trace answers the rest.

The HTML is one file with no external anything. A report that fetches a
stylesheet is a report that renders differently for the person you sent it to,
and eventually not at all.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

_MAX_OUTPUT = 1200


class TranscriptError(ValueError):
    """Raised when a trace file cannot be read."""


def load_trace(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        raise TranscriptError(f"{path}: no such file")
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError as exc:
            raise TranscriptError(f"{path}: line {number} is not JSON: {exc}") from exc
    if not events:
        raise TranscriptError(f"{path}: no events")
    return events


def _clip(text: str, limit: int = _MAX_OUTPUT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... {len(text) - limit} more characters ...]"


def _elapsed(events: list[dict], event: dict) -> float:
    return event.get("ts", 0) - events[0].get("ts", 0)


def render_text(events: list[dict], verbose: bool = False) -> str:
    """The run as a reader would narrate it."""
    lines = []
    for event in events:
        kind = event.get("type")
        stamp = f"[{_elapsed(events, event):6.1f}s]"
        if kind == "run_start":
            lines.append(
                f"{stamp} {event.get('task')} on {event.get('backend')}"
                f"{'' if event.get('enforced') else ' (UNENFORCED)'}"
                f", agent {event.get('agent')}, attempt {event.get('attempt')}"
            )
        elif kind == "setup":
            lines.append(f"{stamp} setup: {event.get('command')}")
        elif kind in ("docs_read", "docs_fetch"):
            note = " (cached)" if event.get("from_cache") else ""
            if event.get("truncated"):
                note += (
                    f" TRUNCATED from {event.get('original_chars')} to "
                    f"{event.get('chars')} chars"
                )
            lines.append(f"{stamp} read {event.get('url')}{note}")
        elif kind in ("docs_read_blocked", "fetch_blocked", "affordance_withheld"):
            reason = event.get("reason", "withheld")
            lines.append(f"{stamp} BLOCKED {event.get('url')} ({reason})")
        elif kind == "egress_blocked":
            lines.append(
                f"{stamp} shell blocked from {event.get('host')} "
                f"({event.get('reason')})"
            )
        elif kind == "tool_call" and event.get("tool") == "bash":
            lines.append(f"{stamp} $ {event.get('command')}")
        elif kind == "tool_result" and event.get("tool") == "bash":
            exit_code = event.get("exit_code")
            output = _clip(event.get("output", ""), 400 if not verbose else _MAX_OUTPUT)
            lines.append(f"{stamp}   exit {exit_code}")
            if output and (verbose or exit_code != 0):
                lines.extend(f"           | {row}" for row in output.splitlines())
        elif kind == "agent_final":
            lines.append(f"{stamp} agent says: {_clip(event.get('text', ''), 500)}")
        elif kind == "success_check":
            lines.append(f"{stamp} success check exited {event.get('exit_code')}")
            for row in _clip(event.get("output", "")).splitlines():
                lines.append(f"           | {row}")
        elif kind == "run_end":
            lines.append(
                f"{stamp} {event.get('classification')} "
                f"(stop reason: {event.get('stop_reason')})"
            )
    return "\n".join(lines)


_CSS = """
:root { color-scheme: light dark; --fg:#111; --bg:#fff; --rule:#e2e2e0;
  --muted:#666; --pass:#1a7f4b; --fail:#b3261e; --surface:#fbfbfa; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e8e8e6; --bg:#16181c; --rule:#33363c; --muted:#9a9a99;
    --pass:#5bd18e; --fail:#ff8a80; --surface:#1d2025; }
}
* { box-sizing: border-box; }
body { margin:0 auto; padding:2rem 1.25rem 4rem; max-width:64rem; color:var(--fg);
  background:var(--bg); font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",sans-serif; }
h1 { font-size:1.5rem; letter-spacing:-0.02em; margin:0 0 .25rem; }
h2 { font-size:1.05rem; letter-spacing:-0.015em; margin:2.5rem 0 .75rem;
  padding-bottom:.3rem; border-bottom:1px solid var(--rule); }
h3 { font-size:.92rem; margin:1.5rem 0 .4rem; }
.sub { color:var(--muted); margin:0 0 1.5rem; }
table { border-collapse:collapse; width:100%; font-size:.83rem;
  border:1px solid var(--rule); border-radius:4px; overflow:hidden; }
th,td { text-align:left; padding:.45rem .6rem; border-bottom:1px solid var(--rule); }
th { background:var(--surface); font-weight:600; }
tr:last-child td { border-bottom:0; }
.pass { color:var(--pass); font-weight:600; }
.fail { color:var(--fail); font-weight:600; }
.muted { color:var(--muted); }
pre { background:var(--surface); border:1px solid var(--rule); border-radius:4px;
  padding:.7rem .8rem; overflow-x:auto; font-size:.76rem; line-height:1.5;
  font-family:ui-monospace,"JetBrains Mono",SFMono-Regular,monospace; }
.page { font-family:ui-monospace,SFMono-Regular,monospace; font-size:.78rem;
  word-break:break-all; }
details { border:1px solid var(--rule); border-radius:4px; padding:.5rem .7rem;
  margin:.6rem 0; }
summary { cursor:pointer; font-size:.85rem; font-weight:600; }
"""


def _rows(document: dict) -> str:
    rows = []
    for task in document.get("tasks", []):
        rate = task.get("pass_rate")
        if task.get("skipped") and not task.get("evidential_runs"):
            shown = '<span class="muted">skipped</span>'
        elif rate is None:
            shown = '<span class="muted">no evidence</span>'
        else:
            css = "pass" if rate == 1 else "fail"
            shown = f'<span class="{css}">{rate:.0%}</span>'
        discarded = task.get("discarded") or {}
        summary = ", ".join(f"{k}={v}" for k, v in sorted(discarded.items())) or "-"
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(task.get('task', '')))}</td>"
            f"<td>{html.escape(str(task.get('agent', '')))}</td>"
            f"<td>{shown}</td>"
            f"<td>{task.get('passes', 0)}/{task.get('evidential_runs', 0)}</td>"
            f'<td class="muted">{html.escape(summary)}</td>'
            "</tr>"
        )
    return "\n".join(rows)


def _failures(document: dict) -> str:
    blocks = []
    for task in document.get("tasks", []):
        for run in task.get("runs", []):
            if run.get("classification") != "docs_gap":
                continue
            check = run.get("success_check") or {}
            output = _clip(check.get("output", "")) or "(the check printed nothing)"
            suspect = run.get("suspect_page")
            pages = run.get("docs_pages_read") or []
            blocks.append(
                f"<h3>{html.escape(str(task.get('task')))}, attempt "
                f"{run.get('attempt')}</h3>"
                + (
                    f'<p>Last page read before failing: <span class="page">'
                    f"{html.escape(suspect)}</span></p>"
                    if suspect
                    else ""
                )
                + f"<pre>{html.escape(output)}</pre>"
                + (
                    "<details><summary>Pages read ("
                    + str(len(pages))
                    + ")</summary><ol>"
                    + "".join(
                        f'<li class="page">{html.escape(str(u))}</li>' for u in pages
                    )
                    + "</ol></details>"
                    if pages
                    else ""
                )
            )
    if not blocks:
        return '<p class="muted">No documentation gaps in this run.</p>'
    return "\n".join(blocks)


def render_html(document: dict, transcripts: dict[str, str] | None = None) -> str:
    """A self-contained page: pass rates, every failure, and the transcripts."""
    totals = document.get("totals") or {}
    environment = document.get("environment") or {}
    cost = totals.get("estimated_cost_usd")
    unpriced = totals.get("unpriced_models") or []
    meta = [
        f"{len(document.get('tasks', []))} task(s)",
        f"repeat {document.get('repeat', 1)}",
        f"backend {environment.get('backend', 'unknown')}",
        f"quickstarted {document.get('quickstarted_version', '')}",
    ]
    if cost is not None:
        meta.append(f"estimated ${cost:.4f}")
    notes = []
    if document.get("interrupted"):
        notes.append(
            "<p><strong>Interrupted.</strong> These are the runs that finished. "
            "Attempts that never started are absent, not failed.</p>"
        )
    if unpriced:
        notes.append(
            "<p class=\"muted\">No published price for "
            + html.escape(", ".join(unpriced))
            + ", so those runs are not in the cost.</p>"
        )
    meta.append(str(document.get("generated_at", "")))
    # Escape each part, then join with the separator. Escaping the joined string
    # would turn the entity's own ampersand into &amp; and print it literally.
    body = [
        "<h1>quickstarted</h1>",
        '<p class="sub">'
        + " &middot; ".join(html.escape(part) for part in meta if part)
        + "</p>",
        *notes,
        "<h2>Pass rates</h2>",
        "<table><thead><tr><th>Task</th><th>Agent</th><th>Pass rate</th>"
        "<th>Evidential</th><th>Discarded</th></tr></thead><tbody>",
        _rows(document),
        "</tbody></table>",
        "<h2>Where it failed</h2>",
        _failures(document),
    ]
    if transcripts:
        body.append("<h2>Transcripts</h2>")
        for name, text in sorted(transcripts.items()):
            body.append(
                f"<details><summary>{html.escape(name)}</summary>"
                f"<pre>{html.escape(text)}</pre></details>"
            )
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>quickstarted report</title>"
        f"<style>{_CSS}</style></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )
