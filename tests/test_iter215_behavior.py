"""Black-box behavior tests for state-dir iteration 236 (ships as ``foundry iter 236``):
EVERY paste-ready ``pla dispatch`` command this product prints carries an ABSOLUTE
``--slate`` path, so a pasted command works from any working directory.

Feature under test: four shipped surfaces print a ``pla dispatch --slate ... --goal-id ...``
line the user is meant to copy -- the needs-approval block and the ``--dry-run`` top-goal
line of ``run``, the deferred auto-approved block (shipped iter 234), and the
``run it for real with:`` echo of ``dispatch --dry-run``.  Each of them used to interpolate
the caller's raw ``--state-dir`` spelling, so the default RELATIVE ``.pla_runs`` invocation
that the README and the Makefile teach produced a command that died with ``exit 2`` the
moment the user was anywhere else.  This module pins the absolute spelling on all four
sites, pins that a pasted line really runs from a foreign directory, and pins the two
non-regressions that keep the change confined (an already-absolute state dir is echoed
character-for-character, and ``run --json``'s ``slate_path`` still carries the caller's
own spelling).

MODULE NAME -- derived from the REPO, never from the state-dir number.  ``git ls-files
tests`` holds 234 entries whose highest ``test_iterNN_behavior.py`` is **214**, so 215 is
the next free name, and ``git cat-file -e HEAD:tests/test_iter215_behavior.py`` FAILED
before the first byte was written.  Naming a module from the state-dir counter (236 here)
is what overwrote a shipped 18,786-byte oracle in state-dir 186.

ISOLATION CONTRACT (honored, no exception).  Every assertion below is derived from this
iteration's spec (``pm.md`` "Expected Behaviors" 1-6), from the conventions of the shipped
modules under ``tests/`` (``test_iter213_behavior.py`` supplies the ``main(argv)`` +
``capsys`` harness, the per-module scripted-response builder, the private workspace copy
and the public-gate precondition recipe; ``test_iter62_behavior.py`` supplies the shipped
stdout markers), and from the product's OBSERVABLE stdout/stderr obtained by RUNNING it.
**No file under ``src/`` was read, no ``git diff`` was inspected, and neither
``engineer.md`` nor ``reviewer.md`` was opened.**

OFFLINE AND DETERMINISTIC.  Every invocation uses the bundled scripted provider with a
per-module response file derived from the tracked ``examples/scripted_responses.json`` (its
``synthesize`` payloads swapped for a hand-built slate, every ``plan``/``check`` entry
reused verbatim so a real dispatch still has a scripted loop to run): no network, no API
key, no clock assertion.  The workspace is a PRIVATE ``tmp_path_factory`` copy of the
tracked ``examples/fixture_workspace`` -- never the shared fixture in place (the iter-142
shared-mutable-tree hazard) and never the ambient repo tree, whose signals differ in a fresh
clone (the iter-154 fresh-clone trap).  Every ``--state-dir`` lives outside the scanned
workspace so a run's own artifacts cannot become perception input.

NON-VACUITY IS ASSERTED, NOT ASSUMED.

* Behavior 1 FAILS CLOSED on zero emitted command lines, as the spec demands: the count of
  ``pla dispatch --slate`` lines is asserted non-empty before any of them is inspected, so a
  report that stopped printing the hand-off command reds the build instead of vacuously
  passing an all-quantifier over an empty list.
* The slate shape every census depends on is re-derived through the PUBLIC gate
  (``gate_slate`` + a bare ``Settings()``) and asserted as an explicit precondition -- three
  ``AUTO_DISPATCH`` plus two ``NEEDS_APPROVAL`` -- so a fixture that stopped producing the
  shape under test fails loudly.  That shape is what makes all THREE ``run`` render sites
  fire in one invocation (2 needs-approval lines + 2 deferred lines + 1 dry-run preview
  line = 5), which is what turns behavior 1 into a real cross-site census rather than a
  single-site check.
* Behavior 3 is the TWO-SIDED control arm the spec asks for, and it is the reason behavior 2
  means anything: the identical argv with only the ``--slate`` value put back to the
  pre-fix relative spelling exits ``2``.  Without it, behavior 2 would also pass on a CLI
  that ignored ``--slate`` altogether.

AMBIGUITY NOTES (PM feedback):

* Behavior 1 says the emitted token "reads back as the same JSON as
  ``<cwd>/<RELATIVE>/slate.json``".  String equality against ``Path.cwd() / rel`` is NOT
  the testable reading on macOS: ``os.getcwd()`` returns a symlink-resolved path, so a
  ``/var/folders/...`` cwd spelling can legitimately be echoed as ``/private/var/...``.
  The reading asserted here is identity of the FILE (``Path.samefile``) plus equality of the
  parsed JSON document, which is what "names the slate the same run wrote" actually means
  and which no symlink spelling can fake.
* Behavior 4 says "byte-identical ... no symlink resolution".  That is asserted directly as
  exact string equality against ``str(<abs state dir>/"slate.json")`` for an
  already-absolute ``tmp_path`` state dir -- on this platform ``tmp_path`` is under
  ``/private/var``, so the arm additionally proves the renderer did not COLLAPSE or REWRITE
  an absolute input.  A ``resolve()``-based implementation passes this arm only by accident
  of the input already being resolved, so behavior 4 also asserts the un-resolved
  ``/var/folders`` spelling survives when the state dir is spelled that way.
* Behavior 5 fixes the property of the echoed ``run it for real with:`` command but not the
  exact header wording, so the echo is located by scanning the whole stdout for
  ``pla dispatch --slate`` lines (output, which the role card admits, not source) rather
  than by pinning the sentence.
"""

