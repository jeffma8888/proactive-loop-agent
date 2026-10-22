"""Grade one ``pla runs --summary --json`` document read from stdin.

Exit codes: 0 the summary describes at least one run with valid status keys
and non-negative aggregate counters, 1 the document parsed but fails a grading
rule, 2 stdin was not one valid JSON document or not a JSON object.  Mirrors
``check_trace.py``'s three-exit-code convention.  Standard library plus
``proactive_loop`` only, no network::

    pla runs --summary --json --state-dir DIR | python examples/check_runs_summary.py
"""

from __future__ import annotations

import json
import sys
from typing import Any

from proactive_loop.models import RunStatus

VALID_STATUSES: frozenset[str] = frozenset(member.value for member in RunStatus)

AGGREGATE_FIELDS: tuple[str, ...] = ("iterations", "artifacts", "retries", "parse_errors")


def grade(summary: dict[str, Any]) -> tuple[int, str]:
    """Return ``(exit_code, one_report_line)`` for one already-parsed summary."""
    if "runs" not in summary:
        return 1, "fail: summary is missing the required key 'runs'"
    runs = summary["runs"]
    if isinstance(runs, bool) or not isinstance(runs, int):
        return 1, f"fail: 'runs' is not an integer: {runs!r}"
    if runs < 1:
        return 1, f"fail: runs={runs} -- a zero-run summary is vacuous"
    if "by_status" not in summary:
        return 1, "fail: summary is missing the required key 'by_status'"
    by_status = summary["by_status"]
    if not isinstance(by_status, dict):
        return 1, f"fail: 'by_status' is not an object: {type(by_status).__name__}"
    for key in by_status:
        if key not in VALID_STATUSES:
            return 1, (
                f"fail: by_status contains an invalid RunStatus key {key!r}"
                f" -- valid: {sorted(VALID_STATUSES)}"
            )
    for field in AGGREGATE_FIELDS:
        if field not in summary:
            return 1, f"fail: summary is missing the required key {field!r}"
        value = summary[field]
        if isinstance(value, bool) or not isinstance(value, int):
            return 1, f"fail: {field!r} is not an integer: {value!r}"
        if value < 0:
            return 1, f"fail: {field!r} is negative: {value}"
    return 0, (
        f"ok: runs={runs}"
        f" iterations={summary['iterations']}"
        f" artifacts={summary['artifacts']}"
        f" retries={summary['retries']}"
        f" parse_errors={summary['parse_errors']}"
    )


def main() -> int:
    """Read one summary document from stdin, print one line, and return the exit code."""
    try:
        document = json.loads(sys.stdin.read())
    except ValueError as exc:
        print(f"error: stdin is not one valid JSON document: {exc}", file=sys.stderr)
        return 2
    if not isinstance(document, dict):
        got = type(document).__name__
        print(f"error: expected one JSON object on stdin, got {got}", file=sys.stderr)
        return 2
    code, line = grade(document)
    print(line, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
