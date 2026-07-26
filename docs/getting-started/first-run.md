# Your first run

> Write a journey, run it in replay mode, and watch it fail on purpose.

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
replay:
  - .venv/bin/pip install --quiet httpx
  - |
    cat > fetch.py <<'PY'
    import httpx

    print(httpx.get("https://www.python-httpx.org/").status_code)
    PY
  - .venv/bin/python fetch.py
```

Check that it parses:

```bash
quickstarted validate journeys/httpx.yaml
```

```
ok       journeys/httpx.yaml (httpx-quickstart, replay+agent)
```

## Run it

`replay` runs the literal commands your documentation tells a reader to type.
It uses no model and costs nothing.

```bash
quickstarted run journeys/httpx.yaml --agent replay
```

```
[PASS] httpx-quickstart (replay)
  classification: passed
  stop reason: completed
  turns: 4, duration: 6.2s
  backend: docker
  docs pages read: 1
```

## Break it on purpose

Replay is a floor. If the documented commands fail, no human reader stands a
chance, so there is no point asking a model to try. Prove the failure path by
editing the replay block to install a package that does not exist:

```yaml
replay:
  - .venv/bin/pip install --quiet httpxx
```

```
[INCONCLUSIVE] httpx-quickstart (replay)
  classification: harness_error
  stop reason: command_failed (replay step 1 failed: .venv/bin/pip install --quiet httpxx)
```

Note the classification. quickstarted separates "your documentation is wrong"
from "this run never produced evidence", and a command that could not reach a
package registry lands in the second group. Guessing between them is how
benchmarks end up publishing noise. See [Pass rates](../guides/pass-rates.md).

## What just happened

The harness created a throwaway workspace, ran your `setup` commands in it,
then ran the replay commands one at a time and stopped at the first non-zero
exit. Afterwards it ran `success.script` in the same workspace. Exit code 0 is
a pass and nothing else is.

Every command ran inside a sandbox whose only route to the network is a proxy
the harness owns. The entrypoint was fetched through the recorded `read_docs`
path, which is why the run reports one page read.

Next: [agent mode](agent-mode.md), where a model has to find its own way.
