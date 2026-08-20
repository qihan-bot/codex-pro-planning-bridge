from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.models import WorkflowState
from codex_pro_planning_bridge.state import WorkflowStateStore
from codex_pro_planning_bridge.workflow import Workflow


class WorkflowEventLogTests(unittest.TestCase):
    def test_event_log_is_jsonl_append_only_and_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = root / "PLAN.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            workflow = Workflow(root, plan=plan)
            workflow.approval.approve("test-user")

            workflow.transition(
                WorkflowState.CONTEXT_READY,
                reason="context collected",
                event="CONTEXT_COLLECTED",
            )
            first_lines = (root / ".codex" / "workflow" / "events.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(first_lines), 2)
            first_record = json.loads(first_lines[0])
            self.assertEqual(first_record["schema_version"], 1)
            self.assertEqual(first_record["event"], "WORKFLOW_INITIALIZED")
            self.assertEqual(first_record["actor"], "codex")

            workflow.transition(
                WorkflowState.PLAN_READY,
                reason="plan found",
                event="PLAN_READY",
            )
            second_lines = (root / ".codex" / "workflow" / "events.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(second_lines), 3)
            self.assertEqual(second_lines[:2], first_lines)
            self.assertEqual(WorkflowStateStore(root).events()[-1].event, "PLAN_READY")


if __name__ == "__main__":
    unittest.main()
