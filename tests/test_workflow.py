from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.models import WorkflowState
from codex_pro_planning_bridge.workflow import Workflow


class WorkflowTests(unittest.TestCase):
    def test_transitions_are_explicit_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workflow = Workflow(Path(temporary_directory), goal="Build a loop", plan="PLAN.md")
            plan_path = Path(temporary_directory) / "PLAN.md"
            plan_path.write_text("# Plan\n", encoding="utf-8")
            workflow.approval.approve("test-user")

            for state in (
                WorkflowState.CONTEXT_READY,
                WorkflowState.PLAN_READY,
                WorkflowState.VALIDATING,
                WorkflowState.IMPLEMENTING,
                WorkflowState.REVIEWING,
                WorkflowState.COMPLETED,
            ):
                workflow.transition(state, reason=f"advance to {state.value}")

            self.assertEqual(workflow.state, WorkflowState.COMPLETED)
            self.assertEqual(len(workflow.history), 7)
            self.assertEqual(workflow.history[-1].to_state, WorkflowState.COMPLETED)

    def test_invalid_transition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workflow = Workflow(temporary_directory)

            with self.assertRaises(ValueError):
                workflow.transition(
                    WorkflowState.IMPLEMENTING,
                    reason="skip approval boundary",
                )

    def test_failure_is_recorded_and_can_be_reset_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workflow = Workflow(temporary_directory)

            workflow.fail("local artifact failed", error="REQUEST.md could not be prepared")
            self.assertEqual(workflow.state, WorkflowState.FAILED)
            self.assertIn("REQUEST.md", workflow.snapshot.error or "")

            workflow.reset(goal="retry the task")
            self.assertEqual(workflow.state, WorkflowState.NEW_TASK)
            self.assertEqual(workflow.snapshot.goal, "retry the task")


if __name__ == "__main__":
    unittest.main()
