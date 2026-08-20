"""Unified command-line entry point for the planning bridge."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .artifacts import DEFAULT_GOAL, build_prompt, collect_context
from .context import collect_repository
from .diff import diff_plan, render_plan_diff
from .handoff import open_chat
from .memory import ProjectMemory
from .repository import resolve_repo, resolve_repo_path, write_text
from .validator import validate as validate_repository


def _add_collection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="repository directory (default: current directory)")
    parser.add_argument("--max-files", type=int, default=80, help="maximum files in the context")
    parser.add_argument("--max-file-bytes", type=int, default=12_000, help="maximum excerpt bytes per file")
    parser.add_argument("--max-total-bytes", type=int, default=120_000, help="maximum total excerpt bytes")
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="include hidden files when scanning a non-Git directory",
    )


def _add_repo_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="repository directory (default: current directory)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-pro-planning-bridge",
        description="Local-first planning, validation, diff, and project-memory tools.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="collect local planning artifacts")
    _add_collection_options(collect_parser)
    collect_parser.add_argument("--output-dir", default=None, help="artifact directory (default: .codex/pro-plan)")
    collect_parser.add_argument("-o", "--output", default=None, help="also write bounded CONTEXT.md to this path")

    init_parser = subparsers.add_parser("init", help="initialize context artifacts and project memory")
    _add_collection_options(init_parser)
    init_parser.add_argument("--output-dir", default=None, help="artifact directory (default: .codex/pro-plan)")

    request_parser = subparsers.add_parser(
        "prompt",
        aliases=["request"],
        help="collect context and generate REQUEST.md",
    )
    _add_collection_options(request_parser)
    request_parser.add_argument("--goal", "--request", dest="user_request", default=DEFAULT_GOAL)
    request_parser.add_argument("--template", default=None, help="planner template path")
    request_parser.add_argument("--output-dir", default=None, help="artifact directory (default: .codex/pro-plan)")
    request_parser.add_argument("-o", "--output", default=None, help="copy REQUEST.md to this path as well")

    handoff_parser = subparsers.add_parser("handoff", help="show the manual Pro handoff checklist")
    _add_repo_option(handoff_parser)
    handoff_parser.add_argument("--request", default=".codex/pro-plan/REQUEST.md")
    handoff_parser.add_argument("--plan", default=".codex/pro-plan/PLAN.md")

    open_parser = subparsers.add_parser("open", help="copy REQUEST.md and open ChatGPT manually")
    _add_repo_option(open_parser)
    open_parser.add_argument("--request", default=".codex/pro-plan/REQUEST.md")
    open_parser.add_argument("--url", default="https://chatgpt.com/")
    open_parser.add_argument("--no-pause", action="store_true")

    validate_parser = subparsers.add_parser("validate", help="validate PLAN.md against repository facts")
    _add_repo_option(validate_parser)
    validate_parser.add_argument("--plan", default=".codex/pro-plan/PLAN.md")
    validate_parser.add_argument("--output", default=".codex/pro-plan/VALIDATION_REPORT.md")
    validate_parser.add_argument("--format", choices=("text", "json"), default="text")

    diff_parser = subparsers.add_parser("diff", help="compare PLAN.md with local repository changes")
    _add_repo_option(diff_parser)
    diff_parser.add_argument("--plan", default=".codex/pro-plan/PLAN.md")
    diff_parser.add_argument("--output", default=".codex/pro-plan/PLAN_DIFF.md")
    diff_parser.add_argument("--base", default=None, help="Git commit/ref to compare against")
    diff_parser.add_argument("--format", choices=("text", "json"), default="text")

    memory_parser = subparsers.add_parser("memory", help="manage persistent project memory")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)

    memory_init = memory_subparsers.add_parser("init", help="create missing project-memory documents")
    _add_repo_option(memory_init)
    memory_init.add_argument("--overwrite", action="store_true", help="replace existing memory templates")

    memory_show = memory_subparsers.add_parser("show", help="print project memory")
    _add_repo_option(memory_show)
    memory_show.add_argument("--document", default=None, help="one document name, such as decisions.md")

    memory_list = memory_subparsers.add_parser("list", help="list ADR entries and memory metadata")
    _add_repo_option(memory_list)

    memory_write = memory_subparsers.add_parser("write", help="write or append a memory document")
    _add_repo_option(memory_write)
    memory_write.add_argument("--document", required=True)
    memory_write.add_argument("--content", required=True)
    memory_write.add_argument("--append", action="store_true")

    memory_record = memory_subparsers.add_parser("record-plan", help="record a PLAN.md summary as an ADR")
    _add_repo_option(memory_record)
    memory_record.add_argument("--plan", default=".codex/pro-plan/PLAN.md")

    memory_adr = memory_subparsers.add_parser("adr-create", help="create a numbered architecture decision record")
    _add_repo_option(memory_adr)
    memory_adr.add_argument("--title", required=True)
    memory_adr.add_argument("--status", default="Proposed")
    content_group = memory_adr.add_mutually_exclusive_group()
    content_group.add_argument("--content", default=None)
    content_group.add_argument("--content-file", default=None)

    return parser


def _collect_context_args(args: argparse.Namespace):
    return collect_repository(
        args.repo,
        max_files=args.max_files,
        max_file_bytes=args.max_file_bytes,
        max_total_bytes=args.max_total_bytes,
        include_hidden=args.include_hidden,
    )


def _run(args: argparse.Namespace) -> int:
    if args.command == "init":
        artifacts = collect_context(args.repo, args.output_dir)
        memory = ProjectMemory(args.repo)
        memory.initialize()
        print("Initialized:")
        for path in artifacts.values():
            print(f"- {path}")
        print(f"- {memory.directory}")
        return 0

    if args.command == "collect":
        artifacts = collect_context(args.repo, args.output_dir)
        print("Generated:")
        for path in artifacts.values():
            print(f"- {path}")
        if args.output:
            context = _collect_context_args(args)
            output = resolve_repo_path(resolve_repo(args.repo), args.output)
            write_text(output, context.to_markdown())
            print(f"- {output}")
        return 0

    if args.command in {"prompt", "request"}:
        artifacts = collect_context(args.repo, args.output_dir)
        request_path = build_prompt(
            args.repo,
            user_request=args.user_request,
            template=args.template,
            output_dir=args.output_dir,
        )
        if args.output:
            root = resolve_repo(args.repo)
            output = resolve_repo_path(root, args.output)
            write_text(output, request_path.read_text(encoding="utf-8"))
            request_path = output
        print(f"Generated {request_path}")
        print("Review REQUEST.md before copying it into ChatGPT Pro manually.")
        return 0

    if args.command == "handoff":
        root = resolve_repo(args.repo)
        request_path = resolve_repo_path(root, args.request)
        if not request_path.is_file():
            print(f"Request file not found: {request_path}", file=sys.stderr)
            return 2
        plan_path = resolve_repo_path(root, args.plan)
        print(f"Request ready: {request_path}")
        print("\nManual handoff:")
        print("1. Open ChatGPT Pro in your browser.")
        print(f"2. Review and paste the contents of {request_path}.")
        print(f"3. Save the response as {plan_path}.")
        print(f"4. Run: codex-pro-planning-bridge validate --repo {root} --plan {plan_path}")
        return 0

    if args.command == "open":
        return open_chat(
            args.repo,
            request=args.request,
            url=args.url,
            pause=not args.no_pause,
        )

    if args.command == "validate":
        report_path, passed = validate_repository(args.repo, plan=args.plan, output=args.output)
        if args.format == "json":
            print(json.dumps({"report": str(report_path), "passed": passed}, indent=2))
        else:
            print(report_path.read_text(encoding="utf-8"))
        return 0 if passed else 1

    if args.command == "diff":
        report_path, result = diff_plan(args.repo, plan=args.plan, output=args.output, base=args.base)
        if args.format == "json":
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(render_plan_diff(result))
            print(f"Wrote {report_path}")
        return 0 if result.ok else 1

    if args.command == "memory":
        memory = ProjectMemory(args.repo)
        if args.memory_command == "init":
            paths = memory.initialize(overwrite=args.overwrite)
            if paths:
                for path in paths:
                    print(f"Created {path}")
            else:
                print(f"Project memory already initialized at {memory.directory}")
            return 0
        if args.memory_command == "show":
            if args.document:
                print(memory.document(args.document).content)
            else:
                print(memory.to_markdown())
            return 0
        if args.memory_command == "list":
            metadata = memory.metadata()
            print(f"Memory format version: {metadata.get('version', 'unknown')}")
            print(f"ADR entries: {metadata.get('entries', len(memory.list_adrs()))}")
            for entry in memory.list_adrs():
                print(f"- {entry.key}: {entry.path.relative_to(memory.root).as_posix()}")
            return 0
        if args.memory_command == "write":
            path = memory.write(args.document, args.content, append=args.append)
            print(f"Updated {path}")
            return 0
        if args.memory_command == "record-plan":
            print(f"Recorded {memory.record_plan(args.plan)}")
            return 0
        if args.memory_command == "adr-create":
            memory.initialize()
            content = args.content
            if args.content_file:
                content_path = resolve_repo_path(memory.root, args.content_file)
                if not content_path.is_file():
                    raise ValueError(f"ADR content file does not exist: {content_path}")
                content = content_path.read_text(encoding="utf-8")
            print(
                f"Created {memory.create_adr(args.title, status=args.status, content=content)}"
            )
            return 0

    raise AssertionError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
