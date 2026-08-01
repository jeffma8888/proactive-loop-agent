"""Black-box behavior tests for iteration 06.

Feature under test: ``pla explain --slate SLATE --goal-id ID`` -- a read-only,
LLM-free CLI verb that, for ONE goal in a saved slate, prints its score
arithmetic (echoing the model's computed ``score``), the live autonomy-gate
decision + which rule fired + the auto-dispatch threshold it was compared
against (so ``explain`` and a later ``dispatch`` agree), and the goal's
rationale / sources / suggested-first-steps. It completes the
``scan -> runs -> explain`` legibility arc and makes every dispatch decision
auditable after the fact.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors", ``README.md``,
and ``SPEC.md`` (the public design contract) -- and drive only the documented
public surface: the ``pla`` CLI via ``proactive_loop.cli.main([...])``, the
public ``proactive_loop.models.GoalSlate`` / ``CandidateGoal`` models (to load
the persisted ``slate.json`` and look up per-goal expected field values), the
public ``proactive_loop.scout.gate(goal, settings)`` re-gater, and
``proactive_loop.config.Settings.from_env()``. No file under ``src/`` was read,
no engineer/reviewer notes were read, and no ``git diff`` was consulted. The
specific goal for each of the four gate outcomes is chosen by RE-GATING every
loaded goal through the public ``gate()`` (never by hard-coding an id and never
by reading ``src/``). All expected substrings (arithmetic, echoed score,
decision value, reason, threshold) are BUILT from the loaded ``goal`` /
``settings`` at runtime, so the tests survive fixture/threshold changes. Every
test uses a fresh ``tmp_path`` state dir (never the repo's ``.pla_runs/``) and
runs fully offline -- zero network, zero API keys.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.models import CandidateGoal, GoalSlate
from proactive_loop.scout import gate

REPO = Path(__file__).resolve().parents[1]
# Absolute paths (runner-location-independent) to the offline fixtures.
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_TRACEBACK = "Traceback (most recent call last)"

# The four verbatim gate reasons documented in the spec (behavior 4) + SPEC.md
# §4.3 policy rules. Used to bucket goals by outcome, never to read src.
_REASON_AUTO = "score meets auto-dispatch threshold"
_REASON_BELOW = "below auto-dispatch threshold"
_REASON_SENSITIVE = "sensitive category"
_REASON_BLOCKED = "not appropriate right now"


# ---------------------------------------------------------------------------
# Setup helpers (the spec's prescribed setup convention)
# ---------------------------------------------------------------------------


def _produce_demo_slate(state_dir: Path) -> Path:
    """Write a real demo ``slate.json`` into ``state_dir`` via the offline
    ``scan`` path and return its path. Per SPEC §4.5 the demo slate holds four
    goals spanning all four gate outcomes."""
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ])
    assert rc == 0, f"demo `scan` setup must exit 0, got {rc}"
    slate_path = state_dir / "slate.json"
    assert slate_path.is_file(), "demo `scan` must write slate.json"
    return slate_path


def _load_slate(slate_path: Path) -> GoalSlate:
    return GoalSlate.model_validate_json(slate_path.read_text())


def _bucket_by_outcome(slate: GoalSlate, settings: Settings) -> dict[tuple[str, str], CandidateGoal]:
    """Map ``(decision_value, reason)`` -> goal by re-gating each loaded goal
    through the public ``gate()`` (the SAME gate the ``dispatch`` verb uses)."""
    buckets: dict[tuple[str, str], CandidateGoal] = {}
    for g in slate.goals:
        d = gate(g, settings)
        buckets[(d.decision.value, d.reason)] = g
    return buckets


def _arith(g: CandidateGoal) -> str:
    """Rebuild the exact substituted arithmetic the spec (behavior 3) mandates:
    single spaces around each operator, each value via Python's ``:g``."""
    return (
        f"{g.impact:g} * {g.urgency:g} * {g.confidence:g} / "
        f"{g.effort_weight:g} = {g.score:g}"
    )


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ---------------------------------------------------------------------------
# Behavior 1 -- exists as a subcommand; required options; argparse errors
# ---------------------------------------------------------------------------


