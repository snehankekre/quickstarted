# Security

## What this tool does with untrusted input

quickstarted runs commands that a language model wrote after reading somebody
else's documentation. Treat that as executing untrusted code, because it is.
A quickstart that says `curl ... | bash` will be followed.

## Backends and what they actually enforce

| Backend | Filesystem | Network | Use for |
| --- | --- | --- | --- |
| `docker` | container | internal network; the only route out is the proxy sidecar | anything, including CI |
| `seatbelt` (macOS) | reads of your home denied, writes confined to the workspace | all egress denied except the harness proxy port | local development |
| `local` | none | none (proxy variables are advisory) | tasks and projects you wrote yourself |

`quickstarted run` refuses to use `local` unless you pass `--allow-unenforced`.
`quickstarted doctor` reports what the current machine can enforce.

Seatbelt is deprecated by Apple but functional. It is a real boundary, not a
strong one: treat it as good hygiene for local work, and use containers for
projects you do not control.

## Credentials

API keys are read from `QUICKSTARTED_*` variables first (`QUICKSTARTED_ANTHROPIC_API_KEY`,
`QUICKSTARTED_OPENAI_API_KEY`, `QUICKSTARTED_GEMINI_API_KEY`), falling back to the
vendor-standard names. The quickstarted-specific names exist so a key can sit in
a developer's shell without other tooling on the same machine picking it up and
spending it.

No credential is passed into the sandbox. The executor builds a scrubbed
environment containing only `PATH`, `HOME`, `TMPDIR`, locale, and the proxy
variables; a test asserts that no API key reaches a command.

## Fetching other people's documentation

Benchmarking means requesting pages from organisations who did not ask to be
measured. By default quickstarted sends a truthful User-Agent that identifies the
tool, honours `robots.txt`, and waits at least one second between requests to
the same host. `--ignore-robots` and `--rate-limit 0` exist; using them against
somebody else's site is your decision to defend.

## Reporting a vulnerability

Open a GitHub security advisory on the repository, or email the address in
`pyproject.toml`. Please do not open a public issue for anything that would let
a malicious task escape a backend.
