"""Human and machine-readable context exporters."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import ProjectContext
from ..repository import write_text


def render_context_markdown(context: ProjectContext) -> str:
    return context.to_markdown()


def render_context_json(context: ProjectContext) -> str:
    return json.dumps(context.to_dict(), indent=2, ensure_ascii=False) + "\n"


def export_context_json(context: ProjectContext, path: str | Path) -> Path:
    return write_text(Path(path), render_context_json(context))


def export_context_markdown(context: ProjectContext, path: str | Path) -> Path:
    return write_text(Path(path), render_context_markdown(context))
