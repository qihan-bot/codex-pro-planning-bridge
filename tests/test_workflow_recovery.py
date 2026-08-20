from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.cli import main
from codex_pro_planning_bridge.models import WorkflowState
from codex_pro_planning_bridge.state import WorkflowStateStore
from codex_pro_planning_bridge.workflow import Workflow


class WorkflowRecoveryTests(unittest.TestCase):
    def test_pause_and_resume_restore_the_previous_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow = Workflow(root, goal="Recover the workflow")

            workflow.transition(WorkflowState.CONTEXT_READY, reason="context collected")
            paused = workflow.pause("temporary handoff pause")
            self.assertEqual(paused.state, WorkflowState.PAUSED)
            self.assertEqual(paused.paused_from, WorkflowState.CONTEXT_READY)

            resumed = Workflow(root).resume()
            self.assertEqual(resumed.state, WorkflowState.CONTEXT_READY)
            self.assertIsNone(resumed.paused_from)

    def test_cancel_is_terminal_and_status_history_are_available_from_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.assertEqual(main(["pause", "--repo", str(root)]), 0)
            self.assertEqual(main(["resume", "--repo", str(root), "--format", "json"]), 0)
            self.assertEqual(main(["cancel", "--repo", str(root)]), 0)

            status_code = main(["status", "--repo", str(root), "--format", "json"])
            history_code = main(["history", "--repo", str(root), "--format", "json"])

            self.assertEqual(status_code, 0)
            self.assertEqual(history_code, 0)
            self.assertIn('"state": "CANCELLED"', (root / ".codex" / "workflow" / "state.json").read_text(encoding="utf-8"))
            self.assertTrue((root / ".codex" / "workflow" / "events.jsonl").is_file())

    def test_rollback_restores_state_without_mutating_source_or_prior_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "service.py"
            source.write_text("def service():\n    return 'original'\n", encoding="utf-8")
            workflow = Workflow(root, goal="Recover safely")
            workflow.transition(WorkflowState.CONTEXT_READY, reason="context collected")
            workflow.transition(WorkflowState.PLAN_READY, reason="plan found")
            events_path = root / ".codex" / "workflow" / "events.jsonl"
            before = events_path.read_bytes()

            restored = workflow.rollback(2, "retry validation")

            self.assertEqual(restored.state, WorkflowState.CONTEXT_READY)
            self.assertEqual(restored.goal, "Recover safely")
            self.assertEqual(source.read_text(encoding="utf-8"), "def service():\n    return 'original'\n")
            after_lines = events_path.read_text(encoding="utf-8").splitlines()
            before_lines = before.decode("utf-8").splitlines()
            self.assertEqual(after_lines[: len(before_lines)], before_lines)
            rollback_event = WorkflowStateStore(root).events()[-1]
            self.assertEqual(rollback_event.event, "WORKFLOW_ROLLBACK")
            self.assertEqual(rollback_event.actor, "user")
            self.assertEqual(rollback_event.to_state, WorkflowState.CONTEXT_READY)
            self.assertIn("event #2", rollback_event.reason)

    def test_rollback_cli_requires_an_earlier_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaises(ValueError):
                Workflow(root).rollback(1)


if __name__ == "__main__":
    unittest.main()
