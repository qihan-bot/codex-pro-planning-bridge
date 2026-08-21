"""Explicit state machine for the recoverable planning workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .approval import (
    APPROVAL_STATUS_EXPIRED,
    APPROVAL_STATUS_INVALIDATED,
    PlanApprovalStore,
)
from .models import WorkflowState
from .state import (
    IMPLEMENTATION_STATES,
    WorkflowSnapshot,
    WorkflowStateStore,
    WorkflowTransition,
)


ALLOWED_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.NEW_TASK: frozenset(
        {WorkflowState.CONTEXT_READY, WorkflowState.FAILED, WorkflowState.PAUSED, WorkflowState.CANCELLED}
    ),
    WorkflowState.CONTEXT_READY: frozenset(
        {WorkflowState.PLAN_READY, WorkflowState.FAILED, WorkflowState.PAUSED, WorkflowState.CANCELLED}
    ),
    WorkflowState.PLAN_READY: frozenset(
        {WorkflowState.VALIDATING, WorkflowState.FAILED, WorkflowState.PAUSED, WorkflowState.CANCELLED}
    ),
    WorkflowState.VALIDATING: frozenset(
        {
            WorkflowState.PLAN_READY,
            WorkflowState.IMPLEMENTING,
            WorkflowState.FAILED,
            WorkflowState.PAUSED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.IMPLEMENTING: frozenset(
        {WorkflowState.REVIEWING, WorkflowState.FAILED, WorkflowState.PAUSED, WorkflowState.CANCELLED}
    ),
    WorkflowState.REVIEWING: frozenset(
        {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.PAUSED, WorkflowState.CANCELLED}
    ),
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.FAILED: frozenset({WorkflowState.CANCELLED}),
    WorkflowState.PAUSED: frozenset(
        {
            WorkflowState.NEW_TASK,
            WorkflowState.CONTEXT_READY,
            WorkflowState.PLAN_READY,
            WorkflowState.VALIDATING,
            WorkflowState.IMPLEMENTING,
            WorkflowState.REVIEWING,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.CANCELLED: frozenset(),
}


class Workflow:
    """Coordinate state transitions and persist every transition locally."""

    def __init__(
        self,
        repo: str | Path = ".",
        *,
        goal: str = "",
        plan: str | Path | None = None,
        store: WorkflowStateStore | None = None,
    ) -> None:
        self.store = store or WorkflowStateStore(repo)
        self.snapshot = self.store.initialize(goal=goal, plan=plan)
        self.approval = PlanApprovalStore(
            self.store.root,
            plan=self.snapshot.plan or plan or ".codex/pro-plan/PLAN.md",
        )

    @property
    def state(self) -> WorkflowState:
        return self.snapshot.state

    @property
    def plan(self) -> Path | None:
        return self.snapshot.plan

    @property
    def history(self) -> list[WorkflowTransition]:
        return self.store.history()

    def can_transition(self, target: WorkflowState) -> bool:
        if target == WorkflowState.IMPLEMENTING and not self.approval.is_approved():
            return False
        if self.state == WorkflowState.PAUSED:
            return target in {self.snapshot.paused_from, WorkflowState.CANCELLED}
        return target in ALLOWED_TRANSITIONS.get(self.state, frozenset())

    def _approval_failure(self) -> tuple[str, str]:
        payload = self.approval.status()
        status = str(payload.get("status") or "UNAPPROVED")
        reason = str(payload.get("binding_reason") or "approval is not effective")
        return status, reason

    def _record_approval_block(self, *, target: WorkflowState | None = None) -> None:
        """Record approval invalidation and prevent implementation continuation."""

        status, binding_reason = self._approval_failure()
        lifecycle_event = {
            APPROVAL_STATUS_INVALIDATED: "APPROVAL_INVALIDATED",
            APPROVAL_STATUS_EXPIRED: "APPROVAL_EXPIRED",
        }.get(status)
        reason = f"effective approval is {status}: {binding_reason}"
        if self.state in IMPLEMENTATION_STATES:
            blocked_from = self.state
            self.transition(
                WorkflowState.PAUSED,
                reason=reason,
                next_action="Re-approve the current PLAN.md before continuing implementation.",
                error=reason,
                event=lifecycle_event or "IMPLEMENTATION_BLOCKED",
                actor="system",
            )
            if lifecycle_event:
                self.store.record(
                    WorkflowTransition(
                        from_state=WorkflowState.PAUSED,
                        to_state=WorkflowState.PAUSED,
                        at=datetime.now(timezone.utc),
                        reason=(
                            f"implementation blocked after {lifecycle_event.lower()} "
                            f"from {blocked_from.value}"
                        ),
                        event="IMPLEMENTATION_BLOCKED",
                        actor="system",
                    )
                )
            return
        if self.state == WorkflowState.PAUSED and target in IMPLEMENTATION_STATES:
            if lifecycle_event:
                self.store.record(
                    WorkflowTransition(
                        from_state=WorkflowState.PAUSED,
                        to_state=WorkflowState.PAUSED,
                        at=datetime.now(timezone.utc),
                        reason=reason,
                        event=lifecycle_event,
                        actor="system",
                    )
                )
            self.store.record(
                WorkflowTransition(
                    from_state=WorkflowState.PAUSED,
                    to_state=WorkflowState.PAUSED,
                    at=datetime.now(timezone.utc),
                    reason=reason,
                    event="IMPLEMENTATION_BLOCKED",
                    actor="system",
                )
            )

    def ensure_effective_approval(self) -> bool:
        """Enforce approval as a continuous invariant for implementation states."""

        if self.state not in IMPLEMENTATION_STATES or self.approval.is_approved():
            return True
        self._record_approval_block()
        return False

    def transition(
        self,
        target: WorkflowState,
        *,
        reason: str,
        next_action: str | None = None,
        error: str | None = None,
        event: str = "STATE_TRANSITION",
        actor: str = "codex",
    ) -> WorkflowSnapshot:
        """Move to ``target`` only when the state machine explicitly allows it."""

        if not reason.strip():
            raise ValueError("workflow transition reason must not be empty")
        if self.state in IMPLEMENTATION_STATES and target not in {
            WorkflowState.PAUSED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        } and not self.ensure_effective_approval():
            raise ValueError(
                "implementation is blocked until PLAN.md has effective human approval"
            )
        if target == WorkflowState.IMPLEMENTING and not self.approval.is_approved():
            raise ValueError(
                "implementation requires explicit approval in .codex/pro-plan/APPROVAL.json"
            )
        if not self.can_transition(target):
            raise ValueError(f"invalid workflow transition: {self.state.value} -> {target.value}")
        now = datetime.now(timezone.utc)
        paused_from = self.state if target == WorkflowState.PAUSED else None
        updated = WorkflowSnapshot(
            state=target,
            plan=self.snapshot.plan,
            goal=self.snapshot.goal,
            started=self.snapshot.started,
            updated=now,
            next_action=next_action,
            error=error,
            paused_from=paused_from,
        )
        self.store.commit(
            updated,
            WorkflowTransition(
                from_state=self.snapshot.state,
                to_state=target,
                at=now,
                reason=reason,
                event=event,
                actor=actor,
            )
        )
        self.snapshot = updated
        return updated

    def annotate(
        self,
        *,
        next_action: str | None = None,
        error: str | None = None,
        plan: str | Path | None = None,
    ) -> WorkflowSnapshot:
        """Update resumable metadata without inventing a state transition."""

        resolved_plan = self.snapshot.plan
        if plan is not None:
            plan_path = Path(plan)
            if not plan_path.is_absolute():
                plan_path = self.store.root / plan_path
            resolved_plan = plan_path.resolve()
        updated = WorkflowSnapshot(
            state=self.snapshot.state,
            plan=resolved_plan,
            goal=self.snapshot.goal,
            started=self.snapshot.started,
            updated=datetime.now(timezone.utc),
            next_action=next_action,
            error=error,
            paused_from=self.snapshot.paused_from,
        )
        self.store.save(updated)
        self.snapshot = updated
        return updated

    def reset(
        self,
        *,
        goal: str = "",
        plan: str | Path | None = None,
        reason: str = "starting a new task",
    ) -> WorkflowSnapshot:
        """Reset to ``NEW_TASK`` while retaining transition history."""

        self.snapshot = self.store.reset(goal=goal, plan=plan, reason=reason)
        self.approval = PlanApprovalStore(
            self.store.root,
            plan=self.snapshot.plan or plan or ".codex/pro-plan/PLAN.md",
        )
        return self.snapshot

    def pause(self, reason: str = "workflow paused by user") -> WorkflowSnapshot:
        """Pause an active workflow without losing the state to resume into."""

        if self.state in {WorkflowState.PAUSED, WorkflowState.COMPLETED, WorkflowState.CANCELLED}:
            raise ValueError(f"cannot pause workflow in state {self.state.value}")
        return self.transition(
            WorkflowState.PAUSED,
            reason=reason,
            next_action="Run cpb resume to continue the paused workflow.",
            event="WORKFLOW_PAUSED",
            actor="user",
        )

    def resume(self, reason: str = "workflow resumed by user") -> WorkflowSnapshot:
        """Return a paused workflow to the exact state it left."""

        if self.state != WorkflowState.PAUSED or self.snapshot.paused_from is None:
            raise ValueError(f"workflow is not paused: {self.state.value}")
        target = self.snapshot.paused_from
        if target in IMPLEMENTATION_STATES and not self.approval.is_approved():
            self._record_approval_block(target=target)
            raise ValueError(
                "cannot resume implementation without effective PLAN.md approval"
            )
        return self.transition(
            target,
            reason=reason,
            next_action="Continue the local planning workflow.",
            event="WORKFLOW_RESUMED",
            actor="user",
        )

    def cancel(self, reason: str = "workflow cancelled by user") -> WorkflowSnapshot:
        """Cancel a workflow while retaining all local audit records."""

        if self.state in {WorkflowState.COMPLETED, WorkflowState.CANCELLED}:
            raise ValueError(f"cannot cancel workflow in state {self.state.value}")
        return self.transition(
            WorkflowState.CANCELLED,
            reason=reason,
            next_action="Start a new workflow with cpb loop --reset when ready.",
            event="WORKFLOW_CANCELLED",
            actor="user",
        )

    def rollback(self, event_index: int, reason: str = "workflow rollback requested") -> WorkflowSnapshot:
        """Restore workflow metadata to an earlier event target state.

        This is an explicit compensating action. It never edits source files,
        plan artifacts, or prior event records.
        """

        self.snapshot = self.store.rollback(
            event_index,
            reason=reason,
            snapshot=self.snapshot,
        )
        return self.snapshot

    def fail(self, reason: str, *, error: str | None = None) -> WorkflowSnapshot:
        """Record an operational failure without allowing a silent state jump."""

        if self.state == WorkflowState.FAILED:
            return self.annotate(next_action="Reset the workflow after resolving the error.", error=error or reason)
        if self.state == WorkflowState.COMPLETED:
            raise ValueError("a completed workflow cannot transition to FAILED")
        return self.transition(
            WorkflowState.FAILED,
            reason=reason,
            next_action="Reset the workflow after resolving the error.",
            error=error or reason,
            event="WORKFLOW_FAILED",
        )


WorkflowMachine = Workflow


__all__ = ["ALLOWED_TRANSITIONS", "Workflow", "WorkflowMachine"]
