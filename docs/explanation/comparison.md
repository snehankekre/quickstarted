# Compared to other tools

> What quickstarted does that adjacent tools do not, and where they are the
> better choice.

## Doc Detective

[Doc Detective](https://github.com/doc-detective/doc-detective) is a
documentation testing framework. You write step-level specs, inline in your
source or standalone, using actions like `click`, `find`, `type`, `goTo`,
`runShell`, `runCode`, `httpRequest`, and `checkLink`. It drives real browsers,
captures screenshots and video with visual regression, and handles native apps
experimentally.

It answers: **does the product still match the doc?**

quickstarted answers: **can a reader who only has the docs reach a working
outcome?**

The difference is the route. Doc Detective is given the path and checks that
each step still works. quickstarted specifies a goal and a success condition,
and the agent has to find its own way, which is why it can fail on ambiguity,
missing prerequisites, wrong ordering, or a page nobody can find.

Worked cases:

| Situation | Doc Detective | quickstarted |
| --- | --- | --- |
| Quickstart is correct but buried three clicks deep | passes | fails |
| A prerequisite is never mentioned | passes, if the spec includes it | fails |
| The product's button moved | fails | never notices |
| A screenshot is stale | fails | never notices |

If you need UI testing, screenshots, or visual regression, use Doc Detective.
quickstarted does none of that, and the two are complementary rather than
competing. Doc Detective is also considerably more mature.

Replay mode overlaps with `runShell` and is weaker than it. Treat replay as a
precondition for agent mode, and if you already run Doc Detective, you already
have that floor covered.

## Answer bots (kapa.ai, Inkeep, RunLLM)

These put a model on your documentation so users can ask questions. They
measure and improve answer quality.

Answering a question and completing a task are different capabilities. A bot
can explain your install process perfectly while an agent still cannot get a
working install, because the failure is in an ordering assumption no answer
would surface.

## Brand visibility tools (Profound, Peec, Athena)

These measure whether ChatGPT and friends mention your product. That is a
marketing question about reach.

quickstarted asks a product question about whether the agent that arrives can
actually use what it finds. Being recommended and being usable are independent,
and a good result on one says nothing about the other.

## Agent evaluation frameworks (DeepEval, Braintrust, Langfuse)

Built for teams evaluating agents they own: prompts, traces, scoring, drift.
The subject under test is the agent.

Here the subject under test is your documentation, and the agent is the
instrument. That inversion is why the harness owns the tools, pins the prompt
across vendors, and refuses to let a model score anything.

## Readiness scanners

Several tools grade a site out of 100 on whether it ships `llms.txt`, an MCP
server, structured data, and similar. These are checklists, and they are cheap
to run because presence is easy to determine.

quickstarted refuses to score presence. It withholds an affordance and measures
the change in pass rate, which is the only method that answers whether the file
helped. See [measuring llms.txt](../guides/affordances.md).

## When to use none of these

If your quickstart has never been run end to end by anyone but its author, run
replay mode first. Most documentation that fails an agent fails a human too,
and the free deterministic check finds that in seconds.
