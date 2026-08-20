"""Build a small, explainable repository fact index without executing code."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None  # type: ignore[assignment]

from .repository import iter_project_files


FRAMEWORK_ALIASES = {
    "django": "django",
    "fastapi": "fastapi",
    "flask": "flask",
    "express": "express",
    "next.js": "next",
    "nextjs": "next",
    "react": "react",
    "svelte": "svelte",
    "vue": "vue",
    "spring boot": "spring-boot",
}


def normalize_dependency(value: str) -> str:
    """Normalize common package-manager spellings to a comparison key."""

    normalized = value.strip().strip("`'\"(),.;:")
    if normalized.startswith("@"):
        scoped_match = re.match(r"(@[^/]+/[^@]+)(?:@.*)?$", normalized)
        if scoped_match:
            normalized = scoped_match.group(1)
        normalized = re.split(r"\s*(?:==|~=|>=|<=|>|<|\^|~)\s*", normalized, maxsplit=1)[0]
    else:
        normalized = re.split(r"\s*(?:==|~=|>=|<=|>|<|\^|~|@)\s*", normalized, maxsplit=1)[0]
    normalized = normalized.split("[")[0]
    return normalized.casefold().replace("_", "-")


@dataclass
class RepositoryFacts:
    """Facts discovered from files and manifests in a local repository."""

    files: set[str] = field(default_factory=set)
    modules: set[str] = field(default_factory=set)
    symbols: set[str] = field(default_factory=set)
    dependencies: dict[str, str | None] = field(default_factory=dict)
    manifests: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    def has_symbol(self, reference: str) -> bool:
        normalized = reference.strip().replace("::", ".")
        if normalized in self.symbols:
            return True
        if "." in normalized:
            return False
        return normalized.rsplit(".", 1)[-1] in self.symbols

    def has_module(self, reference: str) -> bool:
        normalized = reference.strip().replace("/", ".").replace("\\", ".")
        normalized = re.sub(r"\.(?:py|js|jsx|ts|tsx|go|rs)$", "", normalized)
        return normalized in self.modules or normalize_dependency(normalized) in self.dependencies

    def has_dependency(self, reference: str) -> bool:
        return normalize_dependency(reference) in self.dependencies


class _PythonSymbolVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: set[str] = set()
        self._classes: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.add(node.name)
        self._classes.append(node.name)
        for child in node.body:
            self.visit(child)
        self._classes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._add_function(node.name)
        for child in node.body:
            self.visit(child)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._add_function(node.name)
        for child in node.body:
            self.visit(child)

    def _add_function(self, name: str) -> None:
        self.symbols.add(name)
        if self._classes:
            self.symbols.add(f"{self._classes[-1]}.{name}")


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096] or len(raw) > 512_000:
        return None
    return raw.decode("utf-8", errors="replace")


def _add_python_symbols(facts: RepositoryFacts, content: str) -> None:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        facts.notes.append("A Python file could not be parsed; its symbols were skipped.")
        return
    visitor = _PythonSymbolVisitor()
    visitor.visit(tree)
    facts.symbols.update(visitor.symbols)


def _add_regex_symbols(facts: RepositoryFacts, content: str, suffix: str) -> None:
    patterns = [
        r"\b(?:class|interface|struct|trait|enum|type)\s+([A-Za-z_$][\w$]*)",
        r"\b(?:export\s+(?:default\s+)?)?(?:function|fn|func)\s+([A-Za-z_$][\w$]*)",
        r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
    ]
    for pattern in patterns:
        facts.symbols.update(match.group(1) for match in re.finditer(pattern, content))

    class_matches = re.finditer(
        r"\bclass\s+([A-Za-z_$][\w$]*)[^\{]*\{(?P<body>.*?)\}",
        content,
        flags=re.DOTALL,
    )
    for match in class_matches:
        class_name = match.group(1)
        for method in re.finditer(
            r"(?:^|[;{}\n])\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\(",
            match.group("body"),
        ):
            facts.symbols.add(f"{class_name}.{method.group(1)}")

    if suffix == ".go":
        facts.symbols.update(
            match.group(1)
            for match in re.finditer(r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(", content)
        )


def _dependency_name_and_version(value: object) -> tuple[str | None, str | None]:
    if isinstance(value, str):
        match = re.match(r"\s*([@A-Za-z0-9_.\-/]+)\s*(.*)$", value)
        if not match:
            return None, None
        return normalize_dependency(match.group(1)), match.group(2).strip() or None
    return None, None


def _add_dependency(facts: RepositoryFacts, name: str | None, version: str | None) -> None:
    if not name or name in {"python", "node", "rust", "go"}:
        return
    facts.dependencies.setdefault(name, version)


def _add_package_json(facts: RepositoryFacts, path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        facts.notes.append("package.json could not be parsed; dependency checks may be incomplete.")
        return
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        values = data.get(section, {})
        if isinstance(values, dict):
            for name, version in values.items():
                _add_dependency(facts, normalize_dependency(str(name)), str(version))


def _add_toml_dependencies(facts: RepositoryFacts, path: Path, data: dict[str, object]) -> None:
    if path.name == "Cargo.toml":
        values = data.get("dependencies", {})
        if isinstance(values, dict):
            for name, value in values.items():
                version = value if isinstance(value, str) else None
                _add_dependency(facts, normalize_dependency(str(name)), version)
        return

    project = data.get("project", {})
    if isinstance(project, dict):
        dependencies = project.get("dependencies", [])
        if isinstance(dependencies, list):
            for item in dependencies:
                name, version = _dependency_name_and_version(item)
                _add_dependency(facts, name, version)
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for items in optional.values():
                if isinstance(items, list):
                    for item in items:
                        name, version = _dependency_name_and_version(item)
                        _add_dependency(facts, name, version)

    tool = data.get("tool", {})
    if isinstance(tool, dict):
        poetry = tool.get("poetry", {})
        if isinstance(poetry, dict):
            values = poetry.get("dependencies", {})
            if isinstance(values, dict):
                for name, value in values.items():
                    _add_dependency(facts, normalize_dependency(str(name)), str(value))
            groups = poetry.get("group", {})
            if isinstance(groups, dict):
                for group in groups.values():
                    if isinstance(group, dict) and isinstance(group.get("dependencies"), dict):
                        for name, value in group["dependencies"].items():
                            _add_dependency(facts, normalize_dependency(str(name)), str(value))


def _add_manifest_dependencies(facts: RepositoryFacts, relative: str, path: Path) -> None:
    facts.manifests.add(relative)
    if path.name == "package.json":
        _add_package_json(facts, path)
        return
    if path.name in {"pyproject.toml", "Cargo.toml"}:
        if tomllib is None:
            facts.notes.append(f"{relative} requires tomllib for complete dependency checks.")
            return
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            facts.notes.append(f"{relative} could not be parsed; dependency checks may be incomplete.")
            return
        _add_toml_dependencies(facts, path, data)
        return
    if path.name == "go.mod":
        content = _read_text(path) or ""
        for match in re.finditer(r"^\s*([A-Za-z0-9_.\-/]+)\s+v?([0-9][^\s)]*)", content, re.MULTILINE):
            _add_dependency(facts, match.group(1), match.group(2))


def _add_modules(facts: RepositoryFacts, relative: str) -> None:
    path = Path(relative)
    suffix = path.suffix.lower()
    if suffix not in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs"}:
        return
    without_suffix = path.with_suffix("").as_posix().replace("/", ".")
    facts.modules.add(without_suffix)
    facts.modules.add(path.stem)
    if path.name.startswith("__init__."):
        facts.modules.add(path.parent.as_posix().replace("/", "."))


def build_repository_facts(repo: str | Path = ".") -> RepositoryFacts:
    """Scan source files and supported manifests without executing project code."""

    facts = RepositoryFacts()
    for relative, path in iter_project_files(repo):
        facts.files.add(relative)
        _add_modules(facts, relative)
        if path.name in {"package.json", "pyproject.toml", "Cargo.toml", "go.mod"}:
            _add_manifest_dependencies(facts, relative, path)
        content = _read_text(path)
        if content is None:
            continue
        suffix = path.suffix.lower()
        if suffix == ".py":
            _add_python_symbols(facts, content)
        elif suffix in {".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".cs", ".c", ".cpp", ".h"}:
            _add_regex_symbols(facts, content, suffix)
    return facts
