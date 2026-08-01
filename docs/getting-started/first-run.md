# Your first run

> Point a model at real documentation and watch whether it can finish.

## A result before you write anything

```bash
quickstarted run --example httpx --agent replay
```

```
  [    0s] started on seatbelt
  [    2s] read https://www.python-httpx.org/
  [    6s] check exited 0
[PASS] httpx-quickstart (replay)
  classification: passed
  turns: 3, duration: 5.6s
  backend: seatbelt
  docs pages read: 1
```

Three tasks ship with the package; `quickstarted examples` lists them. That one
ran the commands the HTTPX documentation tells a reader to type, in a sandbox,
and checked the result. No key, no cost.

## Scaffold your own

```bash
quickstarted init https://www.python-httpx.org/
```

That writes `tasks/httpx-quickstart.yaml` with the entrypoint filled in, the
allowlist derived from the host, and a schema line that gives any language
server editor completion on every field. Fill in the goal and the check:

```yaml
name: httpx-quickstart
goal: >
  Install httpx into the virtualenv in this workspace and write fetch.py, which
  performs a GET request and prints the response status code. Run it.
docs:
  entrypoint: https://www.python-httpx.org/
  allow:
    - python-httpx.org
setup:
  - python3 -m venv .venv
success:
  script: |
    set -e
    test -f fetch.py || qs_fail "no fetch.py, so the quickstart produced nothing"
    .venv/bin/python -c "import httpx" || qs_fail "httpx is not installed"
    .venv/bin/python fetch.py | grep -q 200 || qs_fail "fetch.py did not print 200"
```

Four lines of shell are the entire scoring mechanism, and they assert exactly
what the documentation promises a reader: a file, a working import, and the
status code the page says you will see. Each one says what it saw when it fails,
because a verdict you cannot act on is barely a verdict.

Check that it parses:

```bash
quickstarted validate tasks/httpx-quickstart.yaml
```

```
ok       tasks/httpx-quickstart.yaml (httpx-quickstart, agent-only)
```

`--check-urls` also fetches the entrypoint, which is worth doing once before you
spend anything: an entrypoint that 404s produces a failure that looks exactly
like a documentation gap.

## Run it

```bash
pip install "quickstarted[claude]"
export QUICKSTARTED_ANTHROPIC_API_KEY=sk-ant-...
quickstarted run tasks/httpx-quickstart.yaml --agent claude
```

```
[PASS] httpx-quickstart (claude:claude-opus-5)
  classification: passed
  stop reason: completed
  turns: 5, duration: 23.9s
  backend: docker
  tokens: 10 in / 791 out, cache 6249 written / 17561 read
  docs pages read: 1
```

One page was enough. The model read the httpx landing page, installed the
package, wrote `fetch.py`, ran it, and stopped. Your script then agreed.

With no paths at all, `quickstarted run` reads every task in `tasks/`.

## What just happened

The harness created a throwaway workspace, ran your `setup` commands in it, and
handed the agent two tools: `bash`, which runs commands in that workspace, and
`read_docs`, which fetches a documentation page.

That second tool is the only route to your documentation. Every command runs
inside a sandbox whose one path to the network is a proxy the harness owns, and
`python-httpx.org` is unreachable from the shell. An agent that tries
`curl https://www.python-httpx.org/` is refused and the attempt is recorded. So
"docs pages read: 1" is a measurement.

When the agent stopped, the harness ran your check in the same workspace. Exit
code 0 is a pass and nothing else is. The agent's own report of success is
recorded in the trace and never consulted. See
[Deterministic scoring](../explanation/scoring.md).

## Read the failure instead

A pass tells you the floor holds. The interesting output is the other one:

```
[FAIL] fastapi-quickstart (openai:gpt-5.2-2025-12-11)
  classification: docs_gap
  turns: 7, duration: 65.7s
  backend: docker (python:3.12-slim)
  success check exit code: 1 (	pip install "fastapi[standard]")
  last docs page read before failure: https://fastapi.tiangolo.com/tutorial/first-steps/
  docs pages read: 1
```

Start at the last page, then read the check's own output. `--out results/` has
the whole thing:

```
GET /items/42 never answered correctly. Last attempt: Connection refused
--- server log (last 20 lines) ---
To use the fastapi command, please install "fastapi[standard]":

	pip install "fastapi[standard]"
```

The model wrote a correct application and then had nothing to run it with,
because it installed `fastapi` where the page says `fastapi[standard]`. That is
a bug report with a page attached, and it reproduced on three runs out of three
while Claude Opus 5 passed the same task eleven times out of eleven.

Two models disagreeing on the same task is the normal case. See
[pass rates](../guides/pass-rates.md).

## Read the whole run back

```bash
quickstarted show results/fastapi-quickstart/trace.jsonl
```

Every page in the order the agent read it, every command with the output of the
ones that failed, the check's own message, and the classification. `--verbose`
adds the commands that succeeded.

```bash
quickstarted report results/ --out report.html
```

One self-contained page for the whole suite, which is the artifact you forward
to whoever owns the documentation. It fetches no stylesheet, script or font, so
it renders the same for them as for you.

## Fix the check without paying for another run

```bash
quickstarted run tasks/httpx-quickstart.yaml --agent claude --keep-sandbox
# ... sandbox kept at: /tmp/quickstarted-8ilw9l6v/workspace

quickstarted check tasks/httpx-quickstart.yaml --sandbox /tmp/quickstarted-8ilw9l6v/workspace
```

`check` runs only the success script, against the workspace the run left behind,
under the same backend. About a second, as many times as you like.

## Add a free precondition

`--agent replay` runs the literal commands your documentation tells a reader to
type. No model, no key, no cost.

```yaml
replay:
  - .venv/bin/pip install --quiet httpx
  - |
    cat > fetch.py <<'PY'
    import httpx

    print(httpx.get("https://pypi.org/simple/").status_code)
    PY
  - .venv/bin/python fetch.py
```

```bash
quickstarted run tasks/httpx-quickstart.yaml --agent replay
```

If the documented commands are broken, no reader stands a chance, and an agent
failure afterwards tells you nothing you did not already know. Run replay on
every push and agent mode on a schedule. See [Replay mode](../guides/replay-mode.md).

Next: [agent mode in depth](agent-mode.md), for choosing models, controlling
cost, and reading the trace.
