"""Black-box behavior tests for state-dir iteration 238 (test module ``iter217``).

Feature under test: ``todos._scan_items`` decides its CHECKBOX pass with a named
compiled prefilter on ``\\[\\s\\]`` -- the bracket subpattern ``_CHECKBOX_RE``
cannot match without -- instead of the measured-useless ``"[" in text``.

MODULE NAME. Derived from the repo, never from the state-dir number, per the
operator pin: ``git ls-files tests`` tops out at ``test_iter216_behavior.py`` and
``git cat-file -e HEAD:tests/test_iter217_behavior.py`` FAILS, so 217 is the next
free slot (both re-measured by this tester, not taken on trust). Naming this file
``test_iter238_behavior.py`` from the state dir would collide with the shipped
oracle numbering the way iteration 186 destroyed ``test_iter186_behavior.py``.

ISOLATION CONTRACT (honored, no exceptions). Every assertion is derived from this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
conventions, and the module's OBSERVABLE behavior obtained by RUNNING it. **No
file under ``src/`` was read, no ``git diff`` was inspected, and neither
``engineer.md`` nor ``reviewer.md`` nor ``fix_review.md`` was opened.** The one
place implementation TEXT is inspected is behavior 2, where the spec itself
mandates ``inspect.getsource(_scan_items)``; that happens inside the test at
runtime, which is how a code-not-prose assertion can exist at all.

Offline and deterministic: no network, no API key, no subprocess.

NO TIMING ASSERTIONS. The measured win (-25.7 ms of the ``_scan_items`` pass,
-4.6% of the 555 ms scan, -9.6% of the ~268 ms reducible surface) is a DATED
record kept in the commit message and the module docstring. Nothing here asserts
on a duration; behavior 3 proves the skip STRUCTURALLY by making the guarded
regex raise if it is ever consulted, and behavior 4 proves the skip LOSES NOTHING
by comparing against the same code path with the gate forced open.

NO INDENTATION OR DOCSTRING-PROSE ASSERTIONS. CI is a 3.12 + 3.13 matrix and 3.13
strips the common leading docstring indent at compile time, so behavior 2 EXCISES
the docstring before asserting on code, and no test here pins docstring wording.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.collectors import todos as todos_mod
from proactive_loop.collectors.todos import clear_todo_memo

# The exact pattern string the gate must be, spelled once.
GATE_PATTERN: Final[str] = r"\[\s\]"

# ----------------------------------------------------------------------------
# Behavior 1 -- the gate is a NAMED constant DERIVED from the regex it guards
# ----------------------------------------------------------------------------


def test_b01_gate_is_a_named_compiled_constant() -> None:
    """Spec behavior 1, first half: a module-level compiled pattern exists and its
    ``.pattern`` is exactly ``\\[\\s\\]`` -- not a retyped whitespace class."""
    gate = todos_mod._CHECKBOX_PREFILTER_RE
    assert isinstance(gate, re.Pattern), type(gate)
    assert gate.pattern == GATE_PATTERN, repr(gate.pattern)


def test_b01_gate_is_a_subpattern_of_the_regex_it_guards() -> None:
    """Spec behavior 1, second half -- the half that makes the two unable to drift
    apart: the gate's pattern is a SUBSTRING of ``_CHECKBOX_RE.pattern``, so
    editing either alone fails this assertion.

    This is the soundness proof, and it is structural rather than empirical: a
    match of ``_CHECKBOX_RE`` requires ``\\[\\s\\]`` somewhere in the line, so
    searching for that subpattern over the whole text is provably WEAKER than the
    regex it guards. Zero empirical losses over a corpus is not a proof; being
    the guarded regex's own subpattern is.
    """
    guarded = todos_mod._CHECKBOX_RE.pattern
    gate = todos_mod._CHECKBOX_PREFILTER_RE.pattern

    assert gate in guarded, (
        "the prefilter must be a literal subpattern of the regex it guards, or "
        f"the two can drift apart: gate={gate!r} guarded={guarded!r}"
    )
    # Anti-vacuity: an empty or trivially-contained gate would satisfy the
    # containment half while gating nothing.
    assert gate == GATE_PATTERN and len(gate) >= 6, repr(gate)


def test_b01_gate_is_annotated_final_pattern() -> None:
    """Spec behavior 1: the constant is annotated ``Final[re.Pattern[str]]``.

    Read from the module's ``__annotations__``, which under
    ``from __future__ import annotations`` holds the annotation SOURCE text -- so
    this asserts the declaration, not a runtime type. ``make typecheck`` is the
    other half of this claim.
    """
    ann = getattr(todos_mod, "__annotations__", {})
    assert "_CHECKBOX_PREFILTER_RE" in ann, sorted(ann)
    declared = str(ann["_CHECKBOX_PREFILTER_RE"])
    assert "Final" in declared and "Pattern" in declared, declared


# ----------------------------------------------------------------------------
# Behavior 2 -- the old gate is gone, asserted on CODE not prose
# ----------------------------------------------------------------------------


def _code_without_docstring(func: object) -> str:
    """``inspect.getsource(func)`` with everything between the FIRST pair of
    triple quotes removed.

    Excising by delimiter rather than by ``__doc__`` is deliberate and required
    twice over: 3.13 strips the common leading docstring indent at compile time
    while 3.12 does not (so ``src.replace(func.__doc__, "")`` is version-
    fragile), and the corrected docstring may legitimately NAME the retired
    expression while the code must not contain it.
    """
    src = inspect.getsource(func)  # type: ignore[arg-type]
    first = src.find('"""')
    assert first != -1, "expected a docstring delimited by triple quotes"
    second = src.find('"""', first + 3)
    assert second != -1, "unterminated docstring in the inspected source"
    return src[:first] + src[second + 3 :]


