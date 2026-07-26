# Contributing

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy
```

Tests that touch the network are skipped unless `QUICKSTARTED_NETWORK_TESTS=1`
is set. No test needs an API key.

## Writing a journey

A good journey asserts an outcome the documentation actually promises, and
nothing else.

- **Assert the data.** Check that `out.csv` holds the right rows. Do not check
  which function the agent called; any correct route should pass.
- **Do not assert incidental paths.** An early journey checked for a `.venv`
  the docs never mention; an agent that made `venv/` "failed" for no reason.
  If `setup` creates something, the agent is told, and the check may rely on
  it.
- **Let the harness verify.** If the goal is a running server, the success
  script starts it, asks it a question, and stops it. Do not trust the agent's
  report, and do not ask the agent to leave something running.
- **Separate docs hosts from registries.** `docs.allow` hosts are readable only
  through `read_docs`; a shell cannot reach them. Putting `pypi.org` there
  stops `pip` working. `quickstarted validate` warns about this.

Run `quickstarted run <journey> --agent replay` first. If the documented
commands do not pass, the journey is not ready for agent mode.

## Adding an agent adapter

Implement `run(journey, toolbelt, deadline) -> AgentOutcome` and act only
through the toolbelt: never touch the filesystem or network directly, or the
run loses the attribution and enforcement the whole tool depends on.

Use `agents/prompt.py` unchanged. Adapters that phrase the task their own way
turn a cross-model comparison into a comparison of prompts.

Do not assume a default model for a new vendor. Model names change faster than
a pinned default survives, and a benchmark that silently picks one produces
numbers nobody can reproduce.

## Things that will get a change rejected

- An LLM anywhere in the scoring path.
- Scoring the presence of `llms.txt`, MCP, or any other affordance. Measure it
  with an ablation instead.
- Counting infrastructure failures as documentation failures.
- Making the unenforced backend the silent default.
