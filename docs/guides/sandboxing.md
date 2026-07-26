# Sandboxing

> What each backend actually enforces, and when the difference matters.

A task runs commands that a model wrote after reading documentation you do
not control. Some quickstarts still say `curl ... | bash`. The agent will
follow that instruction.

## The three backends

| Backend | Filesystem | Network | Use for |
| --- | --- | --- | --- |
| `docker` | container, workspace bind-mounted | internal network with no route out; the proxy sidecar is the only exit | anything, including CI |
| `seatbelt` (macOS) | reads of your home denied, writes confined to the workspace | all egress denied except the proxy port | local development |
| `local` | none | none; the proxy variables are advisory | tasks and projects you wrote yourself |

```bash
quickstarted run tasks/x.yaml --backend docker
quickstarted doctor          # what this machine can enforce
```

`auto` prefers Docker, then Seatbelt, then `local`. Every result records which
backend ran and whether it was enforced, so a number can always be traced back
to the conditions that produced it.

## Why local is refused

```
REFUSING: no enforced execution backend is available, so the docs allowlist
and the page-read record cannot be guaranteed.
```

With no boundary, a command can reach any host it likes. That breaks the
central claim, because a documentation page fetched by `curl` never appears in
the trace and the "last page read before failure" stops being true.

`--allow-unenforced` exists for the case where you wrote both the task and
the project. Results from it are still recorded as unenforced.

## What Docker does

```
[sandbox container]  --internal network-->  [proxy sidecar] --bridge--> internet
```

The sandbox container attaches only to a network created with `--internal`,
which has no route off the host. The single reachable address is the sidecar,
which sits on both that network and a normal bridge. The container also runs
with `--cap-drop ALL`, `no-new-privileges`, and a pid limit.

The isolation does not depend on the agent honouring `HTTP_PROXY`. From inside,
a direct dial to a raw IP address fails:

```python
socket.create_connection(("93.184.215.14", 443), timeout=10)
# OSError: [Errno 101] Network is unreachable
```

A task that needs a different base names one, which is how a suite mixes a
Python quickstart and a Node one in a single run:

```yaml
name: vite-quickstart
image: node:22-slim
```

`--image` sets the default for tasks that do not name one. See
[image](../reference/task-schema.md#image).

The default is `python:3.12-slim`, which has no `curl` and no Node. Success
scripts that need `curl` should install it or use Python instead.

## What Seatbelt does

macOS ships `sandbox-exec`, which applies a policy in the kernel. quickstarted
generates a profile that denies everything by default, then allows reads of the
system prefix, reads and writes inside the workspace, and outbound connections
to one loopback port: the harness proxy.

```
(deny default)
(allow file-read*)
(deny file-read* (subpath "/Users/you"))
(allow file-write* (subpath "/var/folders/.../quickstarted-abc123"))
(allow network-outbound (remote ip "localhost:53821"))
```

A bypass attempt dies in the kernel:

```
curl --noproxy '*' https://example.com/   # exit 7, could not connect
ls ~                                       # denied
```

Apple has deprecated `sandbox-exec`, and it remains functional. Treat it as
good hygiene for local work and use containers for projects you do not control.

## What never enters the sandbox

The executor builds the environment from scratch. Only `PATH`, `HOME`,
`TMPDIR`, locale variables, and the proxy settings are passed through. No API
key reaches a command under any backend, and a test asserts it.

More detail on the network half: [the egress proxy](../explanation/proxy.md).
