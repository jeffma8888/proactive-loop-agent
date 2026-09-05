"""Black-box behavior tests for factory iteration 281 -- the published-floor raise
and the carrier census that grades it.

Feature under test: the README's rounded suite-size floor advances one step at
every tracked file that pins it, and the floor-carrier census in
``tests/test_readme_and_ci_contract.py`` (imported here as ``guard``) learns the
SECOND spelling a floor can be pinned as. Markdown publishes a comma-grouped
token, but a Python module cannot write one, so the two oracles that own the
rounding window pin the floor as a PEP 515 underscore literal. Matching only the
comma spelling made the census blind to both: it reported 6 of the 8 files a
raise must re-key, understating the obligation in the one direction that ships a
red public build, because both of the invisible files go red the moment the
README moves without them. A new pure helper publishes the spelling set, the
claim scanner accepts either, and the two invisible files become DECLARED
carriers -- proven by this same commit, which performs a raise.

THIS MODULE NEVER SPELLS THE FLOOR, in any spelling, and that is a hard
constraint rather than a style choice. The census's domain is the WHOLE tracked
tree and it has an "undeclared file claims the floor" branch, so a new module
that wrote either token would flag ITSELF the moment it landed -- and the
widening shipped here is exactly what makes the underscore spelling dangerous to
write. Every expectation below therefore DERIVES the number from
``guard.published_floor()``, which reads it out of the README. A pleasant side
effect: this module keeps passing across the next raise instead of becoming a
ninth carrier nothing declares.

ISOLATION CONTRACT (honored): written strictly against this iteration's spec
(``pm.md`` "Expected Behaviors" 1-10) plus the conventions of the existing
modules under ``tests/`` -- ``test_iter238_behavior.py`` and
``test_iter245_behavior.py`` are the shipped precedents for this style, and both
are re-keyed by this iteration, so behavior 9 checks them from the outside.
**No file under ``src/`` was read while writing this module, no engineer /
reviewer / fix note was opened, and no ``git diff`` was consulted.** Everything
asserted here was obtained from the spec, from the product's own tracked text,
or by CALLING the helpers under test.

Fully offline and deterministic: pure string work over synthetic literals plus
reads of tracked files through ``guard``'s own ``git ls-files`` domain. No
network, no API key, no sleeps, no duration assertion, and NO mtime-sensitive
precondition (iter-278 lesson: a fresh clone resets every mtime, so a
precondition that reads one passes only on this machine).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import tests.test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parent.parent

#: Any ``N,N00+`` suite-size token, so a leftover superseded floor in the intro is
#: found without this module naming either number.
ANY_FLOOR_TOKEN = re.compile(r"\b\d,\d00\+")

#: The two files that were invisible to the census: a Python module cannot write a
#: comma-grouped literal, so each pins the floor with an underscore instead.
UNDERSCORE_CARRIERS = (
    "tests/test_iter238_behavior.py",
    "tests/test_iter245_behavior.py",
)


def _intro() -> str:
    """The human-owned portfolio intro, taken at the published marker."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert guard.MARKER in text, "the README lost its human-owned intro marker"
    return text.split(guard.MARKER, 1)[0]


def _floor() -> int:
    """The live floor, derived -- never spelled -- so this module is not a carrier."""
    floor = guard.published_floor()
    assert floor % 100 == 0, f"{floor} is not a rounded hundred"
    return floor


# --------------------------------------------------------------------------- b1


def test_b1_the_readme_publishes_the_raised_floor_twice_and_nothing_else() -> None:
    """Behavior 1: both bolded sentences carry the floor, and no other token does.

    Asserted as a CENSUS of every ``N,N00+`` token in the intro rather than as
    "the superseded token is absent": a raise that re-keyed one sentence and left
    the other, or that introduced a third number, is the realistic failure, and
    an absence check on one specific old token cannot see either.
    """
    floor = _floor()
    token = guard.floor_token(floor)
    intro = _intro()
    assert f"**{token}+ tests**" in intro
    assert f"**{token}+ passing tests**" in intro
    found = set(ANY_FLOOR_TOKEN.findall(intro))
    assert found == {f"{token}+"}, (
        f"the intro publishes suite-size tokens {sorted(found)}; the raise must leave "
        f"exactly one, {token}+"
    )


# --------------------------------------------------------------------------- b2


def test_b2_the_live_count_sits_inside_the_window_the_new_floor_opens() -> None:
    """Behavior 2: the floor is TRUE, FRESH, and leaves room for one more test.

    Both rounding clauses are asserted, because the stricter one -- ``(live + 1)``
    must round to the floor too -- is what caps a live count at ``floor + 98`` and
    is the reason this iteration had to happen at all.
    """
    floor = _floor()
    live = guard.collect_live_test_count()
    assert live // 100 * 100 == floor, (
        f"live collection is {live}, which rounds to {live // 100 * 100}, not the "
        f"published floor {floor}"
    )
    assert (live + 1) // 100 * 100 == floor, (
        f"live collection is {live}: adding ONE test would round to "
        f"{(live + 1) // 100 * 100} and red the build, so the window is exhausted"
    )
    assert floor <= live <= floor + 98
    assert guard.suite_size_problems(_intro(), live) == []


