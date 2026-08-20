"""Coordinate the local-first v0.3 planning loop.

The loop is intentionally a collaboration boundary.  It prepares artifacts,
validates a human-reviewed plan, waits for Codex to implement it, and then
reviews local drift.  It never edits source files and never calls an API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from .approval import PlanApprovalStore
from .artifacts import DEFAULT_GOAL, build_prompt, collect_context
from .context import collect_repository
from .diff import DiffEntry as EngineDiffEntry
from .diff import PlanDiffResult, diff_plan
from .intelligence.symbol_graph import build_symbol_graph, export_symbol_graph
from .intelligence.symbol_index import build_symbol_index, export_symbol_index
from .memory import ProjectMemory
from .models import (
    DiffEntry,
    DriftReport,
    Plan,
    ProjectContext,
    ValidationReport,
    WorkflowState,
)
from .repository import resolve_repo, resolve_repo_path
from .validator import validate as validate_repository
from .workflow import Workflow


@dataclass
class LoopResult:
    """Typed result returned by one loop invocation."""

    state: WorkflowState
    next_action: str
    messages: list[str] = field(default_factory=list)
    artifacts: dict[str, Path] = field(default_factory=dict)
    validation: ValidationReport | None = None
    drift: DriftReport | None = None
    context: ProjectContext | None = None
    plan: Plan | None = None

    @property
    def ok(self) -> bool:
        return self.state != WorkflowState.FAILED and (
            self.validation is None or self.validation.passed
        ) and (self.drift is None or not self.drift.missing and not self.drift.changed and not self.drift.blocked and not self.drift.unplanned_changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "next_action": self.next_action,
            "ok": self.ok,
            "messages": list(self.messages),
            "artifacts": {key: str(value) for key, value in self.artifacts.items()},
            "validation": asdict(self.validation) if self.validation else None,
            "drift": self.drift.to_dict() if self.drift else None,
            "context": self.context.to_dict() if self.context else None,
            "plan": {
                "path": str(self.plan.path),
                "sections": list(self.plan.sections),
                "tasks": [asdict(task) for task in self.plan.tasks],
                "assumptions": list(self.plan.assumptions),
            }
            if self.plan
            else None,
        }


def _headings(markdown: str) -> list[str]:
    import re

    return [
        match.group(2).strip()
        for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", markdown, re.MULTILINE)
    ]


def _section(markdown: str, keywords: tuple[str, ...]) -> str:
    import re

    headings = list(re.finditer(r"^(#{1,6})\s+(.+?)\s*$", markdown, re.MULTILINE))
    for index, heading in enumerate(headings):
        title = heading.group(2).casefold()
        if not any(keyword.casefold() in title for keyword in keywords):
            continue
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        return markdown[start:end].strip()
    return ""


def _plan_from_markdown(path: Path, markdown: str) -> Plan:
    from .diff import extract_plan_tasks

    assumptions = [
        line.strip(" -*")
        for line in _section(markdown, ("assumption", "constraint")).splitlines()
        if line.strip(" -*")
    ]
    return Plan(
        path=path,
        sections=_headings(markdown),
        tasks=extract_plan_tasks(markdown),
        assumptions=assumptions,
    )


def _drift_report(result: PlanDiffResult) -> DriftReport:
    def convert(entries: list[EngineDiffEntry]) -> list[DiffEntry]:
        return [
            DiffEntry(task=item.task, detail=item.detail, references=item.references)
            for item in entries
        ]

    from .models import SymbolChange

    return DriftReport(
        plan_path=result.plan_path,
        changed_files=list(result.changed_files),
        completed=convert(result.completed),
        missing=convert(result.missing),
        changed=convert(result.changed),
        blocked=convert(result.blocked),
        unplanned_changes=list(result.unplanned_changes),
        symbol_changes=[
            SymbolChange(
                name=item.name,
                kind=item.kind,
                before_paths=item.before_paths,
                after_paths=item.after_paths,
            )
            for item in result.symbol_changes
        ],
    )


class PlanningLoop:
    """Run one resumable planning session for a local repository."""

    def __init__(
        self,
        repo: str | Path = ".",
        *,
        goal: str = DEFAULT_GOAL,
        plan: str | Path = ".codex/pro-plan/PLAN.md",
        base: str | None = None,
    ) -> None:
        self.root = resolve_repo(repo)
        self.workflow = Workflow(self.root, goal=goal, plan=plan)
        self.plan_path = self.workflow.plan or resolve_repo_path(self.root, plan)
        self.approval = PlanApprovalStore(self.root, plan=self.plan_path)
        self.artifact_dir = self.root / ".codex" / "pro-plan"
        self.base = base
        self.context: ProjectContext | None = None
        self.plan_model: Plan | None = None
        self.artifacts: dict[str, Path] = {}

    @property
    def state(self) -> WorkflowState:
        return self.workflow.state

    def _load_context(self) -> ProjectContext | None:
        path = self.artifact_dir / "context.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return ProjectContext.from_dict(value) if isinstance(value, dict) else None

    def _load_plan(self) -> Plan | None:
        if not self.plan_path.is_file():
            return None
        markdown = self.plan_path.read_text(encoding="utf-8")
        self.plan_model = _plan_from_markdown(self.plan_path, markdown)
        return self.plan_model

    def _result(
        self,
        next_action: str,
        *,
        messages: list[str] | None = None,
        validation: ValidationReport | None = None,
        drift: DriftReport | None = None,
    ) -> LoopResult:
        return LoopResult(
            state=self.state,
            next_action=next_action,
            messages=messages or [],
            artifacts=dict(self.artifacts),
            validation=validation,
            drift=drift,
            context=self.context,
            plan=self.plan_model,
        )

    def prepare_context(self) -> LoopResult:
        """Collect context, prepare a Pro request, and enter CONTEXT_READY."""

        self.artifacts = collect_context(self.root, self.artifact_dir)
        self.artifacts["request"] = build_prompt(
            self.root,
            user_request=self.workflow.snapshot.goal or DEFAULT_GOAL,
            output_dir=self.artifact_dir,
        )
        index_path = self.artifact_dir / "symbol-index.json"
        export_symbol_index(build_symbol_index(self.root), index_path)
        self.artifacts["symbol-index"] = index_path
        graph_path = self.artifact_dir / "symbol-graph.json"
        export_symbol_graph(build_symbol_graph(self.root), graph_path)
        self.artifacts["symbol-graph"] = graph_path
        self.context = self._load_context() or collect_repository(self.root)
        self.workflow.annotate(
            plan=self.plan_path,
            next_action=(
                "Review REQUEST.md in ChatGPT Pro and save the approved response as PLAN.md."
            ),
        )
        if self.state == WorkflowState.NEW_TASK:
                self.workflow.transition(
                    WorkflowState.CONTEXT_READY,
                    reason="local context and Pro request prepared",
                    next_action="Review REQUEST.md in ChatGPT Pro and save the approved response as PLAN.md.",
                    event="CONTEXT_COLLECTED",
                )
        return self._result(
            "Review REQUEST.md in ChatGPT Pro and save the approved response as PLAN.md.",
            messages=[
                "Context was collected locally.",
                "REQUEST.md is ready for a human-controlled ChatGPT Pro handoff.",
                "No source files were modified.",
            ],
        )

    def _mark_plan_ready(self) -> None:
        self.plan_model = self._load_plan()
        if self.plan_model is None:
            return
        if self.state == WorkflowState.CONTEXT_READY:
            self.workflow.transition(
                WorkflowState.PLAN_READY,
                reason="approved PLAN.md was found locally",
                next_action="Run local plan validation.",
                event="PLAN_READY",
            )

    def validate_plan(self) -> LoopResult:
        """Validate PLAN.md and either wait for correction or implementation."""

        self.plan_model = self._load_plan()
        if self.plan_model is None:
            self.workflow.annotate(
                next_action="Save the ChatGPT Pro response as PLAN.md before validation.",
                error=None,
            )
            return self._result(
                "Save the ChatGPT Pro response as PLAN.md before validation.",
                messages=[f"Plan file not found: {self.plan_path}"],
            )
        if self.state == WorkflowState.CONTEXT_READY:
            self.workflow.transition(
                WorkflowState.PLAN_READY,
                reason="approved PLAN.md was found locally",
                next_action="Run local plan validation.",
                event="PLAN_READY",
            )
        if self.state == WorkflowState.PLAN_READY:
            self.workflow.transition(
                WorkflowState.VALIDATING,
                reason="starting local plan and repository fact checks",
                next_action="Review VALIDATION_REPORT.md.",
                event="PLAN_VALIDATION_STARTED",
            )
        report_path, passed = validate_repository(
            self.root,
            plan=self.plan_path,
            output=self.artifact_dir / "VALIDATION_REPORT.md",
        )
        self.artifacts["validation"] = report_path
        report = ValidationReport(
            passed=passed,
            errors=[] if passed else [f"See {report_path} for validation errors."],
            warnings=[],
        )
        if passed:
            if not self.approval.is_approved():
                approval_path = self.approval.path
                self.workflow.annotate(
                    next_action=(
                        "Review PLAN.md and run cpb approve --repo <repo> "
                        "before resuming implementation."
                    ),
                    error=f"Plan approval required; see {approval_path}",
                )
                return self._result(
                    "Review PLAN.md and run cpb approve before resuming implementation.",
                    messages=[
                        "PLAN.md passed local repository and fact checks.",
                        f"Explicit human approval is required in {approval_path}.",
                    ],
                    validation=report,
                )
            self.workflow.transition(
                WorkflowState.IMPLEMENTING,
                reason="PLAN.md passed local validation",
                next_action="Codex may implement the approved plan; source changes remain explicit.",
                event="PLAN_VALIDATED",
            )
            return self._result(
                "Codex may implement the approved plan; source changes remain explicit.",
                messages=["PLAN.md passed local repository and fact checks."],
                validation=report,
            )
        self.workflow.annotate(
            next_action="Fix PLAN.md findings, then run cpb loop again.",
            error=f"Plan validation failed; see {report_path}",
        )
        return self._result(
            "Fix PLAN.md findings, then run cpb loop again.",
            messages=[f"PLAN.md failed local validation; see {report_path}"],
            validation=report,
        )

    def _record_plan_once(self) -> Path:
        memory = ProjectMemory(self.root)
        memory.initialize()
        marker = f"Source: `{self.plan_path.relative_to(self.root).as_posix()}`"
        for entry in memory.list_adrs():
            if marker in entry.content:
                return entry.path
        return memory.record_plan(self.plan_path)

    def review(self) -> LoopResult:
        """Compare implementation drift, update memory, and complete the loop."""

        if self.state == WorkflowState.IMPLEMENTING:
            self.workflow.transition(
                WorkflowState.REVIEWING,
                reason="Codex implementation review requested",
                next_action="Inspect PLAN_DIFF.md and update project memory.",
                event="IMPLEMENTATION_REVIEW_STARTED",
            )
        if self.state not in {WorkflowState.REVIEWING, WorkflowState.COMPLETED}:
            raise ValueError(f"cannot review from workflow state {self.state.value}")
        report_path, diff_result = diff_plan(
            self.root,
            plan=self.plan_path,
            output=self.artifact_dir / "PLAN_DIFF.md",
            base=self.base,
        )
        self.artifacts["diff"] = report_path
        memory_path = self._record_plan_once()
        self.artifacts["memory"] = memory_path
        drift = _drift_report(diff_result)
        if self.state == WorkflowState.REVIEWING:
            next_action = (
                "Review PLAN_DIFF.md and start the next task."
                if drift.missing or drift.changed or drift.blocked or drift.unplanned_changes
                else "Review PLAN_DIFF.md and start the next task when ready."
            )
            self.workflow.transition(
                WorkflowState.COMPLETED,
                reason="implementation drift reviewed and project memory updated",
                next_action=next_action,
                event="WORKFLOW_COMPLETED",
            )
        return self._result(
            self.workflow.snapshot.next_action or "Start the next task.",
            messages=[
                f"PLAN_DIFF.md written to {report_path}.",
                f"Project memory updated at {memory_path}.",
                "No source files were modified by the bridge.",
            ],
            drift=drift,
        )

    def run(
        self,
        *,
        review: bool = False,
        reset: bool = False,
        resume: bool = False,
    ) -> LoopResult:
        """Advance the session as far as local evidence and explicit approval allow."""

        if reset:
            self.workflow.reset(goal=self.workflow.snapshot.goal, plan=self.plan_path)
        if self.state == WorkflowState.PAUSED:
            if not resume:
                return self._result(
                    "Run cpb resume to continue the paused workflow.",
                    messages=["Workflow is paused; no work was performed."],
                )
            self.workflow.resume()
        if self.state == WorkflowState.CANCELLED:
            return self._result(
                "Start a new workflow with cpb loop --reset when ready.",
                messages=["Workflow is cancelled; no work was performed."],
            )
        if self.state == WorkflowState.NEW_TASK:
            self.prepare_context()
        if self.state == WorkflowState.CONTEXT_READY:
            self._mark_plan_ready()
            if self.plan_model is None:
                return self._result(
                    "Review REQUEST.md in ChatGPT Pro and save the approved response as PLAN.md."
                )
        if self.state in {WorkflowState.PLAN_READY, WorkflowState.VALIDATING}:
            return self.validate_plan()
        if self.state == WorkflowState.IMPLEMENTING:
            if review:
                return self.review()
            return self._result(
                "Codex may implement the approved plan; run cpb loop --review after implementation.",
                messages=[
                    "PLAN.md is approved for implementation.",
                    "The bridge is paused for explicit Codex implementation.",
                ],
            )
        if self.state == WorkflowState.REVIEWING:
            return self.review()
        if self.state == WorkflowState.COMPLETED:
            return self._result(
                self.workflow.snapshot.next_action or "Start the next task with cpb loop --reset.",
                messages=["This workflow is already completed; use --reset for a new task."],
            )
        return self._result(
            "Reset the workflow after resolving the recorded error.",
            messages=[self.workflow.snapshot.error or "Workflow is failed."],
        )


def run_loop(
    repo: str | Path = ".",
    *,
    goal: str = DEFAULT_GOAL,
    plan: str | Path = ".codex/pro-plan/PLAN.md",
    base: str | None = None,
    review: bool = False,
    reset: bool = False,
    resume: bool = False,
) -> LoopResult:
    """Convenience entry point used by the unified CLI and integrations."""

    return PlanningLoop(repo, goal=goal, plan=plan, base=base).run(
        review=review,
        reset=reset,
        resume=resume,
    )


__all__ = ["LoopResult", "PlanningLoop", "run_loop"]
