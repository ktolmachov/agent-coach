# D11 Eval Gate

D11 freezes KPI thresholds before any live evidence is considered. The default
gate is deterministic and offline: it uses only packaged synthetic fixtures,
the local in-memory vector profile and scripted provider-contract failures.

Run it with:

```bash
python scripts/run_eval_gate.py
```

Write a report outside the checkout:

```bash
python scripts/run_eval_gate.py --output ../agent-coach-d11-eval-report.json
```

Require full promotion evidence:

```bash
python scripts/run_eval_gate.py --require-promotion
```

Full final promotion check, after the reviewed commit has valid external live
wrapper and clean-release evidence:

```bash
python scripts/run_eval_gate.py --live-evidence ../agent-coach-live-wrapper.json --clean-release-evidence ../agent-coach-clean-release-evidence.json --require-promotion --output ../agent-coach-d11-promotion-report.json
```

When the real evidence files are unavailable, the expected result remains
`promotion_status: HOLD`; do not replace them with marker files.

The report includes schema version, commit, dirty flag, profile, contract hash,
suite version/hash, provenance, corpus hash, thresholds, per-case results, KPI
metrics and limitations. If Git HEAD cannot be read, promotion is blocked with
`git_unavailable`.

## Frozen Thresholds

- offline golden pass rate: 100% on non-retrieval-top1 golden cases;
- retrieval top-1 accuracy: at least 80%;
- forced-grounding live task success: at least 80% for promotion when opt-in
  live evidence is supplied; this checks provider wiring, grounded synthesis
  and citation behavior, not autonomous planner tool-selection accuracy, and
  it does not affect offline `gate_status`;
- invalid or unknown tool executions: 0;
- security assertion failures: 0;
- hidden writes: 0;
- grounded answers without citation: 0;
- offline p95 eval runtime: at most 2500 ms, measured with wall-clock timing
  around each case and using a higher-index nearest-rank percentile for small
  fixed eval sets;
- offline total cost: 0 USD;
- unknown pricing under an active cost cap: fail closed;
- fallback and abstain rates are reported separately.

## Suite

The frozen case manifest is packaged as
`src/agent_coach/data/diploma_eval_cases.json`. It contains 27 public synthetic
cases covering retrieval, no-answer, ambiguous query, multi-step study session,
quiz/cards branch, validation, timeout, rate limit, dependency failure,
cost/step limit, prompt injection, fake secret redaction, separate PII/private
path redaction, unknown tool and malformed native function calls.

The loader validates the exact registered suite: schema version, suite version,
public provenance, exactly 27 non-empty case ids in frozen order, frozen KPI
thresholds, category/type coverage and canonical suite hash. `--suite` is only
for supplying the registered suite from another path; modified or external
suites fail closed. Custom suite JSON is capped at 128000 bytes.

## Status Semantics

`gate_status: PASS` means the deterministic offline D11 gate passed. It does
not mean the final diploma release is promoted.

`promotion_status: PASS` is fail-closed. It requires a passing offline gate,
a clean worktree, valid live evidence with
`schema_version: "agent-coach-live-eval-evidence/1.0.0"` and
`task_success_rate >= 0.8`, `commit` matching HEAD, `profile: "live_provider"`,
`provider_profile_opt_in: true`, `checked_at_utc`, the registered live evidence
provenance, the registered live cases and public evidence artifact records with
repo-relative `docs/evidence/*.json` labels. Registered case contracts include
the question, expected/allowed/forbidden tools, expected answer status, allowed
sources, citation flag, security assertions and success rule. Each referenced
public artifact must exist in the reviewed tree, be tracked by Git, match its
SHA-256 digest, declare `mode: "live_provider"` and
`contains_scripted_responses: false`, include complete per-case projections
for both successful and failed provider cases, and recompute to the wrapper's
task-success rate. Promotion also requires valid clean release evidence with
`schema_version: "agent-coach-clean-release-evidence/1.0.0"` for the current
commit, `worktree_dirty: false`, `checked_at_utc`, the registered clean-release
evidence provenance and PASS/exit-code-0 command evidence for the fresh-clone
suite, strict public release gate and offline eval gate. Clean command records
must match the registered commands and include `stdout_sha256`. Accepted evidence
provenance, artifact labels/digests and command records remain in the final
report. Minimal marker-only and string-only evidence files remain invalid.
Without those files,
`promotion_status: HOLD` is expected. A release tag is not created by this gate.
Evidence JSON files are capped at 64000 bytes each. A live task success rate
below 80% adds `live_evidence_below_threshold` to promotion blockers while the
offline `gate_status` remains determined only by offline cases.

The default CLI exit code follows offline `gate_status`. Supplying
`--live-evidence`, `--clean-release-evidence` or `--require-promotion` switches
the exit code to `promotion_status`. Promotion-mode `--output` paths must be
outside the checkout so the report cannot claim a clean worktree and then dirty
the same checkout by writing itself.

## Live Evidence Runner

`scripts/run_live_eval.py` owns the opt-in D11 live-provider evidence path. The
five public synthetic cases are registered before network execution and cover
photosynthesis, spaced repetition, retrieval practice, active recall flashcards
and cognitive load. Each case declares its question, expected and allowed
tools, forbidden tools, expected grounded status, allowed source labels,
citation requirement, security assertions and success rule.

Because all five cases explicitly require grounded retrieval, the live harness
forces the provider-native `rag.search` function choice and supplies the exact
pre-registered query arguments for each case. The adapter rejects a missing
call, a different tool or changed arguments instead of silently substituting a
local call. Answer synthesis still runs through the configured live provider.
This suite is forced-grounding evidence only; confirmed autonomous planner
accuracy requires the separate `tool_choice: auto` harness and later live
artifact.

Offline runner validation uses a scripted Responses client and is explicitly
not live evidence:

```bash
python scripts/run_live_eval.py --scripted
```

Live collection requires explicit provider and network opt-in:

```bash
python scripts/run_live_eval.py --allow-network --provider-opt-in --output ../agent-coach-live-eval-public.json
```

The public artifact is a bounded redacted projection. The current-evidence
validator rejects scripted mode, missing causal provenance, dirty or
mismatched commits, missing or empty per-case results, security/tool
violations and self-reported success rates that do not match the case results.
Tracked `docs/evidence/historical/live-eval-public.json` is a
`historical_example` and cannot be wrapped as current evidence. After a
current public artifact is written outside the checkout, generate the
external wrapper for the final eval gate:

```bash
python scripts/run_live_eval.py --wrapper-only --public-artifact ../agent-coach-live-eval-public.json --wrapper-output ../agent-coach-live-wrapper.json
```

The wrapper records the artifact `evaluated_commit` and the SHA-256 of the
public artifact. Wrapper-only mode validates the current causal contract
before writing the wrapper, so a scripted validation artifact or historical
example cannot be converted into live promotion evidence.

## Tool SOP

The generated Tool SOP is in `docs/tool_sop.md` and is checked by
`tests/test_eval_gate.py` against the current advertised `ToolSpec` values and
the package-owned negative usage registry. Its limits column distinguishes
declared per-tool `ToolSpec` limits, the global runtime safety projection cap
and the effective result cap, which is the smaller value for tools such as
`rag.search`.
`python scripts/run_eval_gate.py --print-tool-sop` prints the generated SOP and
returns non-zero if the committed snapshot has drifted.
