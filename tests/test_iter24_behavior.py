"""Black-box behavior tests for iteration 24 --- the ``pla diff`` verb.

Feature under test: ``pla diff --old A.json --new B.json [--json]`` --- a
read-only, LLM-free slate-delta inspector (the comparative companion to
``watch``). It matches goals across two saved slates by NORMALIZED TITLE
(``title.strip().lower()`` --- the synthesizer's own dedup key, NEVER the random
per-scan ``CandidateGoal.id``; first-occurrence-wins on an intra-slate duplicate
title), re-gates each side LIVE with the SAME ``gate(goal, settings)`` seam, and
classifies every goal as **added** (title in NEW only), **removed** (in OLD
only), **changed** (in BOTH with ``abs(new_score - old_score) > 1e-9`` OR a
flipped gate decision), or **unchanged** (count only). Human form prints only
the non-empty ``+ added`` / ``- removed`` / ``~ changed`` sections (rows
title-ascending) then an ``unchanged: <N>`` trailer, degrading to a single
``(no differences)`` line when the three delta buckets are empty. ``--json``
emits one object of EXACTLY six top-level keys. Builds no ``LLMClient``, runs no
collector/subprocess, and writes no file.

ISOLATION CONTRACT (honored): these tests are written strictly against this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` sections 4.5/4.3 --- and drive ONLY documented
public surfaces: the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int``
(its observable stdout / stderr / exit codes / on-disk artifacts) plus the
public model/gate/config seams (``proactive_loop.models.{CandidateGoal,
GoalSlate}``, ``proactive_loop.scout.gate``, ``proactive_loop.config.Settings``)
used ONLY as the oracle for expected gate decisions and scores --- exactly as
tests/test_iter22_behavior.py does. **No file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted.** Every
test is fully offline: zero network, zero API keys, driven through the scripted
provider seam; slate fixtures are hand-built in ``tmp_path`` (never the repo's
own tree or ``.pla_runs/``).

NOTE (PM feedback / ambiguity, behaviors 6-7): ``CandidateGoal.score`` is a
computed field ROUNDED TO 4 DECIMALS. The score quantum (1e-4) is far coarser
than the ``1e-9`` epsilon, so in practice the epsilon can never sit strictly
between two distinct persisted scores --- it is a float-representation
robustness guard, and "score-changed" reduces to "scores differ at the 4th
decimal". These tests therefore exercise the two reachable regimes: EXACTLY
equal scores (diff 0, well within epsilon -> unchanged) and scores that differ
at the 4-decimal level (>> 1e-9 -> changed). A strictly-within-epsilon-but-
nonzero score delta is unconstructable through the public slate schema.
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

_TRACEBACK = "Traceback (most recent call last)"
_NO_DIFF = "(no differences)"

# The SIX top-level keys the spec (behavior 12) mandates -- no more, no fewer.
_JSON_KEYS = {"old", "new", "added", "removed", "changed", "unchanged_count"}

# SDK modules whose absence proves the offline guarantee (no LLMClient built).
_SDK_MODULES = ("anthropic", "openai", "boto3")


# ---------------------------------------------------------------------------
# Helpers -- all black-box: hand-build GoalSlate JSON fixtures, drive main(),
# read back stdout / stderr / exit code / on-disk artifacts.
# ---------------------------------------------------------------------------


def _goal(
    title: str,
    *,
    category: str = "learning",
    impact: float = 5.0,
    urgency: float = 4.0,
    confidence: float = 0.9,
    effort_weight: float = 1.0,
    appropriate_now: bool = True,
) -> CandidateGoal:
    """One goal. Defaults score = 5*4*0.9/1 = 18.0 (>= 4.0 threshold),
    non-sensitive, appropriate -> auto_dispatch. Each call gets a FRESH random
    ``id`` (the default_factory) so same-title goals across slates carry
    different ids -- the crux of the behavior-3 id-match regression."""
    return CandidateGoal(
        title=title,
        rationale="black-box diff probe",
        category=category,
        impact=impact,
        urgency=urgency,
        confidence=confidence,
        effort_weight=effort_weight,
        appropriate_now=appropriate_now,
        sources=[],
        suggested_first_steps=["do a thing"],
    )


def _write_slate(tmp_path: Path, *goals: CandidateGoal, name: str) -> Path:
    """Write an in-memory GoalSlate to a tmp slate file, mirroring scan's
    ``_write_slate`` (``model_dump_json(indent=2)``)."""
    slate = GoalSlate(workspace_root=str(tmp_path), goals=list(goals))
    path = tmp_path / name
    path.write_text(slate.model_dump_json(indent=2), encoding="utf-8")
    return path


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _diff(old: Path, new: Path, capsys, *, as_json: bool = False, extra=None):
    argv = ["diff", "--old", str(old), "--new", str(new)]
    if as_json:
        argv.append("--json")
    if extra:
        argv += extra
    return _run(argv, capsys)


def _dec(goal: CandidateGoal) -> str:
    """The live gate decision .value under the default settings -- the oracle."""
    return gate(goal, Settings.from_env()).decision.value


# ===========================================================================
# Behavior 1 -- subcommand exists; runs exit 0 on two valid slates; the shared
# global flags are accepted but inert.
# ===========================================================================


def test_behavior1_diff_runs_exit0_on_two_valid_slates(tmp_path, capsys):
    old = _write_slate(tmp_path, _goal("Learn RAG"), name="old.json")
    new = _write_slate(tmp_path, _goal("Learn RAG"), name="new.json")
    rc, out, err = _diff(old, new, capsys)
    assert rc == 0, f"diff on two valid slates must exit 0, got {rc}; stderr:\n{err}"
    assert _TRACEBACK not in err


def test_behavior1_global_flags_accepted_but_inert(tmp_path, capsys):
    # --provider/--scripted-responses/--state-dir are inherited but inert: a
    # BOGUS scripted-responses path + a non-scripted provider would fault any
    # verb that builds a client, so exit 0 proves diff constructs none.
    old = _write_slate(tmp_path, _goal("Learn RAG"), name="old.json")
    new = _write_slate(tmp_path, _goal("Learn RAG"), name="new.json")
    state = tmp_path / "state_dir"
    rc, out, err = _diff(
        old, new, capsys,
        extra=["--provider", "anthropic",
               "--scripted-responses", "/no/such/file.json",
               "--state-dir", str(state)],
    )
    assert rc == 0, f"diff must ignore provider config, got {rc}; stderr:\n{err}"
    # The inert --state-dir must not be materialized by a read-only verb.
    assert not state.exists(), "diff must not create the (inert) --state-dir"


# ===========================================================================
# Behavior 2 -- a `diff` invocation MUST name a selector: both --old and --new,
# or --dir. The ENFORCEMENT MECHANISM moved in the `diff --dir` iteration --
# argparse cannot express "either (--old AND --new) or --dir", so `_cmd_diff`
# now rejects a missing selector itself and RETURNS 2 instead of argparse
# raising SystemExit. The observable contract these two tests exist to pin is
# unchanged, and is what they assert: exit 2, empty stdout, exactly one
# `error: ` line on stderr naming the option, no traceback.
# --json is an optional store_true defaulting off.
# ===========================================================================


def _assert_usage_error(rc: int, out: str, err: str, names: str) -> None:
    """Pin the exit-2 usage contract: rc 2, silent stdout, ONE `error:` line."""
    assert rc == 2, f"a missing selector must exit 2, got {rc}; stderr:\n{err}"
    assert out == "", f"a usage error must print nothing on stdout; got:\n{out!r}"
    lines = err.splitlines()
    assert len(lines) == 1, f"expected exactly one stderr line; got:\n{err!r}"
    assert lines[0].startswith("error: "), f"stderr must be an `error: ` line; got:\n{err!r}"
    assert names in err, f"usage error must name {names}; got:\n{err!r}"
    assert _TRACEBACK not in err


def test_behavior2_old_is_required(tmp_path, capsys):
    new = _write_slate(tmp_path, _goal("A"), name="new.json")
    rc, out, err = _run(["diff", "--new", str(new)], capsys)
    _assert_usage_error(rc, out, err, "--old")


def test_behavior2_new_is_required(tmp_path, capsys):
    old = _write_slate(tmp_path, _goal("A"), name="old.json")
    rc, out, err = _run(["diff", "--old", str(old)], capsys)
    _assert_usage_error(rc, out, err, "--new")


def test_behavior2_json_defaults_off(tmp_path, capsys):
    # Without --json the human render is used: identical slates -> the human
    # marker line, never a JSON object.
    old = _write_slate(tmp_path, _goal("A"), name="old.json")
    new = _write_slate(tmp_path, _goal("A"), name="new.json")
    rc, out, err = _diff(old, new, capsys)
    assert rc == 0
    assert out.strip() == _NO_DIFF, f"default (no --json) must render the human marker; got:\n{out!r}"
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


# ===========================================================================
# Behavior 3 -- matching by NORMALIZED TITLE, never by id; intra-slate
# first-occurrence-wins on a duplicate normalized title.
# ===========================================================================


def test_behavior3_id_match_trap_regression(tmp_path, capsys):
    # Two slates with the SAME titles/scores/categories but freshly-random ids.
    # An id-based match would report every goal as both added AND removed; a
    # title-based match reports 0 added / 0 removed (all unchanged).
    titles = ["Learn RAG", "Refactor the parser", "Write a design doc"]
    old = _write_slate(tmp_path, *[_goal(t) for t in titles], name="old.json")
    new = _write_slate(tmp_path, *[_goal(t) for t in titles], name="new.json")
    # ids genuinely differ across the two slates.
    old_ids = {g.id for g in GoalSlate.model_validate_json(old.read_text()).goals}
    new_ids = {g.id for g in GoalSlate.model_validate_json(new.read_text()).goals}
    assert old_ids.isdisjoint(new_ids), "fixture precondition: ids must differ across slates"

    rc, obj, out, err = _diff_json(old, new, capsys)
    assert rc == 0
    assert obj["added"] == [], f"id-match trap: added must be empty; got {obj['added']}"
    assert obj["removed"] == [], f"id-match trap: removed must be empty; got {obj['removed']}"
    assert obj["changed"] == [], f"id-match trap: changed must be empty; got {obj['changed']}"
    assert obj["unchanged_count"] == 3


def test_behavior3_normalized_title_matches_case_and_whitespace(tmp_path, capsys):
    # "  Learn RAG  " (OLD) and "learn rag" (NEW) normalize to the same key and
    # carry an identical score/decision -> one unchanged goal, zero deltas.
    old = _write_slate(tmp_path, _goal("  Learn RAG  "), name="old.json")
    new = _write_slate(tmp_path, _goal("learn rag"), name="new.json")
    rc, obj, out, err = _diff_json(old, new, capsys)
    assert rc == 0
    assert obj["added"] == [] and obj["removed"] == [] and obj["changed"] == []
    assert obj["unchanged_count"] == 1


def test_behavior3_first_occurrence_wins_within_slate(tmp_path, capsys):
    # NEW holds two goals sharing normalized title "dup": the FIRST (score 18.0)
    # matches OLD's score 18.0 -> unchanged. If last-wins were used the second
    # (score 12.0) would land the pair in changed. Assert first-wins.
    old = _write_slate(tmp_path, _goal("dup"), name="old.json")  # score 18.0
    first = _goal("Dup")  # normalizes to "dup"; score 18.0 (matches OLD)
    second = _goal("dup", urgency=2.0)  # score 5*2*0.9 = 9.0 (would differ)
    new = _write_slate(tmp_path, first, second, name="new.json")
    rc, obj, out, err = _diff_json(old, new, capsys)
    assert rc == 0
    assert obj["changed"] == [], (
        f"first-occurrence-wins: the pair must be unchanged, not changed; got {obj['changed']}"
    )
    assert obj["added"] == [] and obj["removed"] == []
    assert obj["unchanged_count"] == 1


# ===========================================================================
# Behaviors 4 & 5 -- added (NEW only) and removed (OLD only).
# ===========================================================================


def test_behavior4_added_is_new_only(tmp_path, capsys):
    old = _write_slate(tmp_path, _goal("Keeper"), name="old.json")
    new = _write_slate(tmp_path, _goal("Keeper"), _goal("Fresh arrival"), name="new.json")
    rc, obj, out, err = _diff_json(old, new, capsys)
    assert rc == 0
    assert [a["title"] for a in obj["added"]] == ["Fresh arrival"]
    assert obj["removed"] == []
    assert obj["unchanged_count"] == 1


def test_behavior5_removed_is_old_only(tmp_path, capsys):
    old = _write_slate(tmp_path, _goal("Keeper"), _goal("Departed task"), name="old.json")
    new = _write_slate(tmp_path, _goal("Keeper"), name="new.json")
    rc, obj, out, err = _diff_json(old, new, capsys)
    assert rc == 0
    assert [r["title"] for r in obj["removed"]] == ["Departed task"]
    assert obj["added"] == []
    assert obj["unchanged_count"] == 1


# ===========================================================================
# Behaviors 6 & 7 -- changed (score delta > eps OR decision flip); unchanged
# (both within eps AND same decision, count only).
# ===========================================================================


def test_behavior6_changed_by_score_delta(tmp_path, capsys):
    old = _write_slate(tmp_path, _goal("Movable"), name="old.json")  # 18.0
    new_goal = _goal("Movable", urgency=3.0)  # 5*3*0.9 = 13.5 (>> 1e-9 delta)
    new = _write_slate(tmp_path, new_goal, name="new.json")
    rc, obj, out, err = _diff_json(old, new, capsys)
    assert rc == 0
    assert len(obj["changed"]) == 1, f"a score move must land in changed; got {obj}"
    ch = obj["changed"][0]
    assert ch["title"] == "Movable"
    assert ch["old_score"] == 18.0 and ch["new_score"] == 13.5
    assert obj["added"] == [] and obj["removed"] == []
    assert obj["unchanged_count"] == 0


def test_behavior7_unchanged_reports_count_only_never_rows(tmp_path, capsys):
    # Two goals unchanged (identical scores/decisions) + one changed. The
    # unchanged titles must appear NOWHERE in the human output; only the count.
    old = _write_slate(
        tmp_path, _goal("Steady one"), _goal("Steady two"), _goal("Wobbler"),
        name="old.json",
    )
    new = _write_slate(
        tmp_path, _goal("Steady one"), _goal("Steady two"), _goal("Wobbler", urgency=2.0),
        name="new.json",
    )
    rc, out, err = _diff(old, new, capsys)
    assert rc == 0
    assert "unchanged: 2" in out, f"trailer must report the unchanged count; got:\n{out}"
    assert "Steady one" not in out and "Steady two" not in out, (
        f"unchanged goal rows must never be printed; got:\n{out}"
    )
    assert "Wobbler" in out  # the changed one IS shown


# ===========================================================================
# Behavior 8 -- decision flip with UNCHANGED score lands in changed (proves the
# diff re-gates live rather than comparing stored decisions).
# ===========================================================================


def test_behavior8_decision_flip_same_score_is_changed(tmp_path, capsys):
    # OLD: sensitive category (finance_legal) at score 18.0 -> needs_approval.
    # NEW: SAME title & score but non-sensitive (learning) -> auto_dispatch.
    # Score is identical; only the live gate decision flips.
    old_goal = _goal("Ship the release", category="finance_legal")
    new_goal = _goal("Ship the release", category="learning")
    assert old_goal.score == new_goal.score, "fixture: scores must be identical"
    assert _dec(old_goal) == "needs_approval" and _dec(new_goal) == "auto_dispatch"

    old = _write_slate(tmp_path, old_goal, name="old.json")
    new = _write_slate(tmp_path, new_goal, name="new.json")
    rc, obj, out, err = _diff_json(old, new, capsys)
    assert rc == 0
    assert len(obj["changed"]) == 1, (
        f"decision flip at unchanged score must land in changed; got {obj}"
    )
    ch = obj["changed"][0]
    assert ch["old_score"] == ch["new_score"] == 18.0, "score must be unchanged in this bucket"
    assert ch["old_decision"] == "needs_approval" and ch["new_decision"] == "auto_dispatch"
    assert obj["added"] == [] and obj["removed"] == [] and obj["unchanged_count"] == 0


# ===========================================================================
# Behavior 9 -- all-empty deltas -> exactly "(no differences)" (exit 0),
# regardless of unchanged count; empty-vs-empty likewise.
# ===========================================================================


def test_behavior9_identical_slates_no_differences(tmp_path, capsys):
    old = _write_slate(tmp_path, _goal("A"), _goal("B"), _goal("C"), name="old.json")
    new = _write_slate(tmp_path, _goal("A"), _goal("B"), _goal("C"), name="new.json")
    rc, out, err = _diff(old, new, capsys)
    assert rc == 0
    assert out.strip() == _NO_DIFF, (
        f"identical slates must print exactly '(no differences)'; got:\n{out!r}"
    )
    # No trailer line when there are no differences.
    assert "unchanged:" not in out


def test_behavior9_empty_vs_empty_no_differences(tmp_path, capsys):
    old = _write_slate(tmp_path, name="old.json")
    new = _write_slate(tmp_path, name="new.json")
    rc, out, err = _diff(old, new, capsys)
    assert rc == 0
    assert out.strip() == _NO_DIFF, f"empty-vs-empty must print '(no differences)'; got:\n{out!r}"


# ===========================================================================
# Behaviors 10 & 11 -- human render: only non-empty sections, order added ->
# removed -> changed then the unchanged trailer; exact row formats; rows
# title-ascending; un-normalized title source (NEW for added/changed, OLD for
# removed); scores :.2f; decisions as the gate .value.
# ===========================================================================


def test_behavior10_section_order_and_row_formats(tmp_path, capsys):
    # added: "Delta task"; removed: "Gamma task"; changed: "Beta task" (18->12);
    # unchanged: "Alpha task".
    beta_old = _goal("Beta task")               # 18.0
    beta_new = _goal("Beta task", urgency=3.0, confidence=0.8)  # 5*3*0.8 = 12.0
    old = _write_slate(
        tmp_path, _goal("Alpha task"), beta_old, _goal("Gamma task"), name="old.json",
    )
    new = _write_slate(
        tmp_path, _goal("Alpha task"), beta_new, _goal("Delta task"), name="new.json",
    )
    rc, out, err = _diff(old, new, capsys)
    assert rc == 0

    lines = [ln for ln in out.splitlines() if ln.strip()]
    # Section headers present with correct counts.
    assert "+ added (1)" in lines
    assert "- removed (1)" in lines
    assert "~ changed (1)" in lines
    assert lines[-1] == "unchanged: 1", f"last line must be the unchanged trailer; got:\n{out}"

    # Fixed section order: added header before removed header before changed.
    i_add = lines.index("+ added (1)")
    i_rem = lines.index("- removed (1)")
    i_chg = lines.index("~ changed (1)")
    assert i_add < i_rem < i_chg, f"section order must be added->removed->changed; got:\n{out}"

    # Exact documented rows.
    assert "    Delta task  score=18.00  auto_dispatch" in lines, f"added row format; got:\n{out}"
    assert "    Gamma task  score=18.00  auto_dispatch" in lines, f"removed row format; got:\n{out}"
    assert (
        "    Beta task  score 18.00 -> 12.00  decision auto_dispatch -> auto_dispatch" in lines
    ), f"changed row format; got:\n{out}"

    # Unchanged row is never printed.
    assert "Alpha task" not in out


def test_behavior11_rows_sorted_by_normalized_title(tmp_path, capsys):
    # Three added goals in a deliberately unsorted order; rows must come out
    # ascending by normalized title: apple, mango, zebra.
    old = _write_slate(tmp_path, name="old.json")
    new = _write_slate(
        tmp_path, _goal("Zebra"), _goal("apple"), _goal("Mango"), name="new.json",
    )
    rc, out, err = _diff(old, new, capsys)
    assert rc == 0
    lines = [ln for ln in out.splitlines() if ln.strip()]
    row_titles = [ln.split("score=")[0].strip() for ln in lines if "score=" in ln]
    assert row_titles == ["apple", "Mango", "Zebra"], (
        f"added rows must be normalized-title-ascending; got {row_titles}\n{out}"
    )


def test_behavior11_title_source_new_for_changed_old_for_removed(tmp_path, capsys):
    # A changed goal whose OLD/NEW titles differ only by case/whitespace: the
    # displayed title must be the NEW un-normalized form. A removed goal's title
    # comes from OLD.
    old = _write_slate(
        tmp_path, _goal("  learn rag basics  "), _goal("Old Only Task"), name="old.json",
    )
    new = _write_slate(
        tmp_path, _goal("Learn RAG Basics", urgency=3.0), name="new.json",  # score 13.5
    )
    rc, out, err = _diff(old, new, capsys)
    assert rc == 0
    # changed row uses the NEW slate's un-normalized title.
    assert "Learn RAG Basics" in out, f"changed row must use the NEW title; got:\n{out}"
    assert "learn rag basics" not in out, "changed row must not use the OLD (normalized-ish) title"
    # removed row uses the OLD slate's title.
    assert "Old Only Task" in out


# ===========================================================================
# Behaviors 12 & 13 -- --json: one object of EXACTLY six allowlisted keys;
# arrays always present ([] when empty), title-ascending; scores raw numbers;
# decisions .value; old/new echo the path strings; exit contract unaffected.
# ===========================================================================


def test_behavior12_json_exact_key_allowlist_and_shapes(tmp_path, capsys):
    beta_old = _goal("beta")
    beta_new = _goal("beta", urgency=3.0)  # 13.5
    old = _write_slate(tmp_path, _goal("alpha"), beta_old, _goal("gamma"), name="old.json")
    new = _write_slate(tmp_path, _goal("alpha"), beta_new, _goal("delta"), name="new.json")
    rc, obj, out, err = _diff_json(old, new, capsys)
    assert rc == 0
    assert set(obj) == _JSON_KEYS, f"top-level keys must be exactly {_JSON_KEYS}; got {set(obj)}"

    # old/new echo the path strings exactly as passed.
    assert obj["old"] == str(old) and obj["new"] == str(new)

    # added/removed item shape.
    assert obj["added"] == [{"title": "delta", "score": 18.0, "decision": "auto_dispatch"}]
    assert obj["removed"] == [{"title": "gamma", "score": 18.0, "decision": "auto_dispatch"}]

    # changed item shape (five keys), scores raw NUMBERS not ":.2f" strings.
    assert obj["changed"] == [{
        "title": "beta",
        "old_score": 18.0,
        "new_score": 13.5,
        "old_decision": "auto_dispatch",
        "new_decision": "auto_dispatch",
    }]
    for arr in (obj["added"], obj["removed"]):
        for item in arr:
            assert isinstance(item["score"], (int, float)) and not isinstance(item["score"], str)
    for item in obj["changed"]:
        assert isinstance(item["old_score"], (int, float)) and not isinstance(item["old_score"], str)
        assert isinstance(item["new_score"], (int, float)) and not isinstance(item["new_score"], str)

    assert obj["unchanged_count"] == 1 and isinstance(obj["unchanged_count"], int)
    # No enum repr leaked (iter-08 discipline).
    assert "AutonomyDecision." not in out and "GoalCategory." not in out


def test_behavior12_empty_buckets_are_json_arrays_not_markers(tmp_path, capsys):
    old = _write_slate(tmp_path, _goal("A"), name="old.json")
    new = _write_slate(tmp_path, _goal("A"), name="new.json")
    rc, obj, out, err = _diff_json(old, new, capsys)
    assert rc == 0
    assert obj["added"] == [] and obj["removed"] == [] and obj["changed"] == []
    assert obj["unchanged_count"] == 1
    # The whole thing is ONE JSON object; no human marker text bleeds in.
    assert _NO_DIFF not in out


def test_behavior12_json_arrays_title_ascending(tmp_path, capsys):
    old = _write_slate(tmp_path, name="old.json")
    new = _write_slate(tmp_path, _goal("Zebra"), _goal("apple"), _goal("Mango"), name="new.json")
    rc, obj, out, err = _diff_json(old, new, capsys)
    assert rc == 0
    assert [a["title"] for a in obj["added"]] == ["apple", "Mango", "Zebra"]


def test_behavior13_json_exit_contract_missing_file_still_exit2(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    new = _write_slate(tmp_path, _goal("A"), name="new.json")
    rc, out, err = _diff(missing, new, capsys, as_json=True)
    assert rc == 2, f"--json must not change the exit-2 guard for a missing --old; got {rc}"
    assert out.strip() == "", f"nothing must print to stdout before the guard fires; got:\n{out!r}"
    assert "slate file not found" in err


# ===========================================================================
# Behavior 14 -- missing/non-file --old (checked FIRST) or --new ->
# 'error: slate file not found: <path>' on stderr + exit 2, no traceback.
# ===========================================================================


def test_behavior14_missing_old_exit2(tmp_path, capsys):
    missing = tmp_path / "gone.json"
    new = _write_slate(tmp_path, _goal("A"), name="new.json")
    rc, out, err = _diff(missing, new, capsys)
    assert rc == 2, f"missing --old must exit 2, got {rc}"
    assert err.strip().splitlines()[0] == f"error: slate file not found: {missing}", (
        f"stderr must name the missing --old; got:\n{err!r}"
    )
    assert out.strip() == ""
    assert _TRACEBACK not in err


def test_behavior14_old_ok_missing_new_exit2(tmp_path, capsys):
    old = _write_slate(tmp_path, _goal("A"), name="old.json")
    missing = tmp_path / "gone.json"
    rc, out, err = _diff(old, missing, capsys)
    assert rc == 2, f"missing --new must exit 2, got {rc}"
    assert err.strip().splitlines()[0] == f"error: slate file not found: {missing}", (
        f"stderr must name the missing --new; got:\n{err!r}"
    )
    assert _TRACEBACK not in err


def test_behavior14_old_checked_first_when_both_missing(tmp_path, capsys):
    old = tmp_path / "old_gone.json"
    new = tmp_path / "new_gone.json"
    rc, out, err = _diff(old, new, capsys)
    assert rc == 2
    assert err.strip().splitlines()[0] == f"error: slate file not found: {old}", (
        f"--old must be checked FIRST; got:\n{err!r}"
    )


def test_behavior14_directory_is_not_a_file(tmp_path, capsys):
    # A path that exists but is a DIRECTORY is 'non-file' -> the same guard.
    d = tmp_path / "adir"
    d.mkdir()
    new = _write_slate(tmp_path, _goal("A"), name="new.json")
    rc, out, err = _diff(d, new, capsys)
    assert rc == 2, f"a directory --old must fail the not-a-file guard with exit 2, got {rc}"
    assert "slate file not found" in err
    assert _TRACEBACK not in err


# ===========================================================================
# Behavior 15 -- corrupt/schema-invalid slate -> exit 1 via the main() boundary
# (single 'error: <msg>' line, no traceback, no bespoke catch).
# ===========================================================================


def test_behavior15_corrupt_json_exit1(tmp_path, capsys):
    bad = tmp_path / "corrupt.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    new = _write_slate(tmp_path, _goal("A"), name="new.json")
    rc, out, err = _diff(bad, new, capsys)
    assert rc == 1, f"syntactically corrupt slate must exit 1 via main(), got {rc}"
    first = err.strip().splitlines()[0] if err.strip() else ""
    assert first.startswith("error:"), f"stderr must begin with 'error:'; got:\n{err!r}"
    assert _TRACEBACK not in err, f"corrupt slate must not print a traceback; got:\n{err!r}"


def test_behavior15_schema_invalid_slate_exit1(tmp_path, capsys):
    # Valid JSON but NOT a well-formed GoalSlate (fails model_validate_json) -> exit 1.
    bad = tmp_path / "wrongschema.json"
    # goals must be a list of well-formed CandidateGoals; a goal with a
    # non-numeric impact fails GoalSlate.model_validate_json.
    bad.write_text(json.dumps({"goals": [{"impact": "not-a-number"}]}), encoding="utf-8")
    new = _write_slate(tmp_path, _goal("A"), name="new.json")
    rc, out, err = _diff(bad, new, capsys)
    assert rc == 1, f"schema-invalid slate must exit 1 via main(), got {rc}"
    assert err.strip().splitlines()[0].startswith("error:")
    assert _TRACEBACK not in err


# ===========================================================================
# Acceptance -- diff is a pure reader: builds no LLMClient, runs no
# collector/subprocess, writes no file.
# ===========================================================================


def test_acceptance_builds_no_llm_client_no_sdk_import(tmp_path, capsys):
    old = _write_slate(tmp_path, _goal("A"), name="old.json")
    new = _write_slate(tmp_path, _goal("A"), _goal("B"), name="new.json")
    for name in list(sys.modules):
        if name.split(".")[0] in _SDK_MODULES:
            del sys.modules[name]
    rc, out, err = _diff(old, new, capsys)
    assert rc == 0, f"diff must run offline, got {rc}; stderr:\n{err}"
    leaked = [m for m in _SDK_MODULES if m in sys.modules]
    assert leaked == [], f"diff must build no LLMClient; leaked SDK imports: {leaked}"


def test_acceptance_writes_no_file(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    old = _write_slate(ws, _goal("A"), name="old.json")
    new = _write_slate(ws, _goal("A"), _goal("B"), name="new.json")
    before = {p.name for p in ws.iterdir()}
    state = tmp_path / "st"
    rc, out, err = _diff(old, new, capsys, as_json=True, extra=["--state-dir", str(state)])
    assert rc == 0
    after = {p.name for p in ws.iterdir()}
    assert after == before, f"diff must write no file; new entries: {after - before}"
    # No slate written, no run dir, no state dir materialized.
    assert not (ws / "slate.json").exists()
    assert not list(ws.glob("run-*"))
    assert not state.exists(), "inert --state-dir must not be created"


# ---------------------------------------------------------------------------
# Local JSON helper (defined after _diff so it can reuse it).
# ---------------------------------------------------------------------------


def _diff_json(old: Path, new: Path, capsys, *, extra=None):
    """Run ``diff --json`` and return (rc, parsed_obj_or_None, stdout, stderr)."""
    rc, out, err = _diff(old, new, capsys, as_json=True, extra=extra)
    obj = json.loads(out) if out.strip() else None
    return rc, obj, out, err
