"""Black-box behavior tests for factory iteration 269 --- the self-published test
floor rises one step at every carrier that claims it, under the two-sided census.

MODULE NAME, derived from the repo and never from the state-dir counter. This is
state-dir iteration 269, while ``git ls-files tests`` tops out at
``test_iter244_behavior.py``, so the free name is ``iter245``. Proved free before
writing: ``git cat-file -e HEAD:tests/test_iter245_behavior.py`` returned
``fatal: path ... does not exist in 'HEAD'``.

WHAT THIS ITERATION CLAIMS (restated from the spec so this file stands alone):

* The README intro is the ONE source of truth for the published suite-size floor
  (``published_floor()`` derives it from the intro's bolded claim), and five other
  tracked files hard-code the same comma-grouped token BY DESIGN so that the census
  has something to catch. A bump must re-key every CLAIM in one commit.
* A line carrying an ASCII arrow or ``factory iter`` is bump HISTORY, not a claim:
  it must go on naming an old floor forever. Re-keying one of those would erase the
  chronicle; missing a claim would publish a floor the tree disagrees with.
* The bump is prophylaxis with a measured detonation date. At the pre-bump floor the
  guard had ONE test of headroom, so the next behavior oracle of any size would have
  reverted an unrelated feature -- the failure that cost iterations 261-263.

WHY THIS MODULE HOLDS NO COMMA-GROUPED FLOOR TOKEN. Every token it needs is DERIVED
through ``guard.floor_token`` instead of spelled out. That is not style: the live
census fails on any undeclared tracked file that CLAIMS the live floor, and a test
module quoting the token in prose would become exactly that -- an undeclared
carrier, and the first one nothing checks. ``test_readme_and_ci_contract`` protects
itself the same way with a deliberately synthetic ``7,700``. AMENDED at factory iter
281: the census now also reads the PEP 515 underscore spelling, so the
``EXPECTED_FLOOR`` pin below made this module a carrier in fact, and it is a DECLARED
one from that iteration on. The rule above is unchanged and still load-bearing --
being declared is what makes a pin safe, not being unreadable.

Black-box contract honored: this module drives the published documents and the
census helpers that already ship under ``tests/``. It reads no file under ``src/``,
no engineer or reviewer note, and no content diff.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests import test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
ROADMAP = REPO / "ROADMAP.md"
ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"

#: The floor this iteration raises the published claim TO, as a bare int. Bare on
#: purpose -- see the module docstring on why no comma-grouped token appears here.
EXPECTED_FLOOR = 5_800

#: The floor it is raised FROM.
SUPERSEDED_FLOOR = 5_700

#: The widest live count that still rounds to ``EXPECTED_FLOOR`` under BOTH
#: invariants ``test_iter238`` pins (``live // 100 * 100`` and ``(live + 1) // 100
#: * 100``). The upper bound is 5898, not 5899, because the second invariant is
#: what makes the wall one test narrower than it looks.
FLOOR_WINDOW = (EXPECTED_FLOOR, EXPECTED_FLOOR + 98)

#: This iteration's ledger row id and the tag its shipping commit subject must
#: carry. The tag doubles as the history marker that keeps the row out of the
#: claim census.
LEDGER_ID = "#264"
ITERATION_TAG = "(foundry iter 269)"

#: Lines that RECORD a superseded floor and must survive the bump byte-identical.
HISTORY_LINES: tuple[tuple[str, int], ...] = (
    ("ROADMAP.md", 105),
    ("ROADMAP.md", 106),
    ("tests/test_iter143_behavior.py", 26),
    ("tests/test_iter143_behavior.py", 27),
    ("tests/test_iter171_behavior.py", 41),
)

_LIVE_COUNT: list[int] = []


def _live_count() -> int:
    """One real collection per module run, memoized -- collection is the long pole."""
    if not _LIVE_COUNT:
        _LIVE_COUNT.append(guard.collect_live_test_count())
    return _LIVE_COUNT[0]


def _new_token() -> str:
    return guard.floor_token(EXPECTED_FLOOR)


def _old_token() -> str:
    return guard.floor_token(SUPERSEDED_FLOOR)


def _intro(text: str) -> str:
    """The human-owned block of a README text: everything above the marker."""
    at = text.find(guard.MARKER)
    assert at != -1, "the README lost its PORTFOLIO INTRO marker"
    return text[:at]


def _git(*args: str) -> str:
    proc = subprocess.run(
        ("git", *args),
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr}"
    return proc.stdout


def _head_text(rel: str) -> str:
    return _git("show", f"HEAD:{rel}")


def _ledger_rows(text: str) -> list[str]:
    """Every Done-ledger row: a top-level bullet opening with a ``#NNN`` id."""
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- #") and stripped[3:4].isdigit():
            rows.append(stripped)
    return rows


