# Pass rates

> Why a single run is a sample, and how runs that prove nothing stay out of
> your numbers.

The same documentation and the same model can pass at 10:00 and fail at 10:05.
Models are stochastic, networks are unreliable, and package registries have bad
days. A benchmark that publishes one run per project publishes noise with a
confident face on it.

```bash
quickstarted run tasks/*.yaml --agent claude --model claude-haiku-4-5 --repeat 3
```

Four lines from a real suite of fourteen:

```
  duckdb-quickstart (claude:claude-haiku-4-5-20251001): pass rate 100% [2/2 evidential of 3 run(s)]
      discarded: budget_exhausted=1
      failed after: https://duckdb.org/docs/clients/python/overview (1x)
  fastapi-quickstart (claude:claude-haiku-4-5-20251001): pass rate 0% [0/3 evidential of 3 run(s)]
      failed after: https://fastapi.tiangolo.com/tutorial/first-steps/ (3x)
  polars-quickstart (claude:claude-haiku-4-5-20251001): pass rate 100% [3/3 evidential of 3 run(s)]
  uv-quickstart (claude:claude-haiku-4-5-20251001): pass rate 67% [2/3 evidential of 3 run(s)]
      failed after: https://docs.astral.sh/uv/guides/projects/ (1x)
```

Read the DuckDB line as: three attempts, one ran out of turns and was thrown
away, and both of the remaining two passed. The rate is 100% over two samples,
which is a weaker claim than 100% over three and is reported as such.

Read the FastAPI line as: three attempts, all three produced evidence, none
passed, and every one of them was on the same page when it went wrong. Three out
of three on one page is the strongest signal this tool emits.

The uv line is the ambiguous case, and the common one: two passes, one failure,
no way to tell from three runs whether that is a real gap or variance. Raise the
repeat count before drawing a conclusion from a number like it.

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

## Did the documentation change help?

```bash
quickstarted run --agent claude --repeat 10 --out before/
# edit the page
quickstarted run --agent claude --repeat 10 --out after/
quickstarted diff before/results.json after/results.json
```

```
  fastapi-quickstart
      2/10 (20%)  ->  8/10 (80%)
      improved, p=0.023
```

The p-value is a two-sided Fisher exact test on passes and failures. It is
there because the honest answer to "3/5 became 4/5" is that nothing was
measured, and a tool that prints `+20 points` without saying so is inviting
somebody to publish it.

The more useful line is the one that appears when the experiment was too small
to answer the question at all:

```
      inside the noise, and no result at 3 vs 3 runs could have cleared
      p<0.05 (best possible p=0.100)
```

At three attempts a side, no outcome clears the bar, including a clean sweep
from nothing to everything. Four is the smallest number that can. Budget for
that before spending, not after reading a result you cannot use.

Full flags: [quickstarted diff](../reference/cli.md#quickstarted-diff).
