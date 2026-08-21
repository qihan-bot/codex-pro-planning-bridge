"""Fail-closed recovery from validated local workflow snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from pathlib import Path
from typing import Any

from .approval import plan_digest, PlanApprovalStore
from .memory import MEMORY_METADATA_FILE, ProjectMemory
from .models import WorkflowState
from .repository import git_commit_exists, git_repository_state, resolve_repo, resolve_repo_path
from .snapshot import DEFAULT_PLAN, SnapshotManager, SnapshotRecord
from .state import IMPLEMENTATION_STATES, WorkflowSnapshot, WorkflowStateStore, WorkflowTransition


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_SNAPSHOT_STATUSES = {"APPROVED", "INVALIDATED", "EXPIRED", "REVOKED", "UNAPPROVED"}


def _parse_datetime(value: object, fallback: datetime) -> datetime:
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return fallback


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class RecoveryResult:
    """The metadata transition appended by a successful recovery."""

    snapshot_id: int
    snapshot_path: Path
    state: WorkflowState
    history_position: int
    recovery_event_index: int
    post_recovery_snapshot_id: int | None = None
    post_recovery_snapshot_path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_path": str(self.snapshot_path),
            "state": self.state.value,
            "history_position": self.history_position,
            "recovery_event_index": self.recovery_event_index,
            "post_recovery_snapshot_id": self.post_recovery_snapshot_id,
            "post_recovery_snapshot_path": (
                str(self.post_recovery_snapshot_path)
                if self.post_recovery_snapshot_path
                else None
            ),
        }


class RecoveryEngine:
    """Restore workflow metadata from an immutable snapshot only."""

    def __init__(
        self,
        repo: str | Path = ".",
        *,
        plan: str | Path = DEFAULT_PLAN,
    ) -> None:
        self.root = resolve_repo(repo)
        self.snapshots = SnapshotManager(self.root, plan=plan)
        self.store = WorkflowStateStore(self.root)

    def validate_snapshot(
        self,
        record: SnapshotRecord,
    ) -> tuple[dict[str, Any], WorkflowState, Path | None, int]:
        payload = record.payload
        required = {
            "schema_version",
            "snapshot_id",
            "timestamp",
            "workflow",
            "plan",
            "approval",
            "repository",
            "memory",
        }
        missing = sorted(required.difference(payload))
        if missing:
            raise ValueError(
                f"workflow snapshot #{record.snapshot_id} is missing fields: "
                + ", ".join(missing)
            )

        workflow = payload["workflow"]
        plan = payload["plan"]
        approval = payload["approval"]
        repository = payload["repository"]
        memory = payload["memory"]
        if not all(isinstance(value, dict) for value in (workflow, plan, approval, repository, memory)):
            raise ValueError(f"workflow snapshot #{record.snapshot_id} has invalid section shapes")

        try:
            state = WorkflowState(str(workflow["state"]))
            history_position = int(workflow["history_position"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"workflow snapshot #{record.snapshot_id} has an invalid workflow section"
            ) from error
        if history_position < 0:
            raise ValueError("workflow snapshot history position must not be negative")

        raw_plan_path = plan.get("path")
        raw_plan_hash = plan.get("sha256")
        if raw_plan_path is None:
            if raw_plan_hash is not None:
                raise ValueError("snapshot PLAN hash exists without a PLAN path")
            plan_path = None
        elif isinstance(raw_plan_path, str) and raw_plan_path.strip():
            plan_path = resolve_repo_path(self.root, raw_plan_path)
            if not _inside(self.root, plan_path):
                raise ValueError(
                    f"snapshot PLAN path escapes the repository: {raw_plan_path}"
                )
        else:
            raise ValueError("snapshot PLAN path must be a repository-relative path")

        if raw_plan_hash is not None:
            if not isinstance(raw_plan_hash, str) or not _SHA256_RE.fullmatch(raw_plan_hash):
                raise ValueError("snapshot PLAN SHA-256 is malformed")
            if plan_path is None or not plan_path.is_file():
                raise ValueError("snapshot PLAN file is missing")
            if plan_digest(plan_path).casefold() != raw_plan_hash.casefold():
                raise ValueError("snapshot PLAN contents differ from its recorded hash")

        status = str(approval.get("status", "UNAPPROVED")).upper()
        if status not in _SNAPSHOT_STATUSES:
            raise ValueError(f"unsupported snapshot approval status: {status}")
        approval_hash = approval.get("plan_sha256")
        if approval_hash is not None:
            if not isinstance(approval_hash, str) or not _SHA256_RE.fullmatch(approval_hash):
                raise ValueError("snapshot approval SHA-256 is malformed")
        if status == "APPROVED" and approval_hash != raw_plan_hash:
            raise ValueError("approved snapshot does not bind approval to the PLAN hash")

        commit = repository.get("commit")
        if commit is not None and (
            not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit)
        ):
            raise ValueError("snapshot repository commit is malformed")
        if not isinstance(repository.get("dirty"), (bool, type(None))):
            raise ValueError("snapshot repository dirty flag is malformed")
        if memory.get("version") is not None and not isinstance(
            memory.get("version"), (str, int, float)
        ):
            raise ValueError("snapshot memory version is malformed")

        events = self.store.events()
        history = self.store.history(migrate=False)
        if len(events) != len(history):
            raise ValueError(
                f"workflow history has {len(history)} entries but event ledger has {len(events)}"
            )
        if len(events) < history_position:
            raise ValueError(
                f"event ledger has {len(events)} entries; snapshot requires "
                f"{history_position}"
            )
        if len(history) < history_position:
            raise ValueError(
                f"workflow history has {len(history)} entries; snapshot requires "
                f"{history_position}"
            )
        current_commit, current_dirty = git_repository_state(
            self.root,
            excluded_paths=(self.snapshots.directory.relative_to(self.root),),
        )
        snapshot_commit = repository.get("commit")
        if snapshot_commit is not None:
            if not git_commit_exists(self.root, snapshot_commit):
                raise ValueError(f"snapshot repository commit does not exist: {snapshot_commit}")
            if current_commit != snapshot_commit:
                raise ValueError(
                    f"current repository HEAD {current_commit} differs from snapshot commit "
                    f"{snapshot_commit}"
                )
        elif current_commit is not None:
            raise ValueError("snapshot has no repository commit but the current repository has Git")
        if current_dirty != repository.get("dirty"):
            raise ValueError(
                f"current repository dirty state {current_dirty} differs from snapshot "
                f"{repository.get('dirty')}"
            )

        approval_plan = plan_path or resolve_repo_path(self.root, DEFAULT_PLAN)
        current_approval = PlanApprovalStore(self.root, plan=approval_plan).status()
        for key in ("status", "plan_sha256", "approved_by", "timestamp"):
            if current_approval.get(key) != approval.get(key):
                raise ValueError(
                    f"current approval {key} differs from snapshot: "
                    f"{current_approval.get(key)!r} != {approval.get(key)!r}"
                )
        snapshot_expires_at = approval.get("expires_at")
        if snapshot_expires_at is not None and current_approval.get("expires_at") != snapshot_expires_at:
            raise ValueError("current approval expiry differs from snapshot")
        if state in IMPLEMENTATION_STATES and not current_approval.get("effective"):
            raise ValueError(
                "snapshot restores an implementation state without effective PLAN.md approval"
            )

        memory_path = self.root / MEMORY_METADATA_FILE
        snapshot_memory = memory
        if snapshot_memory.get("version") is None:
            if memory_path.is_file():
                raise ValueError("current Project Memory exists but snapshot has no memory version")
        elif not memory_path.is_file():
            raise ValueError("snapshot Project Memory is missing from the current repository")
        else:
            current_memory = ProjectMemory(self.root).metadata()
            if current_memory.get("version") != snapshot_memory.get("version"):
                raise ValueError("current Project Memory version differs from snapshot")
            if current_memory.get("schema_version") != snapshot_memory.get("schema_version"):
                raise ValueError("current Project Memory schema differs from snapshot")
        return workflow, state, plan_path, history_position

    def recover(
        self,
        snapshot_id: int | str | None = None,
        reason: str = "workflow recovered from snapshot",
    ) -> RecoveryResult:
        """Validate and restore one snapshot, then append a compensating event."""

        if not reason.strip():
            raise ValueError("workflow recovery reason must not be empty")
        record = self.snapshots.show(snapshot_id)
        workflow_data, state, plan_path, history_position = self.validate_snapshot(record)
        current = self.store.load(migrate=False)
        now = datetime.now(timezone.utc)
        paused_from_value = workflow_data.get("paused_from")
        paused_from = (
            WorkflowState(str(paused_from_value)) if paused_from_value else None
        )
        if state == WorkflowState.PAUSED and paused_from is None:
            raise ValueError(
                "paused snapshot does not include the state needed to resume it"
            )
        if state != WorkflowState.PAUSED:
            paused_from = None
        started = _parse_datetime(workflow_data.get("started"), current.started)
        updated = WorkflowSnapshot(
            state=state,
            plan=plan_path,
            goal=str(workflow_data.get("goal", current.goal)),
            started=started,
            updated=now,
            next_action=(
                f"Review workflow recovered from snapshot #{record.snapshot_id} "
                "before continuing."
            ),
            error=None,
            paused_from=paused_from,
        )
        recovery_event_index = len(self.store.events()) + 1
        self.store.commit(
            updated,
            WorkflowTransition(
                from_state=current.state,
                to_state=state,
                at=now,
                reason=f"snapshot #{record.snapshot_id}: {reason.strip()}",
                event="WORKFLOW_RECOVERED",
                actor="user",
            )
        )
        post_recovery_snapshot = self.snapshots.create()
        return RecoveryResult(
            snapshot_id=record.snapshot_id,
            snapshot_path=record.path,
            state=state,
            history_position=post_recovery_snapshot.payload["workflow"]["history_position"],
            recovery_event_index=recovery_event_index,
            post_recovery_snapshot_id=post_recovery_snapshot.snapshot_id,
            post_recovery_snapshot_path=post_recovery_snapshot.path,
        )


__all__ = ["RecoveryEngine", "RecoveryResult"]
