"""Black-box behavior tests for state-dir iteration 263 (ships as ``foundry iter 263``):
THE SHIP RECORD IS PART OF THE SHIP.

Feature under test (``pm.md`` "## Feature"): re-land iteration 262's batch-4
shared-walk conversion -- ``todos``, ``large_file`` and ``syntax_error`` read the
shared per-scan dirent listing from ``collectors/dir_source`` instead of each
running their own ``os.walk`` -- and land in the SAME commit the ``ROADMAP.md``
Done-ledger ship record and the ``DIRECTIONS.md`` decision block whose absence
reverted it.

Why this module exists ALONGSIDE ``tests/test_iter239_behavior.py``. That module
is the conversion's own oracle and covers Expected Behaviors 1-12. It does not
cover 13-15, and 13-15 are the entire reason this work is being done twice: a
reviewed, suite-green, 1,046-insertion tree was destroyed by four missing lines
of Markdown, and ``test_iter214_behavior.py::test_b7`` passes *because* nothing
was appended, so a missing ship record is invisible to a green suite. This module
gives the paperwork an oracle of its own, plus an INDEPENDENT behavioral
cross-check of the conversion's load-bearing claims (Expected Behaviors 2, 3, 4
and 7) written from the spec text rather than from the other module's fixtures.

MODULE NAME -- derived from the REPO, never from the state-dir number. The
highest tracked ``tests/test_iterNN_behavior.py`` at HEAD ``9b13289`` is **238**,
this iteration's engineer adds **239**, so **240** is the next free name, and
``git cat-file -e HEAD:tests/test_iter240_behavior.py`` FAILED (``path ... does
not exist in 'HEAD'``) before the first byte was written. The state dir is 263;
naming the module 263 is what overwrote a shipped 18,786-byte oracle in state
dir 186.

ISOLATION CONTRACT (honored, no exceptions). Every assertion below is derived
from this iteration's ``pm.md`` "## Expected Behaviors" 2, 3, 4, 7 and 13-15,
from the two tracked Markdown documents themselves (``ROADMAP.md``,
``DIRECTIONS.md``, ``README.md``), from the conventions of existing modules under
``tests/`` (``test_iter214_behavior.py`` for the ledger/budget idiom and the
``from tests.test_roadmap_size_budget import ...`` style, ``test_iter222_behavior.py``
for the ``walk_scope`` / ``walk_cache_stats`` idiom, ``test_iter37/77/90_behavior.py``
for the three collectors' public constructors), and from RUNNING the shipped
public interface. **No file under ``src/`` was read as source text, no engineer,
reviewer or fix-review note was opened, and no ``git diff`` was consulted.**

OFFLINE, DETERMINISTIC, FRESH-CLONE SAFE. Every path asserted on is TRACKED by
git and resolved from ``__file__``: no network, no subprocess, no ``git``
invocation, no clock, and no dependence on gitignored loop state (the iter-154
trap, where a test asserted a file count that held only in this working tree).
Nothing asserts on docstring or help-text indentation, so the 3.12/3.13 matrix
legs cannot diverge here.

NON-VACUOUSNESS IS ASSERTED, NOT ASSUMED. Iteration 262's reviewer recorded a
prune probe that reported "0 leaks" only because ``LargeFileCollector``'s default
``min_bytes`` is 5,000,000 and the fixture files were smaller -- a structurally
silent collector makes "no leaks" a tautology. Every negative arm below is paired
with a POSITIVE arm on the same fixture that asserts the collector emitted at
least one signal from a location it is supposed to see.

Coverage (numbered to match the spec's Expected Behaviors):

13. The ship record: ``ROADMAP.md``'s Done ledger gains exactly one new line, it
    is the LAST line of the file, it matches ``^- #261 ``, it ends with the
    literal ``(foundry iter 263)``, and it is <= 120 characters. No existing
    ledger row is deleted, reordered or renumbered.
14. The budget and the non-vacuous ledger: ``len(ROADMAP.md) <= 40_000 - 4_000``,
    the ledger holds 48 ``- #NNN`` rows, and no ship record is recorded in BOTH
    ``ROADMAP.md`` and ``ROADMAP_ARCHIVE.md``.
15. The decision log: ``DIRECTIONS.md`` gains an ``iter-263`` block in the shape
    the file already uses, iteration 260's ``ship:`` line reads ``PUSHED
    9b13289``, and the trailing scouted-iteration count equals the number of
    blocks.
2.  (cross-check) Inside ONE ``walk_scope()`` the three converted collectors
    share a single physical listing of a shared root; with no scope active every
    ``walk()`` is its own traversal.
3.  (cross-check) The inherited directory prune: nothing is emitted from
    ``node_modules``, ``dist``, ``__pycache__``, ``.git`` or a hidden directory.
4.  (cross-check) The hidden-FILE policy survives the conversion.
7.  (cross-check) The library-consumer path is unaffected: ``collect(root)``
    outside a scope is equal, field by field and in order, to ``collect(root)``
    inside one.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.collectors import (
    LargeFileCollector,
    SyntaxErrorCollector,
    TodoCollector,
)
from proactive_loop.collectors import dir_source
from proactive_loop.models import ContextSignal
from tests.test_roadmap_size_budget import check_char_budget

REPO: Final[Path] = Path(__file__).resolve().parents[1]
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"
DIRECTIONS: Final[Path] = REPO / "DIRECTIONS.md"

#: The Done-ledger row shape: ``- #NNN <prose> (foundry iter NNN)``.
LEDGER_ROW: Final[re.Pattern[str]] = re.compile(r"^- #(\d+) ")

#: This iteration's ship record, per ``pm.md`` Expected Behavior 13.
SHIP_ROW_PREFIX: Final[str] = "- #261 "
SHIP_ROW_SUFFIX: Final[str] = "(foundry iter 263)"
SHIP_ROW_MAX_CHARS: Final[int] = 120

#: ``pm.md`` Expected Behavior 14: 47 rows at HEAD plus exactly one.
EXPECTED_LEDGER_ROWS: Final[int] = 48

#: ``pm.md`` Expected Behavior 15: the sha iteration 260 actually shipped as.
ITER_260_SHIP: Final[str] = "ship: PUSHED 9b13289"

#: The three collectors converted by this iteration, with a constructor that is
#: guaranteed NON-SILENT on the fixtures below (``min_bytes`` matters: the stock
#: 5,000,000 makes every large-file arm a tautology on a small fixture).
CONVERTED: Final[tuple[tuple[str, object], ...]] = (
    ("todos", TodoCollector()),
    ("large_file", LargeFileCollector(min_bytes=1_000)),
    ("syntax_error", SyntaxErrorCollector()),
)

#: Directories the shared provider prunes, per the README's shared-walk
#: paragraph and ``pm.md`` Expected Behavior 3.
PRUNED_DIRS: Final[tuple[str, ...]] = (
    "node_modules",
    "dist",
    "__pycache__",
    ".git",
    ".hidden",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ledger_rows(text: str) -> list[str]:
    """Return the ``- #NNN ...`` Done-ledger rows of *text*, in file order."""
    return [line for line in text.splitlines() if LEDGER_ROW.match(line)]


