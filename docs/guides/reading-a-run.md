# Reading a run

> What to do with a results directory: the report, one transcript, and the
> difference between two runs.

A run writes three kinds of thing, and each answers a different question.

```bash
quickstarted run tasks/ --agent openai --model gpt-5.2 --out results/
```

```
results/
├── results.json              the machine-readable record
├── suite.md                  the summary, as Markdown
└── <task-name>/
    ├── trace.jsonl           every event, in order
    └── report.md             that one run, written out
```

## Start with the report

```bash
quickstarted report results/ --out report.html
```

One self-contained page. It is HTML whatever you name the file, because it is
meant to be sent to somebody: no external stylesheet, script, or font, so it
renders the same for them as it did for you, and it works from a file:// URL or
a CI artifact.

The page has three parts.

**Pass rates**, one row per task, with the counts that back them:

| Task | Agent | Pass rate | Evidential | Discarded |
| --- | --- | --- | --- | --- |
| django-quickstart | openai:gpt-5.2 | 100% | 1/1 | - |
| streamlit-quickstart | openai:gpt-5.2 | no evidence | 0/0 | budget_exhausted=1 |

"No evidence" is not a failure. It means nothing in that row is a statement
about the documentation, and the `Discarded` column says why. See
[pass rates](pass-rates.md).

**Where it failed**, one section per documentation gap, carrying the check's own
output and the last page the agent read before things went wrong. This is the
part you send to whoever owns the docs.

**Transcripts**, folded away behind a disclosure per task. Every command, its
exit code, the elapsed time, and each page read.

## Read one transcript when a number surprises you

The pass rate says what happened. The transcript says why, and it is usually
obvious at a glance:

```
[   0.0s] streamlit-quickstart on docker, agent openai:gpt-5.2, attempt 1
[   2.0s] setup: python3 -m venv .venv
[   4.0s] read https://docs.streamlit.io/get-started/installation
[   5.1s] read https://docs.streamlit.io/get-started/fundamentals/main-concepts
[   6.5s] $ . .venv/bin/activate && pip install -U pip && pip install streamlit pandas numpy
[ 306.5s]   exit 124
[ 308.8s] $ . .venv/bin/activate && pip install streamlit pandas numpy
[ 434.4s]   exit 0
[ 434.4s] success check exited 1
           | check failed: no Python file in the workspace imports streamlit
[ 434.4s] budget_exhausted (stop reason: timeout)
```

That is a real run. Exit 124 is the per-command timeout, the retry finished at
434 seconds, and the wall clock budget was 420, so the agent never got as far as
writing an application. Nothing there is a documentation problem: the budget was
too small, which is why the run is discarded rather than counted. The fix was to
raise `max_seconds` on the task, not to change anything about Streamlit's docs.

Without the transcript that row is an unexplained "no evidence".

`quickstarted show results/streamlit-quickstart/trace.jsonl` prints the same
thing for a single run without building a page.

## Compare two runs

```bash
quickstarted diff before/results.json after/results.json
```

Two runs of the same suite, one before a documentation change and one after,
with the tasks that moved. `--fail-on-regression` exits non-zero when something
that passed now does not, which is what makes it useful in CI on a docs pull
request. See [running in CI](ci.md).

## When you want the raw record

`results.json` carries a `schema_version` and is the stable contract: pass
rates, classifications, token counts, the resolved image and backend, and the
pages read per run. Build on it rather than parsing the console output. The
[results schema](../reference/results.md) documents every field, and
[trace events](../reference/trace.md) documents the JSONL underneath it.
