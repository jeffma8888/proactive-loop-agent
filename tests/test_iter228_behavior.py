"""Drift guard: EVERY spelled subparser/subcommand count in ``src/proactive_loop/cli.py``
prose is bound to the LIVE ``build_parser()`` roster -- comments included.

Why this file exists
-------------------
``cli.py`` carried a design comment justifying where the exit-code contract lives:
"duplicating it onto *fifteen* subparsers would be *fifteen* more copies". The live
parser builds SEVENTEEN. The sentence was introduced by factory iteration 152 and
survived iteration 232 -- the iteration whose whole purpose was hunting that exact
stale word -- because both guards it shipped (``tests/test_iter210_behavior.py`` and
``tests/test_iter211_behavior.py``) pin their SUBJECT to ``_module_doc()``, the first
~40 lines of the file. So ``fifteen`` was a build-failing word at the top of ``cli.py``
and a permitted word ~500 lines down. That is a guard whose DOMAIN is one function too
narrow, and the narrow domain is worth more than the sentence.

Scoped by NOUN, not by WORD -- and that choice was measured
----------------------------------------------------------
Censusing ``<number> [modifier] <noun>`` over the comments plus docstrings of every
module in ``src/proactive_loop/`` gives ``subparser(s)``/``subcommand(s)`` = **2**
phrases, against ``verb(s)`` = 15 and ``collectors`` = 15. The larger classes are
dominated by honest PARTIAL claims ("two verbs cannot drift", "four verbs") and by one
operator-sanctioned DATED claim -- ``cli.py``'s ``--json`` alias comment says the flag
was the idiom "on 14 of the 16 verbs" *as of the commit that landed it*, and
``tests/test_iter218_behavior.py``'s docstring records on the record that widening a
count guard onto that prose would red the build on correct text. A ``verbs``-scoped ban
would need a carve-out list, which is the one place a guard can never look. The
``subparser``/``subcommand`` class needs none: it is the package's only clean
TOTAL-ROSTER noun class, and the live tree supplies both fixtures the guard needs --
one true defect and one honest real-negative, in the same file, against the same
registry.

Known limitation, stated rather than discovered
-----------------------------------------------
Every ``<number> subparser(s)|subcommand(s)`` phrase is read as a total-roster claim,
so a legitimate PARTIAL claim ("two subparsers accept ``--json``") would be failed.
Measured: zero such phrases exist today. The mitigation is the finding MESSAGE, which
tells the author to rephrase without a bare count -- never a carve-out set.

Four measurement conventions, all load-bearing
----------------------------------------------
1. SOURCE TEXT, never ``__doc__``. Everything is parsed out of a source string, so the
   guard still bites under ``python -OO``, which discards docstrings at compile time
   and would turn a ``__doc__``-based check into a vacuous pass. Behavior 8 proves this
   by compiling a fixture at ``optimize=2`` and showing ``__doc__`` is ``None`` while
   the checker still reports the finding.
2. Docstrings arrive through ``ast.get_docstring(node, clean=True)``, i.e. through
   ``inspect.cleandoc``. CPython 3.13 strips a docstring's common leading indent at
   COMPILE time and 3.12 does not, so a ``__doc__`` route diverges across the CI
   matrix; the ``clean=True`` route is identical on both legs. Behavior 8 asserts that
   equality directly.
3. Comments are grouped into BLOCKS of consecutive lines before matching, so a phrase
   hard-wrapped across two ``#`` lines cannot hide. Measured on the live file: grouped
   and per-line extraction return the SAME population (2), so the grouping costs no
   false positives here and closes a real fail-open.
4. Blobs are whitespace-collapsed (``" ".join(text.split())``), so a wrap inside a
   docstring cannot fake either verdict.

Why the controls are planted, not sampled
-----------------------------------------
A rule exercised only against a tree that already satisfies it is indistinguishable
from a rule that can never fail. So the checker is proven in BOTH directions against
in-string fixtures: stale spelled counts, a stale DIGIT count, a wrapped comment, and
five honest-prose samples that must stay silent. The live file is then measured with
the same function, and the anti-vacuity assertion fails if it examined nothing.

Expected Behaviors covered (numbered as in the iteration spec):

1. ``fifteen`` and ``thirteen`` occur zero times in ``cli.py``; the corrected sentence
   keeps its ``# TOP-LEVEL only.`` opening.
2. The checker's prose domain is comments (``tokenize``) plus the docstrings of the
   module and of every function/async function/class (``ast.get_docstring``).
3. Over the post-fix ``cli.py`` the checker reports zero findings from a population of
   exactly 2 -- and a population of zero FAILS (anti-vacuity).
4. The compared count is DERIVED at run time from ``build_parser()``'s one
   ``_SubParsersAction``; both surviving phrases spell it.
5. The guard BITES: a planted stale spelled count yields exactly one finding carrying
   the phrase, the word found and the count expected.
6. The guard is SILENT on honest prose, including the operator-sanctioned dated claim.
7. A DIGIT spelling cannot bypass it, and no digit-form phrase exists in ``cli.py``.
8. Source text, not ``__doc__``; and identical under 3.12 and 3.13.
9. ``ROADMAP.md`` gains exactly one ``- #250 `` ledger line, stays within the
   contracted size, and ``#250`` appears in ``ROADMAP.md`` only.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from proactive_loop import cli

REPO: Final[Path] = Path(__file__).resolve().parents[1]
CLI_SOURCE: Final[Path] = REPO / "src" / "proactive_loop" / "cli.py"
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ROADMAP_ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"

#: The ledger row this iteration ships, and the roadmap ceiling it must respect:
#: ``tests/test_iter214_behavior.py`` contracts CHAR_LIMIT 40_000 with MIN_HEADROOM
#: 4_000, so the effective maximum is their difference. Kept as one derived
#: expression rather than a second literal 36_000 to keep them from drifting apart.
LEDGER_ROW: Final[str] = "- #250 "
ITER_TAG: Final[str] = "(foundry iter 250)"
ROADMAP_CEILING: Final[int] = 40_000 - 4_000

#: int -> English number word, 1..20. Same shape and same extend-me contract as
#: ``tests/test_iter210_behavior.py``'s ``_NUM_WORD``; ``_word`` fails loudly past the
#: range rather than letting a growing roster rot this guard into silence.
_NUM_WORD: Final[dict[int, str]] = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
}
_WORD_NUM: Final[dict[str, int]] = {word: n for n, word in _NUM_WORD.items()}

#: Count words this file's prose has published and retired. Behavior 1 pins them as a
#: regression check on the specific historical defect, guarded by a precondition that
#: refuses to become the next wrong-way oracle if the roster ever shrinks to one.
RETIRED_COUNT_WORDS: Final[tuple[str, ...]] = ("thirteen", "fifteen")

#: The total-roster noun class. Deliberately NOT ``verb`` or ``collector`` -- see the
#: module docstring; widening it would red the build on accurate prose.
_NOUN: Final[str] = r"subparsers?|subcommands?"

#: ``<number> [one optional word] <noun>``. The number group is word-bounded on BOTH
#: sides, which is what makes ``seventeen`` parse as 17 and never as ``seven`` plus a
#: stray ``teen``: the trailing ``\b`` fails inside the word and the engine backtracks
#: out of the short alternative. Alternatives are additionally sorted longest-first so
#: the behaviour does not rest on backtracking alone. Digits are accepted so a numeric
#: spelling cannot bypass the guard (behavior 7).
_PHRASE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b((?:"
    + "|".join(sorted(_NUM_WORD.values(), key=len, reverse=True))
    + r")|\d+)\b(?:\s+[A-Za-z][\w'-]*)?\s+("
    + _NOUN
    + r")\b",
    re.IGNORECASE,
)


def _word(n: int) -> str:
    assert n in _NUM_WORD, f"extend _NUM_WORD past {n} to keep the drift-guard sound"
    return _NUM_WORD[n]


@dataclass(frozen=True)
class Phrase:
    """One ``<number> [modifier] <noun>`` occurrence found in prose."""

    text: str
    number: str
    noun: str

    @property
    def value(self) -> int | None:
        """The spelled number as an int, or ``None`` when it is out of range."""
        low = self.number.lower()
        if low.isdigit():
            return int(low)
        return _WORD_NUM.get(low)


@dataclass(frozen=True)
class Finding:
    """A phrase whose count contradicts the live roster."""

    phrase: str
    found: str
    expected: int

    def message(self) -> str:
        return (
            f"stale roster count in cli.py prose: {self.phrase!r} says {self.found!r} "
            f"but build_parser() advertises {self.expected} "
            f"({_word(self.expected)}); if this is a PARTIAL claim rather than a total, "
            f"rephrase it without a bare count"
        )


def comment_blocks(source: str) -> list[str]:
    """Comments from ``source``, grouped into runs of consecutive lines.

    Grouping is what stops a phrase hard-wrapped across two ``#`` lines from hiding.
    ``tokenize`` is used rather than a line regex so a ``#`` inside a string literal is
    not mistaken for a comment.
    """
    tokens = [
        tok
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.COMMENT
    ]
    blocks: list[str] = []
    current: list[str] = []
    previous_line: int | None = None
    for tok in tokens:
        line = tok.start[0]
        if previous_line is not None and line == previous_line + 1:
            current.append(tok.string.lstrip("#").strip())
        else:
            if current:
                blocks.append(" ".join(current))
            current = [tok.string.lstrip("#").strip()]
        previous_line = line
    if current:
        blocks.append(" ".join(current))
    return blocks


def docstring_blobs(source: str) -> list[str]:
    """Docstrings of the module and of every function/async function/class.

    Read through ``ast.get_docstring(..., clean=True)`` so the result is
    ``inspect.cleandoc``-normalised and therefore identical on the 3.12 and 3.13 CI
    legs, which disagree about stripping a docstring's common indent at compile time.
    """
    tree = ast.parse(source)
    blobs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            doc = ast.get_docstring(node, clean=True)
            if doc:
                blobs.append(doc)
    return blobs


def prose_blobs(source: str) -> list[str]:
    """All prose in ``source``, whitespace-collapsed: comment blocks + docstrings."""
    raw = comment_blocks(source) + docstring_blobs(source)
    return [" ".join(blob.split()) for blob in raw]


def phrases(source: str) -> list[Phrase]:
    """Every roster-count phrase in ``source``'s prose, in discovery order."""
    found: list[Phrase] = []
    for blob in prose_blobs(source):
        for match in _PHRASE_RE.finditer(blob):
            found.append(
                Phrase(text=match.group(0), number=match.group(1), noun=match.group(2))
            )
    return found


