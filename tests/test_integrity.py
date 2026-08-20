from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.approval import PlanApprovalStore
from codex_pro_planning_bridge.cli import main
from codex_pro_planning_bridge.integrity import IntegrityChecker
from codex_pro_planning_bridge.models import WorkflowState
from codex_pro_planning_bridge.snapshot import SnapshotManager
from codex_pro_planning_bridge.workflow import Workflow


class WorkflowIntegrityTests(unittest.TestCase):
    def _workflow(self, root: Path) -> tuple[Workflow, Path]:
        plan = root / ".codex" / "pro-plan" / "PLAN.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# Plan\n\nKeep runtime local.\n", encoding="utf-8")
        workflow = Workflow(root, goal="Check runtime integrity", plan=plan)
        workflow.transition(WorkflowState.CONTEXT_READY, reason="context collected")
        return workflow, plan

    def test_integrity_pass_is_read_only_and_checks_all_runtime_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow, plan = self._workflow(root)
            PlanApprovalStore(root, plan=plan).approve("human-reviewer")
            SnapshotManager(root).create()
            paths = [
                root / ".codex" / "workflow" / "state.json",
                root / ".codex" / "workflow" / "history.json",
                root / ".codex" / "workflow" / "events.jsonl",
                plan,
                root / ".codex" / "pro-plan" / "APPROVAL.json",
                root / ".codex" / "workflow" / "snapshots" / "001.json",
                root / ".codex" / "workflow" / "snapshots" / "latest.json",
            ]
            before = {path: path.read_bytes() for path in paths}

            report = IntegrityChecker(root, plan=plan).check()

            self.assertTrue(report.passed)
            self.assertEqual(report.snapshot_id, 1)
            self.assertTrue(all(report.checks.values()))
            self.assertEqual({path: path.read_bytes() for path in paths}, before)
            self.assertEqual(workflow.state, WorkflowState.CONTEXT_READY)

    def test_state_and_plan_drift_fail_before_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow, plan = self._workflow(root)
            SnapshotManager(root).create()
            workflow.transition(WorkflowState.PLAN_READY, reason="plan found")

            state_report = IntegrityChecker(root, plan=plan).check()

            self.assertFalse(state_report.passed)
            self.assertFalse(state_report.checks["state"])
            self.assertFalse(state_report.checks["history_position"])

            plan.write_text("# Plan\n\nChanged after snapshot.\n", encoding="utf-8")
            plan_report = IntegrityChecker(root, plan=plan).check()
            self.assertFalse(plan_report.passed)
            self.assertIn("PLAN contents differ", plan_report.failures[0])

    def test_missing_snapshot_is_a_failed_integrity_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            report = IntegrityChecker(root).check()

            self.assertFalse(report.passed)
            self.assertFalse(report.checks["snapshot"])
            self.assertIn("snapshot validation failed", report.failures[0])
            self.assertIn("Workflow Integrity: FAILED", report.render())

    def test_pause_command_creates_a_baseline_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.assertEqual(main(["pause", "--repo", str(root)]), 0)
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "resume",
                        "--repo",
                        str(root),
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(status, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["integrity"]["passed"])
            self.assertEqual(payload["state"], "CONTEXT_READY")

    def test_resume_blocks_when_integrity_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow, plan = self._workflow(root)
            workflow.pause("wait for review")
            plan.write_text("# Plan\n\nChanged after pause.\n", encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                status = main(["resume", "--repo", str(root)])

            self.assertEqual(status, 1)
            self.assertIn("Workflow Integrity: FAILED", output.getvalue())
            self.assertEqual(Workflow(root).state, WorkflowState.PAUSED)


if __name__ == "__main__":
    unittest.main()
