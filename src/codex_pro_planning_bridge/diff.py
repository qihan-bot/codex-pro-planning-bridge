"""Compare implementation steps in PLAN.md with local Git changes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from pathlib import Path

from .repository import git_changed_files, resolve_repo, resolve_repo_path, run_git, write_text
from .validator import extract_path_references


TASK_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<body>.+?)\s*$")
CHECKBOX_RE = re.compile(r"^\s*\[[ xX]\]\s*")
BLOCKED_RE = re.compile(
    r"\b(blocked|blocker|cannot|can't|waiting for|needs clarification|unavailable|dependency pending)\b",
    re.IGNORECASE,
)
IMPLEMENTATION_HEADINGS = ("implementation", "execution", "tasks", "work items")


@dataclass(frozen=True)
class PlanTask:
    index: int
    text: str
    references: tuple[str, ...] = ()
    checked: bool = False


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
    completed: list[DiffEntry] = field(default_factory=list)
    missing: list[DiffEntry] = field(default_factory=list)
    changed: list[DiffEntry] = field(default_factory=list)
    blocked: list[DiffEntry] = field(default_factory=list)
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
            "completed": [asdict(item) for item in self.completed],
            "missing": [asdict(item) for item in self.missing],
            "changed": [asdict(item) for item in self.changed],
            "blocked": [asdict(item) for item in self.blocked],
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


def compare_plan(
    repo: str | Path,
    markdown: str,
    *,
    plan_path: str | Path = ".codex/pro-plan/PLAN.md",
    base: str | None = None,
    changed_files: list[str] | None = None,
) -> PlanDiffResult:
    """Classify plan tasks against a supplied or locally detected change set."""

    root = resolve_repo(repo)
    resolved_plan = resolve_repo_path(root, plan_path)
    tasks = extract_plan_tasks(markdown)
    source_files = changed_files if changed_files is not None else git_changed_files(root, base=base)
    actual = sorted({path.replace("\\", "/") for path in source_files})
    actual_set = set(actual)
    result = PlanDiffResult(
        plan_path=resolved_plan,
        base=base,
        changed_files=actual,
        tasks=tasks,
    )
    if run_git(root, ("rev-parse", "--git-dir")) is None:
        result.notes.append("Git metadata unavailable; no repository diff could be computed.")
    elif not actual:
        result.notes.append(
            "No changed files detected. Pass --base <commit> to compare an implementation range."
        )

    planned_files: set[str] = set()
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

    result.unplanned_changes = sorted(actual_set - planned_files)
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
        "",
        "## Changed Files",
        "",
    ]
    if result.changed_files:
        lines.extend(f"- `{path}`" for path in result.changed_files)
    else:
        lines.append("_None detected._")
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
    result = compare_plan(root, markdown, plan_path=plan_path, base=base)
    write_text(output_path, render_plan_diff(result))
    return output_path, result
