"""Independent second opinion on factory iteration 297 -- the run dir RECORDS the
effective L1 budget, and every verb that produces a run dir records it.

MODULE NAME, derived from the repo and never from the state-dir counter (the
2026-08-19 operator pin). State dir is ``iter-384``; ``git log -1`` at the base of
this work is ``5f61ee0 ... (foundry iter 296)``, so the two counters differ by 87 and
the offset is NOT arithmetic anyone may reuse. The name was derived the mandated way:
``git ls-files tests`` holds 287 entries whose highest ``test_iterNN_behavior.py`` is
``261``, +1 = ``262``, and ``git cat-file -e HEAD:tests/test_iter262_behavior.py``
FAILED before a byte was written (the worktree path was absent too, so nothing was
overwritten).

WHY THIS MODULE COLLECTS ZERO ITEMS, and why that is a measured constraint rather
than a style choice. Live collection is 5,998 (``make readme-headroom``
-> ``live=5998 published=5900 floor=5900``). Four shipped modules
(``tests/test_iter238_behavior.py``, ``tests/test_iter245_behavior.py``,
``tests/test_iter250_behavior.py``, ``tests/test_iter256_behavior.py``) each assert
BOTH ``live // 100 * 100 == floor`` AND ``(live + 1) // 100 * 100 == floor``; the
second clause is the binding one, and it makes the FIRST additional collected item a
red public build. So this module defines no ``test_``-prefixed function at all: it is
a bank of oracle arms, and one already-collected function calls it. Every assertion
here therefore still runs on every ``uv run pytest``, for zero new items. (The looser
``SUITE_SIZE_SLACK`` gauge reports ``headroom=401``; it is not the gauge that binds.)

WHAT IT GRADES, and why these arms and not a re-derivation of the sibling's. The
arms already living in ``tests/test_iter253_behavior.py`` (``_b297_1`` ... ``_b297_5``)
drive the ``run`` -> ``resume`` path. Read against this iteration's spec they leave two
Expected Behaviors ungraded, and both are load-bearing:

* Behavior 1 says ``meta.json`` has **exactly four** keys. The sibling asserts each of
  the four is PRESENT and well-typed, which a five-key document also satisfies -- so
  the "exactly" half is assumed, never tested. An extra key is not cosmetic here: the
  document is the resume contract's input, and iteration 384's own acceptance criteria
  name the key set, not a minimum.
* Behavior 2 says the same holds after ``dispatch``. NOTHING drives ``dispatch`` in
  the sibling module, and ``dispatch`` is the harder case precisely because it owns no
  ``--max-*`` flag of its own (``UNOWNED_VERBS`` in the sibling pins that): its
  effective bound can only come from the environment or the default, so a record
  written from the FLAG rather than from the resolved setting would pass every
  ``run``-driven arm and still ship a dispatch-produced run dir that lies.

Behaviors 3, 4 and 5 are then re-graded ACROSS the dispatch boundary (env-bounded
dispatch -> clean-env resume -> env-overridden resume), which is the composition no
single-verb arm can reach.

Two further arms were added in the retry round, each closing a reading that every
assertion above passes:

* Arm 5 -- NOTHING anywhere grades what the record looks like AFTER a resume. Spec
  behaviors 1-2 name ``run`` and ``dispatch`` as the recording verbs and behavior 5
  makes the environment WIN over the record, so a resume that wrote its own
  env-derived bound back into ``meta.json`` would satisfy every other arm and still
  turn a one-off ``PLA_MAX_ITERATIONS=16`` into that run dir's permanent bound.
  Measured at this tree before it was encoded: the document is byte-identical across
  an env-overridden resume.
* Arm 6 -- arm 4 resumes a dispatched run that is already AT its bound, so "obeyed
  the recorded number" and "refused because the persisted status says exhausted"
  leave the checkpoint identical and the cheaper wrong reading passes (the iter-383
  lesson, in this module's own shape). Arm 6 records a bound the checkpoint has NOT
  reached, on the DISPATCH-produced dir, and demands the resume stop at exactly it.

ISOLATION CONTRACT (honored). Every assertion is written from this iteration's spec
(``pm.md`` Expected Behaviors 1-6 and its Acceptance Criteria), from the repo's own
``tests/`` conventions, and from the product's OBSERVABLE output obtained by RUNNING
it. **No file under ``src/`` was read, no engineer's or reviewer's note was opened,
no ``IMPLEMENTATION.patch`` and no ``git diff`` was inspected.** Fully offline and
deterministic: the bundled scripted provider only, no network, no API key. Nothing is
written inside the product repo -- every invocation is rooted at a private
``tmp_path`` copy of ``examples/fixture_workspace``, stamped to one fixed age so this
module reads the same on a fresh clone as it does here (the iter-278 lesson).

HARNESS REUSE, single-sourced on purpose. The subprocess/offline/JSON helpers are
IMPORTED from the sibling rather than re-spelled: a second private copy of
``_clean_env`` or ``_offline`` is exactly the drift shape factory iteration 266 spent
a whole increment deleting. The import is one-directional at module scope; the
sibling reaches back only through a function-local import inside the arm it hosts, so
there is no import cycle.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.test_iter253_behavior import (
    BUILTIN_BUDGET,
    RECORDED_BUDGET_KEYS,
    SCRIPT,
    _clean_env,
    _cli,
    _document,
    _offline,
    _resumed,
    _rewrite_meta,
    _sole_run_dir,
    _spent,
    _stamped_workspace,
)

#: Behavior 1/2: the complete key set ``meta.json`` must carry -- no more, no less.
#: Spelled once, as a SET, because the claim under test is set equality and an
#: ordered spelling would let a duplicate hide.
EXPECTED_META_KEYS: frozenset[str] = frozenset(
    {"workspace_root", "artifacts_dir", *RECORDED_BUDGET_KEYS}
)


def _slate(root: Path, workspace: Path, *, label: str) -> tuple[Path, str]:
    """One offline ``scan`` under a private state dir; returns ``(slate, goal_id)``.

    The goal id is read out of the slate the scan actually wrote, never composed,
    so a changed synthesis cannot make this module dispatch a goal that is not in
    the document ``dispatch`` will read.
    """
    slate = root / f"slate-{label}.json"
    proc = _cli(
        "scan",
        "--workspace",
        str(workspace),
        "--out",
        str(slate),
        *_offline(root / f"scan-state-{label}"),
        cwd=root,
    )
    assert proc.returncode == 0, (
        f"{label}: an offline scan must exit 0; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    doc = _document(slate)
    goals = doc.get("goals")
    assert isinstance(goals, list) and goals, (
        f"{label}: the scan must have written a non-empty `goals` list for "
        f"`dispatch` to have something to run; document keys: {sorted(doc)}"
    )
    top = goals[0]
    assert isinstance(top, dict), f"{label}: goal 0 must be an object, got {top!r}"
    goal_id = top.get("id")
    assert isinstance(goal_id, str) and goal_id, (
        f"{label}: the slate's top goal must carry a string `id` for `dispatch "
        f"--goal-id`; got {goal_id!r}\ngoal keys: {sorted(top)}"
    )
    return slate, goal_id


def _dispatched_run_dir(
    root: Path,
    workspace: Path,
    *,
    label: str,
    env: dict[str, str] | None = None,
) -> Path:
    """One offline ``scan`` + ``dispatch`` pair; returns the produced run dir.

    ``dispatch`` declares no budget flag, so whatever bounds this run can only
    come from ``env`` or from the built-in default -- which is precisely what
    behavior 2 needs graded.
    """
    slate, goal_id = _slate(root, workspace, label=label)
    state_dir = root / f"dispatch-state-{label}"
    proc = _cli(
        "dispatch",
        "--slate",
        str(slate),
        "--goal-id",
        goal_id,
        "--yes",
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(state_dir),
        cwd=root,
        env=env,
    )
    assert proc.returncode == 0, (
        f"{label}: an offline approved dispatch must exit 0; got {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    return _sole_run_dir(state_dir)


def _run_dir(
    root: Path,
    workspace: Path,
    *extra: str,
    label: str,
    env: dict[str, str] | None = None,
) -> Path:
    """One offline ``run`` under a private state dir; returns its run dir."""
    state_dir = root / f"run-state-{label}"
    proc = _cli(
        "run",
        "--workspace",
        str(workspace),
        *_offline(state_dir),
        *extra,
        cwd=root,
        env=env,
    )
    assert proc.returncode == 0, (
        f"{label}: an offline run must exit 0; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    return _sole_run_dir(state_dir)


def _assert_meta_key_set(run_dir: Path, *, verb: str, behavior: str) -> dict[str, object]:
    """The recorded document has EXACTLY the four contracted keys, all well-typed."""
    meta = _document(run_dir / "meta.json")
    keys = frozenset(meta)
    assert keys == EXPECTED_META_KEYS, (
        f"{behavior}: `{verb}` must record EXACTLY {sorted(EXPECTED_META_KEYS)} in "
        f"{run_dir.name}/meta.json. Extra keys {sorted(keys - EXPECTED_META_KEYS)}, "
        f"missing keys {sorted(EXPECTED_META_KEYS - keys)}\ndocument: {meta}"
    )
    for key in ("workspace_root", "artifacts_dir"):
        assert isinstance(meta[key], str) and meta[key], (
            f"{behavior}: `{verb}` must keep `{key}` a non-empty string -- it is the "
            f"one fact a checkpoint cannot supply; got {meta[key]!r}"
        )
    for key in RECORDED_BUDGET_KEYS:
        value = meta[key]
        assert isinstance(value, int) and not isinstance(value, bool) and value >= 1, (
            f"{behavior}: `{verb}` must record `{key}` as a JSON integer >= 1; "
            f"got {value!r}\ndocument: {meta}"
        )
    return meta


def iter384_arms(root: Path) -> None:
    """Every arm this module owns, in dependency order.

    Called from ONE already-collected test function, so these assertions cost zero
    new collected items (see this module's docstring for why that is binding).
    """
    workspace = _stamped_workspace(root / "ws")
    _arm_1_run_records_exactly_the_four_keys(root, workspace)
    _arm_2_dispatch_records_exactly_the_four_keys(root, workspace)
    _arm_3_dispatch_records_the_environment_bound_not_the_default(root, workspace)
    _arm_4_resume_of_a_dispatched_run_obeys_then_yields_to_the_environment(
        root, workspace
    )
    _arm_5_the_record_survives_the_resume_that_overrides_it(root, workspace)
    _arm_6_the_dispatch_record_is_read_as_a_number_not_a_status(root, workspace)


def _arm_1_run_records_exactly_the_four_keys(root: Path, workspace: Path) -> None:
    """Behavior 1: the key set is EXACT, on both the flagged and the default path.

    Both arms are needed: the flagged run proves an explicit bound adds no key, and
    the default run proves the resolved default is recorded rather than omitted --
    otherwise "absent" would mean both "no budget" and "the default budget".
    """
    flagged = _run_dir(root, workspace, "--max-iterations", "1", label="arm1-flagged")
    meta = _assert_meta_key_set(flagged, verb="run", behavior="behavior 1")
    assert meta["max_iterations"] == 1, (
        "behavior 1: `run --max-iterations 1` must record the flag's value, not the "
        f"built-in {BUILTIN_BUDGET['max_iterations']}; recorded {meta['max_iterations']!r}"
    )

    default = _run_dir(root, workspace, label="arm1-default")
    meta = _assert_meta_key_set(default, verb="run", behavior="behavior 1")
    for key, expected in BUILTIN_BUDGET.items():
        assert meta[key] == expected, (
            f"behavior 1: an unflagged run in a clean environment must record the "
            f"resolved default `{key}` = {expected}; recorded {meta[key]!r}"
        )

    # The record is a DOCUMENT, not a repr: a resume in another process has to parse
    # it, so the budget values must survive a JSON round trip as integers.
    raw = json.loads((default / "meta.json").read_text(encoding="utf-8"))
    assert [type(raw[k]) for k in RECORDED_BUDGET_KEYS] == [int, int], (
        "behavior 1: the recorded budget must be JSON numbers, not strings -- a "
        f"quoted bound is what a naive writer emits; got "
        f"{ {k: raw[k] for k in RECORDED_BUDGET_KEYS} }"
    )


def _arm_2_dispatch_records_exactly_the_four_keys(root: Path, workspace: Path) -> None:
    """Behavior 2: `dispatch` records the same document `run` does.

    ``dispatch`` owns no ``--max-*`` flag, so a record written from the flag rather
    than from the resolved setting would pass every ``run``-driven arm and still ship
    a dispatch-produced run dir with no budget in it.
    """
    run_dir = _dispatched_run_dir(root, workspace, label="arm2")
    meta = _assert_meta_key_set(run_dir, verb="dispatch", behavior="behavior 2")
    for key, expected in BUILTIN_BUDGET.items():
        assert meta[key] == expected, (
            f"behavior 2: a dispatch in a clean environment must record the resolved "
            f"default `{key}` = {expected}; recorded {meta[key]!r}"
        )


def _arm_3_dispatch_records_the_environment_bound_not_the_default(
    root: Path, workspace: Path
) -> None:
    """Behavior 3: the recorded value is the EFFECTIVE bound, post-env.

    Graded on the verb with no flag, which is the only place "effective" and
    "whatever the flag said" can be told apart. Both halves of the budget are
    driven, so a writer that persists one and defaults the other is caught.
    """
    run_dir = _dispatched_run_dir(
        root,
        workspace,
        label="arm3",
        env=_clean_env(PLA_MAX_ITERATIONS="1", PLA_MAX_LLM_CALLS="2"),
    )
    meta = _assert_meta_key_set(run_dir, verb="dispatch", behavior="behavior 3")
    for key, expected in (("max_iterations", 1), ("max_llm_calls", 2)):
        assert meta[key] == expected, (
            f"behavior 3: `PLA_{key.upper()}={expected}` in the dispatching process's "
            f"environment is that run's EFFECTIVE bound, so it is what must be "
            f"recorded; recorded {meta[key]!r} (the built-in is "
            f"{BUILTIN_BUDGET[key]})"
        )
        assert meta[key] != BUILTIN_BUDGET[key], (
            f"anti-vacuity: {key} must differ from the built-in "
            f"{BUILTIN_BUDGET[key]} or this arm would pass on a writer that records "
            f"the default unconditionally"
        )


def _arm_4_resume_of_a_dispatched_run_obeys_then_yields_to_the_environment(
    root: Path, workspace: Path
) -> None:
    """Behaviors 4 and 5, composed across the process boundary that motivates them.

    A dispatch bounded to one iteration by its environment is resumed twice:
    once with a CLEAN environment (the recorded bound is the only thing left that
    can hold it) and once with the bound RAISED (the environment must win). The
    second half is what makes the first half evidence rather than a tautology --
    "resume never spends anything" would satisfy behavior 4 all by itself.
    """
    run_dir = _dispatched_run_dir(
        root, workspace, label="arm4", env=_clean_env(PLA_MAX_ITERATIONS="1")
    )
    recorded = _document(run_dir / "meta.json")["max_iterations"]
    assert recorded == 1, (
        "behavior 4 precondition: the producing dispatch must have recorded the "
        f"bound of 1 its environment set; meta.json says {recorded!r}"
    )
    before = _spent(run_dir)
    assert before[1] == 1, (
        "behavior 4 precondition: the producing dispatch must have stopped AT its "
        f"one-iteration bound for a resume to have something to obey; checkpoint "
        f"says {before}"
    )

    clean = _resumed(run_dir, cwd=root, env=_clean_env())
    assert clean.returncode == 0, (
        "behavior 4: resuming a run that is already at its recorded bound is a "
        f"NORMAL outcome, not an error; exit {clean.returncode}\n"
        f"stderr:\n{clean.stderr}"
    )
    after = _spent(run_dir)
    assert after[1] == before[1], (
        "behavior 4: with no budget flag and no PLA_MAX_* in the environment, "
        "`resume` must continue under the RECORDED bound of 1 rather than the "
        f"built-in {BUILTIN_BUDGET['max_iterations']}. Iterations before "
        f"{before[1]}, after {after[1]} -- the bound the user set was discarded at "
        "the one place the product promises continuity."
    )

    raised = _resumed(
        run_dir, cwd=root, env=_clean_env(PLA_MAX_ITERATIONS="3", PLA_MAX_LLM_CALLS="24")
    )
    assert raised.returncode == 0, (
        "behavior 5: a resume whose environment RAISES the bound must still exit 0; "
        f"exit {raised.returncode}\nstderr:\n{raised.stderr}"
    )
    raised_spent = _spent(run_dir)
    assert raised_spent[1] > after[1], (
        "behavior 5: `PLA_MAX_ITERATIONS=3` in the environment must WIN over the "
        f"recorded bound of {recorded}, so the resume may spend past it. Iterations "
        f"stayed at {raised_spent[1]} -- the record has become a ceiling no operator "
        "can lift, which is stricter than the spec's precedence (env > recorded > "
        "default) and would also mean behavior 4 above is graded by a resume that "
        "never spends anything."
    )


def _arm_5_the_record_survives_the_resume_that_overrides_it(
    root: Path, workspace: Path
) -> None:
    """Behaviors 1 and 5 composed: overriding the record must not REWRITE it.

    The environment winning is behavior 5; the record still describing the run that
    produced it is behavior 1, one verb later. If a resume persisted its own
    effective bound, precedence would become sticky -- the next resume with a clean
    environment would inherit 16 instead of the 1 the user asked for, and the record
    would no longer be evidence of anything.
    """
    run_dir = _run_dir(root, workspace, "--max-iterations", "1", label="arm5")
    before = _assert_meta_key_set(run_dir, verb="run", behavior="behavior 1")
    assert before["max_iterations"] == 1, (
        "behavior 5 precondition: the producing run must have recorded the bound of "
        f"1 its flag set; meta.json says {before['max_iterations']!r}"
    )
    spent_before = _spent(run_dir)[1]

    raised = _resumed(run_dir, cwd=root, env=_clean_env(PLA_MAX_ITERATIONS="16"))
    assert raised.returncode == 0, (
        "behavior 5: a resume whose environment raises the bound must exit 0; exit "
        f"{raised.returncode}\nstderr:\n{raised.stderr}"
    )
    spent_after = _spent(run_dir)[1]
    assert isinstance(spent_before, int) and isinstance(spent_after, int), (
        f"the checkpoint must record integer iteration counts; got {spent_before!r} "
        f"then {spent_after!r}"
    )
    assert spent_after > spent_before, (
        "anti-vacuity for behavior 5: PLA_MAX_ITERATIONS=16 must actually let the "
        f"resume spend past the recorded bound of 1, or 'the record is unchanged' "
        f"would hold trivially on a resume that did nothing. Iterations stayed at "
        f"{spent_after}."
    )

    after = _assert_meta_key_set(
        run_dir, verb="run", behavior="behavior 1 (after an overridden resume)"
    )
    assert after == before, (
        "behavior 1/5: `resume` READS the record, it does not rewrite it -- the "
        "recording verbs are `run` and `dispatch`. After a resume overridden to 16 "
        f"the document says {after}, but the run it describes was bounded at "
        f"{before}. A persisted override makes a one-off environment variable that "
        "run dir's permanent bound."
    )


def _arm_6_the_dispatch_record_is_read_as_a_number_not_a_status(
    root: Path, workspace: Path
) -> None:
    """Behavior 4, sharpened on the verb that owns no budget flag.

    Three outcomes are separable here, which is the point:

    * ``("budget_exhausted", 3)`` -- the recorded NUMBER is the live bound. Correct.
    * ``("done", 4)`` -- the record was ignored and the built-in 8/24 applied.
    * ``("budget_exhausted", 1)`` -- only the persisted status was consulted.
    """
    run_dir = _dispatched_run_dir(
        root, workspace, label="arm6", env=_clean_env(PLA_MAX_ITERATIONS="1")
    )
    before = _spent(run_dir)
    assert before[:2] == ("budget_exhausted", 1), (
        "behavior 4 precondition: the dispatch must have stopped at the bound of 1 "
        f"its environment set, so the raised record below is unreached; checkpoint "
        f"says {before}"
    )

    bound = 3
    _rewrite_meta(run_dir, max_iterations=bound)
    proc = _resumed(run_dir, cwd=root, env=_clean_env())
    assert proc.returncode == 0, (
        "behavior 4: resuming a dispatched run under its recorded bound must exit 0; "
        f"exit {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    status, iterations, _ = _spent(run_dir)
    assert (status, iterations) == ("budget_exhausted", bound), (
        f"behavior 4: with `max_iterations: {bound}` recorded in a DISPATCH-produced "
        f"run dir and nothing in the environment, the resume must spend up to exactly "
        f"{bound} iteration(s) and stop. Checkpoint says {(status, iterations)} -- "
        "('done', 4) means the record was ignored and the 8/24 default applied, "
        "('budget_exhausted', 1) means only the persisted status was read, never the "
        "number."
    )
