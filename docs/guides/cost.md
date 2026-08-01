# Cost and budgets

> Token counts are always reported. Dollars need a source of rates, and the
> figure says what is missing from it.

## Why no prices ship with the tool

Vendor rates change. A price table baked into a benchmarking tool would keep
producing numbers after it went stale, and those numbers would look exactly as
authoritative as the correct ones. quickstarted reports tokens, which are
facts, and converts to dollars only from rates that come from somewhere
maintained.

Two places qualify. A price book you wrote:

```bash
export QUICKSTARTED_PRICES=prices.json
```

```json
{
  "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.5}
}
```

Or a package that tracks them for you:

```bash
pip install "quickstarted[prices]"
```

That pulls [genai-prices][gp], and costs then appear with no further setup. The
principle holds because the rates live in a package somebody updates, not in a
table in this repository that would rot quietly. A price book you supply always
wins.

genai-prices requires Python 3.10, while quickstarted supports 3.9. On 3.9 the
extra installs nothing and a price book is the only route to dollars. Token
counts are unaffected.

[gp]: https://github.com/pydantic/genai-prices

## When a model has no published price

```
  estimated cost: $0.0415
  no published price for claude:claude-opus-5, so their tokens are not in that figure
```

A bundled price snapshot lags new models, and the models worth benchmarking are
the new ones. Rather than quietly reporting a total that excludes one arm of a
two-model sweep, the summary names what is missing, and `results.json` carries
the same list under `totals.unpriced_models`.

`--refresh-prices` asks for current rates before pricing, which helps when
upstream has caught up. It is opt-in because a benchmarking run should not make
a surprise network call to price itself.

When upstream has not caught up, a price book is the answer. As of
genai-prices 0.0.72 neither its bundled data nor its live data prices
`claude-opus-5`, which is this tool's default model, so a Claude sweep that
wants dollars still writes the four rates down by hand. Yours always wins over
the package's.

## Stopping before it gets expensive

```bash
quickstarted run --agent claude --repeat 5 --max-spend 10
```

The ceiling is checked between runs, never predicted ahead of one, because what
a run costs is not knowable until it has happened. When it trips, the sweep
stops, the runs that finished are written out as normal, and the exit code is
130. The summary says so, since a document with fewer runs than you asked for
has to explain itself:

```
  STOPPED AT THE SPEND LIMIT: these are the runs that finished. Attempts that
  never started are absent, not failed.
```

Interrupting with Ctrl-C behaves the same way. The evidence you already paid
for is kept.

## Reading the token line

```
tokens: 24 in / 4616 out, cache 16812 written / 104148 read
```

Four counters, because cached prompt tokens are billed differently and would
otherwise vanish. An early version of this tool summed only the first field and
reported "22 in" for a run that had read 120,000 cached tokens, which made an
expensive run look free.

Vendors disagree about what their fields mean. Anthropic reports `input_tokens`
with cache traffic already excluded. OpenAI and Google report a prompt total
that includes it. The adapters normalise to the Anthropic meaning, so
`input_tokens` here is always uncached prompt tokens and the four counters
never bill the same token twice.

## Capping a run

```yaml
budgets:
  max_turns: 20
  max_seconds: 420
  max_tokens: 200000
```

`max_tokens` counts all four categories. When a run exceeds it, the agent stops
and the run is classified `budget_exhausted`, which keeps it out of the pass
rate. Prefer this to a dollar cap: it needs no price list and cannot drift.

## Estimating dollars

Write the rates you are actually charged, in dollars per million tokens:

```json
{
  "claude-opus-5": {
    "input": 5.0,
    "output": 25.0,
    "cache_write": 6.25,
    "cache_read": 0.5
  },
  "gpt-5": {
    "input": 1.25,
    "output": 10.0,
    "cache_read": 0.125
  }
}
```

```bash
export QUICKSTARTED_PRICES=~/prices.json
quickstarted run tasks/*.yaml --agent claude --repeat 5
# or
quickstarted run tasks/*.yaml --agent claude --prices ~/prices.json
```

```
  estimated cost: $0.4127
```

The numbers above are an example of the file format. Copy the current rates
from your vendor's pricing page; nothing validates them for you.

Lookup matches the model the API reported, falling back to the tail of an agent
name, so an entry for `claude-opus-5` covers a run reported as
`claude:claude-opus-5`. A model with no entry contributes no cost, and a suite
where nothing matched reports no estimate at all.

## Keeping a sweep affordable

Replay mode is free. Run it on every change, and reserve agent mode for
schedules and model releases.

Prompt caching does most of the work on repeated runs of the same task,
which is visible in the cache-read counter. Concurrency (`--workers`) shortens
wall clock without changing token cost, and raises your chance of a rate limit.

`--cache-dir` removes documentation fetches from repeated runs. That saves the
sites you are testing more than it saves you.