def check_source(source: str, live_count: int) -> list[Finding]:
    """Findings for every phrase in ``source`` whose count is not ``live_count``."""
    return [
        Finding(phrase=p.text, found=p.number, expected=live_count)
        for p in phrases(source)
        if p.value != live_count
    ]


def live_subparser_count() -> int:
    """The live roster size, derived from ``build_parser()`` -- never a literal."""
    actions = [
        action
        for action in cli.build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert len(actions) == 1, (
        f"expected exactly one _SubParsersAction in build_parser(), got {len(actions)}"
    )
    return len(actions[0].choices)


def cli_text() -> str:
    return CLI_SOURCE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------------
# Behavior 1 -- the retired count words are gone from the whole file
# --------------------------------------------------------------------------------


def test_b1_retired_count_words_absent_from_cli_source() -> None:
    live = live_subparser_count()
    assert _word(live) not in RETIRED_COUNT_WORDS, (
        f"the live roster is {live} ({_word(live)}), which is a RETIRED count word -- "
        "this assertion would become a wrong-way oracle; re-derive it before editing"
    )
    lowered = cli_text().lower()
    for stale in RETIRED_COUNT_WORDS:
        assert stale not in lowered, (
            f"{CLI_SOURCE} still contains the retired count word {stale!r} "
            f"({lowered.count(stale)} occurrence(s)); the live roster is {live}"
        )


def test_b1_corrected_sentence_keeps_its_top_level_opening() -> None:
    text = cli_text()
    assert "# TOP-LEVEL only." in text, (
        "the corrected exit-code design comment must keep its '# TOP-LEVEL only.' "
        "opening -- tests/test_iter152_behavior.py reasons about that section"
    )


# --------------------------------------------------------------------------------
# Behavior 2 -- the checker's prose domain
# --------------------------------------------------------------------------------


_DOMAIN_FIXTURE: Final[str] = '''"""Module docstring: MODULE_MARK."""

# comment: COMMENT_MARK

CONSTANT = "a plain string literal: STRING_MARK"


class Thing:
    """Class docstring: CLASS_MARK."""

    def method(self) -> None:
        """Method docstring: METHOD_MARK."""
        "a bare expression string that is NOT a docstring: EXPR_MARK"


async def coro() -> None:
    """Async docstring: ASYNC_MARK."""
'''


def test_b2_prose_domain_is_comments_plus_every_docstring_kind() -> None:
    blob = " || ".join(prose_blobs(_DOMAIN_FIXTURE))
    for mark in (
        "MODULE_MARK",
        "COMMENT_MARK",
        "CLASS_MARK",
        "METHOD_MARK",
        "ASYNC_MARK",
    ):
        assert mark in blob, f"{mark} missing from the checker's prose domain"
    for mark in ("STRING_MARK", "EXPR_MARK"):
        assert mark not in blob, (
            f"{mark} is code, not prose -- the checker must not read string literals"
        )


def test_b2_comment_hash_inside_a_string_is_not_prose() -> None:
    source = 'X = "# fifteen subparsers live in here"\n'
    assert comment_blocks(source) == [], (
        "a '#' inside a string literal is not a comment -- use tokenize, not a regex"
    )
    assert phrases(source) == []


# --------------------------------------------------------------------------------
# Behavior 3 -- the live file is clean, and the guard proves it looked
# --------------------------------------------------------------------------------


def test_b3_post_fix_cli_prose_is_clean_from_a_non_empty_population() -> None:
    source = cli_text()
    population = phrases(source)
    assert population, (
        "anti-vacuity: the checker examined ZERO roster-count phrases in "
        f"{CLI_SOURCE}, so a clean verdict would prove nothing"
    )
    assert len(population) == 2, (
        "expected exactly two roster-count phrases in cli.py prose, got "
        f"{[p.text for p in population]}"
    )
    findings = check_source(source, live_subparser_count())
    assert findings == [], [f.message() for f in findings]


def test_b3_grouped_and_per_line_comment_extraction_agree_on_the_live_file() -> None:
    """Convention 3's cost is measured, not assumed: grouping adds no false positive."""
    source = cli_text()
    per_line = [
        " ".join(tok.string.lstrip("#").strip().split())
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.COMMENT
    ]
    per_line_hits = [m.group(0) for b in per_line for m in _PHRASE_RE.finditer(b)]
    grouped_hits = [
        m.group(0)
        for b in (" ".join(x.split()) for x in comment_blocks(source))
        for m in _PHRASE_RE.finditer(b)
    ]
    assert sorted(grouped_hits) == sorted(per_line_hits)


# --------------------------------------------------------------------------------
# Behavior 4 -- the compared count is derived, never a literal
# --------------------------------------------------------------------------------


def test_b4_live_count_is_derived_from_the_parser_roster() -> None:
    parser = cli.build_parser()
    actions = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(actions) == 1
    choices = actions[0].choices
    assert live_subparser_count() == len(choices) == len(set(choices)) > 0


def test_b4_both_surviving_phrases_spell_the_live_count() -> None:
    live = live_subparser_count()
    population = phrases(cli_text())
    assert [p.number.lower() for p in population] == [_word(live), _word(live)], (
        f"expected both phrases to spell {_word(live)!r}, got "
        f"{[p.number for p in population]}"
    )
    assert [p.value for p in population] == [live, live]
    assert {p.noun.lower() for p in population} == {"subparsers", "subcommands"}


def test_b4_the_guard_would_bite_if_the_roster_changed() -> None:
    """Bound to the LIVE count, not to 17: re-run the clean file against a wrong count."""
    live = live_subparser_count()
    findings = check_source(cli_text(), live - 1)
    assert len(findings) == 2, (
        "cli.py's phrases must be judged against the derived count -- against "
        f"{live - 1} both should be findings, got {[f.phrase for f in findings]}"
    )
    assert all(f.expected == live - 1 for f in findings)


# --------------------------------------------------------------------------------
# Behavior 5 -- controls that the guard BITES
# --------------------------------------------------------------------------------


def test_b5_planted_stale_spelled_count_is_exactly_one_finding() -> None:
    live = live_subparser_count()
    source = "# duplicating it onto fifteen subparsers would mean a copy per verb\n"
    findings = check_source(source, live)
    assert len(findings) == 1, [f.phrase for f in findings]
    only = findings[0]
    assert only.phrase == "fifteen subparsers"
    assert only.found == "fifteen"
    assert only.expected == live
    message = only.message()
    assert "fifteen subparsers" in message
    # DERIVED, not the bare literal. tests/test_iter211_behavior.py censuses every
    # tracked test module for a Compare whose LEFT operand is a string constant equal
    # to a RETIRED count word under an `in` op, because that shape is what red the
    # build for four roster iterations. Asserting the finding own `found` field is
    # census-invisible AND strictly stronger: it binds the message to the value the
    # checker reported rather than to a word this file typed. Do not "simplify" it
    # back to a literal -- that reds the suite, measured this iteration.
    assert only.found in message
    assert str(live) in message


def test_b5_stale_count_hides_in_neither_a_docstring_nor_a_modifier_nor_a_wrap() -> None:
    live = live_subparser_count()
    variants = {
        "function docstring": 'def f() -> None:\n    """We wire fifteen subcommands."""\n',
        "one modifier word": "# fifteen top-level subparsers is the roster\n",
        "wrapped across two comment lines": (
            "# duplicating the epilog onto fifteen\n"
            "# subparsers would mean a copy per verb\n"
        ),
        "digit-and-noun in a class docstring": (
            'class C:\n    """Dispatches to 15 subcommands."""\n'
        ),
    }
    for label, source in variants.items():
        findings = check_source(source, live)
        assert len(findings) == 1, f"{label}: got {[f.phrase for f in findings]}"


def test_b5_a_long_number_word_is_not_read_as_its_short_prefix() -> None:
    """``seventeen`` must parse as 17, never as ``seven`` -- the \\b on both ends."""
    source = "# the epilog covers seventeen subparsers\n"
    assert check_source(source, 17) == []
    findings = check_source(source, 7)
    assert len(findings) == 1
    assert findings[0].found == "seventeen"


# --------------------------------------------------------------------------------
# Behavior 6 -- controls that the guard is SILENT on honest prose
# --------------------------------------------------------------------------------


_HONEST_PROSE: Final[tuple[str, ...]] = (
    "# two verbs cannot drift apart if only one of them formats the row\n",
    "# four verbs share this renderer\n",
    "# sixteen collectors shipped before this one\n",
    "# fourteen registered tools answer the dispatch table\n",
    # The operator-sanctioned DATED claim from cli.py's --json alias comment, named as
    # legitimate on the record by tests/test_iter218_behavior.py's docstring. A
    # verbs-scoped guard would red the build on it; noun scoping cannot see it.
    "# --json was the machine-readable idiom on 14 of the 16 verbs\n",
)


def test_b6_honest_prose_produces_no_finding_and_no_phrase() -> None:
    live = live_subparser_count()
    for source in _HONEST_PROSE:
        assert phrases(source) == [], f"{source!r} is not a roster-count phrase"
        assert check_source(source, live) == [], f"{source!r} must stay silent"


def test_b6_the_whole_honest_batch_together_stays_silent() -> None:
    combined = "".join(_HONEST_PROSE)
    assert check_source(combined, live_subparser_count()) == []


def test_b6_a_correct_count_on_the_guarded_noun_is_silent() -> None:
    live = live_subparser_count()
    assert check_source(f"# {_word(live)} subparsers, no more\n", live) == []
    assert check_source(f"# {live} subcommands, no more\n", live) == []


# --------------------------------------------------------------------------------
# Behavior 7 -- a digit spelling cannot bypass the guard
# --------------------------------------------------------------------------------


def test_b7_planted_digit_count_is_exactly_one_finding() -> None:
    live = live_subparser_count()
    findings = check_source("# duplicating it onto 15 subparsers\n", live)
    assert len(findings) == 1, [f.phrase for f in findings]
    assert findings[0].phrase == "15 subparsers"
    assert findings[0].found == "15"
    assert findings[0].expected == live


def test_b7_no_digit_form_roster_phrase_exists_in_cli_prose() -> None:
    digit_form = [p.text for p in phrases(cli_text()) if p.number.isdigit()]
    assert digit_form == [], (
        f"{CLI_SOURCE} carries a digit-form roster count: {digit_form}"
    )


def test_b7_an_out_of_range_spelled_number_is_still_a_finding() -> None:
    """A word outside 1..20 has no value, so it can never equal the live count."""
    live = live_subparser_count()
    findings = check_source("# 999 subparsers, allegedly\n", live)
    assert len(findings) == 1
    assert findings[0].found == "999"


# --------------------------------------------------------------------------------
# Behavior 8 -- source text (not __doc__), and identical on 3.12 and 3.13
# --------------------------------------------------------------------------------


_OO_FIXTURE: Final[str] = (
    '"""Module doc: we wire fifteen subcommands."""\n'
    "\n"
    "def f() -> None:\n"
    '    """Func doc: fifteen subparsers."""\n'
)


def test_b8_checker_reads_source_so_dash_oo_cannot_blind_it() -> None:
    namespace: dict[str, object] = {}
    exec(compile(_OO_FIXTURE, "<fixture>", "exec", optimize=2), namespace)
    assert namespace.get("__doc__") is None, (
        "precondition: optimize=2 must discard docstrings, else this proves nothing"
    )
    function = namespace["f"]
    assert getattr(function, "__doc__") is None
    findings = check_source(_OO_FIXTURE, live_subparser_count())
    assert len(findings) == 2, (
        "the checker must find both stale counts from SOURCE text even though the "
        f"compiled objects carry no __doc__; got {[f.phrase for f in findings]}"
    )


_INDENTED_FIXTURE: Final[str] = (
    "def f() -> None:\n"
    '    """First line.\n'
    "\n"
    "    Indented continuation naming fifteen subparsers.\n"
    '    """\n'
)


def test_b8_docstring_extraction_is_cleandoc_and_so_matrix_stable() -> None:
    tree = ast.parse(_INDENTED_FIXTURE)
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    literal = function.body[0]
    assert isinstance(literal, ast.Expr)
    assert isinstance(literal.value, ast.Constant)
    raw = literal.value.value
    assert isinstance(raw, str)
    assert "\n    " in raw, "precondition: the fixture's docstring must be indented"
    cleaned = ast.get_docstring(function, clean=True)
    assert cleaned == inspect.cleandoc(raw), (
        "clean=True must equal inspect.cleandoc -- that equality is what makes this "
        "guard's verdict identical on the 3.12 and 3.13 CI legs"
    )
    assert cleaned is not None and "\n    " not in cleaned


def test_b8_verdict_is_identical_with_and_without_docstring_indentation() -> None:
    live = live_subparser_count()
    flat = 'def f() -> None:\n    """Indented continuation naming fifteen subparsers."""\n'
    indented = check_source(_INDENTED_FIXTURE, live)
    assert len(indented) == 1
    assert [f.phrase for f in indented] == [f.phrase for f in check_source(flat, live)]


# --------------------------------------------------------------------------------
# Behavior 9 -- the roadmap ledger row and the size contract
# --------------------------------------------------------------------------------


def test_b9_roadmap_gains_exactly_one_ledger_row_for_this_iteration() -> None:
    rows = [
        line for line in ROADMAP.read_text(encoding="utf-8").splitlines()
        if line.startswith(LEDGER_ROW)
    ]
    assert len(rows) == 1, f"expected exactly one {LEDGER_ROW!r} row, got {rows}"
    assert rows[0].rstrip().endswith(ITER_TAG), rows[0]


def test_b9_roadmap_stays_within_the_contracted_ceiling() -> None:
    size = len(ROADMAP.read_text(encoding="utf-8"))
    assert size <= ROADMAP_CEILING, (
        f"ROADMAP.md is {size:,} chars, over the {ROADMAP_CEILING:,}-char effective "
        "ceiling (40,000 limit less the 4,000 contracted headroom) -- relocate "
        "settled ledger rows to ROADMAP_ARCHIVE.md in the same commit"
    )


def test_b9_row_number_lives_in_the_roadmap_only() -> None:
    pattern = re.compile(r"#250\b")
    assert len(pattern.findall(ROADMAP.read_text(encoding="utf-8"))) == 1
    assert pattern.findall(ROADMAP_ARCHIVE.read_text(encoding="utf-8")) == []
