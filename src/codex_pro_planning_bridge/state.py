"""Versioned, file-backed persistence for the v0.3 planning workflow.

The state files are deliberately ordinary JSON so a human can inspect, review,
and commit them with the repository.  This module only records workflow
metadata; it never stores prompts, secrets, or source-code edits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .models import WorkflowState
from .repository import resolve_repo, resolve_repo_path, write_text


WORKFLOW_DIRECTORY = Path(".codex/workflow")
STATE_FILE = WORKFLOW_DIRECTORY / "state.json"
HISTORY_FILE = WORKFLOW_DIRECTORY / "history.json"
WORKFLOW_SCHEMA_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: object, fallback: datetime | None = None) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return fallback or _now()


def _state_value(value: object) -> WorkflowState:
    if isinstance(value, WorkflowState):
        return value
    normalized = str(value or WorkflowState.NEW_TASK.value).strip().upper()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    try:
        return WorkflowState(normalized)
    except ValueError as error:
        supported = ", ".join(item.value for item in WorkflowState)
        raise ValueError(f"unknown workflow state {value!r}; choose one of: {supported}") from error


@dataclass
class WorkflowSnapshot:
    """Current workflow state and the metadata needed to resume it."""

    state: WorkflowState = WorkflowState.NEW_TASK
    plan: Path | None = None
    goal: str = ""
    started: datetime = field(default_factory=_now)
    updated: datetime = field(default_factory=_now)
    next_action: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class WorkflowTransition:
    """One auditable state transition stored in ``history.json``."""

    from_state: WorkflowState | None
    to_state: WorkflowState
    at: datetime
    reason: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "from": self.from_state.value if self.from_state else None,
            "to": self.to_state.value,
            "at": self.at.isoformat(),
            "reason": self.reason,
        }


def _snapshot_from_dict(root: Path, value: dict[str, Any]) -> WorkflowSnapshot:
    plan_value = value.get("plan")
    plan = resolve_repo_path(root, str(plan_value)) if plan_value else None
    started = _parse_datetime(value.get("started"), _now())
    return WorkflowSnapshot(
        state=_state_value(value.get("state", value.get("status"))),
        plan=plan,
        goal=str(value.get("goal", "")),
        started=started,
        updated=_parse_datetime(value.get("updated"), started),
        next_action=(str(value["next_action"]) if value.get("next_action") else None),
        error=(str(value["error"]) if value.get("error") else None),
    )


class WorkflowStateStore:
    """Read, migrate, and persist workflow state for one repository."""

    def __init__(self, repo: str | Path = ".") -> None:
        self.root = resolve_repo(repo)
        self.directory = self.root / WORKFLOW_DIRECTORY
        self.state_path = self.root / STATE_FILE
        self.history_path = self.root / HISTORY_FILE

    def _relative_or_absolute(self, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def _read_json(self, path: Path, default: object) -> object:
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"invalid workflow JSON: {path}: {error}") from error

    def _state_payload(self, snapshot: WorkflowSnapshot) -> dict[str, object]:
        return {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "state": snapshot.state.value,
            "plan": self._relative_or_absolute(snapshot.plan),
            "goal": snapshot.goal,
            "started": snapshot.started.isoformat(),
            "updated": snapshot.updated.isoformat(),
            "next_action": snapshot.next_action,
            "error": snapshot.error,
        }

    def save(self, snapshot: WorkflowSnapshot) -> Path:
        """Persist a current snapshot in a stable, human-readable shape."""

        return write_text(
            self.state_path,
            json.dumps(self._state_payload(snapshot), indent=2, ensure_ascii=False),
        )

    def load(
        self,
        *,
        default_goal: str = "",
        default_plan: str | Path | None = None,
    ) -> WorkflowSnapshot:
        """Load state, migrating the original unversioned shape when needed."""

        if not self.state_path.is_file():
            return WorkflowSnapshot(
                plan=(resolve_repo_path(self.root, default_plan) if default_plan else None),
                goal=default_goal,
            )
        raw = self._read_json(self.state_path, {})
        if not isinstance(raw, dict):
            raise ValueError(f"workflow state must be a JSON object: {self.state_path}")
        schema_version = int(raw.get("schema_version", 0))
        if schema_version > WORKFLOW_SCHEMA_VERSION:
            raise ValueError(
                f"workflow state schema {schema_version} is newer than supported schema "
                f"{WORKFLOW_SCHEMA_VERSION}"
            )
        snapshot = _snapshot_from_dict(self.root, raw)
        if not snapshot.goal and default_goal:
            snapshot.goal = default_goal
        if snapshot.plan is None and default_plan:
            snapshot.plan = resolve_repo_path(self.root, default_plan)
        if schema_version < WORKFLOW_SCHEMA_VERSION:
            self.save(snapshot)
        return snapshot

    def initialize(
        self,
        *,
        goal: str = "",
        plan: str | Path | None = None,
    ) -> WorkflowSnapshot:
        """Create the initial state and history record if they do not exist."""

        snapshot = self.load(default_goal=goal, default_plan=plan)
        if self.state_path.is_file():
            return snapshot
        self.save(snapshot)
        self.record(
            WorkflowTransition(
                from_state=None,
                to_state=snapshot.state,
                at=snapshot.updated,
                reason="workflow initialized",
            )
        )
        return snapshot

    def history(self) -> list[WorkflowTransition]:
        """Return the transition history, accepting the pre-v0.3 list shape."""

        raw = self._read_json(self.history_path, {"schema_version": WORKFLOW_SCHEMA_VERSION, "events": []})
        if isinstance(raw, list):
            events = raw
            write_text(
                self.history_path,
                json.dumps(
                    {"schema_version": WORKFLOW_SCHEMA_VERSION, "events": events},
                    indent=2,
                    ensure_ascii=False,
                ),
            )
        elif isinstance(raw, dict):
            history_version = int(raw.get("schema_version", 0))
            if history_version > WORKFLOW_SCHEMA_VERSION:
                raise ValueError(
                    f"workflow history schema {history_version} is newer than supported "
                    f"schema {WORKFLOW_SCHEMA_VERSION}"
                )
            events = raw.get("events", [])
        else:
            events = []
        result: list[WorkflowTransition] = []
        for item in events:
            if not isinstance(item, dict):
                continue
            try:
                from_value = item.get("from", item.get("from_state"))
                result.append(
                    WorkflowTransition(
                        from_state=_state_value(from_value) if from_value else None,
                        to_state=_state_value(item.get("to", item.get("to_state"))),
                        at=_parse_datetime(item.get("at", item.get("timestamp"))),
                        reason=str(item.get("reason", "")),
                    )
                )
            except ValueError:
                continue
        return result

    def record(self, transition: WorkflowTransition) -> Path:
        """Append one transition without replacing previous history."""

        events = [item.to_dict() for item in self.history()]
        events.append(transition.to_dict())
        return write_text(
            self.history_path,
            json.dumps(
                {"schema_version": WORKFLOW_SCHEMA_VERSION, "events": events},
                indent=2,
                ensure_ascii=False,
            ),
        )

    def reset(
        self,
        *,
        goal: str = "",
        plan: str | Path | None = None,
        reason: str = "starting a new task",
    ) -> WorkflowSnapshot:
        """Start a new task while preserving the previous history."""

        previous = self.load()
        now = _now()
        snapshot = WorkflowSnapshot(
            state=WorkflowState.NEW_TASK,
            plan=resolve_repo_path(self.root, plan) if plan else None,
            goal=goal,
            started=now,
            updated=now,
        )
        self.save(snapshot)
        self.record(
            WorkflowTransition(
                from_state=previous.state,
                to_state=WorkflowState.NEW_TASK,
                at=now,
                reason=reason,
            )
        )
        return snapshot
