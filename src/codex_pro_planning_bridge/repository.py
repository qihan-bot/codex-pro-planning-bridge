"""Shared local repository helpers.

The planning bridge intentionally keeps repository inspection local.  This
module is the single source of truth for path filtering, Git snapshots, and
safe text writes used by the CLI features.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from typing import Iterable

from .models import FileChange


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    ".venv",
    "venv",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".codex",
}

SENSITIVE_BASENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials.json",
    "credentials.yml",
    "credentials.yaml",
    "service-account.json",
}

SENSITIVE_SUFFIXES = {".pem", ".p12", ".pfx", ".key", ".jks"}
SENSITIVE_NAME_RE = re.compile(
    r"(?:^|[-_.])(secret|secrets|credential|credentials|passwords?|tokens?)(?:[-_.]|$)",
    re.IGNORECASE,
)

SUPPORTED_MANIFESTS = (
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
)


def resolve_repo(value: str | Path = ".") -> Path:
    repo = Path(value).expanduser().resolve()
    if not repo.is_dir():
        raise ValueError(f"project directory does not exist: {repo}")
    return repo


def resolve_repo_path(repo: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (repo / path).resolve()


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
    return path


def is_sensitive_path(path: str | Path) -> bool:
    """Return whether a relative path looks like it may contain a secret."""

    path_obj = Path(path)
    basename = path_obj.name.lower()
    if basename in {item.lower() for item in SENSITIVE_BASENAMES}:
        return True
    if path_obj.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    if any(part.lower() in {"secret", "secrets", "credentials", "private"} for part in path_obj.parts):
        return True
    return bool(SENSITIVE_NAME_RE.search(path_obj.stem))


def is_ignored_path(relative: str | Path) -> bool:
    """Apply the repository-wide local scan ignore policy."""

    path = Path(str(relative).replace("\\", "/"))
    if any(part in DEFAULT_EXCLUDED_DIRS for part in path.parts):
        return True
    name = path.name.lower()
    if name == ".env":
        return True
    if name.startswith(".env.") and not name.endswith((".example", ".sample", ".template")):
        return True
    return is_sensitive_path(path)


def run_git(repo: Path, args: Iterable[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_repository_state(
    repo: str | Path = ".",
    *,
    excluded_paths: Iterable[str | Path] = (),
) -> tuple[str | None, bool | None]:
    """Return the current commit and dirty flag with local artifact exclusions."""

    root = resolve_repo(repo)
    commit = run_git(root, ("rev-parse", "HEAD"))
    if commit is None:
        return None, None
    excluded = {
        Path(str(path)).as_posix().strip("/")
        for path in excluded_paths
    }
    status = run_git(root, ("status", "--porcelain", "--untracked-files=all"))
    if not status:
        return commit, False
    dirty = False
    for line in status.splitlines():
        path = _status_path(line)
        normalized = Path(path).as_posix().strip("/")
        if any(
            normalized == prefix or normalized.startswith(f"{prefix}/")
            for prefix in excluded
        ):
            continue
        dirty = True
        break
    return commit, dirty


def list_repository_paths(repo: Path, *, include_hidden: bool = False) -> list[str] | None:
    """List Git-known paths, falling back to a bounded filesystem walk."""

    output = run_git(repo, ("ls-files", "--cached", "--others", "--exclude-standard"))
    if output is not None:
        return [line.replace("\\", "/") for line in output.splitlines() if line.strip()]

    paths: list[str] = []
    for current, directories, filenames in os.walk(repo, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            directory
            for directory in directories
            if not is_ignored_path(current_path / directory / "marker")
            and (include_hidden or not directory.startswith("."))
        )
        for filename in sorted(filenames):
            if not include_hidden and filename.startswith(".") and not is_sensitive_path(filename):
                continue
            full_path = current_path / filename
            try:
                paths.append(full_path.relative_to(repo).as_posix())
            except ValueError:
                continue
    return paths


def iter_project_files(
    repo: str | Path = ".", *, include_hidden: bool = False
) -> list[tuple[str, Path]]:
    """Return safe project files as ``(relative_path, absolute_path)`` pairs."""

    root = resolve_repo(repo)
    candidates = list_repository_paths(root, include_hidden=include_hidden) or []
    result: list[tuple[str, Path]] = []
    for relative in sorted(set(candidates)):
        if is_ignored_path(relative):
            continue
        full_path = root / Path(relative)
        try:
            if full_path.is_file():
                result.append((relative, full_path))
        except OSError:
            continue
    return result


def _status_path(line: str) -> str:
    path = line[2:].strip() if len(line) >= 2 else line.strip()
    if " -> " in path:
        path = path.rsplit(" -> ", 1)[-1]
    return path.strip().strip('"').replace("\\", "/")


def git_status_lines(repo: str | Path = ".") -> list[str]:
    """Return a sanitized short Git status suitable for local reports."""

    root = resolve_repo(repo)
    output = run_git(root, ("status", "--short", "--untracked-files=all"))
    if output is None:
        return ["Git metadata unavailable."]
    if not output:
        return ["Working tree clean."]

    lines: list[str] = []
    for line in output.splitlines():
        path = _status_path(line)
        if is_sensitive_path(path):
            lines.append(line[:2] + " [sensitive path omitted]")
        else:
            lines.append(line)
    return lines


def git_status(repo: str | Path = ".") -> str:
    return "\n".join(git_status_lines(repo))


def git_changed_files(repo: str | Path = ".", *, base: str | None = None) -> list[str]:
    """Return changed paths from Git commits and the current working tree.

    ``base`` compares the working tree to a known commit or reference.  With
    no base, both staged and unstaged changes relative to ``HEAD`` are used,
    plus untracked files.  The result is path-only and never executes project
    code.
    """

    return sorted({change.path for change in git_file_changes(repo, base=base)})


def _parse_name_status(output: str | None) -> list[FileChange]:
    changes: list[FileChange] = []
    if not output:
        return changes
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) >= 3 and fields[0].startswith(("R", "C")):
            status = fields[0][0]
            similarity = None
            try:
                similarity = int(fields[0][1:])
            except ValueError:
                pass
            changes.append(
                FileChange(
                    status=status,
                    previous_path=fields[-2].replace("\\", "/"),
                    path=fields[-1].replace("\\", "/"),
                    similarity=similarity,
                )
            )
            continue
        if len(fields) >= 2:
            changes.append(
                FileChange(status=fields[0][0], path=fields[-1].replace("\\", "/"))
            )
    return changes


def _status_changes(output: str | None) -> list[FileChange]:
    changes: list[FileChange] = []
    if not output:
        return changes
    for line in output.splitlines():
        if len(line) < 3:
            continue
        code = line[:2].strip()
        path = line[2:].strip().strip('"').replace("\\", "/")
        if " -> " in path:
            previous, current = path.rsplit(" -> ", 1)
            changes.append(FileChange(status="R", previous_path=previous, path=current))
        elif path:
            changes.append(FileChange(status=code[:1] or "M", path=path))
    return changes


def git_file_changes(repo: str | Path = ".", *, base: str | None = None) -> list[FileChange]:
    """Return local Git changes with rename/copy detection enabled."""

    root = resolve_repo(repo)
    changes: list[FileChange] = []
    if base:
        changes.extend(
            _parse_name_status(
                run_git(root, ("diff", "--name-status", "--find-renames", base))
            )
        )
    else:
        changes.extend(
            _parse_name_status(
                run_git(root, ("diff", "--name-status", "--find-renames", "HEAD"))
            )
        )
        changes.extend(
            _parse_name_status(
                run_git(
                    root,
                    ("diff", "--cached", "--name-status", "--find-renames"),
                )
            )
        )

    status = run_git(root, ("status", "--short", "--untracked-files=all"))
    changes.extend(_status_changes(status))
    deduplicated: dict[tuple[str, str | None], FileChange] = {}
    for change in changes:
        if not change.path or is_sensitive_path(change.path):
            continue
        if change.previous_path and is_sensitive_path(change.previous_path):
            continue
        deduplicated[(change.path, change.previous_path)] = change
    return sorted(
        deduplicated.values(),
        key=lambda item: (item.path, item.previous_path or ""),
    )
