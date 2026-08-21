"""Versioned, local workflow runtime snapshots.

Snapshots capture the runtime facts needed by the future recovery engine in a
JSON-only, append-friendly directory. Creating a snapshot only writes the
new numbered snapshot and the latest.json pointer; it does not initialize
or transition the workflow and it never edits source or planning artifacts.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any

from .approval import PlanApprovalStore, plan_digest
from .memory import MEMORY_METADATA_FILE, ProjectMemory
from .repository import (
    atomic_write_text,
    create_immutable_text,
    resolve_repo,
    resolve_repo_path,
    git_repository_state,
)
from .models import WorkflowState
from .state import WorkflowSnapshot, WorkflowStateStore


SNAPSHOT_DIRECTORY = Path(".codex/workflow/snapshots")
SNAPSHOT_SCHEMA_VERSION = 1
LATEST_SNAPSHOT_FILE = "latest.json"
DEFAULT_PLAN = Path(".codex/pro-plan/PLAN.md")
_SNAPSHOT_NAME_RE = re.compile(r"^(?P<snapshot_id>[0-9]+)\.json$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SNAPSHOT_STATUSES = {"APPROVED", "INVALIDATED", "EXPIRED", "REVOKED", "UNAPPROVED"}
_SNAPSHOT_FIELDS = {
    "schema_version",
    "snapshot_id",
    "timestamp",
    "workflow",
    "plan",
    "approval",
    "repository",
    "memory",
}


def _timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat()


def _relative_path(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _memory_metadata(root: Path) -> dict[str, object]:
    """Read memory metadata without creating or migrating project memory."""

    metadata_path = root / MEMORY_METADATA_FILE
    if not metadata_path.is_file():
        return {"version": None, "schema_version": None}
    metadata = ProjectMemory(root).metadata()
    value = metadata.get("version")
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return {
        "version": value,
        "schema_version": metadata.get("schema_version"),
    }


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

    def _numbered_paths(self) -> list[tuple[int, Path]]:
        paths: list[tuple[int, Path]] = []
        if not self.directory.is_dir():
            return paths
        for path in self.directory.glob("*.json"):
            match = _SNAPSHOT_NAME_RE.fullmatch(path.name)
            if match:
                snapshot_id = int(match.group("snapshot_id"))
                if snapshot_id > 0:
                    paths.append((snapshot_id, path))
        return sorted(paths)

    @staticmethod
    def _validate_timestamp(value: object, label: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"snapshot {label} must be an ISO-8601 timestamp")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"snapshot {label} must be an ISO-8601 timestamp") from error

    def _validate_payload(self, path: Path, value: dict[str, Any]) -> dict[str, Any]:
        missing = sorted(_SNAPSHOT_FIELDS.difference(value))
        unknown = sorted(set(value).difference(_SNAPSHOT_FIELDS))
        if missing or unknown:
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unknown:
                details.append("unknown " + ", ".join(unknown))
            raise ValueError(f"workflow snapshot schema mismatch: {'; '.join(details)}: {path}")
        schema_version = value["schema_version"]
        snapshot_id = value["snapshot_id"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != SNAPSHOT_SCHEMA_VERSION
        ):
            raise ValueError(
                f"workflow snapshot schema {schema_version!r} is not supported: {path}"
            )
        if isinstance(snapshot_id, bool) or not isinstance(snapshot_id, int) or snapshot_id < 1:
            raise ValueError(f"workflow snapshot id must be positive: {path}")
        if path.name != LATEST_SNAPSHOT_FILE:
            match = _SNAPSHOT_NAME_RE.fullmatch(path.name)
            if match is None or int(match.group("snapshot_id")) != snapshot_id:
                raise ValueError(
                    f"workflow snapshot filename does not match payload id {snapshot_id}: {path}"
                )
        self._validate_timestamp(value["timestamp"], "timestamp")

        workflow = value["workflow"]
        plan = value["plan"]
        approval = value["approval"]
        repository = value["repository"]
        memory = value["memory"]
        section_specs = (
            (
                "workflow",
                workflow,
                {"state", "history_position", "goal", "started", "updated", "next_action", "paused_from"},
            ),
            ("plan", plan, {"path", "sha256"}),
            (
                "approval",
                approval,
                {"status", "plan_sha256", "approved_by", "timestamp"},
            ),
            ("repository", repository, {"commit", "dirty"}),
            ("memory", memory, {"version", "schema_version"}),
        )
        for label, section, fields in section_specs:
            if not isinstance(section, dict):
                raise ValueError(f"workflow snapshot {label} section must be an object: {path}")
            section_missing = sorted(fields.difference(section))
            allowed_fields = fields | ({"expires_at"} if label == "approval" else set())
            section_unknown = sorted(set(section).difference(allowed_fields))
            if section_missing or section_unknown:
                raise ValueError(
                    f"workflow snapshot {label} section has invalid fields: {path}"
                )

        try:
            WorkflowState(workflow["state"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"workflow snapshot state is invalid: {path}") from error
        history_position = workflow["history_position"]
        if (
            isinstance(history_position, bool)
            or not isinstance(history_position, int)
            or history_position < 0
        ):
            raise ValueError(f"workflow snapshot history position is invalid: {path}")
        if not isinstance(workflow["goal"], str):
            raise ValueError(f"workflow snapshot goal is invalid: {path}")
        for label in ("started", "updated"):
            self._validate_timestamp(workflow[label], f"workflow.{label}")
        if workflow["next_action"] is not None and not isinstance(workflow["next_action"], str):
            raise ValueError(f"workflow snapshot next_action is invalid: {path}")
        if workflow["paused_from"] is not None:
            try:
                WorkflowState(workflow["paused_from"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"workflow snapshot paused_from is invalid: {path}") from error

        if plan["path"] is not None and not isinstance(plan["path"], str):
            raise ValueError(f"workflow snapshot PLAN path is invalid: {path}")
        if plan["sha256"] is not None and (
            not isinstance(plan["sha256"], str) or not _SHA256_RE.fullmatch(plan["sha256"])
        ):
            raise ValueError(f"workflow snapshot PLAN SHA-256 is malformed: {path}")
        if approval["status"] not in _SNAPSHOT_STATUSES:
            raise ValueError(f"workflow snapshot approval status is invalid: {path}")
        for key in ("plan_sha256",):
            if approval[key] is not None and (
                not isinstance(approval[key], str) or not _SHA256_RE.fullmatch(approval[key])
            ):
                raise ValueError(f"workflow snapshot approval {key} is malformed: {path}")
        if approval["approved_by"] is not None and not isinstance(approval["approved_by"], str):
            raise ValueError(f"workflow snapshot approval approver is invalid: {path}")
        for key in ("timestamp", "expires_at"):
            if approval.get(key) is not None:
                self._validate_timestamp(approval[key], f"approval.{key}")
        if repository["commit"] is not None and not isinstance(repository["commit"], str):
            raise ValueError(f"workflow snapshot repository commit is invalid: {path}")
        if repository["dirty"] is not None and not isinstance(repository["dirty"], bool):
            raise ValueError(f"workflow snapshot repository dirty flag is invalid: {path}")
        if memory["version"] is not None and not isinstance(memory["version"], (str, int, float)):
            raise ValueError(f"workflow snapshot memory version is invalid: {path}")
        if memory["schema_version"] is not None and not isinstance(memory["schema_version"], int):
            raise ValueError(f"workflow snapshot memory schema version is invalid: {path}")
        return value

    def _load_payload(self, path: Path, *, validate_latest: bool = True) -> dict[str, Any]:
        if not path.is_file():
            raise ValueError(f"workflow snapshot does not exist: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"invalid workflow snapshot JSON: {path}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"workflow snapshot must be a JSON object: {path}")
        value = self._validate_payload(path, value)
        if validate_latest and path.name == LATEST_SNAPSHOT_FILE:
            numbered = self._numbered_paths()
            if not numbered:
                raise ValueError(f"latest workflow snapshot has no numbered snapshot: {path}")
            _, newest_path = numbered[-1]
            newest = self._load_payload(newest_path, validate_latest=False)
            if value != newest:
                raise ValueError(
                    f"latest workflow snapshot does not match newest numbered snapshot: {path}"
                )
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
        approval_status = str(approval.status()["status"])

        repository_commit, repository_dirty = git_repository_state(
            self.root,
            excluded_paths=(SNAPSHOT_DIRECTORY,),
        )
        history_position = len(self.state_store.events())
        approval_timestamp = (
            approval_record.timestamp.isoformat() if approval_record.timestamp else None
        )
        approval_expires_at = (
            approval_record.expires_at.isoformat() if approval_record.expires_at else None
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
                "expires_at": approval_expires_at,
            },
            "repository": {
                "commit": repository_commit,
                "dirty": repository_dirty,
            },
            "memory": _memory_metadata(self.root),
        }

    def create(self) -> SnapshotRecord:
        """Create the next immutable snapshot and refresh latest.json."""

        with self._creation_lock():
            while True:
                snapshot_id = self._next_snapshot_id()
                payload = self._build_payload(snapshot_id)
                serialized = self._serialize(payload)
                numbered_path = self._numbered_path(snapshot_id)
                try:
                    create_immutable_text(numbered_path, serialized)
                except FileExistsError:
                    continue
                try:
                    atomic_write_text(self.directory / LATEST_SNAPSHOT_FILE, serialized)
                except Exception:
                    # The numbered record belongs to this failed create call;
                    # remove it so latest.json cannot point at a half-published
                    # snapshot and a retry can safely reuse the ID.
                    try:
                        numbered_path.unlink()
                    except OSError:
                        pass
                    raise
                return SnapshotRecord(path=numbered_path, payload=payload)

    @contextmanager
    def _creation_lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_path = self.directory / ".create.lock"
        deadline = time.monotonic() + 30
        while True:
            try:
                lock_path.mkdir()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ValueError("timed out waiting for workflow snapshot creation lock")
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                lock_path.rmdir()
            except OSError:
                pass

    def list_snapshots(self) -> list[SnapshotRecord]:
        """Return numbered snapshots in ascending creation order."""

        records: list[SnapshotRecord] = []
        if not self.directory.is_dir():
            return records
        for _, path in self._numbered_paths():
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
