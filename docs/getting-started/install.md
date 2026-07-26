# Install

> Install quickstarted and check what your machine can enforce.

```bash
pip install quickstarted
```

Python 3.9 or newer. The base install has one runtime dependency, PyYAML, and
runs replay mode, which needs no API key and no model.

Agent mode needs a vendor SDK:

```bash
pip install "quickstarted[claude]"       # Anthropic
pip install "quickstarted[openai]"       # OpenAI
pip install "quickstarted[gemini]"       # Google
pip install "quickstarted[all-agents]"   # all three
```

## Check your machine

```bash
quickstarted doctor
```

```
quickstarted doctor
  backends available: docker, seatbelt, local
  auto would choose:  docker
  price book loaded:  no (token counts only)
  QUICKSTARTED_ANTHROPIC_API_KEY: set
```

Journeys execute commands that a model wrote after reading somebody else's
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
