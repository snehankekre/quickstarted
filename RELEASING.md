# Releasing

## Once, before the first release

1. Create the PyPI project by uploading manually, or configure trusted
   publishing first at <https://pypi.org/manage/account/publishing/>:
   - PyPI project name: `quickstarted`
   - Owner: `snehankekre`
   - Repository: `quickstarted`
   - Workflow: `release.yml`
   - Environment: `pypi`
2. In the GitHub repository settings, create an environment named `pypi`.
3. Enable Pages: Settings, Pages, Source "GitHub Actions". The docs workflow
   deploys on every push to `main`.

## Every release

1. Update `CHANGELOG.md`: move items under a new version heading with a date.
2. Bump the version in `src/quickstarted/_version.py`. That file is the single
   source; `pyproject.toml` and the User-Agent read from it.
3. Verify locally:

   ```bash
   .venv/bin/python -m pytest -q
   .venv/bin/ruff check .
   .venv/bin/mypy
   .venv/bin/mkdocs build --strict
   .venv/bin/quickstarted run journeys/*.yaml --agent replay --backend docker
   ```

4. Build and inspect the artifacts:

   ```bash
   .venv/bin/python -m build
   .venv/bin/twine check dist/*
   tar -tzf dist/quickstarted-*.tar.gz | head -30
   ```

   The sdist should contain `src/`, `tests/`, `journeys/`, `docs/`, and the
   Markdown files, and nothing else.

5. Tag and push:

   ```bash
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin main --tags
   ```

6. Create a GitHub release from the tag. Publishing the release triggers
   `release.yml`, which builds and uploads to PyPI through trusted publishing.

## Verifying a release

```bash
python3 -m venv /tmp/verify && /tmp/verify/bin/pip install quickstarted
/tmp/verify/bin/quickstarted doctor
/tmp/verify/bin/quickstarted validate journeys/pnf-quickstart.yaml
```

## Version policy

Semantic versioning. Before 1.0 the CLI and the journey schema may change in
minor releases, and the changelog says so explicitly when they do.

`results.json` carries its own `schema_version`, which is independent of the
package version. Fields are added but not repurposed; the schema version rises
when that stops being true.
