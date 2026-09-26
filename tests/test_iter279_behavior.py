"""Black-box oracle for foundry iteration 319's RELOCATION half (state-dir iteration 465),
written by the tester from the spec's Expected Behavior 7 alone.

WHY THIS MODULE EXISTS. Iteration 464 built and graded ``pla diff --fail-on-change`` GREEN
(``tests/test_iter277_behavior.py`` + ``tests/test_iter278_behavior.py``) and reverted for
ONE reason: the mandatory ``--fail-on-change`` clause pushed ``SPEC.md`` 284 B over the
95,500-B ceiling. This iteration pays for it by moving ONE settled paragraph -- the 1,936-B
``# executor.py`` contract prose (24 two-space-indented lines from ``Per iteration: PLAN``
to ```resume` continues from a loaded RunState.``) -- into ``SPEC_ARCHIVE.md`` verbatim.

WHAT THIS MODULE GRADES. The relocation as a reader sees it, durably (no dependence on
which commit ``HEAD`` is): (1) the archive holds the paragraph byte-for-byte under its own
``### 4.4`` heading, INSERTED before ``### 4.2 llm/providers.py`` rather than appended
(appending would move the archive's graded tail); (2) ``SPEC.md`` no longer carries the
paragraph, yet keeps the ``# executor.py`` code fence, the ``- Tests:`` bullet, and in the
gap exactly one <= 500-B summary paragraph that names every stop and fail-safe the moved
text contracted and ends with the ``[SPEC_ARCHIVE.md](SPEC_ARCHIVE.md)`` pointer.

ISOLATION CONTRACT (honored). Reads the two Markdown files as a consumer would; no
implementation import, no subprocess, no network. Deterministic and offline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
SPEC: Final[Path] = REPO / "SPEC.md"
ARCHIVE: Final[Path] = REPO / "SPEC_ARCHIVE.md"

#: First and last of the 24 relocated lines, byte-for-byte (two-space indent included).
PARAGRAPH_FIRST_LINE: Final[str] = (
    '  Per iteration: PLAN — LLM returns JSON `{"thought": str, "action": {"tool": str,'
)
PARAGRAPH_LAST_LINE: Final[str] = "  `resume` continues from a loaded RunState."
PARAGRAPH_LINES: Final[int] = 24
PARAGRAPH_BYTES: Final[int] = 1_936
#: Sentences that lived ONLY in the moved paragraph -- present in the archive, gone from SPEC.
MOVED_ONLY_FINGERPRINTS: Final[tuple[str, ...]] = (
    "The WARNING is the degradation twin",
    "PRESENT-but-non-boolean `done`",
    "prefix disjoint from `L0 retry `",
)
ARCHIVE_HEADING: Final[str] = "### 4.4 loop -- executor.py (relocated at foundry iter 319)"
ARCHIVE_NEXT_HEADING: Final[str] = "### 4.2 llm/providers.py"
FENCE_MARKER: Final[str] = "# executor.py"
TESTS_BULLET_PREFIX: Final[str] = "- Tests: `tests/test_loop.py`"
POINTER: Final[str] = "[SPEC_ARCHIVE.md](SPEC_ARCHIVE.md)"
MAX_SUMMARY_BYTES: Final[int] = 500
#: What the summary must still promise in SPEC.md after the move (spec step 2).
SUMMARY_MUST_NAME: Final[tuple[str, ...]] = (
    "PLAN",
    "ACT",
    "CHECK",
    "`with_retry`",
    "checkpoint",
    "DONE",
    "BUDGET_EXHAUSTED",
    "`L1 degraded `",
    "`RunState.parse_errors`",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _relocated_block(archive: str) -> list[str]:
    """The lines between the 4.4 heading and the next ``### `` heading, blanks stripped."""
    start = archive.index(ARCHIVE_HEADING) + len(ARCHIVE_HEADING)
    end = archive.index("\n### ", start)
    body = archive[start:end]
    assert body.startswith("\n\n"), "one blank line must separate the heading from the prose"
    # ``body`` stops at the newline that opens ``\n### 4.2``; a trailing newline of its own
    # therefore means exactly one blank line separates the prose from the next heading.
    assert body.endswith(".\n"), "one blank line must separate the prose from the next heading"
    return body.strip("\n").split("\n")


# ===========================================================================
# Behavior 7 (archive side) -- the paragraph lives in SPEC_ARCHIVE.md byte-for-byte, under
# its own heading, INSERTED before 4.2 rather than appended.
# ===========================================================================


