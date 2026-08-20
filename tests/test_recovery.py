from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.cli import main
from codex_pro_planning_bridge.models import WorkflowState
from codex_pro_planning_bridge.recovery import RecoveryEngine
from codex_pro_planning_bridge.snapshot import SnapshotManager
from codex_pro_planning_bridge.state import WorkflowStateStore
from codex_pro_planning_bridge.workflow import Workflow


class WorkflowRecoveryEngineTests(unittest.TestCase):
    def _workflow(self, root: Path) -> tuple[Workflow, Path]:
        plan = root / ".codex" / "pro-plan" / "PLAN.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# Plan\n\nKeep recovery local.\n", encoding="utf-8")
        workflow = Workflow(root, goal="Recover the runtime", plan=plan)
        workflow.transition(WorkflowState.CONTEXT_READY, reason="context collected")
        workflow.transition(WorkflowState.PLAN_READY, reason="plan found")
        return workflow, plan

    def test_recovery_restores_snapshot_metadata_and_appends_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow, plan = self._workflow(root)
            source = root / "service.py"
            source.write_text("def service():\n    return 'original'\n", encoding="utf-8")
            record = SnapshotManager(root).create()
            before_events = (root / ".codex" / "workflow" / "events.jsonl").read_bytes()
            before_plan = plan.read_bytes()
            before_source = source.read_bytes()

            workflow.transition(WorkflowState.VALIDATING, reason="validation started")
            result = RecoveryEngine(root).recover(1, "retry validation")

            restored = WorkflowStateStore(root).load(migrate=False)
            self.assertEqual(result.snapshot_id, record.snapshot_id)
            self.assertEqual(result.state, WorkflowState.PLAN_READY)
            self.assertEqual(restored.state, WorkflowState.PLAN_READY)
            self.assertEqual(restored.goal, "Recover the runtime")
            self.assertEqual(restored.plan, plan.resolve())
            self.assertEqual(plan.read_bytes(), before_plan)
            self.assertEqual(source.read_bytes(), before_source)
            events = WorkflowStateStore(root).events()
            self.assertEqual(events[-1].event, "WORKFLOW_RECOVERED")
            self.assertEqual(events[-1].actor, "user")
            self.assertIn("snapshot #1", events[-1].reason)
            self.assertEqual(
                (root / ".codex" / "workflow" / "events.jsonl").read_bytes()[: len(before_events)],
                before_events,
            )

    def test_paused_snapshot_keeps_the_resume_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow, _ = self._workflow(root)
            workflow.pause("wait for review")
            SnapshotManager(root).create()
            workflow.resume("continue before recovery")

            RecoveryEngine(root).recover()
            restored = WorkflowStateStore(root).load(migrate=False)
            self.assertEqual(restored.state, WorkflowState.PAUSED)
            self.assertEqual(restored.paused_from, WorkflowState.PLAN_READY)
            resumed = Workflow(root).resume()
            self.assertEqual(resumed.state, WorkflowState.PLAN_READY)

    def test_tampered_plan_fails_closed_without_writing_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, plan = self._workflow(root)
            SnapshotManager(root).create()
            state_path = root / ".codex" / "workflow" / "state.json"
            events_path = root / ".codex" / "workflow" / "events.jsonl"
            before_state = state_path.read_bytes()
            before_events = events_path.read_bytes()
            plan.write_text("# Plan\n\nTampered.\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "PLAN contents differ"):
                RecoveryEngine(root).recover()

            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertEqual(events_path.read_bytes(), before_events)

    def test_recovery_cli_returns_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._workflow(root)
            SnapshotManager(root).create()
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "recover",
                            "--repo",
                            str(root),
                            "--snapshot",
                            "latest",
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["snapshot_id"], 1)
            self.assertEqual(payload["state"], "PLAN_READY")
            self.assertEqual(payload["recovery_event_index"], 4)

    def test_missing_snapshot_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "does not exist"):
                RecoveryEngine(Path(temporary_directory)).recover()


if __name__ == "__main__":
    unittest.main()
