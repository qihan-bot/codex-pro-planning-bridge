"""Make the source package importable when a compatibility script is run directly."""

from __future__ import annotations

from pathlib import Path
import sys


def ensure_src_on_path() -> None:
    source = Path(__file__).resolve().parents[1] / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
