# CLI

> Every command and flag. `quickstarted` and `qstart` are the same program.

## quickstarted examples

```bash
quickstarted examples
quickstarted run --example httpx --agent replay
```

Three tasks ship inside the package (`httpx`, `streamlit`, `vite`), so a
`pip install` needs nothing cloned to produce a first result. `--example` works
on `run` and `validate`.

## quickstarted init

```bash
quickstarted init ENTRYPOINT [--name NAME] [--out PATH] [--force]
```

Scaffolds a task file from a documentation URL: the entrypoint filled in, the
host allowlist derived from it, a commented goal, a starter check, and the
`yaml-language-server` line that gives editors completion. The result validates
as written. The name comes from the host (`fastapi.tiangolo.com` is `fastapi`,
`docs.streamlit.io` is `streamlit`) unless you pass `--name`.

## quickstarted validate

```bash
quickstarted validate tasks/*.yaml [--check-urls]
```

Parses each file, prints its name and available modes, and warns about the
mistakes that produce a wrong number rather than a low one: a check requiring an
environment directory nothing creates, a check that can fail without saying why,
an allowlist that would break installs. Exits 1 if any file is invalid.

`--check-urls` also fetches every entrypoint, honouring `robots.txt`, so a dead
link surfaces before a sweep pays for it.

## quickstarted check

```bash
quickstarted check TASK --sandbox PATH [--backend BACKEND] [--image IMAGE]
quickstarted check TASK --show
```

Runs only the success script, against a workspace an earlier `--keep-sandbox`
run left behind. No model, no key, no cost, and the same backend that judged the
run. Exits 0 when the check passes. `--show` prints the script that would run,
helper prelude included, and exits without running anything.

## quickstarted diff

```bash
quickstarted diff before/results.json after/results.json [--fail-on-regression]
```

Compares two result documents and says whether the change is real:

```
  fastapi-quickstart
      2/5 (40%)  ->  5/5 (100%)
      inside the noise, p=0.167
```

Every comparison carries a two-sided Fisher exact test. Fisher because the
samples are tiny and a normal approximation would lie about them; exact because
it costs nothing but `math.comb`.

When no possible outcome at these sample sizes could have reached significance,
it says that instead of reporting a result:

```
      1/3 (33%)  ->  3/3 (100%)
      inside the noise, and no result at 3 vs 3 runs could have cleared
      p<0.05 (best possible p=0.100)
```

Three attempts a side can never produce a significant difference, whatever
happens. Four can. That is worth knowing before a sweep rather than after.

Two runs served by different models are reported as not comparable rather than
subtracted, for the same reason pass rates are never aggregated across models.
`--fail-on-regression` exits 1 when a pass rate dropped by more than noise,
which is the CI form of the question.

## quickstarted show

```bash
quickstarted show results/httpx-quickstart/trace.jsonl [--verbose]
```

The trace as a person reads it:

```
[   0.0s] will-fail on seatbelt, agent replay, attempt 1
[   0.3s] read https://example.com/
[   0.3s] $ true
[   0.3s]   exit 0
[   0.3s] success check exited 1
           | check failed: nope.txt was never created
[   0.3s] docs_gap (stop reason: completed)
```

Commands that failed print their output; ones that succeeded stay quiet until
`--verbose`. Everything else is still in the JSONL, and `jq` reads it.

## quickstarted report

```bash
quickstarted report results/ --out report.html
```

One self-contained page: pass rates, every documentation gap with the check's
own output and the page the agent was on, and the transcripts folded away
behind disclosures. No external stylesheet, script, or font, because a report
that fetches anything renders differently for the person you sent it to.

## quickstarted schema

```bash
quickstarted schema > task-schema.json
```