# --------------------------------------------------------------------------- b3


def test_b3_floor_tokens_publishes_both_spellings_comma_grouped_first() -> None:
    """Behavior 3: the new helper's contract, at the LIVE floor.

    Checked structurally instead of against a re-spelled expectation: an
    assertion that copied the implementation's own format strings would pass for
    any pair of strings those expressions produce, including a wrong pair.
    """
    floor = _floor()
    tokens = guard.floor_tokens(floor)
    assert isinstance(tokens, tuple) and len(tokens) == 2, tokens
    comma, underscore = tokens
    assert comma == guard.floor_token(floor), "the comma spelling must come FIRST"
    assert "," in comma and "_" not in comma
    assert "_" in underscore and "," not in underscore
    assert comma.replace(",", "") == underscore.replace("_", "") == str(floor)
    assert comma != underscore


def test_b3b_floor_token_is_unchanged_and_still_single_spelling() -> None:
    """Behavior 3: existing callers keep the comma-grouped string they pass around."""
    floor = _floor()
    token = guard.floor_token(floor)
    assert isinstance(token, str)
    assert token.count(",") == 1 and "_" not in token
    assert int(token.replace(",", "")) == floor
    with pytest.raises(AssertionError, match="rounded floor"):
        guard.floor_tokens(floor + 1)


# ------------------------------------------------------------------------ b4, b5


def test_b4_a_claim_is_seen_in_either_spelling() -> None:
    """Behavior 4: the blindness this seam closes, on synthetic text.

    The negative arm matters as much as the positive one: a matcher widened to
    "any line mentioning the digits" would report every line and pass this test's
    first half while destroying the census.
    """
    comma, underscore = guard.floor_tokens(_floor())
    text = f"a\nEXPECTED_FLOOR = {underscore}\nb\n**{comma}+ tests**\n"
    assert guard.floor_claim_lines(text, comma) == (2, 4)
    assert guard.floor_claim_lines("a\nno floor pinned here\nb\n", comma) == ()


def test_b5_history_is_excluded_in_both_spellings() -> None:
    """Behavior 5: a bump RECORD is not a claim, whichever spelling it uses.

    A widened matcher that lost the exclusion would report the roadmap's own Done
    row and every docstring history chain, which is how such a census gets
    deleted rather than fixed.
    """
    comma, underscore = guard.floor_tokens(_floor())
    text = (
        f"- #267 the floor rises {comma} -> {comma} (foundry iter 281)\n"
        f"EXPECTED_FLOOR = {underscore}  # factory iter 281\n"
    )
    assert guard.floor_claim_lines(text, comma) == ()


# ------------------------------------------------------------------------ b6, b7


def test_b6_the_carrier_set_names_all_eight_pinning_files() -> None:
    """Behavior 6: eight distinct tracked paths, including the two invisible ones."""
    carriers = guard.PUBLISHED_FLOOR_CARRIERS
    assert isinstance(carriers, tuple)
    assert len(carriers) == 8, carriers
    assert len(set(carriers)) == len(carriers), "a path is declared twice"
    tracked = guard.tracked_text_sources()
    missing = [path for path in carriers if path not in tracked]
    assert missing == [], f"declared carriers that git ls-files does not know: {missing}"
    for path in UNDERSCORE_CARRIERS:
        assert path in carriers, f"{path} pins the floor but is not declared"


def test_b6b_the_two_new_carriers_pin_the_floor_only_as_an_underscore() -> None:
    """Behavior 6, on the LIVE tree: the reason the census had to widen.

    This is the assertion a synthetic dict cannot make. Each newly declared file
    really does carry the underscore spelling and really does NOT carry the comma
    one, so under the previous matcher both read as carriers that had stopped
    claiming the floor -- the census's own headline failure -- while the raise had
    in fact re-keyed them.
    """
    floor = _floor()
    comma, underscore = guard.floor_tokens(floor)
    sources = guard.tracked_text_sources()
    for path in UNDERSCORE_CARRIERS:
        text = sources[path]
        assert underscore in text, f"{path} no longer pins the floor as a literal"
        assert comma not in text, (
            f"{path} now also spells the comma token, so it no longer proves the "
            "underscore seam"
        )
        assert guard.floor_claim_lines(text, comma) != (), (
            f"{path} claims the floor but the census cannot see it"
        )