from __future__ import annotations

import json
import shlex
import shutil
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.models import AutonomyDecision, GoalSlate
from proactive_loop.scout import gate_slate

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

# The token every render site under test emits, carried over from
# tests/test_iter213_behavior.py.
_DISPATCH_CMD = "pla dispatch"
_SLATE_FLAG = "--slate"


# ---------------------------------------------------------------------------
# Slate.  score == impact * urgency * confidence / effort_weight, the gate
# threshold defaults to 4.0 inclusive, finance_legal is sensitive so it can
# never auto-dispatch, and a below-threshold score reads NEEDS_APPROVAL
# (tests/test_scout.py).  Three AUTO_DISPATCH goals are needed so that `run`
# fires all three of its command-rendering sites in ONE invocation.
# ---------------------------------------------------------------------------


def _goal(
    title: str,
    category: str,
    impact: float,
    urgency: float,
    *,
    confidence: float = 1.0,
    effort_weight: float = 1.0,
) -> dict:
    return {
        "title": title,
        "rationale": f"iteration-236 paste-ready-path fixture: {title}",
        "category": category,
        "impact": impact,
        "urgency": urgency,
        "confidence": confidence,
        "effort_weight": effort_weight,
        "appropriate_now": True,
        "sources": ["notes/journal.md"],
        "suggested_first_steps": ["write the artifact"],
    }


AUTO_TOP = "Draft the alpha learning plan"
AUTO_SECOND = "Draft the beta project scaffold"
AUTO_THIRD = "Draft the gamma refactor notes"
SENSITIVE = "Sort out a personal tax question"
LOW_SCORE = "Refresh portfolio talking points"

# 3 AUTO_DISPATCH (25.0 / 20.0 / 15.0) + 2 NEEDS_APPROVAL (sensitive at 10.0,
# below-threshold at 0.5).  Every score is DISTINCT, so ranked() order is total.
GOALS = [
    _goal(AUTO_TOP, "project", 5.0, 5.0),
    _goal(AUTO_SECOND, "project", 5.0, 4.0),
    _goal(AUTO_THIRD, "maintenance", 5.0, 3.0),
    _goal(SENSITIVE, "finance_legal", 5.0, 2.0),
    _goal(LOW_SCORE, "career", 1.0, 1.0, confidence=0.5),
]


# ---------------------------------------------------------------------------
# Harness -- black-box: drive main(argv), read back exit code + stdout/stderr.
# ---------------------------------------------------------------------------


def _scripted_file(path: Path, goals: list[dict]) -> Path:
    """The tracked response file with every ``synthesize`` payload swapped for
    ``goals``; ``plan``/``check`` entries are reused verbatim so a real dispatch
    still has a scripted loop to run."""
    doc = json.loads(SCRIPT.read_text(encoding="utf-8"))
    for entry in doc["responses"]:
        if entry["tag"] == "synthesize":
            entry["text"] = json.dumps(goals)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def bed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """A private workspace copy plus this module's response file."""
    root = tmp_path_factory.mktemp("iter215")
    ws = root / "workspace"
    shutil.copytree(FIXTURE, ws)
    return {"ws": ws, "script": _scripted_file(root / "responses.json", GOALS)}