def test_b7a_archive_holds_the_executor_paragraph_verbatim_before_section_4_2() -> None:
    archive = _read(ARCHIVE)
    assert archive.count(ARCHIVE_HEADING) == 1, "exactly one relocated-executor heading"
    heading_at = archive.index(ARCHIVE_HEADING)
    next_at = archive.index(ARCHIVE_NEXT_HEADING)
    assert heading_at < next_at, (
        "the executor section must be INSERTED before `### 4.2`; appending after it moves "
        "the archive tail that test_iter255 pins byte-identical"
    )
    assert archive.index("\n---\n") < heading_at, "the section sits below the header rule"

    lines = _relocated_block(archive)
    assert lines[0] == PARAGRAPH_FIRST_LINE, lines[0]
    assert lines[-1] == PARAGRAPH_LAST_LINE, lines[-1]
    assert len(lines) == PARAGRAPH_LINES, len(lines)
    assert all(line.startswith("  ") for line in lines), "two-space indent preserved verbatim"
    paragraph = "\n".join(lines) + "\n"
    assert len(paragraph.encode("utf-8")) == PARAGRAPH_BYTES, len(paragraph.encode("utf-8"))
    for needle in MOVED_ONLY_FINGERPRINTS:
        assert needle in paragraph, needle
    # The heading immediately precedes the block and the block immediately precedes 4.2:
    # nothing else was slipped into the archive alongside the move.
    assert archive.index("\n### ", heading_at + 1) == archive.index("\n" + ARCHIVE_NEXT_HEADING)


# ===========================================================================
# Behavior 7 (SPEC.md side) -- the paragraph is gone, the fence and the `- Tests:` bullet
# stay, and the gap holds exactly one <= 500-B summary ending in the archive pointer.
# ===========================================================================


def _executor_gap(spec: str) -> str:
    """The text between the closing fence of the ``# executor.py`` block and its bullet."""
    fence_open = spec.index("```python\n" + FENCE_MARKER + "\n")
    fence_close = spec.index("\n```\n", fence_open) + len("\n```\n")
    bullet_at = spec.index("\n" + TESTS_BULLET_PREFIX, fence_close)
    return spec[fence_close:bullet_at]


def test_b7b_spec_keeps_the_fence_and_bullet_around_one_bounded_summary_with_a_pointer() -> None:
    spec = _read(SPEC)
    assert "### 4.4 loop" in spec, "the archive rule: SPEC.md keeps every heading"
    assert spec.count(FENCE_MARKER) == 1, "the `# executor.py` code fence stays exactly once"
    assert PARAGRAPH_FIRST_LINE not in spec, "the moved paragraph must not also stay in SPEC.md"
    for needle in MOVED_ONLY_FINGERPRINTS:
        assert needle not in spec, f"moved prose still in SPEC.md: {needle!r}"

    gap = _executor_gap(spec)
    assert gap.startswith("\n"), "one blank line separates the fence from the summary"
    summary = gap.strip("\n")
    assert summary, "the moved body must be replaced by a summary, not by nothing"
    assert "\n\n" not in summary, "exactly ONE paragraph replaces the moved body"
    lines = summary.split("\n")
    assert all(line.startswith("  ") and not line.startswith("   ") for line in lines), (
        "the summary keeps the section's two-space prose indent on every line"
    )
    size = len(summary.encode("utf-8"))
    assert size <= MAX_SUMMARY_BYTES, f"summary is {size} B; the pointer budget is 500 B"
    assert summary.endswith(POINTER + "."), (
        f"the summary must end with the archive pointer sentence; tail: {summary[-80:]!r}"
    )
    assert summary.count(POINTER) == 1, summary
    for needle in SUMMARY_MUST_NAME:
        assert needle in summary, f"summary lost the contract term {needle!r}"
    # The `- Tests:` bullet follows the summary on the very next line: ``gap`` stops at the
    # newline that opens ``\n- Tests:``, so a trailing newline here would be a blank line.
    assert not gap.endswith("\n"), repr(gap[-20:])


# ===========================================================================
# Behavior 6 (SPEC.md side) -- the flag that cost iteration 464 its ship is documented on
# the `diff` usage line AND in a gate clause against exit 5, and the relocation left the
# document >= 1,100 B under test_iter255's ceiling (not merely at it).
# ===========================================================================


def test_b7c_spec_names_the_flag_on_the_diff_usage_line_and_gate_clause_under_the_ceiling() -> None:
    from tests.test_iter255_behavior import SPEC_CEILING_AFTER_SLICE

    spec = _read(SPEC)
    section_4_5 = spec[spec.index("### 4.5 cli"):]
    usage = [line for line in section_4_5.splitlines() if "`pla diff --old" in line]
    assert len(usage) == 1, usage
    assert "[--fail-on-change]" in usage[0], usage[0]
    assert "--json" in usage[0] and usage[0].index("--json") < usage[0].index("--fail-on-change")
    gate_clause = section_4_5[section_4_5.index("`--fail-on-change` opts into"):]
    assert "gate code `5`" in gate_clause[:400], gate_clause[:400]
    assert "gate: fail-on-change tripped -- added=A removed=R changed=C" in gate_clause[:600], (
        gate_clause[:600]
    )
    assert "stdout untouched" in gate_clause[:600], gate_clause[:600]

    size = len(spec.encode("utf-8"))
    bought = PARAGRAPH_BYTES - MAX_SUMMARY_BYTES  # >= 1,436 B the move must have freed
    assert size <= SPEC_CEILING_AFTER_SLICE - 1_100, (
        f"SPEC.md is {size} B; relocating the {PARAGRAPH_BYTES}-B paragraph behind a "
        f"<= {MAX_SUMMARY_BYTES}-B summary frees >= {bought} B, so the document must sit "
        f">= 1,100 B under the {SPEC_CEILING_AFTER_SLICE}-B ceiling, not 18 B like iter 464"
    )
