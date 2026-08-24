"""Black-box behavior tests for state-dir iteration 234 (ships as ``foundry iter 234``):
``pla run`` ACCOUNTS FOR THE AUTO-APPROVED GOALS IT DID NOT DISPATCH.

Feature under test: ``gate_slate()`` returns a decision per goal, so a slate routinely
carries several ``AUTO_DISPATCH`` goals while ``run`` dispatches only the top-ranked one.
Before this iteration the run report accounted for two of the three outcome classes -- the
dispatched goal (named and summarized) and the ``NEEDS_APPROVAL`` goals (counted, listed,
each with a paste-ready command) -- while the auto-approved-but-not-run goals got no
sentence and no command, i.e. the one class the gate judged safe to run unattended was the
one class the user could not act on without re-reading the slate file by hand.  This module
pins the new accounting block: a COUNT, the skipped goals in ``ranked()`` order, and one
paste-ready ``pla dispatch`` line each.

MODULE NAME -- derived from the REPO, never from the state-dir number.  ``git ls-files
tests`` holds 231 entries whose highest ``test_iterNN_behavior.py`` is **212**, so 213 is
the next free name, and ``git cat-file -e HEAD:tests/test_iter213_behavior.py`` FAILED
before the first byte was written.  Naming a module from the state-dir counter (234 here)
is what overwrote a shipped 18,786-byte oracle in state-dir 186.

ISOLATION CONTRACT (honored, no exception).  Every assertion below is derived from this
iteration's spec (``pm.md`` "Expected Behaviors" 1-6), from the conventions of the existing
modules under ``tests/`` (``test_iter62_behavior.py`` is the shipped ``run --dry-run``
module -- its ``main(argv)`` + ``capsys`` harness, its four shipped stdout markers, its
needs-approval block extractor and its volatile-token normaliser are reused verbatim in
spirit; ``test_scout.py`` supplies the public gate vocabulary and the score formula), and
from the product's OBSERVABLE stdout obtained by RUNNING it.  **No file under ``src/`` was
read, no ``git diff`` was inspected, and neither ``engineer.md``, ``reviewer.md`` nor
``fix_review.md`` was opened.**

OFFLINE AND DETERMINISTIC.  Every invocation uses the bundled scripted provider with a
per-module response file derived from the tracked ``examples/scripted_responses.json`` (its
``synthesize`` payloads swapped for a hand-built slate; every ``plan``/``check`` entry
reused verbatim so a REAL dispatch still has a scripted loop to run): no network, no API
key, no clock or duration assertion.  Workspaces are PRIVATE ``tmp_path_factory`` copies of
the tracked ``examples/fixture_workspace`` -- never the shared fixture in place (the
iter-142 shared-mutable-tree hazard) and never the ambient repo tree, whose signals differ
in a fresh clone (the iter-154 fresh-clone trap).  Every ``--state-dir`` lives outside the
scanned workspace so a run's own artifacts cannot become perception input.

NON-VACUITY IS ASSERTED, NOT ASSUMED.  Every test re-derives its slate's gate outcome
through the PUBLIC gate (``gate_slate`` + a bare ``Settings()``) and asserts the shape it
depends on as an explicit PRECONDITION -- three ``AUTO_DISPATCH`` plus two
``NEEDS_APPROVAL`` for the main slate, exactly one ``AUTO_DISPATCH`` for the single slate,
zero for the none slate.  A fixture that stopped producing the shape under test therefore
fails loudly instead of quietly passing an empty claim against an empty set.

AMBIGUITY NOTES (PM feedback):

* Behavior 3 asks for stdout "byte-identical to the pre-change output".  A test cannot
  invoke the pre-change tree, so the testable reading -- the one that actually protects a
  caller -- is asserted instead: with exactly one auto-approved goal (and with zero) the
  new block is ABSENT, and the COUNT of rendered ``pla dispatch`` lines is exactly the
  number the shipped report already owned (one per NEEDS_APPROVAL goal, plus the single
  ``--dry-run`` preview line).  A stray new command line therefore fails.
  ``test_iter212_behavior.py`` reached the same reading for the same wording.
* The spec fixes the block's CONTENT (count, ranked order, one paste-ready command each)
  but not its exact header WORDING, so the header locator below was read from the product's
  own stdout -- output, which the role card admits, not source.  It is matched
  case-insensitively as a substring so a re-worded sentence does not red the build while a
  lost count, a lost goal or a lost command still does.
* Behavior 5 says the dry-run block is "the same ... same commands" as a real run.  Two
  independent scans mint fresh random goal ids and write to different ``--state-dir``
  paths, so full byte equality is unreachable by construction; equality is asserted after
  normalising exactly those two volatile tokens (the ``test_iter62`` behavior-8 recipe),
  and the identity the normaliser erases is asserted separately per run by behavior 2.
* "Paste-ready" is read as EXECUTABLE, not merely well-formed: behavior 2 shells the
  printed command back through ``main()`` verbatim (only the offline provider flags and a
  fresh state dir are appended) and asserts it dispatches that exact goal id.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.models import AutonomyDecision, GoalSlate
from proactive_loop.scout import gate_slate

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

# Markers of the SHIPPED report, carried over from tests/test_iter62_behavior.py.
_DISPATCH_MARKER = "auto-dispatching top goal"
_DRY_PREVIEW_PREFIX = "[dry-run] would auto-dispatch top goal:"
_NOTHING_TO_RUN = "no auto-dispatchable goal in this slate; nothing to run."
_NEEDS_APPROVAL_HEADER = "goal(s) need approval and were NOT auto-run:"

# Locator for THIS iteration's new block, read from observed stdout (see the
# ambiguity note above), matched case-insensitively.
_SKIPPED_HEADER_RE = re.compile(r"auto-approved but not run", re.IGNORECASE)

_DISPATCH_CMD = "pla dispatch"
_HEX12 = re.compile(r"\b[0-9a-f]{12}\b")

# The seven documented top-level keys of `run --json` (behavior 6).
_JSON_KEYS = {
    "workspace_root",
    "slate_path",
    "goal_count",
    "needs_approval",
    "top_goal",
    "dispatched",
    "deferred",
}


# ---------------------------------------------------------------------------
# Slates.  score == impact * urgency * confidence / effort_weight and the gate
# threshold defaults to 4.0 inclusive; finance_legal is sensitive so it can
# never auto-dispatch; a below-threshold score reads NEEDS_APPROVAL
# (tests/test_scout.py).  Every score below is DISTINCT, so ranked() order is
# total and no assertion here can depend on a tie-break.
# ---------------------------------------------------------------------------


def _goal(
    title: str,
    category: str,
    impact: float,
    urgency: float,
    *,
    confidence: float = 1.0,
    effort_weight: float = 1.0,
    appropriate_now: bool = True,
) -> dict:
    return {
        "title": title,
        "rationale": f"iteration-234 accounting fixture: {title}",
        "category": category,
        "impact": impact,
        "urgency": urgency,
        "confidence": confidence,
        "effort_weight": effort_weight,
        "appropriate_now": appropriate_now,
        "sources": ["notes/journal.md"],
        "suggested_first_steps": ["write the artifact"],
    }


AUTO_TOP = "Draft the alpha learning plan"
AUTO_SECOND = "Draft the beta project scaffold"
AUTO_THIRD = "Draft the gamma refactor notes"
SENSITIVE = "Sort out a personal tax question"
LOW_SCORE = "Refresh portfolio talking points"

# 3 AUTO_DISPATCH (25.0 / 20.0 / 15.0) + 2 NEEDS_APPROVAL (sensitive at 10.0,
# below-threshold at 0.5).
MAIN_GOALS = [
    _goal(AUTO_TOP, "project", 5.0, 5.0),
    _goal(AUTO_SECOND, "project", 5.0, 4.0),
    _goal(AUTO_THIRD, "maintenance", 5.0, 3.0),
    _goal(SENSITIVE, "finance_legal", 5.0, 2.0),
    _goal(LOW_SCORE, "career", 1.0, 1.0, confidence=0.5),
]
# Exactly ONE AUTO_DISPATCH goal, beside one NEEDS_APPROVAL goal.
SINGLE_GOALS = [MAIN_GOALS[0], MAIN_GOALS[3]]
# ZERO AUTO_DISPATCH goals.
NONE_GOALS = [MAIN_GOALS[3], MAIN_GOALS[4]]


# ---------------------------------------------------------------------------
# Harness -- black-box: drive main(argv), read back exit code + stdout/stderr.
# ---------------------------------------------------------------------------


def _scripted_file(path: Path, goals: list[dict]) -> Path:
    """The tracked response file with every ``synthesize`` payload swapped for
    ``goals``; ``plan``/``check`` entries are reused verbatim so a real dispatch
    still has a scripted loop to run."""
    doc = json.loads(SCRIPT.read_text(encoding="utf-8"))
    for entry in doc["responses"]:
        if entry["tag"] == "synthesize":
            entry["text"] = json.dumps(goals)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def bed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """A private workspace copy plus the three response files."""
    root = tmp_path_factory.mktemp("iter213")
    ws = root / "workspace"
    shutil.copytree(FIXTURE, ws)
    return {
        "ws": ws,
        "main": _scripted_file(root / "main.json", MAIN_GOALS),
        "single": _scripted_file(root / "single.json", SINGLE_GOALS),
        "none": _scripted_file(root / "none.json", NONE_GOALS),
    }


@pytest.fixture(autouse=True)
def _default_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the shipped 4.0 threshold in effect so a bare ``Settings()`` agrees
    with the gate the verb ran (the iter-185 ambient-env-leak trap)."""
    monkeypatch.delenv("PLA_AUTO_DISPATCH_MIN_SCORE", raising=False)