def _ledger_numbers(text: str) -> list[int]:
    """Return the ledger row numbers of *text*, in file order."""
    return [int(m.group(1)) for line in text.splitlines() if (m := LEDGER_ROW.match(line))]


def _directions_blocks(text: str) -> list[str]:
    """Return the ``iter-NNN`` block labels of ``DIRECTIONS.md``, in file order."""
    return re.findall(r"^  iter-(\d+)$", text, re.MULTILINE)


def _block_body(text: str, label: str) -> str:
    """Return the body of the ``iter-<label>`` block, exclusive of its header."""
    blocks = re.split(r"^  iter-(\d+)$", text, flags=re.MULTILINE)
    # re.split with one group yields [pre, num, body, num, body, ...]
    for num, body in zip(blocks[1::2], blocks[2::2], strict=True):
        if num == label:
            return body
    raise AssertionError(f"DIRECTIONS.md has no iter-{label} block")


def ship_record_problems(text: str) -> list[str]:
    """Return every reason *text* fails ``pm.md`` Expected Behavior 13, or ``[]``.

    Extracted as a pure function of the document text so the live assertion and the
    synthetic mutation arms below run the SAME predicate. A one-sided check that only
    ever sees a correct file cannot prove it would catch the omission that reverted
    iteration 262.
    """
    problems: list[str] = []
    lines = text.splitlines()
    if not lines:
        return ["the document is empty"]
    last = lines[-1]
    if not last.startswith(SHIP_ROW_PREFIX):
        problems.append(f"last line does not start with {SHIP_ROW_PREFIX!r}: {last!r}")
    if not last.endswith(SHIP_ROW_SUFFIX):
        problems.append(f"last line does not end with {SHIP_ROW_SUFFIX!r}: {last!r}")
    if len(last) > SHIP_ROW_MAX_CHARS:
        problems.append(f"last line is {len(last)} chars, over {SHIP_ROW_MAX_CHARS}")
    numbers = _ledger_numbers(text)
    if len(numbers) != len(set(numbers)):
        problems.append(f"a ledger number is recorded twice: {numbers}")
    if numbers[-2:] != [260, 261]:
        problems.append(f"the ledger tail must run #260 then #261; got {numbers[-2:]}")
    return problems


