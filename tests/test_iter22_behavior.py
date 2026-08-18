"""Black-box behavior tests for iteration 22.

Feature under test: ``pla explain --slate S --goal-id ID --json`` -- a
machine-readable (JSON) form of the read-only, LLM-free autonomy-gate audit,
mirroring the ``--json`` flag every other inspector verb already carries
(``runs --json`` / ``trace --json`` / ``signals --json`` / ``scan --format json``).
Adding ``--json`` selects a JSON rendering ONLY; the guards, exit codes, and the
default human render are unchanged. The emitted object is an explicit 12-key
allowlist (never ``model_dump()``), with enums as their str ``.value``, ``score``
echoing the model's computed field, and ``sources`` / ``suggested_first_steps``
as JSON arrays (``[]`` when empty, not the human ``(none)`` marker).

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's PM spec "Expected Behaviors", ``README.md``,
and ``SPEC.md`` (the public design contract, esp. §4.3 gate rules and §4.5 the
``explain`` verb doc) -- and drive only the documented public surface: the
``pla`` CLI via ``proactive_loop.cli.main([...])`` (capturing stdout/stderr +
exit code), the public models ``CandidateGoal`` / ``GoalSlate``, the public
autonomy gate ``proactive_loop.scout.gate(goal, settings)``, and
``proactive_loop.config.Settings.from_env()`` (the same settings seam every
verb resolves through). NO file under ``src/`` was read, no engineer/reviewer
notes were read, and no ``git diff`` was consulted. Every expected
decision/reason is DERIVED at runtime from the public ``gate()`` (never
hard-coded against an implementation quirk) so the tests survive a
threshold/fixture change. Enum ``.value``s, the 12-key schema, and the
``score`` echo are asserted from the loaded ``goal`` / ``settings`` and the
public spec, never from the renderer's internals. Every test uses a fresh
``tmp_path`` slate file (never the repo's ``.pla_runs/``) and runs fully offline
-- zero network, zero API keys, only in-memory fixtures. The no-LLMClient proof
(Behavior 10) mirrors ``tests/test_providers.py``'s sys.modules discipline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.models import CandidateGoal, GoalSlate
from proactive_loop.scout import gate
from tests.test_iter125_behavior import clear_pla_env


@pytest.fixture(autouse=True)
def _hermetic_pla_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the derived ``PLA_*`` set before EVERY test in this module.

    This module asserts DOCUMENTED DEFAULTS, so any ``PLA_*`` knob exported in
    the developer shell -- and the README publishes them all as the supported
    configuration surface -- red a clean checkout while looking like broken
    code. The target set is derived from the call sites the runtime reads, so a
    new knob is covered the moment it lands. Function-scoped and autouse, so it
    runs BEFORE each test body: a test that sets its own override still wins.
    """
    clear_pla_env(monkeypatch)

REPO = Path(__file__).resolve().parents[1]

_TRACEBACK = "Traceback (most recent call last)"

# The 12 top-level keys the spec (Behavior 3) mandates -- no more, no fewer.
_EXPECTED_KEYS = {
    "id",
    "title",
    "category",
    "score",
    "score_components",
    "auto_dispatch_threshold",
    "decision",
    "reason",
    "appropriate_now",
    "rationale",
    "sources",
    "suggested_first_steps",
}
# The 4 nested keys of score_components (Behavior 4).
_EXPECTED_SC_KEYS = {"impact", "urgency", "confidence", "effort_weight"}

# The four verbatim gate reasons (SPEC.md §4.3), used only to document intent
# once gate() has been consulted -- never as the source of truth.
_REASON_AUTO = "score meets auto-dispatch threshold"
_REASON_BELOW = "below auto-dispatch threshold"
_REASON_SENSITIVE = "sensitive category"
_REASON_BLOCKED = "not appropriate right now"

