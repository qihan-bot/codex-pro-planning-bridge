"""Open ChatGPT and copy REQUEST.md for a human-controlled handoff."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

try:
    from ._common import resolve_repo, resolve_repo_path
except ImportError:  # Allow: python scripts/open_chat.py
    from _common import resolve_repo, resolve_repo_path  # type: ignore


CHATGPT_URL = "https://chatgpt.com/"


def _copy_with_command(command: list[str], content: str) -> None:
    subprocess.run(
        command,
        input=content,
        text=True,
        encoding="utf-8",
        check=True,
        capture_output=True,
    )


def copy_to_clipboard(content: str) -> str:
    """Copy text using native Windows/macOS tools, with a Linux fallback."""

    if sys.platform.startswith("win"):
        for command in ("powershell.exe", "pwsh.exe"):
            if shutil.which(command):
                _copy_with_command(
                    [command, "-NoProfile", "-NonInteractive", "-Command", "Set-Clipboard"],
                    content,
                )
                return command
        raise RuntimeError("PowerShell was not found; unable to access the Windows clipboard")
    if sys.platform == "darwin":
        _copy_with_command(["pbcopy"], content)
        return "pbcopy"
    for command in (("xclip", "-selection", "clipboard"), ("xsel", "--clipboard", "--input")):
        if shutil.which(command[0]):
            _copy_with_command(list(command), content)
            return command[0]
    raise RuntimeError("no supported clipboard command found")


def open_chat(
    repo: str | Path = ".",
    *,
    request: str | Path = ".codex/pro-plan/REQUEST.md",
    url: str = CHATGPT_URL,
    pause: bool = True,
) -> int:
    root = resolve_repo(repo)
    request_path = resolve_repo_path(root, request)
    if not request_path.is_file():
        raise ValueError(f"REQUEST.md not found: {request_path}")
    content = request_path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"REQUEST.md is empty: {request_path}")

    clipboard_tool = copy_to_clipboard(content)
    webbrowser.open(url, new=2)
    print(f"Copied {request_path} to the clipboard with {clipboard_tool}.")
    print("ChatGPT is open. Select ChatGPT Pro (or the Pro-capable model you want), then paste the request.")
    print("This script does not submit the prompt or call an OpenAI API.")
    if pause:
        try:
            input("Press Enter after you have completed the manual handoff... ")
        except EOFError:
            pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Copy REQUEST.md and open ChatGPT for manual handoff.")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--request", default=".codex/pro-plan/REQUEST.md")
    parser.add_argument("--url", default=CHATGPT_URL)
    parser.add_argument("--no-pause", action="store_true", help="do not wait for user confirmation")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return open_chat(
            args.repo,
            request=args.request,
            url=args.url,
            pause=not args.no_pause,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
