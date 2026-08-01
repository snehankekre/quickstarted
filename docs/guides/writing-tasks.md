# Writing tasks

> The rules that separate a task which measures your docs from one that
> measures luck.

## Start from a scaffold

```bash
quickstarted init https://fastapi.tiangolo.com/tutorial/first-steps/
```

That writes `tasks/fastapi-quickstart.yaml` with the entrypoint filled in, the
host allowlist derived from the URL, and a schema line that gives any
language-server editor completion on every field below. It validates as written,
so you can edit it one field at a time and check your work as you go.

## Success checks you can copy

The success script is the only thing standing between a report and a model's
opinion of itself, which is why there is no way to skip it. It is usually two
or three lines. You are asserting what your tutorial already promises, so start
by asking what you would type in a terminal to check that the tutorial worked.

```yaml
# The file the tutorial told the reader to create
success:
  script: test -f app.py
```

```yaml
# The package installed and imports
success:
  script: .venv/bin/python -c "import streamlit"
```

```yaml
# The command exists and runs
success:
  script: .venv/bin/mytool --version
```

```yaml
# The output contains what the page said it would
success:
  script: .venv/bin/python fetch.py | grep -q 200
```

```yaml
# Several of the above, stopping at the first failure
success:
  script: |
    set -e
    test -f fetch.py
    .venv/bin/python -c "import httpx"
    .venv/bin/python fetch.py | grep -q 200
```

`set -e` is what makes a multi-line script stop at the first failing line. It
is the only piece of shell syntax you need.

When a check is easier to express in Python than in shell, write it in Python.
Nothing prefers bash:

```yaml
success:
  script: |
    set -e
    .venv/bin/python - <<'PY'
    import csv
    rows = list(csv.DictReader(open("out.csv")))
    assert [r["name"] for r in rows] == ["grace", "ada", "edsger"], rows
    PY
```

A weaker check that you trust beats a strict one you cannot debug, and you can
tighten it later.

## Keep a long check in a file

Once a check is more than a few lines, put it beside the task and point at it:

```yaml
success:
  file: checks/fastapi.sh
```

Now shellcheck, syntax highlighting and `bash -n` work on it, and you can read
it without counting YAML indentation. The file is read when the task loads, so
it never lands in the workspace where the agent could read its own success
criteria.

## Develop a check without paying for a run

`--keep-sandbox` leaves the workspace in place, and `quickstarted check` runs
your success script against it again. No model, no key, no cost, and the same
backend that will judge it for real:

```bash
quickstarted run tasks/mine.yaml --agent claude --keep-sandbox
# ... sandbox kept at: /tmp/quickstarted-8ilw9l6v/workspace

quickstarted check tasks/mine.yaml --sandbox /tmp/quickstarted-8ilw9l6v/workspace
```

That loop takes about a second, so the check can be wrong ten times before it is
right. `--show` prints the script the harness will actually run, helpers
included.

Running the script by hand instead judges it in a different environment from the
one that will judge it for real: another Python, another PATH, and no container.

## Make a failing check say what it saw

The exit code decides the verdict. The output is the bug report, and they are
separate jobs. `test -f out.csv` needs no output because the message is obvious
from the check itself. A check that starts a server and polls it needs to say
what happened, or a failure arrives with an exit code and nothing else.

This bit us. A benchmark run reported `docs_gap` on the FastAPI task with exit
code 1 and an empty message, which is unactionable: no way to tell a missing
route from a server that never booted. The cause was `set -e` aborting the
script at the failing command, before the lines meant to report the problem
could run.

`serve` and `wait_http` exist because of that failure. They keep the last error
rather than swallowing it, print the server log when they give up, and put the
reason on the final line, which is the line the console summary shows.
"Connection refused" and "HTTP 200 with the wrong body" are different bugs in
your documentation, and a bare exit code cannot tell them apart.

For a check with several assertions, one line each is enough. `qs_fail` prints
the reason and stops, and `||` keeps `set -e` from aborting before the message
prints:

```yaml
success:
  script: |
    set -e
    test -f pyproject.toml || qs_fail "no pyproject.toml, so uv never created a project"
    test -f uv.lock || qs_fail "no uv.lock, so the project was never locked"
    grep -q httpx pyproject.toml || qs_fail "httpx is not a dependency in pyproject.toml"
```

That run reports `check failed: httpx is not a dependency in pyproject.toml`
instead of `exit code: 1`, which is the difference between a page to go and read
and a page to go and guess about.

`quickstarted validate` warns when a check has several assertions and no way to
report which one failed, so this is catchable before a run rather than after.

`quickstarted run` says so when a check stays quiet:

```
  success check exit code: 1
  note: the check printed nothing, so this failure cannot be diagnosed.
        Have it say what it saw.
```

## Assert the data

Check the outcome the documentation promises. Do not check how the agent got
there.

```yaml
# Good: any correct route passes.
success:
  script: |
    set -e
    .venv/bin/python - <<'PY'
    import csv
    rows = list(csv.DictReader(open("out.csv")))
    assert [r["name"] for r in rows] == ["grace", "ada", "edsger"], rows
    PY
```