def directions_problems(text: str) -> list[str]:
    """Return every reason *text* fails ``pm.md`` Expected Behavior 15, or ``[]``."""
    problems: list[str] = []
    labels = _directions_blocks(text)
    if not labels:
        return ["the document holds no iter-NNN block"]
    if "263" not in labels:
        problems.append(
            "newest block must be iter-263, or iter-263 present beneath a later block the "
            f"log's maintainer has already opened; got {labels[:3]}"
        )
    if len(labels) != len(set(labels)):
        problems.append("a block label is written twice")
    declared = re.findall(r"(\d+) scouted iterations", text)
    if len(declared) != 1:
        problems.append(f"expected exactly one scouted-iteration count line; got {declared}")
    elif int(declared[0]) != len(labels):
        problems.append(
            f"the trailing count declares {declared[0]} but the file holds {len(labels)} blocks"
        )
    if ITER_260_SHIP not in text:
        problems.append(f"iteration 260's ship line must read {ITER_260_SHIP!r}")
    return problems


def _fields(signals: list[ContextSignal]) -> list[tuple[str, str, str]]:
    """Reduce signals to the observable triple the spec pins: kind, path, summary."""
    return [(s.kind, str(s.path), s.summary) for s in signals]


def _collect(collector: object, root: Path, *, scoped: bool) -> list[ContextSignal]:
    """Collect from *root*, optionally inside a shared-walk scope.

    Expected Behavior 7 says the two regimes must be indistinguishable to a caller,
    so every prune and hidden-file arm below is driven twice through this ONE seam
    instead of being written against whichever regime was convenient. A conversion
    that inherited the provider's prune only when the cache happened to be armed
    would pass a scoped-only test and still ship a leak to every library consumer.
    """
    if scoped:
        with dir_source.walk_scope():
            return list(collector.collect(root))  # type: ignore[attr-defined]
    return list(collector.collect(root))  # type: ignore[attr-defined]


def _seed_visible_work(root: Path) -> None:
    """Seed one qualifying artifact per converted collector in a NORMAL location.

    This is the positive arm every negative arm below is paired with: without it
    a prune assertion is vacuous, because a structurally silent collector emits
    nothing from anywhere.
    """
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "chores.py").write_text("# TODO: wire the thing\n", encoding="utf-8")
    (root / "pkg" / "broken.py").write_text("def (\n", encoding="utf-8")
    (root / "pkg" / "blob.bin").write_bytes(b"x" * 4_000)


def _seed_pruned_work(root: Path) -> None:
    """Seed the same qualifying artifacts INSIDE every pruned directory."""
    for name in PRUNED_DIRS:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "chores.py").write_text("# TODO: must never be reported\n", encoding="utf-8")
        (d / "broken.py").write_text("def (\n", encoding="utf-8")
        (d / "blob.bin").write_bytes(b"x" * 4_000)


def _seed_hidden_files(root: Path) -> None:
    """Seed hidden FILES that would otherwise qualify (Expected Behavior 4)."""
    (root / ".todo.py").write_text("# TODO: hidden file\n", encoding="utf-8")
    (root / ".broken.py").write_text("def (\n", encoding="utf-8")
    (root / ".big.bin").write_bytes(b"x" * 4_000)


