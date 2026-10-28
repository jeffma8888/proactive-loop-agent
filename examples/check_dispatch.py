"""Grade one ``pla dispatch --dry-run`` preview read from stdin.

Exit codes: 0 the preview contains every required marker the spec publishes,
1 the text is missing a required marker, 2 stdin was empty or unreadable.
Mirrors ``check_run.py``'s three-exit-code convention.  Standard library only,
no network::

    pla dispatch --dry-run --slate SLATE --goal-id ID | python examples/check_dispatch.py
"""

from __future__ import annotations

import sys
from typing import Final

REQUIRED_MARKERS: Final = (
    "[dry-run]",
    "decision:",
    "workspace root:",
    "state dir:",
    "run dir:",
    "run it for real with:",
    "pla dispatch",
)


def grade(text: str) -> tuple[int, str]:
    """Return ``(exit_code, one_report_line)`` for the preview text."""
    missing = [m for m in REQUIRED_MARKERS if m not in text]
    if missing:
        return 1, f"fail: missing required marker(s): {missing}"
    return 0, "ok: dispatch dry-run preview contains all required markers"


def main() -> int:
    """Read the preview from stdin, print one line, and return the exit code."""
    text = sys.stdin.read()
    if not text.strip():
        print("error: stdin is empty", file=sys.stderr)
        return 2
    code, line = grade(text)
    print(line, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
