"""Compatibility wrapper for the unified package CLI."""

from __future__ import annotations

import sys

try:
    from ._bootstrap import ensure_src_on_path
except ImportError:  # Allow: python scripts/collect_context.py
    from _bootstrap import ensure_src_on_path  # type: ignore

ensure_src_on_path()

from codex_pro_planning_bridge.artifacts import collect_context  # noqa: E402,F401


def main(argv: list[str] | None = None) -> int:
    from codex_pro_planning_bridge.cli import main as cli_main

    values = sys.argv[1:] if argv is None else argv
    return cli_main(["collect", *values])


if __name__ == "__main__":
    raise SystemExit(main())