# SDK modules whose absence proves the offline guarantee (Behavior 10).
_SDK_MODULES = ("anthropic", "openai", "boto3")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_slate(tmp_path: Path, *goals: CandidateGoal, name: str = "slate.json") -> Path:
    """Write an in-memory GoalSlate of the given goals to a tmp slate file."""
    slate = GoalSlate(workspace_root=str(tmp_path), goals=list(goals))
    path = tmp_path / name
    path.write_text(slate.model_dump_json())
    return path


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _explain_json(slate_path: Path, goal_id: str, capsys, extra: list[str] | None = None):
    """Run ``explain --json`` and return (rc, parsed_obj_or_None, stdout, stderr)."""
    argv = ["explain", "--slate", str(slate_path), "--goal-id", goal_id, "--json"]
    if extra:
        argv += extra
    rc, out, err = _run(argv, capsys)
    obj = json.loads(out) if out.strip() else None
    return rc, obj, out, err


# --- Goal fixtures spanning each gate branch (default threshold 4.0) --------


def _auto_goal() -> CandidateGoal:
    # non-sensitive, appropriate, score = 5*4*0.9/1 = 18.0 (>= 4.0) -> auto_dispatch
    return CandidateGoal(
        title="Learn RAG evaluation",
        rationale="study retrieval-augmented eval before the interview",
        category="learning",
        impact=5.0, urgency=4.0, confidence=0.9, effort_weight=1.0,
        appropriate_now=True,
        sources=["git:abc123", "file:notes/journal.md"],
        suggested_first_steps=["read the paper", "build a small demo"],
    )


def _below_goal() -> CandidateGoal:
    # non-sensitive, appropriate, score = 2*1.5*0.8/1 = 2.4 (< 4.0) -> below-threshold
    return CandidateGoal(
        title="Tidy up the README badges",
        rationale="cosmetic cleanup, low leverage",
        category="project",
        impact=2.0, urgency=1.5, confidence=0.8, effort_weight=1.0,
        appropriate_now=True,
        sources=["file:README.md"],
        suggested_first_steps=["audit the badge links"],
    )


def _sensitive_goal() -> CandidateGoal:
    # sensitive category at a MAXIMAL score = 5*5*1/1 = 25 -> still needs_approval
    return CandidateGoal(
        title="File the quarterly tax estimate",
        rationale="a finance/legal task the gate must never auto-run",
        category="finance_legal",
        impact=5.0, urgency=5.0, confidence=1.0, effort_weight=1.0,
        appropriate_now=True,
        sources=["file:finance/notes.md"],
        suggested_first_steps=["gather 1099s"],
    )


def _blocked_goal() -> CandidateGoal:
    # non-sensitive but appropriate_now=False -> blocked, regardless of score
    return CandidateGoal(
        title="Plan the Q4 career move",
        rationale="not the right moment to act on this",
        category="career",
        impact=5.0, urgency=5.0, confidence=1.0, effort_weight=1.0,
        appropriate_now=False,
        sources=["file:career/plan.md"],
        suggested_first_steps=["revisit after review season"],
    )


def _empty_provenance_goal() -> CandidateGoal:
    # non-sensitive, appropriate, empty sources + steps -> lists must be []
    return CandidateGoal(
        title="Goal with no provenance",
        rationale="a rationale with no sources or steps",
        category="learning",
        impact=5.0, urgency=4.0, confidence=0.9, effort_weight=1.0,
        appropriate_now=True,
        sources=[],
        suggested_first_steps=[],
    )


# ===========================================================================
# Behavior 1 -- --json defaults off; bare explain is unchanged (human render)
# ===========================================================================


def test_behavior1_json_defaults_off_human_render_unchanged(tmp_path, capsys):
    goal = _auto_goal()
    slate = _write_slate(tmp_path, goal)

    # Bare `explain` (no --json) still exits 0 and prints the HUMAN block, which
    # is NOT valid JSON (proves --json is opt-in and changed only the renderer,
    # not the default). The human markers of the iter-06 format are all present.
    rc, out, err = _run(["explain", "--slate", str(slate), "--goal-id", goal.id], capsys)
    assert rc == 0, f"bare explain must exit 0, got {rc}; stderr:\n{err}"
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)  # the default render is human text, never a JSON doc
    for marker in ("goal", "category", "score", "decision", "appropriate", "rationale"):
        assert marker in out, f"human block must retain the {marker!r} marker; got:\n{out}"
    assert goal.title in out and goal.id in out

    # The human render is a pure function of (goal, decision, settings): repeated
    # invocations on an unchanged slate are byte-identical.
    rc2, out2, _ = _run(["explain", "--slate", str(slate), "--goal-id", goal.id], capsys)
    assert rc2 == 0
    assert out == out2, "bare explain output must be deterministic / byte-identical"


