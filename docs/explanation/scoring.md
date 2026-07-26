# Deterministic scoring

> Why a shell script decides, and no model ever does.

The success script runs after the agent stops, in the same workspace, and its
exit code is the verdict. There is no LLM judge anywhere in the scoring path,
and there will not be one.

## The failure this prevents

Agents report success confidently and often. Here is a real run, shortened:

```
stop reason: completed
"Done. I created a virtualenv, installed pnf, and wrote demo.py which
 imports pnf and identifies the decode function."

success check exit code: 1
  ModuleNotFoundError: No module named 'pnf'
```

The agent had built its virtualenv in a different directory from the one the
script checked. Everything it said was true from where it was standing, and the
artifact the user needed did not exist. A model asked to grade that transcript
would very likely have passed it.

The test suite pins this behaviour: an agent claiming completion while the
artifact is missing must produce a failure.

## What this costs

Determinism is not free. A success script has to be written by hand, and it can
only check things a script can check. You cannot assert that documentation is
clear, well organised, or pleasant. Anything you cannot express as an exit code
is outside what this tool measures, and [what this does not tell
you](../index.md) stays honest about that.

The alternative buys breadth by giving up falsifiability. Once a model decides
whether a run passed, every number depends on that model's mood, its version,
and its prompt. Pass rates stop being comparable across time, which is the one
thing a regression signal has to be.

## Where models are allowed

Diagnosis, never verdicts. A model may eventually summarise *why* a run failed
or cluster failures across a sweep. That output is advisory, sits beside the
result, and cannot change it.

The line is simple to state and worth defending: anything that changes a
pass into a fail must be deterministic and inspectable by the person whose
documentation is being measured.

## What a pass actually claims

That one model, on one day, reading only the pages you allowed, produced an
artifact satisfying assertions you wrote. That is a floor.

It does not claim the documentation is good, complete, or accurate elsewhere.
Journeys test the paths you thought to write down, which is the same limitation
every test suite has.

## Why the agent never sees the script

The success script is not shown to the agent, and is not present in the
workspace while the agent runs. An agent that could read the assertions would
be able to satisfy them directly, and the run would measure instruction
following instead of documentation.
