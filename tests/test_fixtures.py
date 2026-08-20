from __future__ import annotations

from pathlib import Path
import unittest

from codex_pro_planning_bridge.context import collect_repository
from codex_pro_planning_bridge.plan import validate_plan


FIXTURES = Path(__file__).parent / "fixtures"


class FixtureTests(unittest.TestCase):
    def test_python_fixture_is_detected_with_dependencies(self) -> None:
        context = collect_repository(FIXTURES / "python_project")

        self.assertEqual(context.project_types, ["python"])
        self.assertIn("pytest", context.dependencies)
        self.assertIn("src/app.py", {item.path for item in context.files})

    def test_node_fixture_is_detected_with_dependencies(self) -> None:
        context = collect_repository(FIXTURES / "node_project")

        self.assertEqual(context.project_types, ["node"])
        self.assertIn("express", context.dependencies)

    def test_broken_plan_fixture_fails_structural_validation(self) -> None:
        plan = (FIXTURES / "broken_plan" / "PLAN.md").read_text(encoding="utf-8")

        result = validate_plan(plan)

        self.assertFalse(result.ok)
        self.assertTrue(result.errors)


if __name__ == "__main__":
    unittest.main()
