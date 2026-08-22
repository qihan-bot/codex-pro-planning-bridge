"""Unified command-line entry point for the planning bridge."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .approval import PlanApprovalStore
from .artifacts import DEFAULT_GOAL, build_prompt, collect_context
from .context import collect_repository
from .diff import diff_plan, render_plan_diff
from .handoff import open_chat
from .integrity import IntegrityChecker
from .loop import run_loop
from .memory import ProjectMemory
from .repository import resolve_repo, resolve_repo_path, write_text
from .recovery import RecoveryEngine
from .registry import RegistryError, RepositoryRegistry
from .snapshot import SnapshotManager
from .state import WorkflowStateStore
from .validator import validate as validate_repository
from .workflow import Workflow


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


def _add_registry_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--registry-path",
        default=None,
        help="local registry file override (defaults to the per-user config path)",
    )


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

    loop_parser = subparsers.add_parser(
        "loop",
        help="advance the recoverable local planning workflow",
    )
    _add_repo_option(loop_parser)
    loop_parser.add_argument("--goal", "--request", dest="user_request", default=DEFAULT_GOAL)
    loop_parser.add_argument("--plan", default=".codex/pro-plan/PLAN.md")
    loop_parser.add_argument("--base", default=None, help="Git commit/ref for implementation review")
    loop_parser.add_argument(
        "--review",
        action="store_true",
        help="review local implementation drift and update project memory",
    )
    loop_parser.add_argument(
        "--reset",
        action="store_true",
        help="start a new workflow while retaining local history",
    )
    loop_parser.add_argument("--format", choices=("text", "json"), default="text")

    approve_parser = subparsers.add_parser(
        "approve",
        help="record or revoke explicit human approval for PLAN.md",
    )
    _add_repo_option(approve_parser)
    approve_parser.add_argument("--plan", default=".codex/pro-plan/PLAN.md")
    approve_parser.add_argument("--approved-by", default="user")
    approve_parser.add_argument(
        "--expires-in",
        type=int,
        default=None,
        help="approval validity window in seconds",
    )
    approve_parser.add_argument("--revoke", action="store_true")
    approve_parser.add_argument("--reason", default="plan approval revoked")
    approve_parser.add_argument("--format", choices=("text", "json"), default="text")

    status_parser = subparsers.add_parser(
        "status",
        help="inspect the current workflow state without advancing it",
    )
    _add_repo_option(status_parser)
    status_parser.add_argument("--plan", default=".codex/pro-plan/PLAN.md")
    status_parser.add_argument("--format", choices=("text", "json"), default="text")

    resume_parser = subparsers.add_parser(
        "resume",
        help="resume a paused or interrupted workflow",
    )
    _add_repo_option(resume_parser)
    resume_parser.add_argument("--goal", "--request", dest="user_request", default=DEFAULT_GOAL)
    resume_parser.add_argument("--plan", default=".codex/pro-plan/PLAN.md")
    resume_parser.add_argument("--base", default=None, help="Git commit/ref for implementation review")
    resume_parser.add_argument("--review", action="store_true")
    resume_parser.add_argument(
        "--snapshot",
        default="latest",
        help="snapshot id used for the pre-resume integrity check",
    )
    resume_parser.add_argument("--format", choices=("text", "json"), default="text")

    pause_parser = subparsers.add_parser("pause", help="pause the current workflow")
    _add_repo_option(pause_parser)
    pause_parser.add_argument("--reason", default="workflow paused by user")

    cancel_parser = subparsers.add_parser("cancel", help="cancel the current workflow")
    _add_repo_option(cancel_parser)
    cancel_parser.add_argument("--reason", default="workflow cancelled by user")

    history_parser = subparsers.add_parser(
        "history",
        help="show transition history and the append-only event log",
    )
    _add_repo_option(history_parser)
    history_parser.add_argument("--format", choices=("text", "json"), default="text")

    events_parser = subparsers.add_parser(
        "events",
        aliases=["event"],
        help="query the append-only workflow event log without changing state",
    )
    _add_repo_option(events_parser)
    events_parser.add_argument("--event", default=None, help="exact event name filter")
    events_parser.add_argument("--actor", default=None, help="exact actor filter")
    events_parser.add_argument("--from-state", dest="from_state", default=None)
    events_parser.add_argument("--to-state", dest="to_state", default=None)
    events_parser.add_argument("--since", default=None, help="ISO-8601 lower timestamp bound")
    events_parser.add_argument("--until", default=None, help="ISO-8601 upper timestamp bound")
    events_parser.add_argument("--limit", type=int, default=None)
    events_parser.add_argument("--format", choices=("text", "json"), default="text")

    rollback_parser = subparsers.add_parser(
        "rollback",
        help="restore workflow metadata to an earlier event target state",
    )
    _add_repo_option(rollback_parser)
    rollback_parser.add_argument(
        "--to",
        "--to-event",
        dest="event_index",
        required=True,
        type=int,
        help="one-based event index shown by cpb events",
    )
    rollback_parser.add_argument("--reason", default="workflow rollback requested")
    rollback_parser.add_argument("--format", choices=("text", "json"), default="text")

    recover_parser = subparsers.add_parser(
        "recover",
        help="restore workflow metadata from a validated runtime snapshot",
    )
    _add_repo_option(recover_parser)
    recover_parser.add_argument("--snapshot", default="latest")
    recover_parser.add_argument("--plan", default=".codex/pro-plan/PLAN.md")
    recover_parser.add_argument("--reason", default="workflow recovered from snapshot")
    recover_parser.add_argument("--format", choices=("text", "json"), default="text")

    snapshot_parser = subparsers.add_parser(
        "snapshot",
        help="create and inspect local workflow runtime snapshots",
    )
    snapshot_subparsers = snapshot_parser.add_subparsers(
        dest="snapshot_command",
        required=True,
    )

    snapshot_create = snapshot_subparsers.add_parser(
        "create",
        help="capture the current workflow runtime context",
    )
    _add_repo_option(snapshot_create)
    snapshot_create.add_argument("--plan", default=".codex/pro-plan/PLAN.md")
    snapshot_create.add_argument("--format", choices=("text", "json"), default="text")

    snapshot_list = snapshot_subparsers.add_parser(
        "list",
        help="list immutable workflow runtime snapshots",
    )
    _add_repo_option(snapshot_list)
    snapshot_list.add_argument("--format", choices=("text", "json"), default="text")

    snapshot_show = snapshot_subparsers.add_parser(
        "show",
        help="show one workflow runtime snapshot",
    )
    _add_repo_option(snapshot_show)
    snapshot_show.add_argument("snapshot_id", nargs="?", default=None)
    snapshot_show.add_argument("--id", dest="snapshot_id_option", default=None)
    snapshot_show.add_argument("--format", choices=("text", "json"), default="text")

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

    memory_migrate = memory_subparsers.add_parser(
        "migrate",
        help="apply local project-memory schema migrations",
    )
    _add_repo_option(memory_migrate)

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

    registry_parser = subparsers.add_parser(
        "repo",
        help="manage the local repository allowlist",
    )
    registry_subparsers = registry_parser.add_subparsers(
        dest="repo_command",
        required=True,
    )

    repo_add = registry_subparsers.add_parser("add", help="register a repository path")
    repo_add.add_argument("repository_id")
    repo_add.add_argument("path")
    repo_add.add_argument("--display-name", default=None)
    repo_add.add_argument("--notes", default=None)
    repo_add.add_argument("--allow-non-git", action="store_true")
    repo_add.add_argument("--yes", action="store_true", help="skip the local confirmation prompt")
    repo_add.add_argument("--format", choices=("text", "json"), default="text")
    _add_registry_option(repo_add)

    repo_list = registry_subparsers.add_parser("list", help="list registered repositories")
    repo_list.add_argument("--format", choices=("text", "json"), default="text")
    _add_registry_option(repo_list)

    repo_show = registry_subparsers.add_parser("show", help="show one registered repository")
    repo_show.add_argument("repository_id")
    repo_show.add_argument("--format", choices=("text", "json"), default="text")
    _add_registry_option(repo_show)

    repo_remove = registry_subparsers.add_parser("remove", help="remove a repository registration")
    repo_remove.add_argument("repository_id")
    repo_remove.add_argument("--yes", action="store_true", help="skip the local confirmation prompt")
    repo_remove.add_argument("--format", choices=("text", "json"), default="text")
    _add_registry_option(repo_remove)

    repo_doctor = registry_subparsers.add_parser(
        "doctor",
        help="check one registered repository without modifying it",
    )
    repo_doctor.add_argument("repository_id")
    repo_doctor.add_argument("--format", choices=("text", "json"), default="text")
    _add_registry_option(repo_doctor)

    return parser


def _collect_context_args(args: argparse.Namespace):
    return collect_repository(
        args.repo,
        max_files=args.max_files,
        max_file_bytes=args.max_file_bytes,
        max_total_bytes=args.max_total_bytes,
        include_hidden=args.include_hidden,
    )


def _workflow_status(repo: str, plan: str) -> dict[str, Any]:
    root = resolve_repo(repo)
    store = WorkflowStateStore(root)
    snapshot = store.load(default_plan=plan)
    approval = PlanApprovalStore(root, plan=snapshot.plan or plan)
    return {
        "state": snapshot.state.value,
        "goal": snapshot.goal,
        "plan": str(snapshot.plan) if snapshot.plan else None,
        "started": snapshot.started.isoformat(),
        "updated": snapshot.updated.isoformat(),
        "next_action": snapshot.next_action,
        "error": snapshot.error,
        "paused_from": snapshot.paused_from.value if snapshot.paused_from else None,
        "approval": approval.status(),
    }


def _print_loop_result(loop_result, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(loop_result.to_dict(), indent=2, ensure_ascii=False))
        return
    print(f"Workflow state: {loop_result.state.value}")
    for message in loop_result.messages:
        print(f"- {message}")
    print(f"Next action: {loop_result.next_action}")
    for name, path in loop_result.artifacts.items():
        print(f"- {name}: {path}")


def _print_event_records(records, output_format: str) -> None:
    if output_format == "json":
        print(
            json.dumps(
                {"count": len(records), "events": [item.to_dict() for item in records]},
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    print(f"Events: {len(records)}")
    for record in records:
        event = record.event
        print(
            f"#{record.index} {event.timestamp.isoformat()} {event.event} "
            f"{event.from_state.value if event.from_state else '(none)'} -> "
            f"{event.to_state.value} [{event.actor}] {event.reason}"
        )


def _print_repository_payload(payload: object, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if isinstance(payload, dict) and "repository" in payload:
        repository = payload["repository"]
        if isinstance(repository, dict):
            print(f"Repository: {repository.get('repository_id', '(unknown)')}")
            print(f"Display name: {repository.get('display_name', '')}")
            print(f"Path: {repository.get('canonical_path', '')}")
            print(f"Enabled: {repository.get('enabled', False)}")
            print(f"Read: {repository.get('read', False)}")
            if "health" in payload:
                health = payload["health"]
                if isinstance(health, dict):
                    print(f"Health: {'PASS' if health.get('ok') else 'FAILED'}")
                    print(f"Git: {health.get('is_git', False)}")
                    print(f"HEAD: {health.get('head') or '(none)'}")
                    print(f"Branch: {health.get('branch') or '(detached or none)'}")
                    print(f"Dirty: {health.get('dirty')}")
                    print(f"Observed redacted paths: {health.get('redacted_count', 0)}")
                    print(f"Observed omitted paths: {health.get('omitted_count', 0)}")
                    print(f"Scan truncated: {health.get('scan_truncated', False)}")
                    for issue in health.get("issues", []):
                        print(f"- {issue}")
                    for warning in health.get("warnings", []):
                        print(f"Warning: {warning}")
            return
    if isinstance(payload, dict) and "repositories" in payload:
        repositories = payload["repositories"]
        print(f"Repositories: {len(repositories) if isinstance(repositories, list) else 0}")
        if isinstance(repositories, list):
            for repository in repositories:
                if not isinstance(repository, dict):
                    continue
                enabled = "enabled" if repository.get("enabled") else "disabled"
                readable = "read" if repository.get("read") else "no-read"
                print(
                    f"- {repository.get('repository_id', '(unknown)')} "
                    f"[{enabled}, {readable}]: {repository.get('canonical_path', '')}"
                )
            return
    if isinstance(payload, dict) and "health" in payload:
        health = payload["health"]
        if isinstance(health, dict):
            print(f"Repository health: {'PASS' if health.get('ok') else 'FAILED'}")
            print(f"Path: {health.get('canonical_path', '')}")
            print(f"Git: {health.get('is_git', False)}")
            print(f"Dirty: {health.get('dirty')}")
            print(f"Observed redacted paths: {health.get('redacted_count', 0)}")
            print(f"Observed omitted paths: {health.get('omitted_count', 0)}")
            print(f"Symlink escapes: {health.get('symlink_escapes', 0)}")
            print(f"Scan truncated: {health.get('scan_truncated', False)}")
            for warning in health.get("warnings", []):
                print(f"Warning: {warning}")
            for issue in health.get("issues", []):
                print(f"Issue: {issue}")
            return
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _confirm(prompt: str) -> bool:
    try:
        answer = input(prompt).strip().casefold()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _run(args: argparse.Namespace) -> int:
    if args.command == "repo":
        registry = RepositoryRegistry(args.registry_path)
        if args.repo_command == "add":
            if args.format == "json" and not args.yes:
                raise RegistryError(
                    "explicit confirmation is required; pass --yes",
                    code="confirmation_required",
                )
            preview = registry.preview(args.path, allow_non_git=args.allow_non_git)
            if not args.yes:
                print(f"Register repository {args.repository_id} at {preview.canonical_path}")
                for warning in preview.warnings:
                    print(f"Warning: {warning}")
                if not _confirm("Continue? [y/N] "):
                    print("Registration cancelled.")
                    return 1
            registration = registry.add(
                args.repository_id,
                args.path,
                display_name=args.display_name,
                allow_non_git=args.allow_non_git,
                notes=args.notes,
            )
            health = registry.doctor(args.repository_id)
            repository_payload = {
                "repository": {"repository_id": registration.repository_id, **registration.to_dict()},
                "health": health.to_dict(),
            }
            _print_repository_payload(
                repository_payload,
                args.format,
            )
            return 0
        if args.repo_command == "list":
            repositories = registry.list()
            repository_list_payload = {
                "count": len(repositories),
                "repositories": [
                    {"repository_id": item.repository_id, **item.to_dict()}
                    for item in repositories
                ],
            }
            _print_repository_payload(
                repository_list_payload,
                args.format,
            )
            return 0
        if args.repo_command == "show":
            registration = registry.show(args.repository_id)
            health = registry.doctor(args.repository_id)
            repository_show_payload = {
                "repository": {"repository_id": registration.repository_id, **registration.to_dict()},
                "health": health.to_dict(),
            }
            _print_repository_payload(
                repository_show_payload,
                args.format,
            )
            return 0
        if args.repo_command == "remove":
            if args.format == "json" and not args.yes:
                raise RegistryError(
                    "explicit confirmation is required; pass --yes",
                    code="confirmation_required",
                )
            registration = registry.show(args.repository_id)
            if not args.yes:
                if not _confirm(f"Remove repository {registration.repository_id}? [y/N] "):
                    print("Removal cancelled.")
                    return 1
            removed = registry.remove(args.repository_id)
            repository_remove_payload = {
                "removed": removed.repository_id,
                "canonical_path": str(removed.canonical_path),
            }
            _print_repository_payload(repository_remove_payload, args.format)
            return 0
        if args.repo_command == "doctor":
            health = registry.doctor(args.repository_id)
            repository_health_payload = {"health": health.to_dict()}
            _print_repository_payload(repository_health_payload, args.format)
            return 0 if health.ok else 1
        raise AssertionError(f"unknown repository command: {args.repo_command}")

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

    if args.command == "approve":
        approval = PlanApprovalStore(args.repo, plan=args.plan)
        path = (
            approval.revoke(args.reason)
            if args.revoke
            else approval.approve(args.approved_by, expires_in=args.expires_in)
        )
        payload = approval.status()
        runtime_snapshot = SnapshotManager(args.repo, plan=args.plan).create()
        payload["runtime_snapshot"] = str(runtime_snapshot.path)
        if args.format == "json":
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            action = "revoked" if args.revoke else "recorded"
            print(f"Plan approval {action}: {path}")
            print(f"Approval status: {payload['status']}")
            print(f"Effective approval: {payload['effective']}")
            print(f"Runtime snapshot: {runtime_snapshot.path}")
        return 0

    if args.command == "status":
        payload = _workflow_status(args.repo, args.plan)
        if args.format == "json":
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"Workflow state: {payload['state']}")
            print(f"Goal: {payload['goal'] or '(none)'}")
            print(f"Plan: {payload['plan'] or '(none)'}")
            print(f"Approval effective: {payload['approval']['effective']}")
            if payload["next_action"]:
                print(f"Next action: {payload['next_action']}")
            if payload["error"]:
                print(f"Error: {payload['error']}")
        return 0

    if args.command == "history":
        store = WorkflowStateStore(args.repo)
        payload = {
            "transitions": [item.to_dict() for item in store.history()],
            "events": [item.to_dict() for item in store.events()],
        }
        if args.format == "json":
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print("Transition history:")
            for item in payload["transitions"]:
                print(
                    f"- {item['at']}: {item['from'] or '(none)'} -> {item['to']} "
                    f"({item['reason']})"
                )
            print("Event log:")
            for item in payload["events"]:
                print(
                    f"- {item['timestamp']}: {item['event']} "
                    f"{item['from'] or '(none)'} -> {item['to']} "
                    f"[{item['actor']}]"
                )
        return 0

    if args.command in {"events", "event"}:
        store = WorkflowStateStore(args.repo)
        records = store.query_events(
            event=args.event,
            actor=args.actor,
            from_state=args.from_state,
            to_state=args.to_state,
            since=args.since,
            until=args.until,
            limit=args.limit,
        )
        _print_event_records(records, args.format)
        return 0

    if args.command == "rollback":
        snapshot = Workflow(args.repo).rollback(args.event_index, args.reason)
        runtime_snapshot = SnapshotManager(args.repo, plan=snapshot.plan or ".codex/pro-plan/PLAN.md").create()
        payload = {
            "state": snapshot.state.value,
            "event_index": args.event_index,
            "next_action": snapshot.next_action,
            "runtime_snapshot": str(runtime_snapshot.path),
        }
        if args.format == "json":
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(
                f"Workflow rolled back to event #{args.event_index}: "
                f"{snapshot.state.value}"
            )
            print(f"Next action: {snapshot.next_action}")
            print(f"Runtime snapshot: {runtime_snapshot.path}")
        return 0

    if args.command == "recover":
        recovery_result = RecoveryEngine(args.repo, plan=args.plan).recover(
            args.snapshot,
            args.reason,
        )
        payload = recovery_result.to_dict()
        if args.format == "json":
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(
                f"Workflow recovered from snapshot #{recovery_result.snapshot_id}: "
                f"{recovery_result.state.value}"
            )
            print(f"Recovery event: #{recovery_result.recovery_event_index}")
            print("Next action: review state before continuing.")
        return 0

    if args.command == "snapshot":
        manager = SnapshotManager(
            args.repo,
            plan=getattr(args, "plan", ".codex/pro-plan/PLAN.md"),
        )
        if args.snapshot_command == "create":
            created_record = manager.create()
            payload = {
                "snapshot_path": str(created_record.path),
                **created_record.to_dict(),
            }
            if args.format == "json":
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(
                    f"Created workflow snapshot #{created_record.snapshot_id}: "
                    f"{created_record.path}"
                )
                print(f"State: {created_record.payload['workflow']['state']}")
                print(
                    f"History position: "
                    f"{created_record.payload['workflow']['history_position']}"
                )
            return 0
        if args.snapshot_command == "list":
            snapshot_records = manager.list_snapshots()
            payload = {
                "count": len(snapshot_records),
                "snapshots": [
                    {
                        "snapshot_path": str(snapshot_record.path),
                        **snapshot_record.to_dict(),
                    }
                    for snapshot_record in snapshot_records
                ],
            }
            if args.format == "json":
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(f"Snapshots: {len(snapshot_records)}")
                for snapshot_record in snapshot_records:
                    snapshot_payload = snapshot_record.payload
                    print(
                        f"#{snapshot_record.snapshot_id} {snapshot_payload['timestamp']} "
                        f"{snapshot_payload['workflow']['state']} {snapshot_record.path}"
                    )
            return 0
        if args.snapshot_command == "show":
            selected_id = args.snapshot_id_option or args.snapshot_id
            shown_record = manager.show(selected_id)
            payload = {
                "snapshot_path": str(shown_record.path),
                **shown_record.to_dict(),
            }
            if args.format == "json":
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(f"Workflow snapshot #{shown_record.snapshot_id}: {shown_record.path}")
                print(json.dumps(shown_record.to_dict(), indent=2, ensure_ascii=False))
            return 0
        raise AssertionError(f"unknown snapshot command: {args.snapshot_command}")

    if args.command == "pause":
        snapshot = Workflow(args.repo).pause(args.reason)
        runtime_snapshot = SnapshotManager(args.repo).create()
        print(f"Workflow paused from {snapshot.paused_from.value if snapshot.paused_from else 'unknown'}.")
        print(f"Runtime snapshot created: {runtime_snapshot.path}")
        return 0

    if args.command == "cancel":
        snapshot = Workflow(args.repo).cancel(args.reason)
        print(f"Workflow cancelled in state {snapshot.state.value}.")
        return 0

    if args.command == "resume":
        integrity_report = IntegrityChecker(args.repo, plan=args.plan).check(
            args.snapshot
        )
        if not integrity_report.passed:
            if args.format == "json":
                print(
                    json.dumps(
                        {"integrity": integrity_report.to_dict()},
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                print(integrity_report.render())
            return 1
        resume_result = run_loop(
            args.repo,
            goal=args.user_request,
            plan=args.plan,
            base=args.base,
            review=args.review,
            resume=True,
        )
        runtime_snapshot = SnapshotManager(args.repo, plan=args.plan).create()
        resume_result.artifacts["snapshot"] = runtime_snapshot.path
        if args.format == "json":
            resume_payload = resume_result.to_dict()
            resume_payload["integrity"] = integrity_report.to_dict()
            print(json.dumps(resume_payload, indent=2, ensure_ascii=False))
        else:
            print(integrity_report.render())
            _print_loop_result(resume_result, args.format)
        return 0 if resume_result.ok else 1

    if args.command == "loop":
        loop_result = run_loop(
            args.repo,
            goal=args.user_request,
            plan=args.plan,
            base=args.base,
            review=args.review,
            reset=args.reset,
        )
        runtime_snapshot = SnapshotManager(args.repo, plan=args.plan).create()
        loop_result.artifacts["snapshot"] = runtime_snapshot.path
        _print_loop_result(loop_result, args.format)
        return 0 if loop_result.ok else 1

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
        if args.memory_command == "migrate":
            paths = memory.migrate()
            if paths:
                for path in paths:
                    print(f"Created {path}")
            else:
                print(f"Project memory is already at the supported schema at {memory.directory}")
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
        if getattr(args, "command", None) == "repo" and getattr(args, "format", "text") == "json":
            error_code = getattr(error, "code", None)
            if not isinstance(error_code, str) or not error_code:
                error_code = "io_error" if isinstance(error, OSError) else "runtime_error"
            print(
                json.dumps(
                    {"error": {"code": error_code, "message": str(error)}},
                    ensure_ascii=False,
                )
            )
        else:
            print(f"error: {error}", file=sys.stderr)
        return 2
