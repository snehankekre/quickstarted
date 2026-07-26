# quickstarted

Test whether an AI agent can actually complete your quickstart by following
your docs.

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

Full documentation: **https://snehankekre.github.io/quickstarted/**

**Status: early. The interface will change.**

## How it works

You write a journey, in YAML:

```yaml
name: pnf-quickstart
goal: >
  Install the pnf package from PyPI into a virtualenv and write a runnable
  snippet that imports pnf and identifies the decode function.
docs:
  entrypoint: https://raw.githubusercontent.com/snehankekre/pnf/main/README.md
  allow:
    - raw.githubusercontent.com
setup:
  - python3 -m venv .venv
success:
  script: |
    set -e
    .venv/bin/python -c "import pnf; assert callable(pnf.decode)"
    .venv/bin/python demo.py
replay:
  - .venv/bin/pip install pnf
  - printf 'import pnf\nprint(pnf.decode.__name__)\n' > demo.py
  - .venv/bin/python demo.py
```

The harness runs an agent in a throwaway workspace with two tools: a sandboxed
`bash`, and `read_docs`, which is the only way it can read documentation.

The harness enforces that. All shell traffic leaves through a proxy it owns,
and documentation hosts are unreachable from the shell, so an agent that tries
`curl https://docs.example.com/...` is refused and the attempt is recorded.
The pages listed in a report are therefore the pages the agent really read.
When a run fails, the last page it read is a fact you can act on.

When the agent stops, the harness runs your `success.script` in the workspace.
Exit code 0 is a pass. Nothing else is. The agent's own claim of success is
recorded and never trusted; there is no LLM judge anywhere in scoring.

## Two modes

**Replay mode** (free, no LLM, no API key) runs your `replay` commands, the
literal commands your docs tell users to type, and stops at the first failure.
Treat it as a precondition. If the documented commands break, no reader stands
a chance, and agent mode only adds noise.

```
quickstarted run journeys/pnf-quickstart.yaml --agent replay
```

**Agent mode** has an LLM follow your docs to the goal. This catches what
replay cannot: ambiguity, missing steps, wrong ordering, docs that assume
context a newcomer does not have.

```
pip install "quickstarted[claude]"
export QUICKSTARTED_ANTHROPIC_API_KEY=...
quickstarted run journeys/pnf-quickstart.yaml --agent claude
```

Keys are read from `QUICKSTARTED_*` names first so they can sit in your shell
without other tooling on the same machine picking them up and spending them.
The vendor-standard names still work as a fallback, which is what CI sets.

```
[PASS] pnf-quickstart (claude:claude-opus-5)
  classification: passed
  turns: 12, duration: 70.7s
  backend: seatbelt
  tokens: 24 in / 4616 out, cache 16812 written / 104148 read
  docs pages read: 2
```

## Pass rates

The same docs and the same model can pass at 10:00 and fail at 10:05. One run
is a sample. Use `--repeat` and read the rate:

```
quickstarted run journeys/*.yaml --agent claude --repeat 5 --workers 3
```

Every run is classified, and only two classifications say anything about your
documentation:

| Classification | Meaning | Counts toward pass rate |
| --- | --- | --- |
| `passed` | success script exited 0 | yes |
| `docs_gap` | the agent finished, the check failed | yes |
| `budget_exhausted` | out of turns, time, or tokens | no |
| `infra_error` | rate limit, upstream 5xx, network failure | no |
| `harness_error` | misconfigured journey, our bug | no |
| `agent_refusal` | model declined | no |

Runs that produced no evidence are excluded from the numerator *and* the
denominator, and reported separately. When nothing produced evidence the suite
says so. Reporting 0% there would be a different claim, and a false one.

## Does llms.txt actually help?

Whether a project ships `llms.txt` is a checklist item anyone can `curl`, and
scoring it would be the proxy metric this tool exists to replace. So
quickstarted never scores affordances. It measures them:

```
quickstarted run journeys/streamlit-quickstart.yaml --agent claude --repeat 10
quickstarted run journeys/streamlit-quickstart.yaml --agent claude --repeat 10 --affordances none
```

Same prompt, same journey, same model. The only difference is whether the
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
pip install quickstarted                 # replay mode only
pip install "quickstarted[claude]"       # + Claude
pip install "quickstarted[all-agents]"   # + OpenAI and Gemini
```

Python 3.9+. One runtime dependency: PyYAML. Every adapter is a plain tool-use
loop against the same two harness-owned tools and the same shared prompt, so
cross-model numbers compare like with like.

## CI

```yaml
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- run: pip install quickstarted
- run: quickstarted run journeys/*.yaml --agent replay --out results --junit junit.xml
- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: quickstarted-results
    path: results/
```

`quickstarted run` exits 1 when any journey fails, so the job gates merges.
`results.json` is versioned (schema 1.0). JUnit XML reports a docs gap as a
failure and infrastructure trouble as an error, so a rate limit does not read
as a broken quickstart. Run agent mode on a schedule, or when a model ships.
Every push is too often, because agent runs cost real tokens.

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
pleasant, complete, or accurate beyond the journey you wrote, and there is no
UI testing at all: if your product's button moved, this will not notice.
[Doc Detective](https://github.com/doc-detective/doc-detective) is the tool for
that, and the two answer different questions.

Write success scripts that assert local, deterministic facts. A pass means the
floor holds, and says nothing about the ceiling.

## License

MIT.
