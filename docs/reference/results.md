# Results schema

> `results.json`, version 2.0. New fields are added; existing ones keep their
> meaning.

Written to `<out>/results.json` when you pass `--out`. The version rises when a
field changes meaning, so anything parsing this file can check one number.

```json
{
  "schema_version": "2.0",
  "quickstarted_version": "0.4.0",
  "generated_at": "2026-07-26T04:11:07Z",
  "environment": {
    "python": "3.12.4",
    "platform": "Linux-6.8.0-x86_64",
    "hostname": "runner-1",
    "backend": "docker"
  },
  "repeat": 3,
  "duration_seconds": 214.7,
  "interrupted": false,
  "totals": {
    "runs": 6,
    "tokens": {"input": 88, "output": 9134, "cache_write": 60215, "cache_read": 402118},
    "estimated_cost_usd": 1.84,
    "unpriced_models": ["claude-opus-5"]
  },
  "tasks": [ ... ]
}
```

`environment.backend` is the resolved backend, never `auto`. A published result
has to say what was enforced.

`interrupted` is true when Ctrl-C or `--max-spend` stopped the sweep early. The
runs that had already finished are still here and still evidence, but a reader
comparing two documents needs to know one of them stopped short.

`unpriced_models` names every model the price book could not price. Their tokens
are in the token totals and their dollars are in nobody's, so a two-model sweep
could otherwise report one model's spend as the whole figure. An empty list is
the only way to read `estimated_cost_usd` as complete.

## Per task

```json
{
  "task": "duckdb-quickstart",
  "agent": "claude:claude-haiku-4-5-20251001",
  "attempts": 3,
  "passes": 2,
  "evidential_runs": 2,
  "pass_rate": 1.0,
  "discarded": {"budget_exhausted": 1},
  "skipped": 0,
  "models_reported": ["claude-haiku-4-5-20251001"],
  "suspect_pages": {"https://duckdb.org/docs/clients/python/overview": 1},
  "tokens": {"input": 25608, "output": 5387, "cache_write": 26486, "cache_read": 261469},
  "estimated_cost_usd": null,
  "runs": [ ... ]
}
```

Note the arithmetic, because it is the whole point of the schema. Three attempts,
one ran out of turns, so `evidential_runs` is 2 and `pass_rate` is 1.0. The rate
is over what produced evidence, never over what was attempted, and `attempts`
minus `evidential_runs` always equals `discarded` plus `skipped`. A consumer that
divides `passes` by `attempts` gets 0.67 and reports a documentation problem that
the runs do not support.

`suspect_pages` still records the page from the discarded run, since knowing
where a run ran out of turns is useful even when it cannot count toward a rate.

| Field | Meaning |
| --- | --- |
| `attempts` | Runs started |
| `evidential_runs` | Runs that said something about the documentation |
| `passes` | Runs classified `passed` |
| `pass_rate` | `passes / evidential_runs`, or `null` when nothing was evidence |
| `discarded` | Counts by classification for runs that should have produced evidence and did not |
| `skipped` | Runs that were never in scope, counted apart from `discarded` |
| `models_reported` | Distinct models the API actually served |
| `suspect_pages` | Last page read before each failure, most frequent first |
| `estimated_cost_usd` | `null` unless a price book was supplied |

`skipped` is not in `discarded` on purpose. Listing "nothing to run here" beside
a rate limit and a harness bug invites reading all three as damage. `attempts`
minus `evidential_runs` equals the sum of `discarded` plus `skipped`.

`pass_rate` is `null` rather than `0` when no run produced evidence. Zero would
assert a documentation failure the runs do not support.

## Per run

A real record, with the check's output trimmed to its first line:

```json
{
  "task": "fastapi-quickstart",
  "attempt": 1,
  "agent": "openai:gpt-5.2-2025-12-11",
  "model_reported": "gpt-5.2-2025-12-11",
  "classification": "docs_gap",
  "passed": false,
  "evidential": true,
  "stop_reason": "completed",
  "turns": 8,
  "duration_seconds": 65.85,
  "backend": "docker",
  "enforced": true,
  "image": "python:3.12-slim",
  "docs_pages_read": ["https://fastapi.tiangolo.com/tutorial/first-steps/"],
  "suspect_page": "https://fastapi.tiangolo.com/tutorial/first-steps/",
  "docs_bypass_attempts": 0,
  "success_check": {
    "exit_code": 1,
    "output": "GET /items/42 never answered correctly. Last attempt: URLError: <urlopen error [Errno 111] Connection refused>"
  },
  "tokens": {"input": 11121, "output": 628, "cache_write": 0, "cache_read": 56320}
}
```

`cache_write` is 0 and `cache_read` is not, because OpenAI does not bill cache
writes; the four counters mean the same thing across vendors but not every vendor
populates all four. See [cost and budgets](../guides/cost.md).

| Field | Meaning |
| --- | --- |
| `classification` | One of the six values; see [pass rates](../guides/pass-rates.md) |
| `evidential` | True for `passed` and `docs_gap` |
| `stop_reason` | Why the agent loop ended, before scoring |
| `enforced` | Whether the backend was a real boundary |
| `image` | Container image used; empty for backends that have none |
| `docs_pages_read` | Complete, because the shell cannot reach documentation |
| `docs_bypass_attempts` | Blocked attempts to fetch docs through the shell |
| `success_check.output` | Last 2000 characters of the script's output |

`stop_reason` and `classification` differ on purpose. A run can stop with
`completed` and still be classified `docs_gap`, which is the most common
failure: the agent believed it was done and the script disagreed.

## JUnit XML

```bash
quickstarted run tasks/*.yaml --junit junit.xml
```

A `docs_gap` becomes a `<failure>`. A `skipped` run becomes a `<skipped/>`,
which is the word JUnit already has for it. Everything else non-evidential
becomes an `<error>`. Any dashboard that reads JUnit then distinguishes a broken
quickstart from a rate limit without knowing anything about this tool.
