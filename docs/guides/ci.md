# Running in CI

> Gate merges on replay, run agent mode on a schedule, and keep a rate limit
> from turning a job red.

## Replay on every pull request

Replay costs nothing and needs no API key, so it belongs on every change to
your documentation.

```yaml
name: docs
on: [pull_request]

jobs:
  replay:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install quickstarted
      - run: quickstarted doctor
      - run: |
          quickstarted run journeys/*.yaml \
            --agent replay --backend docker \
            --out results --junit junit.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: quickstarted-results
          path: results/
```

`quickstarted run` exits 1 when any journey fails, so the job gates the merge.
GitHub runners have Docker, so `--backend docker` gets you an enforced boundary
at no extra cost.

## Agent mode on a schedule

Agent runs cost tokens and take minutes. Run them nightly, and after a model
ships.

```yaml
name: docs-agent
on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch:

jobs:
  agent:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "quickstarted[claude]"
      - env:
          QUICKSTARTED_ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          quickstarted run journeys/*.yaml \
            --agent claude --repeat 3 --workers 2 \
            --backend docker --out results --junit junit.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: quickstarted-results
          path: results/
```

`--repeat 3` turns a verdict into a rate, which is what you want from a
scheduled job. One nightly failure means very little on its own.

## The composite action

```yaml
- uses: snehankekre/quickstarted@v0
  with:
    journeys: journeys/*.yaml
    agent: claude
    repeat: "3"
    backend: docker
    junit: junit.xml
```

Inputs: `journeys`, `agent`, `model`, `repeat`, `workers`, `backend`,
`affordances`, `python-version`, `out`, `junit`.

## Rate limits should not read as broken docs

A 429 produces `infra_error`, which stays out of the pass rate. In JUnit XML it
becomes an `<error>` rather than a `<failure>`, so the distinction survives into
whatever dashboard reads the file.

If you would rather a job go red whenever any run failed to produce evidence:

```bash
quickstarted run journeys/*.yaml --agent claude --strict-inconclusive
```

## Caching documentation between runs

```bash
quickstarted run journeys/*.yaml --agent claude \
  --cache-dir .quickstarted-cache --refresh
```

The cache is content-addressed, so a rerun reads the same bytes the first run
did. With `--refresh`, pages are re-fetched and any whose content changed are
flagged in the trace as `docs_changed`. That is worth surfacing: a pass rate
that moved because the documentation moved is a different story from one that
moved because the model changed.

Persist the directory with `actions/cache` to make reruns cheaper and to be a
better citizen to the sites you are fetching from.

## Machine-readable output

`--out` writes `results.json` (schema 1.0), a per-journey `trace.jsonl`, a
Markdown report per run, and `suite.md`. Fields are added but not repurposed,
and the schema version goes up when that stops being true. See
[results schema](../reference/results.md).
