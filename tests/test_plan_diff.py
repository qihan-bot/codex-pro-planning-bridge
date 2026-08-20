from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.diff import compare_plan, diff_plan, render_plan_diff
from codex_pro_planning_bridge.intelligence.symbol_index import Symbol, SymbolIndex


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


class PlanDiffTests(unittest.TestCase):
    def test_compare_plan_classifies_completion_missing_blocked_and_unplanned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = compare_plan(
                root,
                PLAN,
                changed_files=["src/service.py", "README.md"],
            )

            self.assertEqual(len(result.completed), 1)
            self.assertEqual(len(result.missing), 1)
            self.assertEqual(len(result.blocked), 1)
            self.assertEqual(result.unplanned_changes, ["README.md"])
            report = render_plan_diff(result)
            self.assertIn("## Completed", report)
            self.assertIn("## Missing", report)
            self.assertIn("## Changed / Drift", report)
            self.assertIn("## Blocked", report)
            self.assertIn("README.md", report)

    def test_partial_path_coverage_is_reported_as_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            markdown = PLAN.replace("`src/service.py`", "`src/service.py` and `src/models.py`")
            result = compare_plan(root, markdown, changed_files=["src/service.py"])

            self.assertEqual(len(result.changed), 1)
            self.assertEqual(len(result.missing), 1)
            self.assertIn("partial implementation", result.changed[0].detail)

    def test_diff_plan_writes_a_report_to_the_requested_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan_path = root / ".codex" / "pro-plan" / "PLAN.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN, encoding="utf-8")

            report_path, result = diff_plan(root)

            self.assertEqual(report_path, root / ".codex" / "pro-plan" / "PLAN_DIFF.md")
            self.assertTrue(report_path.is_file())
            self.assertFalse(result.ok)
            self.assertIn("DRIFT DETECTED", report_path.read_text(encoding="utf-8"))

    def test_compare_plan_reports_symbol_movement_between_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            before = SymbolIndex(
                symbols=[
                    Symbol(
                        name="refresh",
                        qualified_name="UserService.refresh",
                        kind="method",
                        path="src/old_service.py",
                        line=4,
                        language="python",
                    )
                ]
            )
            after = SymbolIndex(
                symbols=[
                    Symbol(
                        name="refresh",
                        qualified_name="UserService.refresh",
                        kind="method",
                        path="src/service.py",
                        line=4,
                        language="python",
                    )
                ]
            )

            result = compare_plan(
                root,
                PLAN,
                changed_files=["src/service.py"],
                baseline_symbol_index=before,
                current_symbol_index=after,
            )

            self.assertEqual(result.symbol_changes[0].kind, "moved")
            self.assertIn("## Symbol Changes", render_plan_diff(result))


if __name__ == "__main__":
    unittest.main()