def test_behavior1a_top_help_lists_explain_subcommand(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0, "`pla --help` must exit 0"
    out = capsys.readouterr().out
    assert "explain" in out, f"top-level help must list the 'explain' subcommand; got:\n{out}"


def test_behavior1b_explain_help_exits_zero_documents_required_options(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["explain", "--help"])
    assert excinfo.value.code == 0, "`pla explain --help` must exit 0"
    out = capsys.readouterr().out
    assert "--slate" in out, f"explain --help must document --slate; got:\n{out}"
    assert "--goal-id" in out, f"explain --help must document --goal-id; got:\n{out}"


def test_behavior1c_missing_goal_id_reaches_handler_not_argparse(tmp_path, capsys):
    # CONTRACT CHANGE (iter-72, behavior 6): --goal-id is now OPTIONAL, so omitting
    # it with --slate present is NO LONGER an argparse usage error. It reaches the
    # _cmd_explain missing-file guard, which returns exit 2 with a legible
    # `error: slate file not found: <path>` line -- NOT a parse-time usage error and
    # NOT a traceback. (This intentionally supersedes the old "omitting --goal-id is
    # an argparse usage error" contract; --slate stays required -- see behavior 7.)
    missing = tmp_path / "does-not-exist.json"
    rc = main(["explain", "--slate", str(missing)])
    assert rc == 2, f"missing slate file with no --goal-id must exit 2 (handler guard), got {rc}"
    err = capsys.readouterr().err
    assert f"error: slate file not found: {missing}" in err, (
        f"must be the handler's not-found line, not an argparse usage error; got:\n{err}"
    )
    assert "usage:" not in err, f"must NOT be an argparse usage error; got:\n{err}"
    assert _TRACEBACK not in err, f"handler guard must not traceback; got:\n{err}"


def test_behavior1d_missing_slate_is_argparse_usage_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["explain", "--goal-id", "x"])
    assert excinfo.value.code not in (0, None), (
        f"missing --slate must be a nonzero usage error, got {excinfo.value.code!r}"
    )
    err = capsys.readouterr().err
    assert "usage:" in err, f"missing --slate must print usage to stderr; got:\n{err}"
    assert _TRACEBACK not in err, f"argparse error must not traceback; got:\n{err}"


# ---------------------------------------------------------------------------
# Behavior 2 -- happy path: self-describing block with title, id, category value
# ---------------------------------------------------------------------------


def test_behavior2_happy_path_prints_title_id_category_value(tmp_path, capsys):
    slate_path = _produce_demo_slate(tmp_path / "state")
    slate = _load_slate(slate_path)
    assert slate.goals, "demo slate must contain goals"

    # Assert for EVERY goal in the slate so all category values are exercised.
    for g in slate.goals:
        rc, out, err = _run(["explain", "--slate", str(slate_path), "--goal-id", g.id], capsys)
        assert rc == 0, f"explain on a valid goal must exit 0, got {rc} (goal {g.id})"
        assert g.title in out, f"block must contain goal.title exactly; got:\n{out}"
        assert g.id in out, f"block must contain goal.id exactly; got:\n{out}"
        assert g.category.value in out, (
            f"block must contain the category VALUE {g.category.value!r}; got:\n{out}"
        )
        # ...and NOT the enum repr (e.g. 'GoalCategory.LEARNING').
        assert "GoalCategory." not in out, (
            f"block must print category.value, never the GoalCategory enum repr; got:\n{out}"
        )


# ---------------------------------------------------------------------------
# Behavior 3 -- score arithmetic + literal formula label + echoed model score
# ---------------------------------------------------------------------------


def test_behavior3_prints_score_arithmetic_echoing_model_score(tmp_path, capsys):
    slate_path = _produce_demo_slate(tmp_path / "state")
    slate = _load_slate(slate_path)

    for g in slate.goals:
        rc, out, err = _run(["explain", "--slate", str(slate_path), "--goal-id", g.id], capsys)
        assert rc == 0, f"explain must exit 0, got {rc}"
        # The substituted arithmetic, built from the loaded goal (:g formatting).
        assert _arith(g) in out, (
            f"block must contain the substituted arithmetic {_arith(g)!r}; got:\n{out}"
        )
        # The literal, unsubstituted formula label (self-documenting).
        assert "impact * urgency * confidence / effort_weight" in out, (
            f"block must contain the literal formula label; got:\n{out}"
        )
        # The printed result MUST equal the model's own computed score (echoed,
        # never recomputed) -- so it can never drift from the ranking.
        assert f"{g.score:g}" in out, (
            f"block must echo goal.score ({g.score:g}); got:\n{out}"
        )


# ---------------------------------------------------------------------------
# Behavior 4 -- live gate decision + reason + threshold (explain == dispatch)
# ---------------------------------------------------------------------------


