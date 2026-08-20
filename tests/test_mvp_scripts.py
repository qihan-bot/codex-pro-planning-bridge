from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_prompt import build_prompt
from scripts.collect_context import collect_context
from scripts.open_chat import open_chat
from scripts.validate_plan import check_paths, extract_path_references, validate


class MvpScriptTests(unittest.TestCase):
    def test_context_collector_writes_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            for manifest in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod"):
                (root / manifest).write_text("# manifest\n", encoding="utf-8")
            (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "ignored.js").write_text("ignored\n", encoding="utf-8")
            (root / "dist").mkdir()
            (root / "dist" / "bundle.js").write_text("ignored\n", encoding="utf-8")
            (root / "private.pem").write_text("private\n", encoding="utf-8")

            outputs = collect_context(root)
            tree = outputs["tree"].read_text(encoding="utf-8")
            context = outputs["context"].read_text(encoding="utf-8")

            self.assertEqual(set(outputs), {"tree", "status", "context"})
            self.assertIn("package.json", tree)
            self.assertIn("src/main.py", tree)
            self.assertNotIn("node_modules", tree)
            self.assertNotIn("dist", tree)
            self.assertNotIn(".env", tree)
            self.assertNotIn("private.pem", tree)
            self.assertIn("package.json", context)
            self.assertIn("pyproject.toml", context)
            self.assertIn("Cargo.toml", context)
            self.assertIn("go.mod", context)

    def test_ignore_patterns_cover_required_directories_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for directory in (".git", "node_modules", "dist", "build"):
                (root / directory).mkdir()
                (root / directory / "hidden.txt").write_text("hidden\n", encoding="utf-8")
            (root / ".env").write_text("SECRET=value\n", encoding="utf-8")
            (root / "server.key").write_text("private\n", encoding="utf-8")
            (root / "safe.txt").write_text("safe\n", encoding="utf-8")

            outputs = collect_context(root)
            tree = outputs["tree"].read_text(encoding="utf-8")

            self.assertIn("safe.txt", tree)
            for ignored in (".git", "node_modules", "dist", "build", ".env", "server.key"):
                self.assertNotIn(ignored, tree)

    def test_prompt_builder_uses_template_and_collected_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            collect_context(root)

            output = build_prompt(root, user_request="Add an audit log without API calls")
            request = output.read_text(encoding="utf-8")

            self.assertIn("Add an audit log without API calls", request)
            self.assertIn("# Project Context", request)
            self.assertIn("README.md", request)
            self.assertNotIn("{{USER_REQUEST}}", request)
            self.assertIn("ChatGPT Pro", request)

    def test_plan_validator_checks_referenced_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("pass\n", encoding="utf-8")
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_mvp_scripts.py").write_text("pass\n", encoding="utf-8")
            plan_dir = root / ".codex" / "pro-plan"
            plan_dir.mkdir(parents=True)
            plan = """# Plan

## Summary
Implement the change.

## Assumptions and Constraints
Keep the CLI stable.

## Architecture / Design
Update `src/main.py`.

## Implementation Steps
1. Update `src/main.py`.
2. Add tests in `tests/test_mvp_scripts.py`.
3. Document the behavior in `README.md`.

## Testing and Validation
Run the unit tests.

## Risks and Open Questions
Confirm the rollout sequence.
"""
            (plan_dir / "PLAN.md").write_text(plan, encoding="utf-8")

            self.assertEqual(extract_path_references(plan), ["README.md", "src/main.py", "tests/test_mvp_scripts.py"])
            checks = check_paths(root, extract_path_references(plan))
            self.assertTrue(all(check.status == "OK" for check in checks))
            report_path, passed = validate(root)
            self.assertTrue(passed)
            self.assertIn("PASS", report_path.read_text(encoding="utf-8"))

    @patch("scripts.open_chat.webbrowser.open")
    @patch("scripts.open_chat.copy_to_clipboard", return_value="test-clipboard")
    def test_open_chat_keeps_handoff_manual(self, clipboard, browser) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            request = root / ".codex" / "pro-plan" / "REQUEST.md"
            request.parent.mkdir(parents=True)
            request.write_text("# Request\n", encoding="utf-8")

            result = open_chat(root, pause=False)

            self.assertEqual(result, 0)
            clipboard.assert_called_once_with("# Request\n")
            browser.assert_called_once()


if __name__ == "__main__":
    unittest.main()
