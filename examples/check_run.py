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

WHY IT ALSO READS THE CHECKPOINT BACK. Everything above grades the document's
IN-MEMORY claim: ``run --json`` builds it from the live ``RunState`` and never
consults the filesystem, so its ``run_id``/``status`` agree with the persisted
run by construction and by nobody. The README publishes that agreement as a
contract -- ``dispatched`` is "the machine-readable twin of the ``dispatched :``
summary ... with ``run_id``/``status`` matching that run dir's
``checkpoint.json``" -- and this repo's whole "resilient by design" thesis rests
on that file, while both graded gates check the run directory by EXISTENCE only.
So on the success path the run's own ``<run_dir>/checkpoint.json`` is read back
and the two published fields are reconciled against it. A truncated, empty or
contradictory checkpoint now fails a gate instead of passing one.

WHY AN ABSENT RUN DIRECTORY IS NOT A FAILURE. A document is a portable artifact:
a supervising script may legitimately grade one that was piped from another host
or replayed from a store, where the run directory the producer named simply does
not exist here. That is a cross-check which does not APPLY, not a run which
failed, so the reconciliation is skipped -- and the success line says so
explicitly (``checkpoint=not-on-this-host``), because an unreported skip would
read exactly like a verified join. When the directory IS present this is the
machine that ran it, and a missing or disagreeing checkpoint is graded hard.

WHY three exit codes rather than two: 0 the dispatched run succeeded, 1 the
document parsed and the run did not verifiably succeed, 2 stdin was not one JSON
object. A caller can therefore tell a bad pipe from a bad run, and 2 matches the
CLI's own usage-error code. Every checkpoint failure -- absent, unreadable,
unparseable, or contradicting the document -- REUSES 1 rather than adding a
fourth code: a run whose persisted state cannot be read back or disagrees with
what was published has not verifiably succeeded, which is what 1 already means.

Standard library only, no network, no ``jq``::

    pla run ... --json | python examples/check_run.py
    pla resume --run-dir DIR --json | python examples/check_run.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Final

from proactive_loop.models import RunStatus

#: The one value that means "this run reached its terminal success state".
SUCCESS_STATUS: str = RunStatus.DONE.value

#: The resumable state file every run persists inside its own run directory.
CHECKPOINT_NAME: Final = "checkpoint.json"

#: The two fields the README publishes as matching between the document and the
#: run dir's checkpoint. Kept a named constant so the failure message, the
#: comparison and the docs cannot drift into three different lists.
CROSS_CHECKED_FIELDS: Final = ("run_id", "status")

#: Reported on the success line when the published run directory is not present
#: here, so there is no persisted checkpoint of ours to reconcile against.
NOT_ON_THIS_HOST: Final = "not-on-this-host"


def dispatched_run(document: dict[str, Any]) -> dict[str, Any] | None:
    """Return the dispatched-run object inside ``document``, or ``None``.

    A top-level ``status`` means the document IS the dispatched run; otherwise it
    is the ``run --json`` wrapper and the run hangs off ``dispatched`` (which is
    ``null`` under ``--dry-run``, i.e. nothing was dispatched at all).
    """
    run = document if "status" in document else document.get("dispatched")
    return run if isinstance(run, dict) else None


def grade(document: dict[str, Any]) -> tuple[int, str]:
    """Return ``(exit_code, one_report_line)`` for one already-parsed document.

    Kept pure -- the caller owns stdin/stdout/stderr -- so the whole decision
    is inspectable without building a pipe.
    """
    run = dispatched_run(document)
    if run is None:
        return 1, "fail: no run was dispatched -- the document carries no run object"
    status = run.get("status")
    if status != SUCCESS_STATUS:
        return 1, f"fail: run did not reach {SUCCESS_STATUS} -- status={status}"
    # ``run_dir`` is on the line because ``run_id`` names the CHECKPOINT while
    # this is the value `pla resume --run-dir` and `pla trace --run-dir` accept,
    # so a reader of the success line can act on it without a second lookup.
    return 0, (
        f"ok: run_id={run.get('run_id', '')} status={status}"
        f" iterations={run.get('iterations_used', 0)}"
        f" llm_calls={run.get('llm_calls_used', 0)}"
        f" artifacts={len(run.get('artifacts') or ())}"
        f" run_dir={run.get('run_dir', '')}"
    )


def compare_checkpoint(run: dict[str, Any], checkpoint: Any) -> str | None:
    """Return a failure line when ``checkpoint`` contradicts ``run``, else ``None``.

    Kept pure -- ``main()`` owns path resolution and every filesystem error -- so
    the reconciliation itself is inspectable without planting files on a disk.

    Only ``CROSS_CHECKED_FIELDS`` are compared. The checkpoint also carries
    ``iterations_used``, ``llm_calls_used``, ``retries`` and ``parse_errors``, and
    reconciling those is a DIFFERENT claim from the one the README publishes; it
    is deliberately not asserted here rather than half-asserted.
    """
    if not isinstance(checkpoint, dict):
        got = type(checkpoint).__name__
        return f"fail: the persisted checkpoint is not a JSON object -- got {got}"
    for field in CROSS_CHECKED_FIELDS:
        published = run.get(field)
        persisted = checkpoint.get(field)
        if published != persisted:
            # BOTH values are named: "they disagree" alone leaves the reader
            # unable to tell which side is wrong or by how much.
            return (
                f"fail: the persisted checkpoint disagrees on {field} --"
                f" document={published!r} checkpoint={persisted!r}"
            )
    return None


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
    run = dispatched_run(document)
    # The reconciliation touches the filesystem ONLY for a document that already
    # graded 0: a run this consumer is rejecting anyway must not be able to make
    # it read a path. ``run`` is never None once ``grade`` returned 0 -- the test
    # narrows the type rather than asserting an invariant at runtime.
    if code == 0 and run is not None:
        published_dir = str(run.get("run_dir") or "")
        run_dir = Path(published_dir)
        checkpoint_path = run_dir / CHECKPOINT_NAME
        if not published_dir:
            code, line = 1, (
                "fail: the dispatched run publishes no run_dir, so its persisted"
                f" {CHECKPOINT_NAME} cannot be located"
            )
        elif not run_dir.is_dir():
            line = f"{line} checkpoint={NOT_ON_THIS_HOST}"
        else:
            try:
                raw = checkpoint_path.read_text(encoding="utf-8")
                checkpoint = json.loads(raw)
            except OSError as exc:
                code, line = 1, (
                    "fail: cannot read the persisted checkpoint"
                    f" {checkpoint_path}: {exc}"
                )
            except ValueError as exc:
                code, line = 1, f"fail: {checkpoint_path} is not valid JSON: {exc}"
            else:
                disagreement = compare_checkpoint(run, checkpoint)
                if disagreement is None:
                    line = f"{line} checkpoint=verified"
                else:
                    code, line = 1, disagreement
    print(line, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