def test_b7_the_live_tracked_tree_has_no_floor_disagreement() -> None:
    """Behavior 7: the two-sided census is silent over the shipping tree.

    Its domain is ``git ls-files``, so this also proves the raise left no
    undeclared file claiming the floor in EITHER spelling -- the branch the
    widening made newly reachable.
    """
    sources = guard.tracked_text_sources()
    assert "README.md" in sources, "git ls-files returned no README -- the domain broke"
    assert guard.published_floor_disagreements(sources, _floor()) == []


def test_b7b_the_historical_verdict_line_is_not_read_as_a_claim() -> None:
    """Behavior 7 / acceptance: a quoted past verdict must stay untouched.

    ``tests/test_iter249_behavior.py`` records a verbatim failure message naming
    the SUPERSEDED floor in bare digits. It is history, not a claim, so the census
    must ignore it -- and if it ever did flag it, the exclusion rule would be what
    needs fixing, not the record.
    """
    floor = _floor()
    superseded_digits = str(floor - 100)
    text = guard.tracked_text_sources()["tests/test_iter249_behavior.py"]
    assert superseded_digits in text, (
        "the historical verdict naming the superseded floor was edited away; it is a "
        "record of a real failure and must be left alone"
    )
    assert guard.floor_claim_lines(text, guard.floor_token(floor)) == ()


# --------------------------------------------------------------------------- b8


def test_b8_the_underscore_seam_is_two_sided() -> None:
    """Behavior 8: underscore-only counts as a claim; no pin at all still fails.

    Both arms run at the LIVE floor over a synthetic mapping, so the verdict is
    about the census's logic and not about today's tree. The first arm is the bug
    this iteration fixes -- before the widening this exact input reported the path
    as a carrier that no longer claims the floor.
    """
    floor = _floor()
    comma, underscore = guard.floor_tokens(floor)
    path = UNDERSCORE_CARRIERS[0]
    assert path in guard.PUBLISHED_FLOOR_CARRIERS
    sources = {other: f"claims {comma}+\n" for other in guard.PUBLISHED_FLOOR_CARRIERS}

    sources[path] = f"EXPECTED_FLOOR = {underscore}\n"
    assert guard.published_floor_disagreements(sources, floor) == []

    sources[path] = "this file pins no floor at all\n"
    assert guard.published_floor_disagreements(sources, floor) == [
        f"{path}: declared floor carrier no longer claims the floor {comma}"
    ]


# --------------------------------------------------------------------------- b9


def test_b9_the_window_owning_oracles_advanced_with_the_readme() -> None:
    """Behavior 9: the three floor opinions in the suite are one number.

    Read through the modules' public constants, which is how a raise that
    re-keyed the README and forgot a code pin is caught.
    """
    import tests.test_iter238_behavior as window_a
    import tests.test_iter245_behavior as window_b

    floor = _floor()
    assert window_a.EXPECTED_FLOOR == floor, (
        f"test_iter238 expects {window_a.EXPECTED_FLOOR}, the README publishes {floor}"
    )
    assert window_a.SUPERSEDED_FLOOR == floor - 100
    assert window_b.EXPECTED_FLOOR == floor
    assert window_b.FLOOR_WINDOW == (floor, floor + 98), window_b.FLOOR_WINDOW


# -------------------------------------------------------------------------- b10


def test_b10_the_roadmap_records_the_raise_once_and_stays_inside_its_budget() -> None:
    """Behavior 10: exactly one new Done-ledger row for this iteration, and room left.

    The row is checked to carry the arrow as well, because a Done row that reads
    as a CLAIM instead of as history would make ``ROADMAP.md`` a ninth carrier.
    """
    roadmap = (REPO / "ROADMAP.md").read_text(encoding="utf-8")
    rows = re.findall(r"^- #(\d+) (.+)$", roadmap, flags=re.MULTILINE)
    ids = [int(number) for number, _ in rows]
    assert len(ids) == len(set(ids)), "a Done-ledger id is used twice"

    tagged = [(int(number), body) for number, body in rows if "(foundry iter 281)" in body]
    assert len(tagged) == 1, f"expected exactly one row tagged for this iteration: {tagged}"
    (row_id, body), = tagged
    assert row_id == 267, f"the new row is #{row_id}, expected #267"
    assert row_id == max(ids), "the new row is not the newest id in the ledger"
    assert "->" in body, "the Done row must read as history, never as a live claim"
    assert guard.floor_claim_lines(roadmap, guard.floor_token(_floor())) == ()
    assert "ROADMAP.md" not in guard.PUBLISHED_FLOOR_CARRIERS

    import tests.test_iter214_behavior as budget

    headroom = budget.CHAR_LIMIT - len(roadmap)
    assert headroom >= budget.MIN_HEADROOM, (
        f"ROADMAP.md is {len(roadmap)} chars, leaving {headroom} of headroom under the "
        f"{budget.CHAR_LIMIT}-char limit; the floor is {budget.MIN_HEADROOM}"
    )
