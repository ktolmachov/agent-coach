# Scripts

## Acceptance Commission Demo

Package A of the D11 remediation treats this runner as a published D11
artifact. Run the complete deterministic commissioning sequence from the
repository root. On Windows use the active virtualenv interpreter; a bare
`python` launcher can be intercepted by the App Execution Alias.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts/run_acceptance_demo.py --full-checks --serve --output ../agent-coach-acceptance-report.json
```

POSIX:

```bash
python3 scripts/run_acceptance_demo.py --full-checks --serve --output ../agent-coach-acceptance-report.json
```

The script validates the wheel artifact, exported contracts, OpenAPI snapshot,
architecture drift gate, public release surface, full public tests, Ruff,
compileall and the D11 offline eval gate. It then demonstrates the mock,
local-vector and scripted provider-contract profiles and performs a real HTTP
smoke against the localhost-only Mock API. With `--serve`, Swagger UI remains
available at `http://127.0.0.1:8008/docs` until Ctrl+C.

The HTTP smoke also fails closed unless it can prove the complete agentic chain:
the submitted question, the ordered tool selection, successful retrieval with
a public source, and a grounded final answer that cites that source. These four
links are printed for the commission and stored under `agentic_chain` in the
optional JSON report; a static answer without tool/context evidence fails.
It then submits three contrasting questions and requires three different tool
routes: a grounded learning answer, an empty-cards abstention and a safe
abstention for prompt-injection content. The `contrastive_routing` evidence
proves that the demo does not accept one fixed route or hallucinate when safe
grounding is unavailable.
The same live localhost process also replays an idempotent request, checks that
tool arguments match the advertised schemas, rejects harness identity fields,
records stable per-scenario projection hashes and prints an
`evidence_payload_sha256` digest. Finally, it sends invalid HTTP requests for
idempotency conflict, schema validation, payload limit, unknown tool, forbidden
identity args and unknown run; every case must return a bounded error
envelope.

The default path is offline. It never enables provider network access and
scripted provider validation is not live evidence. Generated reports must be
written outside the checkout. Add `--require-clean` when collecting evidence
for an immutable reviewed commit.

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
python scripts/run_live_eval.py --scripted
```

The default eval gate is deterministic and offline. It reports
`gate_status: PASS` separately from `promotion_status`; promotion remains
`HOLD` until Git is available and live evidence, a clean worktree and clean
fresh-clone release evidence are all valid and above promotion thresholds. The
suite must match the registered 27-case suite version, provenance, id list and
canonical hash. Minimal marker-only or oversized evidence files are invalid;
accepted evidence provenance is retained in the report; live evidence must
identify the current commit, live profile opt-in and public artifact labels
with SHA-256 digests. Those public artifacts must exist in the reviewed tree,
be tracked by Git, declare live mode with no scripted responses and contain
complete registered per-case results whose recomputed success rate matches the
wrapper. Clean release evidence must include PASS/exit-code-0 command records
with `stdout_sha256` for the required checks, including the strict
`python scripts/check_public_release.py --release` command.
Supplying promotion evidence or `--require-promotion` makes `promotion_status`
drive the CLI exit code, and promotion-mode reports must be written outside the
checkout. `--print-tool-sop` prints the generated SOP and fails on committed
snapshot drift without echoing local checkout paths.

The final copy-paste promotion command, after valid external live-wrapper and
clean-release evidence have been captured, is:

```bash
python scripts/run_eval_gate.py --live-evidence ../agent-coach-live-wrapper.json --clean-release-evidence ../agent-coach-clean-release-evidence.json --require-promotion --output ../agent-coach-d11-promotion-report.json
```

If either evidence file is missing or invalid, the expected result remains
`promotion_status: HOLD`; do not create placeholder evidence.

The opt-in live eval runner freezes five public synthetic live-provider cases.
`--scripted` validates the runner with the deterministic Responses test client
and is not live evidence. Actual live collection requires both
`--allow-network` and `--provider-opt-in`, writes only a redacted public
projection and never prints provider credentials:

```bash
python scripts/run_live_eval.py --allow-network --provider-opt-in --output docs/evidence/live-eval-public.json
python scripts/run_live_eval.py --wrapper-only --public-artifact docs/evidence/live-eval-public.json --wrapper-output ../agent-coach-live-wrapper.json
```

The strict final release gate is:

```bash
python scripts/check_public_release.py --release
```

It keeps the normal development gate compatible while adding clean-tree and D11
final-artifact requirements.
