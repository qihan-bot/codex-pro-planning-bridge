"""Persistent Markdown and ADR-based project memory.

Memory stays file-backed and local.  The four v0.2 documents remain stable
entry points, while new decisions are stored as individually versionable ADR
files under ``.codex/project-memory/adr/``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .models import MemoryEntry
from .repository import resolve_repo, resolve_repo_path, write_text


MEMORY_DIRECTORY = Path(".codex/project-memory")
ADR_DIRECTORY = MEMORY_DIRECTORY / "adr"
MIGRATIONS_DIRECTORY = MEMORY_DIRECTORY / "migrations"
MEMORY_METADATA_FILE = MEMORY_DIRECTORY / "memory.json"
MEMORY_VERSION = "1"
MEMORY_SCHEMA_VERSION = 2
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

This document is the compatibility index for Architecture Decision Records.
New decisions should be created under `.codex/project-memory/adr/`.

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


MemoryDocument = MemoryEntry


def normalize_memory_key(value: str) -> str:
    """Resolve a friendly memory name to one of the four base documents."""

    candidate = Path(value.strip()).name.casefold()
    if candidate.endswith(".md"):
        candidate = candidate[:-3]
    candidate = candidate.replace("_", "-").replace(" ", "-")
    if candidate == "issues":
        candidate = "known-issues"
    if candidate not in MEMORY_FILES:
        supported = ", ".join(sorted(MEMORY_FILES))
        raise ValueError(f"unknown memory document {value!r}; choose one of: {supported}")
    return candidate


def memory_path(repo: str | Path, document: str) -> Path:
    root = resolve_repo(repo)
    key = normalize_memory_key(document)
    return root / MEMORY_DIRECTORY / MEMORY_FILES[key]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "decision"


class ProjectMemory:
    """Manage base memory documents, ADR files, and memory metadata."""

    def __init__(self, repo: str | Path = ".") -> None:
        self.root = resolve_repo(repo)
        self.directory = self.root / MEMORY_DIRECTORY
        self.adr_directory = self.root / ADR_DIRECTORY
        self.migrations_directory = self.root / MIGRATIONS_DIRECTORY
        self.metadata_path = self.root / MEMORY_METADATA_FILE

    def initialize(self, *, overwrite: bool = False) -> list[Path]:
        """Create missing base documents and initialize or migrate metadata."""

        created: list[Path] = []
        self.migrate()
        for key, filename in MEMORY_FILES.items():
            path = self.directory / filename
            if overwrite or not path.exists():
                write_text(path, MEMORY_TEMPLATES[key])
                created.append(path)
        self.adr_directory.mkdir(parents=True, exist_ok=True)
        self.migrations_directory.mkdir(parents=True, exist_ok=True)
        self._refresh_metadata()
        return created

    def migrate(self) -> list[Path]:
        """Apply file-backed memory schema migrations without changing content.

        v0.2 metadata only carried ``version``.  v0.3 adds an explicit schema
        number and a human-readable migrations directory while keeping the
        legacy version value stable for compatibility.
        """

        if not self.metadata_path.is_file():
            return []
        try:
            value = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        try:
            current = int(value.get("schema_version", 1))
        except (TypeError, ValueError):
            current = 1
        if current > MEMORY_SCHEMA_VERSION:
            raise ValueError(
                f"memory schema {current} is newer than supported schema "
                f"{MEMORY_SCHEMA_VERSION}"
            )
        created: list[Path] = []
        if current < 2:
            migration = self.migrations_directory / "0002-add-versioned-migrations.md"
            if not migration.exists():
                write_text(
                    migration,
                    "\n".join(
                        [
                            "# Memory Migration 0002",
                            "",
                            "Add an explicit memory schema version and a Git-friendly "
                            "`migrations/` directory.",
                            "",
                            "The legacy `version` field remains `1` for compatibility.",
                        ]
                    ),
                )
                created.append(migration)
        return created

    def document(self, document: str) -> MemoryDocument:
        key = normalize_memory_key(document)
        path = self.directory / MEMORY_FILES[key]
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        updated_at = None
        if path.is_file():
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        return MemoryDocument(key=key, path=path, content=content, updated_at=updated_at)

    def documents(self) -> list[MemoryDocument]:
        return [self.document(key) for key in MEMORY_FILES]

    def list_adrs(self) -> list[MemoryDocument]:
        """Return ADR files ordered by their numeric identifier."""

        if not self.adr_directory.is_dir():
            return []
        entries: list[tuple[int, MemoryDocument]] = []
        for path in self.adr_directory.glob("[0-9][0-9][0-9][0-9]-*.md"):
            match = re.match(r"^(\d{4})-(.+)\.md$", path.name)
            if not match:
                continue
            try:
                number = int(match.group(1))
                content = path.read_text(encoding="utf-8")
                updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            except (OSError, ValueError):
                continue
            entries.append(
                (
                    number,
                    MemoryDocument(
                        key=f"ADR-{number:04d}",
                        path=path,
                        content=content,
                        updated_at=updated_at,
                    ),
                )
            )
        return [entry for _, entry in sorted(entries, key=lambda item: item[0])]

    def metadata(self) -> dict[str, object]:
        """Read versioned metadata, returning a safe default if absent/invalid."""

        if not self.metadata_path.is_file():
            return {
                "version": MEMORY_VERSION,
                "schema_version": MEMORY_SCHEMA_VERSION,
                "updated": None,
                "entries": len(self.list_adrs()),
            }
        try:
            value = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {
                "version": MEMORY_VERSION,
                "schema_version": MEMORY_SCHEMA_VERSION,
                "updated": None,
                "entries": len(self.list_adrs()),
            }
        return value if isinstance(value, dict) else {}

    def _refresh_metadata(self) -> Path:
        payload = {
            "version": MEMORY_VERSION,
            "schema_version": MEMORY_SCHEMA_VERSION,
            "updated": _now().isoformat(),
            "entries": len(self.list_adrs()),
            "documents": list(MEMORY_FILES.values()),
            "adr_directory": ADR_DIRECTORY.as_posix(),
            "migrations_directory": MIGRATIONS_DIRECTORY.as_posix(),
        }
        return write_text(
            self.metadata_path,
            json.dumps(payload, indent=2, ensure_ascii=False),
        )

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
        self._refresh_metadata()
        return path

    def append(self, document: str, content: str) -> Path:
        return self.write(document, content, append=True)

    def create_adr(
        self,
        title: str,
        *,
        status: str = "Proposed",
        content: str | None = None,
        number: int | None = None,
        date: str | None = None,
    ) -> Path:
        """Create one numbered ADR without contacting a remote service."""

        if not isinstance(title, str) or not title.strip():
            raise ValueError("ADR title must not be empty")
        if "\n" in title or "\r" in title or "\n" in status or "\r" in status:
            raise ValueError("ADR title and status must be single-line values")
        self.adr_directory.mkdir(parents=True, exist_ok=True)
        next_number = max(
            (int(item.key.split("-")[-1]) for item in self.list_adrs()),
            default=0,
        ) + 1
        adr_number = number if number is not None else next_number
        if adr_number < 1:
            raise ValueError("ADR number must be positive")
        slug = _slugify(title)
        path = self.adr_directory / f"{adr_number:04d}-{slug}.md"
        if path.exists():
            raise ValueError(f"ADR already exists: {path}")
        body = content.strip() if content and content.strip() else "_Document the context here._"
        markdown = "\n".join(
            [
                f"# ADR-{adr_number:04d}: {title.strip()}",
                "",
                f"Date: {date or _now().date().isoformat()}",
                "",
                f"Status: {status.strip()}",
                "",
                "## Context",
                "",
                body,
                "",
                "## Decision",
                "",
                "_Document the decision here._",
                "",
                "## Consequences",
                "",
                "_Document the consequences here._",
                "",
                "## Alternatives",
                "",
                "_Document rejected alternatives here._",
            ]
        )
        write_text(path, markdown)
        self._refresh_metadata()
        return path

    def record_plan(self, plan: str | Path = ".codex/pro-plan/PLAN.md") -> Path:
        """Persist a concise local planning result as an accepted ADR."""

        plan_path = resolve_repo_path(self.root, plan)
        if not plan_path.is_file():
            raise ValueError(f"plan file does not exist: {plan_path}")
        markdown = plan_path.read_text(encoding="utf-8")
        summary = _section(markdown, ("summary", "overview"))
        architecture = _section(markdown, ("architecture", "design"))
        stamp = _now().date().isoformat()
        lines = [
            f"Source: `{plan_path.relative_to(self.root).as_posix()}`",
            "Review boundary: ChatGPT Pro planned; Codex executes after approval.",
            "",
            "### Summary",
            "",
            summary or "The plan did not contain a Summary or Overview section.",
            "",
            "### Architecture notes",
            "",
            architecture or "The plan did not contain an Architecture or Design section.",
        ]
        adr_path = self.create_adr(
            f"Planning record — {stamp}",
            status="Accepted",
            content="\n".join(lines),
            date=stamp,
        )
        relative = adr_path.relative_to(self.root).as_posix()
        self.append(
            "decisions",
            f"- [{adr_path.stem}]({relative}) — Planning record — {stamp}",
        )
        return adr_path

    def to_markdown(self) -> str:
        """Render available memory and ADR links as bounded context."""

        metadata = self.metadata()
        lines = [
            "# Project Memory",
            "",
            "Memory is local Markdown; no API call was made.",
            "",
            f"- Memory format version: `{metadata.get('version', MEMORY_VERSION)}`",
            f"- ADR entries: `{metadata.get('entries', len(self.list_adrs()))}`",
            "",
        ]
        for document in self.documents():
            lines.extend([f"## `{document.key}`", ""])
            lines.append(document.content.strip() or "_Not initialized._")
            lines.append("")
        lines.extend(["## ADRs", ""])
        adrs = self.list_adrs()
        if adrs:
            lines.extend(
                f"- `{adr.key}`: `{adr.path.relative_to(self.root).as_posix()}`"
                for adr in adrs
            )
        else:
            lines.append("_No ADRs recorded._")
        return "\n".join(lines).rstrip() + "\n"


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
