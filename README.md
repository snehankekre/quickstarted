# quickstarted

Test whether an AI agent can complete your quickstart using only your docs.

[![CI](https://github.com/snehankekre/quickstarted/actions/workflows/ci.yml/badge.svg)](https://github.com/snehankekre/quickstarted/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/quickstarted.svg)](https://pypi.org/project/quickstarted/)
[![Python](https://img.shields.io/pypi/pyversions/quickstarted.svg)](https://pypi.org/project/quickstarted/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Roughly half the traffic to documentation sites is now AI agents and
AI-assisted workflows ([Mintlify's measurement](https://www.mintlify.com/blog/ai-traffic)).
When an agent reads your quickstart and fails, you lose the developer behind
it and you never find out. quickstarted turns that failure into a CI signal: a
sandboxed agent gets your goal, your docs, and nothing else, and a script you
wrote decides whether it succeeded.

Full documentation: **https://snehankekre.com/quickstarted/**

**Status: early. The interface will change.**

## How it works

You write a task, in YAML. This one points at Streamlit's documentation:

```yaml
name: streamlit-quickstart
goal: >
  Install Streamlit into the virtualenv in this workspace and build a small app
  in app.py that shows a title and a slider whose value is displayed on the
  page. Do not start a long-running server yourself; just leave app.py ready to
  run and confirm streamlit is installed.
docs:
  entrypoint: https://docs.streamlit.io/get-started
  allow:
    - docs.streamlit.io
    - streamlit.io
setup:
  - python3 -m venv .venv
success:
  script: |
    set -e
    test -f app.py
    .venv/bin/python -c "import streamlit"
```

Then you run an agent against it:

```
pip install "quickstarted[claude]"
export QUICKSTARTED_ANTHROPIC_API_KEY=...
quickstarted run tasks/streamlit-quickstart.yaml --agent claude
```

```
[PASS] streamlit-quickstart (claude:claude-opus-5)
  classification: passed
  turns: 6, duration: 63.5s
  backend: docker
  tokens: 12 in / 1150 out, cache 11204 written / 33181 read
  docs pages read: 4
```

The agent works in a throwaway workspace with two tools: a sandboxed `bash`,
and `read_docs`, which is the only way it can read documentation. It gets no
browser, no search engine, and no network of its own. The system prompt also
forbids leaning on prior knowledge of the project under test, because a model
that already knows Streamlit would sail through docs that teach a newcomer
nothing.

The harness enforces the boundary rather than requesting it. All shell traffic
leaves through a proxy the harness owns, and documentation hosts are
unreachable from the shell, so an agent that tries
`curl https://docs.streamlit.io/...` is refused and the attempt is recorded.
The pages in a report are therefore the pages the agent really read, and when a
run fails, the last page it read is a fact rather than a guess.

Keys are read from `QUICKSTARTED_*` names first so they can sit in your shell
without other tooling on the same machine picking them up and spending them.
The vendor-standard names still work as a fallback, which is what CI sets.

## The success script is the whole verdict

When the agent stops, the harness runs your `success.script` in the same
workspace. Exit code 0 is a pass. Nothing else is. The agent's own claim of
success is recorded and never trusted, and there is no LLM judge anywhere in
scoring, because a model asked to grade its own work will tell you the app is
ready when `app.py` does not parse.

Most checks are the size of the one above. You are asserting whatever your
tutorial already promises the reader: the file exists, the import works, the
command runs, the output contains the number on the page. If your quickstart
ends with "you should see `200`", the check is `grep -q 200`.

You can go stricter when it is worth it.
[tasks/streamlit-quickstart.yaml](tasks/streamlit-quickstart.yaml) boots
the app headless and polls Streamlit's own health endpoint, which is about
fifteen more lines and proves the app actually serves. That is optional. Start
with the two-line version.

## Replay mode, the free precondition

`--agent replay` runs your `replay` commands, the literal commands your docs
tell a reader to type, and stops at the first failure. No model, no API key, no
cost.

```
quickstarted run tasks/streamlit-quickstart.yaml --agent replay
```

Treat it as a floor to check on every push. If the documented commands are
broken, no reader stands a chance and an agent run only adds noise on top of a
failure you already know about. It cannot tell you whether a reader could have
*found* those commands, understood their order, or guessed the prerequisite you
left out. That is what agent mode is for.

## Pass rates

The same docs and the same model can pass at 10:00 and fail at 10:05. One run
is a sample. Use `--repeat` and read the rate:

```
quickstarted run tasks/*.yaml --agent claude --repeat 5 --workers 3
```

Every run is classified, and only two classifications say anything about your
documentation:

| Classification | Meaning | Counts toward pass rate |
| --- | --- | --- |
| `passed` | success script exited 0 | yes |
| `docs_gap` | the agent finished, the check failed | yes |
| `budget_exhausted` | out of turns, time, or tokens | no |
| `infra_error` | rate limit, upstream 5xx, network failure | no |
| `harness_error` | misconfigured task, our bug | no |
| `agent_refusal` | model declined | no |

Runs that produced no evidence are excluded from the numerator *and* the
denominator, and reported separately. When nothing produced evidence the suite
says so. Reporting 0% there would be a different claim, and a false one.

## Does llms.txt actually help?

Whether a project ships `llms.txt` is a checklist item anyone can `curl`, and
scoring it would be the proxy metric this tool exists to replace. So
quickstarted never scores affordances. It measures them:

```
quickstarted run tasks/streamlit-quickstart.yaml --agent claude --repeat 10
quickstarted run tasks/streamlit-quickstart.yaml --agent claude --repeat 10 --affordances none
```

Same prompt, same task, same model. The only difference is whether the
agent could read `llms.txt` and `.md` variants. The difference in pass rate is
a measurement of the affordance itself.

`--probe-affordances` records what exists without changing anything, including
the size. Presence and usefulness come apart quickly: Streamlit's `llms.txt` is
67 KB, while its `llms-full.txt` is 1.8 MB, which is more than most agents can
read in one go.

## Sandboxing

Agent-authored commands from somebody else's quickstart are untrusted code.

| Backend | Filesystem | Network |
| --- | --- | --- |
| `docker` | container | internal network; the proxy sidecar is the only route out |
| `seatbelt` (macOS) | home directory unreadable, writes confined to the workspace | all egress denied except the harness proxy |
| `local` | none | none; proxy variables are advisory |

`auto` picks the best available. `quickstarted run` refuses `local` unless you
pass `--allow-unenforced`. Run `quickstarted doctor` to see what your machine
can enforce. Details in [SECURITY.md](SECURITY.md).

## Install

```
pip install "quickstarted[claude]"       # agent mode with Claude
pip install "quickstarted[all-agents]"   # + OpenAI and Gemini
pip install quickstarted                 # replay mode only, no SDK
```

Python 3.9+. One runtime dependency: PyYAML. Every adapter is a plain tool-use
loop against the same two harness-owned tools and the same shared prompt, so
cross-model numbers compare like with like.

## CI

Two jobs, on two schedules. Replay on every push, because it is free:

```yaml
- run: pip install quickstarted
- run: quickstarted run tasks/*.yaml --agent replay --junit junit.xml
```

Agent mode on a schedule, or when a model ships, because it costs real tokens:

```yaml
on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:
jobs:
  agent:
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "quickstarted[claude]"
      - run: quickstarted run tasks/*.yaml --agent claude --repeat 3
             --out results --junit junit.xml
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: quickstarted-results
          path: results/
```

`quickstarted run` exits 1 when any task fails, so either job can gate
merges. `results.json` is versioned (schema 1.0). JUnit XML reports a docs gap
as a failure and infrastructure trouble as an error, so a rate limit does not
read as a broken quickstart.

## Fetching other people's docs

Benchmarking means requesting pages from organisations who did not ask to be
measured. quickstarted sends a truthful User-Agent, honours `robots.txt`, and
waits a second between requests to the same host. `--cache-dir` makes reruns
read the same bytes. `--refresh` flags pages whose content changed since the
last run, which is a finding in its own right.

## What this does and does not tell you

It tells you whether a given model, on a given day, could get from your docs to
a working result, and where it was reading when it could not. That is a lower
bound on documentation quality. Nothing here measures whether your docs are
pleasant, complete, or accurate beyond the task you wrote, and there is no
UI testing at all: if your product's button moved, this will not notice.
[Doc Detective](https://github.com/doc-detective/doc-detective) is the tool for
that, and the two answer different questions.

Write success scripts that assert local, deterministic facts. A pass means the
floor holds, and says nothing about the ceiling.

## License

MIT.
