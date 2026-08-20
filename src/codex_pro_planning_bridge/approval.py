"""Explicit, local approval records for a human-reviewed PLAN.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .repository import resolve_repo, resolve_repo_path, write_text


APPROVAL_FILE = Path(".codex/pro-plan/APPROVAL.json")
APPROVAL_SCHEMA_VERSION = 3
APPROVAL_STATUS_APPROVED = "APPROVED"
APPROVAL_STATUS_INVALIDATED = "INVALIDATED"
APPROVAL_STATUS_EXPIRED = "EXPIRED"
APPROVAL_STATUS_REVOKED = "REVOKED"
APPROVAL_STATUSES = frozenset(
    {
        APPROVAL_STATUS_APPROVED,
        APPROVAL_STATUS_INVALIDATED,
        APPROVAL_STATUS_EXPIRED,
        APPROVAL_STATUS_REVOKED,
    }
)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def plan_digest(path: Path) -> str:
    """Return a stable digest for the exact local plan contents."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class PlanApproval:
    """Approval metadata loaded from ``APPROVAL.json``."""

    approved: bool = False
    approved_by: str | None = None
    timestamp: datetime | None = None
    plan: str | None = None
    plan_sha256: str | None = None
    reason: str | None = None
    status: str | None = None
    expires_at: datetime | None = None
    schema_version: int = APPROVAL_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "approved": self.approved,
            "approved_by": self.approved_by,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "plan": self.plan,
            "plan_sha256": self.plan_sha256,
            "reason": self.reason,
            "status": self.status,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class PlanApprovalStore:
    """Read and write the explicit human approval gate for one plan."""

    def __init__(
        self,
        repo: str | Path = ".",
        *,
        plan: str | Path = ".codex/pro-plan/PLAN.md",
        approval: str | Path = APPROVAL_FILE,
    ) -> None:
        self.root = resolve_repo(repo)
        self.plan_path = resolve_repo_path(self.root, plan)
        self.path = resolve_repo_path(self.root, approval)

    def load(self) -> PlanApproval:
        if not self.path.is_file():
            return PlanApproval()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"invalid plan approval JSON: {self.path}: {error}") from error
        if not isinstance(raw, dict):
            raise ValueError(f"plan approval must be a JSON object: {self.path}")
        schema_version = int(raw.get("schema_version", 0))
        if schema_version > APPROVAL_SCHEMA_VERSION:
            raise ValueError(
                f"plan approval schema {schema_version} is newer than supported schema "
                f"{APPROVAL_SCHEMA_VERSION}"
            )
        status = str(raw["status"]).upper() if raw.get("status") else None
        if status is not None and status not in APPROVAL_STATUSES:
            raise ValueError(f"unsupported plan approval lifecycle status: {status}")
        return PlanApproval(
            approved=bool(raw.get("approved", False)),
            approved_by=(str(raw["approved_by"]) if raw.get("approved_by") else None),
            timestamp=_parse_datetime(raw.get("timestamp")),
            plan=(str(raw["plan"]) if raw.get("plan") else None),
            plan_sha256=(str(raw["plan_sha256"]) if raw.get("plan_sha256") else None),
            reason=(str(raw["reason"]) if raw.get("reason") else None),
            status=status,
            expires_at=_parse_datetime(raw.get("expires_at")),
            schema_version=schema_version,
        )

    def _relative_plan(self) -> str:
        try:
            return self.plan_path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(self.plan_path)

    def _binding_reason(self, approval: PlanApproval) -> str | None:
        """Return the first binding problem, or ``None`` when binding is valid."""

        if approval.schema_version < 1:
            return "approval schema version is missing"
        if not approval.approved:
            return "approval artifact is not approved"
        if not approval.approved_by or not approval.approved_by.strip():
            return "approved_by is missing"
        if approval.timestamp is None:
            return "approval timestamp is missing or invalid"
        if not approval.plan:
            return "approved plan path is missing"
        if approval.plan != self._relative_plan():
            return "approved plan path does not match current plan"
        if not approval.plan_sha256:
            return "approved plan hash is missing"
        if not _SHA256_RE.fullmatch(approval.plan_sha256):
            return "approved plan hash is malformed"
        if not self.plan_path.is_file():
            return "PLAN.md does not exist"
        current_digest = plan_digest(self.plan_path)
        if approval.plan_sha256.casefold() != current_digest.casefold():
            return "PLAN.md contents differ from approved hash"
        return None

    def lifecycle_status(self, approval: PlanApproval | None = None) -> str:
        """Return the effective lifecycle status without rewriting the artifact."""

        current = approval or self.load()
        if current.status == APPROVAL_STATUS_REVOKED:
            return APPROVAL_STATUS_REVOKED
        if current.status == APPROVAL_STATUS_EXPIRED:
            return APPROVAL_STATUS_EXPIRED
        if current.status == APPROVAL_STATUS_INVALIDATED:
            return APPROVAL_STATUS_INVALIDATED
        if not current.approved:
            if current.reason or current.approved_by or current.timestamp:
                return APPROVAL_STATUS_REVOKED
            return "UNAPPROVED"
        if current.expires_at and _now() >= current.expires_at:
            return APPROVAL_STATUS_EXPIRED
        if self._binding_reason(current) is not None:
            return APPROVAL_STATUS_INVALIDATED
        return APPROVAL_STATUS_APPROVED

    def binding_status(self) -> dict[str, object]:
        """Explain whether approval is currently effective and why."""

        approval = self.load()
        lifecycle = self.lifecycle_status(approval)
        if lifecycle == APPROVAL_STATUS_APPROVED:
            return {
                "effective": True,
                "reason": "approval matches the current PLAN.md path and SHA-256 hash",
            }
        if lifecycle == APPROVAL_STATUS_EXPIRED:
            return {"effective": False, "reason": "approval has expired"}
        if lifecycle == APPROVAL_STATUS_REVOKED:
            return {
                "effective": False,
                "reason": approval.reason or "approval was revoked",
            }
        reason = self._binding_reason(approval)
        if reason:
            return {"effective": False, "reason": reason}
        return {"effective": False, "reason": "approval is not effective"}

    def is_approved(self) -> bool:
        """Return true only for an approval matching the current PLAN.md."""

        return bool(self.binding_status()["effective"])

    def _record_lifecycle_event(self, event: str, reason: str) -> None:
        """Append explicit lifecycle changes when a workflow already exists."""

        from .state import WorkflowStateStore, WorkflowTransition

        store = WorkflowStateStore(self.root)
        if not store.state_path.is_file():
            return
        current = store.load(migrate=False)
        now = _now()
        store.record(
            WorkflowTransition(
                from_state=current.state,
                to_state=current.state,
                at=now,
                reason=reason,
                event=event,
                actor="user",
            )
        )

    def approve(self, approved_by: str = "user", *, expires_in: int | None = None) -> Path:
        """Write an approval bound to the current PLAN.md contents."""

        identity = approved_by.strip()
        if not identity:
            raise ValueError("approved_by must not be empty")
        if not self.plan_path.is_file():
            raise ValueError(f"PLAN.md does not exist: {self.plan_path}")
        if expires_in is not None and expires_in < 0:
            raise ValueError("approval validity seconds must not be negative")
        now = _now()
        approval = PlanApproval(
            approved=True,
            approved_by=identity,
            timestamp=now,
            plan=self._relative_plan(),
            plan_sha256=plan_digest(self.plan_path),
            status=APPROVAL_STATUS_APPROVED,
            expires_at=(
                now + timedelta(seconds=expires_in)
                if expires_in is not None
                else None
            ),
        )
        path = write_text(
            self.path,
            json.dumps(approval.to_dict(), indent=2, ensure_ascii=False),
        )
        self._record_lifecycle_event(
            "APPROVAL_APPROVED",
            f"plan approval recorded for {approval.plan}",
        )
        return path

    def revoke(self, reason: str = "plan approval revoked") -> Path:
        """Record an explicit rejection without deleting the audit artifact."""

        normalized_reason = reason.strip() or "plan approval revoked"
        approval = PlanApproval(
            approved=False,
            approved_by="user",
            timestamp=_now(),
            plan=self._relative_plan(),
            plan_sha256=plan_digest(self.plan_path) if self.plan_path.is_file() else None,
            reason=normalized_reason,
            status=APPROVAL_STATUS_REVOKED,
        )
        path = write_text(
            self.path,
            json.dumps(approval.to_dict(), indent=2, ensure_ascii=False),
        )
        self._record_lifecycle_event("APPROVAL_REVOKED", normalized_reason)
        return path

    def status(self) -> dict[str, Any]:
        approval = self.load()
        binding = self.binding_status()
        lifecycle = self.lifecycle_status(approval)
        return {
            **approval.to_dict(),
            "status": lifecycle,
            "effective": binding["effective"],
            "binding_reason": binding["reason"],
            "approval_path": str(self.path),
            "plan_path": str(self.plan_path),
        }


__all__ = [
    "APPROVAL_FILE",
    "APPROVAL_SCHEMA_VERSION",
    "APPROVAL_STATUS_APPROVED",
    "APPROVAL_STATUS_INVALIDATED",
    "APPROVAL_STATUS_EXPIRED",
    "APPROVAL_STATUS_REVOKED",
    "APPROVAL_STATUSES",
    "PlanApproval",
    "PlanApprovalStore",
    "plan_digest",
]
