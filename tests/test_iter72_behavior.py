"""Black-box behavior tests for iteration 72 (foundry state dir iter-62).

Feature under test: make ``pla explain --goal-id`` OPTIONAL. When ``--goal-id``
is omitted (``--slate`` still required), ``explain`` audits EVERY ranked goal's
gate decision in one pass:

* human render -> one audit block per goal in ``GoalSlate.ranked()`` order,
  separated by a single blank line;
* ``--json`` -> a JSON **array** of the per-goal 12-key objects in ranked order.

This is a backward-compatible WIDENING: the single-goal path (``--goal-id`` given)
stays byte-identical, and an input that used to be an argparse usage error
(omitting ``--goal-id``) becomes a useful exit-0 whole-slate audit. It makes the
flagship LLM-free autonomy-gate auditor slate-complete like its sibling
inspectors (``scan`` / ``signals`` / ``policy`` / ``diff``).

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's PM spec "Expected Behaviors", ``README.md``,
and ``SPEC.md`` (the public design contract, esp. S4.3 gate rules and S4.5 the
``explain`` verb doc) -- and drive only the documented public surface: the ``pla``
CLI via ``proactive_loop.cli.main([...])`` (capturing stdout/stderr + exit code),
the public models ``CandidateGoal`` / ``GoalSlate`` (incl. the public
``GoalSlate.ranked()`` ordering the spec references), the public autonomy gate
``proactive_loop.scout.gate(goal, settings)``, and
``proactive_loop.config.Settings.from_env()``. NO file under ``src/`` was read,
NO engineer/reviewer notes (state-dir ``*.md`` / ``*.log``) were read, and NO
``git diff`` was consulted. Ranked order and per-goal expectations are DERIVED at
runtime from the public models/gate (never hard-coded against an implementation
quirk), so the tests survive a threshold/fixture change. The whole-slate outputs
are proven equal to the (unchanged) single-goal outputs re-run per goal -- i.e.
the tests never encode the renderer's internal formatting, only the public
"whole-slate == the per-goal audit repeated in ranked order" contract. Every
test uses a fresh ``tmp_path`` slate file (never the repo's ``.pla_runs/``) and
runs fully offline -- zero network, zero API keys, only in-memory fixtures.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.models import CandidateGoal, GoalSlate
from proactive_loop.scout import gate

_TRACEBACK = "Traceback (most recent call last)"

# The 12 top-level contract keys (the existing ``_explain_json_payload`` schema).
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

# Pull the goal id out of a human audit header line: ``goal ... (id=<ID>)``.
_ID_RE = re.compile(r"\(id=([^)]+)\)")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _write_slate(tmp_path: Path, *goals: CandidateGoal, name: str = "slate.json") -> Path:
    """Write an in-memory GoalSlate of the given goals to a tmp slate file."""
    slate = GoalSlate(workspace_root=str(tmp_path), goals=list(goals))
    path = tmp_path / name
    path.write_text(slate.model_dump_json())
    return path


def _load_ranked(slate_path: Path) -> list[CandidateGoal]:
    """The public ranked ordering the spec references: appropriate_now desc,
    then score desc."""
    return GoalSlate.model_validate_json(slate_path.read_text()).ranked()


# --- Goal fixtures spanning each gate branch (default threshold 4.0) --------
# Chosen so ranked() order (appropriate_now desc, score desc) is NON-TRIVIAL
# (differs from insertion order): ranked -> [sensitive(25,appr), auto(18,appr),
# below(2.4,appr), blocked(25,NOT-appr)].


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
    # non-sensitive but appropriate_now=False -> blocked; empty provenance too.
    return CandidateGoal(
        title="Plan the Q4 career move",
        rationale="not the right moment to act on this",
        category="career",
        impact=5.0, urgency=5.0, confidence=1.0, effort_weight=1.0,
        appropriate_now=False,
        sources=[],
        suggested_first_steps=[],
    )


def _multi_slate(tmp_path: Path) -> Path:
    """A 4-goal slate spanning all four gate outcomes; ranked order is
    non-trivial (differs from insertion order)."""
    return _write_slate(
        tmp_path,
        _auto_goal(), _below_goal(), _sensitive_goal(), _blocked_goal(),
    )


# ===========================================================================
# Behavior 1 -- single-goal path is UNCHANGED (regression)
# ===========================================================================


def test_behavior1_single_goal_human_block_unchanged(tmp_path, capsys):
    slate = _multi_slate(tmp_path)
    ranked = _load_ranked(slate)

    for g in ranked:
        rc, out, err = _run(["explain", "--slate", str(slate), "--goal-id", g.id], capsys)
        assert rc == 0, f"single-goal explain must exit 0, got {rc}; stderr:\n{err}"
        # A self-describing human block (NOT a JSON doc) with the goal's identity.
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)
        assert g.title in out and g.id in out
        assert g.category.value in out
        assert "GoalCategory." not in out, f"category enum repr leaked:\n{out}"
        # Deterministic: a second run on the unchanged slate is byte-identical.
        _, out2, _ = _run(["explain", "--slate", str(slate), "--goal-id", g.id], capsys)
        assert out == out2, "single-goal explain must be byte-identical across runs"


def test_behavior1_single_goal_json_is_one_object_not_a_list(tmp_path, capsys):
    slate = _multi_slate(tmp_path)
    ranked = _load_ranked(slate)

    for g in ranked:
        rc, out, err = _run(
            ["explain", "--slate", str(slate), "--goal-id", g.id, "--json"], capsys
        )
        assert rc == 0, f"single-goal explain --json must exit 0, got {rc}; stderr:\n{err}"
        obj = json.loads(out)
        # Load-bearing: single goal-id = exactly ONE object, NOT an array.
        assert isinstance(obj, dict), (
            f"single-goal --json must be one object (dict), not a list; got {type(obj).__name__}"
        )
        assert set(obj) == _EXPECTED_KEYS, (
            f"single-goal --json must carry exactly the 12 contract keys; "
            f"got {sorted(obj)}"
        )
        assert obj["id"] == g.id and obj["title"] == g.title


# ===========================================================================
# Behavior 2 -- whole-slate human audits every goal in ranked order
# ===========================================================================


def test_behavior2_whole_slate_human_audits_all_goals_in_ranked_order(tmp_path, capsys):
    slate = _multi_slate(tmp_path)
    ranked = _load_ranked(slate)
    n = len(ranked)
    assert n >= 2, "this behavior needs a slate with N >= 2 goals"

    rc, out, err = _run(["explain", "--slate", str(slate)], capsys)
    assert rc == 0, f"whole-slate explain must exit 0, got {rc}; stderr:\n{err}"
    assert err == "", f"nothing must go to stderr on the happy path; got:\n{err!r}"

    # One audit block per goal: count the header lines (they begin with 'goal'
    # and carry the '(id=...)' tag).
    header_lines = [ln for ln in out.splitlines() if ln.startswith("goal") and "(id=" in ln]
    assert len(header_lines) == n, (
        f"whole-slate human must print one goal-header line per goal (N={n}); "
        f"got {len(header_lines)}:\n{out}"
    )
    # The ids appear in ranked() order.
    printed_ids = _ID_RE.findall(out)
    assert printed_ids == [g.id for g in ranked], (
        f"goal ids must appear in ranked() order; got {printed_ids} vs "
        f"{[g.id for g in ranked]}"
    )
    # Blocks are separated by a SINGLE blank line -- never a double blank.
    assert "\n\n\n" not in out, f"blocks must be separated by ONE blank line; got:\n{out}"
    # Splitting the (trailing-stripped) output on a blank line yields N blocks.
    blocks = out.rstrip("\n").split("\n\n")
    assert len(blocks) == n, f"whole-slate output must split into N={n} blocks; got {len(blocks)}"


# ===========================================================================
# Behavior 3 -- whole-slate human == the single-goal blocks concatenated
# ===========================================================================


def test_behavior3_whole_slate_human_equals_concatenated_single_blocks(tmp_path, capsys):
    slate = _multi_slate(tmp_path)
    ranked = _load_ranked(slate)

    _, whole, _ = _run(["explain", "--slate", str(slate)], capsys)

    # Re-run the (unchanged) single-goal audit per goal in ranked order.
    singles: list[str] = []
    for g in ranked:
        rc, block, _ = _run(["explain", "--slate", str(slate), "--goal-id", g.id], capsys)
        assert rc == 0
        singles.append(block)

    # Each single-goal block's content appears VERBATIM inside the whole output.
    for block in singles:
        assert block.rstrip("\n") in whole, (
            "each single-goal block must appear byte-identically in the whole-slate output"
        )

    # And the whole-slate human is EXACTLY the per-goal blocks joined by a blank
    # line (no new rendering): the whole-slate audit is just the per-goal audit
    # repeated in ranked order.
    reconstructed = "\n\n".join(b.rstrip("\n") for b in singles) + "\n"
    assert whole == reconstructed, (
        "whole-slate human must equal the ranked single-goal blocks joined by a "
        f"blank line.\n--- whole (tail) ---\n{whole[-120:]!r}\n"
        f"--- reconstructed (tail) ---\n{reconstructed[-120:]!r}"
    )


# ===========================================================================
# Behavior 4 -- whole-slate --json is an ARRAY of 12-key objects in ranked order
# ===========================================================================


def test_behavior4_whole_slate_json_is_ranked_array_of_12key_objects(tmp_path, capsys):
    slate = _multi_slate(tmp_path)
    ranked = _load_ranked(slate)
    n = len(ranked)

    rc, out, err = _run(["explain", "--slate", str(slate), "--json"], capsys)
    assert rc == 0, f"whole-slate --json must exit 0, got {rc}; stderr:\n{err}"
    assert err == "", f"nothing must go to stderr on the happy path; got:\n{err!r}"

    arr = json.loads(out)
    # Load-bearing object-vs-array contract: whole-slate = a JSON ARRAY.
    assert isinstance(arr, list), (
        f"whole-slate --json must be a JSON array, not an object; got {type(arr).__name__}"
    )
    assert len(arr) == n, f"array length must equal N={n}; got {len(arr)}"

    # Each element is a 12-key object; array is in ranked() order.
    for i, (elem, g) in enumerate(zip(arr, ranked)):
        assert isinstance(elem, dict), f"array element {i} must be an object"
        assert set(elem) == _EXPECTED_KEYS, (
            f"element {i} must carry exactly the 12 contract keys; got {sorted(elem)}"
        )
        assert elem["id"] == g.id, f"element {i} must be ranked goal {i} (id order)"


def test_behavior4_array_element_equals_single_goal_json_object(tmp_path, capsys):
    slate = _multi_slate(tmp_path)
    ranked = _load_ranked(slate)

    _, whole_out, _ = _run(["explain", "--slate", str(slate), "--json"], capsys)
    arr = json.loads(whole_out)

    for i, g in enumerate(ranked):
        _, single_out, _ = _run(
            ["explain", "--slate", str(slate), "--goal-id", g.id, "--json"], capsys
        )
        single_obj = json.loads(single_out)
        assert arr[i] == single_obj, (
            f"whole-slate array element {i} must equal the single-goal --json object "
            f"for ranked goal {g.id} (no schema drift)"
        )


# ===========================================================================
# Behavior 5 -- empty slate (0 goals)
# ===========================================================================


def test_behavior5_empty_slate_human_prints_exactly_no_goals_marker(tmp_path, capsys):
    slate = _write_slate(tmp_path)  # zero goals

    rc, out, err = _run(["explain", "--slate", str(slate)], capsys)
    assert rc == 0, f"empty-slate explain must exit 0, got {rc}; stderr:\n{err}"
    assert err == "", f"nothing must go to stderr; got:\n{err!r}"
    # Exactly the marker and nothing else.
    non_empty = [ln for ln in out.splitlines() if ln.strip()]
    assert non_empty == ["(no goals in slate)"], (
        f"empty-slate human must print exactly '(no goals in slate)'; got:\n{out!r}"
    )
    assert out.strip() == "(no goals in slate)"


def test_behavior5_empty_slate_json_is_empty_array(tmp_path, capsys):
    slate = _write_slate(tmp_path)  # zero goals

    rc, out, err = _run(["explain", "--slate", str(slate), "--json"], capsys)
    assert rc == 0, f"empty-slate --json must exit 0, got {rc}; stderr:\n{err}"
    parsed = json.loads(out)
    assert parsed == [], f"empty-slate --json must be []; got {parsed!r}"
    assert isinstance(parsed, list)


# ===========================================================================
# Behavior 6 -- missing slate file -> exit 2 via the HANDLER guard, not argparse
# ===========================================================================


def test_behavior6_missing_slate_no_goal_id_exits_2_via_handler_guard(tmp_path, capsys):
    missing = tmp_path / "does-not-exist.json"
    assert not missing.exists()

    # No --goal-id: this used to be an argparse usage error; now it reaches the
    # handler's missing-file guard (exit 2), NOT a parse-time SystemExit.
    rc, out, err = _run(["explain", "--slate", str(missing)], capsys)
    assert rc == 2, f"missing slate file with no --goal-id must exit 2 (handler guard), got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    assert f"error: slate file not found: {missing}" in err, (
        f"stderr must be the handler's not-found line; got:\n{err!r}"
    )
    assert "usage:" not in err, f"must NOT be an argparse usage error; got:\n{err!r}"
    assert _TRACEBACK not in err, f"handler guard must not traceback; got:\n{err!r}"


# ===========================================================================
# Behavior 7 -- corrupt slate -> exit 1 (sanitized); --slate stays REQUIRED
# ===========================================================================


def test_behavior7_corrupt_slate_no_goal_id_exits_1_sanitized(tmp_path, capsys):
    bad = tmp_path / "corrupt.json"
    bad.write_text("{ not json")

    rc, out, err = _run(["explain", "--slate", str(bad)], capsys)
    assert rc == 1, f"corrupt slate (no --goal-id) must exit 1 via main() boundary, got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error:"), (
        f"stderr's first line must begin with 'error:'; got:\n{err!r}"
    )
    # Sanitized: no traceback, no leaked pydantic model class names.
    assert _TRACEBACK not in err, f"corrupt slate must NOT print a traceback; got:\n{err!r}"
    for leaked in ("CandidateGoal", "GoalSlate", "pydantic"):
        assert leaked not in err, f"{leaked!r} must not leak into the sanitized error; got:\n{err!r}"


def test_behavior7_schema_invalid_slate_no_goal_id_exits_1_sanitized(tmp_path, capsys):
    # Valid JSON, invalid slate SCHEMA (a bare list, not a GoalSlate object).
    bad = tmp_path / "schema_invalid.json"
    bad.write_text("[1, 2, 3]")

    rc, out, err = _run(["explain", "--slate", str(bad)], capsys)
    assert rc == 1, f"schema-invalid slate (no --goal-id) must exit 1, got {rc}"
    assert out == "", f"nothing must be printed to stdout; got:\n{out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert err_lines and err_lines[0].startswith("error:"), (
        f"stderr's first line must begin with 'error:'; got:\n{err!r}"
    )
    assert _TRACEBACK not in err, f"schema-invalid slate must NOT traceback; got:\n{err!r}"


def test_behavior7_missing_slate_flag_is_still_argparse_usage_error(capsys):
    # --slate remains REQUIRED: `explain` with no --slate (with or without
    # --goal-id) is still an argparse usage error (nonzero, usage: on stderr).
    for argv in (["explain"], ["explain", "--goal-id", "x"]):
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code not in (0, None), (
            f"missing --slate ({argv}) must be a nonzero usage error, got {excinfo.value.code!r}"
        )
        err = capsys.readouterr().err
        assert "usage:" in err, f"missing --slate ({argv}) must print usage; got:\n{err!r}"
        assert "--slate" in err, f"usage error must name the required --slate; got:\n{err!r}"
        assert _TRACEBACK not in err, f"argparse error must not traceback; got:\n{err!r}"


# ===========================================================================
# Backward-compat -- optional --goal-id is additive, no version bump
# ===========================================================================


def test_no_version_bump_additive_widening():
    import proactive_loop
    assert proactive_loop.__version__ == "0.1.1", (
        "making --goal-id optional is an additive, backward-compatible widening -- no version bump"
    )


def test_explain_help_documents_optional_goal_id_and_still_required_slate(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["explain", "--help"])
    assert excinfo.value.code == 0, "`pla explain --help` must exit 0"
    out = capsys.readouterr().out
    assert "--slate" in out and "--goal-id" in out, f"help must document both options; got:\n{out}"
    # --goal-id renders as OPTIONAL (bracketed) in the usage line; --slate does not.
    assert "[--goal-id" in out, f"help usage must show --goal-id as optional; got:\n{out}"
