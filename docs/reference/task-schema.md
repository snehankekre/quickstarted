# Task schema

> Every field of a task file, and what the loader rejects.

A task is YAML. Unknown keys under `success`, `budgets` and `network` are
errors, so a typo fails loudly instead of being ignored.

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
| `image` | string | no | Container image for the `docker` backend |

## image

The default image is `python:3.12-slim`, which has no Node, no Go, and no Rust.
A task testing a JavaScript quickstart says so:

```yaml
name: vite-quickstart
image: node:22-slim
```

Precedence is task, then `--image`, then the default, because one invocation of
`quickstarted run tasks/*.yaml` covers a suite that mixes runtimes and a single
flag cannot serve all of it.

The resolved image is recorded in `results.json` and printed next to the
backend. A pass rate is not comparable across base images, so the number is
meaningless without it.

`quickstarted validate` warns when a success script calls `npm`, `npx`, `node`,
`pnpm`, `yarn`, or `bun` and no image is set, since that check would fail for a
reason that has nothing to do with the documentation.

The field is ignored by the `seatbelt` and `local` backends, which run on the
host and use whatever is installed there.

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
`release-assets.githubusercontent.com`, `crates.io`, `static.crates.io`,
`proxy.golang.org`, `deb.debian.org`, `security.debian.org`,
`archive.ubuntu.com`, `security.ubuntu.com`.

`release-assets.githubusercontent.com` is there because npm packages that ship
a prebuilt native binary fetch it during install. The Debian and Ubuntu mirrors
are there because a quickstart is allowed to open with `apt-get install`.
`raw.githubusercontent.com` is deliberately absent: projects serve their README
from it, and a documentation host the shell can reach is an attribution hole.

A host named here explicitly wins over the documentation rule, so a registry
that also serves documentation stays installable. The report notes the
resulting gap in attribution.

## success

| Field | Type | Meaning |
| --- | --- | --- |
| `script` | string | Shell run after the agent stops |
| `file` | path | A shell file to run instead, relative to the task file |
| `serve` | string | A long-running command to background first |
| `wait_http` | mapping | Poll an endpoint until it answers as you say it should |

At least one of `script` and `file` is required, and they are mutually
exclusive. The check runs in the same workspace, under the same backend, with
the same scrubbed environment. Exit code 0 is a pass. No other signal is
consulted, and no model sees this script.

The harness owns the mechanism. Every criterion is yours, which is why a task
with `serve` and nothing that asserts anything is a validation error rather
than a free pass: a server that boots and answers every request with a 500
would otherwise pass.

### file

```yaml
success:
  file: checks/fastapi.sh
```

The file is read when the task loads and carried as text, so shellcheck, syntax
highlighting and `bash -n` all work on it. It is never written into the
workspace. The workspace is the agent's own directory, and a success script it
could read is an answer key.

### serve and wait_http

```yaml
success:
  serve: .venv/bin/fastapi run app.py --host 127.0.0.1 --port $QS_PORT
  wait_http:
    path: /items/42
    json:
      item_id: 42
  script: test -f app.py
```

`$QS_PORT` is a free port picked for this task, from a range derived from the
task name so two tasks in one suite do not collide and a failure reproduces by
hand. `wait_http` backgrounds nothing itself; it polls, keeps the last error
instead of swallowing it, prints the server log when it gives up, and names the
reason on the final line, where the console summary shows it.

| `wait_http` field | Default | Meaning |
| --- | --- | --- |
| `path` | | Resolved against `http://127.0.0.1:$QS_PORT` |
| `url` | | A full URL, when the server is somewhere else |
| `status` | 200 | Status code the response must carry |
| `contains` | | Literal text the body must contain; a string or a list |
| `matches` | | Extended regular expression the body must match |
| `json` | | Key/value pairs the body must carry |
| `timeout` | 40 | Seconds to keep polling |

`json` matches by regular expression rather than parsing, so it tolerates
whitespace and quoting but knows nothing about nesting. When you need a real
parse, write it in the script and assert there.

### The helpers

Whatever form you use, these functions are defined for the check:

| Helper | What it does |
| --- | --- |
| `qs_fail "why"` | Print the reason and exit 1 |
| `qs_serve <command...>` | Background a command, capturing its log |
| `qs_wait_http <path\|url> [flags]` | The polling above, from shell |

`qs_serve` and `qs_wait_http` are what the declarative form generates, so a
check that outgrows the schema can drop to shell without losing anything.
[tasks/checks/fastapi.sh][fa] does exactly that, because the FastAPI tutorial
documents two ways to serve and requiring one of them would measure the task
author's expectation rather than the documentation.

[fa]: https://github.com/snehankekre/quickstarted/blob/main/tasks/checks/fastapi.sh

## budgets

| Field | Default | Meaning |
| --- | --- | --- |
| `max_turns` | 20 | Tool-use rounds before the run stops |
| `max_seconds` | 480 | Wall clock for the agent phase |
| `max_command_seconds` | 300 | Timeout for one command |
| `max_output_chars` | 20000 | Per command; head and tail are kept |
| `max_tokens` | 0 | All four token counters combined; 0 is unlimited |

Exceeding any of these classifies the run `budget_exhausted`, which stays out
of pass rates.

## Validation

```bash
quickstarted validate tasks/*.yaml
```

```
ok       tasks/duckdb-quickstart.yaml (duckdb-quickstart, replay+agent)
warning  pypi.org is declared a docs host, so the shell cannot reach it;
         installs that need it will fail. Add it under network.allow if that
         is intended.
```

Errors are fatal and exit 1: missing required fields, a non-http entrypoint, a
list field that is not a list of strings, an allowlist entry with a path in it,
unknown keys under `success`, `budgets` or `network`.

Warnings are about results rather than syntax, and every one of them describes a
way to get a number that is wrong rather than low:

- A check that requires `X/bin/` when neither `setup` nor `replay` creates it.
  An agent that names its environment differently then fails a check it should
  have passed.
- A check that can exit non-zero while printing nothing, which reports a page
  and no reason.
- A registry declared as a documentation host, which breaks the installs the
  quickstart needs.
- A success script that calls a Node tool with no `image` set, since the default
  image has no Node.

Notes are neither. They say what a choice implies, and both are legitimate
choices:

- A task with no `replay` block, so `--agent replay` skips it.
- A host that is both a documentation host and network-allowed, so pages the
  shell reads there are not recorded.

Validating no files at all exits 3 rather than 0, so a CI job pointed at the
wrong directory stops reporting success.

`--check-urls` also fetches each entrypoint, so a dead link surfaces before a
sweep pays for it rather than after.

## Editor support

```bash
quickstarted schema > task-schema.json
```

Task files scaffolded by `quickstarted init` carry the schema line already:

```yaml
# yaml-language-server: $schema=https://snehankekre.com/quickstarted/task-schema.json
```

Any editor speaking the language server protocol then completes field names and
marks unknown ones as you type.
