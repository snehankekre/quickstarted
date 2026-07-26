# Writing journeys

> The rules that separate a journey which measures your docs from one that
> measures luck.

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

An early journey in this repo checked for a `.venv` directory that the
documentation never mentions. An agent created `venv/` instead, did everything
else correctly, and was marked as a documentation failure.

If `setup` creates something the success script depends on, that is fine. The
agent is told what setup already ran, so it will not rebuild it. Anything else
your script depends on has to come from the documentation, or you are testing
telepathy.

## Let the harness verify

If the goal is a running server, start it in the success script, ask it a
question, and stop it. Do not ask the agent to leave a process running, and
never take its word for the result.

```yaml
success:
  script: |
    set -e
    test -f app.py
    .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8611 > server.log 2>&1 &
    pid=$!
    ok=0
    for _ in $(seq 1 40); do
      sleep 1
      if curl -sf http://127.0.0.1:8611/items/42 | grep -q '"item_id"'; then ok=1; break; fi
    done
    kill "$pid" 2>/dev/null || true
    test "$ok" = "1"
```

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
journey declares one as a documentation host.

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
pass, the journey is not ready for a model, and any failure you see afterwards
tells you nothing about your documentation.

```bash
quickstarted run journeys/mine.yaml --agent replay
quickstarted run journeys/mine.yaml --agent claude
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

A journey that routinely exhausts its budget produces `budget_exhausted`, which
is excluded from pass rates. That is the correct outcome, and it also means a
too-small budget quietly removes the journey from your results. Check the
discarded counts in the summary.

Full field list: [journey schema](../reference/journey-schema.md).
