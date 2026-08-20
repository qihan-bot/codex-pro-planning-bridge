from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.context import (
    collect_repository,
    detect_project_type,
    scan_files,
)
from codex_pro_planning_bridge.models import FileInfo, ProjectContext


class ContextLayerTests(unittest.TestCase):
    def test_scanner_returns_file_info_and_detector_identifies_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "package.json").write_text(
                '{"dependencies": {"requests": "^1.0.0"}}\n', encoding="utf-8"
            )
            (root / "pyproject.toml").write_text(
                "[project]\ndependencies = [\"pytest\"]\n", encoding="utf-8"
            )
            (root / ".env").write_text("TOKEN=hidden\n", encoding="utf-8")

            files = scan_files(root)
            context = collect_repository(root)
            project_type = detect_project_type(files)

            self.assertTrue(all(isinstance(item, FileInfo) for item in files))
            self.assertEqual(project_type.names, ["python", "node"])
            self.assertIsInstance(context, ProjectContext)
            self.assertEqual(context.project_types, ["python", "node"])
            self.assertEqual(context.dependencies, ["pytest", "requests"])
            self.assertNotIn(".env", {item.path for item in files})

    def test_collector_preserves_bounded_excerpts_and_redaction_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "server.pem").write_text("private\n", encoding="utf-8")

            context = collect_repository(root, max_file_bytes=3, max_total_bytes=3)

            self.assertEqual(context.files[0].excerpt, "# D")
            self.assertIn("server.pem", context.excluded_sensitive)
            self.assertIn("README.md", context.to_markdown())


if __name__ == "__main__":
    unittest.main()
