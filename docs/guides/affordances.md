# Measuring llms.txt

> Presence is a checklist item. Effect is a measurement. quickstarted does the
> second one.

Whether a site ships `llms.txt` takes one `curl` to determine. Plenty of tools
will grade you on it. That grade is a proxy for the thing you actually care
about, which is whether an agent does better because the file is there.

quickstarted never scores affordances. It withholds them and measures what
changes.

## The ablation

```bash
quickstarted run tasks/streamlit-quickstart.yaml --agent claude --repeat 10
quickstarted run tasks/streamlit-quickstart.yaml --agent claude --repeat 10 --affordances none
```

`--affordances none` blocks `llms.txt`, `llms-full.txt`, and `.md` variants at
the fetch layer. The agent gets an ordinary "not available" response and
carries on with the regular pages.

Everything else is held constant. The prompt is byte-identical, the task is
the same file, the model is pinned. The only difference between the two runs is
whether the affordance existed for the agent, so the difference in pass rate
is attributable to the affordance.

Run both at `--repeat 10` or more. A five-point difference between two
five-attempt samples is noise.

## Probing without changing anything

```bash
quickstarted run tasks/streamlit-quickstart.yaml --agent claude --probe-affordances
```

This records what exists, with sizes, and changes nothing about the run:

```
llms.txt       present=True  status=200 bytes=   66,867
llms-full.txt  present=True  status=200 bytes=1,807,036
page.md        present=False status=404 bytes=        0
```

Sizes are there because presence and usefulness come apart fast. That
`llms-full.txt` is 1.8 MB, roughly 450k tokens, which is more than most agents
can read in one call. A checklist scores the site two out of three. The
question of whether either file helped is still open, and only an ablation
closes it.

A soft 200 is treated as absent. Single-page apps serve their HTML shell for
any unknown path, so a `llms.txt` that returns markup is recorded as missing,
with a note.

## What lands in the results

Affordance data appears in the trace as an `affordances` event and in
`results.json` under the run, never as a score, a grade, or a total. Nothing in
the scoring path reads it.

```json
{
  "type": "affordances",
  "entrypoint": "https://docs.streamlit.io/get-started",
  "found": {
    "llms.txt": {"present": true, "status": 200, "bytes": 66867, "note": ""},
    "llms-full.txt": {"present": true, "status": 200, "bytes": 1807036, "note": ""},
    "page.md": {"present": false, "status": 404, "bytes": 0, "note": ""}
  }
}
```

## Beyond llms.txt

The same shape works for any affordance you can withhold: per-page Markdown, an
MCP server, an OpenAPI description. If you can control whether the agent has
it, you can measure whether it mattered. That is the only method here that
produces a number worth arguing about.
