"""Portable Handoff command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .errors import HandoffError, ExitCode, SourceError
from .finalize import finalize
from .load import load_capsule
from .preflight import collect_preflight, write_preflight
from .storage import list_capsules, resolve_project_root
from .strict_json import dumps_canonical
from .validate import validate_file


HOSTS = ("codex", "claude", "cursor", "chatgpt", "other", "unknown", "manual")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portable-handoff", description="Create, validate, and load portable AI work-state capsules.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight", help="capture deterministic local facts")
    preflight.add_argument("--cwd", default=".")
    preflight.add_argument("--source-host", choices=HOSTS, default="unknown")
    preflight.add_argument("--session")
    preflight.add_argument("--output", default="-")

    final = sub.add_parser("finalize", help="combine facts and a semantic draft into a capsule")
    final.add_argument("--preflight", required=True)
    final.add_argument("--draft", required=True)
    final.add_argument("--output", default="auto")
    final.add_argument("--force", action="store_true")

    validate = sub.add_parser("validate", help="validate a capsule")
    validate.add_argument("capsule")
    validate.add_argument("--cwd", default=".")
    validate.add_argument("--json", action="store_true", dest="json_output")

    load = sub.add_parser("load", help="load a capsule or latest capsule")
    load.add_argument("reference", choices=None)
    load.add_argument("--cwd", default=".")
    load.add_argument("--format", choices=("briefing", "json"), default="briefing")

    listing = sub.add_parser("list", help="list stored capsules")
    listing.add_argument("--cwd", default=".")
    listing.add_argument("--json", action="store_true", dest="json_output")

    source = sub.add_parser("source", help="inspect a bounded read-only transcript adapter")
    source_sub = source.add_subparsers(dest="source_command", required=True)
    probe = source_sub.add_parser("probe", help="report adapter support")
    probe.add_argument("--host", required=True, choices=HOSTS)
    source_list = source_sub.add_parser("list", help="list bounded sessions")
    source_list.add_argument("--host", required=True, choices=HOSTS)
    source_list.add_argument("--limit", type=int, default=20)
    source_list.add_argument("--json", action="store_true", dest="json_output")
    show = source_sub.add_parser("show", help="show normalized events from a session")
    show.add_argument("--host", required=True, choices=HOSTS)
    show.add_argument("--session", required=True)
    show.add_argument("--output", default="-")
    return parser


def _print_json(value: Any) -> None:
    sys.stdout.write(dumps_canonical(value) + "\n")


def _preflight(args: argparse.Namespace) -> int:
    value = collect_preflight(cwd=args.cwd, source_host=args.source_host, session=args.session)
    result = write_preflight(value, args.output)
    if args.output not in (None, "-"):
        _print_json({"preflight": str(result), "captured_at": value["captured_at"], "git_available": value["git"].get("git_available")})
    else:
        sys.stdout.write(str(result))
    return 0


def _finalize(args: argparse.Namespace) -> int:
    result = finalize(preflight_path=args.preflight, draft_path=args.draft, output=args.output, force=args.force)
    if args.output == "-":
        sys.stdout.write(result.markdown)
    else:
        _print_json({"path": str(result.path) if result.path else None, "valid": True, "redactions": result.redactions, "budget": result.budget.to_dict(), "unknowns": [item["text"] for item in result.document["unknowns"]]})
    return 0


def _validate(args: argparse.Namespace) -> int:
    report = validate_file(args.capsule)
    if args.json_output:
        _print_json(report.to_dict())
    elif report.valid:
        sys.stdout.write(f"valid: {Path(args.capsule).resolve()}\n")
    else:
        sys.stderr.write(f"invalid: {report.errors[0] if report.errors else 'capsule validation failed'}\n")
    return report.code


def _load(args: argparse.Namespace) -> int:
    result = load_capsule(args.reference, cwd=args.cwd)
    if args.format == "json":
        _print_json(result.to_dict())
    else:
        sys.stdout.write(result.briefing)
    return 0


def _list(args: argparse.Namespace) -> int:
    paths = list_capsules(resolve_project_root(args.cwd))
    if args.json_output:
        _print_json({"capsules": [{"path": str(path), "filename": path.name, "bytes": path.stat().st_size} for path in paths]})
    else:
        for path in paths:
            sys.stdout.write(str(path) + "\n")
    return 0


def _source(args: argparse.Namespace) -> int:
    from .sources import source_command

    value = source_command(args)
    if isinstance(value, str):
        sys.stdout.write(value)
    else:
        _print_json(value)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "preflight":
            return _preflight(args)
        if args.command == "finalize":
            return _finalize(args)
        if args.command == "validate":
            return _validate(args)
        if args.command == "load":
            return _load(args)
        if args.command == "list":
            return _list(args)
        if args.command == "source":
            return _source(args)
        parser.error("a command is required")
    except HandoffError as exc:
        if getattr(locals().get("args"), "json_output", False) or getattr(locals().get("args"), "format", None) == "json":
            _print_json({"ok": False, "code": int(exc.code), "error": exc.message})
        else:
            sys.stderr.write(exc.message + "\n")
        return int(exc.code)
    except FileNotFoundError:
        sys.stderr.write("source or capsule not found\n")
        return int(ExitCode.SOURCE_NOT_FOUND)
    except ValueError as exc:
        sys.stderr.write(str(exc).replace("\n", " ")[:500] + "\n")
        return int(ExitCode.VALIDATION)
    except Exception:
        sys.stderr.write("unexpected internal failure\n")
        return int(ExitCode.INTERNAL)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