def test_b02_old_bracket_gate_is_absent_from_the_code() -> None:
    """Spec behavior 2: with the docstring excised, ``_scan_items``' code calls
    the named prefilter and no longer contains the retired ``"[" in text``."""
    src = inspect.getsource(todos_mod._scan_items)
    code = _code_without_docstring(todos_mod._scan_items)

    # The excision really happened, and it really removed the docstring only.
    assert len(code) < len(src), "docstring excision removed nothing"
    assert '"""' not in code, (
        "excision left a triple-quote behind, so this assertion is not scoped to "
        "code; the function body must hold no second triple-quoted literal"
    )

    assert "_CHECKBOX_PREFILTER_RE.search(" in code, (
        "the code must consult the named prefilter; got:\n" + code
    )
    assert '"[" in text' not in code, (
        'the retired gate \'"[" in text\' is still in the CODE of _scan_items:\n' + code
    )


# ----------------------------------------------------------------------------
# Behavior 3 -- the skip is real, proven without timing, and two-sided
# ----------------------------------------------------------------------------


class _Boom:
    """A stand-in regex that fails loudly if it is ever consulted.

    Same shape as the one ``tests/test_iter181_behavior.py`` already ships, so
    the sabotage technique is a repo convention rather than a new invention.
    """

    def search(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("inline tag regex was consulted")

    def match(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("checkbox regex was consulted")


def test_b03_checkbox_regex_is_skipped_for_text_holding_a_bare_bracket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec behavior 3, skip side: text that holds ``[`` but no ``[<space>]``
    never reaches ``_CHECKBOX_RE`` -- the whole point of the change, since the
    retired gate admitted exactly this text."""
    text = "arr[0] = 1\nvals = [1, 2]\n"
    # The premise, re-measured rather than asserted in prose: the RETIRED gate
    # would have admitted this text, and the new one does not.
    assert "[" in text
    assert not todos_mod._CHECKBOX_PREFILTER_RE.search(text)

    monkeypatch.setattr(todos_mod, "_CHECKBOX_RE", _Boom())
    clear_todo_memo()
    assert todos_mod._scan_items(text) == (), (
        "_CHECKBOX_RE must not be consulted for text holding no '[<space>]'"
    )


def test_b03_checkbox_regex_is_still_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec behavior 3, reachability side. A one-sided version of behavior 3
    would pass against a regex that is never called at all, so the SAME sabotaged
    regex must be consulted for text that can match it."""
    monkeypatch.setattr(todos_mod, "_CHECKBOX_RE", _Boom())
    clear_todo_memo()
    with pytest.raises(AssertionError, match="checkbox regex was consulted"):
        todos_mod._scan_items("- [ ] x\n")


# ----------------------------------------------------------------------------
# Behavior 4 -- equivalence over an adversarial corpus: 0 items lost
# ----------------------------------------------------------------------------

# The spec's 16 texts. NBSP and U+2000 are the cases that make a HAND-ENUMERATED
# whitespace gate unsound: ``\s`` matches them and ``str.splitlines()`` does NOT
# split them, so ``- [\xa0] x`` really is ONE line that ``_CHECKBOX_RE`` matches.
# ``\x0b`` is the deliberate agreement case: ``\s`` matches it so the gate PASSES,
# but ``splitlines()`` DOES split on it, so both sides must yield no item.
_CORPUS: Final[tuple[str, ...]] = (
    "- [ ] x\n",
    "- [\t] x\n",
    "- [\xa0] x\n",
    "- [\u2000] x\n",
    "- [\x0b] x\n",
    "* [ ] a\n",
    "+ [ ] b\n",
    "   - [ ] indented\n",
    "- [x] done\n",
    "a [b] c\n",
    "arr[0] = 1\n",
    "[]\n",
    "[ ]\n",
    "no brackets here\n",
    "",
    "# TODO: t\n- [ ] c\n",
)


def _scan(text: str) -> tuple[object, ...]:
    """One cold ``_scan_items`` call. The memo is a module-level dict, so a warm
    call could return a cached tuple and let a sabotaged or forced-open gate look
    correct for the wrong reason."""
    clear_todo_memo()
    return todos_mod._scan_items(text)


@pytest.mark.parametrize("text", _CORPUS, ids=lambda t: repr(t))
def test_b04_gate_loses_nothing_against_the_same_path_ungated(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    """Spec behavior 4: the gated result equals the UNGATED result for every text.

    The reference is the module's OWN code path with the gate forced open by an
    always-matching compiled pattern -- exactly ONE variable changed -- rather
    than a hand-rebuilt per-line scan. A reimplemented reference has to guess
    the item shape, and it guesses wrong (measured: the raw line of
    ``"   - [ ] indented\\n"`` is stored DEDENTED, and inline items are
    normalised to a canonical tag), so it would diverge from the real extraction
    for reasons that have nothing to do with the gate.
    """
    gated = _scan(text)

    always_on = re.compile("")  # .search() matches at position 0 of any string
    assert always_on.search(text) is not None, "the stand-in must force the gate open"
    monkeypatch.setattr(todos_mod, "_CHECKBOX_PREFILTER_RE", always_on)
    ungated = _scan(text)

    assert gated == ungated, (
        f"the prefilter changed the extraction for {text!r}:\n"
        f"  gated  ={gated!r}\n  ungated={ungated!r}"
    )


@pytest.mark.parametrize("text", _CORPUS, ids=lambda t: repr(t))
def test_b04_every_line_the_checkbox_regex_matches_still_yields_an_item(text: str) -> None:
    """Spec behavior 4, with an INDEPENDENT reference for the checkbox half: every
    ``splitlines()`` line that ``_CHECKBOX_RE`` matches must appear among the
    extracted items' line numbers. This does not depend on the module's own gate
    at all, so it cannot be satisfied by a gate that is simply never applied."""
    want_lines = [i for i, line in enumerate(text.splitlines(), 1) if todos_mod._CHECKBOX_RE.match(line)]
    got_lines = [item[0] for item in _scan(text)]
    missing = [n for n in want_lines if n not in got_lines]
    assert not missing, (
        f"checkbox line(s) {missing} of {text!r} matched _CHECKBOX_RE but produced "
        f"no item; extracted={got_lines!r}"
    )


def test_b04_corpus_and_reference_are_anti_vacuous() -> None:
    """The equivalence pass above proves nothing if the corpus extracts nothing,
    and the narrowness claim proves nothing if the gate admits everything.

    Both are measured here, and the two gate-reach counts are the whole case for
    the change: the retired gate admitted 14 of the 16 texts, the derived gate
    admits 10. The corpus extracts 9 items over 8 checkbox lines.
    """
    total_items = sum(len(_scan(t)) for t in _CORPUS)
    checkbox_lines = sum(
        1
        for t in _CORPUS
        for line in t.splitlines()
        if todos_mod._CHECKBOX_RE.match(line)
    )
    assert total_items == 9, total_items
    assert checkbox_lines == 8, checkbox_lines

    old_reach = sum(1 for t in _CORPUS if "[" in t)
    new_reach = sum(1 for t in _CORPUS if todos_mod._CHECKBOX_PREFILTER_RE.search(t))
    assert (old_reach, new_reach) == (14, 10), (old_reach, new_reach)
    assert new_reach < old_reach, "the derived gate must be strictly narrower"


def test_b04_the_two_unsound_hand_enumeration_cases_are_real() -> None:
    """The premise behind deriving the gate instead of hand-writing a whitespace
    class, re-measured rather than trusted: NBSP and U+2000 both survive
    ``splitlines()`` as ONE line AND match ``_CHECKBOX_RE``, so a gate spelling
    ``"[ ]" in text or "[\\t]" in text`` would SILENTLY DROP those items."""
    for exotic in ("\xa0", "\u2000"):
        text = f"- [{exotic}] x\n"
        assert len(text.splitlines()) == 1, repr(text)
        assert todos_mod._CHECKBOX_RE.match(text.splitlines()[0]) is not None, repr(text)
        assert todos_mod._CHECKBOX_PREFILTER_RE.search(text) is not None, repr(text)
        assert "[ ]" not in text and "[\t]" not in text, repr(text)
        assert len(_scan(text)) == 1, repr(text)

    # And the agreement case: the gate passes but splitlines() splits, so neither
    # side finds an item. Both halves asserted, or this is not an agreement.
    vt = "- [\x0b] x\n"
    assert todos_mod._CHECKBOX_PREFILTER_RE.search(vt) is not None
    assert len(vt.splitlines()) == 2, vt.splitlines()
    assert _scan(vt) == ()


# ----------------------------------------------------------------------------
# Behavior 5 -- the shipped iter-181 oracle stays valid, unedited
# ----------------------------------------------------------------------------

_ORACLE_181: Final[Path] = Path(__file__).with_name("test_iter181_behavior.py")


def test_b05_iter181_fixture_data_is_still_the_data_this_claim_rests_on() -> None:
    """Spec behavior 5: the PM's claim that no shipped oracle needs reconciling
    rests on WHICH texts ``tests/test_iter181_behavior.py`` parametrizes -- its
    skip case holds no bracket at all and its reachability case holds ``[ ]``.

    Re-proven here rather than trusted. If that fixture data is ever changed, this
    assertion fires and the compatibility argument must be re-derived.
    """
    src = _ORACLE_181.read_text(encoding="utf-8")
    assert '"_CHECKBOX_RE"' in src, "the iter-181 oracle no longer sabotages _CHECKBOX_RE"
    assert '"no brackets here\\n"' in src, "iter-181's skip fixture changed"
    assert '"- [ ] x\\n"' in src, "iter-181's reachability fixture changed"


def test_b05_new_gate_satisfies_both_directions_of_the_iter181_oracle() -> None:
    """Spec behavior 5: any gate strictly stronger than ``"[" in text`` and still
    weaker than ``_CHECKBOX_RE`` satisfies BOTH of iter-181's directions, so the
    shipped oracle needs no edit. Measured on the new gate directly."""
    skip_text = "no brackets here\n"
    reach_text = "- [ ] x\n"

    assert todos_mod._CHECKBOX_PREFILTER_RE.search(skip_text) is None, (
        "iter-181's skip case must still be skipped by the new gate"
    )
    assert todos_mod._CHECKBOX_PREFILTER_RE.search(reach_text) is not None, (
        "iter-181's reachability case must still reach _CHECKBOX_RE"
    )
    assert _scan(skip_text) == ()
    assert _scan(reach_text) == ((1, "TODO: x", "- [ ] x", 0.8),), _scan(reach_text)


# ----------------------------------------------------------------------------
# AMBIGUITY / PM-FEEDBACK NOTES (per the tester card)
#
# 1. The spec's gate-reach figures for the behavior-4 corpus are OFF BY ONE in
#    both numbers. It states "Gate reach on that corpus falls 13/16 -> 9/16";
#    measured live on all 16 texts it is 14/16 -> 10/16 (the reviewer's own
#    note records 14 -> 10 as well). The 16 texts holding "[" are every one
#    except "no brackets here\n" and "", i.e. 14; the 10 the derived gate admits
#    are the eight bullet forms plus "[ ]\n" plus the two-line "# TODO: t\n-
#    [ ] c\n". Nothing about the change depends on the figure, and the 286-file
#    measurement (282/286 -> 11/286) is a different, unaffected population --
#    but the corpus figure is what a future reader would re-derive first.
#    test_b04_corpus_and_reference_are_anti_vacuous pins the MEASURED pair.
# 2. Behavior 4 says to build the reference by applying "_INLINE_TAG_RE.search
#    then _CHECKBOX_RE.match to every splitlines() line with NO checkbox gate".
#    Taken literally that means REIMPLEMENTING the extraction in the test, which
#    is the trap the reviewer hit: the item tuple is a bare
#    (lineno, summary, raw, weight) whose raw line is DEDENTED and whose inline
#    summary is normalised to a canonical tag, so a hand-built reference diverges
#    for reasons unrelated to the gate. This module therefore uses the same
#    reference SEMANTICS through the module's own code path with the gate forced
#    open by re.compile("") -- exactly one variable changed, so it cannot drift --
#    and adds an INDEPENDENT line-level reference (every line _CHECKBOX_RE
#    matches must yield an item) for the property the spec actually cares about.
# 3. Behavior 1's "annotated Final[re.Pattern[str]]" is asserted against the
#    module's __annotations__, which holds annotation SOURCE text under
#    `from __future__ import annotations`. That is a declaration check, not a
#    runtime type check; `make typecheck` remains the real oracle for the type.
# ----------------------------------------------------------------------------
