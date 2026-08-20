"""Composable repository-context collection layers."""

from .collector import collect_repository
from .detector import detect_dependencies, detect_project_type, detect_project_types
from .exporters import render_context_json, render_context_markdown
from .models import FileContext, ProjectContext, RepositoryContext
from .scanner import scan_files

__all__ = [
    "FileContext",
    "ProjectContext",
    "RepositoryContext",
    "collect_repository",
    "detect_dependencies",
    "detect_project_type",
    "detect_project_types",
    "render_context_json",
    "render_context_markdown",
    "scan_files",
]
