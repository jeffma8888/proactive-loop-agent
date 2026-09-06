"""Black-box behavior tests for ``pla run --max-iterations`` / ``--max-llm-calls``.

Provenance, stated plainly because this module is not newly authored: it is the
factory-iteration-282 oracle for these two flags, RE-LANDED at factory iteration
284 after that commit was reverted at the fresh-clone ship gate for an unrelated
fixture defect (a mtime-sensitive precondition elsewhere in the suite, fixed by
iteration 283). It is carried forward VERBATIM except for two deliberate trims,
both recorded here so a reader can see what is and is not graded:

* Groups ``b06``-``b09`` -- meta-assertions ABOUT the README, config-contract,
  ``SPEC.md`` and roadmap edits of the same commit -- were DROPPED. They are not
  unguarded: ``tests/test_iter125_readme_config_contract.py``,
  ``tests/test_iter214_behavior.py``, ``tests/test_iter234_behavior.py`` and the
  ledger-gap brake already grade those documents directly.
* Two ``@parametrize`` lists were narrowed by one value each (``-1`` dropped from
  both), which loses no behavior: a non-positive value and a non-integer value
  are each still exercised on BOTH flags.

Both trims exist for one measured reason: the suite's own floor oracles bound the
live case count from BOTH sides (``test_iter245_behavior.py`` pins a window only a
few dozen cases wide, and ``test_iter238_behavior.py`` pins ``live // 100 * 100``
to whatever floor the README publishes), so the case budget available to this
module was finite and small. No floor number is quoted anywhere in this file ON
PURPOSE: a file that spells the published floor becomes an undeclared floor
CARRIER, which the census in ``tests/test_readme_and_ci_contract.py`` fails by
design. Raising that ceiling is its own iteration.

Feature under test: the L1 loop budget was REPORTABLE but not SETTABLE. ``pla
config --json`` published both budgets and ``run --json`` published what a run
SPENT, yet the only way to SET either was a ``PLA_*`` environment variable, and
``--dry-run`` runs ZERO iterations -- so there was no way to ask for a BOUNDED
REAL run at all. Both flags are declared on ``p_run`` alone, reusing the shipped
``_positive_int`` argparse validator so a bad value is a PARSE-time usage error
(exit 2) that never reaches pydantic.

Fully offline and deterministic: every invocation pins ``--provider scripted``
with a TEST-AUTHORED response script and a ``tmp_path`` state dir, so no network,
no API key and no shared state. NO mtime-sensitive precondition and no read of
``examples/fixture_workspace`` (iter-278 lesson: a fresh clone resets every
mtime, so a precondition that reads one passes only on this machine) -- the
workspace is synthesized under ``tmp_path`` on every test.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from proactive_loop.cli import _settings, build_parser, main
from proactive_loop.config import Settings


#: The two flags this iteration ships, paired with the variable each overrides.
BUDGET_FLAGS: dict[str, str] = {
    "--max-iterations": "PLA_MAX_ITERATIONS",
    "--max-llm-calls": "PLA_MAX_LLM_CALLS",
}


#: The built-in defaults the spec pins (behavior 2). Spelled here so a silent
#: field-default move is caught rather than absorbed.
BUILTIN_DEFAULTS = {"max_iterations": 8, "max_llm_calls": 24}

#: The verbatim fragment the shipped ``_positive_int`` validator must produce.
POSITIVE_INT_ERR = "must be a positive integer (>= 1)"


#: Substrings that would prove a ``pydantic.ValidationError`` (which IS a
#: ``ValueError``, so ``main()``'s ``except`` would print it) leaked to the user.
#: SPEC pins this vendor dump as CLOSED at this boundary.
VENDOR_DUMP_MARKERS = (
    "validation error",
    "[type=greater_than_equal",
    "input_value=",
    "errors.pydantic.dev",
)


# ---------------------------------------------------------------------------
# Helpers -- synthetic workspace, synthetic script, invocation wrappers
# ---------------------------------------------------------------------------


def _workspace(tmp_path: Path) -> Path:
    """A minimal, real, synthetic workspace (never the in-repo fixture).

    Two reasons this is authored rather than copied: the fixture carries no
    ``.git`` of its own, so git-family collectors resolve upward into this repo
    and a sibling xdist worker can flip what they report mid-test; and a copied
    tree carries the fixture's mtimes, which a fresh clone resets.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "notes.md").write_text("# journal\n\nlearn agentic loops\n", encoding="utf-8")
    (ws / "agent.py").write_text("def plan() -> None:\n    pass\n", encoding="utf-8")
    return ws


