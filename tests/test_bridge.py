from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.context import collect_repository
from codex_pro_planning_bridge.plan import validate_plan
from codex_pro_planning_bridge.prompt import build_request


class ContextCollectionTests(unittest.TestCase):
    def test_redacts_sensitive_files_and_collects_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
            (root / ".env").write_text("TOKEN=do-not-include\n", encoding="utf-8")
            (root / "private.key").write_text("secret\n", encoding="utf-8")

            context = collect_repository(root)
            paths = {file_context.path for file_context in context.files}
            rendered = context.to_markdown()

            self.assertIn("README.md", paths)
            self.assertIn("src/main.py", paths)
            self.assertNotIn(".env", paths)
            self.assertNotIn("TOKEN=do-not-include", rendered)
            self.assertIn(".env", rendered)
            self.assertIn("private.key", rendered)

    def test_respects_file_and_excerpt_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for index in range(5):
                (root / f"file-{index}.txt").write_text("x" * 100, encoding="utf-8")

            context = collect_repository(root, max_files=2, max_file_bytes=10, max_total_bytes=10)
            self.assertEqual(len(context.files), 2)
            self.assertEqual(context.omitted_files, 3)


class RequestAndPlanTests(unittest.TestCase):
    def test_request_contains_goal_and_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            request = build_request(collect_repository(root), "Add a safe export command")

        self.assertIn("Add a safe export command", request)
        self.assertIn("Requested Planning Output", request)
        self.assertIn("Do not write code yet", request)

    def test_valid_plan_passes(self) -> None:
        plan = """# Plan

## Summary
Implement the feature incrementally.

## Assumptions and Constraints
The existing CLI remains compatible.

## Architecture / Design
The command delegates to `src/bridge.py`.

## Implementation Steps
1. Update `src/bridge.py`.
2. Add coverage in `tests/test_bridge.py`.
3. Document the command in `README.md`.

## Testing and Validation
Run the unit test suite and a manual CLI smoke test.

## Risks and Open Questions
Confirm the output format with the requester.
"""
        result = validate_plan(plan)
        self.assertTrue(result.ok, result.to_text())

    def test_incomplete_plan_fails(self) -> None:
        result = validate_plan("# Plan\n\nA short note.")
        self.assertFalse(result.ok)
        self.assertTrue(any("Assumptions" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
