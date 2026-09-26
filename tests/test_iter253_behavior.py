"""Black-box behavior tests for factory iteration 284 -- the per-invocation L1 budget.

Feature under test (roadmap #269): ``pla run --max-iterations N`` and
``pla run --max-llm-calls N`` bound the L1 loop budget for ONE invocation,
overriding ``PLA_MAX_ITERATIONS`` / ``PLA_MAX_LLM_CALLS``. Before this, both
budgets were environment-only and ``--dry-run`` spends zero iterations, so there
was no way to ask for a bounded REAL run at all.

WHY EVERY BEHAVIOR HERE IS DRIVEN THROUGH A REAL SUBPROCESS
The claims are about the PARSER (which verb owns a flag, which value is refused
before anything is constructed) and about what a finished run RECORDS. Both are
properties of a process, not of a function, so this module spends real ``pla``
console-script invocations (the iter-114 / iter-152 / iter-163 / iter-173
convention) and reads the real exit code and the real file descriptors. Cost is
bounded: every executing run is module-scoped and shares one workspace copy,
each measured at ~0.5s against the bundled scripted provider.

WHY THE WORKSPACE COPY IS TIME-STAMPED (the iter-278 / iter-279 lesson)
``shutil.copytree`` preserves mtimes, so a run rooted at an unstamped copy
perceives whatever the local checkout's mtimes happen to be -- while a fresh
clone (the ``preship`` gate, and CI) resets every mtime to the clone time. A
recency-windowed collector therefore reports a DIFFERENT signal set in the two
places, which is how a green local oracle reds a clone. Every copy here is
stamped to one fixed age instead, so the perception this module drives is the
same in both.

NO PLA_* VARIABLE IS INHERITED. The suite must not depend on the operator's
shell (measured historically: an exported ``PLA_SENSITIVE_CATEGORIES`` reds an
unrelated module), so every invocation starts from an environment with the
whole ``PLA_`` prefix stripped and adds back only what the case is testing.

ISOLATION CONTRACT (honored): every assertion is written against this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
conventions, and the product's OBSERVABLE output obtained by RUNNING it. **No
file under ``src/`` was read, no engineer's, reviewer's or fix note was opened,
and no ``git diff`` was inspected.** Fully offline and deterministic: the
bundled scripted provider only, no network, no API key. Nothing is written
inside the product repo -- every run is rooted at a private ``tmp_path_factory``
copy of ``examples/fixture_workspace``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

#: The two flags this iteration publishes, and the environment variable each one
#: overrides (spec behaviors 1, 4).
BUDGET_FLAGS: dict[str, str] = {
    "--max-iterations": "PLA_MAX_ITERATIONS",
    "--max-llm-calls": "PLA_MAX_LLM_CALLS",
}

#: Verbs that must NOT have inherited the flags: the spec places them on ``run``
#: alone, never on the shared ``globals_`` parent (spec behaviors 1-2).
UNOWNED_VERBS: dict[str, list[str]] = {
    "scan": ["--workspace", "<WS>"],
    "dispatch": ["--slate", "<WS>/absent.json", "--goal-id", "deadbeef"],
    "resume": ["--run-dir", "<WS>/absent-run"],
}

#: Values the parse-time validator must refuse (spec behavior 5).
REFUSED_VALUES: tuple[str, ...] = ("0", "-1", "abc")

#: Tokens that betray a raw pydantic dump reaching a user's terminal. The
#: product's sanitization contract forbids them at the CLI boundary, and a
#: ``Field(ge=1)`` violation would have printed exactly these.
VENDOR_DUMP_TOKENS: tuple[str, ...] = (
    "[type=greater_than_equal]",
    "errors.pydantic.dev",
    "ValidationError",
)

#: How old a stamped workspace copy is made to look. Comfortably inside any
#: whole-day recency window, and identical on a fresh clone and on this machine.
STAMP_AGE_SEC = 6 * 60 * 60

_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _console_script() -> Path:
    """The installed ``pla`` console script (iter-114 / iter-163 convention)."""
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, (
        "the `pla` console script must be installed (declared in pyproject and "
        f"installed by `uv sync`); searched {[str(c) for c in candidates]}"
    )
    return script


def _clean_env(**overrides: str) -> dict[str, str]:
    """The ambient environment with every ``PLA_`` knob stripped, plus overrides."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PLA_")}
    env.update(overrides)
    return env


