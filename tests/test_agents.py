"""Adapter contracts that hold without any vendor credentials."""

import time

import pytest

from quickstarted.agents import prompt
from quickstarted.agents.base import Toolbelt
from quickstarted.agents.gemini_agent import GeminiAgent
from quickstarted.agents.openai_agent import OpenAIAgent
from quickstarted.agents.registry import AGENTS, build_agent
from quickstarted.task import load_task
from quickstarted.trace import Trace

TASK = (
    "name: adapters\n"
    "goal: do a thing\n"
    "docs:\n"
    "  entrypoint: https://docs.example.com/start\n"
    "setup:\n"
    "  - python3 -m venv .venv\n"
    "success:\n"
    "  script: 'true'\n"
)


@pytest.fixture
def task(tmp_path):
    path = tmp_path / "j.yaml"
    path.write_text(TASK)
    return load_task(path)


def _run(agent, task):
    return agent.run(task, Toolbelt(task, None, Trace()), time.monotonic() + 30)


def test_registry_builds_every_advertised_agent():
    for name in AGENTS:
        assert build_agent(name, model="x") is not None


def test_unknown_agent_is_rejected():
    with pytest.raises(SystemExit):
        build_agent("telepathy")


@pytest.mark.parametrize("factory", [OpenAIAgent, GeminiAgent])
def test_vendor_adapters_refuse_to_guess_a_model(factory, task):
    """A silently chosen model makes results irreproducible."""
    outcome = _run(factory(), task)
    assert outcome.stop_reason == "error"
    assert "--model" in outcome.detail


@pytest.mark.parametrize(
    ("factory", "key_env"),
    [
        (OpenAIAgent, "QUICKSTARTED_OPENAI_API_KEY"),
        (GeminiAgent, "QUICKSTARTED_GEMINI_API_KEY"),
    ],
)
def test_vendor_adapters_name_their_key_variable(factory, key_env, task, monkeypatch):
    for name in (key_env, "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    pytest.importorskip(
        "openai" if factory is OpenAIAgent else "google.genai",
        reason="adapter reports the missing SDK before it reports the missing key",
    )
    outcome = _run(factory(model="some-model"), task)
    assert outcome.stop_reason == "error"
    assert key_env in outcome.detail


def test_every_adapter_shares_one_prompt(task):
    """Otherwise a cross-model comparison measures the prompts."""
    text = prompt.kickoff(task)
    assert task.goal in text
    assert task.docs_entrypoint in text
    # The agent must know what setup already did, or it rebuilds it.
    assert "python3 -m venv .venv" in text
    assert "read documentation with read_docs" in prompt.SYSTEM.lower()


def test_claude_adapter_uses_the_shared_prompt():
    from quickstarted.agents import claude

    assert claude.SYSTEM is prompt.SYSTEM


def test_openai_usage_does_not_double_count_cached_tokens(task, monkeypatch):
    """OpenAI's prompt_tokens includes cached tokens; Anthropic's does not.

    Adapters must normalise, or a cross-vendor cost comparison bills the same
    token twice on one side and not the other.
    """
    from types import SimpleNamespace

    import quickstarted.agents.openai_agent as mod

    calls = {"n": 0}

    class FakeCompletions:
        def create(self, **kwargs):
            calls["n"] += 1
            return SimpleNamespace(
                model="gpt-test",
                usage=SimpleNamespace(
                    prompt_tokens=1000,
                    completion_tokens=50,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=800),
                ),
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="done", tool_calls=None),
                    )
                ],
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(mod, "openai", SimpleNamespace(OpenAI=FakeClient), raising=False)
    monkeypatch.setitem(__import__("sys").modules, "openai", SimpleNamespace(OpenAI=FakeClient))
    monkeypatch.setenv("QUICKSTARTED_OPENAI_API_KEY", "k")

    outcome = _run(mod.OpenAIAgent(model="gpt-test"), task)
    assert calls["n"] == 1
    assert outcome.cache_read_tokens == 800
    assert outcome.input_tokens == 200, "cached tokens must not be counted twice"
    assert outcome.total_tokens == 1050
