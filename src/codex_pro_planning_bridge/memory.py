"""Persistent, Markdown-based project memory.

Project memory is deliberately file-backed and local.  It can be reviewed and
versioned like any other project documentation, and the bridge never sends it
to an API automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from .repository import resolve_repo, resolve_repo_path, write_text


MEMORY_DIRECTORY = Path(".codex/project-memory")
MEMORY_FILES = {
    "architecture": "architecture.md",
    "decisions": "decisions.md",
    "constraints": "constraints.md",
    "known-issues": "known-issues.md",
}

MEMORY_TEMPLATES = {
    "architecture": """# Architecture

Document the current system boundaries, important components, and data flow.

## Overview

_Add the maintained architecture overview here._
""",
    "decisions": """# Decisions

Record architecture decisions and planning outcomes in dated sections.

## Decision record template

- Date:
- Status:
- Context:
- Decision:
- Consequences:
""",
    "constraints": """# Constraints

Record technical, operational, compatibility, security, and delivery limits.

## Active constraints

_Add constraints here. Keep each constraint testable where possible._
""",
    "known-issues": """# Known Issues

Record persistent problems, workarounds, and follow-up owners.

## Open issues

_Add known issues here. Link to a local issue or plan when available._
""",
}


@dataclass(frozen=True)
class MemoryDocument:
    """One supported project-memory document."""

    key: str
    path: Path
    content: str


def normalize_memory_key(value: str) -> str:
    """Resolve a friendly memory name to one of the four supported keys."""

    candidate = Path(value.strip()).name.casefold()
    if candidate.endswith(".md"):
        candidate = candidate[:-3]
    candidate = candidate.replace("_", "-").replace(" ", "-")
    if candidate not in MEMORY_FILES:
        supported = ", ".join(sorted(MEMORY_FILES))
        raise ValueError(f"unknown memory document {value!r}; choose one of: {supported}")
    return candidate


def memory_path(repo: str | Path, document: str) -> Path:
    root = resolve_repo(repo)
    key = normalize_memory_key(document)
    return root / MEMORY_DIRECTORY / MEMORY_FILES[key]


class ProjectMemory:
    """Manage the supported Markdown documents under ``.codex/project-memory``."""

    def __init__(self, repo: str | Path = ".") -> None:
        self.root = resolve_repo(repo)
        self.directory = self.root / MEMORY_DIRECTORY

    def initialize(self, *, overwrite: bool = False) -> list[Path]:
        """Create missing memory files and return all paths touched."""

        created: list[Path] = []
        for key, filename in MEMORY_FILES.items():
            path = self.directory / filename
            if overwrite or not path.exists():
                write_text(path, MEMORY_TEMPLATES[key])
                created.append(path)
        return created

    def document(self, document: str) -> MemoryDocument:
        key = normalize_memory_key(document)
        path = self.directory / MEMORY_FILES[key]
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        return MemoryDocument(key=key, path=path, content=content)

    def documents(self) -> list[MemoryDocument]:
        return [self.document(key) for key in MEMORY_FILES]

    def read(self, document: str | None = None) -> dict[str, str] | MemoryDocument:
        if document is not None:
            return self.document(document)
        return {item.key: item.content for item in self.documents()}

    def write(self, document: str, content: str, *, append: bool = False) -> Path:
        key = normalize_memory_key(document)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("memory content must not be empty")
        path = self.directory / MEMORY_FILES[key]
        if append and path.is_file():
            previous = path.read_text(encoding="utf-8").rstrip()
            content = f"{previous}\n\n{content.strip()}\n"
        write_text(path, content)
        return path

    def append(self, document: str, content: str) -> Path:
        return self.write(document, content, append=True)

    def record_plan(self, plan: str | Path = ".codex/pro-plan/PLAN.md") -> Path:
        """Persist a concise local planning result in ``decisions.md``."""

        plan_path = resolve_repo_path(self.root, plan)
        if not plan_path.is_file():
            raise ValueError(f"plan file does not exist: {plan_path}")
        markdown = plan_path.read_text(encoding="utf-8")
        summary = _section(markdown, ("summary", "overview"))
        architecture = _section(markdown, ("architecture", "design"))
        stamp = datetime.now(timezone.utc).date().isoformat()
        lines = [
            f"## Planning record — {stamp}",
            "",
            f"- Source: `{plan_path.relative_to(self.root).as_posix()}`",
            "- Review boundary: ChatGPT Pro planned; Codex executes after approval.",
            "",
        ]
        if summary:
            lines.extend(["### Summary", "", summary, ""])
        if architecture:
            lines.extend(["### Architecture notes", "", architecture, ""])
        if not summary and not architecture:
            lines.extend(["### Note", "", "The plan did not contain a Summary or Architecture section.", ""])
        return self.append("decisions", "\n".join(lines).rstrip())

    def to_markdown(self) -> str:
        """Render available memory as a bounded context block."""

        lines = ["# Project Memory", "", "Memory is local Markdown; no API call was made.", ""]
        for document in self.documents():
            lines.extend([f"## `{document.key}`", ""])
            lines.append(document.content.strip() or "_Not initialized._")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _section(markdown: str, keywords: tuple[str, ...]) -> str:
    headings = list(re.finditer(r"^(#{1,6})\s+(.+?)\s*$", markdown, re.MULTILINE))
    for index, heading in enumerate(headings):
        title = heading.group(2).casefold()
        if not any(keyword.casefold() in title for keyword in keywords):
            continue
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        return markdown[start:end].strip()
    return ""


def initialize_memory(repo: str | Path = ".", *, overwrite: bool = False) -> list[Path]:
    return ProjectMemory(repo).initialize(overwrite=overwrite)


def read_memory(repo: str | Path = ".", document: str | None = None) -> dict[str, str] | MemoryDocument:
    return ProjectMemory(repo).read(document)


def update_memory(
    repo: str | Path,
    document: str,
    content: str,
    *,
    append: bool = False,
) -> Path:
    return ProjectMemory(repo).write(document, content, append=append)
