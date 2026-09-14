"""Black-box behavior tests for state-dir iteration 172: the README suite-size
ratchet gains a HEADROOM GAUGE (``headroom_report`` plus ``make readme-headroom``),
so the only signal that the published floor has rotted stops being a RED PUBLIC BUILD.

File naming: the state-dir iteration is 172, but this repo names behavior modules by
the FACTORY iteration number, which is 176 here. ``tests/test_iter172_behavior.py`` is
already a SHIPPED module (``a95c513``, factory iter 172, the ROADMAP size-budget
census) and must not be reused; ``tests/test_iter109_behavior.py`` records the same
state-dir-versus-factory offset for its own name.

Why this exists.  ``suite_size_problems`` is a ratchet with no gauge: on a green run
it prints NOTHING, so a portfolio repo learns its headline "N,N00+ tests" claim went
stale only when CI reds in public.  The gauge renders the SAME derivation as one
machine-readable line, composing the guard's own seams (``SUITE_CLAIM``,
``_published_floor_for``, ``SUITE_SIZE_SLACK``) rather than re-deriving them, so the
two can never disagree on the branch the spec pins.

Every figure asserted below was MEASURED against the guard's own code this stage, not
restated from a document: ``red_at`` is ``published + slack`` (the smallest FAILING
live count), so ``headroom`` is one LESS than the distance to it -- 4,299 is the last
green live count and 4,300 the first red one.

Coverage (numbered to match the iteration spec's Expected Behaviors):

1. ``headroom_report(intro_text, live_count) -> str`` exists and is PURE -- proven by
   making ``subprocess.run`` and ``Path.read_text`` raise, and by determinism.
2. Exactly one line, no newline, fixed field order -- nine fields since factory
   iter 301 added ``binding_at``/``binding_headroom`` (roadmap row #271).
3. Pre-bump sample: exact full-string equality.
4. Post-bump sample: ``published=4200``, ``red_at=4700``, ``headroom=496``.
5. Single-sourced: ``floor=`` equals ``_published_floor_for`` and ``slack=`` equals
   ``SUITE_SIZE_SLACK`` for four live counts; ``replacement=`` is that floor with a
   thousands comma and a ``+``; never an exact live count, never the banned
   ``tests-`` badge shape.
6. Gauge and cliff agree on BOTH sides of the boundary (4,299 green / headroom=0 and
   4,300 red / headroom=-1, negative and never clamped).
7. The BINDING claim is the one reported: the SMALLEST published floor, with the
   reason stated in the helper's docstring.
8. Fails loudly on an intro with no claim -- ``AssertionError`` naming the missing
   README claim, never a fabricated ``published=``.
9. ``make readme-headroom`` is declared phony and its recipe names BOTH helpers
   (asserted by READING the Makefile -- this test never executes ``make`` and runs no
   collection subprocess).
Factory iter 301 (roadmap row #271) EXTENDED the arms above rather than adding any
test function, because the collected-item budget was exhausted (live 5,998 == the
published floor + 98 cap): ``binding_at``/``binding_headroom`` join items 2-6, the
named ``SUITE_ROUNDING_WINDOW`` seam joins item 10, and items 7 and 9 gained the
retraction census for the three prose sites that used to promise this gauge could
never disagree with the build.

10. DEFERRAL RECORD -- see the class docstring below.  The spec's behavior 10 (bump
    the two intro strings ``3,800+`` -> ``4,200+``) is NOT delivered in this tree; it
    is blocked by an authority conflict between two earlier iterations' oracles.  This
    module therefore pins only the invariants that hold either way and that the
    acceptance criteria name: the slack constant is UNCHANGED, and every intro suite
    claim is a rounded ``+`` FLOOR rather than an exact count.
"""

import inspect
import pathlib
import re

import pytest

from tests import test_readme_and_ci_contract as contract
from tests.test_readme_and_ci_contract import (
    SUITE_CLAIM,
    SUITE_ROUNDING_WINDOW,
    SUITE_SIZE_SLACK,
    _intro,
    _published_floor_for,
    headroom_report,
    suite_size_problems,
)

