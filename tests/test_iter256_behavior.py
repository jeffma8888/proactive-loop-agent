"""Black-box behavior tests for factory iteration 288 -- the published test-floor
raise that seats the ``SPEC_ARCHIVE.md`` relocation.

Feature under test: the rounded suite-size floor the README publishes advances one
step at every tracked file that pins it, in BOTH spellings, in the same commit that
relocates ``SPEC.md``'s settled section 4.2 provider contract into a new tracked
``SPEC_ARCHIVE.md``. The two halves are one commit on purpose: the relocation's own
oracle (``tests/test_iter255_behavior.py``) has nowhere to sit until the rounding
window moves, which is why iteration 285 built the relocation correctly and was
reverted on the test count alone.

THIS MODULE NEVER SPELLS THE FLOOR, in any spelling, and that is a hard constraint
rather than a style choice. The carrier census in
``tests/test_readme_and_ci_contract.py`` (imported here as ``guard``) walks the
WHOLE tracked tree and fails on an UNDECLARED file that claims the live floor, so a
new module that wrote either token would flag ITSELF the moment it landed. Every
number below is DERIVED -- from ``guard.published_floor()`` (which reads the
README), from ``guard.floor_token`` / ``guard.floor_tokens``, or from a real
collection. Side effect: this module keeps passing across the NEXT raise instead of
becoming a ninth carrier nothing declares.

Anchors are CONTENT, never line numbers (the iter-283 lesson): every allowance
below is keyed by a substring of the line it excuses, so a file may be reflowed
without silently widening the allowance.

ISOLATION CONTRACT (honored): written strictly against this iteration's spec
(``pm.md`` "Expected Behaviors" 1-10 and its Acceptance Criteria) plus the
conventions of the existing modules under ``tests/`` --
``tests/test_iter238_behavior.py``, ``tests/test_iter245_behavior.py`` and
``tests/test_iter250_behavior.py`` are the shipped precedents for this style and
all three are re-keyed by this iteration, so they are checked from the OUTSIDE.
**No file under ``src/`` was read while writing this module, no engineer /
reviewer / fix note was opened, and no ``git diff`` was consulted.** Everything
asserted here came from the spec, from the product's own tracked text, or by
CALLING the helpers under test.

Fully offline and deterministic: pure string work over tracked text, two ``git``
blob reads and one real pytest collection through ``guard``. No network, no API
key, no sleep, no duration assertion and NO mtime-sensitive precondition (the
iter-278 lesson: a fresh clone resets every mtime, so a precondition that reads
one passes only on this machine).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import tests.test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parent.parent

#: The human-owned block's marker, matched on its stable prefix only: the shipped
#: line spells an em dash, which no test should have to reproduce.
MARKER = "PORTFOLIO INTRO"

#: Any ``N,N00+`` suite-size token, so the intro's floor digits can be neutralised
#: without this module naming either number.
ANY_FLOOR_TOKEN = re.compile(r"\b\d,\d00\+")

#: Every iteration number this work was REVERTED under. The re-land carries the old
#: number in prose, and a guard that names only the first revert goes green on the
#: second one -- which is exactly how this tree reached a fourth attempt. Widened
#: deliberately: 285 built the relocation, 286 and 287 each re-landed it and died on a
#: different unrelated defect, so ALL THREE are stale keys that must never ship.
REVERTED_ITERATIONS = ("285", "286", "287")

#: The eight declared carriers, split by the spelling each one is ABLE to write:
#: Markdown and the modules that assert the README's own text carry the
#: comma-grouped token; the two modules that own the rounding window carry the PEP
#: 515 underscore literal, because a Python integer cannot be comma-grouped.
COMMA_CARRIERS = (
    "README.md",
    "tests/test_iter143_behavior.py",
    "tests/test_iter171_behavior.py",
    "tests/test_iter204_behavior.py",
    "tests/test_iter234_behavior.py",
    "tests/test_iter237_behavior.py",
)
UNDERSCORE_CARRIERS = (
    "tests/test_iter238_behavior.py",
    "tests/test_iter245_behavior.py",
)

#: Where a SUPERSEDED floor token may still legitimately appear, keyed by path ->
#: content anchors. Behaviors 4 and 5: the live-floor family moves one step, and the
#: STALE/SUPERSEDED family moves one step behind it, so exactly these sites keep
#: naming the old number -- as a RECORD, never as a live claim.
SUPERSEDED_ALLOWANCES: dict[str, tuple[str, ...]] = {
    # The queued row that records the headroom-gauge defect measured at the old floor.
    "ROADMAP.md": ("make readme-headroom",),
    "tests/test_iter143_behavior.py": ("STALE_FLOOR_TOKEN", "is gone from"),
    "tests/test_iter171_behavior.py": ("STALE_FLOOR_TOKEN", "not in intro"),
    "tests/test_iter238_behavior.py": ("SUPERSEDED_FLOOR",),
    "tests/test_iter245_behavior.py": ("SUPERSEDED_FLOOR",),
}

#: Lockfiles are excluded from every floor census: they hold upstream hashes and
#: sizes, so a bare four-digit run is a coincidence, not a claim.
CENSUS_EXEMPT = ("uv.lock",)


def _floor() -> int:
    """The live published floor, read out of the README by the census itself."""
    return guard.published_floor()


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _head_blob(rel: str) -> str:
    """The whole ``HEAD`` blob for ``rel`` -- a blob read, never a diff read."""
    return subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _head_has(rel: str) -> bool:
    """True when ``rel`` exists in ``HEAD`` at all -- an existence probe, not a read."""
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{rel}"],
            cwd=REPO,
            capture_output=True,
        ).returncode
        == 0
    )


def _move_has_landed_in_head() -> bool:
    """True once this iteration's commit IS ``HEAD`` -- the fresh-clone and CI case.

    Four cases below want to compare the worktree AGAINST ``HEAD``: the floor rose by a
    step, the vision shrank, the intro moved, the relocated body is still findable in
    the old place. Every one of those is a BEFORE/AFTER delta, so it is answerable only
    while the change is uncommitted; ``preship`` and CI both run with the worktree AT
    the shipping commit, where the two sides are the same bytes and a delta assertion
    can never hold. That is not hypothetical -- it is what reverted the previous attempt
    at this exact tree, with every in-loop gate already green.

    Probed on the RELOCATION, deliberately, and not on the floor digits: three of the
    gated cases assert those digits, and a switch driven by the value under test goes
    vacuously green in the worktree when the edit is forgotten. ``SPEC_ARCHIVE.md``
    appearing in ``HEAD`` is a one-way, once-ever event that no later iteration undoes.
    """
    return _head_has("SPEC_ARCHIVE.md")


def _git(*args: str) -> str:
    """One git read, as text. A thin wrapper so a case reads as its git command."""
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def _tracked() -> frozenset[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return frozenset(line for line in out.splitlines() if line)


def _intro(readme: str) -> str:
    """The human-owned portfolio intro: everything strictly ABOVE the marker."""
    at = readme.index(MARKER)
    return readme[:at]


def _neutralised(intro: str) -> str:
    """``intro`` with its rounded suite-size digits replaced by a fixed placeholder.

    The ONLY sanctioned change above the marker this iteration is the floor number,
    so neutralising it on both sides turns "nothing else changed" into a byte
    comparison that a raise cannot make vacuous.
    """
    return ANY_FLOOR_TOKEN.sub("<FLOOR>+", intro)


# ---------------------------------------------------------------------------
# Behavior 1 -- the README publishes the raised floor, twice, and nothing else
# above the marker moves.
# ---------------------------------------------------------------------------


def test_b1_the_intro_publishes_the_raised_floor_in_both_sentences() -> None:
    """Behavior 1: both intro suite-size claims read the LIVE floor as a floor."""
    floor = _floor()
    token = guard.floor_token(floor)
    intro = _intro(_read("README.md"))
    claims = guard.SUITE_CLAIM.findall(intro)
    assert len(claims) == 2, f"expected exactly two intro suite-size claims, got {claims}"
    for digits, plus in claims:
        assert digits == token, f"intro claim {digits!r} is not the live floor {token!r}"
        assert plus == "+", f"intro claim {digits!r} is an exact count, not a floor"
    assert f"**{token}+ tests**" in intro
    assert f"**{token}+ passing tests**" in intro


def test_b1b_the_superseded_token_is_gone_from_the_readme_entirely() -> None:
    """Behavior 1: not merely absent from the two claims -- absent from the file."""
    old = guard.floor_token(_floor() - 100)
    readme = _read("README.md")
    assert old not in readme, (
        f"the superseded floor token {old!r} survives in README.md; the census and "
        "test_iter238 / test_iter245 both scan the intro for it"
    )


def test_b1c_nothing_but_the_floor_digits_changed_above_the_marker() -> None:
    """Behavior 1: the human-owned intro is byte-identical to ``HEAD`` once the ONE
    sanctioned number is neutralised on both sides -- so the carve-out was used for
    the floor and for nothing else.
    """
    live = _neutralised(_intro(_read("README.md")))
    head = _neutralised(_intro(_head_blob("README.md")))
    assert live == head, (
        "the portfolio intro changed beyond its numeric carve-out; only the "
        "collector count, the CLI-verb count and the floor may move"
    )
    # And the neutralisation really did have something to do -- but that is a DELTA,
    # true only before the raise is committed. Post-commit the two slices are the same
    # bytes by construction, so the steady-state invariant is byte-identity instead.
    live_intro = _intro(_read("README.md"))
    head_intro = _intro(_head_blob("README.md"))
    if _move_has_landed_in_head():
        assert live_intro == head_intro, (
            "the portfolio intro drifted from the blob its own commit carries; above "
            "the marker the shipping tree and HEAD must agree byte for byte"
        )
    else:
        assert live_intro != head_intro, (
            "the intro is unchanged from HEAD, so the floor was never raised"
        )


# ---------------------------------------------------------------------------
# Behavior 2 -- the eight declared carriers all claim the new floor, in the
# spelling each of them can write, and no undeclared file claims it.
# ---------------------------------------------------------------------------


def test_b2_the_carrier_census_reports_no_disagreement() -> None:
    """Behavior 2: one call covers both failure directions -- a declared carrier that
    stopped claiming the floor (a missed re-key) and an undeclared tracked file that
    started claiming it (a leaked literal).
    """
    floor = _floor()
    problems = guard.published_floor_disagreements(guard.tracked_text_sources(), floor)
    assert problems == [], (
        f"the carrier census disagrees at the live floor {guard.floor_token(floor)}: {problems}"
    )


def test_b2b_each_carrier_claims_the_floor_in_its_own_spelling() -> None:
    """Behavior 2: the census's spelling split is real, not incidental -- six files
    carry the comma token and the two rounding-window owners carry the underscore.
    """
    floor = _floor()
    comma, underscore = guard.floor_tokens(floor)
    sources = guard.tracked_text_sources()
    assert set(COMMA_CARRIERS) | set(UNDERSCORE_CARRIERS) == set(
        guard.PUBLISHED_FLOOR_CARRIERS
    ), "the declared carrier set moved; re-derive the spelling split before shipping"
    for path in COMMA_CARRIERS:
        assert comma in sources[path], f"{path} no longer claims the floor in comma form"
    for path in UNDERSCORE_CARRIERS:
        assert underscore in sources[path], (
            f"{path} no longer pins the floor as a PEP 515 underscore literal"
        )
        assert guard.floor_claim_lines(sources[path], comma), (
            f"{path} must still register as a claimant through the derived spellings"
        )


# ---------------------------------------------------------------------------
# Behavior 3 -- the live collection sits inside the raised rounding window.
# ---------------------------------------------------------------------------


def test_b3_the_live_count_sits_inside_the_new_rounding_window() -> None:
    """Behavior 3: BOTH rounding clauses hold at the raised floor, measured by a
    real collection rather than assumed.
    """
    floor = _floor()
    live = guard.collect_live_test_count()
    assert live // 100 * 100 == floor, f"live {live} does not round down to {floor}"
    assert (live + 1) // 100 * 100 == floor, (
        f"live {live} + 1 leaves the {floor} window: one more test would move the floor"
    )
    assert floor <= live <= floor + 98, f"live {live} is outside [{floor}, {floor + 98}]"
    assert guard._published_floor_for(live) == floor, (
        "the README's floor is not the floor the live count implies"
    )


# ---------------------------------------------------------------------------
# Behaviors 4 and 5 -- both literal families moved one step, together.
# ---------------------------------------------------------------------------


def test_b4_no_tracked_file_still_claims_the_superseded_floor() -> None:
    """Behaviors 4 + 5, the acceptance criterion: every surviving mention of the old
    floor is either a history line (``->`` / ``factory iter``) or one of the declared
    RECORD sites. No live claim of the old number may remain anywhere in the tree.
    """
    old = _floor() - 100
    spellings = (*guard.floor_tokens(old), str(old))
    stray: list[str] = []
    for path, text in sorted(guard.tracked_text_sources().items()):
        if path in CENSUS_EXEMPT:
            continue
        allowed = SUPERSEDED_ALLOWANCES.get(path, ())
        for number, line in enumerate(text.splitlines(), start=1):
            if not any(spelling in line for spelling in spellings):
                continue
            if any(marker in line for marker in guard.FLOOR_HISTORY_MARKERS):
                continue
            if any(anchor in line for anchor in allowed):
                continue
            stray.append(f"{path}:{number}: {line.strip()[:120]}")
    assert stray == [], (
        "these lines still name the superseded floor without being a history line "
        f"or a declared record site: {stray}"
    )


def test_b4b_every_declared_record_site_is_still_load_bearing() -> None:
    """Behaviors 4 + 5: the allowance list is not a rug. Each declared site must
    STILL contain a superseded-floor mention, so a stale exemption cannot accumulate.
    """
    old = _floor() - 100
    spellings = (*guard.floor_tokens(old), str(old))
    sources = guard.tracked_text_sources()
    for path, anchors in sorted(SUPERSEDED_ALLOWANCES.items()):
        text = sources[path]
        for anchor in anchors:
            hits = [
                line
                for line in text.splitlines()
                if anchor in line and any(s in line for s in spellings)
            ]
            assert hits, (
                f"{path}: the exemption anchored on {anchor!r} no longer matches any "
                "line naming the superseded floor -- delete the exemption"
            )


def test_b5_the_stale_family_moved_one_step_behind_the_live_floor() -> None:
    """Behavior 5: the SUPERSEDED/STALE family is exactly one step behind the live
    floor in every module that pins it, and the two halves move in one commit.
    """
    floor = _floor()
    old_comma = guard.floor_token(floor - 100)
    iter143 = _read("tests/test_iter143_behavior.py")
    iter171 = _read("tests/test_iter171_behavior.py")
    assert f'STALE_FLOOR_TOKEN = "{old_comma}"' in iter143, (
        "test_iter143's stale-floor token is not one step behind the live floor"
    )
    assert f'assert \'STALE_FLOOR_TOKEN = "{old_comma}"\' in iter143' in iter171, (
        "test_iter171's assertion on that literal text did not move with it"
    )
    assert f'assert "{old_comma}" not in intro' in iter171, (
        "test_iter171's README guard still names the wrong superseded token"
    )
    # The strict clause's replace target is the NEW floor, so the reconstruction can
    # reproduce the pre-commit HEAD intro byte-for-byte.
    assert f'intro.replace("{guard.floor_token(floor)}", STALE_FLOOR_TOKEN)' in iter143, (
        "test_iter143's strict clause does not replace the NEW floor token"
    )
    for path in UNDERSCORE_CARRIERS:
        module = _read(path)
        assert f"SUPERSEDED_FLOOR = {floor - 100:_}" in module, (
            f"{path}'s SUPERSEDED_FLOOR is not one step behind the live floor"
        )
        assert f"EXPECTED_FLOOR = {floor:_}" in module, (
            f"{path}'s EXPECTED_FLOOR does not pin the live floor"
        )


def test_b5b_the_historical_verdict_record_is_left_byte_identical() -> None:
    """Behavior 5's exclusion: ``test_iter249_behavior.py`` narrates a PAST failure
    verdict, so its numbers are immutable history, not a floor claim. An expectation
    about immutable history must be a literal, and the file must not be swept up by a
    family re-key.
    """
    rel = "tests/test_iter249_behavior.py"
    assert _read(rel) == _head_blob(rel), (
        f"{rel} changed; its recorded verdict is past-tense history and must stay "
        "byte-identical across a floor raise"
    )


# ---------------------------------------------------------------------------
# Behaviors 6 and 7 -- the roadmap records this iteration once, and records the
# gauge defect that caused the previous revert.
# ---------------------------------------------------------------------------


def test_b6_the_done_ledger_gains_exactly_one_row_for_this_iteration() -> None:
    """Behavior 6: ONE new ledger row, id ``#270``, folding BOTH halves, naming the
    floor beside an arrow so it records the raise without CLAIMING the floor.
    """
    floor = _floor()
    roadmap = _read("ROADMAP.md")
    rows = [line for line in roadmap.splitlines() if line.startswith("- #270 ")]
    assert len(rows) == 1, f"expected exactly one '- #270' ledger row, got {rows}"
    row = rows[0]
    for needle in (
        "`SPEC.md`",
        "4.2",
        "provider contract",
        "`SPEC_ARCHIVE.md`",
        "retiring row #179",
        f"{guard.floor_token(floor - 100)} -> {guard.floor_token(floor)}",
        "(foundry iter 288)",
    ):
        assert needle in row, f"ledger row #270 does not name {needle!r}: {row}"
    ids = [int(m) for m in re.findall(r"^- #(\d+) ", roadmap, flags=re.MULTILINE)]
    # The "270 is the HIGHEST ledger id" pin that stood here is DELETED: it re-broke
    # on the very next ledger row (foundry iter 289), which is what the identical pin
    # iteration 251 removed from its sibling module had already done. The append-only
    # invariant it was reaching for is OWNED by
    # `tests/test_iter251_behavior.py::test_b8c`, spelled so it survives every
    # successor row instead of dating this file to one iteration.
    assert ids.count(270) == 1, "this iteration folded into ONE row, never two"
    # The floor is NAMED in the roadmap and CLAIMED nowhere in it.
    assert guard.floor_token(floor) in roadmap
    assert guard.floor_claim_lines(roadmap, guard.floor_token(floor)) == (), (
        "a ROADMAP line claims the live floor without a history marker, which makes "
        "the file an undeclared carrier"
    )


def test_b6b_index_row_179_retired_into_the_archive_rekeyed_to_this_iteration() -> None:
    """Behavior 6: the index row leaves ``ROADMAP.md`` and its retirement bullet lands
    in the archive re-keyed to THIS iteration (not the reverted one).
    """
    roadmap = _read("ROADMAP.md")
    archive = _read("ROADMAP_ARCHIVE.md")
    assert not [
        line for line in roadmap.splitlines() if line.startswith("| 179 |")
    ], "index row #179 is still live in ROADMAP.md"
    bullets = [line for line in archive.splitlines() if line.startswith("- **#179 --")]
    assert len(bullets) == 1, f"expected one archived #179 retirement bullet, got {len(bullets)}"
    assert "iter-288, foundry iter 288" in bullets[0], (
        "the #179 retirement bullet is not re-keyed to this iteration: " + bullets[0][:200]
    )
    assert "SPEC_ARCHIVE.md" in bullets[0]


def test_b7_the_roadmap_queues_the_measured_headroom_gauge_defect() -> None:
    """Behavior 7: ONE new QUEUED index row, id ``#271``, recording the gauge defect
    that sized iteration 285 wrongly -- including the trap that makes it non-trivial.
    """
    roadmap = _read("ROADMAP.md")
    rows = [line for line in roadmap.splitlines() if line.startswith("| 271 |")]
    assert len(rows) == 1, f"expected exactly one queued row 271, got {len(rows)}"
    row = rows[0]
    for needle in (
        "readme-headroom",
        "SUITE_SIZE_SLACK",
        "499",
        "98",
        "402",
        "Makefile",
        "README.md",
        "test_iter176_behavior.py",
        "QUEUED",
    ):
        assert needle in row, f"queued row #271 does not name {needle!r}"
    assert "TRAP" in row, "row #271 must name the frozen-sample trap it carries"


def test_b7b_the_roadmap_stays_inside_its_char_budget() -> None:
    """Acceptance criterion: two new rows plus a retirement must not eat the headroom
    the PM stage depends on. Measured, not estimated.
    """
    import tests.test_iter214_behavior as retirement
    import tests.test_roadmap_size_budget as budget

    size = len(_read("ROADMAP.md").encode("utf-8"))
    limit = int(budget.ROADMAP_CHAR_LIMIT)
    floor_headroom = int(retirement.MIN_HEADROOM)
    assert size + floor_headroom <= limit, (
        f"ROADMAP.md is {size} chars against a {limit} limit with {floor_headroom} "
        "of required headroom; relocate at least as much as you added"
    )


# ---------------------------------------------------------------------------
# Behaviors 8, 9 and 10 -- the relocation is published, the re-landed prose names
# THIS iteration, and the preserved oracle ships whole.
# ---------------------------------------------------------------------------


def test_b8_the_archive_is_published_and_the_spec_shrank() -> None:
    """Behavior 8: the new companion is tracked, the vision respects the post-slice
    ceiling (strictly smaller than its ``HEAD`` size until the shrink itself lands),
    and the README's Project-documents section lists five.
    """
    tracked = _tracked()
    assert "SPEC_ARCHIVE.md" in tracked, "SPEC_ARCHIVE.md is not tracked"
    live_spec = len(_read("SPEC.md").encode("utf-8"))
    head_spec = len(_head_blob("SPEC.md").encode("utf-8"))
    if _move_has_landed_in_head():
        # This arm governs EVERY iteration after 288, because the probe is one-way by
        # its own docstring ("a one-way, once-ever event that no later iteration
        # undoes") and `SPEC_ARCHIVE.md` entered HEAD in commit 1709fc5. It therefore
        # may NOT assert byte-equality with HEAD. Post-commit that is a tautology, but
        # PRE-commit it reads "no stage may leave SPEC.md modified" -- an accidental
        # FREEZE on the vision file, and the authoritative tester runs pre-commit. It
        # was never a real guard: no commit between 288 and 292 touched SPEC.md, so the
        # equality only ever compared a file with itself. Iteration 292 is the first
        # edit since, and correcting section 2's stale rosters is established practice
        # (factory iter 193 did it) commissioned by ROADMAP row #231.
        # The durable invariant the relocation actually bought is the post-slice
        # CEILING, so assert that instead -- same claim as
        # tests/test_iter255_behavior.py::test_b3, and unlike HEAD's bytes it holds
        # identically on both sides of the commit.
        import tests.test_iter255_behavior as slice_guard

        ceiling = int(slice_guard.SPEC_CEILING_AFTER_SLICE)
        assert live_spec <= ceiling, (
            f"SPEC.md is {live_spec} bytes, over the {ceiling}-byte post-slice ceiling "
            f"(HEAD carries {head_spec}): the headroom the relocation bought is being "
            "given back. Relocate settled prose; do not raise the ceiling"
        )
    else:
        assert live_spec < head_spec, (
            f"SPEC.md did not shrink: {live_spec} bytes against a HEAD of {head_spec}"
        )
    assert len(_read("SPEC_ARCHIVE.md").strip()) > 0, "the archive is empty"
    readme = _read("README.md")
    at = readme.index("## Project documents")
    section = readme[at : readme.index("\n## ", at + 4)]
    assert MARKER not in section, "the Project-documents section must sit BELOW the marker"
    links = re.findall(r"^- \*\*\[([^\]]+)\]", section, flags=re.MULTILINE)
    assert len(links) == 5, f"expected five listed companion documents, got {links}"
    assert "SPEC_ARCHIVE.md" in links, f"SPEC_ARCHIVE.md is not listed: {links}"
    assert "Five committed documents" in section, (
        "the section's own count sentence disagrees with its list"
    )


def test_b9_the_relanded_prose_names_this_iteration_not_the_reverted_one() -> None:
    """Behavior 9: every prose mention of the relocation inside the re-landed modules
    names foundry iter 288. A patch preserved across a revert carries the OLD
    iteration number, and nothing but prose review catches it.
    """
    iter214 = _read("tests/test_iter214_behavior.py")
    assert "iteration 288 retired row #179" in iter214, (
        "test_iter214's retirement-census comment does not credit iteration 288"
    )
    # The retirement-bullet TOTAL is not a snapshot: tests/test_iter214_behavior.py:374-395
    # designs that literal to move by exactly +1 on every sanctioned row retirement and its
    # own failure message orders the retiring iteration to bump it. Iteration 292 retired
    # row #231, so 78 -> 79. Re-key this token with that bump; do not freeze it (same
    # lesson as tests/test_iter258_behavior.py::test_ac1, which forbids the return of the
    # ledger-id pin that used to red this build on every new ledger row).
    assert "== 79" in iter214, "the retirement-bullet total is not the expected literal 79"
    iter234 = _read("tests/test_iter234_behavior.py")
    assert "foundry iter 288" in iter234, (
        "test_iter234::test_b7's prose does not name foundry iter 288"
    )
    assert "SPEC_ARCHIVE.md" in iter234
    for rel, text in (
        ("tests/test_iter214_behavior.py", iter214),
        ("tests/test_iter234_behavior.py", iter234),
        ("tests/test_iter255_behavior.py", _read("tests/test_iter255_behavior.py")),
    ):
        for reverted in REVERTED_ITERATIONS:
            assert reverted not in text, (
                f"{rel} still names the reverted iteration {reverted}; "
                "the re-key is incomplete"
            )


def test_b10_the_preserved_oracle_ships_whole() -> None:
    """Behavior 10: the module iteration 285 earned lands intact and tracked. Its
    case count is asserted as a FLOOR, not an equality: the spec quoted the
    pre-revert size (607 lines / 12 cases) and the shipped module is larger, so an
    equality here would fail on a legitimate repair.
    """
    rel = "tests/test_iter255_behavior.py"
    assert rel in _tracked(), f"{rel} is not tracked"
    text = _read(rel)
    cases = re.findall(r"^def (test_\w+)", text, flags=re.MULTILINE)
    assert len(cases) >= 11, f"{rel} lost cases: only {len(cases)} remain ({cases})"
    assert len(text.splitlines()) >= 607, f"{rel} shrank to {len(text.splitlines())} lines"
    assert "SPEC_ARCHIVE.md" in text, "the preserved oracle no longer names its own subject"


def test_b10b_the_iteration_touched_no_source_and_no_lockfile() -> None:
    """Acceptance criteria: ``src/`` untouched and ``uv.lock`` untouched, so CI's
    ``--locked`` step cannot drift and no runtime behavior moved.

    Keyed on THIS iteration's shipping COMMIT, never on ``git diff HEAD`` -- the same
    spelling `tests/test_iter251_behavior.py::test_b10b` already uses, and for the
    reason `tests/test_iter257_behavior.py::test_t12` exists: a worktree-versus-``HEAD``
    read answers "what is uncommitted RIGHT NOW", which is a claim about whoever is
    running the suite rather than about this iteration. It went vacuously green the
    moment this work landed (a clean worktree diffs to nothing) and then reddened the
    NEXT iteration that touched ``src/`` at all -- an ownership inversion, since this
    module's scope claim cannot be a veto over its successors. Reading the file list of
    the commit tagged `(foundry iter 288)` measures exactly what shipped here, stays
    true in a fresh clone forever, and is silent about every later commit.
    """
    subjects = _git("log", "--format=%H %s", "-n", "300").splitlines()
    tag = "(foundry iter 288)"
    sha = next((line.split(" ", 1)[0] for line in subjects if tag in line), None)
    if sha is None:
        # Not yet committed: the shipping SET is the working tree, so measure that.
        names = [
            line[3:].strip()
            for line in _git("status", "--porcelain").splitlines()
            if line.strip()
        ]
        assert names, "no shipping commit and a clean tree: nothing to measure"
    else:
        names = _git("show", "--name-only", "--format=", sha).split()
    changed = [
        name
        for name in names
        if name.startswith("src/") or name in {"uv.lock", "pyproject.toml"}
    ]
    assert changed == [], f"a docs/bookkeeping increment changed {changed}"


# ---------------------------------------------------------------------------
# Extension (retry round) -- ground the first round had not covered.
# ---------------------------------------------------------------------------

#: The heading of the ONE section this iteration relocates. A content anchor, never a
#: line number, and bounded by the NEXT heading so a later relocation cannot widen it.
ARCHIVE_SECTION_ANCHOR = "### 4.2 llm/providers.py"


def _archived_section(archive: str) -> str:
    """The relocated section's own text, from its heading to the next heading."""
    start = archive.index(ARCHIVE_SECTION_ANCHOR)
    nxt = archive.find("\n### ", start + len(ARCHIVE_SECTION_ANCHOR))
    return archive[start:] if nxt == -1 else archive[start:nxt]


