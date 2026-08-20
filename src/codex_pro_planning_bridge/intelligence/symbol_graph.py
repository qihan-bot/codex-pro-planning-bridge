"""Build and query a conservative local graph of repository relationships."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from ..repository import iter_project_files, write_text
from .symbol_index import SUPPORTED_SUFFIXES, Symbol, SymbolIndex, build_symbol_index


SYMBOL_GRAPH_SCHEMA_VERSION = 1
_CALL_RE = re.compile(
    r"\b([A-Za-z_$][\w$]*(?:(?:\s*\.\s*|\s*::\s*)[A-Za-z_$][\w$]*)*)\s*\("
)
_IMPORT_RE = re.compile(r"\b(?:from|import)\s+[\"']?([^\s\"';,]+)")
_JS_IMPORT_RE = re.compile(
    r"\b(?:from|import)\s+[\"']([^\"']+)[\"']|\brequire\(\s*[\"']([^\"']+)[\"']\s*\)"
)
_RUST_USE_RE = re.compile(r"^\s*use\s+([^;]+);", re.MULTILINE)
_CALL_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "with",
    "def",
    "class",
    "function",
    "fn",
    "func",
}


@dataclass(frozen=True)
class GraphNode:
    """A file, symbol, or external dependency in the local graph."""

    node_id: str
    kind: str
    name: str
    path: str | None = None
    qualified_name: str | None = None
    language: str | None = None
    parent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GraphEdge:
    """A directed, explainable relationship between two graph nodes."""

    source: str
    target: str
    kind: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class SymbolGraph:
    """Serializable graph with deterministic local relationship queries."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    schema_version: int = SYMBOL_GRAPH_SCHEMA_VERSION

    def find_nodes(self, reference: str) -> list[GraphNode]:
        target = reference.strip().replace("::", ".").strip(".`")
        if not target:
            return []
        folded = target.casefold()
        matches = [
            node
            for node in self.nodes
            if node.node_id.casefold() == folded
            or (node.qualified_name or "").replace("::", ".").casefold() == folded
            or node.name.casefold() == folded
            or (node.path or "").casefold() == folded
            or (node.qualified_name or "").replace("::", ".").casefold().endswith(f".{folded}")
        ]
        return sorted(matches, key=lambda item: (item.kind, item.path or "", item.node_id))

    def relationships(
        self,
        reference: str,
        *,
        kind: str | None = None,
        direction: str = "out",
    ) -> list[GraphEdge]:
        """Return graph edges touching a symbol or node reference."""

        node_ids = {node.node_id for node in self.find_nodes(reference)}
        if not node_ids:
            return []
        relation = kind.casefold() if kind else None
        normalized_direction = direction.casefold()
        if normalized_direction not in {"out", "in", "both"}:
            raise ValueError("direction must be one of: out, in, both")
        result = []
        for edge in self.edges:
            if relation and edge.kind.casefold() != relation:
                continue
            outgoing = edge.source in node_ids
            incoming = edge.target in node_ids
            if (
                (normalized_direction == "out" and outgoing)
                or (normalized_direction == "in" and incoming)
                or (normalized_direction == "both" and (outgoing or incoming))
            ):
                result.append(edge)
        return sorted(result, key=lambda item: (item.kind, item.source, item.target))

    def related(
        self,
        reference: str,
        *,
        kind: str | None = None,
        direction: str = "out",
    ) -> list[GraphNode]:
        """Resolve neighboring nodes for a local relationship query."""

        node_ids = {node.node_id for node in self.find_nodes(reference)}
        normalized_direction = direction.casefold()
        result_ids: set[str] = set()
        for edge in self.relationships(reference, kind=kind, direction=direction):
            if normalized_direction == "in":
                result_ids.add(edge.source)
            elif normalized_direction == "both":
                result_ids.update({edge.source, edge.target} - node_ids)
            else:
                result_ids.add(edge.target)
        return sorted(
            (node for node in self.nodes if node.node_id in result_ids),
            key=lambda item: (item.kind, item.path or "", item.node_id),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "nodes": [
                node.to_dict()
                for node in sorted(self.nodes, key=lambda item: (item.kind, item.node_id))
            ],
            "edges": [
                edge.to_dict()
                for edge in sorted(self.edges, key=lambda item: (item.kind, item.source, item.target))
            ],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SymbolGraph":
        schema_version = int(value.get("schema_version", SYMBOL_GRAPH_SCHEMA_VERSION))
        if schema_version > SYMBOL_GRAPH_SCHEMA_VERSION:
            raise ValueError(
                f"symbol graph schema {schema_version} is newer than supported schema "
                f"{SYMBOL_GRAPH_SCHEMA_VERSION}"
            )
        nodes = [
            GraphNode(
                node_id=str(item.get("node_id", "")),
                kind=str(item.get("kind", "symbol")),
                name=str(item.get("name", "")),
                path=(str(item["path"]) if item.get("path") else None),
                qualified_name=(
                    str(item["qualified_name"]) if item.get("qualified_name") else None
                ),
                language=(str(item["language"]) if item.get("language") else None),
                parent=(str(item["parent"]) if item.get("parent") else None),
            )
            for item in value.get("nodes", [])
            if isinstance(item, dict)
        ]
        edges = [
            GraphEdge(
                source=str(item.get("source", "")),
                target=str(item.get("target", "")),
                kind=str(item.get("kind", "RELATED")),
            )
            for item in value.get("edges", [])
            if isinstance(item, dict)
        ]
        return cls(nodes=nodes, edges=edges, schema_version=SYMBOL_GRAPH_SCHEMA_VERSION)


def _file_id(path: str) -> str:
    return f"file:{path}"


def _symbol_id(symbol: Symbol) -> str:
    return f"symbol:{symbol.path}:{symbol.qualified_name}:{symbol.kind}"


def _dependency_id(value: str) -> str:
    return f"dependency:{value}"


def _dependencies(relative: str, content: str) -> list[str]:
    suffix = Path(relative).suffix.lower()
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return sorted({match.group(1) or match.group(2) for match in _JS_IMPORT_RE.finditer(content)})
    if suffix == ".rs":
        return sorted({match.group(1).strip() for match in _RUST_USE_RE.finditer(content)})
    return sorted({match.group(1) for match in _IMPORT_RE.finditer(content)})


def _line_number(content: str, position: int) -> int:
    return content.count("\n", 0, position) + 1


def _enclosing_symbol(symbols: list[Symbol], line: int) -> Symbol | None:
    candidates = [
        symbol
        for symbol in symbols
        if symbol.line <= line and symbol.kind in {"function", "method"}
    ]
    return max(candidates, key=lambda item: (item.line, len(item.qualified_name))) if candidates else None


def _call_targets(index: SymbolIndex, token: str) -> list[Symbol]:
    normalized = re.sub(r"\s*([.:]{1,2})\s*", r"\1", token)
    matches = index.find(normalized)
    if matches:
        return matches
    leaf = re.split(r"[.:]+", normalized)[-1]
    return index.find(leaf)


def _add_node(nodes: dict[str, GraphNode], node: GraphNode) -> None:
    nodes.setdefault(node.node_id, node)


def _add_edge(edges: set[tuple[str, str, str]], source: str, target: str, kind: str) -> None:
    if source != target:
        edges.add((source, target, kind))


def build_symbol_graph(repo: str | Path = ".", *, index: SymbolIndex | None = None) -> SymbolGraph:
    """Build a local file/symbol/dependency graph without executing project code."""

    root = Path(repo).resolve()
    symbol_index = index or build_symbol_index(root)
    symbols_by_path: dict[str, list[Symbol]] = {}
    for symbol in symbol_index.symbols:
        symbols_by_path.setdefault(symbol.path, []).append(symbol)

    nodes: dict[str, GraphNode] = {}
    edges: set[tuple[str, str, str]] = set()
    for relative, path in iter_project_files(root):
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        file_node_id = _file_id(relative)
        _add_node(nodes, GraphNode(file_node_id, "file", path.name, path=relative))
        file_symbols = symbols_by_path.get(relative, [])
        by_parent: dict[tuple[str, str], str] = {}
        for symbol in file_symbols:
            node_id = _symbol_id(symbol)
            _add_node(
                nodes,
                GraphNode(
                    node_id,
                    symbol.kind,
                    symbol.name,
                    path=symbol.path,
                    qualified_name=symbol.qualified_name,
                    language=symbol.language,
                    parent=symbol.parent,
                ),
            )
            _add_edge(edges, file_node_id, node_id, "CONTAINS")
            by_parent.setdefault((symbol.name, symbol.kind), node_id)
        for symbol in file_symbols:
            if symbol.parent:
                parent_id = next(
                    (
                        candidate.node_id
                        for candidate in nodes.values()
                        if candidate.path == relative
                        and candidate.name == symbol.parent
                        and candidate.kind in {"class", "struct", "trait", "enum"}
                    ),
                    None,
                )
                if parent_id:
                    _add_edge(edges, parent_id, _symbol_id(symbol), "OWNS")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for dependency in _dependencies(relative, content):
            dependency_node_id = _dependency_id(dependency)
            _add_node(nodes, GraphNode(dependency_node_id, "dependency", dependency))
            _add_edge(edges, file_node_id, dependency_node_id, "IMPORTS")
        for match in _CALL_RE.finditer(content):
            token = match.group(1).strip()
            leaf = re.split(r"[.:]+", token)[-1]
            if leaf.casefold() in _CALL_KEYWORDS:
                continue
            line = _line_number(content, match.start())
            prefix = content[max(0, match.start() - 20):match.start()]
            if re.search(r"\b(?:def|class|function|fn|func)\s*$", prefix):
                continue
            source_symbol = _enclosing_symbol(file_symbols, line)
            if source_symbol is None:
                continue
            for target_symbol in _call_targets(symbol_index, token):
                _add_edge(edges, _symbol_id(source_symbol), _symbol_id(target_symbol), "CALLS")

    return SymbolGraph(
        nodes=list(nodes.values()),
        edges=[GraphEdge(source, target, kind) for source, target, kind in sorted(edges)],
    )


def export_symbol_graph(graph: SymbolGraph, path: str | Path) -> Path:
    """Write a deterministic machine-readable graph snapshot."""

    return write_text(
        Path(path),
        json.dumps(graph.to_dict(), indent=2, ensure_ascii=False),
    )


def load_symbol_graph(path: str | Path) -> SymbolGraph:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"symbol graph does not exist: {source}")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid symbol graph: {source}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"symbol graph must be a JSON object: {source}")
    return SymbolGraph.from_dict(value)


__all__ = [
    "GraphEdge",
    "GraphNode",
    "SYMBOL_GRAPH_SCHEMA_VERSION",
    "SymbolGraph",
    "build_symbol_graph",
    "export_symbol_graph",
    "load_symbol_graph",
]