def _args(ws: Path, script: Path, state_dir: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--state-dir", str(state_dir),
        *extra,
    ]


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _slate_of(state_dir: Path) -> GoalSlate:
    return GoalSlate.model_validate_json(
        (state_dir / "slate.json").read_text(encoding="utf-8")
    )


def _ranked_decisions(slate: GoalSlate) -> list[tuple[str, AutonomyDecision]]:
    """(title, decision) in ranked() order, derived through the PUBLIC gate so
    these tests encode the CONTRACT rather than the CLI's own bookkeeping."""
    by_id = {d.goal_id: d.decision for d in gate_slate(slate, Settings())}
    return [(g.title, by_id[g.id]) for g in slate.ranked()]


def _titles_with(slate: GoalSlate, decision: AutonomyDecision) -> list[str]:
    return [t for t, d in _ranked_decisions(slate) if d is decision]


def _ids_by_title(slate: GoalSlate) -> dict[str, str]:
    return {g.title: g.id for g in slate.goals}


def _skipped_block(out: str) -> list[str]:
    """The new accounting block: from its header line up to (not including) the
    first blank line after it.  Returns [] when the block is absent."""
    lines = out.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if _SKIPPED_HEADER_RE.search(ln)), None
    )
    if start is None:
        return []
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if not ln.strip():
            break
        block.append(ln)
    return block