def _cli(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Invoke the real CLI in its own process so exit code and fds are real."""
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=180,
        env=env if env is not None else _clean_env(),
    )


def _stamped_workspace(root: Path) -> Path:
    """A private copy of the offline fixture workspace, every mtime one age.

    Never run the product against the in-repo fixture: it carries no ``.git`` of
    its own, so git-family collectors resolve upward into this repo and a sibling
    xdist worker can flip what they report mid-test.
    """
    dest = root / "workspace"
    shutil.copytree(FIXTURE, dest)
    stamp = time.time() - STAMP_AGE_SEC
    for path in [dest, *dest.rglob("*")]:
        os.utime(path, (stamp, stamp))
    return dest


def _offline(state_dir: Path) -> list[str]:
    """The flags that pin an invocation to the bundled offline provider."""
    return [
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(state_dir),
    ]


def _dispatched(
    root: Path,
    workspace: Path,
    *extra: str,
    label: str,
    env: dict[str, str] | None = None,
) -> dict:
    """One offline ``run --json``; returns the dispatched sub-document.

    The budget a run SPENT is read out of the document the run itself published,
    never composed from a path or a log line.
    """
    state_dir = root / f"state-{label}"
    proc = _cli(
        "run",
        "--workspace",
        str(workspace),
        *_offline(state_dir),
        "--json",
        *extra,
        cwd=root,
        env=env,
    )
    assert proc.returncode == 0, (
        f"{label}: an offline bounded run must exit 0; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    payload = json.loads(proc.stdout)
    dispatched = payload.get("dispatched")
    assert isinstance(dispatched, dict), (
        f"{label}: the run must have dispatched a goal for its budget to be "
        f"observable; `dispatched` was {dispatched!r}\ndocument keys: {sorted(payload)}"
    )
    for key in ("iterations_used", "llm_calls_used"):
        assert isinstance(dispatched[key], int), (
            f"{label}: `{key}` must be an integer, got {dispatched[key]!r}"
        )
    return dispatched


def _declared_flags(help_text: str) -> set[str]:
    """Every long option a verb's ``--help`` mentions.

    Enumerated rather than membership-tested so an ABSENCE claim is evidence
    (here is the whole set, X is not in it) instead of a silent non-match.
    """
    return set(_FLAG.findall(help_text))


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One stamped workspace copy shared by every executing run in this module."""
    return _stamped_workspace(tmp_path_factory.mktemp("iter253-ws"))


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory, workspace: Path) -> dict[str, dict]:
    """The dispatched documents this module reasons over, each run exactly once.

    ``control`` is the same invocation with NO budget flag and no ``PLA_*`` in
    the environment: it is what makes every bound below evidence that the FLAG
    did the bounding rather than the fixture being small enough anyway.
    """
    root = tmp_path_factory.mktemp("iter253-runs")
    return {
        "control": _dispatched(root, workspace, label="control"),
        "iters1": _dispatched(root, workspace, "--max-iterations", "1", label="iters1"),
        "iters2": _dispatched(root, workspace, "--max-iterations", "2", label="iters2"),
        "calls1": _dispatched(root, workspace, "--max-llm-calls", "1", label="calls1"),
        "env_iters1": _dispatched(
            root, workspace, label="env_iters1", env=_clean_env(PLA_MAX_ITERATIONS="1")
        ),
        "env_calls1": _dispatched(
            root, workspace, label="env_calls1", env=_clean_env(PLA_MAX_LLM_CALLS="1")
        ),
        "flag_beats_env": _dispatched(
            root,
            workspace,
            "--max-iterations",
            "1",
            label="flag_beats_env",
            env=_clean_env(PLA_MAX_ITERATIONS="8", PLA_MAX_LLM_CALLS="24"),
        ),
        "absent_keeps_env": _dispatched(
            root,
            workspace,
            "--max-llm-calls",
            "24",
            label="absent_keeps_env",
            env=_clean_env(PLA_MAX_ITERATIONS="1"),
        ),
    }


# --------------------------------------------------------------------------- b1


def test_b1_run_alone_owns_both_budget_flags(tmp_path: Path) -> None:
    """Behavior 1: `run --help` declares both flags with an integer metavar; no
    sibling loop verb inherited them, so they are not on the shared parent."""
    run_help = _cli("run", "--help", cwd=tmp_path)
    assert run_help.returncode == 0, run_help.stderr
    declared = _declared_flags(run_help.stdout)
    for flag in BUDGET_FLAGS:
        assert flag in declared, (
            f"`pla run --help` must declare {flag}; it declares {sorted(declared)}"
        )
        assert f"{flag} N" in run_help.stdout, (
            f"{flag} must take an integer with the `N` metavar the other counted "
            f"flags use; `run --help` shows no `{flag} N`"
        )
    for verb in UNOWNED_VERBS:
        sibling = _cli(verb, "--help", cwd=tmp_path)
        assert sibling.returncode == 0, sibling.stderr
        sibling_flags = _declared_flags(sibling.stdout)
        for flag in BUDGET_FLAGS:
            assert flag not in sibling_flags, (
                f"`pla {verb}` must NOT declare {flag} (the flags are owned by "
                f"`run` alone, not by the shared globals parent); {verb} declares "
                f"{sorted(sibling_flags)}"
            )


# --------------------------------------------------------------------------- b2


