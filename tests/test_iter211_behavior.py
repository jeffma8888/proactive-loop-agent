"""Independent second opinion on iteration 232: the ``cli.py`` module-docstring
verb-count and EMPTY-or-COMPLETE roster guard.

WHY A SECOND MODULE. This iteration's shipped artifact is *itself* an oracle
(``tests/test_iter210_behavior.py``), so the usual arrangement -- one stage writes the
behavior, another writes the guard -- has to be turned inside out. A module cannot
supply its own control: every claim it makes about its own rigor is checked by the
same code that makes the claim, and the defect this iteration fixed is precisely a
guard that pinned the WRONG answer for four iterations while passing every run. So
this module verifies, from OUTSIDE, the properties the Expected Behaviors demand of
that one, RE-MEASURES the roster down a different path, and MUTATES the sibling to
prove it bites. It follows the arrangement ``test_iter209_behavior.py`` already uses
over ``test_iter208_behavior.py``.

MODULE NAME derived from the repo, never from the state-dir counter (the operator pin,
and the defect that cost factory iteration 186 a shipped oracle): the highest
``test_iterNN_behavior.py`` tracked in ``HEAD`` is 209 and this iteration's new module
takes 210, so this file is 211, and ``git cat-file -e HEAD:tests/test_iter211_behavior.py``
failed before a byte was written, proving the path free in ``HEAD``.

FOUR KINDS OF CHECK LIVE HERE, and the split is deliberate.

RE-MEASURED (executed) -- the live verb roster is taken from the CLI's own ``--help``
OUTPUT, by parsing the subcommand metavar argparse prints. The sibling introspects
``build_parser()._actions``. Two measurements down independent paths that agree are
corroboration; two artifacts that agree because they share one source are not.

TRUTH OF THE POINTERS (executed) -- the docstring no longer lists the verbs and
instead points at ``pla --help`` and SPEC section 4.5. The sibling checks those two
strings are PRESENT. Present is not true: a pointer that names a surface which does
not carry the roster is worse than no pointer, because it sends a reader somewhere
and the rot is then invisible. So both pointers are dereferenced -- ``--help`` must
print the COMPLETE live roster, and SPEC 4.5 must exist and name every live verb.

MUTATION (executed, against the sibling's own code) -- the control the sibling cannot
run on itself. With its source-file pointer aimed at a reconstruction of the docstring
this iteration deleted, its Behavior 1, 2 and 4 assertions must actually FAIL. An
oracle that cannot be made to fail is decoration, and reading its source can never
establish that it bites. This is the load-bearing check of the whole module: the
historical defect was a guard that demanded the stale text, so "the guard now rejects
the stale text" is the claim that matters.

CENSUS (``ast``, nothing executed) -- the root-cause regression guard. The prose was
wrong for four iterations because a test asserted the stale word was PRESENT, so the
honest edit red the build. This module bans that SHAPE across every tracked test
module, not just the one that had it, and proves the detector fires on a planted
sample. Its domain is ``git ls-files``, so this file was ``git add -N``'d before the
census ran -- otherwise the census is blind to itself and reds the build the moment it
is committed (the 2026-08-14 operator lesson).

MEASUREMENT CONVENTIONS, both load-bearing and both matching the spec.
1. SOURCE TEXT, never ``cli.__doc__``: every docstring assertion reads
   ``ast.get_docstring(ast.parse(source))``, so the guard still bites under
   ``python -OO``, which discards docstrings at compile time and would silently turn
   every check into a vacuous pass over an empty string.
2. WHITESPACE-COLLAPSED via ``" ".join(doc.split())``: a hard wrap inside the
   docstring must never fake a failure, and 3.12 and 3.13 disagree about stripping a
   docstring's common leading indent, so collapsing makes this module's verdict
   identical on both CI matrix legs.

HERMETIC. No network, no wall clock, no subprocess, no ambient scan root: the only
files read are two tracked source files and the tracked test corpus, and the only
tree written is ``tmp_path``. Nothing here depends on gitignored local state, so it
holds in the fresh-clone release check as well as in the working tree.

BLACK BOX. This module drives the package's public entry point, reads the sibling test
module's text, and reads exactly one artifact of ``src/``: the module DOCSTRING of
``cli.py``, which is the documentation surface under test and is what every Expected
Behavior is about. It reads no implementation logic, no diff, and no stage notes.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import re
import subprocess
import sys
from contextlib import redirect_stdout
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

from proactive_loop import cli

REPO: Final = Path(__file__).resolve().parents[1]
CLI_SOURCE: Final = REPO / "src" / "proactive_loop" / "cli.py"
SPEC: Final = REPO / "SPEC.md"
SIBLING: Final = REPO / "tests" / "test_iter210_behavior.py"

#: int -> English number word, 1..20, with the same extend-me contract
#: ``test_iter79_behavior.py`` uses: a 21st verb must fail loudly in :func:`_word`
#: rather than let a derived assertion degrade into a vacuous one.
_NUM_WORD: Final[dict[int, str]] = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
}

#: Count words this docstring has published and retired. Pinned as a regression check
#: on the specific historical defect, guarded so it cannot itself become the next
#: wrong-way oracle if the live roster ever shrinks back to one of these values.
RETIRED_COUNT_WORDS: Final = ("thirteen", "fifteen")

#: SPEC section that the corrected docstring points at for per-verb contracts.
SPEC_ROSTER_SECTION: Final = "4.5"


def _word(n: int) -> str:
    assert n in _NUM_WORD, f"extend _NUM_WORD past {n} to keep this guard sound"
    return _NUM_WORD[n]


def _collapse(text: str) -> str:
    return " ".join(text.split())


@cache
def _module_doc() -> str:
    """``cli.py``'s MODULE docstring: source-parsed, whitespace-collapsed."""
    doc = ast.get_docstring(ast.parse(CLI_SOURCE.read_text(encoding="utf-8")))
    assert doc, f"{CLI_SOURCE} has no module docstring -- this guard measures nothing"
    return _collapse(doc)