def _needs_approval_block(out: str) -> list[str]:
    """The SHIPPED needs-approval block, extracted exactly as
    tests/test_iter62_behavior.py extracts it."""
    lines = out.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if _NEEDS_APPROVAL_HEADER in ln), None
    )
    if start is None:
        return []
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if (_DRY_PREVIEW_PREFIX in ln
                or ln.startswith(_DISPATCH_MARKER)
                or _NOTHING_TO_RUN in ln):
            break
        block.append(ln)
    while block and not block[-1].strip():
        block.pop()
    return block


def _dispatch_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith(_DISPATCH_CMD)]


def _norm(text: str, state_dir: Path) -> str:
    """Erase the two volatile tokens -- the per-tmp state-dir path and the random
    12-hex goal ids -- so two independent runs can be compared byte-for-byte."""
    return _HEX12.sub("<ID>", text.replace(str(state_dir), "<SD>"))


# ---------------------------------------------------------------------------
# Behavior 1 + 2 -- the skipped auto-approved goals are counted, named in
# ranked() order, and each carries a paste-ready command.
# ---------------------------------------------------------------------------


def test_b01_skipped_auto_goals_counted_and_named_in_ranked_order(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"
    rc, out, _err = _run(_args(bed["ws"], bed["main"], state_dir), capsys)
    assert rc == 0, out

    slate = _slate_of(state_dir)
    autos = _titles_with(slate, AutonomyDecision.AUTO_DISPATCH)
    # PRECONDITION (non-vacuity): the spec's three-auto shape really is present.
    assert autos == [AUTO_TOP, AUTO_SECOND, AUTO_THIRD], _ranked_decisions(slate)

    deferred = autos[1:]
    block = _skipped_block(out)
    assert block, f"no skipped-auto-approval block in stdout:\n{out}"

    header = block[0]
    assert re.search(rf"\b{len(deferred)}\b", header), (
        f"header must state the count {len(deferred)}; got {header!r}"
    )
    # The dispatched goal is accounted for elsewhere, never as a skipped goal.
    assert AUTO_TOP not in "\n".join(block), block

    # Named, in ranked() order.
    named = [t for t in (AUTO_TOP, AUTO_SECOND, AUTO_THIRD, SENSITIVE, LOW_SCORE)
             if any(t in ln for ln in block)]
    order = sorted(named, key=lambda t: min(
        i for i, ln in enumerate(block) if t in ln))
    assert order == deferred, f"block order {order} != ranked order {deferred}"


def test_b02_each_skipped_goal_has_a_paste_ready_dispatch_command(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    """Behavior 2: one ``pla dispatch`` line per skipped goal, carrying THIS
    run's slate path and THAT goal's id."""
    state_dir = tmp_path / "state"
    rc, out, _err = _run(_args(bed["ws"], bed["main"], state_dir), capsys)
    assert rc == 0, out

    slate = _slate_of(state_dir)
    autos = _titles_with(slate, AutonomyDecision.AUTO_DISPATCH)
    assert len(autos) == 3, _ranked_decisions(slate)
    deferred = autos[1:]
    ids = _ids_by_title(slate)

    slate_path = state_dir / "slate.json"
    assert slate_path.is_file(), "the run must have written the slate it cites"

    block = _skipped_block(out)
    cmds = _dispatch_lines("\n".join(block))
    assert len(cmds) == len(deferred), f"{len(deferred)} commands expected; block={block}"

    for title, cmd in zip(deferred, cmds):
        argv = shlex.split(cmd)
        assert argv[:2] == ["pla", "dispatch"], cmd
        assert "--slate" in argv and argv[argv.index("--slate") + 1] == str(slate_path), cmd
        assert "--goal-id" in argv and argv[argv.index("--goal-id") + 1] == ids[title], (
            f"command for {title!r} must carry its own id {ids[title]}; got {cmd}"
        )


def test_b02b_printed_command_actually_dispatches_that_goal(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    """"Paste-ready" read as EXECUTABLE: the first printed command, run back
    through the CLI verbatim (only the offline provider flags and a fresh state
    dir appended), dispatches exactly the goal it names."""
    state_dir = tmp_path / "state"
    rc, out, _err = _run(
        _args(bed["ws"], bed["main"], state_dir, "--dry-run"), capsys
    )
    assert rc == 0, out

    slate = _slate_of(state_dir)
    autos = _titles_with(slate, AutonomyDecision.AUTO_DISPATCH)
    assert len(autos) >= 2, _ranked_decisions(slate)
    expected_title = autos[1]
    expected_id = _ids_by_title(slate)[expected_title]

    cmds = _dispatch_lines("\n".join(_skipped_block(out)))
    assert cmds, out
    argv = shlex.split(cmds[0])
    assert argv[0] == "pla", cmds[0]

    rc2, out2, err2 = _run(
        argv[1:] + [
            "--provider", "scripted",
            "--scripted-responses", str(bed["main"]),
            "--state-dir", str(tmp_path / "exec"),
        ],
        capsys,
    )
    assert rc2 == 0, f"printed command failed: rc={rc2}\nstdout={out2}\nstderr={err2}"
    assert expected_title in out2 and expected_id in out2, out2


# ---------------------------------------------------------------------------
# Behavior 3 -- the block is additive: absent for one auto goal, absent for zero.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dry", [True, False], ids=["dry-run", "real"])
def test_b03_single_auto_goal_leaves_the_report_unchanged(
    bed: dict[str, Path], tmp_path: Path, capsys, dry: bool
) -> None:
    state_dir = tmp_path / "state"
    extra = ("--dry-run",) if dry else ()
    rc, out, _err = _run(_args(bed["ws"], bed["single"], state_dir, *extra), capsys)
    assert rc == 0, out

    slate = _slate_of(state_dir)
    autos = _titles_with(slate, AutonomyDecision.AUTO_DISPATCH)
    approvals = _titles_with(slate, AutonomyDecision.NEEDS_APPROVAL)
    # PRECONDITION: exactly one auto-approved goal, and a real approval goal too.
    assert autos == [AUTO_TOP], _ranked_decisions(slate)
    assert approvals == [SENSITIVE], _ranked_decisions(slate)

    assert _skipped_block(out) == [], f"block must not appear for one auto goal:\n{out}"
    # No stray command: exactly one per approval goal, plus the dry-run preview.
    expected = len(approvals) + (1 if dry else 0)
    assert len(_dispatch_lines(out)) == expected, out
    # The shipped decision line is untouched.
    assert (_DRY_PREVIEW_PREFIX in out) if dry else (_DISPATCH_MARKER in out), out


def test_b03b_zero_auto_goals_keeps_the_nothing_to_run_path(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"
    rc, out, _err = _run(_args(bed["ws"], bed["none"], state_dir), capsys)
    assert rc == 0, out

    slate = _slate_of(state_dir)
    assert _titles_with(slate, AutonomyDecision.AUTO_DISPATCH) == [], (
        _ranked_decisions(slate)
    )
    approvals = _titles_with(slate, AutonomyDecision.NEEDS_APPROVAL)
    assert approvals == [SENSITIVE, LOW_SCORE], _ranked_decisions(slate)

    assert _skipped_block(out) == [], f"block must not appear for zero autos:\n{out}"
    assert _NOTHING_TO_RUN in out, out
    assert len(_dispatch_lines(out)) == len(approvals), out


# ---------------------------------------------------------------------------
# Behavior 4 -- the two classes never cross-contaminate.
# ---------------------------------------------------------------------------


def test_b04_the_two_blocks_do_not_cross_contaminate(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"
    rc, out, _err = _run(_args(bed["ws"], bed["main"], state_dir), capsys)
    assert rc == 0, out

    slate = _slate_of(state_dir)
    autos = _titles_with(slate, AutonomyDecision.AUTO_DISPATCH)
    approvals = _titles_with(slate, AutonomyDecision.NEEDS_APPROVAL)
    # PRECONDITION: both classes are non-empty, so neither claim is vacuous.
    assert autos == [AUTO_TOP, AUTO_SECOND, AUTO_THIRD], _ranked_decisions(slate)
    assert approvals == [SENSITIVE, LOW_SCORE], _ranked_decisions(slate)
    ids = _ids_by_title(slate)

    skipped = "\n".join(_skipped_block(out))
    approval = "\n".join(_needs_approval_block(out))
    # PRECONDITION: both blocks really rendered.
    assert skipped and approval, out

    for title in approvals:
        assert title not in skipped, f"{title!r} is NEEDS_APPROVAL, not a skipped auto"
        assert ids[title] not in skipped, f"id of {title!r} leaked into the new block"
    for title in autos:
        assert title not in approval, f"{title!r} is AUTO_DISPATCH, not an approval goal"
        assert ids[title] not in approval, f"id of {title!r} leaked into the shipped block"

    # Accounting completeness: every AUTO_DISPATCH goal is either the dispatched
    # one or named in the new block -- the whole point of the feature.
    assert all(
        (t == autos[0]) or (t in skipped) for t in autos
    ), f"an auto-approved goal is unaccounted for:\n{out}"


# ---------------------------------------------------------------------------
# Behavior 5 -- the preview reports the same accounting as the act it previews.
# ---------------------------------------------------------------------------


def test_b05_dry_run_renders_the_same_skipped_block_as_a_real_run(
    bed: dict[str, Path], tmp_path: Path, capsys
) -> None:
    dry_dir = tmp_path / "dry"
    rc_dry, dry_out, _ = _run(_args(bed["ws"], bed["main"], dry_dir, "--dry-run"), capsys)
    real_dir = tmp_path / "real"
    rc_real, real_out, _ = _run(_args(bed["ws"], bed["main"], real_dir), capsys)
    assert rc_dry == 0 and rc_real == 0, (dry_out, real_out)

    dry_block = _skipped_block(dry_out)
    real_block = _skipped_block(real_out)
    assert dry_block and real_block, (dry_out, real_out)

    assert _norm("\n".join(dry_block), dry_dir) == _norm("\n".join(real_block), real_dir)
    # And the count/goal names survive the normalisation (guard against both
    # sides degrading to the same empty string).
    assert AUTO_SECOND in dry_block[1] or AUTO_SECOND in "\n".join(dry_block)
    assert len(_dispatch_lines("\n".join(dry_block))) == 2, dry_block


# ---------------------------------------------------------------------------
# Behavior 6 -- `run --json` still publishes exactly the seven documented keys.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dry", [True, False], ids=["dry-run", "real"])
def test_b06_json_document_still_has_exactly_seven_top_level_keys(
    bed: dict[str, Path], tmp_path: Path, capsys, dry: bool
) -> None:
    state_dir = tmp_path / "state"
    extra = ["--json"] + (["--dry-run"] if dry else [])
    rc, out, err = _run(_args(bed["ws"], bed["main"], state_dir, *extra), capsys)
    assert rc == 0, err

    assert out.lstrip().startswith("{"), repr(out[:80])
    doc = json.loads(out)
    assert isinstance(doc, dict)
    assert set(doc) == _JSON_KEYS, sorted(doc)

    # The human accounting block is a stdout-report concern only: with --json the
    # machine stream stays a single document and the block goes to stderr.
    assert not _SKIPPED_HEADER_RE.search(out), out
    assert _skipped_block(err), (
        "the new block must still be reported on the human stream under --json"
    )
