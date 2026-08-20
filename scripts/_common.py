"""Shared filesystem and Git helpers for the standalone MVP scripts."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from codex_pro_planning_bridge.context import is_sensitive_path  # noqa: E402


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".codex",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".venv",
    "venv",
    "__pycache__",
}

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


def is_ignored(relative: str | Path) -> bool:
    """Apply the MVP ignore policy before reading or listing a file."""

    path = Path(str(relative).replace("\\", "/"))
    if any(part in IGNORED_DIRS for part in path.parts):
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


def git_status(repo: Path) -> str:
    output = run_git(repo, ("status", "--short", "--untracked-files=all"))
    if output is None:
        return "Git metadata unavailable."
    if not output:
        return "Working tree clean."
    lines = []
    for line in output.splitlines():
        path_part = line[3:].strip() if len(line) >= 3 else line
        if is_ignored(path_part):
            lines.append(line[:2] + " [sensitive or ignored path omitted]")
        else:
            lines.append(line)
    return "\n".join(lines)


def git_files(repo: Path) -> list[str] | None:
    output = run_git(repo, ("ls-files", "--cached", "--others", "--exclude-standard"))
    if output is None:
        return None
    return [line.replace("\\", "/") for line in output.splitlines() if line.strip()]


def iter_project_files(repo: Path) -> list[tuple[str, Path]]:
    """Return safe project files, preferring Git's ignore rules when available."""

    candidates = git_files(repo)
    if candidates is not None:
        paths = [Path(path) for path in candidates]
    else:
        paths = []
        for current, directories, filenames in os.walk(repo, followlinks=False):
            directories[:] = sorted(
                directory
                for directory in directories
                if not is_ignored(Path(current, directory).relative_to(repo))
                and not directory.startswith(".")
            )
            paths.extend(
                Path(current, filename).relative_to(repo)
                for filename in sorted(filenames)
            )

    result: list[tuple[str, Path]] = []
    for relative_path in sorted(set(paths), key=lambda item: item.as_posix()):
        relative = relative_path.as_posix()
        if is_ignored(relative):
            continue
        full_path = repo / relative_path
        try:
            if full_path.is_file():
                result.append((relative, full_path))
        except OSError:
            continue
    return result


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
    return path
