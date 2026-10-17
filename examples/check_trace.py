"""Grade one ``pla trace --run-dir DIR --json`` document read from stdin.

Exit codes: 0 the trace is a non-empty array of well-formed step objects whose
``kind`` values are valid ``StepKind`` members, 1 the document parsed but fails
a grading rule, 2 stdin was not one valid JSON document or not a JSON array (or
contains a non-object element).  Mirrors ``check_run.py``'s three-exit-code
convention.  Standard library plus ``proactive_loop`` only, no network::

    pla trace --run-dir DIR --json | python examples/check_trace.py
"""

from __future__ import annotations

import json
import sys
from typing import Any

from proactive_loop.models import StepKind

VALID_KINDS: frozenset[str] = frozenset(member.value for member in StepKind)

REQUIRED_KEYS: tuple[str, ...] = ("index", "kind", "output", "done", "artifacts")


def grade(steps: list[dict[str, Any]]) -> tuple[int, str]:
    """Return ``(exit_code, one_report_line)`` for one already-parsed trace."""
    if not steps:
        return 1, "fail: trace is an empty array -- a zero-step trace is vacuous"
    for i, step in enumerate(steps):
        for key in REQUIRED_KEYS:
            if key not in step:
                return 1, (
                    f"fail: step {i} is missing required key {key!r}"
                    f" -- keys present: {sorted(step)}"
                )
        if not isinstance(step["index"], int) or isinstance(step["index"], bool):
            return 1, (
                f"fail: step {i} has a non-integer index:"
                f" {step['index']!r}"
            )
        kind = step["kind"]
        if kind not in VALID_KINDS:
            return 1, (
                f"fail: step {i} has an invalid kind {kind!r}"
                f" -- valid: {sorted(VALID_KINDS)}"
            )
        if not isinstance(step["done"], bool):
            return 1, (
                f"fail: step {i} has a non-boolean done:"
                f" {step['done']!r}"
            )
        if not isinstance(step["artifacts"], list):
            return 1, (
                f"fail: step {i} has a non-list artifacts:"
                f" {type(step['artifacts']).__name__}"
            )
    return 0, f"ok: trace has {len(steps)} steps, all well-formed"


def main() -> int:
    """Read one trace document from stdin, print one line, and return the exit code."""
    try:
        document = json.loads(sys.stdin.read())
    except ValueError as exc:
        print(f"error: stdin is not one valid JSON document: {exc}", file=sys.stderr)
        return 2
    if not isinstance(document, list):
        got = type(document).__name__
        print(f"error: expected one JSON array on stdin, got {got}", file=sys.stderr)
        return 2
    for index, entry in enumerate(document):
        if not isinstance(entry, dict):
            got = type(entry).__name__
            print(
                f"error: trace entry {index} is not a JSON object, got {got}",
                file=sys.stderr,
            )
            return 2
    code, line = grade(document)
    print(line, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
