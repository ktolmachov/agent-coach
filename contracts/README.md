# Contracts

D2 exports the public, versioned Agent contract bundle and a deterministic test
vector derived from it.

Files:

- `agent_contracts/v1/agent_contract_bundle.json` - copied without
  transformation from the source contract artifact;
- `agent_contracts/v1/contract_test_vectors.json` - deterministic public
  validation vector for schema hash, tool order and harness-only fields;
- `export_manifest.json` - file-level provenance for each exported artifact.

The current contract version is `agent-contracts/1.0.0` with schema hash
`218c90732c25ae2f9b26c4f5a9ea5ee81c28bf797299c99b53e310bf22315910`.

Validate the export from this public repository with:

```bash
python scripts/check_contract_export.py
```

Maintainers with access to the private source checkout may additionally pass
`--source-root` to verify source file hashes. Public CI does not need that
checkout.
