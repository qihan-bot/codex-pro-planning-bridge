from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.cli import main
from codex_pro_planning_bridge.models import WorkflowState
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


if __name__ == "__main__":
    unittest.main()
