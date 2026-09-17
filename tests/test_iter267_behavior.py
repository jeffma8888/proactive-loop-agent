"""Black-box behavior tests for state-dir iteration 422 (ships as ``foundry iter 308``).

Feature under test: ``pla resume`` SAYS SO, on stderr, when the run dir's recorded L1
budget is already spent -- instead of exiting 0 having made zero progress and reporting
that with the same exit code a successful resume returns. Report-side only: no new exit
code, no new key, no new flag.

MODULE NAME, derived from the REPO and never from the state-dir counter (the 2026-08-19
operator pin). ``git ls-files tests`` tops out at ``test_iter266_behavior.py`` on the tree
under test, +1 = ``267``, and ``git cat-file -e HEAD:tests/test_iter267_behavior.py``
FAILED (``fatal: path ... does not exist in 'HEAD'``) before the first byte was written,
with no worktree file at that path either.

NO FOUR-DIGIT NUMBER IS SPELLED ANYWHERE IN THIS MODULE, and that is a correctness
requirement rather than a style rule. ``tests/test_readme_and_ci_contract.py`` runs a
census that reports any TRACKED file mirroring the published suite-size floor while not
being one of its declared carriers; this module is tracked, so a stray four-digit literal
would make it the census's own first finding on the very commit that adds it (the measured
iteration-421 hazard). Every number here is a budget bound of 1 or 2, an exit code, or a
key count -- all derived from the fixture's own ``meta.json`` where a bound is asserted.

WHY EVERY BEHAVIOR IS DRIVEN THROUGH A REAL SUBPROCESS
Behaviors 1-7 are claims about the SEPARATION and ORDER of two output streams (which
prefixes land on stderr, what stdout holds, which exit code) and about an ABSENCE
(silence when there is headroom). An in-process ``capsys`` run cannot falsify a real-fd
claim honestly, so this module spends real ``pla`` console-script invocations -- the
iter-114 / iter-152 / iter-163 / iter-173 convention -- and reads the actual file
descriptors. Cost is bounded: FOUR producing runs and eight resumes, all module-scoped,
against the bundled scripted provider.

EVERY RESUME RUNS ON A PRIVATE COPY OF ITS RUN DIR. ``resume`` MUTATES the checkpoint it
resumes (measured in iter-173: a finished run at ``iterations_used=3`` reported 6 after
one resume), so two resumes sharing a run dir would be order-dependent and would flake
under ``-n auto``. The four producing runs are therefore each done ONCE and every resume
gets a ``shutil.copytree`` of the resulting run dir (the pm.md cost-saver), which keeps
the fixture that four separate assertions read immutable.

NOTHING IS TRANSCRIBED. A run dir is READ from the ``run --json`` document that created
it (goal ids are not stable across two scans of one workspace), and every used-of-bound
number an assertion expects is read from the fixture's own ``meta.json`` /
``checkpoint.json`` -- the two files the README documents as published state -- so a
hardcoded ``2 of 2`` cannot pass a run that recorded a different bound.

ISOLATION CONTRACT (honored): every assertion is written against this iteration's spec
("Expected Behaviors" in ``pm.md``), the repo's own ``tests/`` conventions, the product
README, and the product's OBSERVABLE output obtained by RUNNING it. **No file under
``src/`` was read, no engineer's or reviewer's note was consulted, and no ``git diff``
was inspected.** Fully offline and deterministic: the bundled scripted provider only, no
network, no API key, no clock. Every invocation is rooted at a PRIVATE COPY of
``examples/fixture_workspace`` under a ``tmp_path_factory`` dir and writes its state
there -- nothing is written inside the product repo, and no run is rooted at the in-repo
fixture (the iter-142 shared-mutable-tree hazard).

DELIBERATELY NOT RE-ASSERTED HERE, because restating an owned expectation multiplies the
sites the next change has to re-key:

* The nine-key document's equality with ``dispatch --json``'s key set, and the
  summary-moves-to-stderr claim -- ``tests/test_iter173_behavior.py`` owns both over the
  same verb. This module re-derives only the key SET on a resume of a spent run, because
  that is the fixture iter-173 never had.
* The README intro block above the human-owned marker, and the published suite-size
  floor -- ``tests/test_readme_and_ci_contract.py`` owns them. This module asserts only
  that the marker still exists and that the paragraph it grades sits BELOW it.
* ``ROADMAP.md`` size and ledger shape -- ``tests/test_iter241_behavior.py`` and
  ``tests/test_iter264_behavior.py`` own those; measured out of band and reported in
  ``tester.md``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_iter158_behavior import DISPATCHED_RUN_KEYS

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"
README = REPO / "README.md"

# The published dispatched-run document (spec behavior 6): exactly the nine keys IMPORTED
# above as ``DISPATCHED_RUN_KEYS``, not re-spelled -- tests/test_iter158_behavior.py owns
# the single definition. Still a HAND-WRITTEN expectation, still compared against a key
# set obtained by RUNNING the verb on a resumed run.

# The two stderr prefixes this iteration contracts (spec behaviors 1, 2, 4, 5, 7).
_NOTE = "note: "
_HINT = "hint: "

# `<used> of <bound>` -- spec behavior 3 reads the bound back out of the rendered note.
_OF_BOUND = re.compile(r"\bof (\d+)\b")


# ---------------------------------------------------------------------------
# Helpers (iter-114 / iter-152 / iter-163 / iter-173 console-script convention)
# ---------------------------------------------------------------------------


def _console_script() -> Path:
    """The installed ``pla`` console script."""
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


def _run(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Invoke the real CLI in its own process so stdout/stderr are real fds."""
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def _isolated_workspace(root: Path) -> Path:
    """A private copy of the offline fixture workspace under ``root``.

    Never run the product against the in-repo fixture: it carries no ``.git`` of its own,
    so git-family collectors resolve upward into this repo and a sibling xdist worker can
    flip what they report mid-test.
    """
    dest = root / "workspace"
    shutil.copytree(FIXTURE, dest)
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


