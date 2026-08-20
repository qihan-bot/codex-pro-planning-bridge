"""Validate the structure and completeness of a returned PLAN.md."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Iterable


REQUIRED_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Summary", ("summary", "overview", "objective")),
    ("Assumptions and Constraints", ("assumption", "constraint")),
    ("Architecture / Design", ("architecture", "design", "data flow", "trade-off")),
    ("Implementation Steps", ("implementation", "steps", "execution plan")),
    ("Testing and Validation", ("test", "validation", "verification")),
)


@dataclass
class ValidationResult:
    """Machine-readable and human-readable plan validation output."""

    errors: list[str]
    warnings: list[str]
    sections: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"ok": self.ok}

    def to_text(self) -> str:
        lines = ["PLAN.md validation: PASS" if self.ok else "PLAN.md validation: FAIL"]
        if self.sections:
            lines.append(f"Sections found: {', '.join(self.sections)}")
        if self.errors:
            lines.append("Errors:")
            lines.extend(f"- {error}" for error in self.errors)
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        if len(lines) == 1:
            lines.append("No structural issues found.")
        return "\n".join(lines)


def _headings(markdown: str) -> list[str]:
    return [match.group(2).strip() for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", markdown, re.MULTILINE)]


def _has_section(headings: Iterable[str], keywords: Iterable[str]) -> bool:
    normalized = [heading.casefold() for heading in headings]
    return any(any(keyword.casefold() in heading for keyword in keywords) for heading in normalized)


def validate_plan(markdown: str) -> ValidationResult:
    """Validate a plan without requiring a rigid heading vocabulary."""

    errors: list[str] = []
    warnings: list[str] = []
    if not markdown.strip():
        return ValidationResult(errors=["plan is empty"], warnings=[], sections=[])

    headings = _headings(markdown)
    if not headings:
        errors.append("plan must contain Markdown headings")

    for display_name, keywords in REQUIRED_SECTIONS:
        if not _has_section(headings, keywords):
            errors.append(f"missing a section for {display_name}")

    actionable_items = re.findall(r"(?m)^\s*(?:[-*+] |\d+[.)] )\S+", markdown)
    if len(actionable_items) < 3:
        errors.append("implementation plan should contain at least three actionable list items")

    if not _has_section(headings, ("risk", "open question", "follow-up")):
        warnings.append("add a Risks and Open Questions section before implementation")

    if not re.search(r"(?i)(?:^|[`\s/])(?:src|lib|app|tests?|docs?)[/\w.-]+", markdown):
        warnings.append("name the files or directories expected to change")

    if re.search(r"(?i)\b(?:TODO|TBD|FIXME)\b", markdown):
        warnings.append("plan contains unresolved TODO/TBD/FIXME markers")

    duplicate_headings = {heading for heading in headings if headings.count(heading) > 1}
    if duplicate_headings:
        warnings.append("duplicate headings found: " + ", ".join(sorted(duplicate_headings)))

    return ValidationResult(errors=errors, warnings=warnings, sections=headings)
