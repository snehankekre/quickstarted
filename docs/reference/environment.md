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
| `QUICKSTARTED_SANDBOX_DIR` | Parent directory for Docker workspaces |

Settings that would otherwise be repeated on every invocation belong in
`quickstarted.yaml` instead. See [the CLI reference](cli.md#configuration-file).

## Inside a success check

| Variable | Meaning |
| --- | --- |
| `QS_PORT` | A free port, chosen for this task before the check runs |

`$QS_PORT` comes from a range derived from the task name, so two tasks in one
suite do not collide and a failure reproduces by hand. `success.serve` and
`qs_wait_http` both default to it.

```yaml
success:
  serve: .venv/bin/fastapi run app.py --port $QS_PORT
  wait_http:
    path: /items/42
```

### QUICKSTARTED_SANDBOX_DIR

The `docker` backend bind-mounts a fresh workspace into the container, which
requires a host path the daemon can actually see. On Linux that is any path. On
macOS the daemon runs inside a VM with only some directories shared, so the
default there is `~/.quickstarted/sandboxes` rather than the system temp
directory, which is not shared.

Set this if your daemon shares a different set of paths, or to put workspaces on
a specific disk. The mount is verified at startup and the run is refused if it
does not work in both directions, because a bind mount the daemon quietly
redirects into the VM produces runs that pass while the host sees an empty
workspace and cleanup frees nothing.

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
