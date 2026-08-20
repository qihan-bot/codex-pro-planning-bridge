"""Language, priority, excerpt, and sensitivity helpers for context scans."""

from __future__ import annotations

from pathlib import Path

from ..repository import is_sensitive_path


LANGUAGE_BY_SUFFIX = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".css": "css",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".scss": "scss",
    ".sh": "shell",
    ".sql": "sql",
    ".svg": "xml",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}

IMPORTANT_FILENAMES = {
    "README",
    "README.md",
    "LICENSE",
    "Dockerfile",
    "Makefile",
    "Cargo.toml",
    "go.mod",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "SKILL.md",
}


def language_for(path: str) -> str:
    name = Path(path).name
    if name == "Dockerfile":
        return "dockerfile"
    if name in {"Makefile", "justfile"}:
        return "makefile"
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower(), "text")


def priority(path: str) -> tuple[int, str]:
    name = Path(path).name
    if name in IMPORTANT_FILENAMES:
        return (0, path)
    if path.startswith("docs/") or "/docs/" in path:
        return (1, path)
    return (2, path)


def is_text_file(language: str) -> bool:
    return language in set(LANGUAGE_BY_SUFFIX.values()) | {"dockerfile", "makefile"}


def read_excerpt(path: Path, max_bytes: int) -> tuple[str | None, bool]:
    """Read a bounded UTF-8 excerpt while refusing likely binary content."""

    try:
        raw = path.read_bytes()
    except OSError:
        return None, False
    if b"\x00" in raw[:4096]:
        return None, False
    truncated = len(raw) > max_bytes
    raw = raw[:max_bytes]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n"), truncated


def sensitive_paths(paths: list[str]) -> list[str]:
    """Return a bounded, stable list of sensitive-looking paths."""

    return sorted(path for path in paths if is_sensitive_path(path))[:20]