# --------------------------------------------------------------------------- b1


def test_b1_live_collection_crosses_the_wall_and_the_floor_matches_it() -> None:
    """The suite really is past the new floor, and still inside its window."""
    live = _live_count()
    low, high = FLOOR_WINDOW
    assert low <= live <= high, (
        f"live collection is {live}, outside the window [{low}, {high}] that rounds "
        f"to the published floor {EXPECTED_FLOOR}"
    )
    assert live // 100 * 100 == EXPECTED_FLOOR
    assert (live + 1) // 100 * 100 == EXPECTED_FLOOR


# --------------------------------------------------------------------------- b2


def test_b2_readme_publishes_the_new_floor_twice_and_the_old_token_is_gone() -> None:
    text = README.read_text(encoding="utf-8")
    intro = _intro(text)
    token = _new_token()
    for claim in (f"**{token}+ tests**", f"**{token}+ passing tests**"):
        assert claim in intro, f"the README intro no longer publishes {claim!r}"
    assert _old_token() not in text, (
        f"the superseded token {_old_token()!r} still occurs in README.md; the shop "
        "window must publish exactly one floor"
    )


# --------------------------------------------------------------------------- b3


def test_b3_the_intro_changed_in_nothing_but_that_one_number() -> None:
    """Round-tripping the new token back to the old reproduces the HEAD intro.

    Self-disarming on purpose: in a fresh clone AT the shipping commit, ``HEAD``
    already carries the new token, so the replace is a no-op and the two intros are
    equal outright. Both branches assert the same property -- the intro differs from
    its predecessor in the floor token and in nothing else.
    """
    worktree = _intro(README.read_text(encoding="utf-8"))
    head = _intro(_head_text("README.md"))
    if _old_token() in head:
        assert worktree.replace(_new_token(), _old_token()) == head, (
            "the README intro differs from HEAD by more than the floor token; the "
            "block above the marker is human-owned apart from three numbers"
        )
    else:
        assert worktree == head


def test_b3b_a_second_edit_to_the_intro_would_be_caught() -> None:
    """The round-trip is a real comparison, not a tautology."""
    head = _intro(_head_text("README.md"))
    tampered = _intro(README.read_text(encoding="utf-8")) + "\nsmuggled line\n"
    assert tampered.replace(_new_token(), _old_token()) != head


# --------------------------------------------------------------------------- b4


def test_b4_published_floor_derives_the_new_floor_without_editing_the_derivation() -> None:
    assert guard.published_floor() == EXPECTED_FLOOR
    assert guard.floor_token(EXPECTED_FLOOR) == "5," + "800"


# --------------------------------------------------------------------------- b5


def test_b5a_the_tracked_tree_has_no_floor_disagreement() -> None:
    sources = guard.tracked_text_sources()
    problems = guard.published_floor_disagreements(
        sources, EXPECTED_FLOOR, guard.PUBLISHED_FLOOR_CARRIERS
    )
    assert problems == [], "floor census disagreements: " + "; ".join(problems)


def test_b5b_the_declared_carrier_set_names_all_eight_pinning_files() -> None:
    """Grown from six to eight at factory iter 281, when the census learned to see
    the PEP 515 underscore spelling and the two modules pinning the floor that way
    stopped being invisible to it."""
    assert guard.PUBLISHED_FLOOR_CARRIERS == (
        "README.md",
        "tests/test_iter143_behavior.py",
        "tests/test_iter171_behavior.py",
        "tests/test_iter204_behavior.py",
        "tests/test_iter234_behavior.py",
        "tests/test_iter237_behavior.py",
        "tests/test_iter238_behavior.py",
        "tests/test_iter245_behavior.py",
    )


def test_b5c_this_module_pins_the_floor_only_in_the_underscore_spelling() -> None:
    """Inverted at factory iter 281: this module is now a DECLARED carrier.

    The original form asserted it claimed the floor NOWHERE, which was true only
    because the census could not see the ``EXPECTED_FLOOR`` pin at the top of this
    file. The intent that survives is the narrower one: no comma-grouped token in
    prose, so the module can still never become a carrier nothing declared.
    """
    own = Path(__file__).read_text(encoding="utf-8")
    assert _new_token() not in own, "this module spells the comma-grouped live floor"
    assert guard.floor_claim_lines(own, _new_token()) != (), (
        "the underscore pin above is invisible to the census again"
    )
    assert "tests/test_iter245_behavior.py" in guard.PUBLISHED_FLOOR_CARRIERS


