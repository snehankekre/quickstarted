# The egress proxy

> Why documentation is unreachable from the shell, and what that buys.

Every report claims to list the documentation pages an agent read, and names
the last one before a failure. That claim is only worth something if the list
is complete.

## The bug that caused this design

Version 0.1 put the allowlist inside the `read_docs` tool and left `bash` with
ordinary network access. The guarantee held only while the agent chose to
cooperate. Proof, from the sandbox of that version:

```
bash -> non-allowlisted host: 200 (exit 0)
```

Any agent that ran `curl https://docs.example.com/page` read documentation the
trace never saw. Nothing in the design stopped it, and nothing in the output
would have hinted at it. "The last page read before the failure" was a guess
wearing the costume of a fact.

## The fix

All shell traffic leaves through a proxy the harness owns, and the policy has
one asymmetry at its centre:

- **Documentation hosts are refused to the shell.** `read_docs` is the only
  route, so every page read is recorded. An attempt is logged as
  `egress_blocked` with reason `docs_host_requires_read_docs` and counted in
  the report.
- **Registry hosts are allowed to the shell** and are not documentation. `pip`
  works; `read_docs` has no business there.

Under Docker the sandbox container sits on an `--internal` network with no
route off the host, and the proxy sidecar is the only container bridged to the
outside. Under Seatbelt, the kernel denies every outbound connection except the
loopback port the proxy listens on. In both cases enforcement survives an agent
that ignores `HTTP_PROXY`:

```python
socket.create_connection(("93.184.215.14", 443), timeout=10)
# OSError: [Errno 101] Network is unreachable
```

## When a host is both

PyPI serves package downloads and project pages. Some projects keep their
documentation on GitHub raw URLs alongside their releases. Naming a host under
`network.allow` makes the shell able to reach it, and installs then win over
attribution for that host.

The trade is recorded, not hidden. `quickstarted validate` reports it, and the
journey's `attribution_gaps` names the host, so anyone reading a result knows
which pages might have been read without appearing in the list.

## A second dividend

Separating refusals from failures makes classification possible. A connection
this tool refused, a connection that failed upstream, and a page that returned
a 500 are three different events with three different meanings. Without that
distinction, a flaky registry looks exactly like a documentation gap, and a
benchmark that cannot tell them apart will eventually publish that a company's
quickstart is broken when the truth was a network blip.

That is the difference between a measurement and an accusation.

## What it does not do

The proxy is a policy boundary, not a security product. It sees CONNECT targets
rather than URLs for HTTPS, so path-level attribution within an allowed host
comes from `read_docs` rather than from traffic inspection. Container escape,
kernel bugs, and anything a determined attacker would try are out of scope. The
threat model is a well-meaning agent following bad instructions, which is the
realistic case. See [SECURITY.md](https://github.com/snehankekre/quickstarted/blob/main/SECURITY.md).
