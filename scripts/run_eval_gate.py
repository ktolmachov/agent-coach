"""Run the D11 deterministic eval gate and emit JSON evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agent_coach.eval import build_tool_sop_markdown, run_eval_suite

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_SOP_SNAPSHOT = REPO_ROOT / "docs" / "tool_sop.md"


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
    parser.add_argument(
        "--require-promotion",
        action="store_true",
        help="Return non-zero unless promotion_status is PASS.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdout()
    args = build_arg_parser().parse_args(argv)
    if args.print_tool_sop:
        generated = build_tool_sop_markdown()
        print(generated, end="")
        try:
            snapshot = TOOL_SOP_SNAPSHOT.read_text(encoding="utf-8")
        except OSError:
            print("Tool SOP snapshot is unavailable", file=sys.stderr)
            return 1
        if generated != snapshot:
            print("Tool SOP snapshot drift detected", file=sys.stderr)
            return 1
        return 0
    promotion_required = bool(
        args.require_promotion
        or args.live_evidence is not None
        or args.clean_release_evidence is not None
    )
    if args.output is not None and promotion_required and _is_repo_local(args.output):
        print(
            "Promotion reports must be written outside the checkout",
            file=sys.stderr,
        )
        return 2

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
    status_key = "promotion_status" if promotion_required else "gate_status"
    return 0 if report[status_key] == "PASS" else 1


def _configure_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def _is_repo_local(path: Path) -> bool:
    output_path = path.resolve()
    repo_root = REPO_ROOT.resolve()
    return output_path == repo_root or repo_root in output_path.parents


if __name__ == "__main__":
    raise SystemExit(main())
