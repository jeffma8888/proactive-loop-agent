"""Black-box behavior tests for ``pla policy --check-goal '<CandidateGoal JSON>'``.

Feature under test (``pm.md`` iteration 240, closing roadmap row #245): ``policy`` was a
zero-input catalog of the STANDING autonomy contract, so a reader who wanted to know *what
would this gate do with THIS goal* first had to cause a ``scan`` to invent one -- an LLM call
and a workspace, on a product whose thesis is offline-first. ``--check-goal`` takes the goal
as a JSON literal and prints that one goal's decision audit INSTEAD of the catalog, with no
slate, no LLM and no workspace.

Two properties carry the value and both are pinned here rather than described:

* **Agreement, not a second renderer** (behavior 6). The audit is rendered by the helpers
  ``explain`` already uses, so ``policy --check-goal '<G>'`` and
  ``explain --slate <file> --goal-id <G.id>`` must be byte-identical for the same goal --
  human form and ``--json`` alike. A test that only checked "an audit was printed" would pass
  against a divergent copy of the renderer, which is the failure this contract exists to stop.
* **A caller cannot forge auto-dispatch** (behavior 5). ``CandidateGoal.score`` is a computed
  field, so a supplied ``"score": 99.0`` is ignored and the DERIVED score decides. This is a
  safety property of the headline gate and was untested anywhere before this module.

ISOLATION CONTRACT (honored): every assertion below drives documented public surfaces only --
the ``pla`` CLI through ``proactive_loop.cli.main(argv) -> int`` (its observable exit code,
stdout and stderr), ``build_parser()`` for the verb census, and the public
``proactive_loop.models`` types used to BUILD a fixture slate. **No file under ``src/`` was
read, no engineer or reviewer notes were read, and no ``git diff`` was consulted.** The gate
outcomes, reasons, thresholds and category-sensitivity facts are encoded here as the spec's
declared ground facts, never imported from the implementation. Fully offline: no network, no
API key, no provider, no workspace.

ONE LIMIT, stated rather than papered over: behavior 10 also requires two edits INSIDE
``src/proactive_loop/cli.py`` (the ``_cmd_policy`` docstring and the ``p_policy`` subparser
comment). Asserting on those means reading implementation source, which this contract forbids,
so this module covers behavior 10 through the three surfaces it may legitimately reach --
``README.md``, ``SPEC.md`` and the parser's own ``--help`` -- and the source-comment pair is
left to the reviewer. See ``tester.md``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.cli import build_parser, main
from proactive_loop.models import CandidateGoal, GoalSlate
from tests.test_iter125_behavior import clear_pla_env

REPO: Final[Path] = Path(__file__).resolve().parents[1]
README: Final[Path] = REPO / "README.md"
SPEC: Final[Path] = REPO / "SPEC.md"


@pytest.fixture(autouse=True)
def _hermetic_pla_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the derived ``PLA_*`` set before EVERY test in this module.

    These tests assert DOCUMENTED DEFAULTS (threshold ``4.0``), and the README publishes
    every ``PLA_*`` knob as a supported surface, so a knob exported in the developer shell
    would red a clean checkout while looking like broken code. Function-scoped and autouse,
    so a test that sets its own override still wins.
    """
    clear_pla_env(monkeypatch)


# ---------------------------------------------------------------------------
# Tester's constants -- the spec's ground facts, encoded, NOT imported from src.
# ---------------------------------------------------------------------------

#: The four ordered gate reasons (first match wins), verbatim from SPEC 4.3.
REASON_SENSITIVE: Final[str] = "sensitive category"
REASON_BLOCKED: Final[str] = "not appropriate right now"
REASON_AUTO: Final[str] = "score meets auto-dispatch threshold"
REASON_BELOW: Final[str] = "below auto-dispatch threshold"

#: The ``Settings.auto_dispatch_min_score`` default.
DEFAULT_THRESHOLD: Final[float] = 4.0

