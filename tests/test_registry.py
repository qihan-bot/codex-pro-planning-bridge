"""Security, persistence, and concurrency tests for the v0.4 registry."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from codex_pro_planning_bridge.registry import (
    RegistryError,
    RepositoryRegistry,
    ScanLimits,
    default_registry_path,
    normalize_repository_id,
)


def _register_in_process(registry_path: str, project_path: str, index: int, result_queue) -> None:
    try:
        registration = RepositoryRegistry(registry_path).add(
            f"process-{index}",
            project_path,
            allow_non_git=True,
        )
        result_queue.put(("ok", registration.repository_id))
    except Exception as error:  # pragma: no cover - exercised in child processes
        result_queue.put(("error", type(error).__name__, str(error)))


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

    def _git(self, path: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(path), *arguments],
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

    def test_git_registration_requires_the_repository_root(self) -> None:
        git_project = self.root / "git-project"
        git_project.mkdir()
        self._git_init(git_project)
        nested = git_project / "nested"
        nested.mkdir()

        registration = self.registry.add("git-root", git_project)
        self.assertEqual(registration.canonical_path, git_project)
        with self.assertRaises(RegistryError) as raised:
            self.registry.add("git-nested", nested)
        self.assertEqual(raised.exception.code, "git_subdirectory")
        self.assertEqual([item.repository_id for item in self.registry.list()], ["git-root"])

    def test_git_worktree_and_submodule_roots_are_accepted(self) -> None:
        main = self.root / "main"
        main.mkdir()
        self._git_init(main)
        self._git(main, "config", "user.email", "test@example.invalid")
        self._git(main, "config", "user.name", "Registry Tests")
        (main / "README.md").write_text("main\n", encoding="utf-8")
        self._git(main, "add", "README.md")
        self._git(main, "commit", "--quiet", "-m", "initial")

        worktree = self.root / "worktree"
        self._git(main, "worktree", "add", "--quiet", str(worktree), "-b", "registry-worktree")
        worktree_registration = self.registry.add("worktree", worktree)
        self.assertEqual(worktree_registration.canonical_path, worktree.resolve())

        submodule_source = self.root / "submodule-source"
        submodule_source.mkdir()
        self._git_init(submodule_source)
        self._git(submodule_source, "config", "user.email", "test@example.invalid")
        self._git(submodule_source, "config", "user.name", "Registry Tests")
        (submodule_source / "module.txt").write_text("module\n", encoding="utf-8")
        self._git(submodule_source, "add", "module.txt")
        self._git(submodule_source, "commit", "--quiet", "-m", "initial")

        superproject = self.root / "superproject"
        superproject.mkdir()
        self._git_init(superproject)
        self._git(superproject, "config", "user.email", "test@example.invalid")
        self._git(superproject, "config", "user.name", "Registry Tests")
        subprocess.run(
            [
                "git",
                "-C",
                str(superproject),
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                "--quiet",
                str(submodule_source),
                "modules/submodule",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self._git(superproject, "add", ".")
        self._git(superproject, "commit", "--quiet", "-m", "add submodule")

        submodule_registration = self.registry.add(
            "submodule",
            superproject / "modules" / "submodule",
        )
        self.assertEqual(
            submodule_registration.canonical_path,
            (superproject / "modules" / "submodule").resolve(),
        )

    def test_resolve_authorized_rechecks_flags_identity_and_existence(self) -> None:
        self.registry.add("demo", self.project, allow_non_git=True)
        self.assertEqual(self.registry.resolve_authorized("demo").canonical_path, self.project)

        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        payload["repositories"]["demo"]["enabled"] = False
        self.registry_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(RegistryError) as raised:
            self.registry.resolve_authorized("demo")
        self.assertEqual(raised.exception.code, "disabled")

        payload["repositories"]["demo"]["enabled"] = True
        payload["repositories"]["demo"]["read"] = False
        self.registry_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(RegistryError) as raised:
            self.registry.resolve_authorized("demo")
        self.assertEqual(raised.exception.code, "read_denied")

        payload["repositories"]["demo"]["read"] = True
        payload["repositories"]["demo"]["canonical_path"] = str(self.project / "missing")
        self.registry_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(RegistryError) as raised:
            self.registry.resolve_authorized("demo")
        self.assertEqual(raised.exception.code, "missing")

        payload["repositories"]["demo"]["canonical_path"] = str(self.project / "." / ".." / self.project.name)
        self.registry_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(RegistryError) as raised:
            self.registry.resolve_authorized("demo")
        self.assertEqual(raised.exception.code, "redirected")

    def test_read_only_registry_operations_have_no_storage_side_effects(self) -> None:
        empty_registry = RepositoryRegistry(self.registry_path)
        self.assertEqual(empty_registry.list(), [])
        with self.assertRaises(RegistryError) as raised:
            empty_registry.get("demo")
        self.assertEqual(raised.exception.code, "not_found")
        preview = empty_registry.preview(self.project, allow_non_git=True)
        self.assertEqual(preview.canonical_path, self.project)
        self.assertFalse(self.registry_path.exists())
        self.assertFalse(empty_registry.lock_path.exists())

    def test_scan_stops_at_file_directory_and_depth_budgets(self) -> None:
        for index in range(10):
            (self.project / f"file-{index:02d}.txt").write_text("data\n", encoding="utf-8")
        current = self.project
        for index in range(4):
            current = current / f"level-{index}"
            current.mkdir()
        (current / "deep.txt").write_text("deep\n", encoding="utf-8")

        limited = RepositoryRegistry(
            self.registry_path,
            scan_limits=ScanLimits(max_files=3, max_directories=2, max_depth=1),
        )
        preview = limited.preview(self.project, allow_non_git=True)
        self.assertLessEqual(preview.visited_files, 3)
        self.assertLessEqual(preview.visited_directories, 2)
        self.assertTrue(preview.scan_truncated)
        self.assertTrue(any("incomplete" in warning for warning in preview.warnings))

        deep = RepositoryRegistry(
            self.registry_path,
            scan_limits=ScanLimits(max_files=100, max_directories=100, max_depth=1),
        )
        deep_preview = deep.preview(self.project, allow_non_git=True)
        self.assertLessEqual(deep_preview.visited_directories, 100)
        self.assertTrue(deep_preview.scan_truncated)

    def test_scan_records_unreadable_directories_without_unbounded_walk(self) -> None:
        blocked = self.project / "blocked"
        blocked.mkdir()
        (blocked / "hidden.txt").write_text("hidden\n", encoding="utf-8")
        real_scandir = os.scandir

        def scandir_with_block(path):
            if Path(path) == blocked:
                raise PermissionError("test permission boundary")
            return real_scandir(path)

        with patch("codex_pro_planning_bridge.registry.os.scandir", side_effect=scandir_with_block):
            summary = self.registry._scan_path(self.project)
        self.assertEqual(summary.unreadable_directories, 1)
        self.assertFalse(summary.scan_truncated)

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

    def _make_junction(self, link: Path, target: Path) -> None:
        if os.name != "nt":
            self.skipTest("junctions are Windows-only")
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not link.exists():
            self.skipTest("Windows junction capability is unavailable")

    def test_windows_junctions_are_canonicalized_and_not_followed(self) -> None:
        target = self.root / "junction-target"
        target.mkdir()
        alias = self.root / "junction-alias"
        self._make_junction(alias, target)
        registration = self.registry.add("junction", alias, allow_non_git=True)
        self.assertEqual(registration.canonical_path, target.resolve())

        outside = self.root / "junction-outside"
        outside.mkdir()
        escape = self.project / "junction-escape"
        self._make_junction(escape, outside)
        self.registry.add("junction-project", self.project, allow_non_git=True)
        health = self.registry.doctor("junction-project")
        self.assertGreaterEqual(health.symlink_escapes, 1)
        self.assertFalse(health.ok)

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

    def test_multiprocess_writers_keep_all_valid_entries(self) -> None:
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue()
        processes = [
            context.Process(
                target=_register_in_process,
                args=(str(self.registry_path), str(self.project), index, result_queue),
            )
            for index in range(4)
        ]
        for process in processes:
            process.start()
        results = [result_queue.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual([result[0] for result in results], ["ok"] * 4)
        self.assertEqual(
            {item.repository_id for item in self.registry.list()},
            {f"process-{index}" for index in range(4)},
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
