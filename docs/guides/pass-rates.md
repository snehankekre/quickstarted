# Pass rates

> Why a single run is a sample, and how runs that prove nothing stay out of
> your numbers.

The same documentation and the same model can pass at 10:00 and fail at 10:05.
Models are stochastic, networks are unreliable, and package registries have bad
days. A benchmark that publishes one run per project publishes noise with a
confident face on it.

```bash
quickstarted run tasks/*.yaml --agent claude --repeat 5 --workers 3
```

```
==============================================================
Suite: 3 task(s), repeat=5
  polars-quickstart (claude:claude-opus-5): pass rate 100% [5/5 evidential of 5 run(s)]
  duckdb-quickstart (claude:claude-opus-5): pass rate 60% [3/5 evidential of 5 run(s)]
      failed after: https://duckdb.org/docs/stable/clients/python/overview (2x)
  fastapi-quickstart (claude:claude-opus-5): pass rate 75% [3/4 evidential of 5 run(s)]
      discarded: infra_error=1
  tokens: 1204 in / 38210 out, cache 402113 written / 1889222 read
  wall clock: 512.3s
==============================================================
```

Read the DuckDB line as: five attempts, all five produced evidence, three
passed. Read the FastAPI line as: five attempts, one died on a rate limit and
was thrown away, three of the remaining four passed.

## Classifications

Every run gets exactly one.

| Classification | Meaning | In the pass rate |
| --- | --- | --- |
| `passed` | the success script exited 0 | yes |
| `docs_gap` | the agent finished, the success script failed | yes |
| `budget_exhausted` | out of turns, wall clock, or tokens | no |
| `infra_error` | rate limit, upstream 5xx, network failure | no |
| `harness_error` | misconfigured task, missing credentials, our bug | no |
| `agent_refusal` | the model declined the task | no |

Only the first two say anything about your documentation. The rest are excluded
from the numerator and the denominator alike, then reported under `discarded`.

The alternative is worse than useless. A sweep of fifty projects will hit 429s,
and counting those as failed quickstarts would name companies as having broken
documentation because your API key was throttled.

## No evidence is not zero

```
  some-task (claude:claude-opus-5): pass rate no evidence [0/0 evidential of 3 run(s)]
      discarded: infra_error=3
```

When nothing produced evidence, the pass rate is absent. Printing 0% would
assert that the documentation failed, which is a claim these runs do not
support. `SuiteResult.all_passed` treats this as a failure for CI purposes, so
a job still goes red and someone looks at it.

## Comparing models

Pass rates are never aggregated across models. Two models running the same
task are two measurements that happen to share a file.

```bash
quickstarted run tasks/duckdb-quickstart.yaml --agent claude --repeat 10 --out results/claude
quickstarted run tasks/duckdb-quickstart.yaml --agent openai --model gpt-5 --repeat 10 --out results/gpt5
```

If a single task somehow sees more than one served model, the summary warns
and tells you not to compare those runs.

## Parallelism

`--workers N` runs attempts concurrently. Each gets its own workspace, its own
container or sandbox, and its own proxy, so they cannot interfere. Documentation
fetches are still rate-limited per host, which is what keeps a fifty-project
sweep from behaving like a scraper.

Wall clock improves; token cost does not. Concurrency also raises your chance
of being rate-limited by the model vendor, which shows up as `infra_error`
rather than as failed documentation.
