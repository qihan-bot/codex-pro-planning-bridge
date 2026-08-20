"""Compatibility exports for the package repository fact index."""

from __future__ import annotations

try:
    from ._bootstrap import ensure_src_on_path
except ImportError:  # Allow direct imports from a checkout.
    from _bootstrap import ensure_src_on_path  # type: ignore

ensure_src_on_path()

from codex_pro_planning_bridge.facts import *  # noqa: E402,F401,F403
