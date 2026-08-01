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
          quickstarted run tasks/*.yaml \
            --agent replay --backend docker \
            --out results --junit junit.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: quickstarted-results
          path: results/
```

`quickstarted run` exits 1 on a documentation gap, so the job gates the merge.
It exits 2 when nothing produced evidence and 3 on a usage error such as a job
running in the wrong directory, which used to look like success. The full table
is in the [CLI reference](../reference/cli.md#exit-codes).

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
          quickstarted run tasks/*.yaml \
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
    agent: claude
    repeat: "3"
    backend: docker
    junit: junit.xml
```

Every input maps to the flag of the same name:

| Input | Default | Flag |
| --- | --- | --- |
| `tasks` | everything in `tasks/` | positional paths |
| `agent` | `replay` | `--agent` |
| `model` | | `--model` |
| `repeat` | `1` | `--repeat` |
| `workers` | `1` | `--workers` |
| `backend` | `docker` | `--backend` |
| `image` | | `--image` |
| `affordances` | `all` | `--affordances` |
| `probe-affordances` | `false` | `--probe-affordances` |
| `cache-dir` | | `--cache-dir` |
| `prices` | | `--prices` |
| `max-spend` | | `--max-spend` |
| `out` | `quickstarted-results` | `--out` |
| `junit` | | `--junit` |
| `github-summary` | `true` | `--github-summary` |
| `strict-inconclusive` | `false` | `--strict-inconclusive` |
| `allow-unenforced` | `false` | `--allow-unenforced` |
| `python-version` | `3.12` | the Python the action sets up |
| `working-directory` | `.` | where the CLI runs |

Leave `tasks` empty and the CLI runs everything in `tasks/`. The action always
writes `--out`, so the results directory exists to upload even when the run
went red.

Picking an agent picks the install: `agent: claude` installs
`quickstarted[claude,prices]`, so dollars appear in the job summary without a
price book. Runners are on Python 3.12, where the `prices` extra installs.

The `journeys` input that 0.3.0 kept as a deprecated alias was removed in
0.4.0, along with the `journeys/` path fallback.

## Rate limits should not read as broken docs

A 429 produces `infra_error`, which stays out of the pass rate. In JUnit XML it
becomes an `<error>` rather than a `<failure>`, so the distinction survives into
whatever dashboard reads the file.

The exit code carries it too. A sweep that produced no evidence at all exits 2,
not 1, so a workflow can tell "your quickstart is broken" from "we learned
nothing today":

```bash
quickstarted run --agent claude
case $? in
  0) ;;                                    # docs hold
  1) gh issue create --title "docs gap" ;; # a real failure, worth a human
  2) echo "no evidence; not a docs problem" ;;
esac
```

## Agent-only tasks are skipped, not failed

A task with no `replay` block has nothing for replay mode to run. It reports as
skipped, appears in JUnit as `<skipped/>`, and stays out of the discarded
counts. A suite of them used to report "no evidence" on every push, which reads
like the tool is broken rather than like there was nothing to do.

## What lands in the pull request

`--github-summary` appends the markdown report to the job summary, and it is on
by default in the composite action. A documentation gap also emits an
annotation anchored to the task file:

```
::error file=tasks/fastapi-quickstart.yaml,title=quickstarted::pass rate 0% for
fastapi-quickstart. check failed: nothing can serve app.py
Last documentation page read before failing: https://fastapi.tiangolo.com/...
```

For a human to read afterwards, `quickstarted report results/ --out report.html`
turns the artifact directory into one self-contained page.

If you would rather a job go red whenever any run failed to produce evidence:

```bash
quickstarted run tasks/*.yaml --agent claude --strict-inconclusive
```

## Gating on a regression rather than a verdict

Once you have a baseline, the question a scheduled job should answer is whether
today is worse than last week, not whether one run failed:

```bash
quickstarted run tasks/*.yaml --agent claude --repeat 10 --out today/
quickstarted diff baseline/results.json today/results.json --fail-on-regression
```

`--fail-on-regression` exits 1 only when a pass rate dropped by more than noise
at those sample sizes, so a job does not go red for a run that moved 8/10 to
7/10. See [pass rates](pass-rates.md#did-the-documentation-change-help).

## Caching documentation between runs

```bash
quickstarted run tasks/*.yaml --agent claude \
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

`--out` writes `results.json` (schema 2.0), a per-task `trace.jsonl`, a
Markdown report per run, and `suite.md`. Fields are added but not repurposed,
and the schema version goes up when that stops being true. See
[results schema](../reference/results.md).
