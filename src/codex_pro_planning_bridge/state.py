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
from .repository import (
    append_jsonl_event,
    atomic_write_bytes,
    atomic_write_json,
    resolve_repo,
    resolve_repo_path,
    write_text,
)


WORKFLOW_DIRECTORY = Path(".codex/workflow")
STATE_FILE = WORKFLOW_DIRECTORY / "state.json"
HISTORY_FILE = WORKFLOW_DIRECTORY / "history.json"
EVENTS_FILE = WORKFLOW_DIRECTORY / "events.jsonl"
WORKFLOW_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1
IMPLEMENTATION_STATES = frozenset(
    {WorkflowState.IMPLEMENTING, WorkflowState.REVIEWING}
)


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


def _parse_datetime_strict(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
    paused_from: WorkflowState | None = None


@dataclass(frozen=True)
class WorkflowTransition:
    """One auditable state transition stored in ``history.json``."""

    from_state: WorkflowState | None
    to_state: WorkflowState
    at: datetime
    reason: str
    event: str = "STATE_TRANSITION"
    actor: str = "codex"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "from": self.from_state.value if self.from_state else None,
            "to": self.to_state.value,
            "at": self.at.isoformat(),
            "reason": self.reason,
            "event": self.event,
            "actor": self.actor,
        }

    def to_event(self) -> "WorkflowEvent":
        return WorkflowEvent(
            timestamp=self.at,
            event=self.event,
            from_state=self.from_state,
            to_state=self.to_state,
            actor=self.actor,
            reason=self.reason,
        )


@dataclass(frozen=True)
class WorkflowEvent:
    """One append-only JSONL record for workflow auditing."""

    timestamp: datetime
    event: str
    from_state: WorkflowState | None
    to_state: WorkflowState
    actor: str = "codex"
    reason: str = ""
    schema_version: int = EVENT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp.isoformat(),
            "event": self.event,
            "from": self.from_state.value if self.from_state else None,
            "to": self.to_state.value,
            "actor": self.actor,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class WorkflowEventRecord:
    """One indexed event returned by a read-only event query."""

    index: int
    event: WorkflowEvent

    def to_dict(self) -> dict[str, object]:
        payload = self.event.to_dict()
        payload["index"] = self.index
        return payload


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
        paused_from=(
            _state_value(value["paused_from"])
            if value.get("paused_from")
            else None
        ),
    )