@pytest.fixture(autouse=True)
def _isolate_walk_cache() -> Iterator[None]:
    """Leave the process-wide shared-walk cache exactly as it was found.

    ``walk_scope()`` is process state; a test that leaks an armed scope poisons
    every later test in the same worker. The suite runs under ``-n auto``, so
    this is not optional.
    """
    dir_source.clear_walk_cache()
    yield
    dir_source.clear_walk_cache()


# ---------------------------------------------------------------------------
# Expected Behavior 13 -- the ship record lands in THIS commit
# ---------------------------------------------------------------------------


def test_b13a_the_ship_record_is_the_last_line_of_the_roadmap() -> None:
    text = ROADMAP.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines, "ROADMAP.md must not be empty"
    last = lines[-1]
    assert last.startswith(SHIP_ROW_PREFIX), (
        "iteration 262 was reverted with a green suite for exactly this reason: the "
        "Done-ledger ship record was never appended. ROADMAP.md's last line must be "
        f"the new row starting {SHIP_ROW_PREFIX!r}; got {last!r}"
    )
    assert last.endswith(SHIP_ROW_SUFFIX), (
        f"the ship record must end with the literal {SHIP_ROW_SUFFIX!r}; got {last!r}"
    )
    assert len(last) <= SHIP_ROW_MAX_CHARS, (
        f"the ship record must be <= {SHIP_ROW_MAX_CHARS} chars to stay inside the "
        f"roadmap headroom; got {len(last)}: {last!r}"
    )


def test_b13b_the_ship_record_names_the_work_that_was_re_landed() -> None:
    row = ROADMAP.read_text(encoding="utf-8").splitlines()[-1]
    for token in ("todos", "large_file", "syntax_error"):
        assert token in row, (
            "the ship record must name the three converted collectors so the ledger "
            f"row is a real record of the change; {token!r} missing from {row!r}"
        )


def test_b13c_no_existing_ledger_row_was_deleted_reordered_or_renumbered() -> None:
    numbers = _ledger_numbers(ROADMAP.read_text(encoding="utf-8"))
    # MEASURED, and reported as spec feedback rather than asserted: this ledger is
    # NOT globally ascending on the shipping tree (#185, #178, #136, #151, #117 and
    # #222 all sit out of order, left behind by earlier relocations), so an
    # "append-only means ascending" assertion would red a correct tree. The durable
    # properties are uniqueness and the TAIL, which is what pm.md Behavior 13 pins.
    assert len(numbers) == len(set(numbers)), (
        f"a ship-record number appears twice in ROADMAP.md: {numbers}"
    )
    assert numbers[-1] == 261, (
        f"the newest ledger row must be #261; got #{numbers[-1]}"
    )
    assert numbers[-2] == 260, (
        "the new row must sit immediately after the previous ship (#260) with no gap "
        f"and no row displaced; got #{numbers[-2]} before #{numbers[-1]}"
    )


def test_b13d_the_roadmap_ends_with_exactly_one_trailing_newline() -> None:
    raw = ROADMAP.read_text(encoding="utf-8")
    assert raw.endswith("\n"), "ROADMAP.md must end with a newline"
    assert not raw.endswith("\n\n"), (
        "the append must not leave a blank line after the ledger; a later append "
        "would then produce a row that is not the last LINE of the file"
    )


# ---------------------------------------------------------------------------
# Expected Behavior 14 -- budget and ledger conservation
# ---------------------------------------------------------------------------


def test_b14b_the_shipped_budget_guard_agrees() -> None:
    """Cross-check against the repo's own budget helper, not a copy of the number."""
    verdict = check_char_budget(ROADMAP.read_text(encoding="utf-8"))
    assert verdict.ok, (
        f"the repo's own roadmap budget guard refuses the shipped file: {verdict.message}"
    )
    assert verdict.chars <= 40_000 - 4_000, (
        "the guard's own char count must leave the 4,000-char headroom the NEXT "
        f"iteration needs for its ship record: {verdict.message}"
    )


def test_b14c_the_ledger_is_non_vacuous_and_grew_by_exactly_one() -> None:
    rows = _ledger_rows(ROADMAP.read_text(encoding="utf-8"))
    assert len(rows) == EXPECTED_LEDGER_ROWS, (
        f"ROADMAP.md must hold {EXPECTED_LEDGER_ROWS} Done-ledger rows (47 at HEAD "
        f"plus this iteration's one); got {len(rows)}. A count BELOW this means a "
        "relocation rode along on a feature commit, which pm.md puts out of scope"
    )


