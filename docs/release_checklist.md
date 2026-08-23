# Release Checklist

This checklist prepares a public diploma review release. It does not authorize
production deployment, production authentication, durable production state or
ownership cutover.

## Required Gate

Run from a fresh clone or a disposable copy:

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m compileall src
python scripts/check_contract_export.py
python scripts/check_openapi_snapshot.py
python scripts/check_drift_gate.py
python scripts/check_public_release.py
python scripts/run_diploma_demo.py --output ../agent-coach-diploma-demo.json
```

If release evidence is committed under `docs/evidence/`, the public release
gate validates its schema, `commit == HEAD`, `worktree_dirty == false`, mock
adapter profile and successful terminal result. Otherwise keep generated
evidence outside the checkout as a release asset.

The reviewed tree must identify the immutable commit under review:

```bash
git rev-parse HEAD
git status --short
```

The release tag is created only after explicit maintainer approval.

## Public Safety Review

- README and docs say `standalone deterministic diploma demo`.
- README does not claim production readiness.
- Swagger instructions point only to localhost.
- Mock API comparison states no production auth and no durable state.
- Security reporting uses GitHub private reporting when enabled or the concrete
  fallback recipient documented in `SECURITY.md`.
- No secrets, credentials, learner data, caches, databases or local private
  checkout paths are committed.
- `docs/openapi.json` matches the current app factory.
- Apache-2.0 license and `docs/dependency_notices.md` have been reviewed.

## Tag Preparation

After approval, create a release tag from the reviewed commit:

```bash
git tag -a v0.1.0 -m "Agent Coach diploma review kit"
git show --stat v0.1.0
```

Do not tag a dirty tree or generated evidence that points to a different
commit.
