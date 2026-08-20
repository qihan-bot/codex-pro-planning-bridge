from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from codex_pro_planning_bridge.loop import run_loop
from codex_pro_planning_bridge.models import WorkflowState


PLAN = """# Plan

## Summary
Implement the approved local change.

## Assumptions and Constraints
No network access or automatic source edits.

## Architecture / Design
Keep the repository as the source of truth.

## Implementation Steps
1. Update `src/app.py`.
2. Update `tests/test_app.py`.
3. Update `README.md`.

## Testing and Validation
Run the local test suite.

## Risks and Open Questions
Review drift before the next task.
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class PlanningLoopIntegrationTests(unittest.TestCase):
    def test_full_loop_resumes_from_context_to_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "app.py").write_text("def run():\n    return False\n", encoding="utf-8")
            (root / "tests" / "test_app.py").write_text("def test_run():\n    pass\n", encoding="utf-8")
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            _git(root, "init", "-q")
            _git(root, "add", "src/app.py", "tests/test_app.py", "README.md")
            _git(
                root,
                "-c",
                "user.name=Codex Test",
                "-c",
                "user.email=codex@example.invalid",
                "commit",
                "-qm",
                "baseline",
            )

            first = run_loop(root, goal="Improve the demo")
            self.assertEqual(first.state, WorkflowState.CONTEXT_READY)
            self.assertTrue((root / ".codex" / "pro-plan" / "REQUEST.md").is_file())

            plan_path = root / ".codex" / "pro-plan" / "PLAN.md"
            plan_path.write_text(PLAN, encoding="utf-8")
            ready = run_loop(root, goal="Improve the demo")
            self.assertEqual(ready.state, WorkflowState.IMPLEMENTING)
            self.assertTrue(ready.validation and ready.validation.passed)

            (root / "src" / "app.py").write_text("def run():\n    return True\n", encoding="utf-8")
            (root / "tests" / "test_app.py").write_text("def test_run():\n    assert True\n", encoding="utf-8")
            (root / "README.md").write_text("# Demo\n\nUpdated.\n", encoding="utf-8")
            reviewed = run_loop(root, goal="Improve the demo", review=True)

            self.assertEqual(reviewed.state, WorkflowState.COMPLETED)
            self.assertTrue(reviewed.drift)
            self.assertFalse(reviewed.drift.missing)
            self.assertFalse(reviewed.drift.unplanned_changes)
            self.assertTrue((root / ".codex" / "workflow" / "history.json").is_file())
            self.assertTrue((root / ".codex" / "project-memory" / "adr").is_dir())


if __name__ == "__main__":
    unittest.main()
