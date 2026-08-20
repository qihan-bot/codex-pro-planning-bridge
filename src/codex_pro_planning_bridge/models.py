"""Shared typed data models for the planning bridge.

The bridge keeps the repository as the source of truth and deliberately uses
plain dataclasses rather than a runtime validation dependency.  These models
are serializable, easy to inspect in tests, and form the stable boundary that
the v0.3 planning loop can compose.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileInfo:
    """Bounded metadata and optional excerpt for one repository file."""

    path: str
    size: int
    language: str = "text"
    excerpt: str | None = None
    excerpt_truncated: bool = False
    role: str | None = None

    @property
    def extension(self) -> str:
        """Return the normalized file extension, or an empty string."""

        return Path(self.path).suffix.lower()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectType:
    """Detected language or ecosystem manifests in a repository."""

    python: bool = False
    node: bool = False
    rust: bool = False
    go: bool = False
    other: tuple[str, ...] = ()

    @property
    def names(self) -> list[str]:
        names = [
            name
            for name, enabled in (
                ("python", self.python),
                ("node", self.node),
                ("rust", self.rust),
                ("go", self.go),
            )
            if enabled
        ]
        return names + list(self.other)


@dataclass
class GitState:
    """Local Git metadata captured alongside a project context."""

    branch: str | None = None
    status: list[str] = field(default_factory=list)
    recent_commits: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    is_repository: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FileChange:
    """One local Git change, including rename provenance when available."""

    status: str
    path: str
    previous_path: str | None = None
    similarity: int | None = None


@dataclass
class ProjectContext:
    """Machine-readable project understanding shared across workflow stages."""

    root: Path
    project_types: list[str] = field(default_factory=list)
    files: list[FileInfo] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    git_state: GitState = field(default_factory=GitState)
    excluded_sensitive: list[str] = field(default_factory=list)
    omitted_files: int = 0
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def repository_name(self) -> str:
        return self.root.name or str(self.root)

    # Compatibility accessors keep the v0.1/v0.2 public shape stable while
    # callers migrate to the explicit git_state model.
    @property
    def branch(self) -> str | None:
        return self.git_state.branch

    @property
    def status(self) -> list[str]:
        return self.git_state.status

    @property
    def recent_commits(self) -> list[str]:
        return self.git_state.recent_commits

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation without leaking objects."""

        return {
            "root": str(self.root),
            "repository": self.repository_name,
            "project_types": list(self.project_types),
            "dependencies": list(self.dependencies),
            "files": [file_info.to_dict() for file_info in self.files],
            "git_state": self.git_state.to_dict(),
            "excluded_sensitive": list(self.excluded_sensitive),
            "omitted_files": self.omitted_files,
            "generated_at": self.generated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProjectContext":
        """Rehydrate a context artifact for future loop consumers."""

        git_value = value.get("git_state") or {}
        generated_at = value.get("generated_at")
        timestamp = (
            datetime.fromisoformat(generated_at)
            if isinstance(generated_at, str)
            else datetime.now(timezone.utc)
        )
        files = [
            FileInfo(
                path=str(item.get("path", "")),
                size=int(item.get("size", 0)),
                language=str(item.get("language", "text")),
                excerpt=item.get("excerpt"),
                excerpt_truncated=bool(item.get("excerpt_truncated", False)),
                role=item.get("role"),
            )
            for item in value.get("files", [])
            if isinstance(item, dict)
        ]
        return cls(
            root=Path(str(value.get("root", "."))),
            project_types=[str(item) for item in value.get("project_types", [])],
            files=files,
            dependencies=[str(item) for item in value.get("dependencies", [])],
            git_state=GitState(
                branch=git_value.get("branch"),
                status=[str(item) for item in git_value.get("status", [])],
                recent_commits=[
                    str(item) for item in git_value.get("recent_commits", [])
                ],
                changed_files=[
                    str(item) for item in git_value.get("changed_files", [])
                ],
                is_repository=bool(git_value.get("is_repository", False)),
            ),
            excluded_sensitive=[
                str(item) for item in value.get("excluded_sensitive", [])
            ],
            omitted_files=int(value.get("omitted_files", 0)),
            generated_at=timestamp,
        )

    def to_markdown(self) -> str:
        """Render a bounded human-readable context for the Pro handoff."""

        lines = [
            "# Repository Context",
            "",
            "This context was collected locally; no repository content was uploaded.",
            "",
            "## Repository",
            "",
            f"- Name: `{self.repository_name}`",
            f"- Branch: `{self.branch or 'unavailable'}`",
            f"- Generated at: `{self.generated_at.isoformat()}`",
            "",
            "## Git Status",
            "",
        ]
        if self.status:
            lines.extend(f"- `{item}`" for item in self.status)
        else:
            lines.append("- Working tree clean or Git metadata unavailable.")

        lines.extend(["", "## Recent Commits", ""])
        if self.recent_commits:
            lines.extend(f"- {commit}" for commit in self.recent_commits)
        else:
            lines.append("- No commit history available.")

        lines.extend(
            [
                "",
                "## Project Types",
                "",
                ", ".join(f"`{item}`" for item in self.project_types)
                if self.project_types
                else "_Not detected._",
                "",
                "## File Inventory",
                "",
                "| Path | Size | Language | Excerpt |",
                "| --- | ---: | --- | --- |",
            ]
        )
        for file_info in self.files:
            excerpt_state = "yes" if file_info.excerpt is not None else "no"
            path = file_info.path.replace("|", "\\|")
            lines.append(
                f"| `{path}` | {file_info.size} | "
                f"{file_info.language} | {excerpt_state} |"
            )

        if self.omitted_files:
            lines.extend(
                [
                    "",
                    f"{self.omitted_files} additional files were omitted because the "
                    "configured file limit was reached.",
                ]
            )

        lines.extend(["", "## Redaction Notes", ""])
        if self.excluded_sensitive:
            lines.append(
                "Sensitive-looking files were excluded from content excerpts: "
                + ", ".join(f"`{path}`" for path in self.excluded_sensitive)
                + "."
            )
        else:
            lines.append("No sensitive-looking files were discovered.")

        lines.extend(["", "## Selected Excerpts", ""])
        excerpt_files = [file_info for file_info in self.files if file_info.excerpt]
        if not excerpt_files:
            lines.append("No text excerpts were selected.")
        else:
            for file_info in excerpt_files:
                excerpt = file_info.excerpt
                if excerpt is None:
                    continue
                lines.extend(
                    [
                        f"### `{file_info.path}`",
                        "",
                        f"~~~{file_info.language}",
                        excerpt.rstrip(),
                        "~~~",
                        "",
                    ]
                )
                if file_info.excerpt_truncated:
                    lines.append("_Excerpt truncated by the configured byte limit._")
                    lines.append("")

        return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class PlanTask:
    """One implementation step extracted from PLAN.md."""

    index: int
    text: str
    references: tuple[str, ...] = ()
    checked: bool = False


@dataclass
class Plan:
    """Structured plan boundary for validator, diff, and loop consumers."""

    path: Path
    sections: list[str] = field(default_factory=list)
    tasks: list[PlanTask] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Small typed summary of PLAN.md validation."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FactFinding:
    """One repository-fact check result."""

    category: str
    reference: str
    status: str
    detail: str
    possible_matches: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryEntry:
    """One persisted memory entry or ADR summary."""

    key: str
    path: Path
    content: str
    updated_at: datetime | None = None


@dataclass(frozen=True)
class DiffEntry:
    """One plan-to-repository drift classification."""

    task: str
    detail: str
    references: tuple[str, ...] = ()


@dataclass(frozen=True)
class SymbolChange:
    """One symbol-level change between two repository snapshots."""

    name: str
    kind: str
    before_paths: tuple[str, ...] = ()
    after_paths: tuple[str, ...] = ()


@dataclass
class DriftReport:
    """Structured drift report shared by CLI and future planning loops."""

    plan_path: Path
    changed_files: list[str] = field(default_factory=list)
    completed: list[DiffEntry] = field(default_factory=list)
    missing: list[DiffEntry] = field(default_factory=list)
    changed: list[DiffEntry] = field(default_factory=list)
    blocked: list[DiffEntry] = field(default_factory=list)
    unplanned_changes: list[str] = field(default_factory=list)
    symbol_changes: list[SymbolChange] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible drift summary."""

        return {
            "plan_path": str(self.plan_path),
            "changed_files": list(self.changed_files),
            "completed": [asdict(item) for item in self.completed],
            "missing": [asdict(item) for item in self.missing],
            "changed": [asdict(item) for item in self.changed],
            "blocked": [asdict(item) for item in self.blocked],
            "unplanned_changes": list(self.unplanned_changes),
            "symbol_changes": [asdict(item) for item in self.symbol_changes],
            "ok": not (
                self.missing
                or self.changed
                or self.blocked
                or self.unplanned_changes
            ),
        }


class WorkflowState(str, Enum):
    """Explicit states used by the recoverable v0.3 planning workflow."""

    NEW_TASK = "NEW_TASK"
    CONTEXT_READY = "CONTEXT_READY"
    PLAN_READY = "PLAN_READY"
    VALIDATING = "VALIDATING"
    IMPLEMENTING = "IMPLEMENTING"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
