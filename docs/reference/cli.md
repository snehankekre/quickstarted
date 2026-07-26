# CLI

> Every command and flag. `quickstarted` and `qstart` are the same program.

## quickstarted validate

```bash
quickstarted validate journeys/*.yaml
```

Parses each file, prints its name and available modes, and warns about
allowlist mistakes that would break installs. Exits 1 if any file is invalid.

## quickstarted doctor

```bash
quickstarted doctor [--prices PATH]
```

Reports which execution backends this machine has, which one `auto` would
choose, whether a price book loaded, and whether an API key is visible. Run it
before trusting any number the tool produces.

## quickstarted run

```bash
quickstarted run JOURNEY [JOURNEY ...] [options]
```

Exits 0 when every journey passed every attempt that produced evidence, and 1
otherwise.

### Agent selection

| Flag | Default | Meaning |
| --- | --- | --- |
| `--agent` | `replay` | `replay`, `claude`, `openai`, or `gemini` |
| `--model` | vendor default | Required for `openai` and `gemini` |

### Repetition and concurrency

| Flag | Default | Meaning |
| --- | --- | --- |
| `--repeat` | 1 | Attempts per journey; above 1 reports a pass rate |
| `--workers` | 1 | Attempts run in parallel |

### Execution

| Flag | Default | Meaning |
| --- | --- | --- |
| `--backend` | `auto` | `auto`, `docker`, `seatbelt`, `local` |
| `--image` | `python:3.12-slim` | Container image for the Docker backend |
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
| `--strict-inconclusive` | off | Exit 1 if any run produced no evidence |

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Every journey passed every evidential attempt |
| 1 | A journey failed, a file was invalid, or the backend was refused |

## Examples

```bash
# Gate a pull request, free and deterministic.
quickstarted run journeys/*.yaml --agent replay --backend docker --junit junit.xml

# Nightly pass rate across three attempts.
quickstarted run journeys/*.yaml --agent claude --repeat 3 --workers 2 --out results/

# Does llms.txt help? Run both halves and compare.
quickstarted run journeys/x.yaml --agent claude --repeat 10
quickstarted run journeys/x.yaml --agent claude --repeat 10 --affordances none

# Reproduce yesterday's documentation exactly.
quickstarted run journeys/x.yaml --agent claude --cache-dir .cache --offline

# Debug a failure by keeping the workspace.
quickstarted run journeys/x.yaml --agent claude --keep-sandbox --backend local --allow-unenforced
```
