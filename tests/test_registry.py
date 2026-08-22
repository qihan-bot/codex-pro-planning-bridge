"""Security, persistence, and concurrency tests for the v0.4 registry."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from codex_pro_planning_bridge.registry import (
    RegistryError,
    RepositoryRegistry,
    default_registry_path,
    normalize_repository_id,
)


class RepositoryRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.registry_path = self.root / "config" / "repositories.json"
        self.project = self.root / "project"
        self.project.mkdir()
        self.registry = RepositoryRegistry(self.registry_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _git_init(self, path: Path) -> None:
        subprocess.run(
            ["git", "-C", str(path), "init", "--quiet"],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_default_registry_path_is_per_user_and_versioned(self) -> None:
        path = default_registry_path()
        self.assertEqual(path.name, "repositories.json")
        self.assertEqual(path.parent.name, "codex-pro-planning-bridge")

    def test_add_persists_schema_and_sorted_ids(self) -> None:
        self.registry.add("zeta", self.project, allow_non_git=True)
        self.registry.add("alpha", self.project, allow_non_git=True)

        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(list(payload["repositories"]), ["alpha", "zeta"])
        self.assertEqual(payload["repositories"]["alpha"]["canonical_path"], str(self.project))
        if os.name != "nt":
            self.assertEqual(self.registry_path.stat().st_mode & 0o777, 0o600)

    def test_ids_are_strict_and_duplicates_are_rejected(self) -> None:
        for repository_id in ("../escape", "", "all", "home", "with space"):
            with self.subTest(repository_id=repository_id):
                with self.assertRaises(RegistryError) as raised:
                    self.registry.add(repository_id, self.project, allow_non_git=True)
                self.assertEqual(raised.exception.code, "invalid_id")

        self.assertEqual(normalize_repository_id(" A-App "), "a-app")
        self.registry.add("A-App", self.project, allow_non_git=True)
        with self.assertRaises(RegistryError) as raised:
            self.registry.add("a-APP", self.project, allow_non_git=True)
        self.assertEqual(raised.exception.code, "duplicate_id")

    def test_git_detection_requires_explicit_non_git_opt_in(self) -> None:
        with self.assertRaises(RegistryError) as raised:
            self.registry.add("plain", self.project)
        self.assertEqual(raised.exception.code, "non_git")
        registration = self.registry.add("plain", self.project, allow_non_git=True)
        self.assertEqual(registration.canonical_path, self.project)
        self.assertFalse(self.registry.doctor("plain").is_git)

        git_project = self.root / "git-project"
        git_project.mkdir()
        self._git_init(git_project)
        self.registry.add("git", git_project)
        health = self.registry.doctor("git")
        self.assertTrue(health.is_git)
        self.assertTrue(health.available)

    def test_dangerous_roots_are_rejected(self) -> None:
        config_dir = self.registry_path.parent
        config_dir.mkdir(parents=True)
        for repository_id, path in (
            ("config-dir", config_dir),
            ("home-dir", Path.home()),
            ("ssh-dir", self.root / ".ssh"),
        ):
            path.mkdir(parents=True, exist_ok=True)
            with self.subTest(repository_id=repository_id):
                with self.assertRaises(RegistryError) as raised:
                    self.registry.add(repository_id, path, allow_non_git=True)
                self.assertEqual(raised.exception.code, "unsafe_path")

        with self.assertRaises(RegistryError) as raised:
            self.registry.add("filesystem", Path(Path(self.root.anchor)), allow_non_git=True)
        self.assertEqual(raised.exception.code, "unsafe_path")

    def test_root_symlink_is_canonicalized_when_supported(self) -> None:
        alias = self.root / "project-alias"
        try:
            alias.symlink_to(self.project, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable in this environment")
        registration = self.registry.add("alias", alias, allow_non_git=True)
        self.assertEqual(registration.canonical_path, self.project.resolve())

    def test_doctor_rejects_child_symlink_escape_and_does_not_follow_loops(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("not read", encoding="utf-8")
        escape = self.project / "escape"
        loop = self.project / "loop"
        try:
            escape.symlink_to(outside, target_is_directory=True)
            loop.symlink_to(self.project, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable in this environment")

        self.registry.add("project", self.project, allow_non_git=True)
        health = self.registry.doctor("project")
        self.assertGreaterEqual(health.symlink_escapes, 1)
        self.assertFalse(health.ok)
        self.assertEqual(health.omitted_count, 0)

    def test_corrupt_and_newer_registries_fail_closed_without_replacement(self) -> None:
        self.registry_path.parent.mkdir(parents=True)
        corrupt = b"{not-json"
        self.registry_path.write_bytes(corrupt)
        with self.assertRaises(RegistryError) as raised:
            self.registry.list()
        self.assertEqual(raised.exception.code, "corrupt")
        self.assertEqual(self.registry_path.read_bytes(), corrupt)

        newer = {
            "schema_version": 99,
            "updated_at": "2026-08-22T00:00:00Z",
            "repositories": {},
        }
        newer_bytes = json.dumps(newer).encode("utf-8")
        self.registry_path.write_bytes(newer_bytes)
        with self.assertRaises(RegistryError) as raised:
            self.registry.list()
        self.assertEqual(raised.exception.code, "unsupported_schema")
        self.assertEqual(self.registry_path.read_bytes(), newer_bytes)

    def test_interrupted_atomic_write_preserves_previous_registry(self) -> None:
        self.registry.add("original", self.project, allow_non_git=True)
        before = self.registry_path.read_bytes()
        with patch("codex_pro_planning_bridge.registry.atomic_write_text", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.registry.add("new", self.project, allow_non_git=True)
        self.assertEqual(self.registry_path.read_bytes(), before)
        self.assertEqual([item.repository_id for item in self.registry.list()], ["original"])

    def test_concurrent_writers_keep_all_valid_entries(self) -> None:
        def register(index: int) -> str:
            registry = RepositoryRegistry(self.registry_path)
            return registry.add(
                f"repo-{index}",
                self.project,
                allow_non_git=True,
            ).repository_id

        with ThreadPoolExecutor(max_workers=8) as executor:
            registered = list(executor.map(register, range(16)))
        self.assertEqual(set(registered), {f"repo-{index}" for index in range(16)})
        self.assertEqual(
            {item.repository_id for item in self.registry.list()},
            {f"repo-{index}" for index in range(16)},
        )

    def test_registry_operations_do_not_modify_repository_files(self) -> None:
        tracked = self.project / "source.txt"
        tracked.write_text("stable\n", encoding="utf-8")
        before = tracked.read_bytes()
        self.registry.add("project", self.project, allow_non_git=True)
        self.registry.doctor("project")
        self.assertEqual(tracked.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