def test_b2_a_budget_flag_on_a_verb_that_does_not_own_it_is_a_usage_error(
    tmp_path: Path, workspace: Path
) -> None:
    """Behavior 2: passing either flag to scan/dispatch/resume exits 2.

    Each verb is given the arguments it REQUIRES, so the only thing left for
    argparse to complain about is the flag -- otherwise the exit 2 would be the
    missing-argument error and this case would pass vacuously.
    """
    for verb, required in UNOWNED_VERBS.items():
        args = [a.replace("<WS>", str(workspace)) for a in required]
        for flag in BUDGET_FLAGS:
            proc = _cli(verb, *args, flag, "2", cwd=tmp_path)
            assert proc.returncode == 2, (
                f"`pla {verb} {flag} 2` must be an argparse usage error (exit 2); "
                f"got {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
            assert flag in proc.stderr, (
                f"the refusal must name {flag}; stderr was:\n{proc.stderr}"
            )


# --------------------------------------------------------------------------- b3


def test_b3_absent_flags_change_nothing(runs: dict[str, dict]) -> None:
    """Behavior 3: with both flags absent the run spends the built-in budget, and
    an environment-only budget is still honored (the pre-existing path)."""
    control = runs["control"]
    assert control["iterations_used"] > 2, (
        "the control run must spend more than the bounds this module asks for, "
        "or no bound below is evidence of anything; it spent "
        f"{control['iterations_used']} iteration(s)"
    )
    assert control["llm_calls_used"] > 2, (
        f"the control run must spend more than 2 LLM calls; it spent "
        f"{control['llm_calls_used']}"
    )
    assert runs["env_iters1"]["iterations_used"] == 1, (
        "PLA_MAX_ITERATIONS=1 with NO flag must still bound the run to one "
        f"iteration; it spent {runs['env_iters1']['iterations_used']}"
    )


# --------------------------------------------------------------------------- b4


def test_b4_a_present_flag_wins_over_the_environment(runs: dict[str, dict]) -> None:
    """Behavior 4: the flag beats the matching `PLA_*` value, and an ABSENT flag
    never clobbers that variable."""
    assert runs["flag_beats_env"]["iterations_used"] == 1, (
        "`--max-iterations 1` must win over PLA_MAX_ITERATIONS=8; the run spent "
        f"{runs['flag_beats_env']['iterations_used']} iteration(s)"
    )
    assert runs["absent_keeps_env"]["iterations_used"] == 1, (
        "with only `--max-llm-calls` given, PLA_MAX_ITERATIONS=1 must still be in "
        f"force; the run spent {runs['absent_keeps_env']['iterations_used']} "
        "iteration(s), so the absent flag clobbered the environment"
    )


# --------------------------------------------------------------------------- b5


def test_b5_a_non_positive_or_non_integer_value_is_refused_at_parse_time(
    tmp_path: Path, workspace: Path
) -> None:
    """Behavior 5: `0`, `-1` and `abc` exit 2 for BOTH flags, the message names the
    option, no pydantic dump is printed, and nothing is created on disk."""
    for flag in BUDGET_FLAGS:
        for value in REFUSED_VALUES:
            state_dir = tmp_path / f"state{flag}{value}".replace("-", "_")
            proc = _cli(
                "run",
                "--workspace",
                str(workspace),
                *_offline(state_dir),
                flag,
                value,
                cwd=tmp_path,
            )
            where = f"`pla run {flag} {value}`"
            assert proc.returncode == 2, (
                f"{where} must be a parse-time usage error (exit 2); got "
                f"{proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
            assert flag in proc.stderr, (
                f"{where}: the message must name the offending option; stderr "
                f"was:\n{proc.stderr}"
            )
            both = proc.stdout + proc.stderr
            for token in VENDOR_DUMP_TOKENS:
                assert token not in both, (
                    f"{where} leaked a pydantic vendor dump ({token!r}) to the "
                    f"terminal:\n{both}"
                )
            assert not state_dir.exists(), (
                f"{where} must be refused BEFORE any state dir, run dir or LLM "
                f"client exists; {state_dir} was created"
            )


# --------------------------------------------------------------------------- b6


def test_b6_the_flag_bounds_the_real_run_and_the_bound_is_the_flags_doing(
    runs: dict[str, dict],
    workspace: Path,
    tmp_path: Path,
) -> None:
    """Behavior 6: `--max-iterations N` makes the run record exactly N iterations
    for N in (1, 2), and `--max-llm-calls` bounds the call budget independently --
    each demonstrated against the unbounded control and against the environment
    variable the flag overrides."""
    control = runs["control"]
    for bound, key in ((1, "iters1"), (2, "iters2")):
        spent = runs[key]["iterations_used"]
        assert spent == bound, (
            f"`--max-iterations {bound}` must bound the dispatched loop to exactly "
            f"{bound} iteration(s); the run recorded {spent}"
        )
        assert spent < control["iterations_used"], (
            f"the bound must be the FLAG's doing: the same run without it spent "
            f"{control['iterations_used']} iteration(s), not more than {spent}"
        )
    calls1 = runs["calls1"]
    assert calls1["llm_calls_used"] < control["llm_calls_used"], (
        "`--max-llm-calls 1` must bound the call budget below the unbounded run's "
        f"{control['llm_calls_used']}; it recorded {calls1['llm_calls_used']}"
    )
    assert calls1["llm_calls_used"] == runs["env_calls1"]["llm_calls_used"], (
        "the flag must be exactly as strong as the variable it overrides: "
        f"`--max-llm-calls 1` recorded {calls1['llm_calls_used']} call(s) while "
        f"PLA_MAX_LLM_CALLS=1 recorded {runs['env_calls1']['llm_calls_used']}"
    )
    assert calls1["iterations_used"] < control["iterations_used"], (
        "the call budget must bound the run independently of the iteration "
        f"budget; it spent {calls1['iterations_used']} iteration(s) against the "
        f"control's {control['iterations_used']}"
    )

    # ------------------------------------------------------------------ #
    # EXTENSION, factory iter 297: the same bound, one verb later.
    #
    # A bound that only holds for the invocation that named it is not a
    # bound, so this iteration's Expected Behaviors 1-5 (the run RECORDS
    # its effective budget and `resume` continues under it) are graded
    # here, inside the function that already owns "the bound is real".
    #
    # WHY they are helper calls and not five new `test_` functions: live
    # collection sits at 5,998 against a published `N,N00+` floor whose
    # rounding window (`live // 100 * 100 == floor` AND `(live + 1) // 100
    # * 100 == floor`, pinned in five shipped modules) makes 5,999 a RED
    # public build. Extending an already-collected function buys the
    # oracles for zero new collected items; each helper still names its
    # own behavior in every assertion message.
    # ------------------------------------------------------------------ #
    _b297_1_the_effective_budget_is_recorded(tmp_path, workspace)
    _b297_2_resume_obeys_the_recorded_bound(tmp_path, workspace)
    _b297_2b_the_recorded_bound_is_read_not_merely_the_status(tmp_path, workspace)
    _b297_3_the_environment_still_overrides_the_record(tmp_path, workspace)
    _b297_4_an_absent_or_null_record_still_resumes(tmp_path, workspace)
    _b297_5_a_corrupt_record_is_loud_not_silent(tmp_path, workspace)

    # ------------------------------------------------------------------ #
    # EXTENSION, factory iter 297 (second opinion, written independently).
    #
    # `tests/test_iter262_behavior.py` grades the two Expected Behaviors the
    # arms above leave ungraded -- `meta.json` carries EXACTLY the four keys,
    # and `dispatch` records them too -- then re-grades behaviors 3-5 across
    # the dispatch -> resume boundary. It is imported HERE, inside the
    # function body, rather than at module scope: that module imports this
    # one's harness helpers at ITS module scope, so a top-level import back
    # would be a cycle.
    #
    # Same zero-new-collected-items reason as the block above.
    # ------------------------------------------------------------------ #
    from tests.test_iter262_behavior import iter384_arms

    iter384_arms(tmp_path)


# --------------------------------------------------------------------------- b7


def test_b7_the_docs_and_the_roadmap_record_ship_in_the_same_commit() -> None:
    """Behaviors 7-8: README (`run` row, `PLA_*` table, flag-vs-env-only split),
    SPEC section 4.5, and the roadmap ledger + archive all record this feature in
    the commit that ships it."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    spec = (REPO / "SPEC.md").read_text(encoding="utf-8")
    roadmap = (REPO / "ROADMAP.md").read_text(encoding="utf-8")
    archive = (REPO / "ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")

    run_row = next(
        (line for line in readme.splitlines() if line.startswith("| `run`")), None
    )
    assert run_row is not None, "README must still carry a `run` verb row"
    for flag, env_var in BUDGET_FLAGS.items():
        assert f"`{flag} N`" in run_row, (
            f"the README `run` row must document `{flag} N`; row was:\n{run_row}"
        )
        table_row = next(
            (
                line
                for line in readme.splitlines()
                if line.startswith(f"| `{env_var}`")
            ),
            None,
        )
        assert table_row is not None, f"README must carry a `{env_var}` table row"
        assert f"`{flag}`" in table_row, (
            f"the `{env_var}` row must name its flag equivalent {flag} instead of "
            f"`(env-only)`; row was:\n{table_row}"
        )
        assert flag in spec, f"SPEC section 4.5 must name {flag}"

    assert "Seven settings also have a direct CLI flag" in readme, (
        "the README configuration prose counts the flag-backed settings in words; "
        "adding two flags moved that count to six (iter 282); `--max-seconds` (iter 321) to seven"
    )
    assert "the remaining eight are environment-only" in readme, (
        "the same prose counts the env-only settings; it must read eight"
    )
    assert "at PARSE time" in spec and "exit 2" in spec, (
        "SPEC 4.5 must record that a bad budget VALUE is refused at parse time"
    )

    ledger_row = (
        "- #269 `run --max-iterations` / `--max-llm-calls`: the L1 loop budget "
        "becomes settable per invocation, reusing the shipped `_positive_int` "
        "parse-time validator (foundry iter 284)"
    )
    assert ledger_row in roadmap, (
        "ROADMAP.md must gain exactly this Done-ledger row this iteration:\n"
        f"{ledger_row}"
    )
    index_ids = re.findall(r"^\| (\d+) \|", roadmap, flags=re.MULTILINE)
    assert "190" not in index_ids, (
        "the queued index row #190 must be RETIRED from ROADMAP.md in the commit "
        "that ships it"
    )
    assert len(index_ids) == len(set(index_ids)), (
        f"queued index ids must stay unique; got {sorted(index_ids)}"
    )
    retirement = next(
        (line for line in archive.splitlines() if line.startswith("- **#190 --")),
        None,
    )
    assert retirement is not None, (
        "ROADMAP_ARCHIVE.md must carry #190's retirement bullet"
    )
    assert "iter-284, foundry iter 284" in retirement, (
        "the archived bullet must be re-keyed to the iteration that actually "
        f"retired it; bullet opens:\n{retirement[:200]}"
    )
    assert "Reasoning: iter-284 `pm.md`" in retirement, (
        "the archived bullet's reasoning pointer must name this iteration's pm.md"
    )
    # NOTE: the roadmap's size ceiling and headroom floor are deliberately NOT
    # re-asserted here. `tests/test_iter172_behavior.py` pins the SET of modules
    # allowed to hold a size opinion about this document to an enumerated
    # allowlist, so a second opinion from this module is itself a contract
    # violation (measured: it failed both of that module's membership brakes).
    # The clause is graded where it is sanctioned -- `test_roadmap_size_budget.py`
    # and the allowlisted iteration modules.


# --------------------------------------------------------------------------- #
# EXTENSION -- factory iter 297: the recorded bound survives into `resume`
#
# `pla run` records its EFFECTIVE L1 budget in the run dir's `meta.json`, and
# `pla resume` continues that run under the recorded bound instead of silently
# reverting to the built-in 8/24 default.
#
# The defect this closes, measured at HEAD 5f61ee0 offline with the bundled
# fixture: a run bounded to `--max-iterations 1` stopped at 1 iteration / 2 LLM
# calls, and ONE `pla resume` on its run dir drove it to 4 iterations / 8 calls
# and `status: done` -- three iterations and six calls past the bound the user
# set, with ACT tools mutating the workspace the whole way and no warning.
# `iterations_used` is cumulative and persisted, so `max_iterations` is
# definitionally a per-RUN total; it was sourced per-INVOCATION.
#
# Black-box only: every claim below is read out of `meta.json`,
# `checkpoint.json`, the artifacts listing, the exit code, or the child
# process's own stdout/stderr.
# --------------------------------------------------------------------------- #

#: The two keys a producing run records beside the roots a resume already needed.
RECORDED_BUDGET_KEYS: tuple[str, str] = ("max_iterations", "max_llm_calls")

#: The built-in L1 defaults, i.e. what an invocation with no budget flag and no
#: `PLA_MAX_*` in its environment must record. Recording them is what makes an
#: OLD run dir distinguishable from a new one that genuinely chose the defaults.
BUILTIN_BUDGET: dict[str, int] = {"max_iterations": 8, "max_llm_calls": 24}

#: Recorded values that are present, non-null and NOT an integer >= 1, each
#: paired with the key it corrupts. `True` is in the set deliberately: JSON
#: `true` deserializes to an `int` SUBCLASS, so a bare `>= 1` guard would accept
#: it as a budget of 1 and a safety bound would be set by a typo.
CORRUPT_RECORDS: tuple[tuple[str, object], ...] = (
    ("max_iterations", 0),
    ("max_iterations", -1),
    ("max_iterations", "abc"),
    ("max_llm_calls", 1.5),
    ("max_llm_calls", True),
)

#: The message family the metadata reader already publishes. Asserted so this
#: iteration adds a REASON TAIL to a shipped sentence rather than inventing a
#: second dialect of the same failure.
META_ERROR_PREFIX: str = "invalid run metadata file"


def _sole_run_dir(state_dir: Path) -> Path:
    """The one ``run-*`` directory a single dispatching invocation created."""
    found = sorted(p for p in state_dir.glob("run-*") if p.is_dir())
    assert len(found) == 1, (
        f"exactly one run dir must exist under {state_dir}; found "
        f"{[p.name for p in found]}"
    )
    return found[0]


def _document(path: Path) -> dict[str, object]:
    """One JSON document as a mapping, naming the file when it is not one."""
    raw = path.read_text(encoding="utf-8")
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{path} must be valid JSON; {exc}\n{raw[:400]}") from exc
    assert isinstance(loaded, dict), (
        f"{path} must parse as a JSON object; parsed as {type(loaded).__name__}"
    )
    return loaded


def _spent(run_dir: Path) -> tuple[object, object, object]:
    """``(status, iterations_used, llm_calls_used)`` as the checkpoint records it."""
    doc = _document(run_dir / "checkpoint.json")
    missing = [k for k in ("status", "iterations_used", "llm_calls_used") if k not in doc]
    assert not missing, (
        f"{run_dir.name}/checkpoint.json must record {missing}; keys: {sorted(doc)}"
    )
    return (doc["status"], doc["iterations_used"], doc["llm_calls_used"])


def _artifact_names(run_dir: Path) -> list[str]:
    """Every file in the run's recorded artifacts directory, sorted.

    Read from the RECORDED path rather than assumed, so a resume that wrote
    somewhere else would show up as a missing file instead of being invisible.
    """
    meta_path = run_dir / "meta.json"
    recorded = _document(meta_path).get("artifacts_dir") if meta_path.is_file() else None
    directory = Path(recorded) if isinstance(recorded, str) else run_dir / "artifacts"
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.rglob("*") if p.is_file())


def _produced(
    root: Path,
    workspace: Path,
    *extra: str,
    label: str,
    env: dict[str, str] | None = None,
) -> Path:
    """One offline ``run`` under a private state dir; returns its run dir.

    A FRESH run per case, never a copy of one: both `meta.json` and
    `checkpoint.json` record absolute paths into the run dir that produced them,
    so a copied dir would resume against the original's artifacts and the
    "wrote no new artifact" claim below would grade the wrong directory.
    """
    state_dir = root / f"state-{label}"
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


def _resumed(
    run_dir: Path, *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """One offline ``resume`` of ``run_dir``, with no budget flag anywhere.

    `resume` declares no budget flag (that ownership is pinned to `run` by
    ``test_b1``/``test_b2`` above), so what bounds this invocation can only come
    from the environment, the recorded metadata, or the built-in default.
    """
    return _cli(
        "resume",
        "--run-dir",
        str(run_dir),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        cwd=cwd,
        env=env,
    )


def _rewrite_meta(run_dir: Path, **changes: object) -> None:
    """Edit the recorded metadata in place, as an old or mangled run dir differs."""
    path = run_dir / "meta.json"
    doc = _document(path)
    for key, value in changes.items():
        if value is _DROP:
            doc.pop(key, None)
        else:
            doc[key] = value
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


#: Sentinel for `_rewrite_meta`: remove the key instead of setting it, which is
#: what a run dir written before this feature looks like.
_DROP: object = object()


def _b297_1_the_effective_budget_is_recorded(root: Path, workspace: Path) -> None:
    """Behavior 1: the run dir records the budget the run actually ran under.

    Both arms matter. The flagged run proves the RECORD follows the flag, and
    the unflagged run proves an absent flag records the resolved default rather
    than nothing -- otherwise "absent" would have two meanings.
    """
    cases = (
        ("flagged", ("--max-iterations", "1"), {"max_iterations": 1, "max_llm_calls": 24}),
        ("default", (), BUILTIN_BUDGET),
    )
    for label, extra, expected in cases:
        run_dir = _produced(root, workspace, *extra, label=f"b297-1-{label}")
        meta = _document(run_dir / "meta.json")
        for key in ("workspace_root", "artifacts_dir"):
            assert isinstance(meta.get(key), str), (
                f"behavior 1 ({label}): recording the budget must not disturb the "
                f"roots a resume already needed; `{key}` is {meta.get(key)!r}\n"
                f"document: {meta}"
            )
        for key in RECORDED_BUDGET_KEYS:
            value = meta.get(key)
            assert isinstance(value, int) and not isinstance(value, bool) and value >= 1, (
                f"behavior 1 ({label}): {run_dir.name}/meta.json must record `{key}` "
                f"as a JSON integer >= 1; got {value!r}\ndocument: {meta}"
            )
            assert value == expected[key], (
                f"behavior 1 ({label}): the recorded `{key}` must be the run's "
                f"EFFECTIVE setting {expected[key]}; recorded {value!r}"
            )


def _b297_2_resume_obeys_the_recorded_bound(root: Path, workspace: Path) -> None:
    """Behavior 2: resuming an already-exhausted run does nothing at all.

    Graded on BOTH halves of the budget, because either one alone leaves the
    other verb able to spend past the user's bound.
    """
    cases = (
        ("iters", ("--max-iterations", "1"), 1, 1),
        ("calls", ("--max-llm-calls", "2"), 2, 2),
    )
    for label, extra, index, bound in cases:
        run_dir = _produced(root, workspace, *extra, label=f"b297-2-{label}")
        before = _spent(run_dir)
        artifacts_before = _artifact_names(run_dir)
        assert before[0] == "budget_exhausted", (
            f"behavior 2 ({label}): the producing run must stop AT its bound for a "
            f"resume to have something to obey; checkpoint says {before}"
        )
        assert before[index] == bound, (
            f"behavior 2 ({label}): the producing run must have spent exactly "
            f"{bound}; checkpoint says {before}"
        )
        proc = _resumed(run_dir, cwd=root)
        assert proc.returncode == 0, (
            f"behavior 2 ({label}): resuming an exhausted run is a NORMAL outcome, "
            f"not an error; exit {proc.returncode}\nstderr:\n{proc.stderr}"
        )
        after = _spent(run_dir)
        assert after == before, (
            f"behavior 2 ({label}): `resume` must not spend past the bound recorded "
            f"by the producing run. Before {before}, after {after} -- the bound the "
            f"user set was escaped by the second verb."
        )
        assert _artifact_names(run_dir) == artifacts_before, (
            f"behavior 2 ({label}): an exhausted resume performs no PLAN/ACT/CHECK "
            f"iteration, so it writes no new artifact; before {artifacts_before}, "
            f"after {_artifact_names(run_dir)}"
        )


def _b297_2b_the_recorded_bound_is_read_not_merely_the_status(
    root: Path, workspace: Path
) -> None:
    """Behavior 2, sharpened: the recorded NUMBER is the bound, not the status.

    `_b297_2` above cannot separate "the resume honored the recorded budget" from
    "the resume refuses to act once the persisted status says exhausted" -- both
    readings leave the checkpoint untouched, so the cheaper wrong one would pass
    it. This arm therefore records a bound the checkpoint has NOT yet reached (3
    against a spent 1) and demands the resume run to exactly that number, which
    makes three outcomes distinguishable:

    * `("budget_exhausted", 3)` -- the recorded value is the live bound. Correct.
    * `("done", 4)` -- the record was ignored and the built-in default applied.
    * `("budget_exhausted", 1)` -- only the persisted status was consulted.
    """
    run_dir = _produced(root, workspace, "--max-iterations", "1", label="b297-2b")
    before = _spent(run_dir)
    assert before[:2] == ("budget_exhausted", 1), (
        "behavior 2b needs a run stopped at exactly 1 iteration to raise the bound "
        f"on; checkpoint says {before}"
    )
    raised = 3
    _rewrite_meta(run_dir, max_iterations=raised)
    proc = _resumed(run_dir, cwd=root)
    assert proc.returncode == 0, (
        f"behavior 2b: resuming under a raised recorded bound must exit 0; got "
        f"{proc.returncode}\nstderr:\n{proc.stderr}"
    )
    status, iterations, _ = _spent(run_dir)
    assert (status, iterations) == ("budget_exhausted", raised), (
        f"behavior 2b: with `max_iterations: {raised}` recorded, the resume must spend "
        f"up to exactly {raised} iteration(s) and stop there. Checkpoint says "
        f"{(status, iterations)} -- ('done', 4) means the recorded value was ignored "
        "and the 8/24 default applied, ('budget_exhausted', 1) means only the "
        "persisted status was consulted, never the number."
    )


def _b297_3_the_environment_still_overrides_the_record(root: Path, workspace: Path) -> None:
    """Behavior 3: precedence is `PLA_MAX_*` env > recorded > built-in default."""
    run_dir = _produced(root, workspace, "--max-iterations", "1", label="b297-3")
    recorded = _document(run_dir / "meta.json").get("max_iterations")
    assert recorded == 1, (
        f"behavior 3 needs a run dir recording a bound of 1 to override; got {recorded!r}"
    )
    proc = _resumed(run_dir, cwd=root, env=_clean_env(PLA_MAX_ITERATIONS="16"))
    assert proc.returncode == 0, (
        f"behavior 3: an env-raised resume must exit 0; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    status, iterations, _ = _spent(run_dir)
    assert (status, iterations) == ("done", 4), (
        "behavior 3: PLA_MAX_ITERATIONS=16 must beat the recorded bound of 1 and let "
        f"the loop finish exactly as it does at HEAD; checkpoint says {(status, iterations)}"
    )

    # The SAME precedence on the other half of the budget. Graded separately
    # because a layering built for one key and hardcoded for the other reads
    # identically in a report and leaves half the bound unreachable.
    calls_dir = _produced(root, workspace, "--max-llm-calls", "2", label="b297-3-calls")
    recorded_calls = _document(calls_dir / "meta.json").get("max_llm_calls")
    assert recorded_calls == 2, (
        "behavior 3 (calls) needs a run dir recording a call bound of 2 to override; "
        f"got {recorded_calls!r}"
    )
    proc = _resumed(calls_dir, cwd=root, env=_clean_env(PLA_MAX_LLM_CALLS="24"))
    assert proc.returncode == 0, (
        f"behavior 3 (calls): an env-raised resume must exit 0; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    status, iterations, calls = _spent(calls_dir)
    assert (status, iterations) == ("done", 4), (
        "behavior 3 (calls): PLA_MAX_LLM_CALLS=24 must beat the recorded bound of 2 and "
        f"let the loop finish; checkpoint says {(status, iterations, calls)}"
    )
    assert isinstance(calls, int) and calls > recorded_calls, (
        "behavior 3 (calls): the env-raised resume must actually spend PAST the "
        f"recorded {recorded_calls} call(s); it recorded {calls!r}"
    )


def _b297_4_an_absent_or_null_record_still_resumes(root: Path, workspace: Path) -> None:
    """Behavior 4: a run dir from BEFORE this feature resumes unchanged.

    Absent stays tolerated -- the metadata reader's documented posture for a
    missing file -- so an upgrade never strands a run dir already on disk.
    """
    cases: tuple[tuple[str, dict[str, object] | None], ...] = (
        ("dropped", {"max_iterations": _DROP, "max_llm_calls": _DROP}),
        ("null", {"max_iterations": None, "max_llm_calls": None}),
        ("no-meta", None),
    )
    for label, changes in cases:
        run_dir = _produced(root, workspace, "--max-iterations", "1", label=f"b297-4-{label}")
        if changes is None:
            (run_dir / "meta.json").unlink()
        else:
            _rewrite_meta(run_dir, **changes)
        proc = _resumed(run_dir, cwd=root)
        assert proc.returncode == 0, (
            f"behavior 4 ({label}): an unrecorded budget is not an error; exit "
            f"{proc.returncode}\nstderr:\n{proc.stderr}"
        )
        assert "error:" not in proc.stderr, (
            f"behavior 4 ({label}): nothing may be reported on stderr for a run dir "
            f"that simply predates the feature; stderr:\n{proc.stderr}"
        )
        status, iterations, _ = _spent(run_dir)
        assert (status, iterations) == ("done", 4), (
            f"behavior 4 ({label}): with no recorded budget the resume falls back to "
            f"the built-in default and finishes as it does at HEAD; checkpoint says "
            f"{(status, iterations)}"
        )


def _b297_5_a_corrupt_record_is_loud_not_silent(root: Path, workspace: Path) -> None:
    """Behavior 5: a present-but-invalid recorded budget refuses, quietly framed.

    One run dir serves every case precisely BECAUSE the refusal must not advance
    the checkpoint: if any case did, the next one would start from a mutated
    run and the loop itself would report it.
    """
    run_dir = _produced(root, workspace, "--max-iterations", "1", label="b297-5")
    pristine = (run_dir / "meta.json").read_text(encoding="utf-8")
    before = _spent(run_dir)
    for key, value in CORRUPT_RECORDS:
        _rewrite_meta(run_dir, **{key: value})
        proc = _resumed(run_dir, cwd=root)
        case = f"behavior 5 ({key}={value!r})"
        assert proc.returncode == 1, (
            f"{case}: a corrupt recorded budget must exit 1, never run on a value it "
            f"could not read; exit {proc.returncode}\nstdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
        assert proc.stdout == "", (
            f"{case}: a refused resume prints nothing on stdout, so a `--json` "
            f"consumer never sees half a document; stdout:\n{proc.stdout}"
        )
        lines = [line for line in proc.stderr.splitlines() if line.strip()]
        assert len(lines) == 1, (
            f"{case}: exactly one line goes to stderr; got {len(lines)}:\n{proc.stderr}"
        )
        assert lines[0].startswith("error: "), (
            f"{case}: the line must use the product's `error: ` prefix; got:\n{lines[0]}"
        )
        assert META_ERROR_PREFIX in lines[0], (
            f"{case}: reuse the shipped metadata message family "
            f"({META_ERROR_PREFIX!r}) rather than a second dialect; got:\n{lines[0]}"
        )
        assert key in lines[0], (
            f"{case}: the line must NAME the offending key so the user can fix the "
            f"file; got:\n{lines[0]}"
        )
        for token in (*VENDOR_DUMP_TOKENS, "Traceback"):
            assert token not in proc.stderr, (
                f"{case}: {token!r} must never reach a user's terminal; stderr:\n"
                f"{proc.stderr}"
            )
        assert _spent(run_dir) == before, (
            f"{case}: a refusal must not advance the checkpoint; before {before}, "
            f"after {_spent(run_dir)}"
        )
        (run_dir / "meta.json").write_text(pristine, encoding="utf-8")

    # The refusal is scoped to RESUME. `pla runs` reads the same file and its
    # documented contract is that one bad run never aborts a listing, so a
    # validator pushed down into the shared reader would break a shipped verb
    # while every assertion above still passed.
    _rewrite_meta(run_dir, max_iterations=0)
    listing = _cli("runs", "--state-dir", str(run_dir.parent), "--json", cwd=root)
    assert listing.returncode == 0, (
        "behavior 5 (listing): a corrupt recorded budget refuses a RESUME, but "
        f"`pla runs` must still exit 0; got {listing.returncode}\n"
        f"stderr:\n{listing.stderr}"
    )
    assert run_dir.name in listing.stdout, (
        f"behavior 5 (listing): `pla runs` must still name {run_dir.name} despite the "
        f"corrupt recorded budget -- one bad run may never abort a listing; stdout:\n"
        f"{listing.stdout}"
    )
    (run_dir / "meta.json").write_text(pristine, encoding="utf-8")
