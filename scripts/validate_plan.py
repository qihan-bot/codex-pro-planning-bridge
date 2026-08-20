"""Validate PLAN.md against local repository facts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys

try:
    from ._common import resolve_repo, resolve_repo_path, write_text
    from .repository_facts import (
        FRAMEWORK_ALIASES,
        RepositoryFacts,
        build_repository_facts,
        normalize_dependency,
    )
except ImportError:  # Allow: python scripts/validate_plan.py
    from _common import resolve_repo, resolve_repo_path, write_text  # type: ignore
    from repository_facts import (  # type: ignore
        FRAMEWORK_ALIASES,
        RepositoryFacts,
        build_repository_facts,
        normalize_dependency,
    )

from codex_pro_planning_bridge.plan import ValidationResult, validate_plan as validate_markdown


PATH_TOKEN_RE = re.compile(r"`([^`\n]+)`|\]\(([^)\s]+)\)")
KNOWN_FILE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".go", ".h", ".hpp", ".html", ".java", ".js",
    ".json", ".md", ".php", ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts",
    ".tsx", ".txt", ".vue", ".yaml", ".yml",
}
STOPWORDS = {
    "a", "an", "and", "existing", "framework", "library", "module", "new", "package", "the", "this"
}


@dataclass(frozen=True)
class PathCheck:
    reference: str
    status: str
    detail: str


@dataclass(frozen=True)
class Finding:
    category: str
    reference: str
    status: str
    detail: str


@dataclass(frozen=True)
class DependencyReference:
    name: str
    context: str
    version: str | None = None


def _clean_token(token: str) -> str:
    token = token.strip().strip(".,;:()[]{}")
    token = re.sub(r":\d+(?::\d+)?$", "", token)
    return token.strip()


def extract_path_references(markdown: str) -> list[str]:
    """Extract concrete repository paths from inline code and Markdown links."""

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
    """Check that references are relative, inside the repo, and present."""

    checks: list[PathCheck] = []
    resolved_repo = Path(repo).resolve()
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
        resolved = (resolved_repo / Path(*parts)).resolve()
        try:
            resolved.relative_to(resolved_repo)
        except ValueError:
            checks.append(PathCheck(reference, "ERROR", "resolved path is outside the repository"))
            continue
        if resolved.exists():
            checks.append(PathCheck(reference, "OK", "path exists and belongs to the repository"))
        else:
            checks.append(PathCheck(reference, "ERROR", "referenced path does not exist"))
    return checks


def _inline_code_tokens(markdown: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"`([^`\n]+)`", markdown)]


def extract_symbol_references(markdown: str) -> list[str]:
    """Extract explicit class/function/API references without guessing from prose."""

    references: set[str] = set()
    call_pattern = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s*\([^)]*\)")
    explicit_pattern = re.compile(
        r"\b(?:class|interface|function|method|symbol)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)",
        re.IGNORECASE,
    )
    api_pattern = re.compile(r"\bAPI\s+([A-Z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)")
    for token in _inline_code_tokens(markdown):
        match = call_pattern.fullmatch(token)
        if match:
            references.add(match.group(1))
        match = explicit_pattern.search(token)
        if match:
            references.add(match.group(1))
        match = api_pattern.search(token)
        if match:
            references.add(match.group(1))
    for match in call_pattern.finditer(markdown):
        references.add(match.group(1))
    for match in explicit_pattern.finditer(markdown):
        references.add(match.group(1))
    for match in api_pattern.finditer(markdown):
        references.add(match.group(1))
    return sorted(reference for reference in references if reference.casefold() not in STOPWORDS)


def extract_module_references(markdown: str) -> list[str]:
    """Extract import-style module references stated as code or standalone lines."""

    references: set[str] = set()
    import_pattern = re.compile(r"\b(?:from|import)\s+([A-Za-z_][A-Za-z0-9_.]*)")
    for token in _inline_code_tokens(markdown):
        for match in import_pattern.finditer(token):
            references.add(match.group(1))
    for line in markdown.splitlines():
        if re.match(r"^\s*(?:from|import)\s+", line):
            match = import_pattern.search(line)
            if match:
                references.add(match.group(1))
    return sorted(references)


def extract_dependency_references(markdown: str) -> list[DependencyReference]:
    """Extract dependencies/frameworks that a plan explicitly proposes to use."""

    references: dict[str, DependencyReference] = {}
    dependency_pattern = re.compile(
        r"\b(?:add|install|use|using|introduce|require|requires|dependency|dependencies|package|library|framework|depends on)"
        r"\s+(?:the\s+)?(?:dependency\s+)?[`'\"]?([@A-Za-z][A-Za-z0-9_.@/\-]*)",
        re.IGNORECASE,
    )
    for match in dependency_pattern.finditer(markdown):
        name = match.group(1).strip("`'\".,;:()")
        if name.casefold() in STOPWORDS or ("/" in name and name.startswith(("src/", "tests/", "docs/"))):
            continue
        key = normalize_dependency(name)
        if key:
            context = markdown[max(0, match.start() - 60):match.end() + 20]
            version_match = re.search(r"(?:@|==|>=|<=|>|<|\bversion\s+|\bv)\s*(\d+(?:\.\d+){0,2})", context, re.IGNORECASE)
            version = version_match.group(1) if version_match else None
            references.setdefault(key, DependencyReference(name=name, context=context, version=version))

    for mention, dependency in sorted(FRAMEWORK_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(mention)}\b", markdown, re.IGNORECASE):
            key = normalize_dependency(dependency)
            references.setdefault(key, DependencyReference(name=dependency, context=mention))
    return sorted(references.values(), key=lambda item: item.name.casefold())


def check_symbols(facts: RepositoryFacts, references: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for reference in references:
        found = facts.has_symbol(reference)
        findings.append(
            Finding(
                category="Symbol",
                reference=reference,
                status="OK" if found else "ERROR",
                detail="symbol was found in the local source index"
                if found
                else "symbol was not found in the local source index",
            )
        )
    return findings


def check_modules(facts: RepositoryFacts, references: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for reference in references:
        found = facts.has_module(reference)
        findings.append(
            Finding(
                category="Module",
                reference=reference,
                status="OK" if found else "ERROR",
                detail="module is available locally"
                if found
                else "module is not available in the repository or declared dependencies",
            )
        )
    return findings


def check_dependencies(facts: RepositoryFacts, references: list[DependencyReference]) -> list[Finding]:
    findings: list[Finding] = []
    for reference in references:
        if facts.has_dependency(reference.name):
            declared_version = facts.dependencies.get(normalize_dependency(reference.name))
            if reference.version and declared_version:
                declared_match = re.search(r"(\d+(?:\.\d+){0,2})", declared_version)
                if declared_match and declared_match.group(1).split(".")[0] != reference.version.split(".")[0]:
                    findings.append(
                        Finding(
                            "Dependency",
                            reference.name,
                            "WARN",
                            f"plan requests version {reference.version}; manifest declares {declared_version}",
                        )
                    )
                    continue
            findings.append(
                Finding("Dependency", reference.name, "OK", "dependency is declared in a supported manifest")
            )
            continue
        additive = bool(re.search(r"\b(?:add|install|introduce|upgrade)\b", reference.context, re.IGNORECASE))
        findings.append(
            Finding(
                "Dependency",
                reference.name,
                "WARN" if additive else "ERROR",
                "dependency is not currently declared; add it explicitly during implementation"
                if additive
                else "dependency or framework is not declared in a supported manifest",
            )
        )
    return findings


def _render_findings(title: str, findings: list[Finding]) -> list[str]:
    lines = [f"## {title}", "", "| Reference | Status | Detail |", "| --- | --- | --- |"]
    if findings:
        lines.extend(
            f"| `{finding.reference}` | {finding.status} | {finding.detail} |" for finding in findings
        )
    else:
        lines.append("| _none_ | — | No references found |")
    return lines


def _report(
    repo: Path,
    plan_path: Path,
    structural: ValidationResult,
    path_checks: list[PathCheck],
    module_findings: list[Finding],
    symbol_findings: list[Finding],
    dependency_findings: list[Finding],
    facts: RepositoryFacts,
    artifact_notes: list[str],
    extra_errors: list[str],
) -> str:
    all_findings = [*module_findings, *symbol_findings, *dependency_findings]
    errors = [*extra_errors, *structural.errors]
    errors.extend(check.detail + f": `{check.reference}`" for check in path_checks if check.status == "ERROR")
    errors.extend(
        f"{finding.category} `{finding.reference}`: {finding.detail}"
        for finding in all_findings
        if finding.status == "ERROR"
    )
    warnings = [*structural.warnings, *facts.notes]
    warnings.extend(
        f"{finding.category} `{finding.reference}`: {finding.detail}"
        for finding in all_findings
        if finding.status == "WARN"
    )
    if not path_checks:
        warnings.append("No concrete file or directory references were found in PLAN.md.")
    status = "PASS" if not errors else "FAIL"
    path_lines = ["## File / Path Checks", "", "| Reference | Status | Detail |", "| --- | --- | --- |"]
    if path_checks:
        path_lines.extend(f"| `{check.reference}` | {check.status} | {check.detail} |" for check in path_checks)
    else:
        path_lines.append("| _none_ | — | No concrete paths found |")

    lines = [
        "# Plan Validation Report",
        "",
        f"- Status: **{status}**",
        f"- Plan: `{plan_path}`",
        f"- Repository: `{repo.name or repo}`",
        f"- Indexed files: `{len(facts.files)}`",
        f"- Indexed modules: `{len(facts.modules)}`",
        f"- Indexed symbols: `{len(facts.symbols)}`",
        f"- Declared dependencies: `{len(facts.dependencies)}`",
        "",
        "## Input Artifacts",
        "",
        *artifact_notes,
        "",
        "## Structural Checks",
        "",
        structural.to_text(),
        "",
        *path_lines,
        "",
        *_render_findings("Module Checks", module_findings),
        "",
        *_render_findings("Symbol Checks", symbol_findings),
        "",
        *_render_findings("Dependency and Framework Checks", dependency_findings),
    ]
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
    artifact_notes: list[str] = []
    for artifact_name in ("repo-tree.txt", "project-context.md"):
        artifact_path = plan_path.parent / artifact_name
        if artifact_path.is_file():
            artifact_notes.append(f"- `{artifact_name}` available")
        else:
            artifact_notes.append(f"- `{artifact_name}` missing; live repository scan used")

    extra_errors: list[str] = []
    if plan_path.is_file():
        markdown = plan_path.read_text(encoding="utf-8")
        structural = validate_markdown(markdown)
    else:
        markdown = ""
        structural = ValidationResult(errors=["plan file does not exist"], warnings=[], sections=[])
        extra_errors.append(f"PLAN.md not found: `{plan_path}`")

    facts = build_repository_facts(root)
    path_checks = check_paths(root, extract_path_references(markdown))
    module_findings = check_modules(facts, extract_module_references(markdown))
    symbol_findings = check_symbols(facts, extract_symbol_references(markdown))
    dependency_findings = check_dependencies(facts, extract_dependency_references(markdown))
    report = _report(
        root,
        plan_path,
        structural,
        path_checks,
        module_findings,
        symbol_findings,
        dependency_findings,
        facts,
        artifact_notes,
        extra_errors,
    )
    write_text(report_path, report)
    all_findings = [*module_findings, *symbol_findings, *dependency_findings]
    passed = not extra_errors and not structural.errors and not any(
        check.status == "ERROR" for check in path_checks
    ) and not any(finding.status == "ERROR" for finding in all_findings)
    return report_path, passed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate PLAN.md and write a local fact-check report.")
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
