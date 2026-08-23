# D6 Parity and Drift Gate

The drift gate proves that this standalone deterministic diploma demo remains
tied to the exported HomeTutor contract instead of becoming an unrelated toy
fork.

Run the public gate from a fresh checkout:

```bash
python scripts/check_drift_gate.py
```

This mode requires only the public repository. It validates the export manifest,
canonical contract hash, exact deterministic scenario projection hashes,
security assertions and absence of runtime absolute-path dependencies.

Maintainers with both checkouts can run the optional cross-repository gate:

```bash
python scripts/check_drift_gate.py --source-root ../hometutor --json
```

The optional mode verifies the manifest source blob and compares the current
HomeTutor canonical contract schema hash with the exported public bundle. Any
mismatch fails closed.

Promotion thresholds:

- contract hash equals the D2 manifest value;
- semantic subset ratio is at least 95%, counted per exact scenario projection
  rather than per shallow field;
- security assertions pass at 100%;
- source provenance is complete;
- runtime code and runtime-consumed JSON/TOML/YAML resources have no absolute
  path dependency on a local checkout;
- public CI runs without HomeTutor.

The semantic projection includes the public answer, sources, trace, steps and
tool outcomes. The expected oracle is the independent frozen hash snapshot in
`fixtures/drift_golden_projection_hashes.json`, not a value recomputed through
the production sanitizer/helper. The gate requires exact equality between the
fixture scenario ids and frozen scenario ids, and each frozen hash must be a
64-character lowercase sha256 digest.

The absolute-path scan rejects Windows drive paths with either slash style, UNC
paths, `file:///` URIs, absolute POSIX paths containing a `hometutor` checkout
segment under any root, common private POSIX roots, and private paths adjacent
to public URLs after punctuation while preserving public HTTP(S) URLs. Python
source scanning also folds bounded constant string concatenations before
matching.