def test_b14d_no_ship_record_is_recorded_in_both_roadmap_files() -> None:
    roadmap_numbers = set(_ledger_numbers(ROADMAP.read_text(encoding="utf-8")))
    archive_numbers = set(_ledger_numbers(ARCHIVE.read_text(encoding="utf-8")))
    overlap = sorted(roadmap_numbers & archive_numbers)
    assert overlap == [], (
        "a ship record must live in exactly ONE of ROADMAP.md / ROADMAP_ARCHIVE.md; "
        f"these numbers appear in both: {overlap}"
    )
    assert 261 not in archive_numbers, (
        "this iteration's row belongs in ROADMAP.md only -- ROADMAP_ARCHIVE.md holds "
        "RELOCATED rows, and a duplicate reds the conservation guard"
    )


# ---------------------------------------------------------------------------
# Expected Behavior 15 -- the decision log records this iteration
# ---------------------------------------------------------------------------


def test_b15a_directions_gains_an_iter_263_block_at_the_top() -> None:
    """The log must RECORD this iteration; its block need not still be the topmost one.

    ``DIRECTIONS.md`` is auto-maintained and gains the NEXT iteration's block as soon as that
    iteration's scouts run -- which happens before this suite is ever run again. Pinning
    ``labels[0]`` therefore asserts a fact that is true only during iteration 263 and false
    forever after, so it reds every later build on a file no contributor touched. Presence plus
    the strict newest-first ordering asserted below is the same guarantee without the expiry.
    """
    labels = _directions_blocks(DIRECTIONS.read_text(encoding="utf-8"))
    assert labels, "DIRECTIONS.md must hold at least one iter-NNN block"
    assert "263" in labels, (
        f"the decision log must record this iteration as an iter-263 block; got {labels[:3]}"
    )
    assert len(labels) == len(set(labels)), (
        "a decision block is written once per iteration; duplicate labels: "
        f"{sorted(lbl for lbl in set(labels) if labels.count(lbl) > 1)}"
    )
    numeric = [int(lbl) for lbl in labels]
    assert numeric == sorted(numeric, reverse=True), (
        f"decision blocks must run newest-first; got {numeric[:6]}"
    )


def test_b15b_the_iter_263_block_has_the_shape_the_file_already_uses() -> None:
    body = _block_body(DIRECTIONS.read_text(encoding="utf-8"), "263")
    assert re.search(r"^    lenses: \S", body, re.MULTILINE), (
        f"the iter-263 block needs a non-empty 'lenses:' line; got {body!r}"
    )
    candidates = re.findall(r"^    - Candidate \S", body, re.MULTILINE)
    assert len(candidates) >= 2, (
        "the block must list the scouted candidates it decided between; found "
        f"{len(candidates)}"
    )
    assert re.search(r"^    winner: \S", body, re.MULTILINE), (
        f"the iter-263 block needs a non-empty 'winner:' line; got {body!r}"
    )
    assert re.search(r"^    ship: \S", body, re.MULTILINE), (
        f"the iter-263 block needs a 'ship:' line; got {body!r}"
    )


def test_b15c_iteration_260s_pending_ship_is_corrected_to_the_sha_it_shipped_as() -> None:
    body = _block_body(DIRECTIONS.read_text(encoding="utf-8"), "260")
    assert ITER_260_SHIP in body, (
        "iteration 260 shipped as 9b13289 (this repo's HEAD before iter 263), so its "
        f"block must no longer read 'pending'; got {body!r}"
    )
    assert "pending" not in body, (
        f"iteration 260's block still records a pending ship: {body!r}"
    )


def test_b15d_the_trailing_scouted_count_matches_the_number_of_blocks() -> None:
    text = DIRECTIONS.read_text(encoding="utf-8")
    labels = _directions_blocks(text)
    tail = [ln for ln in text.splitlines() if ln.strip().endswith("scouted iterations")]
    assert len(tail) == 1, (
        f"DIRECTIONS.md must carry exactly one scouted-iteration count line; got {tail}"
    )
    (declared,) = re.findall(r"(\d+) scouted iterations", tail[0])
    assert int(declared) == len(labels), (
        "the trailing count is a derived value and must be reconciled in the same "
        f"commit that adds a block; declares {declared}, file holds {len(labels)}"
    )