def _prefixed(stderr: str, prefix: str) -> list[str]:
    """Every stderr line whose STRIPPED form starts with ``prefix``.

    Enumerated rather than membership-tested so an ABSENCE claim is evidence (here is the
    whole list, it is empty) instead of a silent non-match.
    """
    return [line.strip() for line in stderr.splitlines() if line.strip().startswith(prefix)]


def _one_json_object(stdout: str, label: str) -> dict:
    """Parse stdout as EXACTLY one JSON object, or fail with the raw text.

    ``json.loads`` rejects trailing content, so a successful parse is itself the proof
    that no prose and no second document accompany the object.
    """
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - failure reporting
        pytest.fail(
            f"{label}: stdout must be exactly one JSON value; {exc}\nstdout:\n{stdout!r}"
        )
    assert isinstance(payload, dict), (
        f"{label}: the document must be a JSON object, got {type(payload).__name__}"
    )
    return payload


class Fixture:
    """One producing ``pla run`` and the immutable run dir it left behind."""

    def __init__(self, root: Path, run_dir: Path, state_dir: Path, label: str) -> None:
        self.root = root
        self.run_dir = run_dir
        self.state_dir = state_dir
        self.label = label
        self.meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        self.checkpoint = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
        self._copies = 0

    @property
    def max_iterations(self) -> int:
        return int(self.meta["max_iterations"])

    @property
    def max_llm_calls(self) -> int:
        return int(self.meta["max_llm_calls"])

    @property
    def iterations_used(self) -> int:
        return int(self.checkpoint["iterations_used"])

    @property
    def llm_calls_used(self) -> int:
        return int(self.checkpoint["llm_calls_used"])

    def copy(self) -> Path:
        """A private copy of the run dir, so a resume's mutation stays local."""
        self._copies += 1
        dest = self.root / f"rd-copy-{self._copies}"
        shutil.copytree(self.run_dir, dest)
        return dest

    def resume(
        self, *extra: str, offline: bool = True, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """``pla resume`` on a fresh copy of this fixture's run dir."""
        flags = list(_offline(self.state_dir)) if offline else []
        return _run(
            "resume", "--run-dir", str(self.copy()), *flags, *extra, cwd=self.root, env=env
        )


def _produce(root: Path, workspace: Path, label: str, *budget: str) -> Fixture:
    """One offline ``run --json`` under ``budget``; returns its :class:`Fixture`.

    The run dir is READ from the document the run itself published, never composed from a
    goal id.
    """
    sd = root / "state"
    proc = _run(
        "run", "--workspace", str(workspace), *_offline(sd), *budget, "--json", cwd=root
    )
    assert proc.returncode == 0, (
        f"the setup `run --json` for {label} must exit 0; got {proc.returncode}\n"
        f"stderr:\n{proc.stderr}"
    )
    dispatched = _one_json_object(proc.stdout, f"setup run for {label}").get("dispatched")
    assert isinstance(dispatched, dict), (
        f"the setup run for {label} must have auto-dispatched a goal (its `dispatched` "
        "sub-object is the resumable run)"
    )
    run_dir = Path(str(dispatched["run_dir"]))
    assert (run_dir / "checkpoint.json").is_file(), (
        f"the setup run for {label} must leave a resumable checkpoint in {run_dir}"
    )
    return Fixture(root, run_dir, sd, label)


# ---------------------------------------------------------------------------
# Module-scoped product invocations (four producing runs, eight resumes)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """ONE private, immutable copy of the fixture workspace (artifacts land in state dirs)."""
    return _isolated_workspace(tmp_path_factory.mktemp("i267_ws"))


@pytest.fixture(scope="module")
def spent_llm(tmp_path_factory: pytest.TempPathFactory, workspace: Path) -> Fixture:
    """The reference fixture: recorded ``max_llm_calls`` fully spent, iterations not."""
    fx = _produce(
        tmp_path_factory.mktemp("i267_llm"), workspace, "spent-LLM-calls", "--max-llm-calls", "2"
    )
    assert fx.llm_calls_used >= fx.max_llm_calls, (
        "the reference fixture must have SPENT its recorded LLM-call bound; "
        f"used={fx.llm_calls_used} bound={fx.max_llm_calls}"
    )
    assert fx.iterations_used < fx.max_iterations, (
        "the reference fixture must still have ITERATION headroom, so behavior 1 grades "
        f"one dimension alone; used={fx.iterations_used} bound={fx.max_iterations}"
    )
    return fx


@pytest.fixture(scope="module")
def spent_iters(tmp_path_factory: pytest.TempPathFactory, workspace: Path) -> Fixture:
    """Recorded ``max_iterations`` fully spent, with LLM-call headroom left."""
    fx = _produce(
        tmp_path_factory.mktemp("i267_iters"),
        workspace,
        "spent-iterations",
        "--max-iterations",
        "1",
    )
    assert fx.iterations_used >= fx.max_iterations, (
        "the spent-iterations fixture must have SPENT its recorded iteration bound; "
        f"used={fx.iterations_used} bound={fx.max_iterations}"
    )
    return fx


@pytest.fixture(scope="module")
def both_spent(tmp_path_factory: pytest.TempPathFactory, workspace: Path) -> Fixture:
    """BOTH dimensions spent -- the only fixture that can falsify behavior 4's ORDER."""
    fx = _produce(
        tmp_path_factory.mktemp("i267_both"),
        workspace,
        "both-dimensions-spent",
        "--max-iterations",
        "1",
        "--max-llm-calls",
        "2",
    )
    assert fx.iterations_used >= fx.max_iterations, (
        f"both-spent fixture: iterations {fx.iterations_used} of {fx.max_iterations}"
    )
    assert fx.llm_calls_used >= fx.max_llm_calls, (
        f"both-spent fixture: LLM calls {fx.llm_calls_used} of {fx.max_llm_calls}"
    )
    return fx


@pytest.fixture(scope="module")
def with_headroom(tmp_path_factory: pytest.TempPathFactory, workspace: Path) -> Fixture:
    """A run that terminated INSIDE its budget -- behavior 5(a)'s silent case."""
    fx = _produce(tmp_path_factory.mktemp("i267_head"), workspace, "with-headroom")
    assert fx.iterations_used < fx.max_iterations, (
        f"headroom fixture: iterations {fx.iterations_used} of {fx.max_iterations}"
    )
    assert fx.llm_calls_used < fx.max_llm_calls, (
        f"headroom fixture: LLM calls {fx.llm_calls_used} of {fx.max_llm_calls}"
    )
    return fx


@pytest.fixture(scope="module")
def llm_bare(spent_llm: Fixture) -> subprocess.CompletedProcess[str]:
    """``pla resume --run-dir RD`` -- the spec's literal invocation, no other flag."""
    return spent_llm.resume(offline=False)


@pytest.fixture(scope="module")
def llm_json(spent_llm: Fixture) -> subprocess.CompletedProcess[str]:
    """The same recovery under ``--json`` (behavior 6)."""
    return spent_llm.resume("--json")


@pytest.fixture(scope="module")
def iters_plain(spent_iters: Fixture) -> subprocess.CompletedProcess[str]:
    return spent_iters.resume()


@pytest.fixture(scope="module")
def both_plain(both_spent: Fixture) -> subprocess.CompletedProcess[str]:
    return both_spent.resume()


@pytest.fixture(scope="module")
def headroom_plain(with_headroom: Fixture) -> subprocess.CompletedProcess[str]:
    return with_headroom.resume()


@pytest.fixture(scope="module")
def raised_bound(spent_llm: Fixture) -> subprocess.CompletedProcess[str]:
    """Behavior 5(b): the reference fixture with the env bound raised ABOVE its usage.

    Proves the note reads the EFFECTIVE bound after the env-over-recorded fold, not the
    recorded value. The env raise is spelled from the fixture's own recorded bound.
    """
    env = dict(os.environ)
    env["PLA_MAX_LLM_CALLS"] = str(spent_llm.max_llm_calls * 4)
    return spent_llm.resume(env=env)


@pytest.fixture(scope="module")
def refusal(tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess[str]:
    """Behavior 7: a run dir holding no checkpoint at all."""
    root = tmp_path_factory.mktemp("i267_refuse")
    empty = root / "no-such-run"
    empty.mkdir()
    return _run("resume", "--run-dir", str(empty), cwd=root)


@pytest.fixture(scope="module")
def refusal_json(tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess[str]:
    root = tmp_path_factory.mktemp("i267_refuse_json")
    empty = root / "no-such-run"
    empty.mkdir()
    return _run("resume", "--run-dir", str(empty), "--json", cwd=root)


# ---------------------------------------------------------------------------
# Behavior 1 -- the spent-LLM-calls note
# ---------------------------------------------------------------------------


def test_b1_bare_resume_names_the_spent_llm_bound(
    llm_bare: subprocess.CompletedProcess[str], spent_llm: Fixture
) -> None:
    """`pla resume --run-dir RD` on a spent-LLM-call run writes a naming `note:` line."""
    assert llm_bare.returncode == 0, (
        "a resume whose recorded bound is spent must still exit 0 (no new exit code); "
        f"got {llm_bare.returncode}\nstderr:\n{llm_bare.stderr}"
    )
    notes = _prefixed(llm_bare.stderr, _NOTE)
    assert notes, (
        "a resume that cannot advance must say so on stderr with a `note: ` line; "
        f"stderr was:\n{llm_bare.stderr!r}"
    )
    used_of_bound = f"{spent_llm.llm_calls_used} of {spent_llm.max_llm_calls}"
    matching = [n for n in notes if "LLM calls" in n]
    assert len(matching) == 1, (
        f"exactly one note must name the LLM-call dimension; notes were {notes}"
    )
    note = matching[0]
    for token in (used_of_bound, "LLM calls", "cannot advance", "PLA_MAX_LLM_CALLS"):
        assert token in note, f"the LLM-calls note must contain {token!r}; got {note!r}"


def test_b1_note_goes_to_stderr_not_stdout(
    llm_bare: subprocess.CompletedProcess[str],
) -> None:
    """The note is diagnostic output: stdout must not carry either prefix."""
    assert _prefixed(llm_bare.stdout, _NOTE) == [], (
        f"no `note: ` line may appear on stdout; stdout was:\n{llm_bare.stdout!r}"
    )
    assert _prefixed(llm_bare.stdout, _HINT) == [], (
        f"no `hint: ` line may appear on stdout; stdout was:\n{llm_bare.stdout!r}"
    )


def test_b1_note_survives_the_offline_flags(spent_llm: Fixture) -> None:
    """The note is a property of the RUN DIR, not of which flags the resume passed."""
    proc = spent_llm.resume()
    assert proc.returncode == 0, (
        f"resume with the offline flags must exit 0; got {proc.returncode}\n{proc.stderr}"
    )
    notes = [n for n in _prefixed(proc.stderr, _NOTE) if "LLM calls" in n]
    assert len(notes) == 1, (
        "re-supplying --provider/--scripted-responses must not silence the note (the "
        f"bound is still spent); notes were {_prefixed(proc.stderr, _NOTE)}"
    )
    assert f"of {spent_llm.max_llm_calls}" in notes[0]


# ---------------------------------------------------------------------------
# Behavior 2 -- the spent-iterations note
# ---------------------------------------------------------------------------


def test_b2_spent_iterations_note(
    iters_plain: subprocess.CompletedProcess[str], spent_iters: Fixture
) -> None:
    """A run at its recorded iteration bound gets a note naming that dimension's knob."""
    assert iters_plain.returncode == 0, (
        f"must still exit 0; got {iters_plain.returncode}\nstderr:\n{iters_plain.stderr}"
    )
    notes = _prefixed(iters_plain.stderr, _NOTE)
    matching = [n for n in notes if "iterations" in n]
    assert len(matching) == 1, (
        f"exactly one note must name the iterations dimension; notes were {notes}"
    )
    note = matching[0]
    expected = f"{spent_iters.iterations_used} of {spent_iters.max_iterations}"
    for token in (expected, "iterations", "cannot advance", "PLA_MAX_ITERATIONS"):
        assert token in note, f"the iterations note must contain {token!r}; got {note!r}"


def test_b2_iterations_note_names_only_its_own_knob(
    iters_plain: subprocess.CompletedProcess[str],
) -> None:
    """The dimension that still has headroom must not be reported as spent."""
    notes = _prefixed(iters_plain.stderr, _NOTE)
    assert not [n for n in notes if "PLA_MAX_LLM_CALLS" in n], (
        "the LLM-call dimension has headroom in this fixture, so no note may name its "
        f"knob; notes were {notes}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- the bound is READ from the run dir, not hardcoded
# ---------------------------------------------------------------------------


def test_b3_llm_note_quotes_only_the_recorded_bound(
    llm_bare: subprocess.CompletedProcess[str], spent_llm: Fixture
) -> None:
    """Every `of <N>` in the notes equals this fixture's own recorded LLM bound."""
    notes = _prefixed(llm_bare.stderr, _NOTE)
    bounds = {int(m) for note in notes for m in _OF_BOUND.findall(note)}
    assert bounds == {spent_llm.max_llm_calls}, (
        "the only bound the notes may quote is the one meta.json recorded "
        f"({spent_llm.max_llm_calls}); found {sorted(bounds)} in {notes}"
    )


def test_b3_iterations_note_quotes_only_the_recorded_bound(
    iters_plain: subprocess.CompletedProcess[str], spent_iters: Fixture
) -> None:
    notes = _prefixed(iters_plain.stderr, _NOTE)
    bounds = {int(m) for note in notes for m in _OF_BOUND.findall(note)}
    assert bounds == {spent_iters.max_iterations}, (
        "the only bound the notes may quote is the one meta.json recorded "
        f"({spent_iters.max_iterations}); found {sorted(bounds)} in {notes}"
    )


def test_b3_two_fixtures_recorded_different_bounds(
    spent_llm: Fixture, spent_iters: Fixture
) -> None:
    """The two graded fixtures must actually DIFFER, or behavior 3 is vacuous."""
    assert spent_llm.max_llm_calls != spent_iters.max_iterations, (
        "behavior 3 needs two distinct recorded bounds to distinguish 'read' from "
        f"'hardcoded'; got {spent_llm.max_llm_calls} and {spent_iters.max_iterations}"
    )


def test_b3_both_spent_quotes_both_recorded_bounds(
    both_plain: subprocess.CompletedProcess[str], both_spent: Fixture
) -> None:
    """With both dimensions spent, the notes quote exactly the two recorded bounds."""
    notes = _prefixed(both_plain.stderr, _NOTE)
    bounds = {int(m) for note in notes for m in _OF_BOUND.findall(note)}
    assert bounds == {both_spent.max_iterations, both_spent.max_llm_calls}, (
        "the notes must quote each dimension's own recorded bound and nothing else; "
        f"found {sorted(bounds)} in {notes}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- the provider hint, exactly once, in a deterministic order
# ---------------------------------------------------------------------------


def test_b4_hint_appears_exactly_once_per_resume(
    llm_bare: subprocess.CompletedProcess[str],
    iters_plain: subprocess.CompletedProcess[str],
    both_plain: subprocess.CompletedProcess[str],
) -> None:
    """One `hint:` line accompanies ANY number of notes -- one, or two."""
    for label, proc in (
        ("spent LLM calls", llm_bare),
        ("spent iterations", iters_plain),
        ("both dimensions spent", both_plain),
    ):
        assert _prefixed(proc.stderr, _NOTE), f"{label}: expected at least one note"
        hints = _prefixed(proc.stderr, _HINT)
        assert len(hints) == 1, (
            f"{label}: exactly ONE hint line must accompany the note(s); got {hints}"
        )


def test_b4_hint_names_both_missing_facts(
    both_plain: subprocess.CompletedProcess[str],
) -> None:
    """The hint names the two flags a raised-bound resume must re-supply, and why."""
    hint = _prefixed(both_plain.stderr, _HINT)[0]
    for token in ("--provider", "--scripted-responses", "meta.json"):
        assert token in hint, f"the hint must contain {token!r}; got {hint!r}"
    lowered = hint.lower()
    assert "provider configuration" in lowered or "no provider" in lowered, (
        "the hint must state that the run dir / meta.json does not record provider "
        f"configuration; got {hint!r}"
    )
    assert "not" in lowered.split(), (
        f"the hint must be a NEGATIVE statement about what meta.json records; got {hint!r}"
    )


def test_b4_order_is_iterations_then_llm_then_hint(
    both_plain: subprocess.CompletedProcess[str],
) -> None:
    """Deterministic order on the only fixture that can falsify it: both spent."""
    lines = [
        line.strip()
        for line in both_plain.stderr.splitlines()
        if line.strip().startswith((_NOTE, _HINT))
    ]
    assert len(lines) == 3, (
        f"both dimensions spent must produce two notes and one hint; got {lines}"
    )
    assert lines[0].startswith(_NOTE) and "iterations" in lines[0], (
        f"the iterations note must come first; got {lines}"
    )
    assert lines[1].startswith(_NOTE) and "LLM calls" in lines[1], (
        f"the LLM-calls note must come second; got {lines}"
    )
    assert lines[2].startswith(_HINT), f"the hint must come last; got {lines}"


# ---------------------------------------------------------------------------
# Behavior 5 -- silence when there is headroom
# ---------------------------------------------------------------------------


def test_b5a_run_that_finished_inside_its_budget_is_silent(
    headroom_plain: subprocess.CompletedProcess[str], with_headroom: Fixture
) -> None:
    """Headroom in BOTH dimensions: no note, no hint, still exit 0."""
    assert headroom_plain.returncode == 0, (
        f"got {headroom_plain.returncode}\nstderr:\n{headroom_plain.stderr}"
    )
    assert _prefixed(headroom_plain.stderr, _NOTE) == [], (
        "a resume with headroom in both dimensions must print no note; "
        f"stderr:\n{headroom_plain.stderr!r}"
    )
    assert _prefixed(headroom_plain.stderr, _HINT) == [], (
        "and no hint either (the hint is bound to the notes); "
        f"stderr:\n{headroom_plain.stderr!r}"
    )


def test_b5b_env_raised_bound_silences_the_note(
    raised_bound: subprocess.CompletedProcess[str], spent_llm: Fixture
) -> None:
    """The note reads the EFFECTIVE bound (env over recorded), not the recorded one."""
    assert raised_bound.returncode == 0, (
        "PLA_MAX_LLM_CALLS above usage plus re-supplied provider flags must exit 0; "
        f"got {raised_bound.returncode}\nstderr:\n{raised_bound.stderr}"
    )
    assert _prefixed(raised_bound.stderr, _NOTE) == [], (
        "raising the env bound above usage gives the run headroom, so the note must "
        f"disappear; stderr:\n{raised_bound.stderr!r}"
    )
    assert _prefixed(raised_bound.stderr, _HINT) == [], (
        f"and the hint with it; stderr:\n{raised_bound.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- both modes, no exit-code change, no key change
# ---------------------------------------------------------------------------


def test_b6_json_mode_keeps_the_nine_key_document(
    llm_json: subprocess.CompletedProcess[str], spent_llm: Fixture
) -> None:
    """stdout is exactly ONE nine-key object whose values match the checkpoint."""
    assert llm_json.returncode == 0, (
        f"got {llm_json.returncode}\nstderr:\n{llm_json.stderr}"
    )
    payload = _one_json_object(llm_json.stdout, "resume --json on a spent run")
    assert frozenset(payload) == DISPATCHED_RUN_KEYS, (
        "the dispatched document's key set must be unchanged by this iteration; "
        f"extra={sorted(set(payload) - DISPATCHED_RUN_KEYS)} "
        f"missing={sorted(DISPATCHED_RUN_KEYS - set(payload))}"
    )
    assert payload["status"] == spent_llm.checkpoint["status"], (
        "a resume that cannot advance must report the status it loaded; "
        f"document={payload['status']!r} checkpoint={spent_llm.checkpoint['status']!r}"
    )
    assert int(payload["llm_calls_used"]) == spent_llm.llm_calls_used, (
        "and the usage it loaded, unchanged; "
        f"document={payload['llm_calls_used']} checkpoint={spent_llm.llm_calls_used}"
    )


def test_b6_json_mode_still_writes_the_note_and_hint_to_stderr(
    llm_json: subprocess.CompletedProcess[str],
) -> None:
    """The diagnostics land on stderr in BOTH modes, so the document is untouched."""
    assert len(_prefixed(llm_json.stderr, _NOTE)) == 1, (
        f"stderr:\n{llm_json.stderr!r}"
    )
    assert len(_prefixed(llm_json.stderr, _HINT)) == 1, (
        f"stderr:\n{llm_json.stderr!r}"
    )
    assert _prefixed(llm_json.stdout, _NOTE) == []
    assert _prefixed(llm_json.stdout, _HINT) == []


def test_b6_every_graded_resume_exits_zero(
    llm_bare: subprocess.CompletedProcess[str],
    llm_json: subprocess.CompletedProcess[str],
    iters_plain: subprocess.CompletedProcess[str],
    both_plain: subprocess.CompletedProcess[str],
    headroom_plain: subprocess.CompletedProcess[str],
    raised_bound: subprocess.CompletedProcess[str],
) -> None:
    """No new exit code: behaviors 1-5 all exit 0, with and without ``--json``."""
    codes = {
        "llm_bare": llm_bare.returncode,
        "llm_json": llm_json.returncode,
        "iters_plain": iters_plain.returncode,
        "both_plain": both_plain.returncode,
        "headroom_plain": headroom_plain.returncode,
        "raised_bound": raised_bound.returncode,
    }
    assert set(codes.values()) == {0}, f"every graded resume must exit 0; got {codes}"


# ---------------------------------------------------------------------------
# Behavior 7 -- the refusal path is untouched
# ---------------------------------------------------------------------------


def test_b7_no_checkpoint_still_exits_two_and_stays_quiet(
    refusal: subprocess.CompletedProcess[str],
) -> None:
    """The guard sits AFTER the checkpoint load, so the refusal is unchanged."""
    assert refusal.returncode == 2, (
        f"a run dir with no checkpoint must still exit 2; got {refusal.returncode}\n"
        f"stderr:\n{refusal.stderr}"
    )
    assert "error: no checkpoint found in " in refusal.stderr, (
        f"the refusal message must be unchanged; stderr:\n{refusal.stderr!r}"
    )
    assert _prefixed(refusal.stderr, _NOTE) == [], (
        f"the refusal must carry no budget note; stderr:\n{refusal.stderr!r}"
    )
    assert _prefixed(refusal.stderr, _HINT) == [], (
        f"and no provider hint; stderr:\n{refusal.stderr!r}"
    )


def test_b7_refusal_stdout_is_exactly_empty_in_both_modes(
    refusal: subprocess.CompletedProcess[str],
    refusal_json: subprocess.CompletedProcess[str],
) -> None:
    """Never a half-formed document -- the published `--json` promise."""
    assert refusal.stdout == "", f"plain refusal stdout:\n{refusal.stdout!r}"
    assert refusal_json.returncode == 2, f"got {refusal_json.returncode}"
    assert refusal_json.stdout == "", f"--json refusal stdout:\n{refusal_json.stdout!r}"
    assert _prefixed(refusal_json.stderr, _NOTE) == []
    assert _prefixed(refusal_json.stderr, _HINT) == []


# ---------------------------------------------------------------------------
# Behavior 8 -- the README tells the measured truth
# ---------------------------------------------------------------------------

_MARKER = "PORTFOLIO INTRO"


def _readme_below_marker() -> str:
    """Everything BELOW the human-owned portfolio-intro marker."""
    text = README.read_text(encoding="utf-8")
    idx = text.find(_MARKER)
    assert idx > 0, (
        f"README.md must still carry the human-owned {_MARKER!r} marker; "
        "behavior 8 is defined relative to it"
    )
    return text[idx:]


def _resume_paragraph() -> str:
    """The ONE ``resume --json`` reference paragraph, isolated by blank lines.

    Scoped to a single Markdown paragraph on purpose. A whole-file token search passes
    when the required facts are scattered across unrelated sections -- and measured here,
    it does worse than that: the README already carries an EARLIER ``hint:`` paragraph
    belonging to a different verb, so a window anchored on the first match grades the
    wrong prose entirely (my first draft of this test failed exactly that way).
    """
    paragraphs = re.split(r"\n[ \t]*\n", _readme_below_marker())
    hits = [
        para
        for para in paragraphs
        if "`resume --json`" in para and "PLA_MAX_LLM_CALLS" in para
    ]
    assert len(hits) == 1, (
        "exactly one paragraph below the marker must be the resume reference paragraph "
        "that documents the spent-bound dead end (it is the one naming both "
        f"`resume --json` and PLA_MAX_LLM_CALLS); found {len(hits)}"
    )
    return hits[0]


def test_b8_resume_paragraph_documents_the_spent_bound_dead_end() -> None:
    """One paragraph states the dead end, the unchanged exit code and both knobs."""
    para = _resume_paragraph()
    for token in ("PLA_MAX_ITERATIONS", "PLA_MAX_LLM_CALLS", "`note:`", "`hint:`"):
        assert token in para, (
            f"the resume reference paragraph must name {token!r}; paragraph was:\n{para}"
        )
    lowered = para.lower()
    for phrase in ("cannot", "advance", "spent", "exits **0**", "headroom"):
        assert phrase in lowered, (
            f"the paragraph must state {phrase!r}: a resume whose recorded bound is spent "
            "cannot advance the run, still exits 0, and one with headroom in both "
            f"dimensions prints neither line; paragraph was:\n{para}"
        )


def test_b8_resume_paragraph_names_the_two_missing_facts() -> None:
    """Raising the bound needs BOTH the env value AND re-supplied provider flags."""
    para = _resume_paragraph()
    for token in ("meta.json", "--provider", "--scripted-responses"):
        assert token in para, (
            f"the same paragraph must name {token!r} -- the operator needs both facts, "
            f"and a fact stated in another section is not this contract; paragraph:\n{para}"
        )
    lowered = para.lower()
    assert "records no provider" in lowered or "no provider configuration" in lowered, (
        "the paragraph must say meta.json records NO provider configuration (that is why "
        f"the flags must be re-supplied); paragraph was:\n{para}"
    )


def test_b8_stderr_lines_match_what_the_readme_promises(
    both_plain: subprocess.CompletedProcess[str],
) -> None:
    """Cross-check: every knob the paragraph promises is one the product really prints."""
    para = _resume_paragraph()
    printed = "\n".join(_prefixed(both_plain.stderr, _NOTE))
    for knob in ("PLA_MAX_ITERATIONS", "PLA_MAX_LLM_CALLS"):
        assert knob in para and knob in printed, (
            f"{knob} must appear BOTH in the README paragraph and in the notes the "
            f"product actually writes; notes were:\n{printed}"
        )
    hint = _prefixed(both_plain.stderr, _HINT)[0]
    for flag in ("--provider", "--scripted-responses"):
        assert flag in para and flag in hint, (
            f"{flag} must appear BOTH in the README paragraph and in the printed hint; "
            f"hint was:\n{hint}"
        )


def test_b8_nothing_above_the_marker_mentions_this_feature() -> None:
    """The human-owned intro is untouched by this iteration (its own oracle owns the rest)."""
    text = README.read_text(encoding="utf-8")
    above = text[: text.find(_MARKER)]
    for token in ("PLA_MAX_LLM_CALLS", "PLA_MAX_ITERATIONS", "cannot advance"):
        assert token not in above, (
            f"this iteration must not reach above the human-owned marker; found {token!r}"
        )
