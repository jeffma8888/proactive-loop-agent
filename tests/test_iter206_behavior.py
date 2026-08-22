"""Black-box behavior tests for factory iteration 203 (foundry state iter-229) ---
``BrokenDocLinkCollector`` overlap-tests its inline-code mask against a link's
DESTINATION span instead of against the whole ``[text](target)`` match.

The defect this pins closed is a FAIL-OPEN in an ARMED kind: a prose link whose
*label* is wrapped in backticks (```` [`SPEC.md`](path.md) ````, the idiomatic way
to cite a file in Markdown) was invisible to the collector, because the mask that
correctly silences a link sitting *inside* a code span was compared against the
match's full span --- which a backticked label makes overlap a code range.  The
mask itself is right and stays: a link inside a fence, or one whose destination
lies inside a code span, is a documented sample, not a claim about the filesystem.
Only the compared RANGE changes.

MODULE NAME PROVENANCE: ``206`` is derived from the repository (``git ls-files
tests`` tops out at ``test_iter205``, and ``git cat-file -e
HEAD:tests/test_iter206_behavior.py`` exits 128), never from the foundry state-dir
number --- the two counters differ here and naming from the state dir overwrites a
shipped oracle.

ISOLATION CONTRACT (honored): every assertion below is written against THIS
iteration's spec (``pm.md`` "Expected Behaviors" 1-6) and drives only the public
surface ``BrokenDocLinkCollector().collect(root)``.  **No file under ``src/`` was
read, no engineer / reviewer note was read, and no ``git diff`` was consulted.**
The signal field names used here were taken from the RUNNING product (constructing
the public class and printing a signal's fields), which is the "read the product's
own help/output by running it" affordance the role grants, and from the existing
oracle ``tests/test_iter144_behavior.py``.

ANTI-VACUITY (deliberate): four of the six behaviors assert *zero* signals, and a
blind collector also emits zero.  So every silent arm is paired with a control
that must report --- either a same-file prose link (behaviors 3 and 4) or the
identical fixture with the destination deleted from disk (behavior 5).  Behavior 5's
pairing is the load-bearing one: under the pre-fix rule BOTH of its arms were
silent, so without the control the arm could not tell "silent because the target
resolves" from "silent because the collector cannot see backticked labels".

Fully offline and deterministic: no network, no subprocess, every fixture under
``tmp_path``, and no read of the ambient repository tree (so this module is
fresh-clone safe).
"""

from __future__ import annotations

import pathlib

from proactive_loop.collectors.base import ContextSignal
from proactive_loop.collectors.broken_link import BrokenDocLinkCollector

KIND = "broken_link"


# --------------------------------------------------------------------------
# Helpers (same shape as tests/test_iter144_behavior.py)
# --------------------------------------------------------------------------


def _write(path: pathlib.Path, *lines: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _collect(root: pathlib.Path) -> list[ContextSignal]:
    return BrokenDocLinkCollector().collect(root)


def _summaries(signals: list[ContextSignal]) -> list[str]:
    return [s.summary for s in signals]


# --------------------------------------------------------------------------
# Behavior 1 -- the plain prose link is unchanged (non-regression).
# --------------------------------------------------------------------------


def test_b1_plain_prose_link_reports_once_naming_target_and_line_one(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "docs.md", "See [SPEC.md](nope/missing.md) for details.")
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        "an unbacketed prose link to a missing target must still report exactly "
        f"once; got {_summaries(signals)}"
    )
    sig = signals[0]
    assert sig.kind == KIND, f"kind must be {KIND!r}; got {sig.kind!r}"
    assert "nope/missing.md" in sig.summary, (
        f"the summary must name the dead target; got {sig.summary!r}"
    )
    assert sig.summary.startswith("docs.md:1:"), (
        "the summary must carry the container and the 1-based line number; got "
        f"{sig.summary!r}"
    )


# --------------------------------------------------------------------------
# Behavior 2 -- THE FIX: a backticked LABEL no longer blinds the collector.
# --------------------------------------------------------------------------


