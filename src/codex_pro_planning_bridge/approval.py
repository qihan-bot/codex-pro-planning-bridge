"""Explicit, local approval records for a human-reviewed PLAN.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .repository import resolve_repo, resolve_repo_path, write_text


APPROVAL_FILE = Path(".codex/pro-plan/APPROVAL.json")
APPROVAL_SCHEMA_VERSION = 1


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
        return PlanApproval(
            approved=bool(raw.get("approved", False)),
            approved_by=(str(raw["approved_by"]) if raw.get("approved_by") else None),
            timestamp=_parse_datetime(raw.get("timestamp")),
            plan=(str(raw["plan"]) if raw.get("plan") else None),
            plan_sha256=(str(raw["plan_sha256"]) if raw.get("plan_sha256") else None),
            reason=(str(raw["reason"]) if raw.get("reason") else None),
            schema_version=APPROVAL_SCHEMA_VERSION,
        )

    def _relative_plan(self) -> str:
        try:
            return self.plan_path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(self.plan_path)

    def is_approved(self) -> bool:
        """Return true only for an approval matching the current PLAN.md."""

        approval = self.load()
        if not approval.approved or not approval.approved_by or approval.timestamp is None:
            return False
        if not self.plan_path.is_file():
            return False
        if approval.plan and approval.plan != self._relative_plan():
            return False
        if approval.plan_sha256 and approval.plan_sha256 != plan_digest(self.plan_path):
            return False
        return True

    def approve(self, approved_by: str = "user") -> Path:
        """Write an approval bound to the current PLAN.md contents."""

        identity = approved_by.strip()
        if not identity:
            raise ValueError("approved_by must not be empty")
        if not self.plan_path.is_file():
            raise ValueError(f"PLAN.md does not exist: {self.plan_path}")
        approval = PlanApproval(
            approved=True,
            approved_by=identity,
            timestamp=_now(),
            plan=self._relative_plan(),
            plan_sha256=plan_digest(self.plan_path),
        )
        return write_text(
            self.path,
            json.dumps(approval.to_dict(), indent=2, ensure_ascii=False),
        )

    def revoke(self, reason: str = "plan approval revoked") -> Path:
        """Record an explicit rejection without deleting the audit artifact."""

        approval = PlanApproval(
            approved=False,
            approved_by="user",
            timestamp=_now(),
            plan=self._relative_plan(),
            plan_sha256=plan_digest(self.plan_path) if self.plan_path.is_file() else None,
            reason=reason.strip() or "plan approval revoked",
        )
        return write_text(
            self.path,
            json.dumps(approval.to_dict(), indent=2, ensure_ascii=False),
        )

    def status(self) -> dict[str, Any]:
        approval = self.load()
        return {
            **approval.to_dict(),
            "effective": self.is_approved(),
            "approval_path": str(self.path),
            "plan_path": str(self.plan_path),
        }


__all__ = [
    "APPROVAL_FILE",
    "APPROVAL_SCHEMA_VERSION",
    "PlanApproval",
    "PlanApprovalStore",
    "plan_digest",
]