def test_behavior4_auto_dispatch_decision_reason_threshold(tmp_path, capsys):
    slate_path = _produce_demo_slate(tmp_path / "state")
    settings = Settings.from_env()
    slate = _load_slate(slate_path)
    buckets = _bucket_by_outcome(slate, settings)
    goal = buckets.get(("auto_dispatch", _REASON_AUTO))
    assert goal is not None, "demo slate must contain an AUTO_DISPATCH goal"

    rc, out, err = _run(["explain", "--slate", str(slate_path), "--goal-id", goal.id], capsys)
    assert rc == 0
    # explain must report the SAME decision the dispatch verb's gate() computes.
    d = gate(goal, settings)
    assert d.decision.value == "auto_dispatch"
    assert d.decision.value in out, f"block must contain decision 'auto_dispatch'; got:\n{out}"
    assert _REASON_AUTO in out, f"block must contain the verbatim reason; got:\n{out}"
    # The numeric auto-dispatch threshold it was compared against appears.
    assert str(settings.auto_dispatch_min_score) in out, (
        f"block must show the auto_dispatch_min_score threshold "
        f"({settings.auto_dispatch_min_score}); got:\n{out}"
    )


def test_behavior4_below_threshold_decision_reason_threshold(tmp_path, capsys):
    slate_path = _produce_demo_slate(tmp_path / "state")
    settings = Settings.from_env()
    slate = _load_slate(slate_path)
    buckets = _bucket_by_outcome(slate, settings)
    goal = buckets.get(("needs_approval", _REASON_BELOW))
    assert goal is not None, "demo slate must contain a below-threshold NEEDS_APPROVAL goal"

    rc, out, err = _run(["explain", "--slate", str(slate_path), "--goal-id", goal.id], capsys)
    assert rc == 0
    assert "needs_approval" in out, f"block must contain 'needs_approval'; got:\n{out}"
    assert _REASON_BELOW in out, f"block must contain the verbatim reason; got:\n{out}"
    assert str(settings.auto_dispatch_min_score) in out, (
        f"block must show the threshold it fell below; got:\n{out}"
    )


def test_behavior4_sensitive_decision_reason(tmp_path, capsys):
    slate_path = _produce_demo_slate(tmp_path / "state")
    settings = Settings.from_env()
    slate = _load_slate(slate_path)
    buckets = _bucket_by_outcome(slate, settings)
    goal = buckets.get(("needs_approval", _REASON_SENSITIVE))
    assert goal is not None, "demo slate must contain a sensitive-category NEEDS_APPROVAL goal"

    rc, out, err = _run(["explain", "--slate", str(slate_path), "--goal-id", goal.id], capsys)
    assert rc == 0
    assert "needs_approval" in out, f"block must contain 'needs_approval'; got:\n{out}"
    assert _REASON_SENSITIVE in out, f"block must contain the verbatim reason; got:\n{out}"


