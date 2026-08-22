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
        self.assertEqual(json.loads(output)["repository"]["canonical_path"], str(self.project))

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


if __name__ == "__main__":
    unittest.main()
