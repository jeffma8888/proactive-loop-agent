"""Black-box behavior tests for state-dir iteration 242 (ships as ``foundry iter 242``):
``pla run --json`` PUBLISHES THE AUTO-APPROVED GOALS THE RUN DEFERRED.

Feature under test.  ``gate_slate()`` decides per goal, so a slate routinely carries
several ``AUTO_DISPATCH`` goals while ``run`` dispatches only the top-ranked one.  Iter
234 gave the leftovers a HUMAN accounting block ("auto-approved but NOT run"), and iter
236 made its ``--slate`` argument absolute so a person can paste it -- but the MACHINE
document printed by ``run --json`` never got the fact.  A supervising script was therefore
told which goals it may **not** act on unattended (``needs_approval``) while being blind
to the goals the autonomy contract had **already cleared** and this invocation merely did
not reach: the one class it is authorised to dispatch.  This module pins the seventh
always-present key ``deferred`` -- the machine twin of that human block.

MODULE NAME -- derived from the REPO, never from the state-dir number.  The state dir is
``iter-242``; the highest ``test_iterNN_behavior.py`` in ``git ls-files tests`` is **220**,
so 221 is the next free name.  Re-proved before the first byte was written:
``git cat-file -e HEAD:tests/test_iter221_behavior.py`` exited 128 ("does not exist in
'HEAD'") and ``git status`` reports this path as ``A``, not ``M``.  Naming a module from
the state-dir counter is what silently overwrote a shipped 18,786-byte oracle in state-dir
186.

ISOLATION CONTRACT (honored, no exception).  Every assertion below is derived from this
iteration's spec (``pm.md`` "Expected Behaviors" 1-6), from the conventions of the modules
already under ``tests/`` -- ``test_iter213_behavior.py`` supplies the PROVEN offline
harness this spec mandates (``_goal``, ``_scripted_file``, ``_args``, ``_slate_of``,
``_ranked_decisions``, ``_titles_with``, ``_ids_by_title``, the ``_skipped_block``
extractor and ``_dispatch_lines``), ``test_iter125_behavior.py`` the shared ``PLA_*``
clearer -- and from the product's OBSERVABLE output obtained by RUNNING it.  **No file
under ``src/`` was read, no ``git diff`` was inspected, and neither ``engineer.md``,
``reviewer.md`` nor ``IMPLEMENTATION.patch`` was opened.**

OFFLINE AND DETERMINISTIC.  Every invocation drives the bundled scripted provider over a
per-module response file derived from the tracked ``examples/scripted_responses.json`` (its
``synthesize`` payloads swapped for a hand-built slate, every ``plan``/``check`` entry
reused verbatim so a REAL dispatch still has a scripted loop to run): no network, no API
key, no clock or duration assertion.  Workspaces are PRIVATE ``tmp_path_factory`` copies
of the tracked ``examples/fixture_workspace`` -- never the shared fixture in place (the
iter-142 shared-mutable-tree hazard), never the ambient repo tree and never the repo's
gitignored ``.pla_runs/`` (the iter-154 fresh-clone trap: the release gate re-verifies
every ship from a THROWAWAY CLONE, where gitignored paths do not exist).  Every
``--state-dir`` lives outside the scanned workspace so a run's own artifacts cannot become
perception input.

NON-VACUITY IS ASSERTED, NOT ASSUMED.  Every test re-derives its slate's gate outcome
through the PUBLIC gate (``gate_slate`` + a bare ``Settings()``, via
``_ranked_decisions``) and asserts the shape it depends on as an explicit PRECONDITION --
three ``AUTO_DISPATCH`` + two ``NEEDS_APPROVAL`` + one ``BLOCKED`` for the main slate,
exactly one ``AUTO_DISPATCH`` for the single slate, zero for the none slate.  A fixture
that stopped producing the shape under test therefore fails loudly instead of quietly
passing an empty claim against an empty set.  The BLOCKED goal is deliberately scored
**22.5**, above two of the three auto-approved goals, so behavior 4's exclusion claim
cannot be satisfied by ranking accident.

AMBIGUITY NOTES (PM feedback):

* Behavior 1 says "exactly one JSON object to stdout".  Read as: stdout parses as a single
  ``dict`` (``json.loads`` rejects two concatenated documents) whose key set equals the
  seven named keys.  The seven names are quoted from the spec, not from the emitted
  document, so a renamed key fails rather than being adopted.
* Behavior 3 says the entry is a "strict mirror of a ``needs_approval`` entry".  Both
  shapes are asserted against the SAME literal ``{"id", "title"}`` set and, additionally,
  against each other on the one invocation that publishes both -- so the mirror claim
  holds even if the shared shape is later widened in one place only.
* Behavior 4 says "in ``slate.ranked()`` order (highest score first)".  ``ranked()`` sorts
  ``appropriate_now`` first and score second (``tests/test_scout.py``), so the assertion
  compares against the gate-filtered ``ranked()`` projection rather than a raw score sort.
* Behavior 5 says the stderr titles "equal" the document's titles.  Order is compared by
  FIRST APPEARANCE of each title over the whole slate's titles, so a ``needs_approval``
  title leaking into the deferred block fails too; the count is cross-checked a second,
  independent way (one ``pla dispatch`` line per deferred goal, the iter-213 precedent).
* Behavior 6(c) says ``dispatched`` is "the nine-key sub-document".  The spec does not
  enumerate those nine names, so this module asserts the COUNT the spec states plus the
  identity that ties it to the rest of the document (``dispatched["goal_id"] ==
  top_goal["id"]``); ``tests/test_iter158_behavior.py`` owns the nine names themselves.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.models import AutonomyDecision
from tests.test_iter125_behavior import clear_pla_env
from tests.test_iter213_behavior import (
    AUTO_SECOND,
    AUTO_THIRD,
    AUTO_TOP,
    LOW_SCORE,
    NONE_GOALS,
    SENSITIVE,
    SINGLE_GOALS,
    _args,
    _dispatch_lines,
    _goal,
    _ids_by_title,
    _ranked_decisions,
    _scripted_file,
    _skipped_block,
    _slate_of,
    _titles_with,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"

#: The SEVEN top-level keys this iteration's spec publishes (behavior 1).
_TOP_KEYS = frozenset(
    {
        "workspace_root",
        "slate_path",
        "goal_count",
        "needs_approval",
        "top_goal",
        "dispatched",
        "deferred",
    }
)
#: Behavior 3: a deferred entry mirrors a needs-approval entry exactly.
_GOAL_REF_KEYS = frozenset({"id", "title"})
#: Behavior 6(c): the spec's stated size of the dispatch sub-document.
_DISPATCH_KEY_COUNT = 9

#: A goal that would out-rank two auto-approved goals on score (22.5) but is
#: BLOCKED by ``appropriate_now=False`` regardless of score (tests/test_scout.py).
BLOCKED_HIGH = "Rewire the deployment during the change freeze"

#: 3 AUTO_DISPATCH (25.0 / 20.0 / 15.0) + 2 NEEDS_APPROVAL (sensitive 10.0,
#: below-threshold 0.5) + 1 BLOCKED (22.5).  Every score is DISTINCT, so
#: ``ranked()`` is a total order and no assertion depends on a tie-break.
MAIN_GOALS_WITH_BLOCKED = [
    _goal(AUTO_TOP, "project", 5.0, 5.0),
    _goal(AUTO_SECOND, "project", 5.0, 4.0),
    _goal(AUTO_THIRD, "maintenance", 5.0, 3.0),
    _goal(SENSITIVE, "finance_legal", 5.0, 2.0),
    _goal(LOW_SCORE, "career", 1.0, 1.0, confidence=0.5),
    _goal(BLOCKED_HIGH, "project", 5.0, 4.5, appropriate_now=False),
]

ALL_TITLES = [AUTO_TOP, AUTO_SECOND, AUTO_THIRD, SENSITIVE, LOW_SCORE, BLOCKED_HIGH]


# ---------------------------------------------------------------------------
# Harness -- black-box: drive main(argv), read back exit code + stdout/stderr.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """A private workspace copy plus the three response files this spec needs."""
    root = tmp_path_factory.mktemp("iter221")
    ws = root / "workspace"
    shutil.copytree(FIXTURE, ws)
    return {
        "ws": ws,
        "main": _scripted_file(root / "main.json", MAIN_GOALS_WITH_BLOCKED),
        "single": _scripted_file(root / "single.json", SINGLE_GOALS),
        "none": _scripted_file(root / "none.json", NONE_GOALS),
    }


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete every live ``PLA_*`` override so the SHIPPED gate defaults decide,
    and a bare ``Settings()`` agrees with the gate the verb ran (the iter-185
    ambient-env-leak trap)."""
    clear_pla_env(monkeypatch)


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _json_run(
    bed: dict[str, Path], slate_key: str, state_dir: Path, capsys, *extra: str
) -> tuple[int, dict, str]:
    """One ``run --json`` invocation -> (exit code, parsed document, stderr)."""
    rc, out, err = _run(
        _args(bed["ws"], bed[slate_key], state_dir, "--json", *extra), capsys
    )
    assert out.lstrip().startswith("{"), (
        f"stdout must be a single JSON object; got {out[:120]!r}"
    )
    document = json.loads(out)
    assert isinstance(document, dict), f"stdout must parse as an object; got {type(document)}"
    return rc, document, err


