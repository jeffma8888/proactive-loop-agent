"""Unit tests for the INTERNAL merge-conflict helper `_count_markers`.

Scope (engineer-owned, per the role split): this file exercises ONLY the pure,
module-private counting function in isolation -- the load-bearing "detection
rule" of iter-28 (which raw lines are marker lines, and that the ambiguous
`=======` separator is never counted). The end-to-end black-box behavior suite
(`test_iter28_behavior.py`, driven through `main([...])` and the public
collector API) is owned by the test engineer; nothing here overlaps that surface.
"""

from __future__ import annotations

from proactive_loop.collectors.merge_conflict import _count_markers


def test_standard_single_block_counts_open_plus_close_only() -> None:
    # <<<<<<< HEAD / ======= / >>>>>>> feature -> the separator is NOT counted.
    text = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> feature\n"
    assert _count_markers(text) == 2


def test_two_blocks_sum_to_four() -> None:
    text = (
        "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> x\n"
        "mid\n"
        "<<<<<<< HEAD\nc\n=======\nd\n>>>>>>> y\n"
    )
    assert _count_markers(text) == 4


def test_orphaned_close_marker_counts_one() -> None:
    assert _count_markers("keep\n>>>>>>> feature\nmore\n") == 1


def test_orphaned_open_marker_counts_one() -> None:
    assert _count_markers("<<<<<<< HEAD\nonly one side left\n") == 1


def test_bare_separator_and_setext_underline_count_zero() -> None:
    # A bare seven-equals separator and a long Markdown setext-H1 underline are
    # both benign -- neither starts with an open/close prefix.
    assert _count_markers("Title\n=======\nbody\n") == 0
    assert _count_markers("Heading\n==================\nbody\n") == 0


def test_prefix_precision_rejects_near_misses() -> None:
    # Eight chevrons, seven-with-no-space, bare seven, and an INDENTED marker are
    # all NOT marker lines: only the exact 7-chevron-plus-space prefix at column 0.
    for line in ("<<<<<<<<", "<<<<<<<foo", "<<<<<<<", "    <<<<<<< HEAD",
                 ">>>>>>>>", ">>>>>>>foo", ">>>>>>>", "\t>>>>>>> feature"):
        assert _count_markers(line + "\n") == 0, line


def test_marker_with_trailing_content_after_the_space_counts() -> None:
    # The space is required, but any label after it is fine (git writes a ref).
    assert _count_markers("<<<<<<< HEAD\n") == 1
    assert _count_markers(">>>>>>> some/long branch name\n") == 1


def test_empty_and_marker_free_text_count_zero() -> None:
    assert _count_markers("") == 0
    assert _count_markers("just\nnormal\ncode\n") == 0
