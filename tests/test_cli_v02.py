from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.cli import main


class UnifiedCliTests(unittest.TestCase):
    def test_init_and_prompt_aliases_share_the_unified_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")

            self.assertEqual(main(["init", "--repo", str(root)]), 0)
            self.assertTrue((root / ".codex" / "pro-plan" / "context.json").is_file())
            self.assertTrue((root / ".codex" / "project-memory" / "memory.json").is_file())
            self.assertEqual(
                main(["prompt", "--repo", str(root), "--goal", "Review the demo"]),
                0,
            )
            self.assertTrue((root / ".codex" / "pro-plan" / "REQUEST.md").is_file())

    def test_collect_request_validate_and_diff_share_the_cli_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("def run():\n    return True\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_main.py").write_text("def test_run():\n    pass\n", encoding="utf-8")

            self.assertEqual(main(["collect", "--repo", str(root)]), 0)
            self.assertEqual(
                main(["request", "--repo", str(root), "--goal", "Review the local change"]),
                0,
            )
            plan_path = root / ".codex" / "pro-plan" / "PLAN.md"
            plan_path.write_text(
                """# Plan

## Summary
Review the local change.

## Assumptions and Constraints
No network access.

## Architecture / Design
Keep `src/main.py` as the entry point.

## Implementation Steps
1. Update `src/main.py`.
2. Add `tests/test_main.py`.
3. Run the local test suite.

## Testing and Validation
Run the tests.

## Risks and Open Questions
Confirm the rollout.
""",
                encoding="utf-8",
            )
            self.assertEqual(main(["validate", "--repo", str(root)]), 0)
            self.assertEqual(main(["diff", "--repo", str(root)]), 1)
            self.assertTrue((root / ".codex" / "pro-plan" / "VALIDATION_REPORT.md").is_file())
            self.assertTrue((root / ".codex" / "pro-plan" / "PLAN_DIFF.md").is_file())

    def test_memory_commands_are_available_from_the_single_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            self.assertEqual(main(["memory", "init", "--repo", str(root)]), 0)
            self.assertEqual(
                main(
                    [
                        "memory",
                        "write",
                        "--repo",
                        str(root),
                        "--document",
                        "decisions.md",
                        "--content",
                        "- Decision: keep it local.",
                        "--append",
                    ]
                ),
                0,
            )
            self.assertEqual(main(["memory", "show", "--repo", str(root), "--document", "decisions"]), 0)
            self.assertIn(
                "keep it local",
                (root / ".codex" / "project-memory" / "decisions.md").read_text(encoding="utf-8"),
            )

    def test_memory_adr_commands_are_available_from_the_single_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            self.assertEqual(
                main(
                    [
                        "memory",
                        "adr-create",
                        "--repo",
                        str(root),
                        "--title",
                        "Keep the workflow local",
                        "--status",
                        "Accepted",
                        "--content",
                        "No remote API calls.",
                    ]
                ),
                0,
            )
            self.assertEqual(main(["memory", "list", "--repo", str(root)]), 0)
            adr = root / ".codex" / "project-memory" / "adr" / "0001-keep-the-workflow-local.md"
            self.assertTrue(adr.is_file())
            self.assertIn("No remote API calls.", adr.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