def test_behavior4_blocked_decision_reason_and_appropriate_now_false(tmp_path, capsys):
    slate_path = _produce_demo_slate(tmp_path / "state")
    settings = Settings.from_env()
    slate = _load_slate(slate_path)
    buckets = _bucket_by_outcome(slate, settings)
    goal = buckets.get(("blocked", _REASON_BLOCKED))
    assert goal is not None, "demo slate must contain a not-appropriate-now BLOCKED goal"
    assert goal.appropriate_now is False, "the BLOCKED demo goal must have appropriate_now=False"

    rc, out, err = _run(["explain", "--slate", str(slate_path), "--goal-id", goal.id], capsys)
    assert rc == 0
    assert "blocked" in out, f"block must contain 'blocked'; got:\n{out}"
    assert _REASON_BLOCKED in out, f"block must contain the verbatim reason; got:\n{out}"
    # The block must report appropriate_now is false for this goal.
    appro_lines = [ln for ln in out.splitlines() if "appropriate" in ln.lower()]
    assert appro_lines, f"block must report appropriate_now; got:\n{out}"
    assert any("false" in ln.lower() for ln in appro_lines), (
        f"block must report appropriate_now as false; got lines: {appro_lines}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- rationale, sources, suggested first steps
# ---------------------------------------------------------------------------


def test_behavior5_prints_rationale_sources_first_steps(tmp_path, capsys):
    slate_path = _produce_demo_slate(tmp_path / "state")
    slate = _load_slate(slate_path)
    # Pick a goal with a NON-EMPTY sources list (the demo has several).
    goal = next((g for g in slate.goals if g.sources), None)
    assert goal is not None, "demo slate must contain a goal with non-empty sources"

    rc, out, err = _run(["explain", "--slate", str(slate_path), "--goal-id", goal.id], capsys)
    assert rc == 0
    assert goal.rationale in out, f"block must contain the goal's rationale; got:\n{out}"
    for src in goal.sources:
        assert src in out, f"block must list each source string ({src!r}); got:\n{out}"
    for step in goal.suggested_first_steps:
        assert step in out, f"block must list each suggested first step ({step!r}); got:\n{out}"


def test_behavior5_empty_sources_and_steps_show_none_marker(tmp_path, capsys):
    # Build (via the public model) a goal with empty sources + first steps and
    # write it as a valid slate; explain must render a '(none)' marker for each.
    g = CandidateGoal(
        title="Goal with no provenance",
        rationale="a rationale with no sources or steps",
        category="learning",
        impact=5.0, urgency=4.0, confidence=0.9, effort_weight=1.0,
        appropriate_now=True, sources=[], suggested_first_steps=[],
    )
    slate = GoalSlate(workspace_root=str(FIXTURE), goals=[g])
    slate_path = tmp_path / "empty_prov_slate.json"
    slate_path.write_text(slate.model_dump_json())

    rc, out, err = _run(["explain", "--slate", str(slate_path), "--goal-id", g.id], capsys)
    assert rc == 0, f"explain on an empty-provenance goal must exit 0, got {rc}"
    assert "(none)" in out, (
        f"empty sources / first steps must render a '(none)' marker; got:\n{out}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- LLM-free: constructs no LLM client
# ---------------------------------------------------------------------------


def test_behavior6_bogus_scripted_responses_path_still_succeeds(tmp_path, capsys):
    slate_path = _produce_demo_slate(tmp_path / "state")
    slate = _load_slate(slate_path)
    goal = slate.goals[0]

    # A bogus --scripted-responses path would fault ANY verb that constructs a
    # scripted client. explain exiting 0 here proves it builds no LLMClient.
    rc, out, err = _run([
        "explain",
        "--slate", str(slate_path),
        "--goal-id", goal.id,
        "--scripted-responses", "/no/such/file.json",
    ], capsys)
    assert rc == 0, (
        f"explain must exit 0 even with a bogus --scripted-responses path "
        f"(proves no LLMClient constructed), got {rc}; stderr:\n{err}"
    )
    assert goal.title in out, f"the decision block must still print; got:\n{out}"


def test_behavior6_no_provider_flags_still_succeeds(tmp_path, capsys):
    slate_path = _produce_demo_slate(tmp_path / "state")
    slate = _load_slate(slate_path)
    goal = slate.goals[0]

    # No --provider, no --scripted-responses at all.
    rc, out, err = _run(["explain", "--slate", str(slate_path), "--goal-id", goal.id], capsys)
    assert rc == 0, f"explain must run with no provider flags, got {rc}; stderr:\n{err}"
    assert goal.title in out


# ---------------------------------------------------------------------------
# Behavior 7 -- missing slate file -> exit 2, legible stderr, no stdout
# ---------------------------------------------------------------------------


def test_behavior7_missing_slate_file_exit_2(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    assert not missing.exists()

    rc, out, err = _run(["explain", "--slate", str(missing), "--goal-id", "x"], capsys)
    assert rc == 2, f"missing slate file must exit 2, got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error: slate file not found:"), (
        f"stderr must begin with 'error: slate file not found:'; got:\n{err!r}"
    )
    assert str(missing) in err, f"stderr must name the missing path; got:\n{err!r}"
    assert _TRACEBACK not in err, f"must not print a traceback; got:\n{err!r}"


# ---------------------------------------------------------------------------
# Behavior 8 -- unknown goal id -> exit 2, legible stderr, no stdout
# ---------------------------------------------------------------------------


def test_behavior8_unknown_goal_id_exit_2(tmp_path, capsys):
    slate_path = _produce_demo_slate(tmp_path / "state")
    missing_id = "does-not-exist"

    rc, out, err = _run(["explain", "--slate", str(slate_path), "--goal-id", missing_id], capsys)
    assert rc == 2, f"unknown goal id must exit 2, got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error: goal id "), (
        f"stderr must begin with 'error: goal id '; got:\n{err!r}"
    )
    assert missing_id in err, f"stderr must contain the requested id; got:\n{err!r}"
    assert "not found in slate" in err, (
        f"stderr must contain the phrase 'not found in slate'; got:\n{err!r}"
    )
    assert _TRACEBACK not in err, f"must not print a traceback; got:\n{err!r}"


# ---------------------------------------------------------------------------
# Behavior 9 -- corrupt slate JSON -> exit 1 via the main() error boundary
# ---------------------------------------------------------------------------


def test_behavior9_corrupt_slate_json_exit_1(tmp_path, capsys):
    bad = tmp_path / "corrupt.json"
    bad.write_text("{ not json")

    rc, out, err = _run(["explain", "--slate", str(bad), "--goal-id", "x"], capsys)
    assert rc == 1, f"corrupt slate JSON must exit 1 (via the main() boundary), got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error:"), (
        f"stderr's first line must begin with 'error:'; got:\n{err!r}"
    )
    # The load-bearing contract of behavior 9 is exit 1 + an 'error:' line + no
    # raw traceback (the top-level boundary catches it). NOTE (PM feedback): the
    # spec says "a single error: line", but pydantic's ValidationError message
    # is inherently MULTI-line, so a strict single-line assertion would be
    # wrong; the intent (boundary, no traceback) is what is tested here.
    assert _TRACEBACK not in err, f"corrupt slate must NOT print a traceback; got:\n{err!r}"


