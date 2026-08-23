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
