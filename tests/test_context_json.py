from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.artifacts import collect_context


class ContextJsonTests(unittest.TestCase):
    def test_context_json_is_rehydratable_without_executing_project_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "pyproject.toml").write_text(
                "[project]\nname = 'demo'\ndependencies = ['pytest']\n",
                encoding="utf-8",
            )
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("def main():\n    return True\n", encoding="utf-8")

            outputs = collect_context(root)
            data = json.loads(outputs["json"].read_text(encoding="utf-8"))

            self.assertEqual(data["repository"], root.name)
            self.assertEqual(data["project_types"], ["python"])
            self.assertEqual(data["dependencies"], ["pytest"])
            self.assertTrue(data["files"])
            self.assertIn("git_state", data)


if __name__ == "__main__":
    unittest.main()
