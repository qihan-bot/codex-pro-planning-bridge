"""CLI contract tests for repository registration commands."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from codex_pro_planning_bridge.cli import main


class RepositoryRegistryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.registry = self.root / "config" / "repositories.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _run(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main([*arguments, "--registry-path", str(self.registry)])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_add_list_show_doctor_and_remove_json_flow(self) -> None:
        result, output, error = self._run(
            "repo",
            "add",
            "demo",
            str(self.project),
            "--allow-non-git",
            "--yes",
            "--format",
            "json",
        )
        self.assertEqual(result, 0, error)
        self.assertEqual(json.loads(output)["repository"]["repository_id"], "demo")

        result, output, error = self._run("repo", "list", "--format", "json")
        self.assertEqual(result, 0, error)
        self.assertEqual(json.loads(output)["count"], 1)

        result, output, error = self._run("repo", "show", "demo", "--format", "json")
        self.assertEqual(result, 0, error)
        self.assertEqual(
            json.loads(output)["repository"]["canonical_path"],
            str(self.project.resolve()),
        )

        result, output, error = self._run("repo", "doctor", "demo", "--format", "json")
        self.assertEqual(result, 0, error)
        self.assertTrue(json.loads(output)["health"]["ok"])

        result, output, error = self._run("repo", "remove", "demo", "--yes", "--format", "json")
        self.assertEqual(result, 0, error)
        self.assertEqual(json.loads(output)["removed"], "demo")

        result, output, error = self._run("repo", "list", "--format", "json")
        self.assertEqual(result, 0, error)
        self.assertEqual(json.loads(output)["count"], 0)

    def test_add_requires_non_git_opt_in_and_confirmation_is_explicit(self) -> None:
        result, _, error = self._run("repo", "add", "demo", str(self.project), "--yes")
        self.assertEqual(result, 2)
        self.assertIn("allow-non-git", error)

        with patch("builtins.input", return_value="n"):
            result, output, error = self._run(
                "repo",
                "add",
                "demo",
                str(self.project),
                "--allow-non-git",
            )
        self.assertEqual(result, 1)
        self.assertIn("cancelled", output.casefold())
        self.assertEqual(error, "")
        self.assertFalse(self.registry.is_file())

    def test_remove_requires_confirmation(self) -> None:
        result, _, error = self._run(
            "repo",
            "add",
            "demo",
            str(self.project),
            "--allow-non-git",
            "--yes",
        )
        self.assertEqual(result, 0, error)
        with patch("builtins.input", return_value="n"):
            result, output, error = self._run("repo", "remove", "demo")
        self.assertEqual(result, 1)
        self.assertIn("cancelled", output.casefold())
        self.assertEqual(error, "")
        result, _, error = self._run("repo", "show", "demo")
        self.assertEqual(result, 0, error)

    def test_json_add_without_yes_is_one_confirmation_error_document(self) -> None:
        with patch("builtins.input") as prompt:
            result, output, error = self._run(
                "repo",
                "add",
                "demo",
                str(self.project),
                "--allow-non-git",
                "--format",
                "json",
            )
        self.assertEqual(result, 2)
        self.assertEqual(error, "")
        prompt.assert_not_called()
        self.assertEqual(json.loads(output), {
            "error": {
                "code": "confirmation_required",
                "message": "explicit confirmation is required; pass --yes",
            }
        })
        self.assertFalse(self.registry.exists())
        self.assertFalse(self.registry.with_name("repositories.json.lock").exists())

    def test_json_remove_without_yes_is_noninteractive_and_preserves_entry(self) -> None:
        result, _, error = self._run(
            "repo",
            "add",
            "demo",
            str(self.project),
            "--allow-non-git",
            "--yes",
        )
        self.assertEqual(result, 0, error)
        before = self.registry.read_bytes()
        with patch("builtins.input") as prompt:
            result, output, error = self._run(
                "repo",
                "remove",
                "demo",
                "--format",
                "json",
            )
        self.assertEqual(result, 2)
        self.assertEqual(error, "")
        prompt.assert_not_called()
        self.assertEqual(json.loads(output)["error"]["code"], "confirmation_required")
        self.assertEqual(self.registry.read_bytes(), before)

    def test_json_registry_errors_include_stable_codes_on_stdout(self) -> None:
        result, output, error = self._run(
            "repo",
            "add",
            "../invalid",
            str(self.project),
            "--allow-non-git",
            "--yes",
            "--format",
            "json",
        )
        self.assertEqual(result, 2)
        self.assertEqual(error, "")
        self.assertEqual(json.loads(output)["error"]["code"], "invalid_id")

        result, output, error = self._run(
            "repo",
            "add",
            "git-only",
            str(self.project),
            "--yes",
            "--format",
            "json",
        )
        self.assertEqual(result, 2)
        self.assertEqual(error, "")
        self.assertEqual(json.loads(output)["error"]["code"], "non_git")


if __name__ == "__main__":
    unittest.main()