def test_behavior1_json_output_differs_from_human(tmp_path, capsys):
    goal = _auto_goal()
    slate = _write_slate(tmp_path, goal)

    _, human, _ = _run(["explain", "--slate", str(slate), "--goal-id", goal.id], capsys)
    _, js, _ = _run(["explain", "--slate", str(slate), "--goal-id", goal.id, "--json"], capsys)

    assert human != js, "--json must select a distinct rendering from the human block"


# ===========================================================================
# Behavior 2 -- --json is a single parseable object, exit 0, no trailer
# ===========================================================================


def test_behavior2_single_parseable_object_exit0_no_trailer(tmp_path, capsys):
    goal = _auto_goal()
    slate = _write_slate(tmp_path, goal)

    rc, obj, out, err = _explain_json(slate, goal.id, capsys)

    assert rc == 0, f"explain --json must exit 0, got {rc}; stderr:\n{err}"
    assert err == "", f"nothing must go to stderr on the happy path; got:\n{err!r}"
    # The ENTIRE stdout is exactly one JSON object -- no leading/trailing prose,
    # no `slate written:` trailer -- so it pipes cleanly into jq.
    stripped = out.strip()
    assert stripped.startswith("{") and stripped.endswith("}"), f"stdout must be one JSON object; got:\n{out!r}"
    assert "slate written" not in out, f"explain --json must emit no trailer line; got:\n{out!r}"
    assert isinstance(obj, dict), "json.loads(stdout) must yield a single object"
    # json.loads over the RAW stdout (not just the stripped copy) also succeeds.
    assert json.loads(out) == obj


# ===========================================================================
# Behavior 3 -- exact 12 top-level keys (schema-leak guard)
# ===========================================================================


def test_behavior3_exact_top_level_key_set(tmp_path, capsys):
    goal = _auto_goal()
    slate = _write_slate(tmp_path, goal)

    rc, obj, out, _ = _explain_json(slate, goal.id, capsys)

    assert rc == 0
    assert set(obj) == _EXPECTED_KEYS, (
        f"top-level keys must be EXACTLY {sorted(_EXPECTED_KEYS)}; "
        f"got {sorted(obj)} (extra={sorted(set(obj) - _EXPECTED_KEYS)}, "
        f"missing={sorted(_EXPECTED_KEYS - set(obj))})"
    )
    # Schema-leak guard: private model fields that are NOT in the allowlist must
    # never surface (proves an explicit dict, not model_dump()).
    for leaked in ("timestamp", "created_at", "workspace_root", "run_dir"):
        assert leaked not in obj, f"{leaked!r} must not leak into the explain object"


# ===========================================================================
# Behavior 4 -- score_components nested key set is exact + echoes fields
# ===========================================================================


def test_behavior4_score_components_exact_keys_and_values(tmp_path, capsys):
    goal = _auto_goal()
    slate = _write_slate(tmp_path, goal)

    rc, obj, _, _ = _explain_json(slate, goal.id, capsys)

    assert rc == 0
    sc = obj["score_components"]
    assert isinstance(sc, dict)
    assert set(sc) == _EXPECTED_SC_KEYS, (
        f"score_components keys must be EXACTLY {sorted(_EXPECTED_SC_KEYS)}; got {sorted(sc)}"
    )
    # Each component echoes the goal's corresponding numeric field.
    assert sc["impact"] == goal.impact
    assert sc["urgency"] == goal.urgency
    assert sc["confidence"] == goal.confidence
    assert sc["effort_weight"] == goal.effort_weight
    for k in _EXPECTED_SC_KEYS:
        assert isinstance(sc[k], (int, float)), f"{k} must be numeric; got {type(sc[k])}"


