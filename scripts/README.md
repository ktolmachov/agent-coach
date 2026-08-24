# Scripts

D2 adds the contract verification helper:

```bash
python scripts/check_contract_export.py
```

The checker validates the export manifest, target file sha256 values, canonical
contract schema hash, deterministic test vectors and absence of obvious secret
or local-path markers in exported artifacts. It runs without a private source
checkout by default.

Maintainers can add `--source-root <source checkout>` to verify source sha256
values when source evidence is available locally.

D5 adds the OpenAPI snapshot checker:

```bash
python scripts/check_openapi_snapshot.py
```

Use `--write` after intentional API changes to refresh `docs/openapi.json`.

D6 adds the parity and drift gate:

```bash
python scripts/check_drift_gate.py
python scripts/check_drift_gate.py --source-root ../hometutor --json
```

The default mode is public-CI friendly and does not require HomeTutor. The
optional `--source-root` mode verifies the current HomeTutor contract schema
hash against the exported public bundle and fails closed on drift. The public
mode also checks exact scenario projection hashes from a frozen independent
snapshot and runtime private-path forms in code plus runtime-consumed
JSON/TOML/YAML resources. Python source scanning includes bounded constant
string concatenations.

D7 adds the public release gate and diploma demonstration script:

```bash
python scripts/check_public_release.py
python scripts/run_diploma_demo.py
python scripts/run_diploma_demo.py --output ../agent-coach-diploma-demo.json
```

The release gate validates the publishable/runtime surface for private local
path markers, required review files, README safety language, current OpenAPI,
internal Markdown links and tracked or dirty generated release artifacts. The
demo script emits deterministic JSON evidence for one synthetic mock scenario.

D11 adds the offline eval gate and generated Tool SOP snapshot:

```bash
python scripts/run_eval_gate.py
python scripts/run_eval_gate.py --output ../agent-coach-d11-eval-report.json
python scripts/run_eval_gate.py --require-promotion
python scripts/run_eval_gate.py --print-tool-sop
```

The default eval gate is deterministic and offline. It reports
`gate_status: PASS` separately from `promotion_status`; promotion remains
`HOLD` until Git is available and live evidence, a clean worktree and clean
fresh-clone release evidence are all valid and above promotion thresholds. The
suite must match the registered 27-case suite version, provenance, id list and
canonical hash. Minimal marker-only or oversized evidence files are invalid;
accepted evidence provenance is retained in the report; live evidence must
identify the current commit, live profile opt-in and public artifact labels
with SHA-256 digests, and clean release evidence must include
PASS/exit-code-0 command records with `stdout_sha256` for the required checks.
Supplying promotion evidence or `--require-promotion` makes `promotion_status`
drive the CLI exit code, and promotion-mode reports must be written outside the
checkout. `--print-tool-sop` prints the generated SOP and fails on committed
snapshot drift without echoing local checkout paths.