@pytest.fixture(autouse=True)
def _default_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the shipped 4.0 threshold in effect so a bare ``Settings()`` agrees
    with the gate the verb ran (the iter-185 ambient-env-leak trap)."""
    monkeypatch.delenv("PLA_AUTO_DISPATCH_MIN_SCORE", raising=False)


def _run_args(bed: dict[str, Path], state_dir: str, *extra: str) -> list[str]:
    return [
        "run",
        "--workspace", str(bed["ws"]),
        "--provider", "scripted",
        "--scripted-responses", str(bed["script"]),
        "--state-dir", state_dir,
        *extra,
    ]


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _dispatch_lines(text: str) -> list[str]:
    """Every emitted command line: a line whose stripped form starts with
    ``pla dispatch`` and carries a ``--slate`` token."""
    return [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip().startswith(_DISPATCH_CMD) and _SLATE_FLAG in ln
    ]


def _slate_token(cmd: str) -> str:
    argv = shlex.split(cmd)
    assert _SLATE_FLAG in argv, f"emitted line has no {_SLATE_FLAG}: {cmd!r}"
    return argv[argv.index(_SLATE_FLAG) + 1]


def _slate_of(path: Path) -> GoalSlate:
    return GoalSlate.model_validate_json(path.read_text(encoding="utf-8"))


def _decisions(slate: GoalSlate) -> list[tuple[str, AutonomyDecision]]:
    """(title, decision) in ranked() order, through the PUBLIC gate, so these
    preconditions encode the CONTRACT rather than the CLI's own bookkeeping."""
    by_id = {d.goal_id: d.decision for d in gate_slate(slate, Settings())}
    return [(g.title, by_id[g.id]) for g in slate.ranked()]


def _assert_fixture_shape(slate: GoalSlate) -> list[str]:
    """PRECONDITION: the 3-auto + 2-needs-approval shape really is present, so
    all three `run` render sites fire.  Returns the AUTO_DISPATCH titles."""
    pairs = _decisions(slate)
    autos = [t for t, d in pairs if d is AutonomyDecision.AUTO_DISPATCH]
    approvals = [t for t, d in pairs if d is AutonomyDecision.NEEDS_APPROVAL]
    assert autos == [AUTO_TOP, AUTO_SECOND, AUTO_THIRD], pairs
    assert approvals == [SENSITIVE, LOW_SCORE], pairs
    return autos


# ---------------------------------------------------------------------------
# Behavior 1 -- a RELATIVE --state-dir still yields ABSOLUTE --slate tokens,
# on every render site, naming the slate this very run wrote.
# ---------------------------------------------------------------------------


