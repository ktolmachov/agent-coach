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

The report includes schema version, commit, dirty flag, profile, contract hash,
corpus hash, thresholds, per-case results, KPI metrics and limitations.

## Frozen Thresholds

- offline golden pass rate: 100% on non-retrieval-top1 golden cases;
- retrieval top-1 accuracy: at least 80%;
- live agent task success: at least 80% when opt-in live evidence is supplied;
- invalid or unknown tool executions: 0;
- security assertion failures: 0;
- hidden writes: 0;
- grounded answers without citation: 0;
- offline p95 duration: at most 2500 ms;
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

## Status Semantics

`gate_status: PASS` means the deterministic offline D11 gate passed. It does
not mean the final diploma release is promoted.

`promotion_status: PASS` is fail-closed. It requires a passing offline gate,
a clean worktree, valid live evidence with
`schema_version: "agent-coach-live-eval-evidence/1.0.0"` and
`task_success_rate >= 0.8`, `commit` matching HEAD, `profile: "live_provider"`,
`provider_profile_opt_in: true`, `checked_at_utc`, at least five live cases and
public evidence artifact labels, plus valid clean release evidence with
`schema_version: "agent-coach-clean-release-evidence/1.0.0"` for the current
commit, `worktree_dirty: false`, `checked_at_utc` and PASS/exit-code-0 command
evidence for the fresh-clone suite, public release gate and offline eval gate.
Minimal marker-only evidence files remain invalid. Without those files,
`promotion_status: HOLD` is expected. A release tag is not created by this gate.

## Tool SOP

The generated Tool SOP is in `docs/tool_sop.md` and is checked by
`tests/test_eval_gate.py` against the current advertised `ToolSpec` values.