class WorkflowStateStore:
    """Read, migrate, and persist workflow state for one repository."""

    def __init__(self, repo: str | Path = ".") -> None:
        self.root = resolve_repo(repo)
        self.directory = self.root / WORKFLOW_DIRECTORY
        self.state_path = self.root / STATE_FILE
        self.history_path = self.root / HISTORY_FILE
        self.events_path = self.root / EVENTS_FILE

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
            "paused_from": snapshot.paused_from.value if snapshot.paused_from else None,
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
        migrate: bool = True,
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
        if migrate and schema_version < WORKFLOW_SCHEMA_VERSION:
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
        self.commit(
            snapshot,
            WorkflowTransition(
                from_state=None,
                to_state=snapshot.state,
                at=snapshot.updated,
                reason="workflow initialized",
                event="WORKFLOW_INITIALIZED",
            )
        )
        return snapshot

    def history(self, *, migrate: bool = True) -> list[WorkflowTransition]:
        """Return strict transition history, accepting the pre-v0.3 list shape."""

        raw = self._read_json(self.history_path, {"schema_version": WORKFLOW_SCHEMA_VERSION, "events": []})
        if isinstance(raw, list):
            events = raw
            if migrate:
                atomic_write_json(
                    self.history_path,
                    {"schema_version": WORKFLOW_SCHEMA_VERSION, "events": events},
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
            raise ValueError(f"workflow history must be a JSON object: {self.history_path}")
        if not isinstance(events, list):
            raise ValueError(f"workflow history events must be a list: {self.history_path}")
        result: list[WorkflowTransition] = []
        for position, item in enumerate(events, start=1):
            if not isinstance(item, dict):
                raise ValueError(
                    f"invalid workflow history entry at position {position}: expected object"
                )
            from_value = item.get("from", item.get("from_state"))
            to_value = item.get("to", item.get("to_state"))
            if "to" not in item and "to_state" not in item:
                raise ValueError(f"workflow history entry {position} is missing 'to'")
            reason = item.get("reason", "")
            if not isinstance(reason, str):
                raise ValueError(f"workflow history entry {position} has an invalid reason")
            event = item.get("event", "STATE_TRANSITION")
            actor = item.get("actor", "codex")
            if not isinstance(event, str) or not event.strip():
                raise ValueError(f"workflow history entry {position} has an invalid event")
            if not isinstance(actor, str) or not actor.strip():
                raise ValueError(f"workflow history entry {position} has an invalid actor")
            try:
                to_state = _state_value(to_value)
                from_state = _state_value(from_value) if from_value else None
            except ValueError as error:
                raise ValueError(
                    f"invalid workflow history entry at position {position}: {error}"
                ) from error
            timestamp_value = item.get("at", item.get("timestamp"))
            result.append(
                WorkflowTransition(
                    from_state=from_state,
                    to_state=to_state,
                    at=_parse_datetime_strict(timestamp_value, f"history entry {position} at"),
                    reason=reason,
                    event=event,
                    actor=actor,
                )
            )
        return result

    def _history_payload(self, transition: WorkflowTransition) -> dict[str, object]:
        events = [item.to_dict() for item in self.history()]
        events.append(transition.to_dict())
        return {"schema_version": WORKFLOW_SCHEMA_VERSION, "events": events}

    def _file_bytes(self, path: Path) -> bytes | None:
        return path.read_bytes() if path.is_file() else None

    def _restore_file(self, path: Path, content: bytes | None) -> None:
        if content is None:
            if path.exists():
                path.unlink()
            return
        atomic_write_bytes(path, content)

    def _append_history(self, transition: WorkflowTransition) -> Path:
        return atomic_write_json(self.history_path, self._history_payload(transition))

    def commit(self, snapshot: WorkflowSnapshot, transition: WorkflowTransition) -> Path:
        """Atomically persist state, readable history, and the audit event."""

        before = {
            self.state_path: self._file_bytes(self.state_path),
            self.history_path: self._file_bytes(self.history_path),
            self.events_path: self._file_bytes(self.events_path),
        }
        try:
            self.save(snapshot)
            self._append_history(transition)
            self._append_event(transition.to_event())
        except Exception:
            for path, content in before.items():
                self._restore_file(path, content)
            raise
        return self.state_path

    def record(self, transition: WorkflowTransition) -> Path:
        """Append one transition to history and the JSONL audit log atomically."""

        before = {
            self.history_path: self._file_bytes(self.history_path),
            self.events_path: self._file_bytes(self.events_path),
        }
        try:
            self._append_history(transition)
            self._append_event(transition.to_event())
        except Exception:
            for path, content in before.items():
                self._restore_file(path, content)
            raise
        return self.history_path

    def _append_event(self, event: WorkflowEvent) -> Path:
        """Append exactly one event line without rewriting prior audit records."""

        return append_jsonl_event(self.events_path, event.to_dict())

    def event_records(self) -> list[WorkflowEventRecord]:
        """Read the ledger strictly, retaining original JSONL line indexes."""

        if not self.events_path.is_file():
            return []
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeError) as error:
            raise ValueError(f"workflow event ledger cannot be read: {error}") from error
        result: list[WorkflowEventRecord] = []
        for line_number, line in enumerate(lines, start=1):
            has_newline = line.endswith(("\n", "\r"))
            raw_line = line.rstrip("\r\n")
            if not raw_line.strip():
                raise ValueError(f"workflow event ledger line {line_number} is blank or corrupt")
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError as error:
                suffix = " (truncated tail)" if line_number == len(lines) and not has_newline else ""
                raise ValueError(
                    f"workflow event ledger line {line_number} is invalid JSON{suffix}"
                ) from error
            if not has_newline:
                raise ValueError(
                    f"workflow event ledger line {line_number} has a truncated tail "
                    "(missing newline)"
                )
            if not isinstance(value, dict):
                raise ValueError(
                    f"workflow event ledger line {line_number} must be a JSON object"
                )
            schema_version = value.get("schema_version")
            if schema_version != EVENT_SCHEMA_VERSION:
                raise ValueError(
                    f"workflow event ledger line {line_number} has unsupported schema "
                    f"{schema_version!r}; expected {EVENT_SCHEMA_VERSION}"
                )
            if "to" not in value or "timestamp" not in value or "event" not in value:
                raise ValueError(
                    f"workflow event ledger line {line_number} is missing required fields"
                )
            event = value["event"]
            actor = value.get("actor", "codex")
            reason = value.get("reason", "")
            if not isinstance(event, str) or not event.strip():
                raise ValueError(f"workflow event ledger line {line_number} has an invalid event")
            if not isinstance(actor, str) or not actor.strip():
                raise ValueError(f"workflow event ledger line {line_number} has an invalid actor")
            if not isinstance(reason, str):
                raise ValueError(f"workflow event ledger line {line_number} has an invalid reason")
            try:
                from_value = value.get("from")
                from_state = _state_value(from_value) if from_value else None
                to_state = _state_value(value["to"])
            except ValueError as error:
                raise ValueError(
                    f"workflow event ledger line {line_number} has an invalid state: {error}"
                ) from error
            result.append(
                WorkflowEventRecord(
                    index=line_number,
                    event=WorkflowEvent(
                        timestamp=_parse_datetime_strict(
                            value["timestamp"],
                            f"workflow event ledger line {line_number} timestamp",
                        ),
                        event=event,
                        from_state=from_state,
                        to_state=to_state,
                        actor=actor,
                        reason=reason,
                        schema_version=schema_version,
                    ),
                )
            )
        return result

    def events(self) -> list[WorkflowEvent]:
        """Read the append-only event log and fail closed on corruption."""

        return [record.event for record in self.event_records()]

    def query_events(
        self,
        *,
        event: str | None = None,
        actor: str | None = None,
        from_state: WorkflowState | str | None = None,
        to_state: WorkflowState | str | None = None,
        since: datetime | str | None = None,
        until: datetime | str | None = None,
        limit: int | None = None,
    ) -> list[WorkflowEventRecord]:
        """Query the append-only event log without changing repository state.

        Indexes are one-based positions in the valid event stream. They are
        stable for existing records as long as the append-only log is kept
        intact, and can therefore be used by the rollback command.
        """

        if limit is not None and limit < 0:
            raise ValueError("event query limit must not be negative")
        if limit == 0:
            return []
        from_value = _state_value(from_state) if from_state is not None else None
        to_value = _state_value(to_state) if to_state is not None else None
        since_value = self._query_datetime(since, "since")
        until_value = self._query_datetime(until, "until")
        if since_value and until_value and since_value > until_value:
            raise ValueError("event query since must not be later than until")
        event_value = event.casefold() if event else None
        actor_value = actor.casefold() if actor else None
        result: list[WorkflowEventRecord] = []
        for record in self.event_records():
            index = record.index
            item = record.event
            if event_value and item.event.casefold() != event_value:
                continue
            if actor_value and item.actor.casefold() != actor_value:
                continue
            if from_value is not None and item.from_state != from_value:
                continue
            if to_value is not None and item.to_state != to_value:
                continue
            if since_value and item.timestamp < since_value:
                continue
            if until_value and item.timestamp > until_value:
                continue
            result.append(WorkflowEventRecord(index=index, event=item))
            if limit is not None and len(result) >= limit:
                break
        return result

    @staticmethod
    def _query_datetime(value: datetime | str | None, label: str) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError(f"event query {label} must be an ISO-8601 timestamp") from error
        else:
            raise ValueError(f"event query {label} must be an ISO-8601 timestamp")
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def rollback(
        self,
        event_index: int,
        *,
        reason: str,
        snapshot: WorkflowSnapshot | None = None,
    ) -> WorkflowSnapshot:
        """Restore workflow metadata to a prior event target state.

        Rollback is deliberately state-only: source files and planning
        artifacts are never changed. The compensating ``WORKFLOW_ROLLBACK``
        event is appended after the original log so the audit trail remains
        complete.
        """

        if event_index < 1:
            raise ValueError("rollback event index must be a positive integer")
        if not reason.strip():
            raise ValueError("workflow rollback reason must not be empty")
        current = snapshot or self.load()
        records = self.event_records()
        record_indexes = {record.index for record in records}
        if event_index not in record_indexes or event_index >= max(record_indexes, default=0):
            raise ValueError(
                "rollback target must be an earlier event index "
                f"(1-{max(max(record_indexes, default=0) - 1, 0)})"
            )
        target = next(record for record in records if record.index == event_index).event
        if target.to_state in IMPLEMENTATION_STATES:
            from .approval import PlanApprovalStore

            plan = current.plan or self.root / ".codex" / "pro-plan" / "PLAN.md"
            if not PlanApprovalStore(self.root, plan=plan).is_approved():
                raise ValueError(
                    "rollback target requires an effective PLAN.md approval; "
                    "implementation was not restored"
                )
        paused_from = target.from_state if target.to_state == WorkflowState.PAUSED else None
        if target.to_state == WorkflowState.PAUSED and paused_from is None:
            raise ValueError("cannot rollback to a paused event without a resumable state")
        now = _now()
        updated = WorkflowSnapshot(
            state=target.to_state,
            plan=current.plan,
            goal=current.goal,
            started=current.started,
            updated=now,
            next_action=f"Review the workflow after rolling back to event #{event_index}.",
            error=None,
            paused_from=paused_from,
        )
        self.commit(
            updated,
            WorkflowTransition(
                from_state=current.state,
                to_state=target.to_state,
                at=now,
                reason=f"rollback to event #{event_index}: {reason.strip()}",
                event="WORKFLOW_ROLLBACK",
                actor="user",
            )
        )
        return updated

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
        self.commit(
            snapshot,
            WorkflowTransition(
                from_state=previous.state,
            to_state=WorkflowState.NEW_TASK,
            at=now,
            reason=reason,
            event="WORKFLOW_RESET",
        )
        )
        return snapshot
