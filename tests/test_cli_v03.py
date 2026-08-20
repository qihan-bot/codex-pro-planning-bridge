from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.cli import main


PLAN = """# Plan

## Summary
Run the local workflow.

## Assumptions and Constraints
No network access.

## Architecture / Design
Keep the CLI local.

## Implementation Steps
1. Update `src/app.py`.
2. Update `tests/test_app.py`.
3. Review `README.md`.

## Testing and Validation
Run the tests.

## Risks and Open Questions
Review drift.
"""


class UnifiedCliV03Tests(unittest.TestCase):
    def test_loop_command_is_resumable_and_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "app.py").write_text("def run():\n    pass\n", encoding="utf-8")
            (root / "tests" / "test_app.py").write_text("def test_run():\n    pass\n", encoding="utf-8")
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "loop",
                            "--repo",
                            str(root),
                            "--goal",
                            "Review the demo",
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )
            self.assertIn('"state": "CONTEXT_READY"', output.getvalue())

            plan_path = root / ".codex" / "pro-plan" / "PLAN.md"
            plan_path.write_text(PLAN, encoding="utf-8")
            self.assertEqual(main(["loop", "--repo", str(root)]), 0)
            state = (root / ".codex" / "workflow" / "state.json").read_text(encoding="utf-8")
            self.assertIn('"state": "IMPLEMENTING"', state)


if __name__ == "__main__":
    unittest.main()
