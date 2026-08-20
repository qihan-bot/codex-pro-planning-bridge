"""Validate PLAN.md structure and referenced repository paths."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys

try:
    from ._common import resolve_repo, resolve_repo_path, write_text
except ImportError:  # Allow: python scripts/validate_plan.py
    from _common import resolve_repo, resolve_repo_path, write_text  # type: ignore

from codex_pro_planning_bridge.plan import ValidationResult, validate_plan as validate_markdown


PATH_TOKEN_RE = re.compile(r"`([^`\n]+)`|\]\(([^)\s]+)\)")
KNOWN_FILE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".go", ".h", ".hpp", ".html", ".java", ".js",
    ".json", ".md", ".php", ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts",
    ".tsx", ".txt", ".vue", ".yaml", ".yml",
}


@dataclass(frozen=True)
class PathCheck:
    reference: str
    status: str
    detail: str


def _clean_token(token: str) -> str:
    token = token.strip().strip(".,;:()[]{}")
    token = re.sub(r":\d+(?::\d+)?$", "", token)
    return token.strip()


def extract_path_references(markdown: str) -> list[str]:
    candidates: set[str] = set()
    for match in PATH_TOKEN_RE.finditer(markdown):
        token = _clean_token(match.group(1) or match.group(2) or "")
        if not token or " " in token or "://" in token or token.startswith(("$", "--", "<")):
            continue
        normalized = token.replace("\\", "/")
        if normalized.startswith(("#", "./#")):
            continue
        path = PurePosixPath(normalized)
        if (
            "/" in normalized
            or path.suffix.lower() in KNOWN_FILE_SUFFIXES
            or normalized in {"Dockerfile", "Makefile", "README", "LICENSE"}
        ):
            candidates.add(normalized)
    return sorted(candidates)


def check_paths(repo: Path, references: list[str]) -> list[PathCheck]:
    checks: list[PathCheck] = []
    for reference in references:
        windows_path = PureWindowsPath(reference)
        posix_path = PurePosixPath(reference)
        if (
            windows_path.is_absolute()
            or posix_path.is_absolute()
            or re.match(r"^[A-Za-z]:", reference)
            or reference.startswith("~")
        ):
            checks.append(PathCheck(reference, "ERROR", "path must be relative to the repository"))
            continue
        parts = PurePosixPath(reference).parts
        if ".." in parts:
            checks.append(PathCheck(reference, "ERROR", "path escapes the repository with '..'"))
            continue
        resolved = (repo / Path(*parts)).resolve()
        try:
            resolved.relative_to(repo)
        except ValueError:
            checks.append(PathCheck(reference, "ERROR", "resolved path is outside the repository"))
            continue
        if resolved.exists():
            checks.append(PathCheck(reference, "OK", "path exists"))
        else:
            checks.append(PathCheck(reference, "ERROR", "referenced path does not exist"))
    return checks


def _report(
    repo: Path,
    plan_path: Path,
    structural: ValidationResult,
    path_checks: list[PathCheck],
    extra_errors: list[str],
) -> str:
    errors = [*extra_errors, *structural.errors]
    errors.extend(check.detail + f": `{check.reference}`" for check in path_checks if check.status == "ERROR")
    warnings = list(structural.warnings)
    if not path_checks:
        warnings.append("No concrete file or directory references were found in PLAN.md.")
    status = "PASS" if not errors else "FAIL"
    lines = [
        "# Plan Validation Report",
        "",
        f"- Status: **{status}**",
        f"- Plan: `{plan_path}`",
        f"- Repository: `{repo.name or repo}`",
        "",
        "## Structural Checks",
        "",
        structural.to_text(),
        "",
        "## Referenced Paths",
        "",
        "| Reference | Status | Detail |",
        "| --- | --- | --- |",
    ]
    if path_checks:
        lines.extend(f"| `{check.reference}` | {check.status} | {check.detail} |" for check in path_checks)
    else:
        lines.append("| _none_ | WARN | No concrete paths found |")
    if errors:
        lines.extend(["", "## Errors", "", *[f"- {error}" for error in errors]])
    if warnings:
        lines.extend(["", "## Warnings", "", *[f"- {warning}" for warning in warnings]])
    return "\n".join(lines)


def validate(
    repo: str | Path = ".",
    *,
    plan: str | Path = ".codex/pro-plan/PLAN.md",
    output: str | Path = ".codex/pro-plan/VALIDATION_REPORT.md",
) -> tuple[Path, bool]:
    root = resolve_repo(repo)
    plan_path = resolve_repo_path(root, plan)
    report_path = resolve_repo_path(root, output)
    extra_errors: list[str] = []
    if plan_path.is_file():
        markdown = plan_path.read_text(encoding="utf-8")
        structural = validate_markdown(markdown)
        references = extract_path_references(markdown)
        path_checks = check_paths(root, references)
    else:
        structural = ValidationResult(errors=["plan file does not exist"], warnings=[], sections=[])
        path_checks = []
        extra_errors.append(f"PLAN.md not found: `{plan_path}`")
    report = _report(root, plan_path, structural, path_checks, extra_errors)
    write_text(report_path, report)
    return report_path, not extra_errors and not structural.errors and not any(
        check.status == "ERROR" for check in path_checks
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate PLAN.md and write a validation report.")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--plan", default=".codex/pro-plan/PLAN.md")
    parser.add_argument("--output", default=".codex/pro-plan/VALIDATION_REPORT.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report_path, passed = validate(args.repo, plan=args.plan, output=args.output)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {report_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
