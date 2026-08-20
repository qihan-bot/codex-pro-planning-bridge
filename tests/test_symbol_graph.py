from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_pro_planning_bridge.intelligence.symbol_graph import (
    build_symbol_graph,
    export_symbol_graph,
    load_symbol_graph,
)


class SymbolGraphTests(unittest.TestCase):
    def test_graph_connects_ownership_imports_and_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "src"
            source.mkdir()
            (source / "service.py").write_text(
                "from helpers import helper\n\n"
                "class Service:\n"
                "    def run(self):\n"
                "        return helper()\n",
                encoding="utf-8",
            )
            (source / "helpers.py").write_text(
                "def helper():\n    return True\n",
                encoding="utf-8",
            )

            graph = build_symbol_graph(root)

            owned = graph.related("Service.run", kind="OWNS", direction="in")
            imported = graph.related("src/service.py", kind="IMPORTS")
            called = graph.related("Service.run", kind="CALLS")

            self.assertTrue(any(node.name == "Service" for node in owned))
            self.assertTrue(any(node.name == "helpers" for node in imported))
            self.assertTrue(any(node.name == "helper" for node in called))

            path = export_symbol_graph(graph, root / "symbol-graph.json")
            loaded = load_symbol_graph(path)
            self.assertEqual(len(loaded.nodes), len(graph.nodes))
            self.assertEqual(len(loaded.edges), len(graph.edges))

    def test_graph_covers_javascript_typescript_and_rust_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "src"
            source.mkdir()
            (source / "helpers.ts").write_text(
                "export function helper(): boolean { return true; }\n",
                encoding="utf-8",
            )
            (source / "service.ts").write_text(
                "import { helper } from './helpers';\n"
                "export class Service {\n"
                "  run() { return helper(); }\n"
                "}\n",
                encoding="utf-8",
            )
            (source / "lib.rs").write_text(
                "use crate::helpers::rust_helper;\n"
                "pub struct Engine;\n"
                "impl Engine {\n"
                "    pub fn run() { rust_helper(); }\n"
                "}\n",
                encoding="utf-8",
            )
            (source / "helpers.rs").write_text(
                "pub fn rust_helper() {}\n",
                encoding="utf-8",
            )

            graph = build_symbol_graph(root)
            node_languages = {node.language for node in graph.nodes if node.kind != "dependency"}

            self.assertIn("typescript", node_languages)
            self.assertIn("rust", node_languages)
            self.assertTrue(graph.related("src/service.ts", kind="IMPORTS"))
            self.assertTrue(graph.related("Service.run", kind="CALLS"))
            self.assertTrue(graph.related("Engine.run", kind="CALLS"))
            self.assertTrue(any(node.name == "crate::helpers::rust_helper" for node in graph.related("src/lib.rs", kind="IMPORTS")))

    def test_graph_is_deterministic_and_tolerates_unresolved_and_ambiguous_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "src"
            source.mkdir()
            (source / "caller.py").write_text(
                "from missing_package import missing\n\n"
                "def run():\n"
                "    return helper()\n",
                encoding="utf-8",
            )
            (source / "first.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
            (source / "second.py").write_text("def helper():\n    return 2\n", encoding="utf-8")

            first = build_symbol_graph(root)
            second = build_symbol_graph(root)

            self.assertEqual(first.to_dict(), second.to_dict())
            self.assertTrue(any(node.name == "missing_package" for node in first.nodes))
            called = first.related("caller.run", kind="CALLS")
            self.assertEqual({node.name for node in called}, {"helper"})
            self.assertGreaterEqual(len(called), 2)


if __name__ == "__main__":
    unittest.main()
