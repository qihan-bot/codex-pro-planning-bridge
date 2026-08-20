from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.approval import PlanApprovalStore
from codex_pro_planning_bridge.models import WorkflowState
from codex_pro_planning_bridge.workflow import Workflow


class PlanApprovalTests(unittest.TestCase):
    def test_unapproved_plan_cannot_enter_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = root / "PLAN.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            workflow = Workflow(root, plan=plan)
            workflow.transition(WorkflowState.CONTEXT_READY, reason="context collected")
            workflow.transition(WorkflowState.PLAN_READY, reason="plan found")
            workflow.transition(WorkflowState.VALIDATING, reason="validation started")

            with self.assertRaisesRegex(ValueError, "explicit approval"):
                workflow.transition(WorkflowState.IMPLEMENTING, reason="start implementation")

            self.assertEqual(workflow.state, WorkflowState.VALIDATING)

    def test_approval_is_bound_to_the_current_plan_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = root / ".codex" / "pro-plan" / "PLAN.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan\n\nUse the local workflow.\n", encoding="utf-8")
            store = PlanApprovalStore(root, plan=plan)

            self.assertFalse(store.is_approved())
            approval_path = store.approve("human-reviewer")
            self.assertTrue(store.is_approved())
            payload = json.loads(approval_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["approved_by"], "human-reviewer")
            self.assertTrue(payload["plan_sha256"])

            payload["schema_version"] = 1
            approval_path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(store.is_approved())

            plan.write_text("# Plan\n\nChanged after approval.\n", encoding="utf-8")
            self.assertFalse(store.is_approved())

    def test_revoke_preserves_a_reviewable_approval_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = root / "PLAN.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            store = PlanApprovalStore(root, plan=plan)
            store.approve("human-reviewer")

            store.revoke("needs plan changes")

            self.assertFalse(store.is_approved())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertFalse(payload["approved"])
            self.assertEqual(payload["reason"], "needs plan changes")

    def test_approval_without_a_plan_hash_is_never_effective(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = root / ".codex" / "pro-plan" / "PLAN.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan\n", encoding="utf-8")
            approval_path = root / ".codex" / "pro-plan" / "APPROVAL.json"
            approval_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "approved": True,
                        "approved_by": "human-reviewer",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "plan": ".codex/pro-plan/PLAN.md",
                    }
                ),
                encoding="utf-8",
            )

            store = PlanApprovalStore(root, plan=plan)

            self.assertFalse(store.is_approved())
            self.assertEqual(store.binding_status()["reason"], "approved plan hash is missing")

    def test_approval_rejects_malformed_hash_and_wrong_plan_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = root / "PLAN.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            approval_path = root / ".codex" / "pro-plan" / "APPROVAL.json"
            approval_path.parent.mkdir(parents=True)
            approval_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "approved": True,
                        "approved_by": "human-reviewer",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "plan": "other-plan.md",
                        "plan_sha256": "not-a-sha256",
                    }
                ),
                encoding="utf-8",
            )

            store = PlanApprovalStore(root, plan=plan)

            self.assertFalse(store.is_approved())
            self.assertEqual(
                store.binding_status()["reason"],
                "approved plan path does not match current plan",
            )

            approval_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "approved": True,
                        "approved_by": "human-reviewer",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "plan": "PLAN.md",
                        "plan_sha256": "not-a-sha256",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(store.binding_status()["reason"], "approved plan hash is malformed")


if __name__ == "__main__":
    unittest.main()
