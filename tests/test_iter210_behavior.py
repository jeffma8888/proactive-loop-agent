"""Drift guard: ``cli.py``'s MODULE docstring may not name a stale verb count, and
may not name SOME of the verbs.

Why this file exists
The module docstring at the top of ``src/proactive_loop/cli.py`` said this file
wires the library "into fifteen verbs a person actually runs" and then enumerated
fifteen of them by name. The live parser advertised SEVENTEEN: ``verify`` and
``trend`` were missing from the list, and the spelled count had been stale for two
verbs. That contradiction sat in the first prose any reader of the CLI surface
meets, on a PUBLIC portfolio repo whose pitch is auditability -- and the same file
already contradicted itself, because ``build_parser``'s own docstring said
"seventeen subcommands" and was DERIVED-guarded by
``tests/test_iter79_behavior.py``.

What made it survive four roster iterations
A WRONG-WAY ORACLE. ``tests/test_iter75_behavior.py`` asserted ``"fifteen" in
doc``, so the honest correction RED the build. Iterations 189/193/198/201 were all
roster-integrity work and all walked past this line, because fixing it broke the
suite. That is the transferable lesson and it is why every count in this module is
DERIVED from the live parser through :data:`_NUM_WORD`: a literal expected value
in a drift guard eventually pins the defect instead of the contract.

The rule this module encodes (already ruled on by ``test_spec_layout_contract.py``)
A roster is EMPTY-or-COMPLETE. Naming none is honest -- the count plus a pointer at
the live surface. Naming all is honest. Naming SOME is the shipped defect, because
the partial list decays into a lie on the very next verb. This docstring now names
none and points at ``pla --help`` (live roster) and SPEC section 4.5 (per-verb
contracts).

Two measurement conventions, both load-bearing
1. SOURCE TEXT, never ``cli.__doc__``. Every assertion reads the docstring through
   ``ast.get_docstring(ast.parse(source))``, so the guard still bites under
   ``python -OO``, which discards docstrings at compile time and would turn every
   check here into a vacuous pass against an empty string.
2. WHITESPACE-COLLAPSED, via ``" ".join(doc.split())``. A hard line wrap inside the
   docstring must never produce a false red, and 3.12 and 3.13 disagree about
   stripping the common leading indent of a docstring, so collapsing makes this
   module's verdict identical on both matrix legs.

Why Behavior 4 carries planted samples
The EMPTY-or-COMPLETE check is the only non-trivial rule here, and a rule exercised
solely against a tree that already satisfies it is indistinguishable from a rule
that can never fail. So it is proven in BOTH directions against synthetic
docstrings this module builds: a partial roster must FAIL and a complete roster
must PASS. The live file is then measured with the same function.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

from proactive_loop import cli

REPO = Path(__file__).resolve().parents[1]
CLI_SOURCE = REPO / "src" / "proactive_loop" / "cli.py"

#: int -> English number word, covering 1..20 so a growing verb roster cannot rot
#: this guard silently. :func:`_word` fails loudly past the range instead. Same
#: shape and same extend-me contract as ``tests/test_iter79_behavior.py``.
_NUM_WORD: dict[int, str] = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
}

#: The count words this docstring has published and retired. Behavior 2 pins them
#: as a regression check on the specific historical defect; the precondition in
#: that test refuses to become the next wrong-way oracle if the live roster ever
#: shrinks back to one of these values.
RETIRED_COUNT_WORDS = ("thirteen", "fifteen")


def _word(n: int) -> str:
    assert n in _NUM_WORD, f"extend _NUM_WORD past {n} to keep the drift-guard sound"
    return _NUM_WORD[n]


def _live_verbs() -> list[str]:
    """The live verb roster = choices of build_parser()'s one subparsers action."""
    actions = [
        a for a in cli.build_parser()._actions
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(actions) == 1, (
        f"expected exactly one _SubParsersAction in build_parser(), got {len(actions)}"
    )
    return sorted(actions[0].choices)


def _module_doc() -> str:
    """cli.py's MODULE docstring, source-parsed and whitespace-collapsed.

    Source-parsed so the guard survives ``python -OO``; collapsed so a hard wrap
    inside the docstring cannot fake a failure and so 3.12 and 3.13 agree.
    """
    doc = ast.get_docstring(ast.parse(CLI_SOURCE.read_text(encoding="utf-8")))
    assert doc, f"{CLI_SOURCE} has no module docstring -- this guard measures nothing"
    return " ".join(doc.split())


def _longest_verb_run(text: str, verbs: list[str]) -> int:
    """Length of the longest comma-separated run of whole-word live verb names.

    A "verb run" is ``name(, name)+`` -- at least two live verb names separated by
    commas -- so an isolated verb mentioned in prose (``a dispatched run``) scores
    0 and cannot be mistaken for a roster. Alternatives are sorted longest-first so
    ``runs`` is never matched as ``run`` plus a stray ``s``, and both ends are
    word-bounded for the same reason.
    """
    alternation = "|".join(sorted(map(re.escape, verbs), key=len, reverse=True))
    pattern = re.compile(rf"\b(?:{alternation})\b(?:\s*,\s*(?:{alternation})\b)+")
    return max(
        (len(re.split(r"\s*,\s*", m.group(0))) for m in pattern.finditer(text)),
        default=0,
    )


# ==========================================================================
# Behavior 1 -- the spelled count in the module docstring IS the live count.
# ==========================================================================
def test_b01_module_docstring_names_live_verb_count_derived() -> None:
    verbs = _live_verbs()
    phrase = f"{_word(len(verbs))} verbs"
    doc = _module_doc()
    assert phrase in doc, (
        f"cli.py's module docstring must name the live verb count as {phrase!r} "
        f"(live roster of {len(verbs)}: {verbs}); got:\n{doc}"
    )


def test_b01_live_verb_count_is_seventeen() -> None:
    # Anchors today's tree so a silent roster change is visible in the diff. The
    # assertions above and below derive their expectations, so this is the only
    # place a literal count appears and it never gates the docstring.
    assert len(_live_verbs()) == 17


# ==========================================================================
# Behavior 2 -- the retired claims are gone.
# ==========================================================================
def test_b02_retired_count_words_are_absent() -> None:
    live_word = _word(len(_live_verbs()))
    doc = _module_doc()
    for retired in RETIRED_COUNT_WORDS:
        assert retired != live_word, (
            f"the live verb count has returned to {retired!r}, so pinning it as "
            f"RETIRED would make this test the wrong way round -- drop {retired!r} "
            f"from RETIRED_COUNT_WORDS instead of editing the docstring"
        )
        assert retired not in doc, (
            f"cli.py's module docstring still carries the retired count word "
            f"{retired!r}; got:\n{doc}"
        )


# ==========================================================================
# Behavior 3 -- no competing count word precedes "verbs".
# ==========================================================================
def test_b03_no_other_count_word_precedes_verbs() -> None:
    live_word = _word(len(_live_verbs()))
    doc = _module_doc()
    for other in sorted(set(_NUM_WORD.values()) - {live_word}):
        assert f"{other} verbs" not in doc, (
            f"cli.py's module docstring names a competing verb count "
            f"{other + ' verbs'!r} beside the live {live_word + ' verbs'!r}; "
            f"got:\n{doc}"
        )


# ==========================================================================
# Behavior 4 -- EMPTY-or-COMPLETE roster, proven in both directions.
# ==========================================================================
def test_b04_module_docstring_roster_is_empty_or_complete() -> None:
    verbs = _live_verbs()
    longest = _longest_verb_run(_module_doc(), verbs)
    assert longest in (0, len(verbs)), (
        f"cli.py's module docstring enumerates {longest} of {len(verbs)} verbs. A "
        f"roster is EMPTY-or-COMPLETE: name none (the count plus a pointer at "
        f"`pla --help`) or name all -- naming some rots into a lie on the next verb"
    )


def test_b04_live_module_docstring_names_no_verbs() -> None:
    # The shape this iteration shipped: no roster at all, pointer instead.
    assert _longest_verb_run(_module_doc(), _live_verbs()) == 0


def test_b04_control_a_partial_roster_fails_the_rule() -> None:
    # KNOWN-BAD sample: without this the rule above could never fail and reading
    # its source could not establish that it bites.
    verbs = _live_verbs()
    planted = (
        "This file only wires them into seventeen verbs a person actually runs "
        "-- scan, dispatch, run -- and owns the two things a library must not."
    )
    longest = _longest_verb_run(planted, verbs)
    assert longest == 3, f"reader broken: expected a run of 3, measured {longest}"
    assert longest not in (0, len(verbs)), (
        "a partial roster of 3 must violate EMPTY-or-COMPLETE, else the rule is "
        "decoration"
    )


def test_b04_control_a_complete_roster_passes_the_rule() -> None:
    # KNOWN-GOOD sample: naming ALL of them is honest, so the rule must not simply
    # ban commas near verb names.
    verbs = _live_verbs()
    planted = "It wires them into these verbs: " + ", ".join(verbs) + "."
    longest = _longest_verb_run(planted, verbs)
    assert longest == len(verbs), (
        f"reader broken: a complete comma list of {len(verbs)} verbs measured "
        f"{longest}"
    )
    assert longest in (0, len(verbs))


# ==========================================================================
# Behavior 5 -- the reader is pointed at the two authoritative surfaces.
# ==========================================================================
def test_b05_module_docstring_points_at_help_and_spec_section() -> None:
    doc = _module_doc()
    for pointer in ("pla --help", "4.5"):
        assert pointer in doc, (
            f"cli.py's module docstring must point the reader at {pointer!r} in "
            f"place of the deleted partial roster; got:\n{doc}"
        )
