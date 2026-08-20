"""Safe file inventory scanning for repository context collection."""

from __future__ import annotations

from pathlib import Path

from ..models import FileInfo
from ..repository import iter_project_files, list_repository_paths, resolve_repo
from .filters import language_for, sensitive_paths


def scan_files(repo: str | Path = ".", *, include_hidden: bool = False) -> list[FileInfo]:
    """Return safe file metadata without reading file contents."""

    root = resolve_repo(repo)
    result: list[FileInfo] = []
    for relative, full_path in iter_project_files(root, include_hidden=include_hidden):
        try:
            size = full_path.stat().st_size
        except OSError:
            continue
        result.append(
            FileInfo(
                path=relative,
                size=size,
                language=language_for(relative),
            )
        )
    return result


def excluded_sensitive_paths(
    repo: str | Path = ".", *, include_hidden: bool = False
) -> list[str]:
    """List secret-looking paths discovered before the safe-file filter."""

    root = resolve_repo(repo)
    paths = list_repository_paths(root, include_hidden=include_hidden) or []
    return sensitive_paths(paths)
