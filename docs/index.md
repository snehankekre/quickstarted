# quickstarted

> Test whether an AI agent can complete your quickstart using only your docs.

```bash
uvx quickstarted run --example streamlit --agent replay
```

No API key, no cost, nothing to clone:

```
  [    0s] started on seatbelt
  [    2s] read https://docs.streamlit.io/get-started
  [   19s] blocked from the shell: checkip.amazonaws.com
  [   20s] check exited 0
[PASS] streamlit-quickstart (replay)
  classification: passed
  turns: 2, duration: 19.6s
  backend: seatbelt
  docs pages read: 1
```

The third line is the sandbox refusing Streamlit's own call home, which is what
enforcement looks like from outside.

The agent gets your documentation and nothing else: no browser, no search
engine, no network of its own, and a prompt that forbids leaning on what it
already knows about your project. A script you wrote decides whether it got
there. When it does not, you get the page it was reading.

```
[FAIL] fastapi-quickstart (openai:gpt-5.2-2025-12-11)
  classification: docs_gap
  turns: 7, duration: 65.7s
  backend: docker (python:3.12-slim)
  success check exit code: 1 (	pip install "fastapi[standard]")
  last docs page read before failure: https://fastapi.tiangolo.com/tutorial/first-steps/
  docs pages read: 1
```

That is a real run, and the last two lines are the product. The harness owns the
only tool that can read documentation, so the pages in the report are the pages
the agent really read, and the one it was on when things went wrong is a fact
rather than a guess.

What happened there: the model read the tutorial and ran `pip install fastapi`.
The page says `pip install "fastapi[standard]"`, and without the extra there is
no server, so nothing could run the app it had just written. Claude Opus 5
installs the extra and passes the same task every time.

Which is worth being precise about, because it shows what this measures and what
it does not. The run proves a reader arrived at a broken result and names the page
they were on. It cannot tell you whether the page buried something important or
the model simply skipped it. Both are worth knowing and they are different
problems, so the report gives you the page and leaves the judgement to you.

## Start here

<div class="grid cards" markdown>

-   __Install__

    ---

    One dependency plus the SDK for whichever model you point at your docs, or
    nothing at all with `uvx`.

    [Install](getting-started/install.md)

-   __Your first run__

    ---

    Scaffold a task against real documentation and point a model at it.

    [First run](getting-started/first-run.md)

-   __Writing tasks__

    ---

    Success checks you can copy, and the rules that keep a task from
    measuring luck.

    [Writing tasks](guides/writing-tasks.md)

-   __Agent mode in depth__

    ---

    Choosing models, bounding cost, reading the trace.

    [Agent mode](getting-started/agent-mode.md)

</div>

## What makes a result trustworthy

Three decisions do most of the work, and each has a page explaining why.

**A script decides, never a model.** The success script runs after the agent
stops, in the same workspace, and its exit code is the verdict. An agent that
reports triumph over a missing file still fails. Most of these scripts are two
or three lines: the file exists, the import works, the output contains the
number your page promised.
[How scoring works](explanation/scoring.md) and
[checks you can copy](guides/writing-tasks.md#success-checks-you-can-copy)

**The sandbox is a boundary.** Documentation hosts are unreachable from the
shell, so `read_docs` is the only route to a page and every read is recorded.
Commands run in a container, or under a kernel sandbox on macOS.
[The egress proxy](explanation/proxy.md) and [Sandboxing](guides/sandboxing.md)

**One run is one sample.** Repeat runs produce a pass rate, and runs that died
on a rate limit are excluded from it instead of being counted as documentation
failures. [Pass rates](guides/pass-rates.md)

## Did the change help?

That is the question you have after you edit the page, and it is the one a
single verdict cannot answer.

```bash
quickstarted diff before/results.json after/results.json
```

```
  fastapi-quickstart
      2/10 (20%)  ->  8/10 (80%)
      improved, p=0.023
```

Every comparison carries a two-sided Fisher exact test, and when the samples
were too small for any outcome to have cleared the bar, it says that instead of
reporting a result. Three attempts a side never can. Four can.
[quickstarted diff](reference/cli.md#quickstarted-diff)

## Does llms.txt help?

Nobody knows, because presence is easy to check and effect is not. quickstarted
never scores affordances. It withholds them and measures what changes.
[Measuring llms.txt](guides/affordances.md)

## For agents reading this

Every page here is available as raw Markdown: append `.md` to any URL. An index
of the whole site lives at
[llms.txt](https://snehankekre.com/quickstarted/llms.txt). Both are
generated at build time from the same navigation as the site.