def test_b2_backticked_label_reports_once_naming_target_and_line_one(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "docs.md", "See [`SPEC.md`](nope/missing.md) for details.")
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        "a backticked LABEL is prose formatting on the reader's side of the link, "
        "not a code sample: the dead destination must be reported exactly once; "
        f"got {_summaries(signals)}"
    )
    sig = signals[0]
    assert sig.kind == KIND, f"kind must be {KIND!r}; got {sig.kind!r}"
    assert "nope/missing.md" in sig.summary, (
        f"the summary must name the dead target; got {sig.summary!r}"
    )
    assert sig.summary.startswith("docs.md:1:"), (
        f"the summary must carry container and 1-based line; got {sig.summary!r}"
    )


def test_b2_backticked_label_and_plain_label_agree_field_for_field(
    tmp_path: pathlib.Path,
) -> None:
    """The backtick around the label must change NOTHING the collector reports."""
    plain = tmp_path / "plain"
    ticked = tmp_path / "ticked"
    _write(plain / "docs.md", "See [SPEC.md](nope/missing.md) for details.")
    _write(ticked / "docs.md", "See [`SPEC.md`](nope/missing.md) for details.")
    a = _collect(plain)
    b = _collect(ticked)
    assert len(a) == 1 and len(b) == 1, (
        f"both arms must report once; plain={_summaries(a)} ticked={_summaries(b)}"
    )
    assert (a[0].source, a[0].kind, a[0].summary, a[0].path, a[0].weight) == (
        b[0].source,
        b[0].kind,
        b[0].summary,
        b[0].path,
        b[0].weight,
    ), (
        "every reported field except the echoed source line must be identical; "
        f"plain={a[0].summary!r} ticked={b[0].summary!r}"
    )


# --------------------------------------------------------------------------
# Behavior 3 -- a WHOLE link inside one inline-code span stays silent.
# --------------------------------------------------------------------------


def test_b3_whole_link_inside_one_code_span_yields_zero(
    tmp_path: pathlib.Path,
) -> None:
    _write(
        tmp_path / "docs.md",
        "Tail prose with `[b](gone-in-inline-code.md)` inside code.",
    )
    signals = _collect(tmp_path)
    assert signals == [], (
        "a link wholly inside a code span is a documented sample, not a claim "
        f"about the filesystem; got {_summaries(signals)}"
    )


def test_b3_code_span_stays_silent_while_same_file_prose_reports(
    tmp_path: pathlib.Path,
) -> None:
    """Same-file positive control, so the zero above cannot pass vacuously."""
    _write(
        tmp_path / "docs.md",
        "Prose: [live](gone-prose.md)",
        "Tail prose with `[b](gone-in-inline-code.md)` inside code.",
    )
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        "exactly the prose link may report while the code-span link stays "
        f"silent; got {_summaries(signals)}"
    )
    assert "gone-prose.md" in signals[0].summary, (
        f"the positive control must be the reported one; got {signals[0].summary!r}"
    )


# --------------------------------------------------------------------------
# Behavior 4 -- a fenced block still suppresses (with a positive control).
# --------------------------------------------------------------------------


def test_b4_fenced_link_yields_zero(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path / "docs.md",
        "```",
        "[a](gone-in-fence.md)",
        "```",
    )
    signals = _collect(tmp_path)
    assert signals == [], (
        f"a link inside a fenced block must stay silent; got {_summaries(signals)}"
    )


def test_b4_fence_suppresses_and_closes_so_later_prose_reports(
    tmp_path: pathlib.Path,
) -> None:
    """Positive control: the fence must suppress and then CLOSE."""
    _write(
        tmp_path / "docs.md",
        "```",
        "[a](gone-in-fence.md)",
        "```",
        "After the fence: [`live`](gone-after-fence.md)",
    )
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        "only the post-fence prose link may report; got "
        f"{_summaries(signals)}"
    )
    assert "gone-after-fence.md" in signals[0].summary, (
        f"the post-fence link must be the reported one; got {signals[0].summary!r}"
    )


# --------------------------------------------------------------------------
# Behavior 5 -- un-blinding must not manufacture a finding for a LIVE target.
# --------------------------------------------------------------------------