# ---------------------------------------------------------------------------
# Behavior 10 -- no regression to existing verbs / demo; deterministic render
# ---------------------------------------------------------------------------


def test_behavior10a_existing_verbs_unchanged(tmp_path, capsys):
    # --version still exits 0 (iter-05 contract).
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0, "`pla --version` must still exit 0"
    capsys.readouterr()

    # scan still exits 0 and writes the slate, dispatching nothing.
    scan_state = tmp_path / "scan_state"
    out_path = tmp_path / "slate.json"
    rc_scan = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(scan_state),
        "--out", str(out_path),
    ])
    assert rc_scan == 0, f"scan must still exit 0, got {rc_scan}"
    assert out_path.is_file(), "scan must still write the slate JSON"
    assert not list(scan_state.glob("run-*")), "scan alone must still dispatch nothing"
    capsys.readouterr()

    # runs on an empty state dir still exits 0 (iter-04 contract).
    empty = tmp_path / "empty_state"
    empty.mkdir()
    assert main(["runs", "--state-dir", str(empty)]) == 0, "runs must still exit 0"
    capsys.readouterr()

    # dispatch on an unknown goal id still exits 2 (its documented code).
    empty_slate = tmp_path / "empty_slate.json"
    empty_slate.write_text(GoalSlate(workspace_root=str(FIXTURE)).model_dump_json())
    rc_bad = main([
        "dispatch",
        "--slate", str(empty_slate),
        "--goal-id", "does-not-exist",
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "d_state"),
    ])
    assert rc_bad == 2, f"dispatch unknown goal-id must still exit 2, got {rc_bad}"


def test_behavior10b_end_to_end_demo_run_still_succeeds(tmp_path, capsys):
    # The exact vector `make demo` uses still exits 0 and writes slate + both
    # artifacts + a checkpointed run dir -- adding `explain` did not perturb it.
    run_state = tmp_path / "run_state"
    rc = main([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(run_state),
    ])
    assert rc == 0, f"end-to-end demo `run` must exit 0, got {rc}"
    assert (run_state / "slate.json").is_file(), "demo run must write slate.json"
    run_dirs = list(run_state.glob("run-*"))
    assert len(run_dirs) == 1, f"demo must dispatch exactly one run, got {run_dirs}"
    assert (run_dirs[0] / "artifacts" / "learning_plan.md").is_file()
    assert (run_dirs[0] / "artifacts" / "project_scaffold.md").is_file()


def test_behavior10c_explain_render_is_deterministic(tmp_path, capsys):
    # The explain render is a pure function of (goal, decision, settings):
    # two invocations against the same unchanged slate are byte-identical.
    slate_path = _produce_demo_slate(tmp_path / "state")
    slate = _load_slate(slate_path)
    goal = slate.goals[0]

    rc1, out1, _ = _run(["explain", "--slate", str(slate_path), "--goal-id", goal.id], capsys)
    rc2, out2, _ = _run(["explain", "--slate", str(slate_path), "--goal-id", goal.id], capsys)
    assert rc1 == 0 and rc2 == 0
    assert out1 == out2, "repeated explain output on an unchanged slate must be byte-identical"
