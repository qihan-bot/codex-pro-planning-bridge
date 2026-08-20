from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from codex_pro_planning_bridge.diff import compare_plan, render_plan_diff
from codex_pro_planning_bridge.facts import build_repository_facts
from codex_pro_planning_bridge.models import FileChange
from codex_pro_planning_bridge.repository import git_file_changes
from codex_pro_planning_bridge.validator import check_symbols


class FactHardeningTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "git is required for rename detection")
    def test_git_change_reader_preserves_rename_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            def git(*args: str) -> None:
                subprocess.run(
                    ["git", *args],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            git("init", "-q")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "Test")
            (root / "old.py").write_text("def run():\n    return True\n", encoding="utf-8")
            git("add", "old.py")
            git("commit", "-qm", "initial")
            (root / "old.py").rename(root / "new.py")
            git("add", "-A")

            changes = git_file_changes(root, base="HEAD")

            self.assertTrue(
                any(
                    item.previous_path == "old.py" and item.path == "new.py"
                    for item in changes
                )
            )

    def test_plan_diff_reports_renames_as_changed_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = """# Plan

## Implementation Steps
1. Update `old.py`.
"""
            result = compare_plan(
                root,
                plan,
                file_changes=[
                    FileChange(
                        status="R",
                        previous_path="old.py",
                        path="new.py",
                        similarity=91,
                    )
                ],
            )

            self.assertEqual(len(result.renamed_files), 1)
            self.assertEqual(len(result.changed), 1)
            self.assertIn("renamed locally", result.changed[0].detail)
            report = render_plan_diff(result)
            self.assertIn("## Renamed Files", report)
            self.assertIn("old.py", report)
            self.assertIn("new.py", report)

    def test_validator_suggests_possible_symbol_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "service.py").write_text(
                "class AuthService:\n    def refresh_token(self):\n        return True\n",
                encoding="utf-8",
            )
            facts = build_repository_facts(root)

            findings = check_symbols(facts, ["UserService.refresh"])

            self.assertEqual(findings[0].status, "ERROR")
            self.assertIn("AuthService.refresh_token", findings[0].possible_matches)
            self.assertIn("possible matches", findings[0].detail)


if __name__ == "__main__":
    unittest.main()
