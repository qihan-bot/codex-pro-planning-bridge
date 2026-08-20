from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.intelligence.symbol_index import (
    build_symbol_index,
    export_symbol_index,
    load_symbol_index,
)


class SymbolIndexTests(unittest.TestCase):
    def test_indexes_python_javascript_typescript_and_rust_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "src").mkdir()
            (root / "src" / "service.py").write_text(
                "class UserService:\n    def refresh(self):\n        return True\n",
                encoding="utf-8",
            )
            (root / "src" / "client.ts").write_text(
                "export class Client {\n  connect() { return true; }\n}\n"
                "export function createClient() { return new Client(); }\n",
                encoding="utf-8",
            )
            (root / "src" / "lib.rs").write_text(
                "pub struct Account;\nimpl Account { pub fn close(&self) {} }\n",
                encoding="utf-8",
            )

            index = build_symbol_index(root)

            self.assertTrue(index.find("UserService.refresh"))
            self.assertTrue(index.find("Client.connect"))
            self.assertTrue(index.find("createClient"))
            self.assertTrue(index.find("Account::close"))
            self.assertIn("src/service.py", index.files)

    def test_symbol_index_round_trips_as_local_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("def run():\n    pass\n", encoding="utf-8")
            index = build_symbol_index(root)
            path = export_symbol_index(index, root / "symbol-index.json")

            loaded = load_symbol_index(path)

            self.assertEqual([item.qualified_name for item in loaded.symbols], [item.qualified_name for item in index.symbols])
            self.assertEqual(loaded.schema_version, 1)


if __name__ == "__main__":
    unittest.main()