def _titles_in_first_appearance_order(block: list[str], candidates: list[str]) -> list[str]:
    """Every candidate title present in ``block``, ordered by first appearance."""
    found = [
        (min(i for i, line in enumerate(block) if title in line), title)
        for title in candidates
        if any(title in line for line in block)
    ]
    return [title for _index, title in sorted(found)]


def _expected_deferred(state_dir: Path) -> tuple[list[str], list[str], list[str]]:
    """(auto titles, needs-approval titles, blocked titles) in ranked() order,
    re-derived through the PUBLIC gate rather than the CLI's own bookkeeping."""
    slate = _slate_of(state_dir)
    return (
        _titles_with(slate, AutonomyDecision.AUTO_DISPATCH),
        _titles_with(slate, AutonomyDecision.NEEDS_APPROVAL),
        _titles_with(slate, AutonomyDecision.BLOCKED),
    )


def _assert_main_slate_shape(state_dir: Path) -> None:
    """PRECONDITION for behaviors 1, 3, 4, 5, 6(b), 6(c)."""
    autos, approvals, blocked = _expected_deferred(state_dir)
    decisions = _ranked_decisions(_slate_of(state_dir))
    assert autos == [AUTO_TOP, AUTO_SECOND, AUTO_THIRD], decisions
    assert approvals == [SENSITIVE, LOW_SCORE], decisions
    assert blocked == [BLOCKED_HIGH], decisions


