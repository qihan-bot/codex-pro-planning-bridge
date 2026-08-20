"""Compatibility wrapper for the unified package CLI."""

from __future__ import annotations

import sys

try:
    from ._bootstrap import ensure_src_on_path
except ImportError:  # Allow: python scripts/open_chat.py
    from _bootstrap import ensure_src_on_path  # type: ignore

ensure_src_on_path()

from codex_pro_planning_bridge import handoff as _handoff  # noqa: E402

CHATGPT_URL = _handoff.CHATGPT_URL
copy_to_clipboard = _handoff.copy_to_clipboard
webbrowser = _handoff.webbrowser


def open_chat(*args, **kwargs):
    """Delegate while preserving the old module's test/integration hooks."""

    return _handoff.open_chat(
        *args,
        clipboard=copy_to_clipboard,
        browser=webbrowser,
        **kwargs,
    )


def main(argv: list[str] | None = None) -> int:
    from codex_pro_planning_bridge.cli import main as cli_main

    values = sys.argv[1:] if argv is None else argv
    return cli_main(["open", *values])


if __name__ == "__main__":
    raise SystemExit(main())
