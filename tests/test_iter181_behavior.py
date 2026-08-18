"""Black-box behavior tests for state-dir iteration 177 (ships as ``factory iter 181``).

Feature under test: ``TodoCollector``'s per-line pass prefilters its INLINE-TAG
regex and its CHECKBOX regex INDEPENDENTLY, using a mechanically-derived token
set ``TODO_PREFILTER_TOKENS``, with byte-identical signal output.

MODULE NAME. This repo names behavior modules by the FACTORY iteration number,
which runs ahead of the state-dir counter (``tests/test_iter109_behavior.py``
documents the offset for itself). ``test_iter177..180_behavior.py`` are all
shipped oracles, so state-dir 177 is factory 181 and this file is 181 -- writing
177 would have SILENTLY OVERWRITTEN a shipped oracle (the iter-172 destroyed-
oracle lesson), and the spec's acceptance criteria name
``tests/test_iter181_behavior.py`` explicitly.

WHY THE TOKENS EXCLUDE THE LETTER ``i``. The obvious prefilter is
``("todo", "fixme", "xxx")``, and it is UNSOUND: the shipped inline regex runs
under ``re.IGNORECASE``, where U+0131 LATIN SMALL LETTER DOTLESS I matches the
pattern letter ``i``, but ``"# F\u0131XME: dotless i".lower()`` does NOT contain
the literal ``"fixme"`` (and ``.casefold()`` does not rescue it either). A
prefilter keyed on ``"fixme"`` therefore SKIPS that file and SILENTLY DROPS a
real L2 signal -- exactly the failure roadmap row #129 warns about. The shipped
token set is the longest contiguous run of ASCII-case-stable letters per tag,
so ``fixme`` contributes ``xme`` and no token contains ``i``.

ISOLATION CONTRACT (honored, no exceptions). Every assertion is derived from this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
conventions, and the product's OBSERVABLE output obtained by RUNNING it. **No
file under ``src/`` was read, no ``git diff`` was inspected, and neither
``engineer.md`` nor ``reviewer.md`` was opened.** Fully offline and
deterministic: no network, no API key, no subprocess.

NO TIMING ASSERTIONS. The measured win (34% of the per-line loop) is recorded in
the commit message, per row #129's own warning; nothing here asserts on a
duration, and behaviors 5 and 6 prove the skip STRUCTURALLY instead, by making
the skipped regex raise if it is ever consulted.

NO INDENTATION ASSERTIONS. CI is a 3.12 + 3.13 matrix and 3.13 strips the common
leading indent from docstrings at compile time, so nothing here asserts on
docstring or comment indentation.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.collectors import todos as todos_mod
from proactive_loop.collectors.todos import (
    TODO_PREFILTER_TOKENS,
    TodoCollector,
    clear_todo_memo,
    todo_memo_stats,
)

# The dotless-i sample, spelled as an escape so the file stays ASCII-safe.
DOTLESS: Final[str] = "# F\u0131XME: dotless i"


def test_b03_prefilter_tokens_are_a_named_derived_constant() -> None:
    """Spec behavior 3: the token set is a public module constant, and no token
    contains the letter ``i`` (the unsound one)."""
    assert TODO_PREFILTER_TOKENS == ("todo", "xme", "xxx"), TODO_PREFILTER_TOKENS
    for token in TODO_PREFILTER_TOKENS:
        assert "i" not in token, token


def test_b02_dotless_i_regression_oracle() -> None:
    """Spec behavior 2: the dotless-i signal survives the prefilter.

    ``_INLINE_TAG_RE`` matches U+0131 under ``re.IGNORECASE``, but neither
    ``.lower()`` nor ``.casefold()`` of this text contains the literal
    ``"fixme"``, so a prefilter keyed on ``"fixme"`` would drop this signal.
    """
    # The premise, re-measured rather than asserted in prose.
    assert "fixme" not in DOTLESS.lower()
    assert "fixme" not in DOTLESS.casefold()

    items = todos_mod._scan_items(DOTLESS + "\n")
    assert items == ((1, "FIXME: dotless i", DOTLESS, 1.0),), items


def test_b02_dotless_i_survives_a_whole_collect(tmp_path: Path) -> None:
    """Behavior 2, end to end: the dotless-i file is not skipped by the collector
    either, so the regression oracle is not confined to the pure unit."""
    (tmp_path / "dotless.py").write_text(DOTLESS + "\n", encoding="utf-8")
    clear_todo_memo()
    sigs = TodoCollector().collect(tmp_path)
    assert [(s.path, s.summary, s.weight) for s in sigs] == [
        ("dotless.py:1", "FIXME: dotless i", 1.0)
    ], sigs


# ----------------------------------------------------------------------------
# Behavior 1 -- signal-set equivalence on a planted tree
# ----------------------------------------------------------------------------

# The spec's six one-line files. ``clean.py`` holds NO prefilter token and no
# ``[``, so both passes are skipped for it and it must contribute nothing.
_PLANTED: Final[dict[str, str]] = {
    "dotless.py": DOTLESS + "\n",
    "boxonly.md": "- [ ] ship the thing\n",
    "lower.py": "# todo: lowercase tag\n",
    "mixed.py": "# Xxx mixed case\n",
    "clean.py": "print('nothing here')\n",
    "starbox.md": "* [ ] star bullet\n",
}

# Measured, not predicted -- the spec states these five rows and this order.
_EXPECTED_ROWS: Final[tuple[tuple[str, str, float], ...]] = (
    ("boxonly.md:1", "TODO: ship the thing", 0.8),
    ("dotless.py:1", "FIXME: dotless i", 1.0),
    ("lower.py:1", "TODO: lowercase tag", 1.0),
    ("mixed.py:1", "XXX: mixed case", 1.0),
    ("starbox.md:1", "TODO: star bullet", 0.8),
)


def test_b01_planted_tree_emits_exactly_the_five_expected_signals(tmp_path: Path) -> None:
    """Spec behavior 1: five signals, all ``kind == "todo"``, in the stated order
    of ``(path, summary, weight)``; ``clean.py`` contributes nothing."""
    for name, content in _PLANTED.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    clear_todo_memo()
    sigs = TodoCollector().collect(tmp_path)

    rows = tuple((s.path, s.summary, s.weight) for s in sigs)
    assert len(sigs) == 5, f"expected exactly five signals; got {rows!r}"
    assert rows == _EXPECTED_ROWS, f"\n  got={rows!r}\n  want={_EXPECTED_ROWS!r}"
    assert {s.kind for s in sigs} == {"todo"}, {s.kind for s in sigs}

    # The one file that must be skipped by BOTH passes contributes nothing.
    assert not [s for s in sigs if s.path.startswith("clean.py")], rows


# ----------------------------------------------------------------------------
# Behavior 4 -- soundness RE-DERIVED over a stated codepoint range
# ----------------------------------------------------------------------------

# Every letter that appears in an alternative of the inline tag regex
# (``todo`` | ``fixme`` | ``xxx``). The scan class is this SUPERSET of the token
# letters, not the token letters alone -- see AMBIGUITY NOTE 1 at the bottom of
# this module: the spec's own non-vacuity example (U+0130 matching ``i``) is only
# reachable if ``i`` and ``f`` are in the scanned class, and scanning a superset
# can only make the zero-violation claim STRONGER.
_TAG_LETTERS: Final[tuple[str, ...]] = tuple(sorted(set("todo" + "fixme" + "xxx")))
_TOKEN_LETTERS: Final[frozenset[str]] = frozenset("".join(TODO_PREFILTER_TOKENS))

# Scanned range, stated rather than implied. Lone surrogates are excluded: they
# are not characters, cannot appear in text decoded from a file, and are not
# encodable, so including them would test nothing real.
_SCAN_LO: Final[int] = 0x80
_SCAN_HI: Final[int] = 0x110000


def _non_ascii_case_hits() -> list[int]:
    """Every codepoint in ``[0x80, 0x110000)`` that an IGNORECASE character class
    over ``_TAG_LETTERS`` matches. ONE scan, not one per letter (the per-letter
    shape costs ~1.0s and the spec rejects it)."""
    pattern = re.compile("[" + "".join(_TAG_LETTERS) + "]", re.IGNORECASE)
    haystack = "".join(
        chr(cp) for cp in range(_SCAN_LO, _SCAN_HI) if not 0xD800 <= cp <= 0xDFFF
    )
    return [ord(m.group(0)) for m in pattern.finditer(haystack)]


def _violations(hits: list[int], letters: Iterable[str]) -> dict[str, list[int]]:
    """Codepoints that MATCH a letter under IGNORECASE yet do NOT contain that
    letter in ``chr(cp).lower()`` -- i.e. exactly the codepoints a prefilter keyed
    on that letter would wrongly skip."""
    per_letter = {L: re.compile(L, re.IGNORECASE) for L in letters}
    out: dict[str, list[int]] = {}
    for cp in hits:
        ch = chr(cp)
        low = ch.lower()
        for letter, rx in per_letter.items():
            if rx.fullmatch(ch) and letter not in low:
                out.setdefault(letter, []).append(cp)
    return out


def test_b04_no_token_letter_has_a_lowercase_blind_spot() -> None:
    """Spec behavior 4: over ``0x80..0x10FFFF``, no letter of any shipped token
    matches a codepoint whose ``.lower()`` lacks that letter -- so testing
    ``token in text.lower()`` can never skip a line the regex would have matched.

    Proven NON-VACUOUS two ways, both required, because a scan that found nothing
    would satisfy the zero-violation claim trivially.
    """
    hits = _non_ascii_case_hits()

    # Non-vacuity (a): the scan really does reach non-ASCII case-folding pairs.
    assert hits, "the IGNORECASE scan found no non-ASCII codepoints at all"
    assert 0x130 in hits, (
        "U+0130 LATIN CAPITAL LETTER I WITH DOT ABOVE must be among the hits; "
        f"got {[hex(c) for c in hits]!r}"
    )

    # The claim itself: zero blind spots among the letters actually shipped.
    bad = _violations(hits, _TOKEN_LETTERS)
    assert bad == {}, (
        "a shipped prefilter token letter has a lowercase blind spot: "
        + repr({k: [hex(c) for c in v] for k, v in bad.items()})
    )

    # Non-vacuity (b): the SAME derivation applied to ``i`` DOES find a violation,
    # which is precisely why no token contains ``i``.
    unsound = _violations(hits, {"i"})
    assert unsound.get("i") == [0x131], (
        "the derivation must still flag U+0131 for the letter i, or it cannot "
        f"detect a blind spot at all; got {unsound!r}"
    )
    assert "i" not in _TOKEN_LETTERS


# ----------------------------------------------------------------------------
# Behaviors 5 and 6 -- each pass is genuinely skipped, proven without timing
# ----------------------------------------------------------------------------


class _Boom:
    """A stand-in regex that fails loudly if it is ever consulted."""

    def search(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("inline tag regex was consulted")

    def match(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("checkbox regex was consulted")


@pytest.mark.parametrize(
    ("attr", "skipped_text", "consulted_text"),
    [
        # Behavior 5: no prefilter token -> the inline search() is skipped.
        ("_INLINE_TAG_RE", "print('nothing here')\n", "# TODO: real\n"),
        # Behavior 6: no literal '[' -> the checkbox match() is skipped.
        ("_CHECKBOX_RE", "no brackets here\n", "- [ ] x\n"),
    ],
)
def test_b05_b06_each_pass_is_skipped_and_still_reachable(
    monkeypatch: pytest.MonkeyPatch, attr: str, skipped_text: str, consulted_text: str
) -> None:
    """Two-sided by construction: the same sabotaged regex must NOT be consulted
    for text that cannot possibly match it, and MUST be consulted for text that
    can. A one-sided version of this test would pass against a regex that is
    never called at all."""
    monkeypatch.setattr(todos_mod, attr, _Boom())

    clear_todo_memo()
    assert todos_mod._scan_items(skipped_text) == (), (
        f"{attr} must be skipped for {skipped_text!r}"
    )

    clear_todo_memo()
    with pytest.raises(AssertionError):
        todos_mod._scan_items(consulted_text)


def test_b06_checkbox_pass_is_not_suppressed_by_the_inline_skip() -> None:
    """Spec behavior 6, second half: a line holding NO prefilter token still
    yields its checkbox item, so the two prefilters are independent rather than
    one guard over the whole loop (the shape roadmap #129 settled on, which this
    iteration corrects)."""
    text = "- [ ] ship the thing\n"
    assert not any(tok in text.lower() for tok in TODO_PREFILTER_TOKENS), text

    clear_todo_memo()
    assert todos_mod._scan_items(text) == ((1, "TODO: ship the thing", text.rstrip("\n"), 0.8),)


# ----------------------------------------------------------------------------
# Behavior 7 -- the memo seam is untouched
# ----------------------------------------------------------------------------


def test_b07_scan_items_is_pure_and_path_free() -> None:
    """Spec behavior 7: ``_scan_items`` still takes exactly one parameter, the
    text. A path parameter would make it unmemoizable by content."""
    params = list(inspect.signature(todos_mod._scan_items).parameters)
    assert params == ["text"], params


def test_b07_identical_content_in_two_files_is_one_miss_and_one_hit(tmp_path: Path) -> None:
    """Spec behavior 7: the content-keyed memo still serves byte-identical files
    from one computation, with identical items both times."""
    body = "# TODO: same content\n"
    (tmp_path / "one.py").write_text(body, encoding="utf-8")
    (tmp_path / "two.py").write_text(body, encoding="utf-8")

    clear_todo_memo()
    sigs = TodoCollector().collect(tmp_path)
    stats = dict(todo_memo_stats())

    assert stats["misses"] == 1, stats
    assert stats["hits"] == 1, stats
    assert stats["entries"] == 1, stats
    assert [(s.path, s.summary, s.weight) for s in sigs] == [
        ("one.py:1", "TODO: same content", 1.0),
        ("two.py:1", "TODO: same content", 1.0),
    ], sigs


def test_b07_memo_seam_functions_keep_their_contract() -> None:
    """``clear_todo_memo()`` returns to a zeroed counter set with the same keys."""
    clear_todo_memo()
    stats = dict(todo_memo_stats())
    assert set(stats) >= {"hits", "misses", "entries"}, stats
    assert stats["hits"] == 0 and stats["misses"] == 0 and stats["entries"] == 0, stats


# ----------------------------------------------------------------------------
# AMBIGUITY NOTES (PM feedback, per the tester card)
#
# 1. Behavior 4 says to scan a class built from "letters of all tokens" and then
#    proves non-vacuity with "U+0130 matches ``i``" -- but ``i`` is in NO token
#    (that is the point of the whole change), so a class of ``[todxme]`` can
#    never produce that hit. Measured: an IGNORECASE class over the TOKEN letters
#    finds ZERO non-ASCII codepoints, which would make the zero-violation claim
#    vacuous. The only self-consistent reading is to scan the union of letters in
#    the TAGS (``t o d f i x m e``), which finds exactly two hits, U+0130 and
#    U+0131, and lets both halves of the non-vacuity requirement hold. Scanning
#    that superset only strengthens the claim, so this module uses it.
# 2. Behavior 7 calls ``_scan_items`` "the pure, path-free, memoized unit", but
#    the memo counters are NOT incremented by direct ``_scan_items`` calls
#    (measured: two identical direct calls leave ``hits/misses/entries`` at
#    0/0/0, while a collect over two identical files gives 1/1/1). So the memo
#    wraps the per-FILE lookup and keys on content; ``_scan_items`` itself is the
#    uncached computation. Tested as measured. This also makes behaviors 5 and 6
#    honest: a cached ``_scan_items`` would let a warm call skip a sabotaged
#    regex for the wrong reason.
# ----------------------------------------------------------------------------