#: Markers unique to the STANDING-catalog rendering. Their ABSENCE is what proves
#: ``--check-goal`` REPLACES the catalog rather than appending to it (behavior 1).
CATALOG_MARKERS: Final[tuple[str, ...]] = (
    "autonomy contract",
    "gate rules (first match wins):",
)

#: The EXACT four-key allowlist ``policy --json`` emits with no ``--check-goal``
#: (the ``tests/test_iter39_behavior.py`` contract, restated as the behavior-9 anchor).
CONTRACT_JSON_KEYS: Final[frozenset[str]] = frozenset(
    {"auto_dispatch_min_score", "sensitive_categories", "categories", "rules"}
)

#: Live ``pla`` subcommands. ``--check-goal`` is a FLAG on an existing verb, so this
#: number must not move (behavior 9). The README portfolio intro publishes it too.
EXPECTED_VERB_COUNT: Final[int] = 17

#: Vendor detail that must never reach a user's terminal (behaviors 7-8). Proven
#: NON-VACUOUS by ``test_b07c``: an unsanitized pydantic message really does spell these.
VENDOR_TOKENS: Final[tuple[str, ...]] = (
    "pydantic",
    "errors.pydantic.dev",
    "[type=",
    "input_value=",
)

#: The four spec payloads, one per ordered gate rule. ``id`` is always supplied because
#: ``CandidateGoal.id`` is auto-generated when omitted, which would make output nondeterministic.
PAYLOAD_SENSITIVE: Final[str] = (
    '{"id":"g1","title":"t","category":"finance_legal",'
    '"impact":5,"urgency":5,"confidence":1.0}'
)
PAYLOAD_BLOCKED: Final[str] = (
    '{"id":"g2","title":"t","appropriate_now":false,'
    '"impact":5,"urgency":5,"confidence":1.0}'
)
PAYLOAD_AUTO: Final[str] = (
    '{"id":"g3","title":"t","impact":5,"urgency":4,'
    '"confidence":1.0,"effort_weight":1.0}'
)
PAYLOAD_BELOW: Final[str] = '{"id":"g4","title":"t"}'


