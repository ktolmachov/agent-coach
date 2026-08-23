"""Check or update the committed OpenAPI snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_coach.api import create_app

SNAPSHOT = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"


def _snapshot_text() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    expected = _snapshot_text()
    if args.write:
        SNAPSHOT.write_text(expected, encoding="utf-8")
        return 0
    actual = SNAPSHOT.read_text(encoding="utf-8")
    if actual != expected:
        print("docs/openapi.json is not current")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
