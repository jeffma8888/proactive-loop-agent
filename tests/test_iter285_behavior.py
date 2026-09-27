"""Black-box oracle for foundry iteration 325 (state-dir iteration 473, ROADMAP #304):
``collectors/dir_source.py``'s module docstring states the shared walk's measured AFTER
beside its BEFORE and quotes ``collectors/text_source.py`` verbatim -- written by the tester
from the spec alone (pm.md ``## Expected Behaviors``), the repo's own ``tests/`` tree,
``ROADMAP.md`` / ``ROADMAP_ARCHIVE.md`` and by IMPORTING the two public collector modules.

WHY THIS MODULE EXISTS. Until foundry iter 325 ``dir_source.py`` priced the shared walk
only in the BEFORE tense ("13 ``os.walk`` traversals ... ~915 ms" before it landed) and
attributed to its sibling the words ``called the walk "the missing half: the I/O"`` when
``text_source.py`` says of ITSELF "This module is the missing half: the I/O." -- two public
docstrings one file apart disagreeing about which module is "the missing half". This module
binds the corrected prose to live values: the AFTER integer to
``tests.test_iter192_behavior.WALK_BUDGET`` (imported, never respelled -- lowering the budget
without the prose reds here, and vice versa) and every double-quoted span in the
``text_source.py`` paragraph to ``text_source.__doc__`` itself, so a paraphrase can never
again be dressed as a quotation.

WHAT THIS MODULE GRADES (THREE collected items -- ``make readme-headroom`` read
``binding_headroom == MIN_BINDING_HEADROOM`` at the parent commit once three items were
added, so the module is funded 1:1 by three retired assert-message-only duplicates of
``assert len(all_collectors()) == 17``, see ``RETIRED_TESTS``; extra assertions live INSIDE
these three bodies, never as a fourth item or a parametrization):
(1) behaviors 1+2: exactly one ``Measured AFTER ... **N** ``os.walk`` calls per scan``
sentence, ``N == WALK_BUDGET``, its paragraph names all three remaining walk owners
(``this module`` / ``dir_source.py``, ``filesystem.py``, ``notes.py`` -- the same trio
test_iter187 pins as the only walkers), and the BEFORE phrase ``before this module landed``
shares that paragraph, so the BEFORE figure never stands alone again;
(2) behaviors 3+4: in the one paragraph naming ``text_source.py`` every ``"..."`` span is a
verbatim substring of the whitespace-normalised ``text_source.__doc__`` (non-empty list, so
never vacuous), the misattribution ``called the walk "the missing half`` is gone, the true
span ``"This module is the missing half: the I/O."`` is present and the word ``itself``
sits within the 80 characters before it;
(3) behaviors 6+7: ROADMAP.md holds exactly one ``- #304`` Done-ledger row (<= 120 chars,
tagged ``(foundry iter 325)`` exactly once, naming ``WALK_BUDGET`` and ``text_source``),
the index keeps its 20 rows with no #304 row, ROADMAP_ARCHIVE.md never mentions #304,
``test_iter264::EXPECTED_LEDGER_ROWS`` was re-keyed past 92, the three named duplicates are
gone while their canonical copy survives, and this module holds exactly three collected
items and bounds no document by size (test_iter172's census).

ISOLATION CONTRACT (honored). Every assertion was written from pm.md's Expected Behaviors,
the ``tests/`` tree, the two roadmap files, and by importing the public modules and reading
their ``__doc__``. No file under ``src/`` was read by the tester; no engineer/reviewer
notes, no ``git diff``.

Offline and deterministic: no subprocess, no network, no tmp files. Every docstring
assertion goes through ``inspect.cleandoc`` and then ``re.sub(r"\\s+", " ", ...)`` because
3.13 strips the common docstring indent and 3.12 does not, and a later reflow of the prose
must not red a substring test.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from proactive_loop.collectors import dir_source as DIR
from proactive_loop.collectors import text_source as TEXT
from tests.test_iter172_behavior import roadmap_size_bounds
from tests.test_iter192_behavior import WALK_BUDGET
from tests.test_iter264_behavior import EXPECTED_LEDGER_ROWS

REPO = Path(__file__).resolve().parents[1]
ROADMAP = REPO / "ROADMAP.md"
ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"

#: Behavior 1: the AFTER sentence, per pm.md's regex (applied to the cleandoc'd docstring).
AFTER_RE = re.compile(r"Measured AFTER[^.]*\*\*(\d+)\*\* ``os\.walk`` calls per scan")
#: The three remaining walk owners pm.md names (test_iter187 pins the same trio of modules).
OWNER_FILESYSTEM = "filesystem.py"
OWNER_NOTES = "notes.py"
OWNER_SELF = ("dir_source.py", "this module")
#: Behavior 2: the BEFORE figure's anchor phrase.
BEFORE_PHRASE = "before this module landed"
#: Behaviors 3+4: the sibling's name, the retracted misattribution and the true span.
SIBLING = "text_source.py"
MISATTRIBUTION = 'called the walk "the missing half'
TRUE_SPAN = "This module is the missing half: the I/O."
ATTRIBUTION_WORD = re.compile(r"\bitself\b", re.IGNORECASE)
ATTRIBUTION_WINDOW = 80

#: Behavior 6 records.
LEDGER_ROW_NUMBER = 304
ITER_TAG = "(foundry iter 325)"
LEDGER_ROW_MAX_CHARS = 120  # tests/test_iter241_behavior.py cap
LEDGER_ROW_NEEDLES = ("dir_source", "WALK_BUDGET", "text_source", "verbatim")
INDEX_ROWS = 20  # #304 never had an index row (mirrors #303 in 685a5ba)
LEDGER_ROWS_BEFORE = 92  # test_iter264::EXPECTED_LEDGER_ROWS at the parent commit
COLLECTED_ITEMS = 3

#: Behavior 7 funding: the assert-message-only duplicates retired in this commit -- every
#: body was ``assert len(all_collectors()) == 17`` differing only in its message.
RETIRED_TESTS: tuple[tuple[str, str], ...] = (
    ("test_iter87_behavior.py", "test_b7_collector_count_unchanged"),
    ("test_iter89_behavior.py", "test_b7_collector_registry_count_unchanged"),
    ("test_iter90_behavior.py", "test_b7_collector_registry_count_unchanged"),
)
#: The canonical copy that must SURVIVE (a ``test_iter283::KEEPERS`` entry).
KEEPERS: tuple[tuple[str, str], ...] = (
    ("test_iter75_behavior.py", "test_b12_collector_count_fifteen"),
)


def _doc(module: object) -> str:
    doc = getattr(module, "__doc__", None)
    assert isinstance(doc, str) and doc.strip(), f"precondition: {module!r} has a docstring"
    return inspect.cleandoc(doc)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _paragraphs(doc: str) -> list[str]:
    """Paragraphs per pm.md: split on a blank line (after cleandoc)."""
    return [p for p in re.split(r"\n[ \t]*\n", doc) if p.strip()]


def _only(paragraphs: list[str], needle: str, label: str) -> str:
    hits = [p for p in paragraphs if needle in p]
    assert len(hits) == 1, (
        f"{label}: exactly one paragraph of dir_source.__doc__ contains {needle!r}; "
        f"got {len(hits)}"
    )
    return hits[0]


# ===========================================================================
# Behaviors 1 + 2 -- the AFTER sentence exists, is bound, and sits beside the BEFORE.
# ===========================================================================


def _b1_after_sentence_present_and_bound(doc: str) -> str:
    found = AFTER_RE.findall(doc)
    assert len(found) == 1, (
        f"behavior 1: exactly one 'Measured AFTER ... **N** ``os.walk`` calls per scan' "
        f"sentence in dir_source.__doc__; got {found!r}"
    )
    assert int(found[0]) == WALK_BUDGET, (
        f"behavior 1: the AFTER integer {found[0]} must equal "
        f"tests.test_iter192_behavior.WALK_BUDGET = {WALK_BUDGET}; lower both together"
    )
    paragraphs = _paragraphs(doc)
    owners = [p for p in paragraphs if AFTER_RE.search(p)]
    assert len(owners) == 1, "behavior 1: the AFTER sentence lives in exactly one paragraph"
    paragraph = owners[0]
    assert any(name in paragraph for name in OWNER_SELF), (
        f"behavior 1: the AFTER paragraph names this module ({OWNER_SELF!r}) as a walk owner"
    )
    assert OWNER_FILESYSTEM in paragraph, (
        f"behavior 1: the AFTER paragraph names {OWNER_FILESYSTEM!r} as a walk owner"
    )
    assert OWNER_NOTES in paragraph, (
        f"behavior 1: the AFTER paragraph names {OWNER_NOTES!r} as a walk owner"
    )
    return paragraph


def _b2_before_never_stands_alone(doc: str, after_paragraph: str) -> None:
    assert BEFORE_PHRASE in doc, f"behavior 2: {BEFORE_PHRASE!r} is still in dir_source.__doc__"
    before_paragraph = _only(_paragraphs(doc), BEFORE_PHRASE, "behavior 2")
    assert before_paragraph == after_paragraph, (
        "behavior 2: the BEFORE figure and the AFTER sentence share ONE paragraph -- "
        "a docstring whose BEFORE paragraph has no AFTER fails"
    )
    assert AFTER_RE.search(before_paragraph), (
        "behavior 2: the AFTER sentence appears in the BEFORE paragraph"
    )


def test_b1_b2_after_sentence_bound_to_walk_budget_and_beside_the_before() -> None:
    doc = _doc(DIR)
    _b2_before_never_stands_alone(doc, _b1_after_sentence_present_and_bound(doc))


# ===========================================================================
# Behaviors 3 + 4 -- every quoted span is the sibling's own words, attributed to itself.
# ===========================================================================


def _b3_quote_fidelity(dir_doc: str, text_doc_n: str) -> str:
    paragraph = _normalise(_only(_paragraphs(dir_doc), SIBLING, "behavior 3"))
    spans = re.findall(r'"([^"]+)"', paragraph)
    assert spans, (
        f"behavior 3: the {SIBLING!r} paragraph quotes the sibling at least once "
        "(an empty span list would make this test vacuous)"
    )
    for span in spans:
        assert span in text_doc_n, (
            f"behavior 3: quoted span {span!r} is not a verbatim substring of "
            "text_source.__doc__ (whitespace-normalised) -- a paraphrase dressed as a quote"
        )
    return paragraph


def _b4_misattribution_gone(dir_doc_n: str, text_doc_n: str) -> None:
    assert MISATTRIBUTION not in dir_doc_n, (
        f"behavior 4: {MISATTRIBUTION!r} must not occur in dir_source.__doc__ -- "
        "text_source.py says that of ITSELF, not of the walk"
    )
    assert TRUE_SPAN in text_doc_n, (
        f"behavior 4 precondition: text_source.__doc__ really says {TRUE_SPAN!r}"
    )
    quoted = f'"{TRUE_SPAN}"'
    assert quoted in dir_doc_n, (
        f"behavior 4: dir_source.__doc__ quotes {quoted} verbatim"
    )
    assert dir_doc_n.count(quoted) == 1, "behavior 4: the true span is quoted exactly once"
    start = dir_doc_n.index(quoted)
    window = dir_doc_n[max(0, start - ATTRIBUTION_WINDOW) : start]
    assert ATTRIBUTION_WORD.search(window), (
        f"behavior 4: the word 'itself' must occur within the {ATTRIBUTION_WINDOW} characters "
        f"before the quoted span, attributing it to the sibling; window was {window!r}"
    )


def test_b3_b4_quoted_spans_are_the_siblings_own_words_about_itself() -> None:
    dir_doc = _doc(DIR)
    text_doc_n = _normalise(_doc(TEXT))
    _b3_quote_fidelity(dir_doc, text_doc_n)
    _b4_misattribution_gone(_normalise(dir_doc), text_doc_n)


# ===========================================================================
# Behaviors 6 + 7 -- records and funding (one item).
# ===========================================================================


def _index_rows(text: str) -> list[str]:
    rows = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) > 2 and line.startswith("|") and parts[1].strip().isdigit():
            rows.append(line)
    return rows


def _b6_roadmap_records() -> None:
    text = ROADMAP.read_text(encoding="utf-8")
    ledger = [line for line in text.splitlines() if line.startswith(f"- #{LEDGER_ROW_NUMBER} ")]
    assert len(ledger) == 1, (
        f"behavior 6: exactly one Done-ledger row for #{LEDGER_ROW_NUMBER}; got {ledger!r}"
    )
    row = ledger[0]
    assert len(row) <= LEDGER_ROW_MAX_CHARS, (
        f"behavior 6: the #{LEDGER_ROW_NUMBER} row is <= {LEDGER_ROW_MAX_CHARS} chars; "
        f"got {len(row)}"
    )
    assert row.endswith(ITER_TAG), f"behavior 6: the row ends with {ITER_TAG!r}; got {row!r}"
    for needle in LEDGER_ROW_NEEDLES:
        assert needle in row, f"behavior 6: the #{LEDGER_ROW_NUMBER} row names {needle!r}"
    assert text.count(ITER_TAG) == 1, (
        f"behavior 6: {ITER_TAG} appears exactly once in ROADMAP.md (one row per iteration)"
    )
    rows = _index_rows(text)
    numbers = [int(r.split("|")[1].strip()) for r in rows]
    assert len(rows) == INDEX_ROWS, (
        f"behavior 6: no index row is retired -- the index keeps {INDEX_ROWS} rows; got {len(rows)}"
    )
    assert LEDGER_ROW_NUMBER not in numbers, f"behavior 6: #{LEDGER_ROW_NUMBER} never had an index row"
    assert EXPECTED_LEDGER_ROWS > LEDGER_ROWS_BEFORE, (
        f"behavior 6: test_iter264::EXPECTED_LEDGER_ROWS was re-keyed past {LEDGER_ROWS_BEFORE} "
        f"for the #{LEDGER_ROW_NUMBER} row; got {EXPECTED_LEDGER_ROWS}"
    )

    archive = ARCHIVE.read_text(encoding="utf-8")
    assert f"#{LEDGER_ROW_NUMBER}" not in archive, (
        f"behavior 6: ROADMAP_ARCHIVE.md is untouched (no #{LEDGER_ROW_NUMBER} bullet or row)"
    )


def _b7_funding_and_self_shape() -> None:
    tests_dir = REPO / "tests"
    for module, name in RETIRED_TESTS:
        source = (tests_dir / module).read_text(encoding="utf-8")
        assert f"def {name}(" not in source, (
            f"behavior 7: {module}::{name} was retired to fund this module; it is back"
        )
    for module, name in KEEPERS:
        source = (tests_dir / module).read_text(encoding="utf-8")
        assert f"def {name}(" in source, (
            f"behavior 7: canonical copy {module}::{name} must survive"
        )

    own_source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(own_source)
    collected = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert len(collected) == COLLECTED_ITEMS, (
        f"behavior 7: this module holds exactly {COLLECTED_ITEMS} collected items; "
        f"got {collected}"
    )
    marker = "param" + "etrize"
    assert marker not in own_source.replace('"param" + "etrize"', ""), (
        "behavior 7: no parametrization multiplies the collected count"
    )
    assert roadmap_size_bounds(own_source) == (), (
        "this module must not bound ROADMAP.md by size (test_iter172 census); "
        f"found {roadmap_size_bounds(own_source)}"
    )


def test_b6_b7_roadmap_records_and_funding() -> None:
    _b6_roadmap_records()
    _b7_funding_and_self_shape()
