from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.memory import ProjectMemory, read_memory


PLAN = """# Plan

## Summary
Implement a service change.

## Assumptions and Constraints
Keep the local-only workflow.

## Architecture / Design
The service remains the integration point.

## Implementation Steps
1. Update `src/service.py`.
2. Add coverage in `tests/test_service.py`.
3. Blocked until the external requirement is clarified.

## Testing and Validation
Run the unit tests.

## Risks and Open Questions
Confirm the rollout.
"""


class ProjectMemoryTests(unittest.TestCase):
    def test_initialize_is_idempotent_and_persists_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            memory = ProjectMemory(root)

            created = memory.initialize()
            self.assertEqual(len(created), 4)
            self.assertTrue((root / ".codex" / "project-memory" / "decisions.md").is_file())

            memory.write("architecture.md", "# Architecture\n\nUse a local CLI.")
            self.assertEqual(memory.initialize(), [])
            self.assertIn("Use a local CLI", memory.document("architecture").content)

            memory.append("constraints", "- No API calls.")
            loaded = read_memory(root)
            self.assertIn("No API calls", loaded["constraints"])

    def test_record_plan_persists_summary_and_architecture_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan_path = root / ".codex" / "pro-plan" / "PLAN.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN, encoding="utf-8")

            memory = ProjectMemory(root)
            memory.initialize()
            path = memory.record_plan()
            content = path.read_text(encoding="utf-8")

            self.assertIn("Planning record", content)
            self.assertIn("Implement a service change.", content)
            self.assertIn("The service remains the integration point.", content)


if __name__ == "__main__":
    unittest.main()
