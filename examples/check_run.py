"""Grade one machine-readable run document read from stdin.

WHY this file exists. Four verbs publish JSON documents (``run --json``,
``dispatch --json``, ``resume --json``, ``scan --snapshot``) and until this
iteration NOTHING in the repo consumed one outside ``tests/``: the README sells
``pla run ... --json | jq`` while ``jq`` can never be a dependency of an
offline-first project, so the advertised integration shipped with no runnable
proof. This is that proof, and it is the smallest useful one -- the question a
supervising script actually asks: *did the run I just launched succeed?*

WHY one consumer serves three verbs. ``run --json`` NESTS the nine-key
dispatched document under its ``dispatched`` key; ``dispatch --json`` and
``resume --json`` publish that SAME document at top level. So a top-level
``status`` key discriminates the two shapes unambiguously: the ``run --json``
wrapper publishes exactly six keys and ``status`` is not among them.

WHY the success value is imported and never typed. The terminal success status
is ``done`` -- not the ``completed`` a careful reader guesses, which is exactly
what this consumer's own first draft guessed. Deriving it from
``proactive_loop.models.RunStatus.DONE.value`` makes the published contract
executable: rename that enum member and THIS script fails loudly, instead of a
stranger's script silently reporting failure on every successful run.

WHY three exit codes rather than two: 0 the dispatched run succeeded, 1 the
document parsed and the run did not succeed, 2 stdin was not one JSON object.
A caller can therefore tell a bad pipe from a bad run, and 2 matches the CLI's
own usage-error code.

Standard library only, no network, no ``jq``::

    pla run ... --json | python examples/check_run.py
    pla resume --run-dir DIR --json | python examples/check_run.py
"""

from __future__ import annotations

import json
import sys
from typing import Any

from proactive_loop.models import RunStatus

#: The one value that means "this run reached its terminal success state".
SUCCESS_STATUS: str = RunStatus.DONE.value


def grade(document: dict[str, Any]) -> tuple[int, str]:
    """Return ``(exit_code, one_report_line)`` for one already-parsed document.

    Kept pure -- the caller owns stdin/stdout/stderr -- so the whole decision
    is inspectable without building a pipe.
    """
    # A top-level ``status`` means the document IS the dispatched run; otherwise
    # it is the ``run --json`` wrapper and the run hangs off ``dispatched``.
    run = document if "status" in document else document.get("dispatched")
    if not isinstance(run, dict):
        return 1, "fail: no run was dispatched -- the document carries no run object"
    status = run.get("status")
    if status != SUCCESS_STATUS:
        return 1, f"fail: run did not reach {SUCCESS_STATUS} -- status={status}"
    return 0, (
        f"ok: run_id={run.get('run_id', '')} status={status}"
        f" iterations={run.get('iterations_used', 0)}"
        f" llm_calls={run.get('llm_calls_used', 0)}"
        f" artifacts={len(run.get('artifacts') or ())}"
    )


def main() -> int:
    """Read one document from stdin, print one line, and return the exit code."""
    try:
        # ValueError covers both failure modes of this one read: a JSONDecodeError
        # from malformed text and a UnicodeDecodeError from undecodable bytes.
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
