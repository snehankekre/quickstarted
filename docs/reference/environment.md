# Environment variables

> What quickstarted reads, and what the sandbox never sees.

## Credentials

| Variable | Fallback | Used by |
| --- | --- | --- |
| `QUICKSTARTED_ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` | `--agent claude` |
| `QUICKSTARTED_OPENAI_API_KEY` | `OPENAI_API_KEY` | `--agent openai` |
| `QUICKSTARTED_GEMINI_API_KEY` | `GOOGLE_API_KEY` | `--agent gemini` |

The prefixed name wins. It exists so a key can live in your shell without other
tooling on the same machine picking it up and spending it. Claude Code, for
example, offers to use any `ANTHROPIC_API_KEY` it finds, which silently moves
your usage from a subscription onto API billing.

The vendor names remain as a fallback because that is what CI secrets are
conventionally called.

Keeping a key out of your shell entirely, on macOS:

```bash
security add-generic-password -a "$USER" -s quickstarted-anthropic -w

quickstarted() {
  QUICKSTARTED_ANTHROPIC_API_KEY="$(security find-generic-password -a "$USER" -s quickstarted-anthropic -w)" \
    command quickstarted "$@"
}
```

## Configuration

| Variable | Meaning |
| --- | --- |
| `QUICKSTARTED_PRICES` | Path to a price book; `--prices` overrides it |

## Test suite

| Variable | Meaning |
| --- | --- |
| `QUICKSTARTED_NETWORK_TESTS` | Set to run tests that reach the network |

## What the sandbox receives

The executor builds the environment from scratch rather than filtering yours.
Commands see exactly:

| Variable | Value |
| --- | --- |
| `PATH` | Inherited |
| `HOME` | The workspace |
| `TMPDIR` | A directory inside the workspace |
| `LANG`, `LC_ALL` | Inherited or `en_US.UTF-8` |
| `TERM` | `dumb` |
| `NO_COLOR` | `1` |
| `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` | The harness proxy, upper and lower case |

No API key is passed in, under any backend. A test asserts that neither
`QUICKSTARTED_ANTHROPIC_API_KEY` nor `ANTHROPIC_API_KEY` appears in the output
of `env` inside a sandbox.

Proxy variables are set for the sake of tools that read them, and enforcement
does not depend on that. Under Docker the container has no route out except the
sidecar; under Seatbelt the kernel denies every outbound connection except the
proxy port.
