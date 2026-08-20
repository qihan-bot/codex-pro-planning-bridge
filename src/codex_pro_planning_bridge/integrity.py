"""Read-only consistency checks for the local workflow runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .approval import PlanApprovalStore, plan_digest
from .memory import MEMORY_METADATA_FILE, ProjectMemory
from .recovery import RecoveryEngine
from .repository import git_repository_state, resolve_repo
from .snapshot import DEFAULT_PLAN, SNAPSHOT_DIRECTORY
from .state import WorkflowStateStore


def _relative_path(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _same_version(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    return str(left) == str(right)


@dataclass(frozen=True)
class IntegrityReport:
    """A serializable result from one read-only integrity check."""

    passed: bool
    snapshot_id: int | None
    checks: dict[str, bool]
    failures: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "snapshot_id": self.snapshot_id,
            "checks": dict(self.checks),
            "failures": list(self.failures),
        }

    def render(self) -> str:
        lines = [f"Workflow Integrity: {'PASS' if self.passed else 'FAILED'}"]
        for failure in self.failures:
            lines.append(f"- {failure}")
        return "\n".join(lines)


class IntegrityChecker:
    """Compare current runtime metadata with one validated snapshot."""

    def __init__(
        self,
        repo: str | Path = ".",
        *,
        plan: str | Path = DEFAULT_PLAN,
    ) -> None:
        self.root = resolve_repo(repo)
        self.plan_path = (
            (self.root / plan).resolve()
            if not Path(plan).is_absolute()
            else Path(plan).resolve()
        )
        self.store = WorkflowStateStore(self.root)
        self.recovery = RecoveryEngine(self.root, plan=plan)

    def _report(
        self,
        snapshot_id: int | None,
        checks: dict[str, bool],
        failures: list[str],
    ) -> IntegrityReport:
        return IntegrityReport(
            passed=not failures,
            snapshot_id=snapshot_id,
            checks=checks,
            failures=failures,
        )

    def check(self, snapshot_id: int | str | None = None) -> IntegrityReport:
        """Run all checks without rewriting any workflow artifact."""

        checks: dict[str, bool] = {}
        failures: list[str] = []
        try:
            record = self.recovery.snapshots.show(snapshot_id)
            workflow_data, expected_state, expected_plan, expected_position = (
                self.recovery.validate_snapshot(record)
            )
        except (OSError, ValueError) as error:
            return self._report(
                None,
                {"snapshot": False},
                [f"snapshot validation failed: {error}"],
            )

        checks["snapshot"] = True
        state_path = self.store.state_path
        if not state_path.is_file():
            checks["state"] = False
            failures.append(f"workflow state is missing: {state_path}")
            return self._report(record.snapshot_id, checks, failures)

        try:
            current = self.store.load(
                default_plan=self.plan_path,
                migrate=False,
            )
        except (OSError, ValueError) as error:
            checks["state"] = False
            failures.append(f"workflow state cannot be read: {error}")
            return self._report(record.snapshot_id, checks, failures)

        state_ok = current.state == expected_state
        if "goal" in workflow_data:
            state_ok = state_ok and current.goal == str(workflow_data["goal"])
        if "next_action" in workflow_data:
            state_ok = state_ok and current.next_action == workflow_data["next_action"]
        if "paused_from" in workflow_data:
            paused_from = workflow_data["paused_from"]
            current_paused = current.paused_from.value if current.paused_from else None
            state_ok = state_ok and current_paused == paused_from
        checks["state"] = state_ok
        if not state_ok:
            failures.append(
                f"state mismatch: current {current.state.value}, "
                f"snapshot {expected_state.value}"
            )

        events = self.store.events()
        history = self.store.history(migrate=False)
        position_ok = len(events) == expected_position and len(history) == expected_position
        checks["history_position"] = position_ok
        if not position_ok:
            failures.append(
                f"history position mismatch: events={len(events)}, "
                f"history={len(history)}, snapshot={expected_position}"
            )

        current_plan = current.plan or self.plan_path
        current_plan_value = _relative_path(self.root, current_plan)
        snapshot_plan_value = _relative_path(self.root, expected_plan)
        plan_path_ok = current_plan_value == snapshot_plan_value
        current_hash = plan_digest(current_plan) if current_plan.is_file() else None
        snapshot_hash = record.payload["plan"].get("sha256")
        plan_hash_ok = current_hash == snapshot_hash
        checks["plan_path"] = plan_path_ok
        checks["plan_hash"] = plan_hash_ok
        if not plan_path_ok:
            failures.append(
                f"PLAN path mismatch: current {current_plan_value}, "
                f"snapshot {snapshot_plan_value}"
            )
        if not plan_hash_ok:
            failures.append("PLAN SHA-256 does not match the snapshot")

        approval = PlanApprovalStore(self.root, plan=current_plan)
        approval_payload = approval.status()
        current_approval_status = approval_payload.get("status")
        if current_approval_status is None:
            current_approval_status = (
                "APPROVED" if approval_payload.get("effective") else "UNAPPROVED"
            )
        snapshot_approval = record.payload["approval"]
        approval_status_ok = current_approval_status == snapshot_approval.get("status")
        approval_hash_ok = approval_payload.get("plan_sha256") == snapshot_approval.get(
            "plan_sha256"
        )
        checks["approval_status"] = approval_status_ok
        checks["approval_hash"] = approval_hash_ok
        if not approval_status_ok:
            failures.append(
                f"approval status mismatch: current {current_approval_status}, "
                f"snapshot {snapshot_approval.get('status')}"
            )
        if not approval_hash_ok:
            failures.append("approval PLAN hash does not match the snapshot")

        current_commit, current_dirty = git_repository_state(
            self.root,
            excluded_paths=(SNAPSHOT_DIRECTORY,),
        )
        snapshot_repository = record.payload["repository"]
        repository_ok = (
            current_commit == snapshot_repository.get("commit")
            and current_dirty == snapshot_repository.get("dirty")
        )
        checks["repository"] = repository_ok
        if not repository_ok:
            failures.append(
                "repository state mismatch: current "
                f"{current_commit}/{current_dirty}, snapshot "
                f"{snapshot_repository.get('commit')}/{snapshot_repository.get('dirty')}"
            )

        memory_metadata_path = self.root / MEMORY_METADATA_FILE
        snapshot_memory = record.payload["memory"]
        if snapshot_memory.get("version") is None:
            memory_ok = not memory_metadata_path.is_file()
        elif not memory_metadata_path.is_file():
            memory_ok = False
        else:
            metadata = ProjectMemory(self.root).metadata()
            memory_ok = _same_version(
                metadata.get("version"),
                snapshot_memory.get("version"),
            )
            if "schema_version" in snapshot_memory:
                memory_ok = memory_ok and (
                    metadata.get("schema_version") == snapshot_memory["schema_version"]
                )
        checks["memory"] = memory_ok
        if not memory_ok:
            failures.append("Project Memory version does not match the snapshot")

        return self._report(record.snapshot_id, checks, failures)


__all__ = ["IntegrityChecker", "IntegrityReport"]
