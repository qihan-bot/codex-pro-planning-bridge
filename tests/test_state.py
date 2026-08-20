from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.models import WorkflowState
from codex_pro_planning_bridge.state import WorkflowStateStore


class WorkflowStateStoreTests(unittest.TestCase):
    def test_initial_state_and_history_are_human_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            store = WorkflowStateStore(root)

            snapshot = store.initialize(goal="Add a safe command", plan="PLAN.md")

            self.assertEqual(snapshot.state, WorkflowState.NEW_TASK)
            state = json.loads(store.state_path.read_text(encoding="utf-8"))
            history = json.loads(store.history_path.read_text(encoding="utf-8"))
            self.assertEqual(state["schema_version"], 1)
            self.assertEqual(state["state"], "NEW_TASK")
            self.assertEqual(state["plan"], "PLAN.md")
            self.assertEqual(history["events"][0]["to"], "NEW_TASK")

    def test_unversioned_state_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            store = WorkflowStateStore(root)
            store.state_path.parent.mkdir(parents=True)
            store.state_path.write_text(
                json.dumps(
                    {
                        "state": "CONTEXT_READY",
                        "plan": ".codex/pro-plan/PLAN.md",
                        "started": "2026-08-20T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            snapshot = store.load()

            self.assertEqual(snapshot.state, WorkflowState.CONTEXT_READY)
            migrated = json.loads(store.state_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], 1)
            self.assertEqual(migrated["state"], "CONTEXT_READY")


if __name__ == "__main__":
    unittest.main()