def _goal_dict() -> dict[str, Any]:
    """One AUTO_DISPATCH-eligible goal, matching the synthesize JSON contract.

    ``learning`` is outside the default sensitive set and the score clears the
    default ``PLA_AUTO_DISPATCH_MIN_SCORE`` of 4.0, so ``run`` auto-dispatches it
    without ``--yes`` -- which is what behavior 5 needs in order to spend real
    iterations.
    """
    return {
        "title": "Draft a learning plan for the agentic-loop project",
        "rationale": "iter-282 bounded-run probe",
        "category": "learning",
        "impact": 5.0,
        "urgency": 5.0,
        "confidence": 1.0,
        "effort_weight": 1.0,
        "appropriate_now": True,
        "sources": ["notes.md"],
        "suggested_first_steps": ["write learning_plan.md"],
    }


def _never_done_script(tmp_path: Path, *, plan_act_check_pairs: int = 12) -> Path:
    """A scripted-responses file whose CHECK step NEVER reports the goal done.

    Without that property the loop could finish on its own and the run would
    report DONE at fewer iterations than the budget, making a budget assertion
    vacuous. Enough pairs are written to outlast the largest budget any test
    here asks for, so exhaustion is always the budget's doing.
    """
    responses: list[dict[str, str]] = [
        {"tag": "synthesize", "text": json.dumps([_goal_dict()])}
    ]
    for i in range(1, plan_act_check_pairs + 1):
        responses.append(
            {
                "tag": "plan",
                "text": json.dumps(
                    {
                        "thought": f"step {i}: write an artifact",
                        "action": {
                            "tool": "write_file",
                            "args": {"path": f"step{i}.md", "content": f"# step {i}\n"},
                        },
                    }
                ),
            }
        )
        responses.append(
            {
                "tag": "check",
                "text": json.dumps({"done": False, "reason": f"step {i} written; more to do"}),
            }
        )
    path = tmp_path / "script.json"
    path.write_text(json.dumps({"responses": responses}), encoding="utf-8")
    return path


def _run_argv(ws: Path, script: Path, state_dir: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--workspace",
        str(ws),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(script),
        "--state-dir",
        str(state_dir),
        *extra,
    ]