# ---------------------------------------------------------------------------
# Behavior 1 -- the published key set is exactly SEVEN keys.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dry", [True, False], ids=["dry-run", "real"])
def test_b01_json_document_publishes_exactly_the_seven_keys(
    bed: dict[str, Path], tmp_path: Path, capsys, dry: bool
) -> None:
    state_dir = tmp_path / "state"
    extra = ("--dry-run",) if dry else ()
    rc, document, err = _json_run(bed, "main", state_dir, capsys, *extra)
    assert rc == 0, err
    _assert_main_slate_shape(state_dir)

    assert set(document) == set(_TOP_KEYS), (
        "run --json must publish exactly the seven documented keys; "
        f"missing={sorted(_TOP_KEYS - set(document))} "
        f"extra={sorted(set(document) - _TOP_KEYS)}"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- `deferred` is ALWAYS present, carried by VALUE, `[]` when the
# gated slate holds zero or one AUTO_DISPATCH goal.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slate_key", ["single", "none"], ids=["one-auto", "zero-auto"])
@pytest.mark.parametrize("dry", [True, False], ids=["dry-run", "real"])
def test_b02_deferred_is_an_empty_array_never_null_or_absent(
    bed: dict[str, Path], tmp_path: Path, capsys, slate_key: str, dry: bool
) -> None:
    state_dir = tmp_path / "state"
    extra = ("--dry-run",) if dry else ()
    rc, document, err = _json_run(bed, slate_key, state_dir, capsys, *extra)
    assert rc == 0, err

    autos, approvals, _blocked = _expected_deferred(state_dir)
    # PRECONDITION: the slate really is the shape this parametrisation claims.
    expected_autos = [AUTO_TOP] if slate_key == "single" else []
    assert autos == expected_autos, _ranked_decisions(_slate_of(state_dir))
    assert approvals, "precondition: a needs-approval goal keeps the run non-trivial"

    assert "deferred" in document, "`deferred` must be present on every exit path"
    deferred = document["deferred"]
    assert isinstance(deferred, list), f"`deferred` must be a JSON array; got {deferred!r}"
    assert deferred == [], (
        f"with {len(autos)} auto-approved goal(s) nothing is deferred; got {deferred!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- entry shape is a strict mirror of a `needs_approval` entry.
# ---------------------------------------------------------------------------


def test_b03_each_deferred_entry_is_exactly_id_and_title(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"
    rc, document, err = _json_run(bed, "main", state_dir, capsys)
    assert rc == 0, err
    _assert_main_slate_shape(state_dir)

    deferred = document["deferred"]
    # PRECONDITION: non-vacuous -- there really are entries to inspect.
    assert len(deferred) == 2, deferred

    for entry in deferred:
        assert isinstance(entry, dict), f"each entry must be an object; got {entry!r}"
        assert set(entry) == set(_GOAL_REF_KEYS), (
            "a deferred entry mirrors a needs_approval entry exactly; "
            f"missing={sorted(_GOAL_REF_KEYS - set(entry))} "
            f"extra={sorted(set(entry) - _GOAL_REF_KEYS)}"
        )
        for key in sorted(_GOAL_REF_KEYS):
            assert isinstance(entry[key], str) and entry[key], (
                f"deferred[].{key} must be a non-empty string; got {entry[key]!r}"
            )
        # In particular: no paste-ready command string rides along.
        assert "pla dispatch" not in json.dumps(entry), (
            f"the document mirrors needs_approval and carries no command; got {entry!r}"
        )

    # The mirror claim, asserted against the sibling class on the SAME document.
    approvals = document["needs_approval"]
    assert approvals, "precondition: this slate publishes needs_approval entries too"
    assert {frozenset(entry) for entry in deferred} == {
        frozenset(entry) for entry in approvals
    }, (
        "deferred and needs_approval must publish the identical entry shape; "
        f"deferred={deferred!r} needs_approval={approvals!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- membership and order; the published classes are disjoint.
# ---------------------------------------------------------------------------


def test_b04_deferred_is_the_ranked_remainder_and_the_classes_are_disjoint(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"
    rc, document, err = _json_run(bed, "main", state_dir, capsys)
    assert rc == 0, err
    _assert_main_slate_shape(state_dir)

    autos, approvals, blocked = _expected_deferred(state_dir)
    ids = _ids_by_title(_slate_of(state_dir))
    expected_titles = autos[1:]
    assert len(expected_titles) == 2, autos  # N-1 for N == 3

    deferred = document["deferred"]
    assert [entry["title"] for entry in deferred] == expected_titles, (
        "deferred must hold the N-1 auto-approved goals beyond the dispatched one, "
        f"in ranked() order; got {[e['title'] for e in deferred]!r}"
    )
    assert [entry["id"] for entry in deferred] == [ids[t] for t in expected_titles], (
        f"each deferred id must be that goal's own id; got {deferred!r}"
    )

    deferred_ids = {entry["id"] for entry in deferred}
    top = document["top_goal"]
    assert isinstance(top, dict), f"precondition: this run named a top goal; got {top!r}"
    assert top["id"] == ids[autos[0]], top
    assert top["id"] not in deferred_ids, (
        "the dispatched goal is accounted for by top_goal, never as deferred"
    )
    assert deferred_ids.isdisjoint({entry["id"] for entry in document["needs_approval"]}), (
        "the published classes are disjoint; a needs_approval id appeared in deferred"
    )
    for title in approvals:
        assert ids[title] not in deferred_ids, f"{title!r} is NEEDS_APPROVAL, not deferred"
    # A gate-BLOCKED goal appears in NEITHER published class, even though its
    # score (22.5) out-ranks two of the three auto-approved goals.
    assert blocked == [BLOCKED_HIGH], blocked
    blocked_id = ids[BLOCKED_HIGH]
    assert blocked_id not in deferred_ids, "a BLOCKED goal must not be published as deferred"
    assert blocked_id not in {entry["id"] for entry in document["needs_approval"]}, (
        "a BLOCKED goal must not be published as needs_approval either"
    )
    assert blocked_id != top["id"], "a BLOCKED goal must never be the dispatched goal"


# ---------------------------------------------------------------------------
# Behavior 5 -- the document agrees with the human report on the SAME invocation.
# ---------------------------------------------------------------------------


def test_b05_document_agrees_with_the_human_stderr_block(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"
    rc, document, err = _json_run(bed, "main", state_dir, capsys)
    assert rc == 0, err
    _assert_main_slate_shape(state_dir)

    block = _skipped_block(err)
    # PRECONDITION: the human block really rendered on the redirected stream.
    assert block, f"the auto-approved-but-NOT-run block must reach stderr:\n{err}"

    published = [entry["title"] for entry in document["deferred"]]
    assert published, "precondition: the document really publishes deferred titles"
    assert _titles_in_first_appearance_order(block, ALL_TITLES) == published, (
        "the stderr block and the document must name the same goals in the same "
        f"order; block={block!r} document={published!r}"
    )
    # Independent second signal on the COUNT (the iter-213 precedent).
    assert len(_dispatch_lines("\n".join(block))) == len(published), (
        f"one paste-ready command per deferred goal; block={block!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- all THREE `--json` exit paths publish it.
# ---------------------------------------------------------------------------


def test_b06a_no_auto_dispatchable_goal_publishes_an_empty_deferred(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"
    rc, document, err = _json_run(bed, "none", state_dir, capsys)
    assert rc == 0, err

    autos, approvals, _blocked = _expected_deferred(state_dir)
    assert autos == [], _ranked_decisions(_slate_of(state_dir))
    assert approvals == [SENSITIVE, LOW_SCORE], _ranked_decisions(_slate_of(state_dir))

    assert set(document) == set(_TOP_KEYS), sorted(document)
    assert document["top_goal"] is None, document["top_goal"]
    assert document["deferred"] == [], document["deferred"]


def test_b06b_dry_run_publishes_deferred_with_a_null_dispatched(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"
    rc, document, err = _json_run(bed, "main", state_dir, capsys, "--dry-run")
    assert rc == 0, err
    _assert_main_slate_shape(state_dir)

    autos, _approvals, _blocked = _expected_deferred(state_dir)
    ids = _ids_by_title(_slate_of(state_dir))

    assert set(document) == set(_TOP_KEYS), sorted(document)
    assert document["dispatched"] is None, (
        f"--dry-run must not dispatch; got {document['dispatched']!r}"
    )
    top = document["top_goal"]
    assert isinstance(top, dict) and top["id"] == ids[autos[0]], (
        f"top_goal must name the goal a real run WOULD dispatch; got {top!r}"
    )
    deferred = document["deferred"]
    assert [entry["title"] for entry in deferred] == autos[1:], deferred
    for entry in deferred:
        assert set(entry) == set(_GOAL_REF_KEYS), entry


def test_b06c_real_dispatch_publishes_deferred_beside_the_dispatch_subdocument(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"
    rc, document, err = _json_run(bed, "main", state_dir, capsys)
    assert rc == 0, err
    _assert_main_slate_shape(state_dir)

    autos, _approvals, _blocked = _expected_deferred(state_dir)
    ids = _ids_by_title(_slate_of(state_dir))

    assert set(document) == set(_TOP_KEYS), sorted(document)
    dispatched = document["dispatched"]
    assert isinstance(dispatched, dict), (
        f"a real auto-dispatch must publish a `dispatched` object; got {dispatched!r}"
    )
    assert len(dispatched) == _DISPATCH_KEY_COUNT, (
        f"`dispatched` is the {_DISPATCH_KEY_COUNT}-key sub-document; got {sorted(dispatched)}"
    )
    top = document["top_goal"]
    assert isinstance(top, dict), top
    assert dispatched["goal_id"] == top["id"] == ids[autos[0]], (
        f"dispatched.goal_id must be the dispatched goal's id; got {dispatched['goal_id']!r}"
    )

    deferred = document["deferred"]
    assert [entry["title"] for entry in deferred] == autos[1:], deferred
    assert dispatched["goal_id"] not in {entry["id"] for entry in deferred}, (
        "the goal that actually ran must never be published as deferred"
    )