def test_b01_relative_state_dir_emits_absolute_slate_tokens_on_every_site(
    bed: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = tmp_path / "cwd"
    base.mkdir()
    monkeypatch.chdir(base)
    rel = ".pla_runs/b01"

    rc, out, err = _run(_run_args(bed, rel, "--dry-run"), capsys)
    assert rc == 0, f"stdout={out}\nstderr={err}"

    written = base / rel / "slate.json"
    assert written.is_file(), "the run must have written the slate it cites"
    autos = _assert_fixture_shape(_slate_of(written))
    expected_doc = json.loads(written.read_text(encoding="utf-8"))

    cmds = _dispatch_lines(out)
    # FAIL CLOSED: zero emitted lines is a failure, never a vacuous pass.
    assert cmds, f"no emitted `{_DISPATCH_CMD} ... {_SLATE_FLAG}` line in:\n{out}"
    # The 3-auto + 2-approval shape fires all three `run` render sites, so a
    # single-site fix cannot satisfy this census.
    assert len(cmds) == len(autos) - 1 + 2 + 1, (
        f"expected 2 needs-approval + 2 deferred + 1 dry-run-preview command "
        f"lines; got {len(cmds)}:\n" + "\n".join(cmds)
    )

    for cmd in cmds:
        token = _slate_token(cmd)
        assert Path(token).is_absolute(), (
            f"{_SLATE_FLAG} token must be absolute so the line pastes anywhere; "
            f"got {token!r} from {cmd!r}"
        )
        assert Path(token).is_file(), f"{token!r} does not name an existing file"
        assert Path(token).samefile(written), (
            f"{token!r} must name the slate this run wrote ({written})"
        )
        assert json.loads(Path(token).read_text(encoding="utf-8")) == expected_doc


# ---------------------------------------------------------------------------
# Behavior 2 + 3 -- a pasted line runs from a FOREIGN directory, and the
# absolute spelling is what makes it run (two-sided control).
# ---------------------------------------------------------------------------


def test_b02_pasted_command_runs_from_a_foreign_directory(
    bed: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = tmp_path / "cwd"
    base.mkdir()
    monkeypatch.chdir(base)
    rel = ".pla_runs/b02"

    rc, out, err = _run(_run_args(bed, rel, "--dry-run"), capsys)
    assert rc == 0, f"stdout={out}\nstderr={err}"
    cmds = _dispatch_lines(out)
    assert cmds, out

    argv = shlex.split(cmds[0])
    assert argv[0] == "pla", cmds[0]
    goal_id = argv[argv.index("--goal-id") + 1]

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    assert not (foreign / "slate.json").exists()
    assert not (foreign / rel.split("/")[0]).exists(), (
        "the foreign cwd must not be able to resolve the relative spelling"
    )
    monkeypatch.chdir(foreign)

    rc2, out2, err2 = _run(argv[1:] + ["--dry-run"], capsys)
    assert rc2 == 0, (
        f"the printed command must run from a foreign cwd: rc={rc2}\n"
        f"cmd={cmds[0]}\nstdout={out2}\nstderr={err2}"
    )
    assert f"[dry-run] would dispatch goal {goal_id}" in out2, out2


def test_b03_two_sided_control_the_relative_spelling_fails_from_that_cwd(
    bed: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The SAME argv as behavior 2 with only the ``--slate`` value put back to the
    caller's relative spelling exits 2 -- so behavior 2 is not passing on a CLI
    that ignores ``--slate``."""
    base = tmp_path / "cwd"
    base.mkdir()
    monkeypatch.chdir(base)
    rel = ".pla_runs/b03"

    rc, out, err = _run(_run_args(bed, rel, "--dry-run"), capsys)
    assert rc == 0, f"stdout={out}\nstderr={err}"
    cmds = _dispatch_lines(out)
    assert cmds, out

    argv = shlex.split(cmds[0])[1:]
    idx = argv.index(_SLATE_FLAG)
    absolute_token = argv[idx + 1]
    relative_argv = list(argv)
    relative_argv[idx + 1] = f"{rel}/slate.json"
    # PRECONDITION: the two spellings really differ, i.e. the fix did something.
    assert relative_argv[idx + 1] != absolute_token

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.chdir(foreign)

    rc3, out3, err3 = _run(relative_argv + ["--dry-run"], capsys)
    assert rc3 == 2, f"expected exit 2 for the relative spelling; got {rc3}\n{out3}\n{err3}"
    assert "slate file not found" in err3, err3


# ---------------------------------------------------------------------------
# Behavior 4 -- an already-absolute --state-dir is echoed character for
# character: no symlink resolution, no `..` collapsing.
# ---------------------------------------------------------------------------


def test_b04_absolute_state_dir_is_echoed_character_for_character(
    bed: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "abs_state"
    rc, out, err = _run(_run_args(bed, str(state_dir), "--dry-run"), capsys)
    assert rc == 0, f"stdout={out}\nstderr={err}"

    cmds = _dispatch_lines(out)
    assert cmds, out
    want = str(state_dir / "slate.json")
    for cmd in cmds:
        assert _slate_token(cmd) == want, (
            f"an already-absolute state dir must be echoed verbatim; "
            f"got {_slate_token(cmd)!r}, want {want!r}"
        )


def test_b04b_an_unresolved_absolute_spelling_is_not_rewritten(
    bed: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Behavior 4's teeth: pass an absolute state dir spelled through a SYMLINK
    and assert the emitted token keeps that spelling.  A ``resolve()``-based
    renderer rewrites it to the link target and fails here, while passing
    ``test_b04`` by accident of ``tmp_path`` already being resolved."""
    real = tmp_path / "real_state"
    real.mkdir()
    link = tmp_path / "link_state"
    link.symlink_to(real, target_is_directory=True)
    # PRECONDITION: the two spellings really differ under resolution.
    assert str(link.resolve()) != str(link)

    rc, out, err = _run(_run_args(bed, str(link), "--dry-run"), capsys)
    assert rc == 0, f"stdout={out}\nstderr={err}"

    cmds = _dispatch_lines(out)
    assert cmds, out
    want = str(link / "slate.json")
    for cmd in cmds:
        assert _slate_token(cmd) == want, (
            f"the caller's absolute spelling must survive unresolved; "
            f"got {_slate_token(cmd)!r}, want {want!r}"
        )


# ---------------------------------------------------------------------------
# Behavior 5 -- the `dispatch --dry-run` echo has the same property.
# ---------------------------------------------------------------------------


def test_b05_dispatch_dry_run_echo_is_absolute(
    bed: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = tmp_path / "cwd"
    base.mkdir()
    monkeypatch.chdir(base)
    rel = ".pla_runs/b05"

    rc, out, err = _run(_run_args(bed, rel, "--dry-run"), capsys)
    assert rc == 0, f"stdout={out}\nstderr={err}"

    written = base / rel / "slate.json"
    slate = _slate_of(written)
    autos = _assert_fixture_shape(slate)
    goal_id = {g.title: g.id for g in slate.goals}[autos[0]]

    # Invoke `dispatch` with a RELATIVE --slate from the dir it resolves in.
    rc2, out2, err2 = _run(
        ["dispatch", _SLATE_FLAG, f"{rel}/slate.json", "--goal-id", goal_id, "--dry-run"],
        capsys,
    )
    assert rc2 == 0, f"rc={rc2}\nstdout={out2}\nstderr={err2}"

    echoed = _dispatch_lines(out2)
    assert echoed, f"no echoed command line in the dry-run preview:\n{out2}"
    for cmd in echoed:
        token = _slate_token(cmd)
        assert Path(token).is_absolute(), f"echoed token must be absolute; got {token!r}"
        assert Path(token).samefile(written), f"{token!r} must name {written}"


# ---------------------------------------------------------------------------
# Behavior 6 -- confinement: only the command renderers are re-spelled.
# ---------------------------------------------------------------------------


def test_b06_run_json_slate_path_keeps_the_callers_spelling(
    bed: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = tmp_path / "cwd"
    base.mkdir()
    monkeypatch.chdir(base)
    rel = ".pla_runs/b06"

    rc, out, err = _run(_run_args(bed, rel, "--dry-run", "--json"), capsys)
    assert rc == 0, f"stdout={out}\nstderr={err}"

    doc = json.loads(out[out.index("{"):])
    assert doc["slate_path"] == f"{rel}/slate.json", (
        "run --json is a machine document graded by examples/check_run.py and "
        f"test_iter158_behavior.py; its slate_path must keep the caller's "
        f"spelling, got {doc['slate_path']!r}"
    )
    assert not Path(doc["slate_path"]).is_absolute(), doc["slate_path"]


def test_b06b_dispatch_preview_display_lines_keep_the_callers_spelling(
    bed: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ``state dir:`` display line of the dry-run preview is out of scope for
    this change, so it still shows what the caller typed."""
    base = tmp_path / "cwd"
    base.mkdir()
    monkeypatch.chdir(base)
    rel = ".pla_runs/b06b"

    rc, out, err = _run(_run_args(bed, rel, "--dry-run"), capsys)
    assert rc == 0, f"stdout={out}\nstderr={err}"
    slate = _slate_of(base / rel / "slate.json")
    goal_id = {g.title: g.id for g in slate.goals}[_assert_fixture_shape(slate)[0]]

    rc2, out2, err2 = _run(
        [
            "dispatch", _SLATE_FLAG, f"{rel}/slate.json", "--goal-id", goal_id,
            "--state-dir", rel, "--dry-run",
        ],
        capsys,
    )
    assert rc2 == 0, f"rc={rc2}\nstdout={out2}\nstderr={err2}"

    display = [ln.strip() for ln in out2.splitlines() if ln.strip().startswith("state dir:")]
    assert display, f"no `state dir:` display line in:\n{out2}"
    assert display[0] == f"state dir:      {rel}", display[0]
