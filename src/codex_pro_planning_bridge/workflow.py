"""Explicit state machine for the recoverable planning workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .models import WorkflowState
from .state import WorkflowSnapshot, WorkflowStateStore, WorkflowTransition


ALLOWED_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.NEW_TASK: frozenset({WorkflowState.CONTEXT_READY, WorkflowState.FAILED}),
    WorkflowState.CONTEXT_READY: frozenset({WorkflowState.PLAN_READY, WorkflowState.FAILED}),
    WorkflowState.PLAN_READY: frozenset({WorkflowState.VALIDATING, WorkflowState.FAILED}),
    WorkflowState.VALIDATING: frozenset(
        {WorkflowState.PLAN_READY, WorkflowState.IMPLEMENTING, WorkflowState.FAILED}
    ),
    WorkflowState.IMPLEMENTING: frozenset({WorkflowState.REVIEWING, WorkflowState.FAILED}),
    WorkflowState.REVIEWING: frozenset({WorkflowState.COMPLETED, WorkflowState.FAILED}),
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.FAILED: frozenset(),
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
        return target in ALLOWED_TRANSITIONS.get(self.state, frozenset())

    def transition(
        self,
        target: WorkflowState,
        *,
        reason: str,
        next_action: str | None = None,
        error: str | None = None,
    ) -> WorkflowSnapshot:
        """Move to ``target`` only when the state machine explicitly allows it."""

        if not reason.strip():
            raise ValueError("workflow transition reason must not be empty")
        if not self.can_transition(target):
            raise ValueError(f"invalid workflow transition: {self.state.value} -> {target.value}")
        now = datetime.now(timezone.utc)
        updated = WorkflowSnapshot(
            state=target,
            plan=self.snapshot.plan,
            goal=self.snapshot.goal,
            started=self.snapshot.started,
            updated=now,
            next_action=next_action,
            error=error,
        )
        self.store.save(updated)
        self.store.record(
            WorkflowTransition(
                from_state=self.snapshot.state,
                to_state=target,
                at=now,
                reason=reason,
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
        )


WorkflowMachine = Workflow


__all__ = ["ALLOWED_TRANSITIONS", "Workflow", "WorkflowMachine"]
