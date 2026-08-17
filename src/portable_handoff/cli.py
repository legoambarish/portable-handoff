"""Command-line entry point; full command handlers are added by later milestones."""

from __future__ import annotations

import argparse
import sys

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="portable-handoff",
        description="Create, validate, and load portable AI work-state capsules.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")
    for name, help_text in (
        ("preflight", "capture deterministic local facts"),
        ("finalize", "combine facts and a semantic draft into a capsule"),
        ("validate", "validate a capsule"),
        ("load", "load a capsule or latest capsule"),
        ("list", "list stored capsules"),
        ("source", "inspect a read-only transcript adapter"),
    ):
        subparsers.add_parser(name, help=help_text)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
