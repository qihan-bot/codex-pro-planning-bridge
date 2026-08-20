"""Orchestrate the independent Context Collector components."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..models import FileInfo, GitState, ProjectContext
from ..repository import (
    git_changed_files,
    git_status_lines,
    resolve_repo,
    run_git,
)
from .detector import detect_dependencies, detect_project_types
from .filters import is_text_file, priority, read_excerpt
from .scanner import excluded_sensitive_paths, scan_files


def collect_repository(
    root: str | Path = ".",
    *,
    max_files: int = 80,
    max_file_bytes: int = 12_000,
    max_total_bytes: int = 120_000,
    include_hidden: bool = False,
) -> ProjectContext:
    """Collect bounded, redacted repository metadata and excerpts locally."""

    if max_files < 1:
        raise ValueError("max_files must be at least 1")
    if max_file_bytes < 1 or max_total_bytes < 1:
        raise ValueError("excerpt byte limits must be positive")

    root_path = resolve_repo(root)
    scanned = sorted(
        scan_files(root_path, include_hidden=include_hidden),
        key=lambda item: priority(item.path),
    )
    selected = scanned[:max_files]
    omitted_files = max(0, len(scanned) - len(selected))
    files: list[FileInfo] = []
    excerpt_bytes = 0
    for file_info in selected:
        full_path = root_path / Path(file_info.path)
        excerpt = None
        excerpt_truncated = False
        if is_text_file(file_info.language):
            remaining = max_total_bytes - excerpt_bytes
            if remaining > 0:
                excerpt, excerpt_truncated = read_excerpt(
                    full_path, min(max_file_bytes, remaining)
                )
                if excerpt is not None:
                    excerpt_bytes += len(excerpt.encode("utf-8"))
        files.append(
            replace(
                file_info,
                excerpt=excerpt,
                excerpt_truncated=excerpt_truncated,
            )
        )

    branch = run_git(root_path, ["branch", "--show-current"])
    if branch == "":
        branch = run_git(root_path, ["rev-parse", "--short", "HEAD"])
    is_repository = run_git(root_path, ["rev-parse", "--git-dir"]) is not None
    status = git_status_lines(root_path)
    recent_output = run_git(root_path, ["log", "-5", "--pretty=format:%h %s"])
    git_state = GitState(
        branch=branch or None,
        status=status,
        recent_commits=(recent_output or "").splitlines(),
        changed_files=git_changed_files(root_path),
        is_repository=is_repository,
    )
    return ProjectContext(
        root=root_path,
        project_types=detect_project_types(scanned),
        files=sorted(files, key=lambda item: item.path),
        dependencies=detect_dependencies(root_path, scanned),
        git_state=git_state,
        excluded_sensitive=excluded_sensitive_paths(
            root_path, include_hidden=include_hidden
        ),
        omitted_files=omitted_files,
    )
