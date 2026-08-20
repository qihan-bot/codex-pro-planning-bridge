from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from codex_pro_planning_bridge.memory import ProjectMemory, read_memory


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


class ProjectMemoryTests(unittest.TestCase):
    def test_initialize_is_idempotent_and_persists_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            memory = ProjectMemory(root)

            created = memory.initialize()
            self.assertEqual(len(created), 4)
            self.assertTrue((root / ".codex" / "project-memory" / "decisions.md").is_file())
            metadata = json.loads(
                (root / ".codex" / "project-memory" / "memory.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(metadata["version"], "1")
            self.assertEqual(metadata["entries"], 0)

            memory.write("architecture.md", "# Architecture\n\nUse a local CLI.")
            self.assertEqual(memory.initialize(), [])
            self.assertIn("Use a local CLI", memory.document("architecture").content)

            memory.append("constraints", "- No API calls.")
            loaded = read_memory(root)
            self.assertIn("No API calls", loaded["constraints"])

    def test_record_plan_persists_summary_and_architecture_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan_path = root / ".codex" / "pro-plan" / "PLAN.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN, encoding="utf-8")

            memory = ProjectMemory(root)
            memory.initialize()
            path = memory.record_plan()
            content = path.read_text(encoding="utf-8")

            self.assertIn("Planning record", content)
            self.assertIn("Implement a service change.", content)
            self.assertIn("The service remains the integration point.", content)

    def test_adr_storage_is_numbered_versioned_and_listable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            memory = ProjectMemory(root)
            memory.initialize()

            first = memory.create_adr(
                "Use a local cache",
                status="Accepted",
                content="The bridge must remain local-first.",
            )
            second = memory.create_adr("Keep the CLI stable")

            self.assertEqual(first.name, "0001-use-a-local-cache.md")
            self.assertEqual(second.name, "0002-keep-the-cli-stable.md")
            self.assertEqual(
                [item.key for item in memory.list_adrs()], ["ADR-0001", "ADR-0002"]
            )
            self.assertIn("Status: Accepted", first.read_text(encoding="utf-8"))
            self.assertEqual(memory.metadata()["entries"], 2)

    def test_legacy_decisions_document_remains_a_compatibility_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            memory = ProjectMemory(root)
            memory.initialize()
            memory.append("decisions", "- Existing decision remains documented.")

            self.assertIn("Existing decision", memory.document("decisions").content)
            self.assertEqual(memory.document("issues").key, "known-issues")

    def test_memory_schema_migration_is_recorded_without_rewriting_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            memory = ProjectMemory(root)
            memory.initialize()
            metadata_path = root / ".codex" / "project-memory" / "memory.json"
            metadata_path.write_text(
                json.dumps({"version": "1", "entries": 0}),
                encoding="utf-8",
            )

            migrated = memory.migrate()

            self.assertEqual(len(migrated), 1)
            self.assertTrue(migrated[0].is_file())
            self.assertIn("migrations", migrated[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
