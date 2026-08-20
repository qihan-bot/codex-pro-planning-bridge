"""Build REQUEST.md from collected context and a local Markdown template."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

try:
    from ._common import PROJECT_ROOT, resolve_repo, resolve_repo_path, write_text
except ImportError:  # Allow: python scripts/build_prompt.py
    from _common import PROJECT_ROOT, resolve_repo, resolve_repo_path, write_text  # type: ignore


DEFAULT_GOAL = "Review this repository and propose the safest next implementation steps."


def build_prompt(
    repo: str | Path = ".",
    *,
    user_request: str = DEFAULT_GOAL,
    template: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    root = resolve_repo(repo)
    destination = (
        resolve_repo_path(root, output_dir)
        if output_dir is not None
        else root / ".codex" / "pro-plan"
    )
    template_path = (
        Path(template).expanduser().resolve()
        if template is not None and Path(template).expanduser().is_absolute()
        else (root / template if template is not None else PROJECT_ROOT / "templates" / "planner_prompt.md")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build REQUEST.md for manual ChatGPT Pro planning.")
    parser.add_argument("--repo", default=".", help="project directory (default: current directory)")
    parser.add_argument("--goal", "--request", dest="user_request", default=DEFAULT_GOAL)
    parser.add_argument("--template", default=None, help="planner template path")
    parser.add_argument("--output-dir", default=None, help="planning artifact directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = build_prompt(
            args.repo,
            user_request=args.user_request,
            template=args.template,
            output_dir=args.output_dir,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"Generated {output}")
    print("Review REQUEST.md before copying it into ChatGPT Pro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
