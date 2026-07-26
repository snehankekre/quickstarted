# Journey schema

> Every field of a journey file, and what the loader rejects.

A journey is YAML. Unknown keys under `budgets` and `network` are errors, so a
typo fails loudly instead of being ignored.

```yaml
name: duckdb-quickstart
goal: >
  Using DuckDB from Python, create shop.db containing a table "orders" ...
docs:
  entrypoint: https://duckdb.org/docs/stable/clients/python/overview
  allow:
    - duckdb.org
network:
  allow:
    - files.pythonhosted.org
setup:
  - python3 -m venv .venv
success:
  script: |
    set -e
    test -f script.py
budgets:
  max_turns: 20
  max_seconds: 420
replay:
  - .venv/bin/pip install --quiet duckdb
  - .venv/bin/python script.py
```

## Top level

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `name` | string | yes | Identifier used in output paths and reports |
| `goal` | string | yes | The only instruction the agent receives |
| `docs` | mapping | yes | Where the documentation lives |
| `success` | mapping | yes | The script that decides pass or fail |
| `setup` | list of strings | no | Commands run before the agent starts |
| `replay` | list of strings | no | The documented commands, for replay mode |
| `network` | mapping | no | Hosts the shell may reach |
| `budgets` | mapping | no | Limits on the agent phase |

## docs

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `entrypoint` | http(s) URL | yes | First page the agent is pointed at |
| `allow` | list of hostnames | no | Additional documentation hosts |

The entrypoint's host is added to the allowlist automatically. Entries are bare
hostnames (`docs.pola.rs`), and a hostname matches itself and its subdomains.

Documentation hosts are readable **only** through `read_docs`. The shell cannot
reach them, which is what keeps the record of pages read complete.

## network

| Field | Type | Meaning |
| --- | --- | --- |
| `allow` | list of hostnames | Added to the default registry list |
| `only` | list of hostnames | Replaces the default list entirely |

Defaults: `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`,
`github.com`, `codeload.github.com`, `objects.githubusercontent.com`,
`crates.io`, `static.crates.io`, `proxy.golang.org`.

A host named here explicitly wins over the documentation rule, so a registry
that also serves documentation stays installable. The report notes the
resulting gap in attribution.

## success

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `script` | string | yes | Shell script run after the agent stops |

Runs in the same workspace, under the same backend, with the same scrubbed
environment. Exit code 0 is a pass. No other signal is consulted, and no model
sees this script.

## budgets

| Field | Default | Meaning |
| --- | --- | --- |
| `max_turns` | 20 | Tool-use rounds before the run stops |
| `max_seconds` | 900 | Wall clock for the agent phase |
| `max_command_seconds` | 300 | Timeout for one command |
| `max_output_chars` | 20000 | Per command; head and tail are kept |
| `max_tokens` | 0 | All four token counters combined; 0 is unlimited |

Exceeding any of these classifies the run `budget_exhausted`, which stays out
of pass rates.

## Validation

```bash
quickstarted validate journeys/*.yaml
```

```
ok       journeys/duckdb-quickstart.yaml (duckdb-quickstart, replay+agent)
warning  pypi.org is declared a docs host, so the shell cannot reach it;
         installs that need it will fail. Add it under network.allow if that
         is intended.
```

Errors are fatal and exit 1: missing required fields, a non-http entrypoint, a
list field that is not a list of strings, an allowlist entry with a path in it,
unknown `budgets` or `network` keys.