# --------------------------------------------------------------------------- b6


def test_b6a_the_lock_stepped_constants_advanced_together() -> None:
    source = (REPO / "tests" / "test_iter143_behavior.py").read_text(encoding="utf-8")
    assert f"PUBLISHED_FLOOR = {EXPECTED_FLOOR}" in source
    assert f'STALE_FLOOR_TOKEN = "{_old_token()}"' in source


def test_b6b_the_source_text_pins_match_what_they_pin() -> None:
    pinner = (REPO / "tests" / "test_iter171_behavior.py").read_text(encoding="utf-8")
    for pin in (
        f"PUBLISHED_FLOOR = {EXPECTED_FLOOR}",
        f'STALE_FLOOR_TOKEN = "{_old_token()}"',
    ):
        assert pin in pinner, (
            f"tests/test_iter171_behavior.py no longer pins {pin!r}; the two sites "
            "must move in the same commit"
        )


# --------------------------------------------------------------------------- b7


def test_b7_superseded_floor_advanced_one_step() -> None:
    from tests import test_iter238_behavior as bump

    assert bump.EXPECTED_FLOOR == EXPECTED_FLOOR
    assert bump.SUPERSEDED_FLOOR == SUPERSEDED_FLOOR


# --------------------------------------------------------------------------- b8


@pytest.mark.parametrize(("rel", "number"), HISTORY_LINES)
def test_b8_bump_history_lines_are_not_re_keyed(rel: str, number: int) -> None:
    """A history line must survive the bump verbatim, wherever it now sits.

    Compared by CONTENT rather than by position: appending a ledger row must not be
    able to break this test, and a line that moved is still a line that survived.
    """
    head_lines = _head_text(rel).splitlines()
    assert len(head_lines) >= number, f"{rel} has no line {number} at HEAD"
    expected = head_lines[number - 1]
    assert any(marker in expected for marker in guard.FLOOR_HISTORY_MARKERS), (
        f"{rel}:{number} is not a history line, so this fixture is wrong"
    )
    worktree = (REPO / rel).read_text(encoding="utf-8").splitlines()
    assert expected in worktree, (
        f"the history line {rel}:{number} was re-keyed or deleted; it reads "
        f"{expected!r} at HEAD and no line matches it in the worktree"
    )


def test_b8b_the_history_census_is_unchanged_in_both_files() -> None:
    """No history line was added or lost in the two chronicles the bump touches."""
    for rel in ("tests/test_iter143_behavior.py", "tests/test_iter171_behavior.py"):
        head = _head_text(rel).splitlines()
        live = (REPO / rel).read_text(encoding="utf-8").splitlines()
        token = _old_token()
        head_history = [ln for ln in head if token in ln and guard.floor_claim_lines(ln, token) == ()]
        live_history = [ln for ln in live if token in ln and guard.floor_claim_lines(ln, token) == ()]
        assert live_history == head_history, f"{rel}: the bump chronicle changed"


# --------------------------------------------------------------------------- b9


def test_b9a_the_roadmap_records_the_bump_as_history_never_as_a_claim() -> None:
    roadmap = ROADMAP.read_text(encoding="utf-8")
    token = _new_token()
    assert token in roadmap, "the roadmap does not record the bump at all"
    assert guard.floor_claim_lines(roadmap, token) == (), (
        "the roadmap CLAIMS the new floor on a line carrying no history marker, "
        "which would make it an undeclared carrier"
    )


def test_b9b_the_roadmap_stays_absent_from_the_carrier_set() -> None:
    assert "ROADMAP.md" not in guard.PUBLISHED_FLOOR_CARRIERS


# -------------------------------------------------------------------------- b10


def test_b10a_a_live_count_below_the_published_floor_is_reported() -> None:
    intro = _intro(README.read_text(encoding="utf-8"))
    assert guard.suite_size_problems(intro, EXPECTED_FLOOR - 1) != []


def test_b10b_a_floor_a_full_slack_stale_is_reported() -> None:
    intro = _intro(README.read_text(encoding="utf-8"))
    assert guard.suite_size_problems(intro, EXPECTED_FLOOR + guard.SUITE_SIZE_SLACK) != []


def test_b10c_the_real_live_count_yields_no_problem() -> None:
    intro = _intro(README.read_text(encoding="utf-8"))
    problems = guard.suite_size_problems(intro, _live_count())
    assert problems == [], "; ".join(problems)


def test_b10d_the_staleness_knob_is_unchanged() -> None:
    assert guard.SUITE_SIZE_SLACK == 500


# -------------------------------------------------------------------------- b11


