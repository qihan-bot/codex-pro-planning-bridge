from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

from codex_pro_planning_bridge.models import (
    FileInfo,
    GitState,
    Plan,
    PlanTask,
    ProjectContext,
)


class ModelTests(unittest.TestCase):
    def test_project_context_round_trips_as_json_compatible_data(self) -> None:
        context = ProjectContext(
            root=Path("/tmp/demo"),
            project_types=["python"],
            files=[FileInfo("src/main.py", 12, "python", "print('ok')")],
            dependencies=["pytest"],
            git_state=GitState(
                branch="main",
                status=[" M src/main.py"],
                is_repository=True,
            ),
            generated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )

        restored = ProjectContext.from_dict(context.to_dict())

        self.assertEqual(restored.root, context.root)
        self.assertEqual(restored.project_types, ["python"])
        self.assertEqual(restored.files[0].extension, ".py")
        self.assertEqual(restored.git_state.branch, "main")
        self.assertEqual(restored.generated_at, context.generated_at)

    def test_future_models_have_stable_typed_boundaries(self) -> None:
        task = PlanTask(1, "Update src/main.py", ("src/main.py",))
        plan = Plan(
            Path("PLAN.md"),
            ["Summary", "Implementation Steps"],
            [task],
            ["local-only"],
        )

        self.assertEqual(plan.tasks[0].references, ("src/main.py",))
        self.assertEqual(plan.assumptions, ["local-only"])


if __name__ == "__main__":
    unittest.main()