# The measured state of the repo BEFORE this iteration's (deferred) bump.
PRE_BUMP_INTRO = "the demo and all **3,800+ tests** run with no network"
POST_BUMP_INTRO = "a portfolio codebase -- **4,200+ passing tests** (green in CI)"
LIVE_AT_SPEC_TIME = 4203

# Field names in their contractual order (behavior 2).
FIELD_ORDER = (
    "live",
    "published",
    "floor",
    "slack",
    "red_at",
    "headroom",
    # Added factory iter 301 (row #271). The two BINDING-wall fields sit between the
    # slack figures they qualify and the trailing ``replacement`` token, so a reader
    # meets the honest countdown next to the generous one rather than after the
    # paste-ready string.
    "binding_at",
    "binding_headroom",
    "replacement",
)


def _fields(line: str) -> dict[str, str]:
    """Split one gauge line into its ``key=value`` pairs, preserving order."""
    head, _, rest = line.partition(" ")
    assert head == "readme-suite-size:", head
    return dict(
        pair.split("=", 1) for pair in rest.split(" ") if "=" in pair
    )


# --------------------------------------------------------------------------
# 1. The helper exists and is PURE.
# --------------------------------------------------------------------------


def test_b1_helper_is_exposed_with_the_specced_two_argument_signature() -> None:
    assert callable(headroom_report)
    params = list(inspect.signature(headroom_report).parameters)
    assert params == ["intro_text", "live_count"], params


