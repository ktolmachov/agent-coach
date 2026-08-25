# Contributing

This repository is developed one implementation slice at a time. Each slice
must keep the public demo safe to clone, inspect and run without private
infrastructure.

Before opening a change:

1. Keep the write-set limited to the current slice.
2. Do not add secrets, learner data, provider configuration or generated state.
3. Do not add HomeTutor runtime imports or a dependency on a private checkout.
4. Run targeted tests, Ruff and compile checks for the touched surface.
5. Stop after the promotion report instead of starting the next slice.

On Windows PowerShell, prefer the active virtual environment interpreter:

```powershell
.\.venv\Scripts\python.exe -m pytest <relevant tests>
.\.venv\Scripts\python.exe -m ruff check <touched paths>
.\.venv\Scripts\python.exe -m compileall src scripts
.\.venv\Scripts\python.exe scripts/check_d11_remediation_status.py
```

On POSIX shells, use the environment's `python` or `python3` consistently for
the same commands. CI runs the offline eval gate without live evidence or
promotion flags; live/provider evidence collection is a separate opt-in step.

Use `docs/implementation_plan.md` as the source of truth for the current slice,
its lifecycle status and its authorized write-set. Historical slice boundaries
remain in force: foundation, contracts, Core, adapters, API, retrieval,
provider, eval and release evidence changes stay in their documented owner
slices unless a maintenance change explicitly scopes a smaller surface.
