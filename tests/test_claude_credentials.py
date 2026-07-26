"""Credential resolution for the Claude adapter.

The quickstarted-specific variable exists so a key can sit in a developer's
shell without other Anthropic tooling on the same machine picking it up.
"""

import time

import pytest

from quickstarted.agents.base import Toolbelt
from quickstarted.agents.claude import (
    FALLBACK_KEY_ENV,
    KEY_ENV,
    ClaudeAgent,
    resolve_api_key,
)
from quickstarted.journey import load_journey
from quickstarted.trace import Trace


def test_quickstarted_key_wins_over_generic(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "sk-quickstarted")
    monkeypatch.setenv(FALLBACK_KEY_ENV, "sk-generic")
    assert resolve_api_key() == "sk-quickstarted"


def test_generic_key_is_a_fallback(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.setenv(FALLBACK_KEY_ENV, "sk-generic")
    assert resolve_api_key() == "sk-generic"


def test_no_key_at_all(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv(FALLBACK_KEY_ENV, raising=False)
    assert resolve_api_key() is None


def test_missing_credentials_report_the_quickstarted_variable(tmp_path, monkeypatch):
    pytest.importorskip("anthropic")
    for name in (KEY_ENV, FALLBACK_KEY_ENV, "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "j.yaml"
    path.write_text(
        "name: creds\n"
        "goal: nothing\n"
        "docs:\n"
        "  entrypoint: https://example.com/docs/\n"
        "success:\n"
        "  script: 'true'\n"
    )
    journey = load_journey(path)
    deadline = time.monotonic() + 30
    outcome = ClaudeAgent().run(journey, Toolbelt(journey, None, Trace()), deadline)
    assert outcome.stop_reason == "error"
    assert KEY_ENV in outcome.detail


def test_usage_counts_cache_tokens():
    """A cached run must not look free: cache traffic is tracked, not dropped."""
    from types import SimpleNamespace

    from quickstarted.agents.claude import _Usage
    from quickstarted.report import _token_line

    used = _Usage()
    used.add(
        SimpleNamespace(
            input_tokens=2,
            output_tokens=146,
            cache_creation_input_tokens=4100,
            cache_read_input_tokens=0,
        )
    )
    used.add(
        SimpleNamespace(
            input_tokens=20,
            output_tokens=300,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=4100,
        )
    )
    assert (used.input_tokens, used.output_tokens) == (22, 446)
    assert (used.cache_write_tokens, used.cache_read_tokens) == (4100, 4100)

    line = _token_line(
        SimpleNamespace(
            input_tokens=22,
            output_tokens=446,
            cache_write_tokens=4100,
            cache_read_tokens=4100,
        )
    )
    assert "cache 4100 written / 4100 read" in line
