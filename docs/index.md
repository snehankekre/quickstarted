# quickstarted

> Test whether an AI agent can complete your quickstart by following your docs.

Roughly half the traffic to documentation sites is now AI agents and
AI-assisted workflows. When an agent reads your quickstart and fails, you lose
the developer behind it and you never find out.

quickstarted turns that into a CI signal. A sandboxed agent gets your goal,
your documentation, and nothing else. A script you wrote decides whether it
succeeded.

```
[FAIL] duckdb-quickstart (claude:claude-opus-5)
  classification: docs_gap
  turns: 14, duration: 88.1s
  backend: docker
  success check exit code: 1
  last docs page read before failure: https://duckdb.org/docs/stable/clients/python/overview
```

That last line is the product. The harness owns the only tool that can read
documentation, so the pages in the report are the pages the agent really read,
and the one it was on when things went wrong is a fact rather than a guess.

## Start here

<div class="grid cards" markdown>

- **[Install](getting-started/install.md)**
  One dependency, no API key needed for replay mode.

- **[Your first run](getting-started/first-run.md)**
  Write a journey and run it against real documentation in about five minutes.

- **[Agent mode](getting-started/agent-mode.md)**
  Put a model in the loop and see where your docs run out.

- **[Writing journeys](guides/writing-journeys.md)**
  The rules that separate a useful journey from a flaky one.

</div>

## What makes a result trustworthy

Three decisions do most of the work, and each has a page explaining why.

**A script decides, never a model.** The success script runs after the agent
stops, in the same workspace, and its exit code is the verdict. An agent that
reports triumph over a missing file still fails.
[How scoring works](explanation/scoring.md)

**The sandbox is a boundary.** Documentation hosts are unreachable from the
shell, so `read_docs` is the only route to a page and every read is recorded.
Commands run in a container, or under a kernel sandbox on macOS.
[The egress proxy](explanation/proxy.md) and [Sandboxing](guides/sandboxing.md)

**One run is one sample.** Repeat runs produce a pass rate, and runs that died
on a rate limit are excluded from it instead of being counted as documentation
failures. [Pass rates](guides/pass-rates.md)

## Does llms.txt help?

Nobody knows, because presence is easy to check and effect is not. quickstarted
never scores affordances. It withholds them and measures what changes.
[Measuring llms.txt](guides/affordances.md)

## For agents reading this

Every page here is available as raw Markdown: append `.md` to any URL. An index
of the whole site lives at
[llms.txt](https://snehankekre.com/quickstarted/llms.txt). Both are
generated at build time from the same navigation as the site.
