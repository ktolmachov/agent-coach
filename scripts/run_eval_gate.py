"""Run the D11 deterministic eval gate and emit JSON evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agent_coach.eval import build_tool_sop_markdown, run_eval_suite


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the D11 offline diploma eval gate.",
    )
    parser.add_argument(
        "--suite",
        type=Path,
        help="Optional eval suite JSON path; defaults to packaged D11 cases.",
    )
    parser.add_argument(
        "--live-evidence",
        type=Path,
        help="Optional redacted live evidence JSON with task_success_rate.",
    )
    parser.add_argument(
        "--clean-release-evidence",
        type=Path,
        help="Optional clean fresh-clone release evidence JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path to write.",
    )
    parser.add_argument(
        "--print-tool-sop",
        action="store_true",
        help="Print generated Tool SOP markdown instead of the eval report.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdout()
    args = build_arg_parser().parse_args(argv)
    if args.print_tool_sop:
        print(build_tool_sop_markdown(), end="")
        return 0
    report = run_eval_suite(
        suite_path=args.suite,
        live_evidence_path=args.live_evidence,
        clean_release_evidence_path=args.clean_release_evidence,
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["gate_status"] == "PASS" else 1


def _configure_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
