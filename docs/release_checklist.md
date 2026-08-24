# Release Checklist

This checklist prepares a public diploma review release. It does not authorize
production deployment, production authentication, durable production state or
ownership cutover.

## Required Gate

Run from a fresh clone or a disposable copy:

```bash
python -m pip install -e ".[dev,build]"
python -m pytest tests/test_package_smoke.py
python -m pytest
python -m ruff check .
python -m compileall src scripts
python scripts/check_contract_export.py
python scripts/check_openapi_snapshot.py
python scripts/check_drift_gate.py
python scripts/check_public_release.py
python scripts/check_public_release.py --release
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

## D11 Live and Clean Evidence

Before running live provider evidence, record the fixed cases and obtain
explicit approval for network access, environment-supplied provider credentials,
the configured planner/synthesizer models and possible cost. Then run:

```bash
python scripts/run_live_eval.py --allow-network --provider-opt-in --output docs/evidence/live-eval-public.json
```

The committed public artifact must be redacted and must not contain raw
provider payloads, credentials, private paths, learner data or chain-of-thought.
After the reviewed commit exists, generate the external wrapper:

```bash
python scripts/run_live_eval.py --wrapper-only --public-artifact docs/evidence/live-eval-public.json --wrapper-output ../agent-coach-live-wrapper.json
```

Clean fresh-clone evidence is captured outside the checkout and must bind to
the same immutable commit. It records real stdout SHA-256 values for the
registered commands `python -m pytest`,
`python scripts/check_public_release.py --release` and
`python scripts/run_eval_gate.py`.

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