```yaml
# Bad: passes only if the agent used one particular function.
success:
  script: grep -q "pl.read_csv" script.py
```

The second version fails a reader who used `scan_csv`, which the documentation
also recommends. You would be measuring your own expectations.

## Do not assert incidental paths

An early task in this repo checked for a `.venv` directory that the
documentation never mentions. An agent created `venv/` instead, did everything
else correctly, and was marked as a documentation failure.

If `setup` creates something the success script depends on, that is fine. The
agent is told what setup already ran, so it will not rebuild it. Anything else
your script depends on has to come from the documentation, or you are testing
telepathy.

## Let the harness verify

If the goal is a running server, the harness starts it, asks it a question, and
stops it. Do not ask the agent to leave a process running, and never take its
word for the result:

```yaml
success:
  serve: .venv/bin/fastapi run app.py --host 127.0.0.1 --port $QS_PORT
  wait_http:
    path: /items/42
    json:
      item_id: 42
  script: test -f app.py
```

`$QS_PORT` is a free port picked for this task. The polling, the log capture,
the last error and the kill are the harness's job, which is the point: the
hand-written version of this block was twenty lines, four tasks in this repo
each had their own copy, and the copies were where the `if !` idiom got dropped.

When the shape does not fit, the same helpers are available directly:

```yaml
success:
  script: |
    set -e
    if [ -x .venv/bin/fastapi ]; then
      qs_serve .venv/bin/fastapi run app.py --port "$QS_PORT"
    elif .venv/bin/python -c "import uvicorn" 2>/dev/null; then
      qs_serve .venv/bin/python -m uvicorn app:app --port "$QS_PORT"
    else
      qs_fail "neither the fastapi CLI nor uvicorn is installed"
    fi
    qs_wait_http /items/42 --json item_id=42
```

That is [the real FastAPI check][fa], and it branches because the tutorial
documents two ways to serve. Requiring one of them would measure my expectation
rather than the documentation, and it already cost three runs once.

[fa]: https://github.com/snehankekre/quickstarted/blob/main/tasks/checks/fastapi.sh

## Separate documentation hosts from registries

`docs.allow` hosts are readable only through `read_docs`. The shell cannot
reach them. Put `pypi.org` there and `pip install` stops working, which shows
up as a `harness_error` rather than a documentation problem.

```yaml
docs:
  entrypoint: https://docs.pola.rs/user-guide/getting-started/
  allow:
    - docs.pola.rs      # documentation
network:
  allow:
    - files.pythonhosted.org   # only if the defaults are not enough
```

Common registries are allowed by default. `quickstarted validate` warns when a
task declares one as a documentation host.

When a host genuinely serves both, name it under `network.allow` as well. The
installs then work, and the report notes that reads from that host are no
longer fully attributable.

## Write the goal for a stranger

The goal is the only instruction the agent gets. It should describe an outcome
in the words a user would use, and avoid naming the API that produces it.

```yaml
# Good
goal: >
  Using Polars, read people.csv, keep rows where age is over 30, sort by age
  descending, and write the result to out.csv with the same column names.

# Bad: hands over the answer
goal: >
  Call pl.read_csv, then .filter(pl.col("age") > 30), then .sort, then
  .write_csv.
```

## Start in replay

Write the replay commands first and run them. If the documented commands do not
pass, the task is not ready for a model, and any failure you see afterwards
tells you nothing about your documentation.

```bash
quickstarted run tasks/mine.yaml --agent replay
quickstarted run tasks/mine.yaml --agent claude
```

## Budget deliberately

```yaml
budgets:
  max_turns: 20            # tool-use rounds
  max_seconds: 420         # wall clock for the agent phase
  max_command_seconds: 300 # one command
  max_output_chars: 20000  # per command, head and tail kept
  max_tokens: 0            # 0 means unlimited
```

A task that routinely exhausts its budget produces `budget_exhausted`, which
is excluded from pass rates. That is the correct outcome, and it also means a
too-small budget quietly removes the task from your results. Check the
discarded counts in the summary.

## Say the shared parts once

A suite of tasks usually wants the same setup and the same budgets, and a repo
usually wants the same flags on every invocation. `quickstarted.yaml` at the
root of your project says so once:

```yaml
run:
  backend: docker
  cache_dir: .cache
tasks:
  setup:
    - python3 -m venv .venv
  budgets:
    max_seconds: 420
```

The more specific statement wins in both directions. A task file beats `tasks:`,
and a flag you typed beats `run:`. Lists replace rather than combine, because a
config `setup` and a task `setup` running one after the other would execute both
in an order nobody chose.

`run:` accepts `backend`, `image`, `cache_dir`, `prices`, `out`, `junit` and
`workers`. It deliberately refuses `agent`, `model`, `repeat` and `affordances`:
a file that quietly changed which model served a task, or how many attempts a
rate was computed over, would make two runs incomparable for a reason invisible
in the command you typed.

Full field list: [task schema](../reference/task-schema.md).