Prints the task file JSON Schema. The published copy that scaffolded tasks point
at lives at
[snehankekre.com/quickstarted/task-schema.json](https://snehankekre.com/quickstarted/task-schema.json).

## quickstarted doctor

```bash
quickstarted doctor [--prices PATH]
```

Reports which execution backends this machine has, which one `auto` would
choose, whether a price book loaded, and whether an API key is visible. Run it
before trusting any number the tool produces.

## quickstarted run

```bash
quickstarted run [TASK ...] [options]
```

Exit codes are in the table below.

With no paths it runs every `.yaml` in `tasks/`, or in the current directory if
there is no `tasks/`. A path may be a file, a directory, or a glob, and globs
are expanded here as well as by the shell, because PowerShell hands
`tasks/*.yaml` through literally.

### Watching a run

| Flag | Default | Meaning |
| --- | --- | --- |
| `--verbose` | off | Also stream every shell command the agent runs |
| `--quiet` | off | Print only the per-run summaries |

A run prints each documentation page as the agent reads it, and the success
check's exit code, so a slow model and a hung container stop looking identical.
Under `--workers` above one, every line is labelled with its task and attempt.

### Agent selection

| Flag | Default | Meaning |
| --- | --- | --- |
| `--agent` | `replay` | `replay`, `claude`, `openai`, or `gemini` |
| `--model` | vendor default | Required for `openai` and `gemini` |

### Repetition and concurrency

| Flag | Default | Meaning |
| --- | --- | --- |
| `--repeat` | 1 | Attempts per task; above 1 reports a pass rate |
| `--workers` | 1 | Attempts run in parallel |

### Execution

| Flag | Default | Meaning |
| --- | --- | --- |
| `--backend` | `auto` | `auto`, `docker`, `seatbelt`, `local` |
| `--image` | `python:3.12-slim` | Container image for the Docker backend, for tasks that do not set `image` themselves |
| `--allow-unenforced` | off | Permit the `local` backend |
| `--keep-sandbox` | off | Leave the workspace on disk for inspection |

### Documentation fetching

| Flag | Default | Meaning |
| --- | --- | --- |
| `--affordances` | `all` | `all`, or `none` to withhold llms.txt and .md |
| `--probe-affordances` | off | Record which machine-facing files exist |
| `--cache-dir` | none | Content-addressed cache directory |
| `--refresh` | off | Re-fetch cached pages and flag content changes |
| `--offline` | off | Use the cache only; never fetch |
| `--rate-limit` | 1.0 | Minimum seconds between requests to one host |
| `--ignore-robots` | off | Fetch where robots.txt disallows |

### Output

| Flag | Default | Meaning |
| --- | --- | --- |
| `--out` | none | Directory for traces, reports, and results.json |
| `--junit` | none | Path for a JUnit XML report |
| `--prices` | `$QUICKSTARTED_PRICES` | Price book for cost estimates |
| `--refresh-prices` | off | Fetch current rates before pricing |
| `--max-spend` | none | Stop once the estimated cost reaches this many dollars |
| `--github-summary` | off | Append the markdown report to `$GITHUB_STEP_SUMMARY` |
| `--strict-inconclusive` | off | Treat "no evidence" as failure (exit 1, not 2) |

Inside a GitHub workflow a documentation gap also emits an annotation pointing
at the task file that defines it, so the failure lands beside the diff rather
than inside a log.

## Configuration file

`quickstarted.yaml`, at the root of your project or any directory above the one
you run from, supplies flags you did not type and defaults for every task:

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

A flag you typed beats `run:`, and a task file beats `tasks:`. `run:` accepts
`backend`, `image`, `cache_dir`, `prices`, `out`, `junit` and `workers`, and
refuses `agent`, `model`, `repeat` and `affordances`, which change what a result
means and belong in the command you can see.

## Exit codes

Meant to be branched on, because "your quickstart is broken" and "somebody
else's API returned 429" need different people to do different things.

| Code | Meaning |
| --- | --- |
| 0 | Every task passed every attempt that produced evidence |
| 1 | A documentation gap: a run finished and the check failed |
| 2 | No evidence at all, from rate limits, budgets, or nothing to run |
| 3 | Usage: no tasks found, an invalid task file, a refused backend |
| 130 | Interrupted, or stopped at `--max-spend` |

`--strict-inconclusive` collapses 2 into 1 for anyone who would rather a job go
red whenever a run failed to produce evidence.

```bash
quickstarted run --agent claude
case $? in
  0) echo "docs hold" ;;
  1) echo "a real documentation gap, page the docs owner" ;;
  2) echo "we learned nothing; retry later, do not page anyone" ;;
esac
```

## Examples

```bash
# Scaffold a task, then check it before spending anything.
quickstarted init https://fastapi.tiangolo.com/tutorial/first-steps/
quickstarted validate tasks/fastapi-quickstart.yaml --check-urls

# When the host does not name the project, say so. docs.pola.rs would be "pola".
quickstarted init https://docs.pola.rs/user-guide/getting-started/ --name polars-quickstart

# Iterate on a success check for a second per attempt instead of a run per attempt.
quickstarted run tasks/x.yaml --agent claude --keep-sandbox
quickstarted check tasks/x.yaml --sandbox /tmp/quickstarted-8ilw9l6v/workspace

# Gate a pull request, free and deterministic.
quickstarted run tasks/*.yaml --agent replay --backend docker --junit junit.xml

# Nightly pass rate across three attempts.
quickstarted run tasks/*.yaml --agent claude --repeat 3 --workers 2 --out results/

# Does llms.txt help? Run both halves and compare.
quickstarted run tasks/x.yaml --agent claude --repeat 10
quickstarted run tasks/x.yaml --agent claude --repeat 10 --affordances none

# Reproduce yesterday's documentation exactly.
quickstarted run tasks/x.yaml --agent claude --cache-dir .cache --offline

# Debug a failure by keeping the workspace.
quickstarted run tasks/x.yaml --agent claude --keep-sandbox --backend local --allow-unenforced
```