def test_b2c_the_census_domain_is_the_shipping_tree_and_not_the_head_tree() -> None:
    """Behavior 2: the census must SEE this iteration's new files.

    ``tracked_text_sources`` takes its domain from ``git ls-files``, so a new file that
    is still untracked when the census runs contributes ZERO violations at every stage
    and then self-hits the moment it is committed. That is the measured shape that
    reverted iteration 154 and bit two more, and it is invisible to a green census.
    Assert the domain directly, and assert it over every DECLARED carrier too, so a
    carrier that fell out of the tree cannot be mistaken for a carrier that agrees.
    """
    sources = guard.tracked_text_sources()
    for rel in (
        "SPEC_ARCHIVE.md",
        "tests/test_iter255_behavior.py",
        "tests/test_iter256_behavior.py",
    ):
        assert rel in sources, (
            f"{rel} is outside the floor census's domain (git ls-files), so the census "
            "cannot see it -- it must be tracked before its content is measured"
        )
        assert sources[rel].strip(), f"{rel} is in the domain but decodes to nothing"
    for path in guard.PUBLISHED_FLOOR_CARRIERS:
        assert path in sources, (
            f"declared floor carrier {path} is not in the census domain; the census "
            "would report agreement it never measured"
        )


def test_b2d_this_module_is_not_itself_a_floor_carrier() -> None:
    """Behavior 2's other direction, aimed at this file.

    An undeclared tracked file that claims the live floor reds the census. This module
    asserts things ABOUT the floor, so it is the likeliest accidental ninth carrier --
    and the failure would land on whoever performs the NEXT raise, not on this
    iteration. Both spellings plus the bare digits, so no future edit can leak one.
    """
    me = _read("tests/test_iter256_behavior.py")
    floor = _floor()
    for token in (*guard.floor_tokens(floor), str(floor)):
        assert token not in me, (
            f"this module spells the live floor as {token!r}; it must derive every "
            "number from guard.published_floor() so the next raise leaves it untouched"
        )
    assert "tests/test_iter256_behavior.py" not in guard.PUBLISHED_FLOOR_CARRIERS
    assert guard.floor_claim_lines(me, guard.floor_token(floor)) == ()


