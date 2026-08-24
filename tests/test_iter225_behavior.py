"""Black-box oracle for factory iteration 245 -- ``pla run --collector NAME``.

Feature under test: the sole autonomous verb can finally scope its own perception.
``run --collector NAME`` is repeatable, is validated against the LIVE collector
registry at parse time, and the verb says out loud that it narrowed.

MODULE NAME (derived from the repo, never from the state dir). ``git ls-files tests``
tops out at ``test_iter224_behavior.py`` (219 iteration oracles tracked) and
``git cat-file -e HEAD:tests/test_iter225_behavior.py`` FAILS, so 225 is the next free
number. The foundry state dir for this ship is ``iter-245``; naming a module from that
counter is how an already-shipped oracle gets silently overwritten.

ISOLATION CONTRACT (honored, no exceptions). Every assertion below is derived from this
iteration's ``pm.md`` Expected Behaviors 1-9, from the product's own observable output
obtained by RUNNING it, and from the conventions of ``tests/test_iter118_behavior.py``
(the ``signals --collector`` oracle: ``_run`` harness, workspace fixture, deliberately
invalid value bound to a NAMED constant) and ``tests/test_iter135_behavior.py`` (the
offline scripted ``run`` invocation). **No file under ``src/`` was read as source text,
no engineer / reviewer / fix note was opened, and no ``git diff`` was consulted.**

THE THREE ORACLES, kept apart on purpose
1. WHAT THE USER SEES -- stdout / stderr of ``main(argv)``.
2. WHAT THE RUN PERCEIVED -- the ``--snapshot`` document, whose every signal carries the
   emitting collector's name in its ``source`` field. That is the narrowing oracle: a
   flag that is parsed and ignored cannot shrink it.
3. WHAT THE PARSER ACCEPTS -- exit code plus the argparse ``invalid choice`` list, which
   must equal the live registry rather than any list written down here.

WHY EVERY IDENTITY COMPARISON MASKS 12-HEX GOAL IDS
Two byte-identical ``run`` invocations do NOT produce byte-identical stdout: the goal ids
printed in the paste-ready ``pla dispatch`` lines differ run to run (measured: two bare
dry-runs into the SAME state dir differ at char 681). So every identity assertion here
masks ``\\b[0-9a-f]{12}\\b`` and is guarded by a bare-vs-bare CONTROL in the same test,
so id churn can never be reported as a narrowing bug -- the technique
``test_iter118_behavior.py`` established for clock-derived ``recent_file`` weights.

OFFLINE, DETERMINISTIC, FRESH-CLONE SAFE
Every invocation uses ``--provider scripted`` with the git-TRACKED
``examples/scripted_responses.json``, so no network, no API key and no ambient config is
touched; every workspace and every ``--state-dir`` lives under ``tmp_path``, so nothing
writes into the checkout and no assertion depends on a gitignored path. No subprocesses,
no clock assertions, and no assertion on docstring or help-text INDENTATION, so the
3.12 and 3.13 CI legs cannot diverge.

Coverage (numbered to match the spec's Expected Behaviors):

1. ``--collector todos`` is accepted; the flag is REPEATABLE and two names mean the
   UNION of the two collectors' perception.
2. Narrowing is real, asserted TWO-SIDED: the narrowed snapshot carries signals from the
   named collector only, a bare run's snapshot carries at least one kind the narrowed one
   LOST, and the named collector's own signals are byte-for-byte unchanged.
3. An unknown name is a parse-time usage error: exit 2, nothing on stdout, no state dir,
   no slate and no snapshot written -- and the accepted values named in the error are
   exactly the live registry.
4. Absent flag is byte-transparent: no narrowing line anywhere, and an all-collectors
   narrowed run minus its one narrowing line is byte-identical to a bare run.
5. Exactly ONE narrowing line, exact format, names sorted lexicographically regardless of
   the order they were passed -- asserted on the REAL (non-dry-run) path too, which is
   the one that executes the loop.
6. Under ``--json`` stdout stays exactly one JSON document, the narrowing line goes to
   stderr, and the payload's key set is unchanged by the feature.
7. ``--dry-run --collector`` reports the narrowing and still executes no loop.
8. Repeating a name is idempotent -- in the ``N`` of the line and in the perception.
9. ``--collector`` composes with ``--json`` / ``--dry-run`` / ``--snapshot`` at once
   without changing any of their existing behavior.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.collectors import all_collectors

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"

#: The narrowing line's stable ASCII prefix -- matched, never reconstructed.
NARROW_PREFIX = "perception narrowed"

#: A value the parser MUST reject. Bound to a name rather than written inline for the
#: same reason ``test_iter118_behavior.py`` binds ``_UNKNOWN_KIND``: a hardcoded invalid
#: literal is indistinguishable from an accidental typo to a corpus scan, and the repo
#: convention for a deliberately-rejected value is this indirection. It is the exact
#: INVERSE of iteration 118's trap -- ``todo`` is a live signal KIND, and the collector
#: that emits it is ``todos``, so this is the most likely real user typo and the one an
#: alias-tolerant parser would quietly accept.
_UNKNOWN_COLLECTOR = "todo"

#: Run-scoped goal ids, which churn between two otherwise identical invocations.
_ID_RE = re.compile(r"\b[0-9a-f]{12}\b")


# ---------------------------------------------------------------------------
# Helpers -- black-box: drive main(), read back exit code + stdout/stderr.
# ---------------------------------------------------------------------------
def _run(argv: list[str]) -> tuple[int, str, str]:
    """Drive ``main(argv)``, normalizing argparse's ``SystemExit`` to a code."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
    except SystemExit as exc:  # argparse usage error / --help
        code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


