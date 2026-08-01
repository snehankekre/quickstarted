# Install

> Install quickstarted and check what your machine can enforce.

## Run it without installing anything

```bash
uvx quickstarted run --example streamlit --agent replay
```

Three example tasks travel with the package, so there is nothing to clone and
no key to set. `quickstarted examples` lists them. This is also the right way to
use the tool from a JavaScript or Go project, where a Python environment is
friction you did not ask for.

## Install it properly

Agent mode is what you came for, so install a vendor SDK with it:

```bash
pip install "quickstarted[claude]"       # Anthropic
pip install "quickstarted[openai]"       # OpenAI
pip install "quickstarted[gemini]"       # Google
pip install "quickstarted[all-agents]"   # all three
```

Python 3.9 or newer. The only runtime dependency the harness itself adds is
PyYAML; the rest is the SDK you chose.

```bash
pip install quickstarted
```

The bare install runs [replay mode](../guides/replay-mode.md) only, which needs
no model and no key. That is the right install for a CI job that just checks the
documented commands still work.

## Check your machine

```bash
quickstarted doctor
```

```
quickstarted doctor
  backends available: docker, seatbelt, local
  auto would choose:  docker
  docker:             daemon reachable
  default image:      python:3.12-slim pulled
  claude:             SDK installed, key from QUICKSTARTED_ANTHROPIC_API_KEY
  openai:             SDK missing, no key (QUICKSTARTED_OPENAI_API_KEY or OPENAI_API_KEY)
  gemini:             SDK missing, no key (QUICKSTARTED_GEMINI_API_KEY or GOOGLE_API_KEY)
  price book:         none (token counts only)
  config file:        none
  tasks found:        14 in tasks/
```

It reports every provider, not only the one whose adapter happens to be
imported, says which environment variable a key came from, and tells you
whether the default image is already pulled. The first agent run otherwise
stalls on a silent `docker pull` that looks like a hung harness.

Tasks execute commands that a model wrote after reading somebody else's
documentation, which is untrusted code by any reasonable definition. The
backend decides what those commands can touch:

| Backend | Available when | Enforced |
| --- | --- | --- |
| `docker` | a Docker daemon is running | yes |
| `seatbelt` | macOS | yes |
| `local` | always | no |

If `doctor` reports `local` only, install Docker before you point this at a
project you did not write. `quickstarted run` will refuse to use `local`
until you pass `--allow-unenforced`. See [Sandboxing](../guides/sandboxing.md).

## Set an API key

Keys are read from `QUICKSTARTED_*` names first:

```bash
export QUICKSTARTED_ANTHROPIC_API_KEY=sk-ant-...
```

The vendor-standard names (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GOOGLE_API_KEY`) work as a fallback, which is what CI usually sets. The
prefixed names exist so a key can live in your shell without other tooling on
the same machine finding it and billing against it. Nothing in the sandbox ever
sees either name; the executor builds a scrubbed environment, and a test
asserts that no key reaches a command.

Next: [your first run](first-run.md).