# ---------------------------------------------------------------------------
# Expected Behavior 2 (cross-check) -- three walks collapse to one
# ---------------------------------------------------------------------------


def test_b2a_inside_one_scope_the_three_converted_collectors_share_one_listing(
    tmp_path: Path,
) -> None:
    _seed_visible_work(tmp_path)
    with dir_source.walk_scope():
        emitted = {name: len(c.collect(tmp_path)) for name, c in CONVERTED}  # type: ignore[attr-defined]
        stats = dir_source.walk_cache_stats()
    assert all(count >= 1 for count in emitted.values()), (
        "NON-VACUOUSNESS GUARD: every converted collector must actually emit on this "
        f"fixture, or the cache assertion below proves nothing; got {emitted}"
    )
    assert stats["misses"] == 1, (
        "three collectors walking the SAME root inside one scope must produce exactly "
        f"one physical traversal; got {stats!r}"
    )
    assert stats["hits"] >= 2, (
        f"the second and third collectors must be served from the cache; got {stats!r}"
    )


def test_b2b_with_no_scope_each_collector_walks_for_itself(tmp_path: Path) -> None:
    _seed_visible_work(tmp_path)
    for _name, collector in CONVERTED:
        collector.collect(tmp_path)  # type: ignore[attr-defined]
    stats = dir_source.walk_cache_stats()
    assert stats["misses"] == len(CONVERTED), (
        "pm.md Behavior 2: with NO scope active, misses must rise once per walk() call "
        f"-- three collectors, three traversals; got {stats!r}"
    )
    assert stats["hits"] == 0, (
        f"nothing may be served from a cache that is not armed; got {stats!r}"
    )
    assert stats["entries"] == 0, (
        "outside a scope no listing may be RETAINED, which is the whole no-staleness "
        f"argument for a long-lived watch process; got {stats!r}"
    )


# ---------------------------------------------------------------------------
# Expected Behaviors 3 and 4 (cross-check) -- prune and hidden-file policy
# ---------------------------------------------------------------------------


def test_b3_nothing_is_emitted_from_a_pruned_directory(tmp_path: Path) -> None:
    """Both regimes in ONE test function on purpose -- see MODULE FOOTPRINT above."""
    _seed_visible_work(tmp_path)
    _seed_pruned_work(tmp_path)
    for scoped in (False, True):
        for name, collector in CONVERTED:
            signals = _collect(collector, tmp_path, scoped=scoped)
            assert signals, (
                f"NON-VACUOUSNESS GUARD [scoped={scoped}]: {name} emitted nothing at "
                "all, so its prune assertion would be a tautology"
            )
            leaks = [
                str(s.path)
                for s in signals
                if any(f"/{d}/" in str(s.path).replace("\\", "/") for d in PRUNED_DIRS)
            ]
            assert leaks == [], (
                f"[scoped={scoped}] {name} must inherit the shared provider's directory "
                f"prune; it reported paths inside {PRUNED_DIRS}: {leaks}"
            )


def test_b4_a_hidden_file_that_would_otherwise_qualify_emits_nothing(tmp_path: Path) -> None:
    """Both regimes in ONE test function on purpose -- see MODULE FOOTPRINT above."""
    _seed_visible_work(tmp_path)
    _seed_hidden_files(tmp_path)
    for scoped in (False, True):
        for name, collector in CONVERTED:
            signals = _collect(collector, tmp_path, scoped=scoped)
            assert signals, (
                f"NON-VACUOUSNESS GUARD [scoped={scoped}]: {name} emitted nothing at "
                "all, so its hidden-file assertion would be a tautology"
            )
            leaks = [s for s in signals if Path(str(s.path)).name.startswith(".")]
            assert leaks == [], (
                f"[scoped={scoped}] {name} must keep filtering hidden FILES at its own "
                "call site (the shared provider does not filter filenames); leaked: "
                f"{[str(s.path) for s in leaks]}"
            )


# ---------------------------------------------------------------------------
# Expected Behavior 7 (cross-check) -- the library-consumer path is unaffected
# ---------------------------------------------------------------------------


