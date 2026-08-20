"""Compatibility artifact workflow for the local planning handoff."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .context import collect_repository
from .context.exporters import export_context_json
from .repository import (
    SUPPORTED_MANIFESTS,
    git_status,
    iter_project_files,
    resolve_repo,
    resolve_repo_path,
    write_text,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOAL = "Review this repository and propose the safest next implementation steps."


def collect_context(repo: str | Path = ".", output_dir: str | Path | None = None) -> dict[str, Path]:
    """Write the three local planning artifacts used by the Pro handoff."""

    root = resolve_repo(repo)
    destination = resolve_repo_path(root, output_dir) if output_dir is not None else root / ".codex" / "pro-plan"
    machine_context = collect_repository(root)
    files = iter_project_files(root)
    paths = [relative for relative, _ in files]
    manifests = set(paths)
    manifest_lines = [
        f"- [{'x' if manifest in manifests else ' '}] `{manifest}`"
        for manifest in SUPPORTED_MANIFESTS
    ]
    context = "\n".join(
        [
            "# Project Context",
            "",
            f"- Project: `{root.name or root}`",
            f"- Generated at: `{datetime.now(timezone.utc).isoformat()}`",
            f"- Files included in tree: `{len(paths)}`",
            "- Collection is local-only; no API or network upload is performed.",
            "",
            "## Recognized Project Manifests",
            "",
            *manifest_lines,
            "",
            "## Ignore Policy",
            "",
            "The collector excludes `.git`, `node_modules`, `dist`, `build`, `.codex`, `.env` files, and secret/key-looking paths.",
            "",
            "## Git Snapshot",
            "",
            "See `git-status.txt` for the complete sanitized status snapshot.",
            "",
            "## Repository Tree",
            "",
            "See `repo-tree.txt` for the sanitized file list.",
        ]
    )
    outputs = {
        "tree": write_text(destination / "repo-tree.txt", "\n".join(paths) if paths else "(no project files found)"),
        "status": write_text(destination / "git-status.txt", git_status(root)),
        "context": write_text(destination / "project-context.md", context),
    }
    outputs["json"] = export_context_json(machine_context, destination / "context.json")
    return outputs


def _default_template() -> Path:
    candidates = (
        PROJECT_ROOT / "templates" / "planner_prompt.md",
        Path.cwd() / "templates" / "planner_prompt.md",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def build_prompt(
    repo: str | Path = ".",
    *,
    user_request: str = DEFAULT_GOAL,
    template: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    """Build REQUEST.md from the collected local artifacts and template."""

    root = resolve_repo(repo)
    destination = resolve_repo_path(root, output_dir) if output_dir is not None else root / ".codex" / "pro-plan"
    template_path = (
        Path(template).expanduser().resolve()
        if template is not None and Path(template).expanduser().is_absolute()
        else (root / template if template is not None else _default_template())
    )
    required = {
        "project context": destination / "project-context.md",
        "repository tree": destination / "repo-tree.txt",
        "git status": destination / "git-status.txt",
        "planner template": template_path,
    }
    missing = [f"{label}: {path}" for label, path in required.items() if not path.is_file()]
    if missing:
        raise ValueError("missing planning input(s): " + "; ".join(missing))
    if not user_request.strip():
        raise ValueError("user request must not be empty")

    values = {
        "{{USER_REQUEST}}": user_request.strip(),
        "{{PROJECT_CONTEXT}}": (destination / "project-context.md").read_text(encoding="utf-8").strip(),
        "{{REPO_TREE}}": (destination / "repo-tree.txt").read_text(encoding="utf-8").strip(),
        "{{GIT_STATUS}}": (destination / "git-status.txt").read_text(encoding="utf-8").strip(),
        "{{GENERATED_AT}}": datetime.now(timezone.utc).isoformat(),
    }
    content = template_path.read_text(encoding="utf-8")
    for placeholder, value in values.items():
        content = content.replace(placeholder, value)
    return write_text(destination / "REQUEST.md", content)
