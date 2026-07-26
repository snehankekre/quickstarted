# Your first run

> Point a model at real documentation and watch whether it can finish.

A journey states a goal, where the documentation lives, and a script that
decides whether the goal was reached. Save this as `journeys/httpx.yaml`:

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
    test -f fetch.py
    .venv/bin/python -c "import httpx"
    .venv/bin/python fetch.py | grep -q 200
```

Three lines of shell are the entire scoring mechanism, and they assert exactly
what the documentation promises a reader: a file, a working import, and the
status code the page says you will see.

Check that it parses:

```bash
quickstarted validate journeys/httpx.yaml
```

```
ok       journeys/httpx.yaml (httpx-quickstart, agent-only)
```

## Run it

```bash
pip install "quickstarted[claude]"
export QUICKSTARTED_ANTHROPIC_API_KEY=sk-ant-...
quickstarted run journeys/httpx.yaml --agent claude
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

## What just happened

The harness created a throwaway workspace, ran your `setup` commands in it, and
handed the agent two tools: `bash`, which runs commands in that workspace, and
`read_docs`, which fetches a documentation page.

That second tool is the only route to your documentation. Every command runs
inside a sandbox whose one path to the network is a proxy the harness owns, and
`python-httpx.org` is unreachable from the shell. An agent that tries
`curl https://www.python-httpx.org/` is refused and the attempt is recorded. So
"docs pages read: 1" is a measurement, not a claim.

When the agent stopped, the harness ran `success.script` in the same workspace.
Exit code 0 is a pass and nothing else is. The agent's own report of success is
recorded in the trace and never consulted. See
[Deterministic scoring](../explanation/scoring.md).

## Read the failure instead

A pass tells you the floor holds. The interesting output is the other one:

```
[FAIL] duckdb-quickstart (claude:claude-opus-5)
  classification: docs_gap
  turns: 14, duration: 88.1s
  backend: docker
  success check exit code: 1 (AssertionError: no table named orders)
  last docs page read before failure: https://duckdb.org/docs/stable/clients/python/overview
  docs pages read: 9
```

Start at the last page. The agent read nine pages, got that far, and produced a
database without the table the script expected. Either that page is missing a
step, or the next step is somewhere the agent never found. That is a bug report
against your documentation with a line number.

## Add a free precondition

`--agent replay` runs the literal commands your documentation tells a reader to
type. No model, no key, no cost.

```yaml
replay:
  - .venv/bin/pip install --quiet httpx
  - |
    cat > fetch.py <<'PY'
    import httpx

    print(httpx.get("https://www.python-httpx.org/").status_code)
    PY
  - .venv/bin/python fetch.py
```

```bash
quickstarted run journeys/httpx.yaml --agent replay
```

If the documented commands are broken, no reader stands a chance, and an agent
failure afterwards tells you nothing you did not already know. Run replay on
every push and agent mode on a schedule. See [Replay mode](../guides/replay-mode.md).

Next: [agent mode in depth](agent-mode.md), for choosing models, controlling
cost, and reading the trace.
