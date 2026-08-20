"""Compatibility exports for the unified Project Memory manager."""

from __future__ import annotations

import sys

try:
    from ._bootstrap import ensure_src_on_path
except ImportError:  # Allow: python scripts/memory.py
    from _bootstrap import ensure_src_on_path  # type: ignore

ensure_src_on_path()

from codex_pro_planning_bridge.memory import *  # noqa: E402,F401,F403


def main(argv: list[str] | None = None) -> int:
    from codex_pro_planning_bridge.cli import main as cli_main

    values = sys.argv[1:] if argv is None else argv
    return cli_main(["memory", *values])


if __name__ == "__main__":
    raise SystemExit(main())