def _registry() -> list[str]:
    """The live collector names, sorted -- the SAME expression the parser derives from."""
    return sorted(c.name for c in all_collectors())


def _make_workspace(tmp_path: Path) -> Path:
    """A workspace that SEVERAL different collectors perceive.

    Narrowing assertions are vacuous against a workspace only one collector sees, so
    this plants a TODO comment and a source file, which (measured) makes a bare run
    perceive 5 distinct kinds: ``todo``, ``license``, ``ci_config``, ``test_posture``
    and ``recent_file``. Nothing here asserts that exact set -- it is ambient-sensitive
    -- only that the narrowed run is a strict subset of it.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("# TODO: fix this\nx = 1\n", encoding="utf-8")
    (ws / "b.py").write_text("# FIXME: later\ny = 2\n", encoding="utf-8")
    (ws / "NOTES.md").write_text("- idea one\n- [ ] idea two\n", encoding="utf-8")
    return ws


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return _make_workspace(tmp_path)


def _base(ws: Path, state_dir: Path) -> list[str]:
    """A ``run`` argv that is fully offline and writes only under ``tmp_path``."""
    return [
        "run",
        "--workspace",
        str(ws),
        "--state-dir",
        str(state_dir),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
    ]


def _mask(text: str) -> str:
    return _ID_RE.sub("<ID>", text)


def _narrow_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith(NARROW_PREFIX)]


def _snapshot(path: Path) -> dict[str, object]:
    """The snapshot document, fail-closed: a missing file raises rather than returning {}."""
    assert path.is_file(), f"--snapshot did not write {path}"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict) and "signals" in doc, f"malformed snapshot: {doc!r}"
    return doc


def _sources(doc: dict[str, object]) -> set[str]:
    signals = doc["signals"]
    assert isinstance(signals, list)
    return {str(s["source"]) for s in signals}


def _kinds(doc: dict[str, object]) -> set[str]:
    signals = doc["signals"]
    assert isinstance(signals, list)
    return {str(s["kind"]) for s in signals}


def _entries(doc: dict[str, object], sources: set[str]) -> list[tuple[object, ...]]:
    """Signals emitted by ``sources``, as comparable tuples in document order."""
    signals = doc["signals"]
    assert isinstance(signals, list)
    return [
        tuple(sorted(s.items()))
        for s in signals
        if str(s["source"]) in sources
    ]


# ---------------------------------------------------------------------------
# Behavior 0 -- preconditions, so no assertion below can pass vacuously.
# ---------------------------------------------------------------------------
def test_b00_preconditions_hold() -> None:
    assert SCRIPT.is_file(), (
        f"the tracked offline driver {SCRIPT.name} is missing -- every `run` "
        "invocation below would fail for a reason unrelated to this feature"
    )
    names = _registry()
    assert len(names) >= 2, f"narrowing needs >= 2 collectors; registry={names!r}"
    assert _UNKNOWN_COLLECTOR not in names, (
        f"{_UNKNOWN_COLLECTOR!r} became a real collector name -- behavior 3 would now "
        "assert nothing; pick another value the registry does not hold"
    )


# ---------------------------------------------------------------------------
# Behavior 1 -- accepted, and REPEATABLE meaning the union.
# ---------------------------------------------------------------------------
def test_b01_single_collector_is_accepted(ws: Path, tmp_path: Path) -> None:
    code, _out, err = _run(
        [*_base(ws, tmp_path / "st"), "--dry-run", "--collector", "todos"]
    )
    assert code == 0, f"run --collector todos must be accepted; exit={code} stderr={err!r}"


def test_b01_repeated_flag_means_the_union_of_both_collectors(
    ws: Path, tmp_path: Path
) -> None:
    snap = tmp_path / "union.json"
    code, _out, err = _run(
        [
            *_base(ws, tmp_path / "st"),
            "--dry-run",
            "--snapshot",
            str(snap),
            "--collector",
            "todos",
            "--collector",
            "license",
        ]
    )
    assert code == 0, f"two --collector flags must be accepted; exit={code} err={err!r}"
    assert _sources(_snapshot(snap)) == {"todos", "license"}, (
        "--collector todos --collector license must perceive with BOTH collectors and "
        f"nothing else; snapshot sources={_sources(_snapshot(snap))!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- narrowing is REAL, asserted two-sided.
# ---------------------------------------------------------------------------
def test_b02_narrowed_snapshot_loses_kinds_a_bare_run_perceives(
    ws: Path, tmp_path: Path
) -> None:
    narrow_snap, full_snap = tmp_path / "narrow.json", tmp_path / "full.json"
    code_n, _o, err_n = _run(
        [
            *_base(ws, tmp_path / "stn"),
            "--dry-run",
            "--snapshot",
            str(narrow_snap),
            "--collector",
            "todos",
        ]
    )
    code_f, _o2, err_f = _run(
        [*_base(ws, tmp_path / "stf"), "--dry-run", "--snapshot", str(full_snap)]
    )
    assert (code_n, code_f) == (0, 0), f"both runs must exit 0; {code_n=} {code_f=} {err_n=!r} {err_f=!r}"

    narrowed, full = _snapshot(narrow_snap), _snapshot(full_snap)

    # (a) only the named collector contributed.
    assert _sources(narrowed) == {"todos"}, (
        f"only the named collector may contribute; sources={_sources(narrowed)!r}"
    )
    # (b) the bare run genuinely saw MORE -- so a parsed-and-ignored flag cannot pass.
    lost = _kinds(full) - _kinds(narrowed)
    assert lost, (
        "the bare run perceived no kind the narrowed run lost, so this assertion is "
        f"vacuous: full={sorted(_kinds(full))!r} narrowed={sorted(_kinds(narrowed))!r}"
    )
    assert _kinds(narrowed) < _kinds(full), (
        f"narrowed kinds must be a STRICT subset; narrowed={sorted(_kinds(narrowed))!r} "
        f"full={sorted(_kinds(full))!r}"
    )
    # (c) the named collector's own perception is UNCHANGED, not merely present.
    assert _entries(narrowed, {"todos"}) == _entries(full, {"todos"}), (
        "narrowing must not alter the named collector's signals; "
        f"narrowed={_entries(narrowed, {'todos'})!r} full={_entries(full, {'todos'})!r}"
    )
    assert _entries(narrowed, {"todos"}), "the workspace produced no todo signal at all"


def test_b02_narrowed_snapshot_keeps_the_published_document_shape(
    ws: Path, tmp_path: Path
) -> None:
    """The snapshot is what ``pla verify`` grades a slate against, so narrowing may not
    change its key set -- only which signals are inside it."""
    narrow_snap, full_snap = tmp_path / "n.json", tmp_path / "f.json"
    _run(
        [
            *_base(ws, tmp_path / "stn"),
            "--dry-run",
            "--snapshot",
            str(narrow_snap),
            "--collector",
            "todos",
        ]
    )
    _run([*_base(ws, tmp_path / "stf"), "--dry-run", "--snapshot", str(full_snap)])
    narrowed, full = _snapshot(narrow_snap), _snapshot(full_snap)
    assert set(narrowed) == set(full), (
        f"snapshot key set changed: narrowed={sorted(narrowed)!r} full={sorted(full)!r}"
    )
    assert narrowed["workspace_root"] == full["workspace_root"]


# ---------------------------------------------------------------------------
# Behavior 3 -- an unknown name is a PARSE-time usage error, exit 2, no side effects.
# ---------------------------------------------------------------------------
def test_b03_unknown_collector_exits_2_before_anything_is_written(
    ws: Path, tmp_path: Path
) -> None:
    state_dir, snap = tmp_path / "never", tmp_path / "never.json"
    code, out, err = _run(
        [
            *_base(ws, state_dir),
            "--snapshot",
            str(snap),
            "--collector",
            _UNKNOWN_COLLECTOR,
        ]
    )
    assert code == 2, f"an unknown collector must be a usage error (exit 2); got {code}"
    assert out == "", f"a usage error must print nothing on stdout; got {out!r}"
    assert "--collector" in err and "invalid choice" in err, (
        f"stderr must name the offending option and the rejection; got {err!r}"
    )
    assert _UNKNOWN_COLLECTOR in err, f"stderr must quote the rejected value; got {err!r}"
    # The rejection happens BEFORE any client, collector, slate, run dir or snapshot.
    assert not state_dir.exists(), (
        f"a rejected run must not create the state dir; found {sorted(state_dir.iterdir())!r}"
    )
    assert not snap.exists(), "a rejected run must not write the snapshot document"
    assert NARROW_PREFIX not in err, "a rejected run must not report a narrowing"


def test_b03_accepted_values_are_the_live_registry_not_a_hardcoded_list(
    ws: Path, tmp_path: Path
) -> None:
    """The choice list is DERIVED, so adding a collector must widen it with no edit here."""
    _code, _out, err = _run(
        [*_base(ws, tmp_path / "st"), "--collector", _UNKNOWN_COLLECTOR]
    )
    quoted = set(re.findall(r"'([a-z_]+)'", err))
    names = set(_registry())
    missing = names - quoted
    assert not missing, (
        "the argparse choice list must name every LIVE collector (a hardcoded list "
        f"drifts the moment one is added); missing={sorted(missing)!r} stderr={err!r}"
    )
    extra = quoted - names - {_UNKNOWN_COLLECTOR}
    assert not extra, (
        f"the choice list names values the registry does not hold: {sorted(extra)!r}"
    )


def test_b03_help_publishes_the_flag_and_its_repeatability(ws: Path) -> None:
    code, out, err = _run(["run", "--help"])
    assert code == 0, f"run --help must exit 0; got {code} (stderr={err!r})"
    assert "--collector" in out, "run --help must publish the new flag"
    assert "repeatable" in out.lower(), (
        "run --help must say the flag is repeatable, or a user cannot discover the "
        f"union form; help={out!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- absent flag is byte-transparent.
# ---------------------------------------------------------------------------
def test_b04_absent_flag_prints_no_narrowing_line(ws: Path, tmp_path: Path) -> None:
    code, out, err = _run([*_base(ws, tmp_path / "st"), "--dry-run"])
    assert code == 0, f"a bare run must exit 0; got {code} (stderr={err!r})"
    assert NARROW_PREFIX not in out, f"bare stdout must carry no narrowing line: {out!r}"
    assert NARROW_PREFIX not in err, f"bare stderr must carry no narrowing line: {err!r}"


def test_b04_all_collectors_run_minus_its_one_line_is_byte_identical_to_a_bare_run(
    ws: Path, tmp_path: Path
) -> None:
    """The strong form of behavior 4.

    Naming EVERY collector narrows to nothing, so the only legitimate difference from a
    bare run is the single narrowing line. A bare-vs-bare CONTROL runs first, in the same
    state dir, so run-scoped goal-id churn is proved to be the ONLY thing the mask hides
    -- without it a mask could be quietly concealing a real regression.
    """
    state_dir = tmp_path / "st"
    bare = [*_base(ws, state_dir), "--dry-run"]

    code1, out1, err1 = _run(list(bare))
    code2, out2, err2 = _run(list(bare))
    assert (code1, code2) == (0, 0), f"{code1=} {code2=} {err1=!r} {err2=!r}"
    assert _mask(out1) == _mask(out2), (
        "CONTROL FAILED: two identical bare runs differ by more than their goal ids, so "
        "no identity claim below is trustworthy"
    )

    argv = list(bare)
    for name in _registry():
        argv += ["--collector", name]
    code3, out3, err3 = _run(argv)
    assert code3 == 0, f"naming every collector must exit 0; got {code3} (stderr={err3!r})"

    lines = out3.splitlines(keepends=True)
    narrowing = [ln for ln in lines if ln.startswith(NARROW_PREFIX)]
    assert len(narrowing) == 1, f"expected exactly one narrowing line; got {narrowing!r}"
    stripped = "".join(ln for ln in lines if not ln.startswith(NARROW_PREFIX))
    assert _mask(stripped) == _mask(out1), (
        "an all-collectors run must be byte-identical to a bare run once its single "
        "narrowing line is removed -- the feature may add a line and change nothing else"
    )
    assert err3 == err1 == "", f"neither run may write to stderr; {err1=!r} {err3=!r}"


# ---------------------------------------------------------------------------
# Behavior 5 -- exactly one line, exact format, order-independent.
# ---------------------------------------------------------------------------
def test_b05_narrowing_line_format_is_exact_and_order_independent(
    ws: Path, tmp_path: Path
) -> None:
    m = len(_registry())
    forward = [
        *_base(ws, tmp_path / "sta"),
        "--dry-run",
        "--collector",
        "todos",
        "--collector",
        "git_state",
    ]
    reverse = [
        *_base(ws, tmp_path / "stb"),
        "--dry-run",
        "--collector",
        "git_state",
        "--collector",
        "todos",
    ]
    expected = f"{NARROW_PREFIX} to 2 of {m} collectors: git_state, todos"

    for argv, label in ((forward, "todos-then-git_state"), (reverse, "git_state-then-todos")):
        code, out, err = _run(argv)
        assert code == 0, f"{label} must exit 0; got {code} (stderr={err!r})"
        lines = _narrow_lines(out)
        assert lines == [expected], (
            f"{label} must print EXACTLY one narrowing line, lexicographically sorted so "
            f"the output is order-independent; expected {[expected]!r} got {lines!r}"
        )


def test_b05_the_real_non_dry_run_path_prints_the_line_exactly_once(
    ws: Path, tmp_path: Path
) -> None:
    """The dry-run path returns early; the REAL path executes the loop and is the one
    where a second print site or a per-iteration print would show up."""
    state_dir = tmp_path / "st"
    code, out, err = _run([*_base(ws, state_dir), "--collector", "todos"])
    assert code == 0, f"a real narrowed run must exit 0; got {code} (stderr={err!r})"
    assert len(_narrow_lines(out) + _narrow_lines(err)) == 1, (
        "the narrowing line must be printed from exactly ONE place, once per run; "
        f"stdout lines={_narrow_lines(out)!r} stderr lines={_narrow_lines(err)!r}"
    )
    assert sorted(state_dir.glob("run-*")), (
        "the real path must still execute the loop and write a run dir; state dir held "
        f"{sorted(p.name for p in state_dir.iterdir())!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- --json keeps ONE document on stdout and an unchanged key set.
# ---------------------------------------------------------------------------
def test_b06_json_stdout_stays_one_document_and_the_line_goes_to_stderr(
    ws: Path, tmp_path: Path
) -> None:
    code_n, out_n, err_n = _run(
        [*_base(ws, tmp_path / "stn"), "--dry-run", "--json", "--collector", "todos"]
    )
    assert code_n == 0, f"--json --collector must exit 0; got {code_n} (stderr={err_n!r})"
    payload = json.loads(out_n)  # raises if stdout is not exactly one JSON document
    assert NARROW_PREFIX not in out_n, (
        "the narrowing line must NOT land on stdout under --json, which is a machine "
        f"channel; stdout={out_n!r}"
    )
    assert _narrow_lines(err_n) == [f"{NARROW_PREFIX} to 1 of {len(_registry())} collectors: todos"], (
        f"the narrowing line must go to stderr with the human progress; stderr={err_n!r}"
    )

    code_f, out_f, err_f = _run([*_base(ws, tmp_path / "stf"), "--dry-run", "--json"])
    assert code_f == 0, f"the bare --json control must exit 0; got {code_f} ({err_f!r})"
    assert set(payload) == set(json.loads(out_f)), (
        "this feature may not change the --json payload's key set; "
        f"narrowed={sorted(payload)!r} bare={sorted(json.loads(out_f))!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- --dry-run reports the narrowing and still executes no loop.
# ---------------------------------------------------------------------------
def test_b07_dry_run_reports_the_narrowing_and_executes_no_loop(
    ws: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "st"
    code, out, err = _run(
        [*_base(ws, state_dir), "--dry-run", "--collector", "todos"]
    )
    assert code == 0, f"--dry-run --collector must exit 0; got {code} (stderr={err!r})"
    assert _narrow_lines(out) == [f"{NARROW_PREFIX} to 1 of {len(_registry())} collectors: todos"], (
        f"the preview must report the perception the real act would use; stdout={out!r}"
    )
    assert "[dry-run]" in out, f"the dry-run preview line must survive; stdout={out!r}"
    assert not sorted(state_dir.glob("run-*")), (
        "--dry-run must still execute no loop iteration and write no run dir; found "
        f"{sorted(p.name for p in state_dir.glob('run-*'))!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 8 -- repeating a name is idempotent.
# ---------------------------------------------------------------------------
def test_b08_repeating_a_name_behaves_exactly_like_naming_it_once(
    ws: Path, tmp_path: Path
) -> None:
    once_snap, twice_snap = tmp_path / "once.json", tmp_path / "twice.json"
    code_1, out_1, err_1 = _run(
        [
            *_base(ws, tmp_path / "st1"),
            "--dry-run",
            "--snapshot",
            str(once_snap),
            "--collector",
            "todos",
        ]
    )
    code_2, out_2, err_2 = _run(
        [
            *_base(ws, tmp_path / "st2"),
            "--dry-run",
            "--snapshot",
            str(twice_snap),
            "--collector",
            "todos",
            "--collector",
            "todos",
        ]
    )
    assert (code_1, code_2) == (0, 0), f"{code_1=} {code_2=} {err_1=!r} {err_2=!r}"
    expected = [f"{NARROW_PREFIX} to 1 of {len(_registry())} collectors: todos"]
    assert _narrow_lines(out_2) == expected, (
        "a duplicated name must count ONCE in N and must not be listed twice; "
        f"got {_narrow_lines(out_2)!r}"
    )
    assert _narrow_lines(out_1) == _narrow_lines(out_2)
    assert _snapshot(once_snap)["signals"] == _snapshot(twice_snap)["signals"], (
        "duplicating a name must not change what was perceived"
    )


# ---------------------------------------------------------------------------
# Behavior 9 -- composition with every existing run flag at once.
# ---------------------------------------------------------------------------
def test_b09_composes_with_json_dry_run_and_snapshot_simultaneously(
    ws: Path, tmp_path: Path
) -> None:
    state_dir, snap = tmp_path / "st", tmp_path / "combo.json"
    code, out, err = _run(
        [
            *_base(ws, state_dir),
            "--json",
            "--dry-run",
            "--snapshot",
            str(snap),
            "--collector",
            "todos",
        ]
    )
    assert code == 0, f"the four flags must compose; got {code} (stderr={err!r})"

    payload = json.loads(out)  # --json: still exactly one document
    assert payload["workspace_root"] == str(ws)
    assert NARROW_PREFIX not in out
    assert _narrow_lines(err) == [f"{NARROW_PREFIX} to 1 of {len(_registry())} collectors: todos"]
    # --snapshot: written, and it inherited the narrowing by construction.
    assert _sources(_snapshot(snap)) == {"todos"}, (
        "the audit document must record what the run ACTUALLY saw; sources="
        f"{_sources(_snapshot(snap))!r}"
    )
    # --dry-run: still no loop.
    assert not sorted(state_dir.glob("run-*")), "--dry-run must remain a preview"
    # The slate the other flags depend on is still written.
    assert (state_dir / "slate.json").is_file(), (
        f"the slate must still be written; state dir held "
        f"{sorted(p.name for p in state_dir.iterdir())!r}"
    )