# ---------------------------------------------------------------------------
# Helpers -- black-box: drive main(), read back exit code + stdout/stderr.
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Invoke the CLI and return ``(rc, stdout, stderr)``.

    Drains ``capsys`` first so any setup output stays out of the assertion window.
    """
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _check(payload: str, *json_flag: str) -> list[str]:
    return ["policy", "--check-goal", payload, *json_flag]


def _decision_line(out: str) -> str:
    """The single ``decision    : ...`` line of the human audit."""
    hits = [ln for ln in out.splitlines() if ln.startswith("decision")]
    assert len(hits) == 1, f"audit must carry exactly ONE decision line; got {hits!r} in:\n{out}"
    return hits[0]


def _score_line(out: str) -> str:
    """The substituted-arithmetic line of the human audit (the one carrying ``=``)."""
    hits = [ln for ln in out.splitlines() if "=" in ln and "/" in ln]
    assert len(hits) == 1, f"audit must carry exactly ONE arithmetic line; got {hits!r} in:\n{out}"
    return hits[0]


def _error_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if ln.startswith("error: ")]


def _verb_count() -> int:
    """The number of live ``pla`` subcommands, straight off the public parser."""
    parser = build_parser()
    subs = [
        a
        for a in parser._subparsers._group_actions
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(subs) == 1, f"expected exactly one subparser action, got {len(subs)}"
    return len(subs[0].choices)


def _one_goal_slate(tmp_path: Path, goal: CandidateGoal) -> Path:
    """Write a real one-goal ``slate.json`` built from the PUBLIC models and return its path.

    Built rather than scanned on purpose: behavior 6 compares two renderings of the SAME
    goal, so the fixture must pin every field the audit prints. A scanned demo slate would
    make the comparison depend on an LLM script.
    """
    path = tmp_path / "slate.json"
    path.write_text(GoalSlate(goals=[goal]).model_dump_json(indent=2), encoding="utf-8")
    return path


def _spec_policy_entry() -> str:
    """The ``pla policy`` bullet of SPEC.md's CLI section, up to the next verb bullet.

    Scoped so the behavior-10 assertions cannot be satisfied (or broken) by the
    ``tools``/``collectors``/``providers``/``config`` entries, which legitimately KEEP
    their own zero-input claims -- those verbs gained no input.
    """
    text = SPEC.read_text(encoding="utf-8")
    starts = [m.start() for m in re.finditer(r"(?m)^  - `pla policy ", text)]
    assert len(starts) == 1, f"SPEC.md must hold exactly one `pla policy` entry, found {len(starts)}"
    rest = text[starts[0] :]
    nxt = re.search(r"(?m)^  - `pla (?!policy )", rest)
    return rest[: nxt.start()] if nxt else rest


def _readme_policy_row() -> str:
    """The README CLI-reference table row whose first cell is the ``policy`` verb."""
    rows = [
        ln
        for ln in README.read_text(encoding="utf-8").splitlines()
        if ln.startswith("|") and ln.split("|")[1].strip().strip("`") == "policy"
    ]
    assert len(rows) == 1, f"README must hold exactly one `policy` CLI-reference row, found {len(rows)}"
    return rows[0]


# ==========================================================================
# Behavior 1 -- the flag exists and REPLACES the catalog.
# ==========================================================================


def test_b01_check_goal_exits_zero_and_prints_the_one_goal_audit(capsys):
    rc, out, err = _run(_check(PAYLOAD_BELOW), capsys)
    assert rc == 0, f"`policy --check-goal` must exit 0; stderr={err!r}"
    assert _decision_line(out).startswith("decision"), out


def test_b01b_catalog_markers_are_absent(capsys):
    """The audit REPLACES the catalog; it does not append to it."""
    _, out, _ = _run(_check(PAYLOAD_BELOW), capsys)
    for marker in CATALOG_MARKERS:
        assert marker not in out, (
            f"--check-goal must REPLACE the standing catalog, but stdout still spells "
            f"{marker!r}:\n{out}"
        )


def test_b01c_control_bare_policy_does_print_those_markers(capsys):
    """Two-sided control: the markers behavior 1b asserts absent are really the catalog's.

    Without this, ``test_b01b`` would also pass against markers that no longer exist
    anywhere -- an assertion that can never fail proves nothing.
    """
    rc, out, _ = _run(["policy"], capsys)
    assert rc == 0
    for marker in CATALOG_MARKERS:
        assert marker in out, f"bare `policy` must still print {marker!r}; got:\n{out}"


# ==========================================================================
# Behavior 2 -- the rendered decision is gate()'s, for all four ordered rules,
# with no workspace, no slate and no LLM.
# ==========================================================================


@pytest.mark.parametrize(
    ("payload", "decision", "reason"),
    [
        (PAYLOAD_SENSITIVE, "needs_approval", REASON_SENSITIVE),
        (PAYLOAD_BLOCKED, "blocked", REASON_BLOCKED),
        (PAYLOAD_AUTO, "auto_dispatch", REASON_AUTO),
        (PAYLOAD_BELOW, "needs_approval", REASON_BELOW),
    ],
    ids=["sensitive", "blocked", "auto_dispatch", "below_threshold"],
)
def test_b02_four_ordered_rules_human_form(payload, decision, reason, capsys):
    rc, out, err = _run(_check(payload), capsys)
    assert rc == 0, f"payload {payload} must exit 0; stderr={err!r}"
    line = _decision_line(out)
    assert decision in line, f"expected decision {decision!r} in {line!r}"
    assert reason in line, f"expected reason {reason!r} in {line!r}"


@pytest.mark.parametrize(
    ("payload", "decision", "reason", "score"),
    [
        (PAYLOAD_SENSITIVE, "needs_approval", REASON_SENSITIVE, 25.0),
        (PAYLOAD_BLOCKED, "blocked", REASON_BLOCKED, 25.0),
        (PAYLOAD_AUTO, "auto_dispatch", REASON_AUTO, 20.0),
        (PAYLOAD_BELOW, "needs_approval", REASON_BELOW, 0.5),
    ],
    ids=["sensitive", "blocked", "auto_dispatch", "below_threshold"],
)
def test_b02b_four_ordered_rules_json_form(payload, decision, reason, score, capsys):
    """Sensitivity PRECEDES score: the sensitive payload scores 25.0 and still gates."""
    rc, out, err = _run(_check(payload, "--json"), capsys)
    assert rc == 0, f"payload {payload} must exit 0; stderr={err!r}"
    obj = json.loads(out)
    assert obj["decision"] == decision, obj
    assert obj["reason"] == reason, obj
    assert obj["score"] == pytest.approx(score), obj
    assert obj["auto_dispatch_threshold"] == pytest.approx(DEFAULT_THRESHOLD), obj


# ==========================================================================
# Behavior 3 -- the EFFECTIVE threshold is honored through the shared _settings seam.
# ==========================================================================


def test_b03_env_override_flips_auto_dispatch_and_the_printed_threshold(monkeypatch, capsys):
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "25")
    rc, out, err = _run(_check(PAYLOAD_AUTO, "--json"), capsys)
    assert rc == 0, f"stderr={err!r}"
    obj = json.loads(out)
    assert obj["score"] == pytest.approx(20.0), obj
    assert obj["decision"] == "needs_approval", (
        f"score 20.0 under a threshold of 25 must NOT auto-dispatch; got {obj['decision']!r}"
    )
    assert obj["reason"] == REASON_BELOW, obj
    assert obj["auto_dispatch_threshold"] == pytest.approx(25.0), (
        f"the printed threshold must be the EFFECTIVE one; got {obj['auto_dispatch_threshold']!r}"
    )


def test_b03b_env_override_reaches_the_human_form_too(monkeypatch, capsys):
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "25")
    rc, out, _ = _run(_check(PAYLOAD_AUTO), capsys)
    assert rc == 0
    assert "25" in _score_line(out), (
        f"the human audit must print the EFFECTIVE threshold; got {_score_line(out)!r}"
    )
    assert "needs_approval" in _decision_line(out), _decision_line(out)


# ==========================================================================
# Behavior 4 -- --json emits the EXPLAIN object, not the contract object.
# ==========================================================================


def test_b04_json_key_set_equals_explains_and_carries_no_contract_keys(tmp_path, capsys):
    goal = CandidateGoal(id="gx", title="t")
    slate = _one_goal_slate(tmp_path, goal)

    rc, out, err = _run(_check(PAYLOAD_BELOW, "--json"), capsys)
    assert rc == 0, f"stderr={err!r}"
    obj = json.loads(out)  # the ENTIRE stdout must be ONE JSON object
    assert isinstance(obj, dict), f"top-level JSON must be an object; got {type(obj)}"

    rc2, out2, _ = _run(["explain", "--slate", str(slate), "--goal-id", "gx", "--json"], capsys)
    assert rc2 == 0
    assert set(obj) == set(json.loads(out2)), (
        "`policy --check-goal --json` must emit EXPLAIN's key set (no new wire schema); "
        f"got {sorted(obj)} vs explain's {sorted(json.loads(out2))}"
    )
    for stale in ("rules", "categories"):
        assert stale not in obj, f"the contract key {stale!r} must be gone with --check-goal: {obj}"


# ==========================================================================
# Behavior 5 -- a caller cannot forge the score (score is a computed field).
# ==========================================================================


def test_b05_supplied_score_is_ignored_json(capsys):
    rc, out, err = _run(_check('{"id":"g5","title":"t","score":99.0}', "--json"), capsys)
    assert rc == 0, f"a supplied score must be IGNORED, not rejected; stderr={err!r}"
    obj = json.loads(out)
    assert obj["score"] == pytest.approx(0.5), f"derived score must win; got {obj['score']!r}"
    assert obj["decision"] == "needs_approval", obj
    assert obj["reason"] == REASON_BELOW, obj


def test_b05b_the_forged_number_appears_nowhere_in_the_human_score_line(capsys):
    rc, out, err = _run(_check('{"id":"g5","title":"t","score":99.0}'), capsys)
    assert rc == 0, f"stderr={err!r}"
    line = _score_line(out)
    assert "99" not in line, f"the forged score must not be echoed; got {line!r}"
    assert "0.5" in line, f"the derived score must be shown; got {line!r}"


# ==========================================================================
# Behavior 6 -- agreement with `explain`, byte for byte.
# ==========================================================================


def test_b06_human_form_is_byte_identical_to_explain(tmp_path, capsys):
    goal = CandidateGoal(
        id="gx",
        title="Ship the audit",
        category="learning",
        impact=4,
        urgency=3,
        confidence=0.9,
        effort_weight=2.0,
        rationale="because the gate is the headline claim",
        sources=["notes.md"],
        suggested_first_steps=["draft the flag"],
    )
    slate = _one_goal_slate(tmp_path, goal)

    rc_p, out_p, err_p = _run(_check(goal.model_dump_json()), capsys)
    rc_e, out_e, err_e = _run(["explain", "--slate", str(slate), "--goal-id", goal.id], capsys)
    assert rc_p == 0 and rc_e == 0, f"policy err={err_p!r} explain err={err_e!r}"
    assert out_p == out_e, (
        "policy --check-goal must reuse explain's renderer, byte for byte\n"
        f"policy :\n{out_p}\nexplain:\n{out_e}"
    )


def test_b06b_json_form_parses_equal_to_explains(tmp_path, capsys):
    goal = CandidateGoal(
        id="gy",
        title="Another goal",
        category="finance_legal",
        impact=5,
        urgency=5,
        confidence=1.0,
    )
    slate = _one_goal_slate(tmp_path, goal)

    _, out_p, _ = _run(_check(goal.model_dump_json(), "--json"), capsys)
    _, out_e, _ = _run(
        ["explain", "--slate", str(slate), "--goal-id", goal.id, "--json"], capsys
    )
    assert json.loads(out_p) == json.loads(out_e), (
        f"the two --json objects must be equal\npolicy : {out_p}\nexplain: {out_e}"
    )


# ==========================================================================
# Behaviors 7-8 -- both input faults are ONE opaque `error:` line at exit 1.
# ==========================================================================


def test_b07_malformed_json_is_one_opaque_error_line_at_exit_1(capsys):
    rc, out, err = _run(_check("{not json"), capsys)
    assert rc == 1, f"malformed --check-goal JSON must exit 1; got {rc}, stderr={err!r}"
    lines = _error_lines(err)
    assert len(lines) == 1, f"exactly ONE `error: ` line; got {lines!r}"
    assert "--check-goal" in lines[0], f"the line must name the flag; got {lines[0]!r}"
    assert "Traceback (most recent call last)" not in err, err
    assert out == "", f"stdout must stay clean on failure; got {out!r}"


def test_b07b_no_vendor_detail_and_no_payload_echo(capsys):
    payload = '{not json'
    _, _, err = _run(_check(payload), capsys)
    for token in VENDOR_TOKENS:
        assert token not in err, f"vendor detail {token!r} must be stripped; got {err!r}"
    assert "not json" not in err, f"the supplied payload must not be echoed; got {err!r}"


def test_b07c_control_the_vendor_tokens_are_really_in_an_unsanitized_message():
    """Two-sided control: prove ``VENDOR_TOKENS`` is not a list of strings that never occur.

    Without this, ``test_b07b`` is unfalsifiable -- it would pass just as loudly against a
    typo'd token list. The raw pydantic message for the same fault is measured here.
    """
    with pytest.raises(Exception) as excinfo:
        CandidateGoal.model_validate_json("{not json")
    raw = str(excinfo.value)
    hits = [t for t in VENDOR_TOKENS if t in raw]
    assert hits, (
        "an unsanitized pydantic message must spell at least one VENDOR_TOKEN, else the "
        f"opacity assertion is vacuous; raw message was:\n{raw}"
    )


def test_b08_schema_invalid_json_reports_the_first_location(capsys):
    rc, out, err = _run(_check('{"title":"t","impact":99}'), capsys)
    assert rc == 1, f"schema-invalid --check-goal JSON must exit 1; got {rc}, stderr={err!r}"
    lines = _error_lines(err)
    assert len(lines) == 1, f"exactly ONE `error: ` line; got {lines!r}"
    assert "--check-goal" in lines[0], lines[0]
    assert "1 validation error" in lines[0], lines[0]
    assert "impact" in lines[0], f"the line must name the first bad location; got {lines[0]!r}"
    for token in VENDOR_TOKENS:
        assert token not in err, f"vendor detail {token!r} must be stripped; got {err!r}"
    assert out == "", f"stdout must stay clean on failure; got {out!r}"


# ==========================================================================
# Behavior 9 -- omitting the flag changes nothing.
# ==========================================================================


def test_b09_bare_policy_json_is_still_the_exact_four_key_allowlist(capsys):
    rc, out, err = _run(["policy", "--json"], capsys)
    assert rc == 0, f"stderr={err!r}"
    obj = json.loads(out)
    assert set(obj) == set(CONTRACT_JSON_KEYS), (
        f"policy --json must still emit EXACTLY {sorted(CONTRACT_JSON_KEYS)}; got {sorted(obj)}"
    )
    assert obj["auto_dispatch_min_score"] == pytest.approx(DEFAULT_THRESHOLD), obj


def test_b09b_the_flag_added_no_verb():
    assert _verb_count() == EXPECTED_VERB_COUNT, (
        f"--check-goal is a FLAG on `policy`, so the verb count must stay "
        f"{EXPECTED_VERB_COUNT}; got {_verb_count()}"
    )


def test_b09c_bare_policy_prints_no_audit(capsys):
    """The reverse direction of behavior 1: with no flag, no per-goal audit appears."""
    rc, out, _ = _run(["policy"], capsys)
    assert rc == 0
    assert not [ln for ln in out.splitlines() if ln.startswith("decision")], (
        f"bare `policy` must print the catalog only, no decision line; got:\n{out}"
    )


# ==========================================================================
# Behavior 10 -- the docs no longer contradict the code (the three surfaces
# this isolation contract may reach; see the module docstring).
# ==========================================================================


def test_b10_policy_help_documents_the_flag_with_a_json_metavar(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["policy", "--help"])
    assert excinfo.value.code == 0, "`pla policy --help` must exit 0"
    out = capsys.readouterr().out
    assert "--check-goal JSON" in out, f"help must document `--check-goal JSON`; got:\n{out}"


def test_b10b_readme_cli_row_documents_the_flag():
    row = _readme_policy_row()
    assert "--check-goal" in row, (
        "README's CLI-reference `policy` row must document --check-goal (the live-flag guard "
        f"reds the build otherwise); got:\n{row}"
    )


def test_b10c_spec_policy_entry_documents_the_flag_and_drops_the_stale_claims():
    entry = _spec_policy_entry()
    assert "--check-goal" in entry, f"SPEC's `pla policy` entry must document the flag; got:\n{entry}"
    for stale in ("zero-input", "no input to fail on"):
        assert stale not in entry, (
            f"SPEC's `pla policy` entry must no longer claim {stale!r} -- the verb now has an "
            f"input that can fail; got:\n{entry}"
        )


def test_b10d_control_a_verb_that_gained_no_input_keeps_its_zero_input_claim():
    """Two-sided control for 10c: the stale phrases still exist in SPEC.md elsewhere.

    ``tools``/``collectors``/``providers``/``config`` are explicitly out of scope, so a
    repo-wide deletion of "zero-input" would be over-reach. Asserting one survivor proves
    10c is scoped, not a blunt sweep.
    """
    text = SPEC.read_text(encoding="utf-8")
    assert "zero-input" in text, (
        "SPEC.md must still describe the genuinely zero-input verbs that way; only `policy`'s "
        "claim was corrected"
    )