@cache
def _help_text() -> str:
    """Top-level ``pla --help``, captured in-process (no subprocess, no network)."""
    buf = io.StringIO()
    with pytest.raises(SystemExit) as excinfo, redirect_stdout(buf):
        cli.main(["--help"])
    assert excinfo.value.code == 0, f"`pla --help` must exit 0, got {excinfo.value.code}"
    return buf.getvalue()


@cache
def _roster_from_help() -> tuple[str, ...]:
    """The live verb roster, parsed out of the CLI's OWN help output.

    Deliberately NOT ``build_parser()._actions``: the sibling oracle uses that, and a
    second measurement that borrows the first one's instrument corroborates nothing.
    argparse renders a subparsers action as a ``{a,b,c}`` metavar group, so the roster
    is readable from the same text a human reads.
    """
    match = re.search(r"\{([a-z0-9_,-]+)\}", _help_text())
    assert match, f"`pla --help` printed no subcommand metavar group:\n{_help_text()}"
    names = tuple(sorted(match.group(1).split(",")))
    assert all(names), f"empty verb name parsed out of the metavar group: {names}"
    return names


@cache
def _roster_from_parser() -> tuple[str, ...]:
    """The same roster by parser introspection -- used ONLY to cross-check the above."""
    actions = [
        a for a in cli.build_parser()._actions
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(actions) == 1, f"expected one _SubParsersAction, got {len(actions)}"
    return tuple(sorted(actions[0].choices))


def _longest_comma_run(text: str, verbs: tuple[str, ...]) -> int:
    """Longest run of comma-separated whole-word live verb names in ``text``.

    A different IMPLEMENTATION of the sibling's rule, on purpose: it splits on commas
    and walks the resulting fields, where the sibling builds one regex alternation. If
    two independently written readers disagree about the live docstring, that
    disagreement is itself the finding.
    """
    live = set(verbs)
    longest = run = 0
    for field in re.split(r",", text):
        stripped = field.strip()
        # A field counts only if a live verb sits at the boundary the comma created:
        # its tail for a field before a comma, its head for a field after one. Any
        # other content breaks the run, so prose that merely mentions a verb scores 0.
        head = re.match(r"[a-z0-9_-]+", stripped)
        tail = re.search(r"[a-z0-9_-]+$", stripped)
        touches = {m.group(0) for m in (head, tail) if m is not None} & live
        if touches:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return longest if longest >= 2 else 0


def _strip_parentheticals(text: str) -> str:
    return re.sub(r"\([^)]*\)", " ", text)


@cache
def _load_sibling() -> ModuleType:
    """Import the oracle under examination under its own private name.

    Registering it in ``sys.modules`` before executing is the documented import
    protocol; ``exec()`` into a bare dict breaks any module that resolves string
    annotations by looking its own name up there.
    """
    spec = importlib.util.spec_from_file_location("_iter210_oracle_probe", SIBLING)
    assert spec is not None and spec.loader is not None, f"cannot load {SIBLING}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# The docstring this iteration DELETED, reconstructed from the PM spec's verbatim
# quotation of the stale phrase and its 15-name enumeration. Labelled a
# reconstruction, not a byte-exact history: what the mutation control needs is a
# sample carrying the two defects (a stale spelled count, a partial roster), and both
# are present here by construction.
STALE_DOCSTRING_SAMPLE: Final = '''"""Command-line entry point (L2 orchestration surface).

WHY a thin CLI over the library layers: every capability the CLI exposes already
lives in a tested module. This file only *wires* them into fifteen verbs a person
actually runs -- scan, dispatch, run, resume, runs, explain, trace, signals, watch,
diff, policy, tools, collectors, providers, config -- and owns the two things a
library must not: argument parsing and where run artifacts land on disk.
"""
'''


# ==========================================================================
# Behavior 1 -- the spelled count in the module docstring IS the live count,
# where "live" is re-measured off the CLI's own help output.
# ==========================================================================
def test_b01_docstring_count_matches_the_roster_printed_by_help() -> None:
    roster = _roster_from_help()
    phrase = f"{_word(len(roster))} verbs"
    doc = _module_doc()
    assert phrase in doc, (
        f"cli.py's module docstring must name the count of verbs that `pla --help` "
        f"actually prints as {phrase!r} (help printed {len(roster)}: {list(roster)}); "
        f"got:\n{doc}"
    )


def test_b01_two_independent_roster_measurements_agree() -> None:
    from_help, from_parser = _roster_from_help(), _roster_from_parser()
    assert from_help == from_parser, (
        "the roster `pla --help` prints disagrees with the roster build_parser() "
        f"exposes: help={list(from_help)} parser={list(from_parser)}. Until they "
        "agree, no docstring count can be checked against 'the live roster'"
    )
    assert len(from_help) == 17, (
        f"anchor for today's tree: expected 17 live verbs, measured {len(from_help)}. "
        "Every gating assertion in this module derives its expectation, so update this "
        "anchor rather than any of them"
    )


# ==========================================================================
# Behavior 2 -- the retired claims are gone.
# ==========================================================================
def test_b02_retired_count_words_absent_from_module_docstring() -> None:
    live_word = _word(len(_roster_from_help()))
    doc = _module_doc()
    for retired in RETIRED_COUNT_WORDS:
        assert retired != live_word, (
            f"the live verb count has returned to {retired!r}, so banning that word "
            f"would make THIS test the wrong way round -- drop {retired!r} from "
            "RETIRED_COUNT_WORDS instead of editing the docstring"
        )
        assert retired not in doc.lower(), (
            f"retired verb-count word {retired!r} still present in cli.py's module "
            f"docstring; got:\n{doc}"
        )


# ==========================================================================
# Behavior 3 -- no competing count precedes "verbs", in words OR digits.
# ==========================================================================
def test_b03_exactly_one_spelled_count_precedes_verbs_and_it_is_live() -> None:
    live_word = _word(len(_roster_from_help()))
    words = set(_NUM_WORD.values())
    found = [m.group(1).lower() for m in re.finditer(r"\b([A-Za-z]+)\s+verbs\b", _module_doc())]
    spelled = [w for w in found if w in words]
    assert spelled == [live_word], (
        f"cli.py's module docstring must spell the verb count exactly once and it must "
        f"be the live {live_word!r}; the phrases '<number word> verbs' found were "
        f"{spelled} (all words preceding 'verbs': {found})"
    )


def test_b03_no_digit_count_precedes_verbs() -> None:
    # A word-only ban is evadable by writing the count in digits, which would restore
    # exactly the drift this iteration removed while passing every spelled-word check.
    digits = re.findall(r"\b(\d+)\s+verbs\b", _module_doc())
    assert digits == [], (
        f"cli.py's module docstring writes the verb count in digits {digits}, which no "
        "spelled-word guard can keep honest -- spell it so the derived check binds"
    )


# ==========================================================================
# Behavior 4 -- EMPTY-or-COMPLETE roster, proven two-sided with this module's
# OWN reader, and shown not to be an artifact of the parenthetical aside.
# ==========================================================================
def test_b04_module_docstring_names_no_verb_roster() -> None:
    roster = _roster_from_help()
    longest = _longest_comma_run(_module_doc(), roster)
    assert longest in (0, len(roster)), (
        f"cli.py's module docstring enumerates {longest} of {len(roster)} verbs. A "
        "roster is EMPTY-or-COMPLETE: name none (the count plus a pointer at "
        "`pla --help`) or name all -- naming some rots into a lie on the next verb"
    )
    assert longest == 0, (
        f"this iteration shipped the EMPTY shape, so the longest verb run must be 0, "
        f"measured {longest}"
    )


def test_b04_reader_rejects_a_partial_roster() -> None:
    # KNOWN-BAD control. Without it, the rule above could never fail and reading its
    # source could not establish that it bites.
    roster = _roster_from_help()
    planted = (
        "This file only wires them into seventeen verbs a person actually runs "
        "-- scan, dispatch, run -- and owns the two things a library must not."
    )
    longest = _longest_comma_run(planted, roster)
    assert longest == 3, f"reader broken: expected a run of 3, measured {longest}"
    assert longest not in (0, len(roster)), (
        "a partial roster of 3 must violate EMPTY-or-COMPLETE, else the rule is "
        "decoration"
    )


def test_b04_reader_accepts_a_complete_roster() -> None:
    # KNOWN-GOOD control: naming ALL of them is honest, so the rule must not degrade
    # into "no commas near verb names".
    roster = _roster_from_help()
    planted = "It wires them into these verbs: " + ", ".join(roster) + "."
    longest = _longest_comma_run(planted, roster)
    assert longest == len(roster), (
        f"reader broken: a complete comma list of {len(roster)} verbs measured {longest}"
    )
    assert longest in (0, len(roster))


def test_b04_reader_agrees_with_the_siblings_independent_implementation() -> None:
    # Two readers written from the same spec sentence but with different mechanics.
    # If they disagree on the live docstring or on either planted sample, one of them
    # is wrong and the EMPTY-or-COMPLETE verdict is not established by either.
    sibling = _load_sibling()
    roster = _roster_from_help()
    samples = {
        "live": _module_doc(),
        "partial": "wires them into scan, dispatch, run -- and owns",
        "complete": ", ".join(roster),
        "prose-mention": "Layout of a dispatched run under state_dir, then scan again.",
    }
    for name, text in samples.items():
        mine = _longest_comma_run(text, roster)
        theirs = sibling._longest_verb_run(text, list(roster))
        assert mine == theirs, (
            f"the two independently written verb-run readers disagree on sample "
            f"{name!r}: this module measured {mine}, "
            f"tests/test_iter210_behavior.py measured {theirs}"
        )


def test_b04_empty_verdict_is_not_an_artifact_of_the_parenthetical_aside() -> None:
    """The pass must survive stripping parenthesised asides -- and here is the hazard.

    The live docstring contains a parenthesised list of MODULE names,
    ``(collectors, scout, loop)``, and ``collectors`` is a live VERB. Today only one
    of those three names is a verb, so no run forms and the rule scores 0 either way.
    But the margin is one verb name: a future verb called ``scout`` would turn that
    aside into a run of 2 and RED a docstring that names no roster at all. This test
    records the margin as a measurement rather than as prose, and pins the property
    that actually matters -- the EMPTY verdict holds under BOTH readings.
    """
    roster = _roster_from_help()
    doc = _module_doc()
    assert _longest_comma_run(doc, roster) == 0
    assert _longest_comma_run(_strip_parentheticals(doc), roster) == 0, (
        "the EMPTY verdict must not depend on how parenthesised asides are handled"
    )
    # The margin, measured: with a hypothetical verb named `scout`, the unstripped
    # reading of the SAME docstring turns a module-name aside into a roster.
    hypothetical = tuple(sorted(roster + ("scout",)))
    assert _longest_comma_run(doc, hypothetical) == 2, (
        "expected the parenthesised module list to score a run of 2 once `scout` is a "
        "verb -- if this changes, re-derive the hazard before trusting the note above"
    )
    assert _longest_comma_run(_strip_parentheticals(doc), hypothetical) == 0, (
        "stripping parenthesised asides is the escape from that false positive"
    )


# ==========================================================================
# Behavior 5 -- the two pointers replacing the roster must be PRESENT and TRUE.
# ==========================================================================
def test_b05_both_pointers_are_present_in_the_module_docstring() -> None:
    doc = _module_doc()
    for pointer in ("pla --help", SPEC_ROSTER_SECTION):
        assert pointer in doc, (
            f"cli.py's module docstring must point the reader at {pointer!r} in place "
            f"of the deleted partial roster; got:\n{doc}"
        )


def test_b05_help_pointer_is_true_help_prints_the_complete_live_roster() -> None:
    # A pointer that is present but false is worse than no pointer: it sends the
    # reader somewhere, so the rot becomes invisible instead of merely undocumented.
    roster, out = _roster_from_help(), _help_text()
    missing = [v for v in roster if not re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", out)]
    assert not missing, (
        "the docstring says ``pla --help`` prints the live roster, but its output does "
        f"not name {missing}; got:\n{out}"
    )


def test_b05_spec_pointer_is_true_section_names_every_live_verb() -> None:
    text = SPEC.read_text(encoding="utf-8")
    lines = text.splitlines()
    starts = [
        i for i, line in enumerate(lines)
        if re.match(rf"^#{{1,4}}\s+{re.escape(SPEC_ROSTER_SECTION)}(\s|$)", line)
    ]
    assert len(starts) == 1, (
        f"SPEC.md must carry exactly one section {SPEC_ROSTER_SECTION} heading for the "
        f"docstring's pointer to resolve; found {len(starts)}"
    )
    start = starts[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^#{1,3}\s", lines[i])),
        len(lines),
    )
    section = "\n".join(lines[start:end])
    missing = [
        v for v in _roster_from_help()
        if not re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", section)
    ]
    assert not missing, (
        f"the docstring sends the reader to SPEC section {SPEC_ROSTER_SECTION} for each "
        f"verb's contract, but that section never names {missing}"
    )


# ==========================================================================
# MUTATION -- the control the sibling oracle cannot run on itself: aimed at the
# docstring this iteration deleted, its assertions must FAIL.
# ==========================================================================
@pytest.mark.parametrize(
    "test_name",
    [
        "test_b01_module_docstring_names_live_verb_count_derived",
        "test_b02_retired_count_words_are_absent",
        "test_b04_module_docstring_roster_is_empty_or_complete",
    ],
)
def test_mut_sibling_guard_rejects_the_stale_docstring(
    test_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sibling = _load_sibling()
    stale = tmp_path / "cli_stale.py"
    stale.write_text(STALE_DOCSTRING_SAMPLE, encoding="utf-8")
    # Sanity-check the sample before trusting the mutation: it must really carry both
    # defects, or a "the guard fires" result would prove nothing about either.
    doc = _collapse(ast.get_docstring(ast.parse(stale.read_text(encoding="utf-8"))) or "")
    assert "fifteen verbs" in doc and _longest_comma_run(doc, _roster_from_help()) == 15, (
        f"the reconstructed stale sample lost its defects; collapsed docstring: {doc!r}"
    )

    monkeypatch.setattr(sibling, "CLI_SOURCE", stale)
    sibling._module_doc.cache_clear() if hasattr(sibling._module_doc, "cache_clear") else None
    with pytest.raises(AssertionError):
        getattr(sibling, test_name)()


def test_mut_sibling_guard_passes_on_the_live_docstring() -> None:
    # The other half of the two-sidedness: unmutated, those same three assertions must
    # pass, so the failures above are attributable to the docstring and not to the
    # patching machinery.
    sibling = _load_sibling()
    for name in (
        "test_b01_module_docstring_names_live_verb_count_derived",
        "test_b02_retired_count_words_are_absent",
        "test_b04_module_docstring_roster_is_empty_or_complete",
        "test_b05_module_docstring_points_at_help_and_spec_section",
    ):
        getattr(sibling, name)()


def test_mut_sibling_guard_is_oo_durable_it_reads_source_not_dunder_doc() -> None:
    # Under `python -OO` docstrings are discarded at compile time, so a guard reading
    # `cli.__doc__` degrades to a vacuous pass over an empty string. Structural check:
    # the sibling must parse the source and must never touch a `__doc__` attribute.
    tree = ast.parse(SIBLING.read_text(encoding="utf-8"))
    dunder_doc = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "__doc__"
    ]
    assert not dunder_doc, (
        f"{SIBLING.name} reads a __doc__ attribute at line(s) {dunder_doc}; docstrings "
        "are gone under -OO, so the guard must source-parse instead"
    )
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_docstring"
    ]
    assert calls, f"{SIBLING.name} never calls ast.get_docstring -- it cannot be -OO durable"


# ==========================================================================
# CENSUS -- the root cause. No tracked test may assert that a RETIRED count word
# is PRESENT in a docstring; that shape is what red the build for four iterations.
# ==========================================================================
def _wrong_way_pins(source: str) -> list[tuple[int, str]]:
    """Line numbers where a retired count word is asserted to be IN something."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Compare) and len(node.ops) == 1):
            continue
        if not isinstance(node.ops[0], ast.In):
            continue
        left = node.left
        if isinstance(left, ast.Constant) and isinstance(left.value, str):
            if left.value.strip().lower() in RETIRED_COUNT_WORDS:
                out.append((node.lineno, left.value))
    return out


@cache
def _tracked_test_modules() -> tuple[Path, ...]:
    listing = subprocess.run(
        ["git", "ls-files", "tests"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    return tuple(REPO / p for p in listing if p.endswith(".py"))


def test_census_detector_fires_on_a_planted_wrong_way_pin() -> None:
    # Anti-vacuity: the census below reports zero, and a detector that can only
    # report zero is indistinguishable from one that never looks.
    planted = 'def t(doc):\n    assert "fifteen" in doc\n'
    assert _wrong_way_pins(planted) == [(2, "fifteen")], (
        f"census detector broken: {_wrong_way_pins(planted)}"
    )
    # ... and must not fire on the honest NOT-in shape every guard here uses.
    assert _wrong_way_pins('def t(doc):\n    assert "fifteen" not in doc\n') == []


def test_census_no_tracked_test_pins_a_retired_count_word_as_present() -> None:
    modules = _tracked_test_modules()
    assert len(modules) > 200, (
        f"census walked only {len(modules)} tracked test modules -- `git ls-files "
        "tests` returned an implausibly small domain, so a clean result means nothing"
    )
    assert any(m.name == Path(__file__).name for m in modules), (
        "this module is outside its own census domain -- run `git add -N` on it so the "
        "census measures the tree that will actually be committed"
    )
    offenders = {
        m.relative_to(REPO).as_posix(): pins
        for m in modules
        if (pins := _wrong_way_pins(m.read_text(encoding="utf-8")))
    }
    assert not offenders, (
        "a test asserts a RETIRED verb-count word is PRESENT, which makes the honest "
        f"docstring correction red the build -- the exact defect that survived four "
        f"roster iterations: {offenders}"
    )