def _usage_error(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Drive ``main()`` expecting an argparse PARSE-TIME usage error.

    A ``type=`` validator failure raises ``SystemExit(2)`` from inside
    ``parse_args`` -- OUTSIDE ``main()``'s try-boundary -- so the exit code is
    carried by the exception rather than returned. Same mechanism
    ``test_iter38_behavior.py`` relies on for ``--max-scans``.
    """
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    cap = capsys.readouterr()
    code = excinfo.value.code
    return (code if isinstance(code, int) else 1), cap.out, cap.err


def _one_json_object(stdout: str, label: str) -> dict[str, Any]:
    """Parse stdout as EXACTLY one JSON object, or fail with the raw text."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - failure reporting
        pytest.fail(f"{label}: stdout must be one JSON object; {exc}\nstdout:\n{stdout!r}")
    assert isinstance(payload, dict), f"{label}: expected a JSON object, got {type(payload).__name__}"
    return payload


def _collect_long_flags(parser: argparse.ArgumentParser) -> dict[str, frozenset[str | None]]:
    """Every ``--`` option the live CLI exposes, mapped to its owning verbs.

    Walks the top-level parser and, recursively, every subparser in each
    ``argparse._SubParsersAction.choices``. An owner of ``None`` means the
    top-level parser itself. Enumerated rather than membership-tested so an
    ABSENCE claim is evidence (here is the whole set, X is not in it).
    """
    owners: dict[str, set[str | None]] = {}
    stack: list[tuple[argparse.ArgumentParser, str | None]] = [(parser, None)]
    while stack:
        current, verb = stack.pop()
        for action in current._actions:
            for option in action.option_strings:
                if option.startswith("--"):
                    owners.setdefault(option, set()).add(verb)
            if isinstance(action, argparse._SubParsersAction):
                for name, subparser in action.choices.items():
                    stack.append((subparser, name))
    return {flag: frozenset(verbs) for flag, verbs in owners.items()}


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("the top-level parser exposes no subparsers")


def _long_options(parser: argparse.ArgumentParser) -> frozenset[str]:
    return frozenset(
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--")
    )


def _namespace(**kwargs: Any) -> argparse.Namespace:
    """A namespace carrying ONLY the attributes named, so a missing attribute is
    genuinely missing (that is the shape every non-``run`` verb hands
    ``_settings``)."""
    return argparse.Namespace(**kwargs)


# ===========================================================================
# Behavior 1 -- both flags exist on `run`, and ONLY on `run`
# ===========================================================================


def test_b01a_run_accepts_both_flags_and_binds_the_given_integers(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    args = build_parser().parse_args(
        ["run", "--workspace", str(ws), "--max-iterations", "3", "--max-llm-calls", "9"]
    )
    assert args.max_iterations == 3, f"--max-iterations 3 must bind 3, got {args.max_iterations!r}"
    assert args.max_llm_calls == 9, f"--max-llm-calls 9 must bind 9, got {args.max_llm_calls!r}"


def test_b01b_absent_flags_default_to_none_not_to_the_builtin_budget(tmp_path: Path) -> None:
    """``None`` is load-bearing, not a style choice.

    ``Settings.from_env`` DROPS a ``None`` override by documented contract, so a
    default of ``8`` / ``24`` would silently clobber an environment value on
    every plain ``pla run`` -- the exact regression behavior 3 forbids.
    """
    ws = _workspace(tmp_path)
    args = build_parser().parse_args(["run", "--workspace", str(ws)])
    assert args.max_iterations is None, (
        f"an unspecified --max-iterations must be None so from_env drops it; got "
        f"{args.max_iterations!r}"
    )
    assert args.max_llm_calls is None, (
        f"an unspecified --max-llm-calls must be None so from_env drops it; got "
        f"{args.max_llm_calls!r}"
    )


def test_b01c_both_flags_are_owned_by_run_alone() -> None:
    owners = _collect_long_flags(build_parser())
    for flag in BUDGET_FLAGS:
        assert flag in owners, f"{flag} is absent from the live parser; owners seen: {sorted(owners)}"
        assert owners[flag] == frozenset({"run"}), (
            f"{flag} must be owned by `run` and nothing else, got {sorted(owners[flag], key=str)}"
        )


def test_b01d_no_other_subparser_declares_either_flag() -> None:
    """The absence half, enumerated per verb so the report names the offender."""
    verbs = _subparsers(build_parser())
    assert "run" in verbs, f"the CLI lost its `run` verb; verbs: {sorted(verbs)}"
    assert len(verbs) > 1, "a single-verb parser would make this check vacuous"
    for name, subparser in sorted(verbs.items()):
        if name == "run":
            continue
        options = _long_options(subparser)
        for flag in BUDGET_FLAGS:
            assert flag not in options, (
                f"`{name}` must not declare {flag} (row #190's seam trap: a shared-parent "
                f"placement leaks the flag onto verbs whose SPEC pins it INERT); "
                f"its long options are {sorted(options)}"
            )


def test_b01e_the_flag_on_another_verb_is_a_usage_error_exit2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    rc, _out, err = _usage_error(["scan", "--workspace", str(ws), "--max-iterations", "3"], capsys)
    assert rc == 2, f"`scan --max-iterations` must exit 2, got {rc}; stderr={err!r}"
    assert "--max-iterations" in err, f"stderr must name the rejected flag; got:\n{err}"


# ===========================================================================
# Behavior 2 -- the flags reach `Settings`
# ===========================================================================


def test_b02a_a_namespace_carrying_the_flags_yields_those_budgets(tmp_path: Path) -> None:
    settings = _settings(_namespace(max_iterations=3, max_llm_calls=9), workspace_root=tmp_path)
    assert settings.max_iterations == 3, f"expected 3, got {settings.max_iterations}"
    assert settings.max_llm_calls == 9, f"expected 9, got {settings.max_llm_calls}"


def test_b02b_a_namespace_carrying_none_yields_the_builtin_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in BUDGET_FLAGS.values():
        monkeypatch.delenv(var, raising=False)
    settings = _settings(_namespace(max_iterations=None, max_llm_calls=None), workspace_root=tmp_path)
    assert settings.max_iterations == BUILTIN_DEFAULTS["max_iterations"]
    assert settings.max_llm_calls == BUILTIN_DEFAULTS["max_llm_calls"]


def test_b02c_a_namespace_lacking_the_attributes_entirely_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This is the shape EVERY non-``run`` verb hands ``_settings``.

    The flags are local to ``p_run``, so ``getattr(args, "max_iterations", None)``
    has to tolerate a namespace on which the attribute does not exist at all --
    otherwise wiring the flag reds every other verb.
    """
    for var in BUDGET_FLAGS.values():
        monkeypatch.delenv(var, raising=False)
    bare = _namespace()
    assert not hasattr(bare, "max_iterations"), "the probe namespace must genuinely lack the attribute"
    settings = _settings(bare, workspace_root=tmp_path)
    assert settings.max_iterations == BUILTIN_DEFAULTS["max_iterations"]
    assert settings.max_llm_calls == BUILTIN_DEFAULTS["max_llm_calls"]


def test_b02d_the_builtin_defaults_this_module_pins_are_the_live_field_defaults() -> None:
    """Guards against the assertions above passing for the wrong reason."""
    bare = Settings()
    assert bare.max_iterations == BUILTIN_DEFAULTS["max_iterations"]
    assert bare.max_llm_calls == BUILTIN_DEFAULTS["max_llm_calls"]


# ===========================================================================
# Behavior 3 -- flag beats env; an absent flag PRESERVES env
# ===========================================================================


def test_b03a_flag_overrides_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "7")
    monkeypatch.setenv("PLA_MAX_LLM_CALLS", "21")
    settings = _settings(_namespace(max_iterations=2, max_llm_calls=5), workspace_root=tmp_path)
    assert settings.max_iterations == 2, (
        f"an explicit flag must beat PLA_MAX_ITERATIONS=7, got {settings.max_iterations}"
    )
    assert settings.max_llm_calls == 5, (
        f"an explicit flag must beat PLA_MAX_LLM_CALLS=21, got {settings.max_llm_calls}"
    )


def test_b03b_an_absent_flag_never_clobbers_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "7")
    monkeypatch.setenv("PLA_MAX_LLM_CALLS", "21")
    settings = _settings(_namespace(max_iterations=None, max_llm_calls=None), workspace_root=tmp_path)
    assert settings.max_iterations == 7, (
        f"an unspecified flag must leave PLA_MAX_ITERATIONS=7 standing, got {settings.max_iterations}"
    )
    assert settings.max_llm_calls == 21, (
        f"an unspecified flag must leave PLA_MAX_LLM_CALLS=21 standing, got {settings.max_llm_calls}"
    )


def test_b03c_the_precedence_is_visible_end_to_end_on_a_real_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same precedence, observed through the product's own JSON rather than
    through a helper: env says 1 iteration, the flag says 2, the run spends 2."""
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "1")
    ws = _workspace(tmp_path)
    script = _never_done_script(tmp_path)

    rc = main(_run_argv(ws, script, tmp_path / "env-only", "--json"))
    payload = _one_json_object(capsys.readouterr().out, "env-only run")
    assert rc == 0, f"the env-bounded run must succeed, got {rc}"
    assert payload["dispatched"]["iterations_used"] == 1, (
        f"PLA_MAX_ITERATIONS=1 alone must bound the run to 1 iteration; got {payload['dispatched']}"
    )

    rc = main(_run_argv(ws, script, tmp_path / "flag-wins", "--json", "--max-iterations", "2"))
    payload = _one_json_object(capsys.readouterr().out, "flag-wins run")
    assert rc == 0, f"the flag-bounded run must succeed, got {rc}"
    assert payload["dispatched"]["iterations_used"] == 2, (
        f"--max-iterations 2 must beat PLA_MAX_ITERATIONS=1; got {payload['dispatched']}"
    )


# ===========================================================================
# Behavior 4 -- a bad value is a PARSE-time usage error, with no vendor dump
# ===========================================================================


@pytest.mark.parametrize("flag", sorted(BUDGET_FLAGS))
@pytest.mark.parametrize("bad", ["0"])
def test_b04a_a_non_positive_value_is_exit2_with_the_shipped_validator_message(
    flag: str, bad: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    rc, out, err = _usage_error(["run", "--workspace", str(ws), flag, bad], capsys)
    assert rc == 2, f"`run {flag} {bad}` must exit 2 (parse-time), got {rc}; stderr={err!r}"
    assert POSITIVE_INT_ERR in err, (
        f"stderr must carry {POSITIVE_INT_ERR!r} for `{flag} {bad}`; got:\n{err}"
    )
    assert flag in err, f"stderr must name the rejected flag; got:\n{err}"
    assert out == "", f"a rejected budget must print nothing on stdout; got:\n{out}"


@pytest.mark.parametrize("flag", sorted(BUDGET_FLAGS))
def test_b04a2_a_non_integer_value_is_the_same_exit2_usage_error(
    flag: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AMBIGUITY RESOLVED IN FAVOUR OF THE SHIPPED VALIDATOR, and recorded.

    ``pm.md`` behavior 4 asks for the ``must be a positive integer (>= 1)``
    sentence on all three of ``0`` / ``-1`` / ``abc``, but its own acceptance
    criteria mandate REUSING ``_positive_int`` and forbid a new validator, and
    those two requirements cannot both hold: ``argparse`` copies an
    ``ArgumentTypeError`` message through verbatim (so ``0`` and ``-1`` speak the
    sentence) while a plain ``ValueError`` out of ``int()`` is replaced by its own
    ``invalid <type> value: 'abc'`` wording. The shipped siblings ``scan --top``
    and ``watch --max-scans`` behave identically today, and ``SPEC.md`` 4.5 pins
    only "an argparse usage error (exit 2) at PARSE time" for the non-integer
    case -- so consistency with the shipped validator is the reading tested here.
    """
    ws = _workspace(tmp_path)
    rc, out, err = _usage_error(["run", "--workspace", str(ws), flag, "abc"], capsys)
    assert rc == 2, f"`run {flag} abc` must exit 2 (parse-time), got {rc}; stderr={err!r}"
    assert flag in err, f"stderr must name the rejected flag; got:\n{err}"
    assert "invalid" in err, f"stderr must call the value invalid; got:\n{err}"
    assert out == "", f"a rejected budget must print nothing on stdout; got:\n{out}"


@pytest.mark.parametrize("flag", sorted(BUDGET_FLAGS))
@pytest.mark.parametrize("bad", ["0", "abc"])
def test_b04b_the_pydantic_vendor_dump_never_reaches_the_user(
    flag: str, bad: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``pydantic.ValidationError`` IS a ``ValueError``, and ``main()`` catches
    ``ValueError`` -- so a budget validated by the model instead of by argparse
    would print the taxonomy line and the ``errors.pydantic.dev`` URL that SPEC
    pins as closed at this boundary."""
    ws = _workspace(tmp_path)
    _rc, _out, err = _usage_error(["run", "--workspace", str(ws), flag, bad], capsys)
    lowered = err.lower()
    leaked = [marker for marker in VENDOR_DUMP_MARKERS if marker.lower() in lowered]
    assert leaked == [], f"`{flag} {bad}` leaked the pydantic dump {leaked}; stderr:\n{err}"


@pytest.mark.parametrize("flag", sorted(BUDGET_FLAGS))
def test_b04c_rejection_happens_before_any_state_dir_or_provider_exists(
    flag: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two proofs of PARSE-time in one invocation.

    (1) The state dir is never created, so no run dir, slate or checkpoint
    exists. (2) ``--scripted-responses`` is deliberately OMITTED while the
    provider stays ``scripted``: constructing the client would raise the
    "no scripted_responses_path was configured" error and exit 1, so an exit of
    2 with the positive-integer message proves the parser refused first.
    """
    ws = _workspace(tmp_path)
    state_dir = tmp_path / "never-created"
    rc, _out, err = _usage_error(
        ["run", "--workspace", str(ws), "--state-dir", str(state_dir), flag, "0"], capsys
    )
    assert rc == 2, f"expected exit 2, got {rc}; stderr={err!r}"
    assert POSITIVE_INT_ERR in err, f"expected the argparse validator to speak; got:\n{err}"
    assert "scripted_responses" not in err, (
        f"the provider must not have been constructed; stderr:\n{err}"
    )
    assert not state_dir.exists(), (
        f"a parse-time rejection must create no state dir; found "
        f"{sorted(p.name for p in state_dir.iterdir())}"
    )


# ===========================================================================
# Behavior 5 -- it bounds a REAL run
# ===========================================================================


@pytest.mark.parametrize("budget", [1, 2])
def test_b05a_max_iterations_bounds_a_real_dispatched_loop(
    budget: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for var in BUDGET_FLAGS.values():
        monkeypatch.delenv(var, raising=False)
    ws = _workspace(tmp_path)
    script = _never_done_script(tmp_path)

    rc = main(_run_argv(ws, script, tmp_path / f"state-{budget}", "--json", "--max-iterations", str(budget)))
    payload = _one_json_object(capsys.readouterr().out, f"--max-iterations {budget}")

    assert rc == 0, f"a budget-exhausted run still exits 0, got {rc}"
    dispatched = payload.get("dispatched")
    assert isinstance(dispatched, dict), (
        f"the run must have auto-dispatched a goal; payload keys {sorted(payload)}"
    )
    assert dispatched["iterations_used"] == budget, (
        f"--max-iterations {budget} must spend exactly {budget} iteration(s); got {dispatched}"
    )
    assert dispatched["status"] == "budget_exhausted", (
        f"a CHECK that never reports done must end in budget_exhausted; got {dispatched['status']!r}"
    )


def test_b05b_max_llm_calls_bounds_the_same_run_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The second flag is not decoration: with iterations left unbounded, a
    2-call session budget stops the run on calls alone."""
    for var in BUDGET_FLAGS.values():
        monkeypatch.delenv(var, raising=False)
    ws = _workspace(tmp_path)
    script = _never_done_script(tmp_path)

    rc = main(_run_argv(ws, script, tmp_path / "calls", "--json", "--max-llm-calls", "2"))
    payload = _one_json_object(capsys.readouterr().out, "--max-llm-calls 2")

    assert rc == 0, f"a budget-exhausted run still exits 0, got {rc}"
    dispatched = payload["dispatched"]
    assert dispatched["llm_calls_used"] <= 2, (
        f"--max-llm-calls 2 must cap the session's model calls; got {dispatched}"
    )
    assert dispatched["status"] == "budget_exhausted", (
        f"expected budget_exhausted, got {dispatched['status']!r}"
    )


def test_b05c_the_bound_is_the_flags_doing_not_the_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-vacuity guard for behavior 5.

    The SAME workspace and the SAME never-done script, run with NO budget flag,
    must spend MORE than 2 iterations -- otherwise the two assertions above
    would pass on a script that simply ran out, and the flags would be proving
    nothing.
    """
    for var in BUDGET_FLAGS.values():
        monkeypatch.delenv(var, raising=False)
    ws = _workspace(tmp_path)
    script = _never_done_script(tmp_path)

    rc = main(_run_argv(ws, script, tmp_path / "unbounded", "--json"))
    payload = _one_json_object(capsys.readouterr().out, "unbounded run")
    assert rc == 0, f"the unbounded run must succeed, got {rc}"
    assert payload["dispatched"]["iterations_used"] > 2, (
        "the unbounded run must outlast the bounded ones, else the budget assertions are "
        f"vacuous; got {payload['dispatched']}"
    )
