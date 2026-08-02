# Design notes

## The one decision everything follows from

Deterministic assertions are the only pass/fail truth. The success script runs
after the agent stops, in the same workspace, and its exit code is the
verdict. LLM judges may eventually classify WHY a run failed; they will never
decide WHETHER it failed. This keeps the tool falsifiable and keeps vendors
(including Anthropic) out of the scoring path.

## A task may name nothing its target documentation does not name

The point of the tool is to ask whether a project's own quickstart works. A
task that invents a filename is asking a different question, and answering it
confidently.

This was violated by every task in this repository, and the cause was
structural rather than careless. The success check could only observe the
filesystem after the run, so the goal got written backwards from what the check
could see. Most quickstarts do not end at a file. DuckDB's persistent storage
example prints a table, Polars' getting started guide ends at `print(df_csv)`,
Prisma's SQLite quickstart ends at two `console.log` calls. To assert anything,
the author bolted an artefact onto the goal: `total.txt`, `out.csv`,
`out.json`, `fetch.py`. FastAPI's tutorial says "copy that to a file
`main.py`"; the task demanded `app.py`. A reader who followed the page exactly
would have failed.

`success.expect_output` removes the pressure by making the terminal assertable.
It reads the recorded session output, which a determined agent could satisfy
with `echo`. That is not a new weakness: a check that greps a file the agent
wrote has always had it. The discipline is unchanged, and it is to assert
durable state as well wherever the documentation produces any.

## A quickstart is a route, not a page

`docs.entrypoint` was a single URL, which quietly assumed the thing being
tested fits on one page. It usually does not. FastAPI's install instruction is
on `/tutorial/` and its first application is on `/tutorial/first-steps/`.

The 0.3.0 benchmark shows what that costs. GPT-5.2 failed FastAPI three times
out of three and passed it five times out of five on the same day, with the
same model and the same task. The only difference was which pages got read: the
failures read `first-steps` alone, which carries no install instruction, and
the passes also read the index. The harness recorded a `docs_gap` against a
page that is missing nothing.

So `docs.path` is an ordered list, and every page on it is offered to the
agent. Where a reader starts is a variable worth controlling deliberately
rather than one to leave to whichever URL the task author happened to paste.

## Every page read goes through a tool the agent cannot bypass

Agents act only through the Toolbelt (`bash` + `read_docs`), so every page read
is recorded and failures attribute to a page.

v0.1 stopped there, and that was not enough. The allowlist lived in the
`read_docs` tool while `bash` had unrestricted network access, so any agent
that ran `curl` read documentation the trace never saw. The guarantee held only
while the agent cooperated, which is not a guarantee.

Now all shell traffic leaves through a proxy the harness owns, and
documentation hosts are unreachable from the shell. An attempted `curl` to a
docs host is refused and counted. The set of pages in the report is the set of
pages the agent read.

This creates one deliberate asymmetry: `docs.allow` hosts are readable only via
`read_docs`, and `network.allow` hosts (package registries) are reachable only
from the shell. When a host is genuinely both, PyPI being the obvious case, the
task says so explicitly and installs win. The resulting gap in attribution
is reported alongside the result.

## Backends, and saying which one ran

Three: `docker` (container on an internal network whose only route out is the
proxy sidecar), `seatbelt` (macOS, kernel-enforced, all egress denied except
the proxy port, home directory unreadable), and `local` (nothing enforced).

`local` is refused unless explicitly allowed, every result records which
backend ran and whether it was enforced, and `quickstarted doctor` says what a
machine can do before anyone trusts its numbers. An unenforced result still
tells you something. It just supports a weaker claim, and the claim should
travel with the number.

## A run is a sample; a rate is a measurement

The same docs and model can pass and then fail. `--repeat` produces a pass
rate, and every run is classified. Only `passed` and `docs_gap` are statements
about documentation. Rate limits, exhausted budgets, refusals, and our own bugs
are excluded from both the numerator and the denominator and reported
separately.

A sweep of fifty projects will hit 429s and flaky networks. Reporting those as
failed quickstarts would be a lie that is very easy to tell, and it is the
difference between a benchmark and a leaderboard-shaped rumour.

## Affordances are measured, never scored

Whether a project ships `llms.txt` is a checklist item anyone can `curl`, and
scoring it would be the proxy metric this tool exists to replace. So presence
is recorded as context, with sizes, and the affordance can be *withheld*:
`--affordances none` blocks `llms.txt` and `.md` variants while keeping the
prompt byte-identical. Run both conditions and the difference in pass rate is a
measurement of the affordance itself.

That question is currently argued without data. This is the only shape of tool
that can answer it, because answering it requires running the task.

## Replay mode is a precondition

Replay (documented commands verbatim, no LLM) is free, deterministic and
CI-friendly, and it defines a floor: if replay fails, agent mode is noise. It
is a weaker `runShell` than a docs-testing framework like Doc Detective
already offers. Sell it as a precondition, and let agent mode carry the
product.

## Trace as the product surface

Everything interesting is an event in the JSONL trace: setup, tool calls, docs
fetches with content hashes, egress decisions, agent turns with token usage,
retries, the success check. `results.json` (schema 2.0) is the stable contract
over those traces. The hosted product is, to a first approximation, storage
plus diffing plus alerting across models and time.

## Cost is reported in tokens

Cached prompt tokens are excluded from `input_tokens` by the API, so summing
that field alone made a run costing 120k cache-read tokens look free. All four
counters are tracked. Dollars appear only when the operator supplies a price
book: vendor rates change, and a stale table baked into a benchmarking tool
would quietly misreport what a sweep costs.

## Known gaps

- Both enforced backends are verified end to end against live daemons. In the
  container the isolation is stronger than Seatbelt's: a direct dial to an IP
  address fails with `Network is unreachable`. The sandbox network has no route
  out at all, so the isolation does not depend on name resolution.
- HTML-to-text is a tag stripper, so markdown-native docs still read better.
  That is itself a finding worth publishing, but only once the stripper is not
  the thing producing the finding. It used to join text nodes with no
  separator, which turned tabbed install blocks into
  `npm create vite@latestbash$ yarn create vite` and Tailwind's install page
  into `npm create vite@latest my-projectcd my-project`. Six of the eleven
  sites tested here were affected. Anything measured before 0.6.0 is partly a
  measurement of this bug.
- `expect_output` trusts the run's own transcript. It is deterministic and no
  model sees it, but it cannot distinguish a computed value from an echoed one.
  Assert durable state alongside it when the documentation leaves any.
- Concurrency is per-attempt threads. Hosts are rate-limited individually, and
  there is no global budget governor.
- No pip/npm cache; every run cold-installs.
- The Gemini adapter is written against the same Toolbelt contract but has not
  been run live; Claude and OpenAI have.
- Nothing distinguishes "the docs are wrong" from "the product is broken". Both
  surface as `docs_gap` and need a human.
