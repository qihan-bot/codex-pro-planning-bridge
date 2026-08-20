"""Compare implementation steps in PLAN.md with local Git changes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from pathlib import Path

from .intelligence.symbol_index import SymbolIndex, build_symbol_index, load_symbol_index
from .models import FileChange, PlanTask, ProjectContext, SymbolChange
from .repository import git_file_changes, resolve_repo, resolve_repo_path, run_git, write_text
from .validator import extract_path_references


TASK_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<body>.+?)\s*$")
CHECKBOX_RE = re.compile(r"^\s*\[[ xX]\]\s*")
BLOCKED_RE = re.compile(
    r"\b(blocked|blocker|cannot|can't|waiting for|needs clarification|unavailable|dependency pending)\b",
    re.IGNORECASE,
)
IMPLEMENTATION_HEADINGS = ("implementation", "execution", "tasks", "work items")


@dataclass(frozen=True)
class DiffEntry:
    task: str
    detail: str
    references: tuple[str, ...] = ()


@dataclass
class PlanDiffResult:
    plan_path: Path
    base: str | None
    changed_files: list[str]
    tasks: list[PlanTask]
    context_available: bool = False
    completed: list[DiffEntry] = field(default_factory=list)
    missing: list[DiffEntry] = field(default_factory=list)
    changed: list[DiffEntry] = field(default_factory=list)
    blocked: list[DiffEntry] = field(default_factory=list)
    renamed_files: list[FileChange] = field(default_factory=list)
    symbol_changes: list[SymbolChange] = field(default_factory=list)
    unplanned_changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing or self.changed or self.blocked or self.unplanned_changes)

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_path": str(self.plan_path),
            "base": self.base,
            "changed_files": self.changed_files,
            "tasks": [asdict(task) for task in self.tasks],
            "context_available": self.context_available,
            "completed": [asdict(item) for item in self.completed],
            "missing": [asdict(item) for item in self.missing],
            "changed": [asdict(item) for item in self.changed],
            "blocked": [asdict(item) for item in self.blocked],
            "renamed_files": [asdict(item) for item in self.renamed_files],
            "symbol_changes": [asdict(item) for item in self.symbol_changes],
            "unplanned_changes": self.unplanned_changes,
            "notes": self.notes,
            "ok": self.ok,
        }


def _implementation_section(markdown: str) -> str:
    headings = list(re.finditer(r"^(#{1,6})\s+(.+?)\s*$", markdown, re.MULTILINE))
    for index, heading in enumerate(headings):
        title = heading.group(2).casefold()
        if not any(keyword in title for keyword in IMPLEMENTATION_HEADINGS):
            continue
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        return markdown[start:end]
    return markdown


def extract_plan_tasks(markdown: str) -> list[PlanTask]:
    """Extract ordered implementation tasks and their explicit file references."""

    tasks: list[PlanTask] = []
    for line in _implementation_section(markdown).splitlines():
        match = TASK_RE.match(line)
        if not match:
            continue
        raw_text = match.group("body").strip()
        checked = bool(re.match(r"^\[[xX]\]\s*", raw_text))
        text = CHECKBOX_RE.sub("", raw_text).strip()
        if not text:
            continue
        tasks.append(
            PlanTask(
                index=len(tasks) + 1,
                text=text,
                references=tuple(extract_path_references(text)),
                checked=checked,
            )
        )
    return tasks


def _entry(task: PlanTask, detail: str) -> DiffEntry:
    return DiffEntry(task=f"Step {task.index}: {task.text}", detail=detail, references=task.references)


def _is_bridge_artifact(path: str) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized == ".codex" or normalized.startswith(".codex/")


def _compare_symbol_indexes(
    before: SymbolIndex | None,
    after: SymbolIndex | None,
) -> list[SymbolChange]:
    if before is None or after is None:
        return []
    before_locations = before.locations()
    after_locations = after.locations()
    changes: list[SymbolChange] = []
    for name in sorted(set(before_locations) | set(after_locations), key=str.casefold):
        old_paths = tuple(sorted(before_locations.get(name, set())))
        new_paths = tuple(sorted(after_locations.get(name, set())))
        if old_paths == new_paths:
            continue
        if not old_paths:
            kind = "added"
        elif not new_paths:
            kind = "removed"
        else:
            kind = "moved"
        changes.append(
            SymbolChange(
                name=name,
                kind=kind,
                before_paths=old_paths,
                after_paths=new_paths,
            )
        )
    return changes


def compare_plan(
    repo: str | Path,
    markdown: str,
    *,
    plan_path: str | Path = ".codex/pro-plan/PLAN.md",
    base: str | None = None,
    changed_files: list[str] | None = None,
    file_changes: list[FileChange] | None = None,
    context: ProjectContext | None = None,
    baseline_symbol_index: SymbolIndex | None = None,
    current_symbol_index: SymbolIndex | None = None,
    symbol_index: SymbolIndex | None = None,
) -> PlanDiffResult:
    """Classify plan tasks against a supplied or locally detected change set."""

    root = resolve_repo(repo)
    resolved_plan = resolve_repo_path(root, plan_path)
    tasks = extract_plan_tasks(markdown)
    if file_changes is not None:
        source_changes = file_changes
    elif changed_files is not None:
        source_changes = git_file_changes(root, base=base)
    else:
        source_changes = [
            item
            for item in git_file_changes(root, base=base)
            if not _is_bridge_artifact(item.path)
            and not (item.previous_path and _is_bridge_artifact(item.previous_path))
        ]
    source_files = changed_files if changed_files is not None else [item.path for item in source_changes]
    actual = sorted({path.replace("\\", "/") for path in source_files})
    actual_set = set(actual)
    current_symbols = current_symbol_index or symbol_index
    if current_symbols is None and baseline_symbol_index is not None:
        current_symbols = build_symbol_index(root)
    result = PlanDiffResult(
        plan_path=resolved_plan,
        base=base,
        changed_files=actual,
        tasks=tasks,
        context_available=context is not None,
        renamed_files=[item for item in source_changes if item.previous_path],
        symbol_changes=_compare_symbol_indexes(baseline_symbol_index, current_symbols),
    )
    if run_git(root, ("rev-parse", "--git-dir")) is None:
        result.notes.append("Git metadata unavailable; no repository diff could be computed.")
    elif not actual:
        result.notes.append(
            "No changed files detected. Pass --base <commit> to compare an implementation range."
        )
    if context is not None:
        result.notes.append(
            "Machine-readable context snapshot loaded before comparing repository changes."
        )

    planned_files: set[str] = set()
    rename_targets: dict[str, str] = {
        item.previous_path: item.path
        for item in result.renamed_files
        if item.previous_path
    }
    for task in tasks:
        planned_files.update(task.references)
        if BLOCKED_RE.search(task.text) and not task.checked:
            result.blocked.append(_entry(task, "task is explicitly blocked or waiting on an unresolved dependency"))
            continue
        if not task.references:
            if task.checked:
                result.completed.append(_entry(task, "marked complete in PLAN.md; no concrete path to verify"))
            else:
                result.missing.append(_entry(task, "task has no concrete repository path to verify"))
            continue
        renamed_references = [
            (reference, rename_targets[reference])
            for reference in task.references
            if reference in rename_targets
        ]
        if renamed_references:
            details = ", ".join(
                f"`{old}` → `{new}`" for old, new in renamed_references
            )
            result.changed.append(
                _entry(task, f"planned path was renamed locally: {details}")
            )
            continue
        touched = sorted(set(task.references) & actual_set)
        if task.checked and not touched:
            result.completed.append(_entry(task, "marked complete in PLAN.md"))
        elif len(touched) == len(task.references):
            result.completed.append(_entry(task, "all referenced paths changed locally"))
        elif touched:
            result.changed.append(
                _entry(task, f"partial implementation: changed {', '.join(touched)}; expected {', '.join(task.references)}")
            )
        else:
            result.missing.append(_entry(task, "none of the referenced paths changed locally"))

    planned_actual_files = planned_files | {
        new_path
        for old_path, new_path in rename_targets.items()
        if old_path in planned_files
    }
    result.unplanned_changes = sorted(actual_set - planned_actual_files)
    if result.unplanned_changes:
        result.notes.append("Changed paths not named by an implementation step are reported as drift.")
    if not tasks:
        result.notes.append("No implementation steps were found in PLAN.md.")
    return result


def _render_entries(title: str, entries: list[DiffEntry]) -> list[str]:
    lines = [f"## {title}", ""]
    if not entries:
        lines.append("_None._")
        return lines
    for item in entries:
        lines.extend([f"- **{item.task}** — {item.detail}"])
        if item.references:
            lines.append(f"  - References: {', '.join(f'`{path}`' for path in item.references)}")
    return lines


def render_plan_diff(result: PlanDiffResult) -> str:
    status = "ALIGNED" if result.ok else "DRIFT DETECTED"
    lines = [
        "# Plan Diff Report",
        "",
        f"- Status: **{status}**",
        f"- Plan: `{result.plan_path}`",
        f"- Baseline: `{result.base or 'working tree / HEAD'}`",
        f"- Changed files: `{len(result.changed_files)}`",
        f"- Plan tasks: `{len(result.tasks)}`",
        f"- Context snapshot: `{'available' if result.context_available else 'not available'}`",
        "",
        "## Changed Files",
        "",
    ]
    if result.changed_files:
        lines.extend(f"- `{path}`" for path in result.changed_files)
    else:
        lines.append("_None detected._")
    lines.extend(["", "## Renamed Files", ""])
    if result.renamed_files:
        lines.extend(
            f"- `{item.previous_path}` → `{item.path}`"
            + (f" ({item.similarity}% similar)" if item.similarity is not None else "")
            for item in result.renamed_files
        )
    else:
        lines.append("_None detected._")
    lines.extend([""])
    lines.extend(["## Symbol Changes", ""])
    if result.symbol_changes:
        for change in result.symbol_changes:
            before = ", ".join(f"`{path}`" for path in change.before_paths) or "—"
            after = ", ".join(f"`{path}`" for path in change.after_paths) or "—"
            lines.append(
                f"- `{change.name}` — **{change.kind}**; before: {before}; after: {after}"
            )
    else:
        lines.append("_None detected or no baseline symbol index was available._")
    lines.extend([""])
    lines.extend(_render_entries("Completed", result.completed))
    lines.extend([""])
    lines.extend(_render_entries("Missing", result.missing))
    lines.extend([""])
    lines.extend(_render_entries("Changed / Drift", result.changed))
    lines.extend([""])
    lines.extend(_render_entries("Blocked", result.blocked))
    lines.extend(["", "## Unplanned Changes", ""])
    if result.unplanned_changes:
        lines.extend(f"- `{path}`" for path in result.unplanned_changes)
    else:
        lines.append("_None._")
    if result.notes:
        lines.extend(["", "## Notes", "", *[f"- {note}" for note in result.notes]])
    return "\n".join(lines).rstrip() + "\n"


def diff_plan(
    repo: str | Path = ".",
    *,
    plan: str | Path = ".codex/pro-plan/PLAN.md",
    output: str | Path = ".codex/pro-plan/PLAN_DIFF.md",
    base: str | None = None,
) -> tuple[Path, PlanDiffResult]:
    """Read PLAN.md, compare it with local changes, and write PLAN_DIFF.md."""

    root = resolve_repo(repo)
    plan_path = resolve_repo_path(root, plan)
    output_path = resolve_repo_path(root, output)
    if not plan_path.is_file():
        raise ValueError(f"plan file does not exist: {plan_path}")
    markdown = plan_path.read_text(encoding="utf-8")
    context = None
    context_path = plan_path.parent / "context.json"
    context_error: str | None = None
    if context_path.is_file():
        try:
            value = json.loads(context_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                context = ProjectContext.from_dict(value)
        except (OSError, ValueError) as error:
            context_error = f"invalid context snapshot: {context_path}: {error}"
    baseline_symbol_index = None
    symbol_index_path = plan_path.parent / "symbol-index.json"
    if symbol_index_path.is_file():
        try:
            baseline_symbol_index = load_symbol_index(symbol_index_path)
        except ValueError as error:
            baseline_symbol_index = None
            # Keep the report useful while making an invalid baseline visible.
            result = compare_plan(
                root,
                markdown,
                plan_path=plan_path,
                base=base,
                context=context,
            )
            result.notes.append(str(error))
            if context_error:
                result.notes.append(context_error)
            write_text(output_path, render_plan_diff(result))
            return output_path, result
    result = compare_plan(
        root,
        markdown,
        plan_path=plan_path,
        base=base,
        context=context,
        baseline_symbol_index=baseline_symbol_index,
    )
    if context_error:
        result.notes.append(context_error)
    write_text(output_path, render_plan_diff(result))
    return output_path, result
