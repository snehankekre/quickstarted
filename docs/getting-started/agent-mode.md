# Agent mode in depth

> Choosing a model, bounding the cost, and reading what a run left behind.

[Your first run](first-run.md) is a working agent run. This page covers what
you need once you are running more than one.

## What the agent can and cannot do

It gets two tools. `bash` runs commands in the workspace. `read_docs` fetches a
documentation page.

It does not get a web browser, a search engine, or its own network access.
Documentation hosts are unreachable from the shell, so `read_docs` is the only
way to a page, and every page it reads is recorded. Package registries work the
other way around: reachable from the shell for installs, absent from the docs
allowlist. [The egress proxy](../explanation/proxy.md) explains why the split
runs in that direction.

The system prompt also forbids relying on prior knowledge of the project under
test. A model that already knows httpx would otherwise sail through
documentation that tells a newcomer nothing.

## Choosing a model

```bash
quickstarted run tasks/httpx.yaml --agent claude --model claude-opus-5
quickstarted run tasks/httpx.yaml --agent openai --model gpt-5
quickstarted run tasks/httpx.yaml --agent gemini --model gemini-2.5-pro
```

The Claude adapter defaults to `claude-opus-5`. The OpenAI and Gemini adapters
require `--model`, because vendor model names change faster than any default
would survive, and a benchmark that silently picks one produces numbers nobody
can reproduce.

Every adapter uses the same prompt and the same two tools. Otherwise a
cross-model comparison would be measuring the prompts.

Results record the model the API actually served, which is often more specific
than what you asked for. An alias can start resolving to a new build without
telling you, and a pass-rate trend across a silent change means nothing.

## What a run leaves behind

The summary names the last page read before a failure, which is where to start
reading. Everything else is in the artifacts. `--out results/` writes the full
trace and a Markdown report:

```bash
quickstarted run tasks/httpx.yaml --agent claude --out results/
```

`results/httpx-quickstart/trace.jsonl` has every tool call, every page fetch
with a content hash, every egress decision, and per-turn token usage.
`report.md` is the same run in prose. See [Trace events](../reference/trace.md).

## Cost

Agent runs cost real tokens. A short task is cents; the numbers above are
typical. Two controls keep a sweep bounded:

```yaml
budgets:
  max_turns: 20
  max_seconds: 420
  max_tokens: 200000
```

Token budgets need no price list and cannot drift when a vendor changes rates.
If you want dollars, supply your own price book with `--prices`. See
[Cost and budgets](../guides/cost.md).

Next: the rules for [writing tasks](../guides/writing-tasks.md) that
measure documentation instead of luck.
