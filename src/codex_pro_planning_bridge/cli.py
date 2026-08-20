"""Command-line interface for the planning bridge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .context import collect_repository
from .plan import validate_plan
from .prompt import build_request


def _add_collection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="repository directory (default: current directory)")
    parser.add_argument("--max-files", type=int, default=80, help="maximum files in the context")
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=12_000,
        help="maximum excerpt bytes per file",
    )
    parser.add_argument(
        "--max-total-bytes",
        type=int,
        default=120_000,
        help="maximum total excerpt bytes",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="include hidden files when scanning a non-Git directory",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-pro-planning-bridge",
        description="Generate local-first architecture planning requests and validate plans.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="collect repository context")
    _add_collection_options(collect_parser)
    collect_parser.add_argument("-o", "--output", default="CONTEXT.md", help="output Markdown path")

    request_parser = subparsers.add_parser("request", help="generate REQUEST.md for ChatGPT Pro")
    _add_collection_options(request_parser)
    request_parser.add_argument("--goal", required=True, help="the user request to plan")
    request_parser.add_argument("-o", "--output", default="REQUEST.md", help="output Markdown path")

    handoff_parser = subparsers.add_parser("handoff", help="show the manual Pro handoff checklist")
    handoff_parser.add_argument("--request", default="REQUEST.md", help="generated request path")
    handoff_parser.add_argument("--plan", default="PLAN.md", help="expected plan path")

    validate_parser = subparsers.add_parser("validate", help="validate a ChatGPT Pro plan")
    validate_parser.add_argument("--plan", default="PLAN.md", help="plan Markdown path")
    validate_parser.add_argument("--format", choices=("text", "json"), default="text")

    return parser


def _collect_args(args: argparse.Namespace):
    return collect_repository(
        args.repo,
        max_files=args.max_files,
        max_file_bytes=args.max_file_bytes,
        max_total_bytes=args.max_total_bytes,
        include_hidden=args.include_hidden,
    )


def _write_text(path: str | Path, content: str) -> Path:
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")
    return output


def _run(args: argparse.Namespace) -> int:
    if args.command == "collect":
        context = _collect_args(args)
        output = _write_text(args.output, context.to_markdown())
        print(f"Wrote {output} ({len(context.files)} files, {context.omitted_files} omitted).")
        return 0

    if args.command == "request":
        context = _collect_args(args)
        output = _write_text(args.output, build_request(context, args.goal))
        print(
            f"Wrote {output}. Review it locally, then paste it into ChatGPT Pro manually."
        )
        return 0

    if args.command == "handoff":
        request_path = Path(args.request).expanduser()
        if not request_path.is_file():
            print(f"Request file not found: {request_path}", file=sys.stderr)
            return 2
        plan_path = Path(args.plan).expanduser()
        print(f"Request ready: {request_path.resolve()}")
        print("\nManual handoff:")
        print("1. Open ChatGPT Pro in your browser.")
        print(f"2. Review and paste the contents of {request_path}.")
        print(f"3. Save the response as {plan_path}.")
        print(f"4. Run: codex-pro-planning-bridge validate --plan {plan_path}")
        return 0

    if args.command == "validate":
        plan_path = Path(args.plan).expanduser()
        if not plan_path.is_file():
            print(f"Plan file not found: {plan_path}", file=sys.stderr)
            return 2
        result = validate_plan(plan_path.read_text(encoding="utf-8"))
        if args.format == "json":
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(result.to_text())
        return 0 if result.ok else 1

    raise AssertionError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
