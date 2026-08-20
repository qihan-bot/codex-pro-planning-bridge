from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.cli import main
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
            self.assertEqual(len(first_lines), 3)
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
            self.assertEqual(len(second_lines), 4)
            self.assertEqual(second_lines[: len(first_lines)], first_lines)
            self.assertEqual(WorkflowStateStore(root).events()[-1].event, "PLAN_READY")

    def test_event_query_filters_are_read_only_and_keep_original_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workflow = Workflow(root)
            workflow.transition(WorkflowState.CONTEXT_READY, reason="context collected")
            workflow.transition(WorkflowState.PLAN_READY, reason="plan found")
            workflow.pause("waiting for review")
            events_path = root / ".codex" / "workflow" / "events.jsonl"
            before = events_path.read_bytes()

            user_events = WorkflowStateStore(root).query_events(actor="USER")
            plan_events = WorkflowStateStore(root).query_events(to_state="PLAN_READY")
            limited = WorkflowStateStore(root).query_events(limit=1)

            self.assertEqual([item.index for item in user_events], [4])
            self.assertEqual(plan_events[0].index, 3)
            self.assertEqual(len(limited), 1)
            self.assertEqual(events_path.read_bytes(), before)

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "events",
                            "--repo",
                            str(root),
                            "--event",
                            "WORKFLOW_PAUSED",
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["events"][0]["index"], 4)

    def test_event_cli_does_not_initialize_an_empty_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["events", "--repo", str(root), "--format", "json"]),
                    0,
                )

            self.assertEqual(json.loads(output.getvalue()), {"count": 0, "events": []})
            self.assertFalse((root / ".codex").exists())


if __name__ == "__main__":
    unittest.main()
