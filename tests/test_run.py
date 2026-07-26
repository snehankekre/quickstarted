"""End-to-end harness tests using the replay agent. No network, no API key:
docs fetches are injected via http_get."""

import textwrap

from quickstarted.agents.base import Toolbelt
from quickstarted.agents.replay import ReplayAgent
from quickstarted.report import console_summary, markdown_report
from quickstarted.run import run_task
from quickstarted.task import load_task


def fake_http_get(url, timeout=30):
    return "text/html", "<html><body><h1>Docs</h1><p>pip install thing</p></body></html>"


def make_task(tmp_path, success="test -f done.txt", replay=("echo x > done.txt",)):
    replay_yaml = "\n".join(f"  - {c!r}" for c in replay)
    text = textwrap.dedent(
        f"""
        name: t
        goal: create done.txt
        docs:
          entrypoint: https://example.com/docs/
        success:
          script: {success!r}
        budgets:
          max_seconds: 60
          max_command_seconds: 30
        replay:
        {replay_yaml}
        """
    )
    path = tmp_path / "t.yaml"
    path.write_text(text)
    return load_task(path)


def test_replay_pass(tmp_path):
    task = make_task(tmp_path)
    result = run_task(task, ReplayAgent(), http_get=fake_http_get, backend="local")
    assert result.passed
    assert result.outcome.stop_reason == "completed"
    # entrypoint was fetched and recorded
    assert result.trace.fetched_urls() == ["https://example.com/docs/"]
    assert "PASS" in console_summary(result)


def test_replay_fail_scores_fail_and_attributes(tmp_path):
    task = make_task(tmp_path, replay=("false",))
    result = run_task(task, ReplayAgent(), http_get=fake_http_get, backend="local")
    assert not result.passed
    assert result.outcome.stop_reason == "command_failed"
    assert result.suspect_page == "https://example.com/docs/"
    md = markdown_report(result)
    assert "FAIL" in md
    assert "Where to look first" in md


def test_agent_lies_scoring_is_deterministic(tmp_path):
    """Agent 'completes' but the artifact is missing: score must be FAIL."""
    task = make_task(tmp_path, replay=("echo pretending I made done.txt",))
    result = run_task(task, ReplayAgent(), http_get=fake_http_get, backend="local")
    assert result.outcome.stop_reason == "completed"
    assert not result.passed


def test_setup_failure_short_circuits(tmp_path):
    text = textwrap.dedent(
        """
        name: t
        goal: g
        docs:
          entrypoint: https://example.com/
        setup:
          - "false"
        success:
          script: "true"
        replay:
          - "true"
        """
    )
    path = tmp_path / "t.yaml"
    path.write_text(text)
    task = load_task(path)
    result = run_task(task, ReplayAgent(), http_get=fake_http_get, backend="local")
    assert not result.passed
    assert result.outcome.stop_reason == "error"
    assert "setup" in result.outcome.detail


def test_trace_jsonl_written(tmp_path):
    task = make_task(tmp_path)
    result = run_task(task, ReplayAgent(), http_get=fake_http_get, backend="local")
    out = tmp_path / "trace.jsonl"
    result.trace.write_jsonl(out)
    lines = out.read_text().strip().splitlines()
    assert len(lines) == len(result.trace.events)
    import json

    types = [json.loads(line)["type"] for line in lines]
    assert types[0] == "run_start"
    assert types[-1] == "run_end"
    assert "success_check" in types


def test_toolbelt_blocks_disallowed_hosts(tmp_path):
    task = make_task(tmp_path)
    from quickstarted.sandbox import Sandbox
    from quickstarted.trace import Trace

    sb = Sandbox()
    try:
        trace = Trace()
        belt = Toolbelt(task, sb, trace, http_get=fake_http_get)
        out = belt.fetch("https://evil.com/steal")
        assert out.startswith("BLOCKED")
        assert trace.fetched_urls() == []  # blocked fetches are not docs reads
        assert any(e.type == "fetch_blocked" for e in trace.events)
    finally:
        sb.cleanup()


def test_html_is_converted_to_text(tmp_path):
    task = make_task(tmp_path)
    from quickstarted.sandbox import Sandbox
    from quickstarted.trace import Trace

    sb = Sandbox()
    try:
        belt = Toolbelt(task, sb, Trace(), http_get=fake_http_get)
        out = belt.fetch("https://example.com/docs/")
        assert "<html>" not in out
        assert "pip install thing" in out
    finally:
        sb.cleanup()


def test_replay_requires_replay_commands(tmp_path):
    text = textwrap.dedent(
        """
        name: t
        goal: g
        docs:
          entrypoint: https://example.com/
        success:
          script: "true"
        """
    )
    path = tmp_path / "t.yaml"
    path.write_text(text)
    task = load_task(path)
    result = run_task(task, ReplayAgent(), http_get=fake_http_get, backend="local")
    assert result.outcome.stop_reason == "error"
    assert "replay" in result.outcome.detail