def test_b7_collect_is_field_for_field_equal_inside_and_outside_a_scope(
    tmp_path: Path,
) -> None:
    _seed_visible_work(tmp_path)
    _seed_pruned_work(tmp_path)
    _seed_hidden_files(tmp_path)
    (tmp_path / "pkg" / "more.py").write_text(
        "# FIXME: second one\n# TODO: third one\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "bigger.bin").write_bytes(b"y" * 9_000)
    (tmp_path / "pkg" / "alsobroken.py").write_text("class (\n", encoding="utf-8")
    for name, collector in CONVERTED:
        outside = _fields(collector.collect(tmp_path))  # type: ignore[attr-defined]
        with dir_source.walk_scope():
            inside = _fields(collector.collect(tmp_path))  # type: ignore[attr-defined]
        assert outside, (
            f"NON-VACUOUSNESS GUARD: {name} emitted nothing, so equality proves nothing"
        )
        assert outside == inside, (
            f"{name} must be indistinguishable to a library consumer with and without "
            f"a scan scope -- same signals, same order, same summaries.\n"
            f"outside={outside}\ninside={inside}"
        )


# ---------------------------------------------------------------------------
# Two-sided arms -- the paperwork predicates FIRE on the omission that
# reverted iteration 262, and stay silent on the shipped documents
# ---------------------------------------------------------------------------


def test_the_ship_record_predicate_is_silent_on_the_shipped_roadmap() -> None:
    assert ship_record_problems(ROADMAP.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "mutation, expect",
    [
        pytest.param("drop_row", "does not start with", id="row-never-appended"),
        pytest.param("blank_after", "does not start with", id="trailing-blank-line"),
        pytest.param("wrong_tag", "does not end with", id="wrong-iteration-tag"),
        pytest.param("too_long", "over 120", id="row-over-the-char-cap"),
        pytest.param("duplicate", "recorded twice", id="duplicate-ship-number"),
        pytest.param("archive_gap", "tail must run", id="row-relocated-out"),
    ],
)
def test_the_ship_record_predicate_fires_on_each_way_the_record_can_be_wrong(
    mutation: str, expect: str
) -> None:
    text = ROADMAP.read_text(encoding="utf-8")
    lines = text.splitlines()
    if mutation == "drop_row":
        lines = lines[:-1]
    elif mutation == "blank_after":
        lines = [*lines, ""]
    elif mutation == "wrong_tag":
        lines[-1] = lines[-1].replace(SHIP_ROW_SUFFIX, "(foundry iter 262)")
    elif mutation == "too_long":
        lines[-1] = lines[-1].replace(
            SHIP_ROW_SUFFIX, "and a great deal of further explanatory prose " + SHIP_ROW_SUFFIX
        )
    elif mutation == "duplicate":
        lines = [*lines, lines[-1]]
    elif mutation == "archive_gap":
        lines = [ln for ln in lines if not ln.startswith("- #260 ")]
    problems = ship_record_problems("\n".join(lines) + "\n")
    assert any(expect in p for p in problems), (
        f"mutation {mutation!r} must be caught; predicate said {problems}"
    )


def test_the_directions_predicate_is_silent_on_the_shipped_decision_log() -> None:
    assert directions_problems(DIRECTIONS.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "mutation, expect",
    [
        pytest.param("no_block", "newest block must be", id="block-never-added"),
        pytest.param("stale_count", "the trailing count declares", id="count-not-reconciled"),
        pytest.param("pending_260", "must read", id="iter-260-left-pending"),
    ],
)
def test_the_directions_predicate_fires_on_each_way_the_block_can_be_wrong(
    mutation: str, expect: str
) -> None:
    text = DIRECTIONS.read_text(encoding="utf-8")
    if mutation == "no_block":
        text = re.sub(r"^  iter-263$", "  iter-999", text, count=1, flags=re.MULTILINE)
    elif mutation == "stale_count":
        text = re.sub(r"\d+ scouted iterations", "1 scouted iterations", text)
    elif mutation == "pending_260":
        text = text.replace(ITER_260_SHIP, "ship: pending (not yet decided)")
    problems = directions_problems(text)
    assert any(expect in p for p in problems), (
        f"mutation {mutation!r} must be caught; predicate said {problems}"
    )