def test_b5_backticked_label_with_existing_target_yields_zero(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "real.md", "I exist.")
    _write(tmp_path / "docs.md", "See [`real.md`](real.md) for details.")
    signals = _collect(tmp_path)
    assert signals == [], (
        "a backticked-label link whose target EXISTS must stay silent -- "
        f"un-blinding must not manufacture findings; got {_summaries(signals)}"
    )


def test_b5_silence_is_because_the_target_resolves_not_because_it_is_unseen(
    tmp_path: pathlib.Path,
) -> None:
    """The control that makes behavior 5 mean something.

    Under the pre-fix rule BOTH arms were silent, so the zero above alone cannot
    distinguish "silent because the target resolves" from "silent because a
    backticked label hides the link".  Byte-identical Markdown, one arm with the
    target on disk and one without: the arms must DIFFER.
    """
    lives = tmp_path / "lives"
    dies = tmp_path / "dies"
    line = "See [`real.md`](real.md) for details."
    _write(lives / "docs.md", line)
    _write(lives / "real.md", "I exist.")
    _write(dies / "docs.md", line)

    resolving = _collect(lives)
    dangling = _collect(dies)
    assert resolving == [], (
        f"the resolving arm must stay silent; got {_summaries(resolving)}"
    )
    assert len(dangling) == 1, (
        "the identical Markdown with the target ABSENT must report -- otherwise "
        "the resolving arm's silence proves nothing; got "
        f"{_summaries(dangling)}"
    )
    assert "real.md" in dangling[0].summary, (
        f"the dangling arm must name the target; got {dangling[0].summary!r}"
    )


# --------------------------------------------------------------------------
# Behavior 6 -- the angle-bracketed destination alternative, same rule.
# --------------------------------------------------------------------------


def test_b6_backticked_label_with_angle_bracketed_target_reports_unbracketed(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "docs.md", "See [`a`](<gone doc.md>) here.")
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        "the destination-span rule must apply to the <angle-bracketed> "
        f"alternative too; got {_summaries(signals)}"
    )
    summary = signals[0].summary
    assert "gone doc.md" in summary, (
        "the summary must name the destination WITHOUT its angle brackets; got "
        f"{summary!r}"
    )
    assert "<gone doc.md>" not in summary, (
        f"the angle brackets are delimiters, not part of the path; got {summary!r}"
    )


def test_b6_angle_bracketed_target_that_exists_stays_silent(
    tmp_path: pathlib.Path,
) -> None:
    """Control for behavior 6: the angle-bracket arm is not report-everything."""
    _write(tmp_path / "here doc.md", "I exist.")
    _write(tmp_path / "docs.md", "See [`a`](<here doc.md>) here.")
    signals = _collect(tmp_path)
    assert signals == [], (
        "an <angle-bracketed> destination that EXISTS must stay silent; got "
        f"{_summaries(signals)}"
    )


# --------------------------------------------------------------------------
# Behavior 2, extended to the image form.  NOT in pm.md's enumerated list, but
# SPEC.md:432 puts `![alt](target)` in this collector's scope in the same breath
# as `[text](target)`, so a backticked ALT is the exact same fail-open as a
# backticked LABEL and nothing else in tests/ pins it.
# --------------------------------------------------------------------------


def test_b2_image_with_backticked_alt_reports_its_missing_target(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "docs.md", "See ![`alt`](nope/missing.png) here.")
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        "an image whose ALT text is backticked is the same fail-open as a "
        "backticked link label; SPEC.md:432 keeps `![alt](target)` in scope; got "
        f"{_summaries(signals)}"
    )
    assert "nope/missing.png" in signals[0].summary, (
        f"the summary must name the missing image target; got {signals[0].summary!r}"
    )


def test_b2_image_with_backticked_alt_and_existing_target_stays_silent(
    tmp_path: pathlib.Path,
) -> None:
    """Control: the image arm is not report-everything."""
    (tmp_path / "real.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    _write(tmp_path / "docs.md", "See ![`alt`](real.png) here.")
    signals = _collect(tmp_path)
    assert signals == [], (
        f"an image whose target EXISTS must stay silent; got {_summaries(signals)}"
    )
