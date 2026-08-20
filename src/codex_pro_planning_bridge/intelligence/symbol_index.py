"""Build a small local symbol and dependency index without executing code.

The index intentionally uses standard-library parsers and conservative regular
expressions.  It is repository evidence for planning and validation, not a
compiler and not an attempt to infer runtime behavior.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from ..repository import iter_project_files, write_text


SYMBOL_INDEX_SCHEMA_VERSION = 1
SUPPORTED_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".rs"}


@dataclass(frozen=True)
class Symbol:
    """One statically discovered class, function, type, or method."""

    name: str
    qualified_name: str
    kind: str
    path: str
    line: int
    language: str
    parent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SymbolRecord = Symbol


@dataclass
class SymbolIndex:
    """Serializable symbol inventory for one repository snapshot."""

    symbols: list[Symbol] = field(default_factory=list)
    dependencies: set[str] = field(default_factory=set)
    schema_version: int = SYMBOL_INDEX_SCHEMA_VERSION

    @property
    def files(self) -> list[str]:
        return sorted({item.path for item in self.symbols})

    def add(self, symbol: Symbol) -> None:
        if symbol not in self.symbols:
            self.symbols.append(symbol)

    def add_dependency(self, value: str) -> None:
        normalized = value.strip()
        if normalized:
            self.dependencies.add(normalized)

    def find(self, reference: str) -> list[Symbol]:
        """Find exact or suffix-qualified matches for a plan reference."""

        target = reference.strip().replace("::", ".").strip(".`")
        if not target:
            return []
        folded = target.casefold()
        matches = [
            item
            for item in self.symbols
            if item.qualified_name.replace("::", ".").casefold() == folded
            or item.name.casefold() == folded
            or item.qualified_name.replace("::", ".").casefold().endswith(f".{folded}")
        ]
        return sorted(matches, key=lambda item: (item.path, item.line, item.qualified_name))

    def possible_matches(self, reference: str, *, limit: int = 3) -> list[str]:
        """Return deterministic suffix/substring suggestions for a missing symbol."""

        target = reference.strip().replace("::", ".").casefold()
        leaf = target.rsplit(".", 1)[-1]
        candidates = sorted(
            {item.qualified_name for item in self.symbols},
            key=str.casefold,
        )
        ranked = sorted(
            candidates,
            key=lambda value: (
                0 if value.casefold().endswith(f".{leaf}") else 1,
                0 if leaf in value.casefold() else 1,
                value.casefold(),
            ),
        )
        return [value for value in ranked if leaf in value.casefold()][:limit]

    def locations(self) -> dict[str, set[str]]:
        locations: dict[str, set[str]] = {}
        for symbol in self.symbols:
            locations.setdefault(symbol.qualified_name, set()).add(symbol.path)
        return locations

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "files": self.files,
            "dependencies": sorted(self.dependencies),
            "symbols": [item.to_dict() for item in sorted(self.symbols, key=_symbol_sort_key)],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SymbolIndex":
        symbols: list[Symbol] = []
        for item in value.get("symbols", []):
            if not isinstance(item, dict):
                continue
            try:
                symbols.append(
                    Symbol(
                        name=str(item.get("name", "")),
                        qualified_name=str(item.get("qualified_name", item.get("name", ""))),
                        kind=str(item.get("kind", "symbol")),
                        path=str(item.get("path", "")),
                        line=int(item.get("line", 0)),
                        language=str(item.get("language", "text")),
                        parent=(str(item["parent"]) if item.get("parent") else None),
                    )
                )
            except (TypeError, ValueError):
                continue
        return cls(
            symbols=symbols,
            dependencies={str(item) for item in value.get("dependencies", [])},
            schema_version=int(value.get("schema_version", SYMBOL_INDEX_SCHEMA_VERSION)),
        )


def _symbol_sort_key(item: Symbol) -> tuple[str, int, str, str]:
    return (item.path, item.line, item.qualified_name, item.kind)


def _module_name(relative: str) -> str:
    path = Path(relative)
    without_suffix = path.with_suffix("").as_posix().replace("/", ".")
    if without_suffix.endswith(".__init__"):
        without_suffix = without_suffix[: -len(".__init__")]
    return without_suffix


def _language(path: Path) -> str:
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".rs": "rust",
    }.get(path.suffix.lower(), "text")


def _safe_read(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > 1_000_000 or b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace")


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, index: SymbolIndex, relative: str, module: str) -> None:
        self.index = index
        self.relative = relative
        self.module = module
        self.parents: list[str] = []

    def _add(self, name: str, kind: str, line: int) -> None:
        qualified_parts = [part for part in (self.module, *self.parents, name) if part]
        self.index.add(
            Symbol(
                name=name,
                qualified_name=".".join(qualified_parts),
                kind=kind,
                path=self.relative,
                line=line,
                language="python",
                parent=self.parents[-1] if self.parents else None,
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add(node.name, "class", node.lineno)
        self.parents.append(node.name)
        for child in node.body:
            self.visit(child)
        self.parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._add(node.name, "method" if self.parents else "function", node.lineno)
        self.parents.append(node.name)
        for child in node.body:
            self.visit(child)
        self.parents.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]


def _add_python(index: SymbolIndex, relative: str, content: str) -> None:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return
    _PythonVisitor(index, relative, _module_name(relative)).visit(tree)
    for match in re.finditer(r"^\s*(?:from\s+([\w.]+)|import\s+([\w.]+))", content, re.MULTILINE):
        index.add_dependency(match.group(1) or match.group(2) or "")


def _matching_brace(content: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(content)):
        if content[index] == "{":
            depth += 1
        elif content[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(content)


def _line_number(content: str, position: int) -> int:
    return content.count("\n", 0, position) + 1


def _add_js(index: SymbolIndex, relative: str, content: str, language: str) -> None:
    module = _module_name(relative)
    classes: list[tuple[str, int, str]] = []
    for match in re.finditer(r"\bclass\s+([A-Za-z_$][\w$]*)\s*\{", content):
        class_name = match.group(1)
        classes.append((class_name, match.end() - 1, module))
        index.add(
            Symbol(
                name=class_name,
                qualified_name=f"{module}.{class_name}" if module else class_name,
                kind="class",
                path=relative,
                line=_line_number(content, match.start()),
                language=language,
            )
        )
        closing = _matching_brace(content, match.end() - 1)
        body = content[match.end():closing]
        for method in re.finditer(
            r"(?:^|[;{}\n])\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\(", body
        ):
            name = method.group(1)
            qualified = f"{module}.{class_name}.{name}" if module else f"{class_name}.{name}"
            index.add(
                Symbol(
                    name=name,
                    qualified_name=qualified,
                    kind="method",
                    path=relative,
                    line=_line_number(content, match.end() + method.start()),
                    language=language,
                    parent=class_name,
                )
            )
    class_spans = [
        (opening, _matching_brace(content, opening), name)
        for name, opening, _ in classes
    ]
    for match in re.finditer(
        r"\b(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
        content,
    ):
        if any(start <= match.start() <= end for start, end, _ in class_spans):
            continue
        name = match.group(1)
        index.add(
            Symbol(
                name=name,
                qualified_name=f"{module}.{name}" if module else name,
                kind="function",
                path=relative,
                line=_line_number(content, match.start()),
                language=language,
            )
        )
    for match in re.finditer(
        r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(",
        content,
    ):
        name = match.group(1)
        index.add(
            Symbol(
                name=name,
                qualified_name=f"{module}.{name}" if module else name,
                kind="function",
                path=relative,
                line=_line_number(content, match.start()),
                language=language,
            )
        )
    for match in re.finditer(r"\b(?:from|import)\s+[\"']([^\"']+)[\"']|\bfrom\s+[\"']([^\"']+)[\"']", content):
        index.add_dependency(match.group(1) or match.group(2) or "")
    for match in re.finditer(r"\brequire\(\s*[\"']([^\"']+)[\"']\s*\)", content):
        index.add_dependency(match.group(1))


def _add_rust(index: SymbolIndex, relative: str, content: str) -> None:
    module = _module_name(relative)
    for pattern, kind in (
        (r"\b(?:pub\s+)?struct\s+([A-Za-z_]\w*)", "struct"),
        (r"\b(?:pub\s+)?enum\s+([A-Za-z_]\w*)", "enum"),
        (r"\b(?:pub\s+)?trait\s+([A-Za-z_]\w*)", "trait"),
        (r"\b(?:pub\s+)?type\s+([A-Za-z_]\w*)", "type"),
    ):
        for match in re.finditer(pattern, content):
            name = match.group(1)
            index.add(
                Symbol(
                    name=name,
                    qualified_name=f"{module}::{name}" if module else name,
                    kind=kind,
                    path=relative,
                    line=_line_number(content, match.start()),
                    language="rust",
                )
            )
    for impl in re.finditer(r"\bimpl(?:<[^>]+>)?\s+([A-Za-z_]\w*)[^\{]*\{", content):
        parent = impl.group(1)
        closing = _matching_brace(content, impl.end() - 1)
        body = content[impl.end():closing]
        for match in re.finditer(r"\b(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)", body):
            name = match.group(1)
            index.add(
                Symbol(
                    name=name,
                    qualified_name=f"{module}::{parent}::{name}" if module else f"{parent}::{name}",
                    kind="method",
                    path=relative,
                    line=_line_number(content, impl.end() + match.start()),
                    language="rust",
                    parent=parent,
                )
            )
    for match in re.finditer(r"\b(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)", content):
        if any(item.name == match.group(1) and item.path == relative for item in index.symbols):
            continue
        name = match.group(1)
        index.add(
            Symbol(
                name=name,
                qualified_name=f"{module}::{name}" if module else name,
                kind="function",
                path=relative,
                line=_line_number(content, match.start()),
                language="rust",
            )
        )
    for match in re.finditer(r"^\s*use\s+([^;]+);", content, re.MULTILINE):
        index.add_dependency(match.group(1).strip())


def build_symbol_index(repo: str | Path = ".") -> SymbolIndex:
    """Build a local index for Python, JavaScript/TypeScript, and Rust files."""

    index = SymbolIndex()
    for relative, path in iter_project_files(repo):
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            continue
        content = _safe_read(path)
        if content is None:
            continue
        if suffix == ".py":
            _add_python(index, relative, content)
        elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
            _add_js(index, relative, content, _language(path))
        else:
            _add_rust(index, relative, content)
    index.symbols.sort(key=_symbol_sort_key)
    return index


def export_symbol_index(index: SymbolIndex, path: str | Path) -> Path:
    """Write a deterministic machine-readable symbol snapshot."""

    return write_text(
        Path(path),
        json.dumps(index.to_dict(), indent=2, ensure_ascii=False),
    )


def load_symbol_index(path: str | Path) -> SymbolIndex:
    """Load a previously exported symbol snapshot."""

    source = Path(path)
    if not source.is_file():
        raise ValueError(f"symbol index does not exist: {source}")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid symbol index: {source}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"symbol index must be a JSON object: {source}")
    return SymbolIndex.from_dict(value)


__all__ = [
    "SUPPORTED_SUFFIXES",
    "Symbol",
    "SymbolIndex",
    "SymbolRecord",
    "build_symbol_index",
    "export_symbol_index",
    "load_symbol_index",
]
