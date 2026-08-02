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

## Try it in one command

```bash
uvx quickstarted run --example streamlit --agent replay
```

No API key, no cost, and nothing to clone:

```
  [    0s] started on seatbelt
  [    2s] read https://docs.streamlit.io/get-started/installation
  [    3s] read https://docs.streamlit.io/get-started/fundamentals/main-concepts
  [   24s] blocked from the shell: checkip.amazonaws.com
  [   24s] check exited 0
[PASS] streamlit-quickstart (replay)
  classification: passed
  turns: 2, duration: 24.4s
  backend: seatbelt
  docs pages read: 2
```

That ran the commands Streamlit's documentation tells a reader to type, booted
the app, and polled its health endpoint. Two pages, because that is the route a
reader takes: install on one, the first app on the next. The fourth line is the
sandbox refusing Streamlit's own call home, which is what enforcement looks
like from the outside. `quickstarted examples` lists the others.

## Install

```bash
uvx quickstarted run --example httpx --agent replay   # nothing to install
pip install "quickstarted[claude]"                    # agent mode with Claude
pip install "quickstarted[all-agents]"                # + OpenAI and Gemini
pip install quickstarted                              # replay mode only, no SDK
```

Python 3.9+. One runtime dependency: PyYAML. Every adapter is a plain tool-use
loop against the same two harness-owned tools and the same shared prompt, so
cross-model numbers compare like with like.

## How it works

You write a task, in YAML. `quickstarted init <docs-url>` scaffolds one:

```yaml
name: streamlit-quickstart
goal: >
  Following Streamlit's documentation, install Streamlit into this workspace and
  write a small script that uses Streamlit commands to put something on the
  page, the way its basic concepts page describes. Leave the script ready to run
  and do not start a long-running server yourself; the harness starts one.
docs:
  # The route a reader takes, in the project's own order. Install is one page
  # and the first app is another, and a task naming only the second measures
  # whether the agent goes looking rather than whether the docs work.
  path:
    - https://docs.streamlit.io/get-started/installation
    - https://docs.streamlit.io/get-started/fundamentals/main-concepts
  allow:
    - docs.streamlit.io
    - streamlit.io
setup:
  - python3 -m venv .venv
success:
  script: |
    set -e
    app=$(find . -maxdepth 2 -name "*.py" -not -path "./.venv/*" \
      -exec grep -l "streamlit" {} + | head -1)
    test -n "$app" || qs_fail "no Python file imports streamlit, so no app was written"
    qs_serve .venv/bin/streamlit run "$app" --server.headless true \
      --server.port "$QS_PORT" --browser.gatherUsageStats false
    qs_wait_http /_stcore/health --contains ok
```

Note what the task does not do: it never names a file. Streamlit's
documentation writes `streamlit run your_script.py`, a placeholder, so the
check finds the script rather than dictating one. A task that demands `app.py`
fails a reader who followed the page exactly, and reports it as a
documentation gap.

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

When the agent stops, the harness runs your check in the same workspace. Exit
code 0 is a pass. Nothing else is. The agent's own claim of success is recorded
and never trusted, and there is no LLM judge anywhere in scoring, because a
model asked to grade its own work will tell you the app is ready when `app.py`
does not parse.

Most checks are the size of the one above. You are asserting whatever your
tutorial already promises the reader: the import works, the command runs, the
file your page told them to create exists. If your quickstart ends with "you
should see `200`", the check is one line:

```yaml
success:
  expect_output:
    contains: "200"
```

**Name nothing your documentation does not name.** Most quickstarts end at a
value on a terminal rather than a file, and a check that can only see the
filesystem pushes you into inventing somewhere to put it. Every task in this
repository once did that: FastAPI's tutorial says "copy that to a file
`main.py`" and the task demanded `app.py`, so a reader who followed the page
exactly would have failed. [Why this matters][fid].

[fid]: https://snehankekre.com/quickstarted/explanation/fidelity/

**Say what you saw.** `qs_fail` is defined for every check, and a failure that
reports `check failed: httpx is not a dependency in pyproject.toml` is a bug
report, where `exit code: 1` is a page to go and guess about.

**Keep a long check in a file.** `success.file: checks/mine.sh` puts it beside
the task, where shellcheck and syntax highlighting work on it. It is read when
the task loads and never written into the workspace, so the agent cannot read
its own success criteria.