# ===========================================================================
# Behavior 5 -- enums emit their string .value, never a Python repr
# ===========================================================================


def test_behavior5_enums_emit_value_not_repr(tmp_path, capsys):
    settings = Settings.from_env()
    # Exercise several categories AND several decision classes.
    for goal in (_auto_goal(), _sensitive_goal(), _blocked_goal(), _below_goal()):
        slate = _write_slate(tmp_path, goal, name=f"slate_{goal.id}.json")
        rc, obj, out, _ = _explain_json(slate, goal.id, capsys)
        assert rc == 0

        assert obj["category"] == goal.category.value, (
            f"category must be the enum .value {goal.category.value!r}; got {obj['category']!r}"
        )
        expected_decision = gate(goal, settings).decision.value
        assert obj["decision"] == expected_decision, (
            f"decision must be gate().decision.value {expected_decision!r}; got {obj['decision']!r}"
        )
        # Never a Python enum repr, anywhere in the serialized object.
        assert "GoalCategory." not in out, f"category enum repr leaked:\n{out}"
        assert "AutonomyDecision." not in out, f"decision enum repr leaked:\n{out}"


# ===========================================================================
# Behavior 6 -- score echoes the computed field (never recomputed)
# ===========================================================================


def test_behavior6_score_echoes_computed_field_and_rederives(tmp_path, capsys):
    for goal in (_auto_goal(), _below_goal(), _sensitive_goal(), _blocked_goal()):
        slate = _write_slate(tmp_path, goal, name=f"slate_{goal.id}.json")
        rc, obj, _, _ = _explain_json(slate, goal.id, capsys)
        assert rc == 0

        # Echoes the pydantic computed field exactly.
        assert obj["score"] == goal.score, (
            f"score must echo goal.score {goal.score!r}; got {obj['score']!r}"
        )
        # Cross-check: the components re-derive to the emitted score.
        sc = obj["score_components"]
        rederived = round(sc["impact"] * sc["urgency"] * sc["confidence"] / sc["effort_weight"], 4)
        assert rederived == round(obj["score"], 4), (
            f"score_components must re-derive to score; {rederived} != {obj['score']}"
        )


# ===========================================================================
# Behavior 7 -- gate parity across ALL FOUR decision classes
# ===========================================================================


def test_behavior7_gate_parity_auto_dispatch(tmp_path, capsys):
    settings = Settings.from_env()
    goal = _auto_goal()
    slate = _write_slate(tmp_path, goal)
    d = gate(goal, settings)
    assert (d.decision.value, d.reason) == ("auto_dispatch", _REASON_AUTO), (
        f"fixture must land in the auto-dispatch branch under this env; got {d.decision.value}/{d.reason!r}"
    )

    rc, obj, _, _ = _explain_json(slate, goal.id, capsys)
    assert rc == 0
    assert obj["decision"] == d.decision.value == "auto_dispatch"
    assert obj["reason"] == d.reason == _REASON_AUTO


def test_behavior7_gate_parity_below_threshold(tmp_path, capsys):
    settings = Settings.from_env()
    goal = _below_goal()
    slate = _write_slate(tmp_path, goal)
    d = gate(goal, settings)
    assert (d.decision.value, d.reason) == ("needs_approval", _REASON_BELOW), (
        f"fixture must land below threshold under this env; got {d.decision.value}/{d.reason!r}"
    )

    rc, obj, _, _ = _explain_json(slate, goal.id, capsys)
    assert rc == 0
    assert obj["decision"] == d.decision.value == "needs_approval"
    assert obj["reason"] == d.reason == _REASON_BELOW


