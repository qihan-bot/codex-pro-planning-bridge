from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.cli import main
from codex_pro_planning_bridge.memory import ProjectMemory
from codex_pro_planning_bridge.models import WorkflowState
from codex_pro_planning_bridge.snapshot import SnapshotManager
from codex_pro_planning_bridge.workflow import Workflow


class WorkflowSnapshotTests(unittest.TestCase):
    def _plan(self, root: Path) -> Path:
        plan = root / ".codex" / "pro-plan" / "PLAN.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("# Plan\n\nKeep recovery local.\n", encoding="utf-8")
        return plan

    def test_create_captures_runtime_context_without_mutating_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = self._plan(root)
            workflow = Workflow(root, goal="Build a reliable runtime", plan=plan)
            workflow.approval.approve("human-reviewer")
            workflow.transition(
                WorkflowState.CONTEXT_READY,
                reason="context collected",
                event="CONTEXT_COLLECTED",
            )
            ProjectMemory(root).initialize()

            state_path = root / ".codex" / "workflow" / "state.json"
            events_path = root / ".codex" / "workflow" / "events.jsonl"
            approval_path = root / ".codex" / "pro-plan" / "APPROVAL.json"
            memory_path = root / ".codex" / "project-memory" / "memory.json"
            before = {
                path: path.read_bytes()
                for path in (plan, state_path, events_path, approval_path, memory_path)
            }

            record = SnapshotManager(root).create()
            payload = json.loads(record.path.read_text(encoding="utf-8"))

            self.assertEqual(record.snapshot_id, 1)
            self.assertEqual(
                list(payload),
                [
                    "schema_version",
                    "snapshot_id",
                    "timestamp",
                    "workflow",
                    "plan",
                    "approval",
                    "repository",
                    "memory",
                ],
            )
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["workflow"]["state"], "CONTEXT_READY")
            self.assertEqual(payload["workflow"]["history_position"], 3)
            self.assertEqual(payload["plan"]["path"], ".codex/pro-plan/PLAN.md")
            self.assertEqual(
                payload["plan"]["sha256"],
                hashlib.sha256(plan.read_bytes()).hexdigest(),
            )
            self.assertEqual(payload["approval"]["status"], "APPROVED")
            self.assertEqual(payload["approval"]["plan_sha256"], payload["plan"]["sha256"])
            self.assertEqual(payload["approval"]["approved_by"], "human-reviewer")
            self.assertEqual(payload["memory"]["version"], 1)
            self.assertEqual(payload["memory"]["schema_version"], 2)
            self.assertEqual(
                (root / ".codex" / "workflow" / "snapshots" / "latest.json").read_bytes(),
                record.path.read_bytes(),
            )
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_numbered_snapshots_are_immutable_and_latest_tracks_newest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._plan(root)
            manager = SnapshotManager(root)

            first = manager.create()
            first_bytes = first.path.read_bytes()
            second = manager.create()

            self.assertEqual(first.snapshot_id, 1)
            self.assertEqual(second.snapshot_id, 2)
            self.assertEqual(first.path.read_bytes(), first_bytes)
            self.assertEqual(
                (manager.directory / "latest.json").read_bytes(),
                second.path.read_bytes(),
            )
            self.assertEqual([item.snapshot_id for item in manager.list_snapshots()], [1, 2])
            self.assertEqual(manager.show().snapshot_id, 2)
            self.assertEqual(manager.show(1).snapshot_id, 1)

    def test_cli_snapshot_commands_are_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._plan(root)

            create_output = StringIO()
            with redirect_stdout(create_output):
                self.assertEqual(
                    main(
                        [
                            "snapshot",
                            "create",
                            "--repo",
                            str(root),
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )
            created = json.loads(create_output.getvalue())
            self.assertEqual(created["snapshot_id"], 1)
            self.assertTrue(Path(created["snapshot_path"]).is_file())

            list_output = StringIO()
            with redirect_stdout(list_output):
                self.assertEqual(
                    main(
                        [
                            "snapshot",
                            "list",
                            "--repo",
                            str(root),
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )
            listed = json.loads(list_output.getvalue())
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["snapshots"][0]["snapshot_id"], 1)

            show_output = StringIO()
            with redirect_stdout(show_output):
                self.assertEqual(
                    main(
                        [
                            "snapshot",
                            "show",
                            "--repo",
                            str(root),
                            "--id",
                            "1",
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )
            shown = json.loads(show_output.getvalue())
            self.assertEqual(shown["snapshot_id"], 1)
            self.assertEqual(shown["plan"]["path"], ".codex/pro-plan/PLAN.md")

    def test_snapshot_read_commands_do_not_initialize_an_empty_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = SnapshotManager(root)
            self.assertEqual(manager.list_snapshots(), [])
            with self.assertRaisesRegex(ValueError, "does not exist"):
                manager.show()
            self.assertFalse((root / ".codex").exists())


if __name__ == "__main__":
    unittest.main()
