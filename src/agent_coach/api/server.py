"""Localhost-safe server entry point for the Mock Agent API."""

from __future__ import annotations

import argparse
import ipaddress
from collections.abc import Sequence

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8008


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Agent Coach local Mock API.")
    parser.add_argument("--host", default=DEFAULT_HOST, type=_loopback_host)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    import uvicorn

    uvicorn.run(
        "agent_coach.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
    )


def _loopback_host(value: str) -> str:
    host = value.strip()
    if host == "localhost":
        return host
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "host must be localhost or a loopback IP address"
        ) from exc
    if not address.is_loopback:
        raise argparse.ArgumentTypeError(
            "host must be localhost or a loopback IP address"
        )
    return host
