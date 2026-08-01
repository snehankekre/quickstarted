# Example tasks

Every file here is a real task against real published documentation. Run any
of them with an agent:

```bash
pip install "quickstarted[claude]"
export QUICKSTARTED_ANTHROPIC_API_KEY=...
quickstarted run tasks/httpx-quickstart.yaml --agent claude
```

Start with `httpx-quickstart.yaml`. It is the smallest complete example: one
documentation page, a four-line success check, and a goal a model can finish in
about twenty seconds.

| Task | Documentation under test | Check | What it shows |
| --- | --- | --- | --- |
| `httpx-quickstart` | python-httpx.org | 4 lines | The minimum viable task. |
| `pnf-quickstart` | a project README on raw.githubusercontent | 4 lines | A README is a documentation site. |
| `bottomtime-quickstart` | a project README | 3 lines | The shortest check in the repo. |
| `uv-quickstart` | docs.astral.sh/uv | 7 lines | A tool that manages the environment itself. |
| `prefect-quickstart` | docs.prefect.io | 6 lines | Asserting arithmetic the flow produced. |
| `polars-quickstart` | docs.pola.rs | 10 lines | Asserting data rather than API calls. |
| `duckdb-quickstart` | duckdb.org | 10 lines | A multi-page task. |
| `vite-quickstart` | vite.dev | 5 lines | Node, and proving a build really ran. |
| `tailwind-quickstart` | tailwindcss.com | 14 lines | The build has to have scanned the HTML. |
| `prisma-quickstart` | prisma.io/docs | 12 lines | A major version redesign; usually the hardest here. |
| `django-quickstart` | docs.djangoproject.com | 23 lines | A multi-step tutorial, answered through Django's test client. |
| `fastapi-quickstart` | fastapi.tiangolo.com | `checks/fastapi.sh` | A check in its own file, using the helpers. |
| `streamlit-quickstart` | docs.streamlit.io | 9 lines | The declarative `serve` and `wait_http` form. |
| `quickstarted-quickstart` | this project's docs | 11 lines | The tool tested against its own quickstart. |

The check column is the length of the success script, which is the only thing
that decides a pass. Read it as a difficulty rating for writing the task, not
for passing it: the short checks are the representative ones, and the long ones
are the strictest possible version of "does the thing actually work." Both are
legitimate. See
[writing tasks](https://snehankekre.com/quickstarted/guides/writing-tasks/).

Two of them are worth reading side by side. `streamlit-quickstart` boots the app
and polls its health endpoint in nine lines of YAML, using `serve` and
`wait_http`. `fastapi-quickstart` needs to choose between two documented ways of
serving, which the declarative form deliberately cannot express, so its check
lives in `checks/fastapi.sh` and calls the same helpers by hand.

The four Node tasks set `image: node:22-slim`, because the default
`python:3.12-slim` has no Node. One `quickstarted run tasks/*.yaml` covers both
runtimes; the image is per task.

`prisma-quickstart` is worth reading if you want to see what these measure.
Prisma 7 moved the datasource URL out of the schema into `prisma.config.ts`,
made the generated client TypeScript, and made a driver adapter mandatory. Three
independent ways for a reader following an older page to end up stranded, and
none of them show up as a broken command.

Every task also carries a `replay` block, the literal commands the
documentation prints, which runs with no model and no API key:

```bash
quickstarted run tasks/*.yaml --agent replay
```

That is the free precondition. It proves the documented commands still work, and
it cannot tell you whether a reader could have found them.

## A note on fetching these

Most of these sites belong to people who did not ask to be measured. The harness
sends a truthful User-Agent, honours `robots.txt`, and waits a second between
requests to the same host. Use `--cache-dir` when you are iterating so you are
not re-fetching the same pages.
