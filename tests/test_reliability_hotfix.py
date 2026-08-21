from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codex_pro_planning_bridge.cli import main
from codex_pro_planning_bridge.loop import PlanningLoop
from codex_pro_planning_bridge.models import WorkflowState
from codex_pro_planning_bridge.recovery import RecoveryEngine
from codex_pro_planning_bridge.repository import atomic_write_text
from codex_pro_planning_bridge.snapshot import SnapshotManager
from codex_pro_planning_bridge.state import WorkflowStateStore
from codex_pro_planning_bridge.workflow import Workflow


PLAN = """# Plan

## Summary
Keep the runtime local and recoverable.

## Assumptions and Constraints
No network access.

## Architecture / Design
Keep the repository as the source of truth.

## Implementation Steps
1. Update `src/app.py`.
2. Add `tests/test_app.py`.

## Testing and Validation
Run the local test suite.

## Risks and Open Questions
Review drift before release.
"""


class ReliabilityHotfixTests(unittest.TestCase):
    def _plan(self, root: Path) -> Path:
        plan = root / ".codex" / "pro-plan" / "PLAN.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(PLAN, encoding="utf-8")
        return plan

    def _implementation_workflow(self, root: Path) -> tuple[Workflow, Path]:
        plan = self._plan(root)
        workflow = Workflow(root, goal="Exercise reliability", plan=plan)
        workflow.approval.approve("reviewer")
        for state in (
            WorkflowState.CONTEXT_READY,
            WorkflowState.PLAN_READY,
            WorkflowState.VALIDATING,
            WorkflowState.IMPLEMENTING,
        ):
            workflow.transition(state, reason=f"advance to {state.value}")
        return workflow, plan

    def test_revoke_after_implementation_is_blocked_and_paused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow, plan = self._implementation_workflow(root)
            workflow.approval.revoke("manual review required")

            result = PlanningLoop(root, plan=plan).run()

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            restored = WorkflowStateStore(root).load(migrate=False)
            self.assertEqual(restored.state, WorkflowState.PAUSED)
            self.assertEqual(restored.paused_from, WorkflowState.IMPLEMENTING)
            events = WorkflowStateStore(root).events()
            self.assertEqual(events[-1].event, "IMPLEMENTATION_BLOCKED")

    def test_plan_edit_after_implementation_records_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow, plan = self._implementation_workflow(root)
            plan.write_text(PLAN + "\nEdited after approval.\n", encoding="utf-8")

            result = PlanningLoop(root, plan=plan).run()

            self.assertTrue(result.blocked)
            events = WorkflowStateStore(root).events()
            self.assertIn("APPROVAL_INVALIDATED", [event.event for event in events])
            self.assertEqual(events[-1].event, "IMPLEMENTATION_BLOCKED")

    def test_resume_and_rollback_cannot_restore_implementation_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow, plan = self._implementation_workflow(root)
            implementation_event = next(
                record.index
                for record in WorkflowStateStore(root).event_records()
                if record.event.to_state == WorkflowState.IMPLEMENTING
            )
            workflow.pause("pause before another review")
            workflow.approval.revoke("approval withdrawn")

            with self.assertRaisesRegex(ValueError, "effective PLAN.md approval"):
                Workflow(root, plan=plan).resume()
            self.assertEqual(WorkflowStateStore(root).load(migrate=False).state, WorkflowState.PAUSED)

            with self.assertRaisesRegex(ValueError, "effective PLAN.md approval"):
                Workflow(root, plan=plan).rollback(implementation_event)
            self.assertEqual(WorkflowStateStore(root).load(migrate=False).state, WorkflowState.PAUSED)

    def test_recovery_rejects_revoked_approval_for_implementation_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow, plan = self._implementation_workflow(root)
            record = SnapshotManager(root, plan=plan).create()
            workflow.approval.revoke("approval withdrawn")
            before = WorkflowStateStore(root).load(migrate=False)

            with self.assertRaisesRegex(ValueError, "approval status"):
                RecoveryEngine(root, plan=plan).recover(record.snapshot_id)

            after = WorkflowStateStore(root).load(migrate=False)
            self.assertEqual(after.state, before.state)

    def test_cli_recover_then_resume_uses_post_recovery_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            main(["pause", "--repo", str(root)])
            main(["recover", "--repo", str(root), "--snapshot", "latest"])
            output = StringIO()
            with redirect_stdout(output):
                status = main(["resume", "--repo", str(root), "--format", "json"])

            self.assertEqual(status, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["integrity"]["passed"])
            self.assertGreaterEqual(payload["integrity"]["snapshot_id"], 2)

    def test_pause_approve_resume_refreshes_the_integrity_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._plan(root)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text(
                "def run():\n    return True\n",
                encoding="utf-8",
            )
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text(
                "def test_run():\n    assert True\n",
                encoding="utf-8",
            )
            main(["pause", "--repo", str(root)])
            self.assertEqual(main(["approve", "--repo", str(root)]), 0)
            output = StringIO()
            with redirect_stdout(output):
                status = main(["resume", "--repo", str(root), "--format", "json"])

            self.assertIn(status, (0, 1), output.getvalue())
            self.assertTrue(json.loads(output.getvalue())["integrity"]["passed"])

    def test_corrupted_middle_and_truncated_tail_event_lines_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow = Workflow(root)
            workflow.transition(WorkflowState.CONTEXT_READY, reason="context collected")
            workflow.transition(WorkflowState.PLAN_READY, reason="plan found")
            events_path = root / ".codex" / "workflow" / "events.jsonl"
            lines = events_path.read_text(encoding="utf-8").splitlines(keepends=True)
            lines[1] = "{not-json}\n"
            events_path.write_text("".join(lines), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 2"):
                WorkflowStateStore(root).events()

            events_path.write_text(lines[0].rstrip("\n"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "truncated tail"):
                WorkflowStateStore(root).events()

            events_path.write_text(
                json.dumps(
                    {
                        **json.loads(lines[0]),
                        "schema_version": 999,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsupported schema"):
                WorkflowStateStore(root).events()

    def test_snapshot_filename_and_latest_pointer_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._plan(root)
            manager = SnapshotManager(root)
            first = manager.create()
            renamed = manager.directory / "002.json"
            first.path.rename(renamed)
            with self.assertRaisesRegex(ValueError, "filename does not match"):
                manager.list_snapshots()

    def test_unknown_repository_commit_and_dirty_drift_fail_before_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = self._plan(root)
            workflow = Workflow(root, plan=plan)
            manager = SnapshotManager(root, plan=plan)
            record = manager.create()
            payload = json.loads(record.path.read_text(encoding="utf-8"))
            payload["repository"]["commit"] = "a" * 40
            atomic_write_text(record.path, json.dumps(payload, indent=2))
            atomic_write_text(manager.directory / "latest.json", json.dumps(payload, indent=2))
            with self.assertRaisesRegex(ValueError, "commit does not exist"):
                RecoveryEngine(root, plan=plan).recover(record.snapshot_id)
            self.assertEqual(WorkflowStateStore(root).load(migrate=False).state, workflow.state)

    def test_snapshot_creation_is_exclusive_under_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._plan(root)
            manager = SnapshotManager(root)
            with ThreadPoolExecutor(max_workers=4) as executor:
                records = list(executor.map(lambda _: manager.create(), range(4)))

            self.assertEqual(sorted(record.snapshot_id for record in records), [1, 2, 3, 4])
            self.assertEqual(manager.show().snapshot_id, 4)

    def test_atomic_state_commit_restores_all_files_when_event_append_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow = Workflow(root)
            store = workflow.store
            before = {
                path: path.read_bytes()
                for path in (store.state_path, store.history_path, store.events_path)
            }
            with patch.object(store, "_append_event", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    workflow.transition(WorkflowState.CONTEXT_READY, reason="context collected")

            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_snapshot_write_failure_does_not_leave_partial_numbered_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._plan(root)
            manager = SnapshotManager(root)
            with patch(
                "codex_pro_planning_bridge.snapshot.create_immutable_text",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaisesRegex(OSError, "disk full"):
                    manager.create()
            self.assertEqual(list(manager.directory.glob("[0-9]*.json")), [])

    def test_cli_events_reports_corrupt_ledger_without_reindexing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow = Workflow(root)
            workflow.transition(WorkflowState.CONTEXT_READY, reason="context collected")
            events_path = root / ".codex" / "workflow" / "events.jsonl"
            lines = events_path.read_text(encoding="utf-8").splitlines(keepends=True)
            lines.insert(1, "\n")
            events_path.write_text("".join(lines), encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                status = main(["events", "--repo", str(root)])
            self.assertEqual(status, 2)
            self.assertIn("line 2", stderr.getvalue())

    def test_recovery_rejects_clean_snapshot_after_repository_becomes_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = self._plan(root)
            workflow = Workflow(root, plan=plan)
            self._git(root, "runtime baseline")
            record = SnapshotManager(root, plan=plan).create()
            (root / "drift.txt").write_text("uncommitted drift\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "dirty state"):
                RecoveryEngine(root, plan=plan).recover(record.snapshot_id)
            self.assertEqual(WorkflowStateStore(root).load(migrate=False).state, workflow.state)

    @staticmethod
    def _git(root: Path, message: str) -> None:
        def run(*args: str) -> None:
            subprocess.run(
                ["git", *args],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

        run("init")
        run("config", "user.email", "test@example.com")
        run("config", "user.name", "Reliability Test")
        run("add", ".")
        run("commit", "-m", message)


if __name__ == "__main__":
    unittest.main()