def test_behavior7_gate_parity_sensitive_even_at_max_score(tmp_path, capsys):
    settings = Settings.from_env()
    goal = _sensitive_goal()
    slate = _write_slate(tmp_path, goal)
    d = gate(goal, settings)
    # Sensitivity is checked FIRST -- even a maximal score cannot auto-dispatch.
    assert goal.score >= settings.auto_dispatch_min_score, "fixture must have a maximal (>= threshold) score"
    assert (d.decision.value, d.reason) == ("needs_approval", _REASON_SENSITIVE)

    rc, obj, _, _ = _explain_json(slate, goal.id, capsys)
    assert rc == 0
    assert obj["decision"] == d.decision.value == "needs_approval"
    assert obj["reason"] == d.reason == _REASON_SENSITIVE
    assert obj["category"] == "finance_legal"


def test_behavior7_gate_parity_blocked_not_appropriate(tmp_path, capsys):
    settings = Settings.from_env()
    goal = _blocked_goal()
    slate = _write_slate(tmp_path, goal)
    d = gate(goal, settings)
    assert (d.decision.value, d.reason) == ("blocked", _REASON_BLOCKED)

    rc, obj, _, _ = _explain_json(slate, goal.id, capsys)
    assert rc == 0
    assert obj["decision"] == d.decision.value == "blocked"
    assert obj["reason"] == d.reason == _REASON_BLOCKED
    assert obj["appropriate_now"] is False


# ===========================================================================
# Behavior 8 -- auto_dispatch_threshold echoes the effective setting
# ===========================================================================


def test_behavior8_threshold_echoes_default(tmp_path, capsys):
    settings = Settings.from_env()
    goal = _auto_goal()
    slate = _write_slate(tmp_path, goal)

    rc, obj, _, _ = _explain_json(slate, goal.id, capsys)
    assert rc == 0
    assert obj["auto_dispatch_threshold"] == settings.auto_dispatch_min_score
    assert obj["auto_dispatch_threshold"] == 4.0  # documented default


def test_behavior8_threshold_reflects_env_override(tmp_path, capsys, monkeypatch):
    # The emitted threshold must resolve through the SAME _settings seam every
    # verb uses -- so a PLA_AUTO_DISPATCH_MIN_SCORE override is reflected.
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "2.5")
    settings = Settings.from_env()
    assert settings.auto_dispatch_min_score == 2.5

    goal = _auto_goal()
    slate = _write_slate(tmp_path, goal)
    rc, obj, _, _ = _explain_json(slate, goal.id, capsys)
    assert rc == 0
    assert obj["auto_dispatch_threshold"] == 2.5, (
        f"threshold must reflect the env override; got {obj['auto_dispatch_threshold']!r}"
    )
    # And the decision still agrees with gate() under the overridden settings.
    assert obj["decision"] == gate(goal, settings).decision.value


# ===========================================================================
# Behavior 9 -- list fields are JSON arrays, [] when empty; scalar types right
# ===========================================================================


def test_behavior9_lists_are_arrays_nonempty(tmp_path, capsys):
    goal = _auto_goal()  # has non-empty sources + steps
    slate = _write_slate(tmp_path, goal)

    rc, obj, _, _ = _explain_json(slate, goal.id, capsys)
    assert rc == 0
    assert isinstance(obj["sources"], list) and obj["sources"] == goal.sources
    assert isinstance(obj["suggested_first_steps"], list)
    assert obj["suggested_first_steps"] == goal.suggested_first_steps
    # Scalar types.
    assert isinstance(obj["appropriate_now"], bool)
    assert isinstance(obj["rationale"], str) and obj["rationale"] == goal.rationale
    assert isinstance(obj["title"], str) and obj["title"] == goal.title
    assert isinstance(obj["id"], str) and obj["id"] == goal.id


def test_behavior9_empty_lists_are_empty_arrays_not_none_marker(tmp_path, capsys):
    goal = _empty_provenance_goal()
    slate = _write_slate(tmp_path, goal)

    rc, obj, out, _ = _explain_json(slate, goal.id, capsys)
    assert rc == 0
    assert obj["sources"] == [], f"empty sources must serialize as []; got {obj['sources']!r}"
    assert obj["suggested_first_steps"] == [], (
        f"empty steps must serialize as []; got {obj['suggested_first_steps']!r}"
    )
    # The human '(none)' marker must NOT appear in the JSON form.
    assert "(none)" not in out, f"JSON form must not emit the human (none) marker; got:\n{out}"


