"""Collect the files used by the v0.1 planning bridge workflow."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

try:
    from ._common import (
        PROJECT_ROOT,
        SUPPORTED_MANIFESTS,
        iter_project_files,
        resolve_repo,
        resolve_repo_path,
        run_git,
        git_status,
        write_text,
    )
except ImportError:  # Allow: python scripts/collect_context.py
    from _common import (  # type: ignore
        PROJECT_ROOT,
        SUPPORTED_MANIFESTS,
        iter_project_files,
        resolve_repo,
        resolve_repo_path,
        run_git,
        git_status,
        write_text,
    )


def _tree(paths: list[str]) -> str:
    return "\n".join(paths) if paths else "(no project files found)"


def collect_context(repo: str | Path = ".", output_dir: str | Path | None = None) -> dict[str, Path]:
    """Scan ``repo`` and write the three requested planning artifacts."""

    root = resolve_repo(repo)
    destination = (
        resolve_repo_path(root, output_dir)
        if output_dir is not None
        else root / ".codex" / "pro-plan"
    )
    files = iter_project_files(root)
    paths = [relative for relative, _ in files]
    status = git_status(root)
    generated_at = datetime.now(timezone.utc).isoformat()
    manifests = set(paths)

    manifest_lines = [
        f"- [{'x' if manifest in manifests else ' '}] `{manifest}`"
        for manifest in SUPPORTED_MANIFESTS
    ]
    context = "\n".join(
        [
            "# Project Context",
            "",
            f"- Project: `{root.name or root}`",
            f"- Generated at: `{generated_at}`",
            f"- Files included in tree: `{len(paths)}`",
            "- Collection is local-only; no API or network upload is performed.",
            "",
            "## Recognized Project Manifests",
            "",
            *manifest_lines,
            "",
            "## Ignore Policy",
            "",
            "The collector excludes `.git`, `node_modules`, `dist`, `build`, `.codex`, `.env` files, and secret/key-looking paths.",
            "",
            "## Git Snapshot",
            "",
            "See `git-status.txt` for the complete sanitized status snapshot.",
            "",
            "## Repository Tree",
            "",
            "See `repo-tree.txt` for the sanitized file list.",
        ]
    )

    output_files = {
        "tree": write_text(destination / "repo-tree.txt", _tree(paths)),
        "status": write_text(destination / "git-status.txt", status),
        "context": write_text(destination / "project-context.md", context),
    }
    return output_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect local project context for Pro planning.")
    parser.add_argument("--repo", default=".", help="project directory (default: current directory)")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="artifact directory (default: <repo>/.codex/pro-plan)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        files = collect_context(args.repo, args.output_dir)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print("Generated:")
    for path in files.values():
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
