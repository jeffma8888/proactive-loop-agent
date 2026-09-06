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

    assert "Six settings also have a direct CLI flag" in readme, (
        "the README configuration prose counts the flag-backed settings in words; "
        "adding two flags moves that count to six"
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
