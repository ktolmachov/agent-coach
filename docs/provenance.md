# Provenance

Source repository: HomeTutor
Source commit: `292be74f97b18615388838c2a1ddf2e0879585e0`
Source ADR path: `docs/adr/0007-agent-coach-diploma-distribution.md`
Transformation: `public-safe derivative`

D1 exported no HomeTutor runtime code, contracts, schemas, fixtures, learner
data, provider configuration or generated runtime state. It created only the
public foundation needed to continue implementation inside this repository.

D2 exports only public contract artifacts:

- `contracts/agent_contracts/v1/agent_contract_bundle.json`, copied without
  transformation from the source versioned contract artifact;
- `contracts/agent_contracts/v1/contract_test_vectors.json`, deterministically
  derived from that bundle for public validation;
- `contracts/export_manifest.json`, which records source commit, source path,
  target path, source sha256, target sha256 and transformation for each
  exported file.

The current exported contract version is `agent-contracts/1.0.0` with schema
hash `218c90732c25ae2f9b26c4f5a9ea5ee81c28bf797299c99b53e310bf22315910`.

The export is validated by `scripts/check_contract_export.py`. The default mode
requires only this repository; an optional source checkout can be supplied by
maintainers for source hash verification.

D6 adds `scripts/check_drift_gate.py`, which combines manifest validation,
canonical contract hash equality, exact executable scenario projection hashes
from `fixtures/drift_golden_projection_hashes.json`, security assertions and
runtime absolute-path dependency scanning for code and runtime-consumed
resources. The default mode remains public-CI independent; `--source-root
<checkout>` adds current HomeTutor contract parity verification when both
repositories are available.

Target repository baseline before D1: `81026a20ff4425e58b48a359700ddb01c76f36f7`
