"""Reading a run back: the transcript, and the page you can send someone."""

import json

import pytest

from quickstarted.transcript import (
    TranscriptError,
    load_trace,
    render_html,
    render_text,
)

EVENTS = [
    {"ts": 100.0, "type": "run_start", "task": "t", "agent": "claude",
     "backend": "docker", "enforced": True, "attempt": 1},
    {"ts": 101.0, "type": "setup", "command": "python3 -m venv .venv", "exit_code": 0},
    {"ts": 103.0, "type": "docs_fetch", "url": "https://example.com/", "chars": 10},
    {"ts": 104.0, "type": "tool_call", "tool": "bash", "command": "pip install thing"},
    {"ts": 106.0, "type": "tool_result", "tool": "bash", "exit_code": 1,
     "output": "could not find thing"},
    {"ts": 107.0, "type": "egress_blocked", "host": "docs.example.com",
     "reason": "docs_host_requires_read_docs"},
    {"ts": 108.0, "type": "success_check", "exit_code": 1,
     "output": "check failed: nothing was built"},
    {"ts": 108.5, "type": "run_end", "stop_reason": "completed",
     "classification": "docs_gap"},
]


def test_a_transcript_reads_in_order_with_elapsed_time():
    text = render_text(EVENTS)
    assert "[   0.0s] t on docker, agent claude, attempt 1" in text
    assert "[   3.0s] read https://example.com/" in text
    assert "$ pip install thing" in text
    assert "shell blocked from docs.example.com" in text
    assert "check failed: nothing was built" in text
    assert text.strip().endswith("docs_gap (stop reason: completed)")


def test_output_of_a_failing_command_shows_without_verbose():
    """A command that failed is the interesting one; a quiet one is noise."""
    assert "could not find thing" in render_text(EVENTS)


def test_a_successful_command_stays_quiet_until_asked():
    events = [dict(e) for e in EVENTS]
    events[4] = {**events[4], "exit_code": 0, "output": "installed fine"}
    assert "installed fine" not in render_text(events)
    assert "installed fine" in render_text(events, verbose=True)


def test_an_unenforced_backend_is_called_out():
    events = [{**EVENTS[0], "enforced": False}]
    assert "(UNENFORCED)" in render_text(events)


def test_a_missing_or_empty_trace_is_reported(tmp_path):
    with pytest.raises(TranscriptError, match="no such file"):
        load_trace(tmp_path / "nope.jsonl")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n")
    with pytest.raises(TranscriptError, match="no events"):
        load_trace(empty)


def test_a_corrupt_line_names_its_line_number(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text('{"ts":1,"type":"run_start"}\nnot json\n')
    with pytest.raises(TranscriptError, match="line 2"):
        load_trace(path)


DOCUMENT = {
    "schema_version": "2.0",
    "quickstarted_version": "0.5.0",
    "generated_at": "2026-08-01T00:00:00Z",
    "repeat": 1,
    "environment": {"backend": "docker"},
    "totals": {"estimated_cost_usd": 1.5, "unpriced_models": ["claude:claude-opus-5"]},
    "tasks": [{
        "task": "t", "agent": "claude", "passes": 0, "evidential_runs": 1,
        "pass_rate": 0.0, "discarded": {}, "skipped": 0,
        "runs": [{
            "attempt": 1, "classification": "docs_gap",
            "suspect_page": "https://example.com/page",
            "docs_pages_read": ["https://example.com/page"],
            "success_check": {"exit_code": 1, "output": "check failed: no app.py"},
        }],
    }],
}


def test_the_html_report_is_self_contained():
    """A report that fetches a stylesheet renders differently for the recipient."""
    page = render_html(DOCUMENT)
    for marker in ("<script src", "<link rel=\"stylesheet\"", "@import", "src=\"http"):
        assert marker not in page
    assert "<style>" in page


def test_the_html_report_carries_the_failure_and_the_page():
    page = render_html(DOCUMENT, {"t": render_text(EVENTS)})
    assert "check failed: no app.py" in page
    assert "https://example.com/page" in page
    assert "Transcripts" in page


def test_the_html_report_says_what_the_cost_excludes():
    assert "No published price for" in render_html(DOCUMENT)


def test_the_html_report_flags_an_interrupted_sweep():
    assert "Interrupted." in render_html({**DOCUMENT, "interrupted": True})


def test_html_is_escaped_but_entities_still_render():
    document = json.loads(json.dumps(DOCUMENT))
    document["tasks"][0]["task"] = "<script>alert(1)</script>"
    page = render_html(document)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    # The separator is a real entity, not the literal text.
    assert "&amp;middot;" not in page