def test_b11a_the_ledger_row_is_appended_once_and_carries_the_arrow_and_the_tag() -> None:
    rows = [r for r in _ledger_rows(ROADMAP.read_text(encoding="utf-8")) if r.startswith(f"- {LEDGER_ID} ")]
    assert len(rows) == 1, f"expected exactly one {LEDGER_ID} ledger row, found {len(rows)}"
    row = rows[0]
    assert "->" in row, "the row must carry the ASCII arrow that makes it history"
    assert ITERATION_TAG in row, f"the row must cite {ITERATION_TAG}"


def test_b11b_the_ship_record_is_not_also_in_the_archive() -> None:
    archive = ARCHIVE.read_text(encoding="utf-8")
    assert f"- {LEDGER_ID} " not in archive
    assert ITERATION_TAG not in archive


def test_b11c_the_ledger_grew_by_exactly_one_row() -> None:
    head_rows = len(_ledger_rows(_head_text("ROADMAP.md")))
    live_rows = len(_ledger_rows(ROADMAP.read_text(encoding="utf-8")))
    if live_rows == head_rows:
        pytest.skip("running at the shipping commit: the row is already in HEAD")
    assert live_rows == head_rows + 1, (
        f"the ledger went {head_rows} -> {live_rows}; one iteration is one row"
    )


def test_b11d_no_ledger_id_is_used_twice() -> None:
    ids = [r.split()[1] for r in _ledger_rows(ROADMAP.read_text(encoding="utf-8"))]
    assert len(ids) == len(set(ids)), "duplicate ledger ids in ROADMAP.md"


# -------------------------------------------------------------------------- b12


def test_b12_the_roadmap_stays_inside_its_budget_as_its_owners_measure_it() -> None:
    """The row fits, judged by the two modules that already own this budget.

    Delegated on purpose, and the delegation is the interesting part. Spelling a
    ceiling here would make this module a THIRD opinion on one document's size, which
    is precisely what ``tests/test_iter172_behavior.py`` exists to stop: it censuses
    every tracked module that applies ``len`` to the budgeted document inside an
    assert and reds on any bound that is not the owner's. An early draft of this test
    asserted ``<= 36_000`` directly and reddened that census at line 365 -- a real
    catch, not a nuisance, since a re-typed ceiling is a number that can rot apart
    from the one enforced. So the char count comes from the owner's verdict object and
    the working ceiling is DERIVED from the constants that define it.
    """
    from tests import test_iter214_behavior as headroom_owner
    from tests import test_roadmap_size_budget as budget_owner

    verdict = budget_owner.check_char_budget(ROADMAP.read_text(encoding="utf-8"))
    assert verdict.ok, verdict.message
    measured = verdict.chars
    working_ceiling = headroom_owner.CHAR_LIMIT - headroom_owner.MIN_HEADROOM
    assert measured <= working_ceiling, (
        f"ROADMAP.md is {measured} chars, past the working ceiling "
        f"{working_ceiling} (= CHAR_LIMIT - MIN_HEADROOM). Relocate at least what "
        "this iteration added into ROADMAP_ARCHIVE.md in the SAME commit."
    )


def test_b12b_this_module_holds_no_size_opinion_of_its_own() -> None:
    """The census that caught the first draft must find nothing here now."""
    from tests import test_iter172_behavior as census

    own = Path(__file__).read_text(encoding="utf-8")
    assert census.located_roadmap_size_bounds(own) == (), (
        "this module asserts a size bound on the budgeted document; the sanctioned "
        "numbers live in tests/test_roadmap_size_budget.py"
    )


# -------------------------------------------------------------------------- b13


def test_b13_this_iteration_touches_nothing_under_src() -> None:
    """A numbers-and-prose bump, measured on the shipping file list.

    Keyed on the iteration tag rather than on ``HEAD~1``, so it stays true in every
    later clone: before the commit exists it reads the dirty worktree, after it
    exists it reads that commit's own name-only file list. No content diff is read.
    """
    subjects = _git("log", "--format=%H %s", "-n", "200").splitlines()
    sha = next((ln.split(" ", 1)[0] for ln in subjects if ITERATION_TAG in ln), None)
    if sha is None:
        names = [
            line[3:].strip()
            for line in _git("status", "--porcelain").splitlines()
            if line.strip()
        ]
        assert names, "no shipping commit and a clean tree: nothing to measure"
    else:
        names = _git("show", "--name-only", "--format=", sha).split()
    offenders = [n for n in names if n.startswith("src/") or n in {"pyproject.toml", "uv.lock"}]
    assert offenders == [], f"this iteration must touch no source or dependency file: {offenders}"
