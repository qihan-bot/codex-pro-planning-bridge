"""Versioned, local workflow runtime snapshots.

Snapshots capture the runtime facts needed by the future recovery engine in a
JSON-only, append-friendly directory. Creating a snapshot only writes the
new numbered snapshot and the latest.json pointer; it does not initialize
or transition the workflow and it never edits source or planning artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from .approval import PlanApprovalStore, plan_digest
from .memory import MEMORY_METADATA_FILE, ProjectMemory
from .repository import resolve_repo, resolve_repo_path, run_git, write_text
from .state import WorkflowSnapshot, WorkflowStateStore


SNAPSHOT_DIRECTORY = Path(".codex/workflow/snapshots")
SNAPSHOT_SCHEMA_VERSION = 1
LATEST_SNAPSHOT_FILE = "latest.json"
DEFAULT_PLAN = Path(".codex/pro-plan/PLAN.md")
_SNAPSHOT_NAME_RE = re.compile(r"^(?P<snapshot_id>[0-9]+)\.json$")


def _timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat()


def _relative_path(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _memory_version(root: Path) -> object:
    """Read memory metadata without creating or migrating project memory."""

    metadata_path = root / MEMORY_METADATA_FILE
    if not metadata_path.is_file():
        return None
    metadata = ProjectMemory(root).metadata()
    value = metadata.get("version")
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _repository_state(root: Path) -> tuple[str | None, bool | None]:
    """Return the current Git commit and dirty flag, if Git is available."""

    commit = run_git(root, ("rev-parse", "HEAD"))
    if commit is None:
        return None, None
    status = run_git(root, ("status", "--porcelain", "--untracked-files=all"))
    return commit, bool(status)


@dataclass(frozen=True)
class SnapshotRecord:
    """A validated snapshot payload and the numbered file that stores it."""

    path: Path
    payload: dict[str, Any]

    @property
    def snapshot_id(self) -> int:
        return int(self.payload["snapshot_id"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class SnapshotManager:
    """Create and inspect immutable workflow runtime snapshots."""

    def __init__(
        self,
        repo: str | Path = ".",
        *,
        plan: str | Path = DEFAULT_PLAN,
    ) -> None:
        self.root = resolve_repo(repo)
        self.directory = self.root / SNAPSHOT_DIRECTORY
        self.plan_path = resolve_repo_path(self.root, plan)
        self.state_store = WorkflowStateStore(self.root)

    def _numbered_path(self, snapshot_id: int) -> Path:
        return self.directory / f"{snapshot_id:03d}.json"

    def _next_snapshot_id(self) -> int:
        snapshot_ids: list[int] = []
        if self.directory.is_dir():
            for path in self.directory.glob("*.json"):
                match = _SNAPSHOT_NAME_RE.fullmatch(path.name)
                if match:
                    snapshot_id = int(match.group("snapshot_id"))
                    if snapshot_id > 0:
                        snapshot_ids.append(snapshot_id)
        return max(snapshot_ids, default=0) + 1

    def _serialize(self, payload: dict[str, Any]) -> str:
        """Serialize with stable key order and human-readable JSON."""

        return json.dumps(payload, indent=2, ensure_ascii=False)

    def _load_payload(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise ValueError(f"workflow snapshot does not exist: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"invalid workflow snapshot JSON: {path}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"workflow snapshot must be a JSON object: {path}")
        try:
            schema_version = int(value["schema_version"])
            snapshot_id = int(value["snapshot_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"workflow snapshot is missing its version or id: {path}") from error
        if schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                f"workflow snapshot schema {schema_version} is not supported; "
                f"expected {SNAPSHOT_SCHEMA_VERSION}: {path}"
            )
        if snapshot_id < 1:
            raise ValueError(f"workflow snapshot id must be positive: {path}")
        return value

    def _selected_runtime(self) -> tuple[WorkflowSnapshot, Path]:
        """Read current workflow metadata without initializing the workflow."""

        workflow = self.state_store.load(default_plan=self.plan_path, migrate=False)
        plan_path = workflow.plan or self.plan_path
        return workflow, plan_path

    def _build_payload(self, snapshot_id: int) -> dict[str, Any]:
        workflow, plan_path = self._selected_runtime()
        plan_path_value = _relative_path(self.root, plan_path)
        plan_sha256 = plan_digest(plan_path) if plan_path.is_file() else None

        approval = PlanApprovalStore(self.root, plan=plan_path)
        approval_record = approval.load()
        binding = approval.binding_status()
        approval_status = "APPROVED" if binding["effective"] else "UNAPPROVED"

        repository_commit, repository_dirty = _repository_state(self.root)
        history_position = len(self.state_store.events())
        approval_timestamp = (
            approval_record.timestamp.isoformat() if approval_record.timestamp else None
        )

        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "timestamp": _timestamp(),
            "workflow": {
                "state": workflow.state.value,
                "history_position": history_position,
                "goal": workflow.goal,
                "started": workflow.started.isoformat(),
                "updated": workflow.updated.isoformat(),
                "next_action": workflow.next_action,
                "paused_from": (
                    workflow.paused_from.value if workflow.paused_from else None
                ),
            },
            "plan": {
                "path": plan_path_value,
                "sha256": plan_sha256,
            },
            "approval": {
                "status": approval_status,
                "plan_sha256": approval_record.plan_sha256,
                "approved_by": approval_record.approved_by,
                "timestamp": approval_timestamp,
            },
            "repository": {
                "commit": repository_commit,
                "dirty": repository_dirty,
            },
            "memory": {
                "version": _memory_version(self.root),
            },
        }

    def create(self) -> SnapshotRecord:
        """Create the next immutable snapshot and refresh latest.json."""

        snapshot_id = self._next_snapshot_id()
        payload = self._build_payload(snapshot_id)
        serialized = self._serialize(payload)
        numbered_path = write_text(self._numbered_path(snapshot_id), serialized)
        write_text(self.directory / LATEST_SNAPSHOT_FILE, serialized)
        return SnapshotRecord(path=numbered_path, payload=payload)

    def list_snapshots(self) -> list[SnapshotRecord]:
        """Return numbered snapshots in ascending creation order."""

        records: list[SnapshotRecord] = []
        if not self.directory.is_dir():
            return records
        paths: list[tuple[int, Path]] = []
        for path in self.directory.glob("*.json"):
            match = _SNAPSHOT_NAME_RE.fullmatch(path.name)
            if match:
                snapshot_id = int(match.group("snapshot_id"))
                if snapshot_id > 0:
                    paths.append((snapshot_id, path))
        for _, path in sorted(paths):
            records.append(SnapshotRecord(path=path, payload=self._load_payload(path)))
        return records

    def show(self, snapshot_id: int | str | None = None) -> SnapshotRecord:
        """Load one numbered snapshot, or the deterministic latest pointer."""

        selected = "latest" if snapshot_id is None else str(snapshot_id).strip()
        if not selected or selected.casefold() == "latest":
            path = self.directory / LATEST_SNAPSHOT_FILE
        else:
            try:
                parsed_id = int(selected)
            except ValueError as error:
                raise ValueError(f"snapshot id must be a number or latest: {selected!r}") from error
            if parsed_id < 1:
                raise ValueError("snapshot id must be positive")
            path = self._numbered_path(parsed_id)
        return SnapshotRecord(path=path, payload=self._load_payload(path))


__all__ = [
    "DEFAULT_PLAN",
    "LATEST_SNAPSHOT_FILE",
    "SNAPSHOT_DIRECTORY",
    "SNAPSHOT_SCHEMA_VERSION",
    "SnapshotManager",
    "SnapshotRecord",
]