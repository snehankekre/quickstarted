# Results schema

> `results.json`, version 1.0. Fields get added, not repurposed.

Written to `<out>/results.json` when you pass `--out`. The version rises when a
field changes meaning, so anything parsing this file can check one number.

```json
{
  "schema_version": "1.0",
  "quickstarted_version": "0.2.0",
  "generated_at": "2026-07-26T04:11:07Z",
  "environment": {
    "python": "3.12.4",
    "platform": "Linux-6.8.0-x86_64",
    "hostname": "runner-1",
    "backend": "docker"
  },
  "repeat": 3,
  "duration_seconds": 214.7,
  "totals": {
    "runs": 6,
    "tokens": {"input": 88, "output": 9134, "cache_write": 60215, "cache_read": 402118},
    "estimated_cost_usd": null
  },
  "journeys": [ ... ]
}
```

`environment.backend` is the resolved backend, never `auto`. A published result
has to say what was enforced.

## Per journey

```json
{
  "journey": "duckdb-quickstart",
  "agent": "claude:claude-opus-5",
  "attempts": 3,
  "passes": 2,
  "evidential_runs": 3,
  "pass_rate": 0.6666666666666666,
  "discarded": {"infra_error": 1},
  "models_reported": ["claude-opus-5"],
  "suspect_pages": {"https://duckdb.org/docs/stable/clients/python/overview": 1},
  "tokens": {"input": 44, "output": 4567, "cache_write": 30107, "cache_read": 201059},
  "estimated_cost_usd": null,
  "runs": [ ... ]
}
```

| Field | Meaning |
| --- | --- |
| `attempts` | Runs started |
| `evidential_runs` | Runs that said something about the documentation |
| `passes` | Runs classified `passed` |
| `pass_rate` | `passes / evidential_runs`, or `null` when nothing was evidence |
| `discarded` | Counts by classification for non-evidential runs |
| `models_reported` | Distinct models the API actually served |
| `suspect_pages` | Last page read before each failure, most frequent first |
| `estimated_cost_usd` | `null` unless a price book was supplied |

`pass_rate` is `null` rather than `0` when no run produced evidence. Zero would
assert a documentation failure the runs do not support.

## Per run

```json
{
  "journey": "duckdb-quickstart",
  "attempt": 2,
  "agent": "claude:claude-opus-5",
  "model_reported": "claude-opus-5",
  "classification": "docs_gap",
  "passed": false,
  "evidential": true,
  "stop_reason": "completed",
  "turns": 14,
  "duration_seconds": 88.1,
  "backend": "docker",
  "enforced": true,
  "docs_pages_read": ["https://duckdb.org/docs/stable/clients/python/overview"],
  "suspect_page": "https://duckdb.org/docs/stable/clients/python/overview",
  "docs_bypass_attempts": 0,
  "success_check": {"exit_code": 1, "output": "AssertionError: no table named orders"},
  "tokens": {"input": 22, "output": 2100, "cache_write": 15000, "cache_read": 98000}
}
```

| Field | Meaning |
| --- | --- |
| `classification` | One of the six values; see [pass rates](../guides/pass-rates.md) |
| `evidential` | True for `passed` and `docs_gap` |
| `stop_reason` | Why the agent loop ended, before scoring |
| `enforced` | Whether the backend was a real boundary |
| `docs_pages_read` | Complete, because the shell cannot reach documentation |
| `docs_bypass_attempts` | Blocked attempts to fetch docs through the shell |
| `success_check.output` | Last 2000 characters of the script's output |

`stop_reason` and `classification` differ on purpose. A run can stop with
`completed` and still be classified `docs_gap`, which is the most common
failure: the agent believed it was done and the script disagreed.

## JUnit XML

```bash
quickstarted run journeys/*.yaml --junit junit.xml
```

A `docs_gap` becomes a `<failure>`. Everything non-evidential becomes an
`<error>`. Any dashboard that reads JUnit then distinguishes a broken quickstart
from a rate limit without knowing anything about this tool.