def test_b1_helper_is_pure_no_subprocess_and_no_file_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove purity by DENYING the two impure capabilities, not by scanning source.

    A substring scan of ``inspect.getsource`` is fail-closed here: the helper's own
    docstring advertises "no subprocess, no file read, no network", so a naive scan
    reports impure on provably clean code.  Making the capabilities raise decides it.
    """

    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("headroom_report must not shell out or read files")

    monkeypatch.setattr(contract.subprocess, "run", boom)
    monkeypatch.setattr(pathlib.Path, "read_text", boom)

    line = headroom_report(PRE_BUMP_INTRO, LIVE_AT_SPEC_TIME)
    assert line.startswith("readme-suite-size: ")


def test_b1_helper_is_deterministic_across_repeated_identical_calls() -> None:
    first = headroom_report(PRE_BUMP_INTRO, LIVE_AT_SPEC_TIME)
    second = headroom_report(PRE_BUMP_INTRO, LIVE_AT_SPEC_TIME)
    assert first == second


# --------------------------------------------------------------------------
# 2. Exactly one line, fixed field order.
# --------------------------------------------------------------------------


def test_b2_exactly_one_line_with_every_field_in_contractual_order() -> None:
    """The count is pinned to ``FIELD_ORDER`` AND to a literal, so neither drifts alone.

    Renamed at factory iter 301: the name said ``seven`` and the contract now carries
    nine fields, so the name itself was the kind of stale count this repo keeps
    guarding against.
    """
    line = headroom_report(PRE_BUMP_INTRO, LIVE_AT_SPEC_TIME)
    assert "\n" not in line
    assert line.startswith("readme-suite-size:")

    keys = [pair.split("=", 1)[0] for pair in line.split(" ")[1:]]
    assert tuple(keys) == FIELD_ORDER, keys
    assert len(keys) == len(FIELD_ORDER) == 9, keys

    # The two fields added at factory iter 301 are INSERTED, not appended: a reader
    # meets the honest countdown before the paste-ready replacement token.
    legacy = (
        "live",
        "published",
        "floor",
        "slack",
        "red_at",
        "headroom",
        "replacement",
    )
    assert tuple(key for key in keys if key in legacy) == legacy, keys
    assert keys[keys.index("headroom") + 1 : keys.index("replacement")] == [
        "binding_at",
        "binding_headroom",
    ], keys


# --------------------------------------------------------------------------
# 3 + 4. The two samples the spec pins character for character.
# --------------------------------------------------------------------------


def test_b3_pre_bump_sample_is_the_exact_specced_string() -> None:
    line = headroom_report(PRE_BUMP_INTRO, LIVE_AT_SPEC_TIME)
    assert line == (
        "readme-suite-size: live=4203 published=3800 floor=4200 slack=500 "
        "red_at=4300 headroom=96 binding_at=3899 binding_headroom=-305 "
        'replacement="4,200+"'
    )

    # Deleting the two NEW fields must reproduce the pre-301 line byte for byte, which
    # is how the seven legacy fields are pinned to their old VALUES and not just their
    # names -- an extension may not quietly re-derive one of them.
    assert " ".join(
        part
        for part in line.split(" ")
        if not part.startswith(("binding_at=", "binding_headroom="))
    ) == (
        "readme-suite-size: live=4203 published=3800 floor=4200 slack=500 "
        'red_at=4300 headroom=96 replacement="4,200+"'
    )


def test_b4_post_bump_sample_moves_published_red_at_and_headroom() -> None:
    fields = _fields(headroom_report(POST_BUMP_INTRO, LIVE_AT_SPEC_TIME))
    assert fields["published"] == "4200"
    assert fields["red_at"] == "4700"
    assert fields["headroom"] == "496"
    # Same live count as the pre-bump sample, so the binding pair moves with the
    # CLAIM alone: 4,200 + 98 is the last green count, hence 4,299 is the first red.
    assert fields["binding_at"] == "4299"
    assert fields["binding_headroom"] == "95"


# --------------------------------------------------------------------------
# 5. Single-sourced, never re-derived.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("live", "expected_floor"),
    [(4203, 4200), (4300, 4300), (4999, 4900), (9999, 9900)],
)
def test_b5_floor_and_slack_fields_come_from_the_guards_own_seams(
    live: int, expected_floor: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    fields = _fields(headroom_report(PRE_BUMP_INTRO, live))

    # Pinned to the seam AND to the independently measured value, so a change to
    # either the helper or the seam is caught rather than cancelling out.
    assert fields["floor"] == str(_published_floor_for(live))
    assert fields["floor"] == str(expected_floor)
    assert fields["slack"] == str(SUITE_SIZE_SLACK)
    assert fields["live"] == str(live)

    # The BINDING wall is the smaller of the two walls standing on the same claim,
    # and its countdown is never clamped -- every live count parametrized here sits
    # past the rounding window, so all four report a NEGATIVE binding_headroom while
    # the slack-only ``headroom`` still reads comfortable at 4,203.
    published = min(
        int(match.group(1).replace(",", ""))
        for match in SUITE_CLAIM.finditer(PRE_BUMP_INTRO)
    )
    expected_binding_at = min(
        published + SUITE_SIZE_SLACK, published + SUITE_ROUNDING_WINDOW + 1
    )
    assert fields["binding_at"] == str(expected_binding_at)
    assert fields["binding_headroom"] == str(expected_binding_at - 1 - live)
    assert int(fields["binding_headroom"]) < 0

    # Both seams are read as module globals at CALL time, proven by patching each in
    # turn: an implementation that inlined 500 or 98 passes every other arm above and
    # fails here, which is the whole reason ``min`` is load-bearing rather than decor.
    monkeypatch.setattr(contract, "SUITE_SIZE_SLACK", 10)
    slack_bound = _fields(headroom_report(PRE_BUMP_INTRO, LIVE_AT_SPEC_TIME))
    assert slack_bound["slack"] == "10"
    assert slack_bound["binding_at"] == "3810"

    monkeypatch.setattr(contract, "SUITE_SIZE_SLACK", SUITE_SIZE_SLACK)
    monkeypatch.setattr(contract, "SUITE_ROUNDING_WINDOW", 8)
    rounding_bound = _fields(headroom_report(PRE_BUMP_INTRO, LIVE_AT_SPEC_TIME))
    assert rounding_bound["slack"] == str(SUITE_SIZE_SLACK)
    assert rounding_bound["binding_at"] == "3809"


@pytest.mark.parametrize(
    ("live", "expected_replacement"),
    [
        (4203, '"4,200+"'),
        (4300, '"4,300+"'),
        (4999, '"4,900+"'),
        (9999, '"9,900+"'),
    ],
)
def test_b5_replacement_is_the_floor_with_a_comma_and_a_plus(
    live: int, expected_replacement: str
) -> None:
    line = headroom_report(PRE_BUMP_INTRO, live)
    assert _fields(line)["replacement"] == expected_replacement

    # Never an exact live count, and never the shields badge shape the operator
    # banned (a hardcoded ``tests-NNNN-passing`` goes stale on the next commit).
    assert str(live) not in expected_replacement
    assert "tests-" not in line


# --------------------------------------------------------------------------
# 6. The gauge and the cliff agree, on BOTH sides of the boundary.
# --------------------------------------------------------------------------


def test_b6_last_green_live_count_reports_zero_headroom_and_no_problems() -> None:
    assert _fields(headroom_report(PRE_BUMP_INTRO, 4299))["headroom"] == "0"
    assert suite_size_problems(PRE_BUMP_INTRO, 4299) == []

    # The BINDING wall has its own cliff, 401 tests earlier: 3,898 is the last live
    # count at which both of ``test_iter250_behavior.py::test_b2``'s rounding clauses
    # still hold for a published floor of 3,800. Pure arithmetic over literals, so
    # this arm cannot pass by reading a file that happens to agree.
    assert _fields(headroom_report(PRE_BUMP_INTRO, 3898))["binding_headroom"] == "0"
    assert 3898 // 100 * 100 == 3800
    assert (3898 + 1) // 100 * 100 == 3800


def test_b6_first_red_live_count_reports_negative_one_and_a_real_problem() -> None:
    fields = _fields(headroom_report(PRE_BUMP_INTRO, 4300))
    assert fields["headroom"] == "-1"
    assert int(fields["headroom"]) < 0
    assert suite_size_problems(PRE_BUMP_INTRO, 4300) != []

    # One test past the binding cliff the gauge reads -1 while the SLACK guard is
    # still silent -- the exact disagreement that let a reader trust ``headroom`` and
    # size an oracle 401 tests too large.
    binding = _fields(headroom_report(PRE_BUMP_INTRO, 3899))
    assert binding["binding_headroom"] == "-1"
    assert binding["headroom"] == "400"
    assert suite_size_problems(PRE_BUMP_INTRO, 3899) == []
    assert 3899 // 100 * 100 == 3800
    assert (3899 + 1) // 100 * 100 == 3900


# --------------------------------------------------------------------------
# 7. The BINDING claim is the one reported.
# --------------------------------------------------------------------------


def test_b7_two_disagreeing_claims_report_the_smallest_published_floor() -> None:
    """The smallest floor rots FIRST, so reporting any other understates the risk."""
    both = "**3,800+ tests** ... **4,200+ passing tests**"
    fields = _fields(headroom_report(both, LIVE_AT_SPEC_TIME))
    assert fields["published"] == "3800"
    assert fields["red_at"] == "4300"
    assert fields["headroom"] == "96"

    # Order must not matter: the binding claim is the smallest, not the first seen.
    reversed_intro = "**4,200+ passing tests** ... **3,800+ tests**"
    assert _fields(headroom_report(reversed_intro, LIVE_AT_SPEC_TIME))[
        "published"
    ] == "3800"


def test_b7_docstring_states_why_the_smallest_floor_is_the_binding_one() -> None:
    # cleandoc: Python 3.13 strips the common leading docstring indent at compile
    # time and 3.12 does not, so never assert on raw docstring indentation.
    doc = inspect.cleandoc(headroom_report.__doc__ or "")
    assert "smallest" in doc.lower()
    assert "independently" in doc.lower()

    # It used to promise it "cannot drift away from the verdict it reports on", which
    # was true of the slack rule and FALSE of the build, because the tighter rounding
    # window lives in a module this helper never reads. The retraction must name both
    # walls and the oracle that owns the other one.
    lowered = doc.lower()
    assert "cannot drift away from the verdict" not in lowered
    assert "slack" in lowered
    assert "rounding" in lowered
    assert "binding" in lowered
    assert "tests/test_iter250_behavior.py" in doc


# --------------------------------------------------------------------------
# 8. Fails loudly, never fabricates.
# --------------------------------------------------------------------------


def test_b8_an_intro_with_no_bolded_claim_raises_naming_the_missing_claim() -> None:
    with pytest.raises(AssertionError) as excinfo:
        headroom_report("an intro that never mentions the suite size", 4203)

    message = str(excinfo.value)
    assert "no bolded suite-size claim" in message
    assert "README" in message
    # It must not have invented a published floor on the way out.
    assert "published=" not in message


# --------------------------------------------------------------------------
# 9. Exposed as a target, pinned to its helpers (Makefile READ, never executed).
# --------------------------------------------------------------------------


def test_b9_makefile_declares_readme_headroom_phony_and_names_both_helpers() -> None:
    makefile = (pathlib.Path(__file__).resolve().parent.parent / "Makefile").read_text(
        encoding="utf-8"
    )

    phony = [line for line in makefile.splitlines() if line.startswith(".PHONY:")]
    assert phony, "Makefile lost its .PHONY declaration"
    assert any("readme-headroom" in line for line in phony), phony

    recipe = re.search(
        r"^readme-headroom:\n((?:\t.*\n)+)", makefile, flags=re.MULTILINE
    )
    assert recipe, "no readme-headroom target with a recipe in the Makefile"
    body = recipe.group(1)
    assert "headroom_report" in body, body
    assert "collect_live_test_count" in body, body

    # The comment block a reader hits before running the target must not promise that
    # the gauge and the verdict can never disagree: they can, and did by 401 tests.
    header = re.search(r"((?:^#.*\n)+)readme-headroom:\n", makefile, flags=re.MULTILINE)
    assert header, "readme-headroom lost its explanatory comment block"
    block = header.group(1)
    assert "the gauge and the verdict can never disagree" not in block, block
    assert "suite_size_problems" in block, block
    assert "slack" in block, block
    assert "98" in block, block
    assert "tests/test_iter250_behavior.py" in block, block
    assert "binding_headroom" in block, block


# --------------------------------------------------------------------------
# 10. DEFERRAL RECORD -- invariants that hold whether or not the bump lands.
# --------------------------------------------------------------------------


def test_b10_slack_is_unchanged_because_the_floor_moves_not_the_tolerance() -> None:
    """Raise the floor, never the slack -- widening tolerance is buying green."""
    assert SUITE_SIZE_SLACK == 500

    # The OTHER wall is now named beside it, annotated, and documented against the
    # oracle that enforces it -- an unnamed number is what let the gauge publish 401
    # tests of room against a true 0. Adding the name may not widen the tolerance.
    assert SUITE_ROUNDING_WINDOW == 98
    source = inspect.getsource(contract)
    assert re.search(
        r"^SUITE_ROUNDING_WINDOW:\s*int\s*=\s*98\s*$", source, flags=re.MULTILINE
    ), "SUITE_ROUNDING_WINDOW must be a module-level annotated int constant"
    named = re.search(
        r"((?:^#.*\n)+)SUITE_ROUNDING_WINDOW:", source, flags=re.MULTILINE
    )
    assert named, "SUITE_ROUNDING_WINDOW ships with no explanation"
    assert "tests/test_iter250_behavior.py::test_b2" in named.group(1)
    assert "published <= live <= published + SUITE_ROUNDING_WINDOW" in named.group(1)


def test_b10_every_intro_suite_claim_is_a_rounded_floor_not_an_exact_count() -> None:
    """Survives the deferred bump: true of ``3,800+`` today and ``4,200+`` after."""
    claims = list(SUITE_CLAIM.finditer(_intro()))
    assert claims, "the README intro lost its bolded suite-size claim"
    for match in claims:
        assert match.group(2) == "+", match.group(0)
        value = int(match.group(1).replace(",", ""))
        assert value % 100 == 0, match.group(0)
        assert value == _published_floor_for(value), match.group(0)

    # The prose that TELLS a stranger how to read the gauge sits BELOW the
    # human-owned marker, and it must now send them to ``binding_headroom`` instead
    # of promising that ``headroom`` is the only advance warning they get.
    readme = (
        pathlib.Path(__file__).resolve().parent.parent / "README.md"
    ).read_text(encoding="utf-8")
    marker = readme.index("PORTFOLIO INTRO")
    bullet_at = readme.index("- `make readme-headroom`")
    assert bullet_at > marker, "the gauge bullet moved into the human-owned intro"
    bullet = re.split(r"\n(?=- |#|\n)", readme[bullet_at:])[0]
    assert "this gauge is the only advance warning you get" not in readme
    assert "binding_headroom" in bullet, bullet
    assert "reds the build" in bullet, bullet
    assert "`0`" in bullet, bullet
