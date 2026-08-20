from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.approval import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_EXPIRED,
    APPROVAL_STATUS_INVALIDATED,
    APPROVAL_STATUS_REVOKED,
    PlanApprovalStore,
)
from codex_pro_planning_bridge.cli import main
from codex_pro_planning_bridge.state import WorkflowStateStore
from codex_pro_planning_bridge.workflow import Workflow


class ApprovalLifecycleTests(unittest.TestCase):
    def _plan(self, root: Path) -> Path:
        plan = root / ".codex" / "pro-plan" / "PLAN.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# Plan\n\nKeep approval explicit.\n", encoding="utf-8")
        return plan

    def test_plan_changes_expire_and_revoke_the_effective_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = self._plan(root)
            store = PlanApprovalStore(root, plan=plan)

            store.approve("reviewer")
            self.assertEqual(store.status()["status"], APPROVAL_STATUS_APPROVED)
            self.assertTrue(store.is_approved())

            plan.write_text("# Plan\n\nChanged after approval.\n", encoding="utf-8")
            self.assertEqual(store.status()["status"], APPROVAL_STATUS_INVALIDATED)
            self.assertFalse(store.is_approved())

            store.approve("reviewer", expires_in=0)
            self.assertEqual(store.status()["status"], APPROVAL_STATUS_EXPIRED)
            self.assertFalse(store.is_approved())

            store.approve("reviewer")
            store.revoke("manual review required")
            self.assertEqual(store.status()["status"], APPROVAL_STATUS_REVOKED)
            self.assertFalse(store.is_approved())

    def test_explicit_lifecycle_changes_are_added_to_the_event_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = self._plan(root)
            workflow = Workflow(root, plan=plan)
            workflow.approval.approve("reviewer")
            self.assertEqual(WorkflowStateStore(root).events()[-1].event, "APPROVAL_APPROVED")

            workflow.approval.revoke("manual review required")
            event = WorkflowStateStore(root).events()[-1]
            self.assertEqual(event.event, "APPROVAL_REVOKED")
            self.assertEqual(event.actor, "user")

    def test_cli_can_configure_an_expiring_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._plan(root)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "approve",
                            "--repo",
                            str(root),
                            "--expires-in",
                            "0",
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], APPROVAL_STATUS_EXPIRED)
            self.assertFalse(payload["effective"])


if __name__ == "__main__":
    unittest.main()