def test_b3b_the_raise_is_exactly_one_step_above_the_published_predecessor() -> None:
    """Behaviors 1 + 3: the floor advanced by exactly ONE hundred.

    ``published_floor()`` only proves the README and the live count agree, which a
    two-step overshoot also satisfies. Comparing against the floor the ``HEAD`` README
    published makes "the raise is one step" an assertion rather than an assumption.
    """
    head_claims = {digits for digits, _ in guard.SUITE_CLAIM.findall(_intro(_head_blob("README.md")))}
    assert len(head_claims) == 1, (
        f"HEAD's intro published more than one distinct floor token: {sorted(head_claims)}"
    )
    (head_token,) = tuple(head_claims)
    head_floor = int(head_token.replace(",", ""))
    if _move_has_landed_in_head():
        assert _floor() == head_floor, (
            f"the live floor {_floor()} disagrees with the {head_token} its own commit "
            "publishes; once the raise is in HEAD the two readings are one number"
        )
    else:
        assert _floor() == head_floor + 100, (
            f"the floor moved {_floor() - head_floor} from HEAD's {head_token}; a raise "
            "is one rounded hundred, and a wider jump means the window was skipped, "
            "not moved"
        )


def test_b8c_the_relocated_prose_is_byte_identical_to_the_head_spec() -> None:
    """Behavior 8's *byte-for-byte* clause, as an oracle rather than a promise.

    Three failure modes, each silent under a size check alone: prose PARAPHRASED on the
    way across, prose COPIED without being removed from ``SPEC.md`` (which buys no
    headroom at all), and the heading vanishing from ``SPEC.md`` so a reader of the
    fixed intent can no longer find where the contract went.
    """
    archive = _read("SPEC_ARCHIVE.md")
    assert ARCHIVE_SECTION_ANCHOR in archive, (
        f"SPEC_ARCHIVE.md does not carry {ARCHIVE_SECTION_ANCHOR!r}"
    )
    section = _archived_section(archive).strip()
    assert section, "the relocated section is empty"
    if _move_has_landed_in_head():
        # HEAD is the SLICED document, so the body's byte-identity has to be proved
        # against its new owner instead -- and the old owner must no longer hold it.
        assert section in _head_blob("SPEC_ARCHIVE.md"), (
            "the archived section is not a byte-identical substring of git show "
            "HEAD:SPEC_ARCHIVE.md -- the shipping tree and its own commit disagree"
        )
        assert section not in _head_blob("SPEC.md"), (
            "the committed SPEC.md STILL carries the relocated body, so what shipped "
            "was a copy and it bought no headroom"
        )
    else:
        assert section in _head_blob("SPEC.md"), (
            "the archived section is not a byte-identical substring of git show "
            "HEAD:SPEC.md -- it was re-typed or reflowed, so the relocation is not "
            "verbatim"
        )
    live_spec = _read("SPEC.md")
    assert section not in live_spec, (
        "the archived section is STILL in SPEC.md: this is a copy, not a relocation, and "
        "it buys none of the headroom the iteration exists to buy"
    )
    assert ARCHIVE_SECTION_ANCHOR in live_spec, (
        "SPEC.md dropped the relocated section's heading; a moved body must leave the "
        "heading plus a pointer behind"
    )
    at = live_spec.index(ARCHIVE_SECTION_ANCHOR)
    nxt = live_spec.find("\n### ", at + len(ARCHIVE_SECTION_ANCHOR))
    pointer = live_spec[at:] if nxt == -1 else live_spec[at:nxt]
    assert "SPEC_ARCHIVE.md" in pointer, (
        f"SPEC.md's surviving section names no pointer to the archive: {pointer!r}"
    )