**Let the harness boot the server.** If the goal is a running application, do
not ask the agent to leave a process running and do not take its word for it:

```yaml
success:
  serve: .venv/bin/fastapi run main.py --host 127.0.0.1 --port $QS_PORT
  wait_http:
    path: /
    json:
      message: Hello World
  script: test -f main.py
```

The harness backgrounds it, polls, keeps the last error, dumps the server log
when it gives up, and kills it. Every criterion is still yours: a task that
serves and asserts nothing is a validation error, because a server that answers
every request with a 500 also boots.

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

## Iterate on a check for free

```bash
quickstarted run tasks/mine.yaml --agent claude --keep-sandbox
quickstarted check tasks/mine.yaml --sandbox /tmp/quickstarted-8ilw9l6v/workspace
```

`check` re-runs only the success script against the workspace the run left
behind, under the same backend. About a second per iteration, instead of a paid
run per iteration.

`quickstarted validate` catches the rest before you spend anything: a check that
requires a `.venv` nothing creates, a check that can fail in silence, an
entrypoint that 404s (`--check-urls`). Every one of those produces a number that
is wrong rather than low.

## Pass rates

The same docs and the same model can pass at 10:00 and fail at 10:05. One run
is a sample. Use `--repeat` and read the rate:

```
quickstarted run --repeat 5 --workers 3 --agent claude
```

With no paths, that runs every task in `tasks/`.

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
| `skipped` | nothing ran, and nothing was meant to | no |

Runs that produced no evidence are excluded from the numerator *and* the
denominator, and reported separately. When nothing produced evidence the suite
says so. Reporting 0% there would be a different claim, and a false one.

`skipped` is counted apart from the rest: a task with no `replay` block, run
under `--agent replay`, is out of scope for the mode it was asked to run in.
Listing that beside a rate limit and a harness bug invites reading all three as
damage.

## Did the change help?

That is the question you have after editing the page, and one run cannot answer
it:

```
quickstarted run --agent claude --repeat 10 --out before/
# edit the page
quickstarted run --agent claude --repeat 10 --out after/
quickstarted diff before/results.json after/results.json
```

```
  fastapi-quickstart
      2/10 (20%)  ->  8/10 (80%)
      improved, p=0.023
```

Every comparison carries a two-sided Fisher exact test, and when the samples
were too small for any outcome to have cleared the bar, it says that instead of
reporting a result. Three attempts a side never can. Four can. That is worth
knowing before a sweep rather than after reading a number you cannot use.
`--fail-on-regression` is the CI form of the same question.

To read a run back, `quickstarted show <trace.jsonl>` narrates one in order, and
`quickstarted report results/ --out report.html` turns a whole suite into one
self-contained page to forward to whoever owns the documentation.

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
| `seatbelt` (macOS) | home directory unreadable, writes confined to the workspace | all egress denied except the harness proxy and loopback |
| `local` | none | none; proxy variables are advisory |

`auto` picks the best available. `quickstarted run` refuses `local` unless you
pass `--allow-unenforced`. Run `quickstarted doctor` to see what your machine
can enforce, which SDKs and keys it can find, and whether your tasks parse.
Details in [SECURITY.md](SECURITY.md).

## CI

Two jobs, on two schedules. Replay on every push, because it is free:

```yaml
- run: pip install quickstarted
- run: quickstarted run --agent replay --junit junit.xml
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
      - run: quickstarted run --agent claude --repeat 3
             --out results --junit junit.xml
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: quickstarted-results
          path: results/
```

Exit codes are meant to be branched on, because "your quickstart is broken" and
"somebody else's API returned 429" need different people to do different
things: 0 passed, 1 a documentation gap, 2 no evidence at all, 3 usage, 130
interrupted or stopped at `--max-spend`. `results.json` is versioned (schema
2.0). JUnit XML reports a docs gap as a failure and infrastructure trouble as an
error, so a rate limit does not read as a broken quickstart.

Repeated flags belong in `quickstarted.yaml` instead:

```yaml
run:
  backend: docker
  cache_dir: .cache
tasks:
  setup:
    - python3 -m venv .venv
```

It refuses `agent`, `model`, `repeat` and `affordances`. A file that quietly
changed which model served a task would make two runs incomparable for a reason
invisible in the command you typed.

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
