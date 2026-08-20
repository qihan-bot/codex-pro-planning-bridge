"""Build the human-reviewed planning request sent to ChatGPT Pro."""

from __future__ import annotations

from collections.abc import Iterable

from .context import RepositoryContext


DEFAULT_CONSTRAINTS = (
    "Keep the proposal compatible with the repository's existing conventions.",
    "Prefer incremental changes with explicit tests and rollback considerations.",
    "Do not assume API access, automated browser scraping, or external uploads.",
    "Call out assumptions and unresolved questions instead of silently inventing facts.",
)


def build_request(
    context: RepositoryContext,
    goal: str,
    *,
    constraints: Iterable[str] = DEFAULT_CONSTRAINTS,
) -> str:
    """Return a structured architecture request suitable for manual handoff."""

    normalized_goal = goal.strip()
    if not normalized_goal:
        raise ValueError("goal must not be empty")

    constraint_lines = [f"- {item.strip()}" for item in constraints if item.strip()]
    if not constraint_lines:
        constraint_lines = ["- Use the repository context below as the source of truth."]

    lines = [
        "# Architecture Planning Request",
        "",
        "This file was generated locally by Codex Pro Planning Bridge.",
        "Review it before pasting it into ChatGPT Pro; remove anything you do not want to share.",
        "",
        "## User Request",
        "",
        normalized_goal,
        "",
        "## Repository Context",
        "",
        context.to_markdown().rstrip(),
        "",
        "## Planning Constraints",
        "",
        *constraint_lines,
        "",
        "## Requested Planning Output",
        "",
        "Return a self-contained implementation plan in Markdown with these sections:",
        "",
        "1. `Summary` — restate the goal and the recommended approach.",
        "2. `Assumptions and Constraints` — identify facts that need confirmation.",
        "3. `Architecture / Design` — explain boundaries, data flow, and key trade-offs.",
        "4. `Implementation Steps` — give ordered, file-level changes with dependencies.",
        "5. `Testing and Validation` — define unit, integration, and manual checks.",
        "6. `Risks and Open Questions` — include mitigations and explicit follow-ups.",
        "",
        "Do not write code yet. Optimize for a plan that another coding agent can execute",
        "without guessing at missing requirements.",
        "",
    ]
    return "\n".join(lines)
