**What this changes**

**Why**

**How it was verified**

- [ ] `pytest` passes
- [ ] `ruff check .` and `mypy` pass
- [ ] `mkdocs build --strict` passes, if docs changed
- [ ] A live run, if behaviour changed: paste the summary line

**Checklist for behaviour changes**

- [ ] No model has been added to the scoring path
- [ ] Infrastructure failures are still excluded from pass rates
- [ ] The unenforced backend is still not a silent default