# ===========================================================================
# Behavior 10 -- builds NO LLMClient (offline inspector proof)
# ===========================================================================


def test_behavior10_builds_no_llm_client_sys_modules(tmp_path, capsys):
    goal = _auto_goal()
    slate = _write_slate(tmp_path, goal)

    # Drop any pre-existing SDK entries first (mirrors tests/test_providers.py),
    # then run explain --json and assert none reappeared.
    for name in list(sys.modules):
        if name.split(".")[0] in _SDK_MODULES:
            del sys.modules[name]

    rc, obj, _, _ = _explain_json(slate, goal.id, capsys)
    assert rc == 0

    leaked = [m for m in _SDK_MODULES if m in sys.modules]
    assert leaked == [], f"explain --json must build no LLMClient; leaked SDK imports: {leaked}"


def test_behavior10_provider_flags_accepted_but_inert(tmp_path, capsys):
    # --provider / --scripted-responses remain accepted-but-inert globals: a
    # BOGUS scripted-responses path would fault any verb that builds a client,
    # so exit 0 proves explain --json constructs none.
    goal = _auto_goal()
    slate = _write_slate(tmp_path, goal)

    rc, obj, out, err = _explain_json(
        slate, goal.id, capsys,
        extra=["--provider", "scripted", "--scripted-responses", "/no/such/file.json"],
    )
    assert rc == 0, f"explain --json must ignore provider config, got {rc}; stderr:\n{err}"
    assert set(obj) == _EXPECTED_KEYS


# ===========================================================================
# Behavior 11 -- exit-code contract is UNCHANGED by --json (guards run first)
# ===========================================================================


def test_behavior11_missing_slate_file_exit2_with_json(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    assert not missing.exists()

    rc, out, err = _run(["explain", "--slate", str(missing), "--goal-id", "x", "--json"], capsys)
    assert rc == 2, f"missing slate must exit 2 even with --json, got {rc}"
    assert out == "", f"nothing must be printed to stdout before a guard fails; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error: slate file not found:"), (
        f"stderr must begin with 'error: slate file not found:'; got:\n{err!r}"
    )
    assert str(missing) in err
    assert _TRACEBACK not in err


def test_behavior11_unknown_goal_id_exit2_with_json(tmp_path, capsys):
    slate = _write_slate(tmp_path, _auto_goal())

    rc, out, err = _run(
        ["explain", "--slate", str(slate), "--goal-id", "does-not-exist", "--json"], capsys
    )
    assert rc == 2, f"unknown goal id must exit 2 even with --json, got {rc}"
    assert out == "", f"nothing must be printed to stdout on the guard; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error: goal id "), (
        f"stderr must begin with 'error: goal id '; got:\n{err!r}"
    )
    assert "does-not-exist" in err and "not found in slate" in err
    assert _TRACEBACK not in err


def test_behavior11_corrupt_slate_json_exit1_with_json(tmp_path, capsys):
    bad = tmp_path / "corrupt.json"
    bad.write_text("{ not json")

    rc, out, err = _run(["explain", "--slate", str(bad), "--goal-id", "x", "--json"], capsys)
    assert rc == 1, f"corrupt slate must exit 1 via the main() boundary even with --json, got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error:"), (
        f"stderr's first line must begin with 'error:'; got:\n{err!r}"
    )
    assert _TRACEBACK not in err, f"corrupt slate must not print a traceback; got:\n{err!r}"


# ===========================================================================
# Backward-compat -- additive flag, no version bump
# ===========================================================================


def test_no_version_bump_additive_flag():
    import proactive_loop
    assert proactive_loop.__version__ == "0.1.1", (
        "explain --json is an additive, backward-compatible flag -- no version bump"
    )
