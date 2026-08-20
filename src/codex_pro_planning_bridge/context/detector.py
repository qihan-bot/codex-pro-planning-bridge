"""Project-type and dependency detection from supported manifests."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable

from ..models import FileInfo, ProjectType
from ..repository import SUPPORTED_MANIFESTS, resolve_repo


MANIFEST_TYPES = {
    "package.json": "node",
    "pyproject.toml": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
}


def detect_project_type(files: Iterable[FileInfo | str]) -> ProjectType:
    """Detect supported ecosystems from file metadata or relative paths."""

    names = {Path(item.path if isinstance(item, FileInfo) else item).name for item in files}
    return ProjectType(
        python="pyproject.toml" in names,
        node="package.json" in names,
        rust="Cargo.toml" in names,
        go="go.mod" in names,
    )


def detect_project_types(files: Iterable[FileInfo | str]) -> list[str]:
    return detect_project_type(files).names


def _read_json_dependencies(path: Path) -> list[str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    dependencies: list[str] = []
    if isinstance(value, dict):
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            entries = value.get(section, {})
            if isinstance(entries, dict):
                dependencies.extend(str(name) for name in entries)
    return dependencies


def _read_pyproject_dependencies(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    dependencies: list[str] = []
    in_dependencies = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_dependencies = stripped in {"[project]", "[tool.poetry.dependencies]"}
        inline = re.search(r"dependencies\s*=\s*\[(.*?)\]", stripped)
        if inline:
            dependencies.extend(
                re.findall(r"[\"']([A-Za-z0-9_.-]+)[\"']", inline.group(1))
            )
            in_dependencies = False
            continue
        if stripped.startswith("dependencies") and "[" in stripped:
            in_dependencies = True
        if in_dependencies:
            match = re.match(r"[-\"']+([A-Za-z0-9_.-]+)", stripped)
            if match:
                dependencies.append(match.group(1))
    return dependencies


def _read_cargo_dependencies(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    dependencies: list[str] = []
    active = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            active = stripped == "[dependencies]"
            continue
        if active:
            match = re.match(r"([A-Za-z0-9_-]+)\s*=", stripped)
            if match:
                dependencies.append(match.group(1))
    return dependencies


def _read_go_dependencies(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    dependencies: list[str] = []
    in_require = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "require (":
            in_require = True
            continue
        if in_require and stripped == ")":
            in_require = False
            continue
        if in_require:
            parts = stripped.split()
            if parts:
                dependencies.append(parts[0])
        elif stripped.startswith("require "):
            parts = stripped.split()
            if len(parts) > 1:
                dependencies.append(parts[1])
    return dependencies


def detect_dependencies(repo: str | Path = ".", files: Iterable[FileInfo | str] = ()) -> list[str]:
    """Read dependency names from supported manifests without executing code."""

    root = resolve_repo(repo)
    paths = {Path(item.path if isinstance(item, FileInfo) else item) for item in files}
    dependencies: list[str] = []
    readers = {
        "package.json": _read_json_dependencies,
        "pyproject.toml": _read_pyproject_dependencies,
        "Cargo.toml": _read_cargo_dependencies,
        "go.mod": _read_go_dependencies,
    }
    for manifest in SUPPORTED_MANIFESTS:
        path = root / manifest
        if Path(manifest) not in paths and not path.is_file():
            continue
        reader = readers[manifest]
        dependencies.extend(reader(path))
    return sorted(set(dependencies), key=str.casefold)
