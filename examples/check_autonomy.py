"""Grade the autonomy audit ``pla explain --json`` publishes, read from stdin.

WHAT IT GRADES. ``SPEC.md``'s autonomy contract is this product's headline
claim: a goal in a sensitive category ALWAYS needs human approval, at any
score, and nothing may auto-dispatch below the published threshold. ``make
demo`` publishes the audit for the very slate both graded gates read, and until
this script existed every graded step passed on an audit that auto-dispatched
the top-scoring sensitive goal -- advertised, unenforced, on a public repo.

WHY THE SENSITIVE SET IS IMPORTED, NEVER SPELLED. ``Settings.from_env()`` owns
it, so this file carries no category literal: change the effective set (its
default, or ``PLA_SENSITIVE_CATEGORIES``) and the verdict follows with no edit
here. A spelled copy could only ever agree with a stale version of itself.

WHY A VACUOUS AUDIT FAILS. An audit with no auto-dispatched goal, or none in a
sensitive category, cannot exercise either rule -- so emptying it would turn
the gate green. A gate proven green but never proven to fire is fail-open.

Exit codes: 0 the audit honors the contract, 1 it does not (or cannot exercise
it), 2 stdin was not one JSON array of objects. Full rationale lives in this
iteration's spec. Standard library plus ``proactive_loop`` only, no network::

    pla explain --slate .pla_runs/slate.json --json > .pla_runs/explain.json
    python examples/check_autonomy.py < .pla_runs/explain.json
"""

from __future__ import annotations

import json
import sys
from typing import Any, Final

from proactive_loop.config import Settings

#: The one decision value that means "this goal runs with no human in the loop".
#: Every rule below is about entries carrying exactly this value.
AUTO_DISPATCH: Final = "auto_dispatch"

#: Every key this grader reads, named once so the missing-key report and the
#: rules cannot drift into two different lists. The audit publishes twelve keys
#: and this asks for nothing beyond these five -- the other seven are the
#: reader-facing narrative, not the contract.
REQUIRED_KEYS: Final = ("id", "category", "score", "decision", "auto_dispatch_threshold")

#: The two required keys a rule COMPARES rather than merely reads. Present but
#: non-numeric, they would make ``score < threshold`` raise instead of decide,
#: so they are validated up front and reported like any other bad entry.
NUMERIC_KEYS: Final = ("score", "auto_dispatch_threshold")


def sensitive_values() -> frozenset[str]:
    """Return the effective sensitive-category VALUES, derived from the product.

    ``Settings.sensitive_categories`` holds ``GoalCategory`` members while the
    audit publishes plain strings, so the enum values are what compare.
    """
    return frozenset(c.value for c in Settings.from_env().sensitive_categories)


def find_bad_entry(audit: list[dict[str, Any]]) -> str | None:
    """Return a failure line for the first unusable entry, else ``None``.

    Kept separate from the rules so a malformed audit is never silently graded
    as compliant: an entry missing ``decision`` would otherwise simply fail to
    match ``AUTO_DISPATCH`` and pass, which is fail-open.
    """
    for index, entry in enumerate(audit):
        for key in REQUIRED_KEYS:
            if key not in entry:
                return (
                    f"fail: audit entry {index} is missing the required key"
                    f" {key!r} -- keys present: {sorted(entry)}"
                )
        for key in NUMERIC_KEYS:
            value = entry[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return (
                    f"fail: audit entry {index} has a non-numeric {key!r}"
                    f" ({value!r}), so the threshold rule cannot be decided"
                )
    return None


def grade(audit: list[dict[str, Any]], sensitive: frozenset[str]) -> tuple[int, str]:
    """Return ``(exit_code, one_report_line)`` for one already-parsed audit.

    Kept pure -- the caller owns stdin/stdout/stderr and the environment -- so
    the whole decision is inspectable without building a pipe.

    Rule ORDER is deliberate: real violations are reported BEFORE vacuity,
    because a narrow audit can be both an outright violation and too thin to
    exercise the other rule, and the violation is the actionable half.
    """
    if (bad := find_bad_entry(audit)) is not None:
        return 1, bad

    for entry in audit:
        if entry["decision"] == AUTO_DISPATCH and entry["category"] in sensitive:
            return 1, (
                f"fail: goal {entry['id']} is in sensitive category"
                f" {entry['category']!r} and marked {AUTO_DISPATCH} -- a"
                " sensitive goal needs human approval at ANY score"
            )

    for entry in audit:
        score, threshold = entry["score"], entry["auto_dispatch_threshold"]
        if entry["decision"] == AUTO_DISPATCH and score < threshold:
            return 1, (
                f"fail: goal {entry['id']} is marked {AUTO_DISPATCH} at score"
                f" {score}, below its own auto_dispatch_threshold {threshold}"
            )

    # The three counts are on BOTH outcome lines, so a reader can tell a
    # contract that holds from one that was never tested without re-running.
    counts = (
        f"audited={len(audit)}"
        f" {AUTO_DISPATCH}={sum(1 for e in audit if e['decision'] == AUTO_DISPATCH)}"
        f" sensitive={sum(1 for e in audit if e['category'] in sensitive)}"
    )
    if not audit or f" {AUTO_DISPATCH}=0" in counts or " sensitive=0" in counts:
        return 1, (
            f"fail: this audit cannot exercise the autonomy contract -- {counts};"
            f" it needs at least one {AUTO_DISPATCH} goal and at least one goal"
            " in a sensitive category, or the gate passes vacuously"
        )
    return 0, f"ok: the autonomy contract holds -- {counts}"


def main() -> int:
    """Read one audit from stdin, print one line, and return the exit code."""
    try:
        # ValueError covers both failure modes of this one read: a
        # JSONDecodeError from malformed text and a UnicodeDecodeError from
        # undecodable bytes.
        audit = json.loads(sys.stdin.read())
    except ValueError as exc:
        print(f"error: stdin is not one valid JSON document: {exc}", file=sys.stderr)
        return 2
    if not isinstance(audit, list):
        got = type(audit).__name__
        print(f"error: expected one JSON array on stdin, got {got}", file=sys.stderr)
        return 2
    for index, entry in enumerate(audit):
        if not isinstance(entry, dict):
            got = type(entry).__name__
            print(
                f"error: audit entry {index} is not a JSON object, got {got}",
                file=sys.stderr,
            )
            return 2
    try:
        sensitive = sensitive_values()
    except ValueError as exc:
        # A malformed PLA_* override is a USAGE error, which is what 2 already
        # means here and in the CLI -- not an audit that failed the contract.
        print(f"error: cannot read the sensitive-category set: {exc}", file=sys.stderr)
        return 2
    code, line = grade(audit, sensitive)
    print(line, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
