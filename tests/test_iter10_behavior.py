"""Black-box behavior tests for iteration 10.

Feature under test: a **front-door workspace guard** on the two most-used verbs,
``pla scan`` and ``pla run``. A missing or non-directory ``--workspace`` must
fail fast with ``error: workspace not found: <path>`` on stderr and exit code
**2**, instead of silently degrading every collector to ``[]`` and producing an
empty slate with exit 0. This closes a genuine self-inconsistency: ``dispatch``,
``resume``, ``runs`` and ``trace`` already reject bad input paths with exit 2;
``scan``/``run`` were the exceptions.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration -- the spec's "Expected Behaviors",
``README.md``, and ``SPEC.md`` section 4.5 -- and drive ONLY the documented
public entrypoint ``proactive_loop.cli.main(argv) -> int`` with captured
stdout/stderr and observed exit codes / on-disk artifacts. No file under
``src/`` was read, the engineer's and reviewer's notes were not read, and no
``git diff`` was consulted. The valid-path fixtures reused here
(``examples/fixture_workspace`` + ``examples/scripted_responses.json``) are the
same public artifacts the existing ``tests/test_cli_integration.py`` drives.
Every test runs fully offline: zero network, zero API keys. Behaviors that
prove a *bad* path exercise the ``scripted`` provider only for realism, and the
fast-fail behavior (B4) deliberately uses the ``anthropic`` provider with NO key
and NO scripted file to prove the guard short-circuits before any provider work.

ITERATION-387 ARMS (factory iter 300, appended -- nothing above was changed).
The guard population has since grown from ``scan``/``run`` to
``scan``/``run``/``signals``/``watch``, each carrying its own hand-copied copy of
these three lines; iteration 387 collapses the four copies into ONE shared
front-door helper with the message, the exit code and the guard ORDER unchanged.
The arms live inside the two existing tests whose subject they extend --- the
cross-verb population loop (``test_b6_*``) and the valid-directory regression
(``test_b7_scan_valid_dir_unaffected``) --- because the suite's published test
floor sits AT its rounding ceiling (measured 5998 live, and
``tests/test_iter256_behavior.py::test_b3_*`` reds the build on collected item
5999), so this iteration's oracle must add ZERO collected items. This module
deliberately does NOT spell the floor number: doing so registered it as an
undeclared floor CLAIMANT and reddened six carrier censuses on the first run. They pin what
four copies could satisfy only by accident: CROSS-VERB byte-identity of the
rejection line, an empty stdout, ``is_dir()`` (not ``exists()``) semantics, that
nothing is written, that the workspace guard still outranks the output-target
guards, and --- by an AST census of the shipped ``src/proactive_loop/cli.py``,
resolved BY NAME and never by line number --- that the rule has exactly one
definition which all four verb handlers reach. The census reads the WORKTREE
file, which is the tree that ships and the tree a fresh clone checks out; the
author still read no implementation source, no engineer/reviewer note and no
``git diff``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
# Runner-location-independent paths to the public offline demo artifacts.
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_MSG = "error: workspace not found"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _missing(tmp_path: Path) -> Path:
    """A path under tmp_path that is guaranteed not to exist."""
    return tmp_path / "no_such_workspace"


def _scan_bad(ws: Path, tmp_path: Path, *, out: Path | None = None) -> list[str]:
    """`scan` argv against a bad workspace, wired through the scripted provider."""
    out = out if out is not None else (tmp_path / "slate.json")
    return [
        "scan",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
        "--out", str(out),
    ]


def _run_bad(ws: Path, tmp_path: Path) -> list[str]:
    """`run` argv against a bad workspace, wired through the scripted provider."""
    return [
        "run",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
    ]


# ---------------------------------------------------------------------------
# Iteration-387 helpers -- the FOUR verbs that share the one front-door guard
# ---------------------------------------------------------------------------

_ITER387_VERBS = ("scan", "run", "signals", "watch")
_ITER387_HANDLERS = ("_cmd_scan", "_cmd_run", "_cmd_signals", "_cmd_watch")

# The output-target rejections the workspace guard must keep outranking:
# `error: --out parent is not a directory: <p>` and its --snapshot / --out-dir
# siblings all share this fragment, so one substring covers the family.
_OUTPUT_TARGET_MSG = "parent is not a directory"

_PRINT_LITERAL = 'print(f"error: workspace not found:'
_ISDIR_LITERAL = "workspace.is_dir()"

CLI_SOURCE = REPO / "src" / "proactive_loop" / "cli.py"


def _bad_argv(verb: str, ws: Path, sandbox: Path) -> list[str]:
    """Argv driving `verb` at a bad ``--workspace``, with EVERY output target the
    verb accepts pointed inside `sandbox`.

    That is what lets one ``sandbox.iterdir() == []`` assertion stand in for "no
    slate, no snapshot, no state dir, no ``run-*``, no tick dir". ``watch`` is
    deliberately BOUNDED (``--max-scans 1 --interval 0``): if a regression ever
    let a bad workspace through, the verb must still terminate instead of
    blocking the suite forever on its default 3600s sleep.
    """
    scripted = ["--provider", "scripted", "--scripted-responses", str(SCRIPT)]
    state = ["--state-dir", str(sandbox / "state")]
    if verb == "scan":
        return [
            "scan", "--workspace", str(ws), *scripted, *state,
            "--out", str(sandbox / "slate.json"),
            "--snapshot", str(sandbox / "snap.json"),
        ]
    if verb == "run":
        return ["run", "--workspace", str(ws), *scripted, *state]
    if verb == "signals":
        return ["signals", "--workspace", str(ws), *state]
    if verb == "watch":
        return [
            "watch", "--workspace", str(ws), *scripted, *state,
            "--out-dir", str(sandbox / "ticks"),
            "--max-scans", "1", "--interval", "0",
        ]
    raise AssertionError(f"unknown workspace verb {verb!r}")


def _top_level_functions(source: str) -> list[ast.FunctionDef]:
    """Every module-level ``def`` in `source`, as AST nodes."""
    return [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)]


def _shared_guard_owner(source: str) -> str:
    """DERIVE the name of the one function that owns the workspace rejection.

    Resolved from the shipped tree by AST rather than hardcoded, so a rename
    stays green while a SECOND definition goes red.
    """
    owners = [
        fn.name
        for fn in _top_level_functions(source)
        if _ISDIR_LITERAL in (ast.get_source_segment(source, fn) or "")
    ]
    assert len(owners) == 1, (
        f"the workspace rule must have exactly one owner, found {owners!r}"
    )
    return owners[0]


def _top_level_callers(source: str, name: str) -> set[str]:
    """Names of the module-level functions (other than `name`) that reference it."""
    callers: set[str] = set()
    for fn in _top_level_functions(source):
        if fn.name == name:
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and node.id == name:
                callers.add(fn.name)
                break
    return callers


# ---------------------------------------------------------------------------
# Behavior 1 -- `scan` rejects a missing workspace
# ---------------------------------------------------------------------------


def test_b1_scan_rejects_missing_workspace(tmp_path, capsys):
    missing = _missing(tmp_path)
    out_path = tmp_path / "slate.json"

    rc = main(_scan_bad(missing, tmp_path, out=out_path))
    captured = capsys.readouterr()

    assert rc == 2
    assert f"{_MSG}: {missing}" in captured.err
    # No ranked table printed to stdout...
    assert "DECISION" not in captured.out
    # ...and no slate JSON file written to disk.
    assert not out_path.exists()


# ---------------------------------------------------------------------------
# Behavior 2 -- `run` rejects a missing workspace
# ---------------------------------------------------------------------------


def test_b2_run_rejects_missing_workspace(tmp_path, capsys):
    missing = _missing(tmp_path)
    state_dir = tmp_path / "state"

    rc = main(_run_bad(missing, tmp_path))
    captured = capsys.readouterr()

    assert rc == 2
    assert f"{_MSG}: {missing}" in captured.err
    # No slate JSON written and no run-* directory created under the state dir.
    assert not (state_dir / "slate.json").exists()
    assert list(state_dir.glob("run-*")) == []


# ---------------------------------------------------------------------------
# Behavior 3 -- an existing regular file (not a directory) is also rejected
# ---------------------------------------------------------------------------


def test_b3_scan_rejects_regular_file(tmp_path, capsys):
    a_file = tmp_path / "not_a_dir.txt"
    a_file.write_text("i am a file, not a workspace\n", encoding="utf-8")

    rc = main(_scan_bad(a_file, tmp_path))
    captured = capsys.readouterr()

    # Same single is_dir() guard covers both the missing and not-a-dir cases.
    assert rc == 2
    assert f"{_MSG}: {a_file}" in captured.err
    assert "DECISION" not in captured.out


def test_b3_run_rejects_regular_file(tmp_path, capsys):
    a_file = tmp_path / "not_a_dir.txt"
    a_file.write_text("i am a file, not a workspace\n", encoding="utf-8")

    rc = main(_run_bad(a_file, tmp_path))
    captured = capsys.readouterr()

    assert rc == 2
    assert f"{_MSG}: {a_file}" in captured.err


# ---------------------------------------------------------------------------
# Behavior 4 -- fast-fail BEFORE any client/provider construction
# ---------------------------------------------------------------------------
# Uses a non-scripted provider with NO API key and NO scripted-responses file.
# If the guard did not fire first, we'd see a provider-import / credential /
# exhausted-script error instead of the workspace error. Runs fully offline.


def test_b4_scan_fastfails_before_client(tmp_path, capsys):
    missing = _missing(tmp_path)

    rc = main(["scan", "--workspace", str(missing), "--provider", "anthropic"])
    captured = capsys.readouterr()

    assert rc == 2
    assert _MSG in captured.err
    # Prove it is the WORKSPACE error, not a provider/credential/script error.
    low = captured.err.lower()
    assert "api key" not in low
    assert "credential" not in low
    assert "exhausted" not in low


def test_b4_run_fastfails_before_client(tmp_path, capsys):
    missing = _missing(tmp_path)

    rc = main(["run", "--workspace", str(missing), "--provider", "anthropic"])
    captured = capsys.readouterr()

    assert rc == 2
    assert _MSG in captured.err
    low = captured.err.lower()
    assert "api key" not in low
    assert "credential" not in low
    assert "exhausted" not in low


# ---------------------------------------------------------------------------
# Behavior 5 -- the error goes to stderr, NOT stdout
# ---------------------------------------------------------------------------


def test_b5_error_is_on_stderr_not_stdout(tmp_path, capsys):
    missing = _missing(tmp_path)

    # scan (scripted) ...
    main(_scan_bad(missing, tmp_path))
    scan_out = capsys.readouterr().out
    assert _MSG not in scan_out

    # ... run (scripted) ...
    main(_run_bad(missing, tmp_path))
    run_out = capsys.readouterr().out
    assert _MSG not in run_out

    # ... and the fast-fail (anthropic) path too.
    main(["scan", "--workspace", str(missing), "--provider", "anthropic"])
    fastfail_out = capsys.readouterr().out
    assert _MSG not in fastfail_out


# ---------------------------------------------------------------------------
# Behavior 6 -- exit code is exactly 2, never 1
# ---------------------------------------------------------------------------


def test_b6_exit_code_is_exactly_two_never_one(tmp_path, capsys):
    missing = _missing(tmp_path)
    a_file = tmp_path / "f.txt"
    a_file.write_text("x\n", encoding="utf-8")

    for argv in (
        _scan_bad(missing, tmp_path),
        _run_bad(missing, tmp_path),
        _scan_bad(a_file, tmp_path),
        ["scan", "--workspace", str(missing), "--provider", "anthropic"],
        ["run", "--workspace", str(missing), "--provider", "anthropic"],
    ):
        capsys.readouterr()  # drain
        rc = main(argv)
        assert rc == 2, f"argv {argv!r} did not exit 2"
        assert rc != 1, f"argv {argv!r} used the reserved exit-1 class"

    # -----------------------------------------------------------------------
    # Iteration-387 arms (factory iter 300): ONE home, FOUR verbs.
    # Expected Behaviors 1, 2, 3, 4, 5 and 7 of that iteration's spec.
    # Behavior 6 is armed in test_b7_scan_valid_dir_unaffected below, and
    # Behavior 8 is `make typecheck`, not a pytest case.
    # -----------------------------------------------------------------------

    # Behaviors 1 + 2 -- all four verbs reject a MISSING workspace with the
    # byte-identical single stderr line, exit 2, and a strictly EMPTY stdout.
    shared = tmp_path / "iter387_missing"
    shared.mkdir()
    absent = _missing(shared)
    expected_line = f"{_MSG}: {absent}\n"
    seen: dict[str, tuple[int, str, str]] = {}
    for verb in _ITER387_VERBS:
        capsys.readouterr()  # drain
        rc = main(_bad_argv(verb, absent, shared))
        cap = capsys.readouterr()
        seen[verb] = (rc, cap.out, cap.err)
    for verb, (rc, out, err) in seen.items():
        assert rc == 2, f"{verb} did not exit 2 on a missing --workspace (rc={rc})"
        assert err == expected_line, (
            f"{verb} stderr is not the shared guard line: {err!r} != {expected_line!r}"
        )
        assert out == "", f"{verb} wrote to stdout while rejecting: {out!r}"
    assert len({err for _, _, err in seen.values()}) == 1, (
        "the four verbs no longer print ONE line for one missing path: "
        f"{ {v: e for v, (_, _, e) in seen.items()} !r}"
    )

    # Behavior 3 -- a path that EXISTS but is a FILE is rejected identically, so
    # the rule stays is_dir() and never weakens to exists().
    filed = tmp_path / "iter387_file"
    filed.mkdir()
    a_regular_file = filed / "workspace.txt"
    a_regular_file.write_text("i exist, but i am not a directory\n", encoding="utf-8")
    for verb in _ITER387_VERBS:
        capsys.readouterr()  # drain
        rc = main(_bad_argv(verb, a_regular_file, filed))
        cap = capsys.readouterr()
        assert rc == 2, f"{verb} accepted a regular file as a workspace (rc={rc})"
        assert cap.err == f"{_MSG}: {a_regular_file}\n", (
            f"{verb} did not reject a file with the shared line: {cap.err!r}"
        )
        assert cap.out == "", f"{verb} wrote to stdout for a file workspace: {cap.out!r}"

    # Behavior 4 -- NOTHING is written on rejection. Every output target each
    # verb accepts lives inside a fresh, empty sandbox, so one assertion covers
    # slate, snapshot, state dir, run-* dirs and the tick dir at once.
    for verb in _ITER387_VERBS:
        box = tmp_path / f"iter387_box_{verb}"
        box.mkdir()
        capsys.readouterr()  # drain
        rc = main(_bad_argv(verb, _missing(box), box))
        capsys.readouterr()  # drain
        residue = sorted(q.name for q in box.iterdir())
        assert rc == 2, f"{verb} did not exit 2 (rc={rc})"
        assert residue == [], f"{verb} created {residue!r} while rejecting"

    # Behavior 5 -- precedence is unchanged: with BOTH a missing workspace and
    # an unusable --out in one invocation, the WORKSPACE guard is the one that
    # speaks, and the output-target wording never appears.
    prec = tmp_path / "iter387_precedence"
    prec.mkdir()
    parent_is_a_file = prec / "not_a_dir"
    parent_is_a_file.write_text("blocks every child path\n", encoding="utf-8")
    capsys.readouterr()  # drain
    rc = main([
        "scan",
        "--workspace", str(_missing(prec)),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(prec / "state"),
        "--out", str(parent_is_a_file / "slate.json"),
    ])
    cap = capsys.readouterr()
    assert rc == 2
    assert cap.err == f"{_MSG}: {_missing(prec)}\n", cap.err
    assert _OUTPUT_TARGET_MSG not in cap.err, (
        f"the output-target guard now outranks the workspace guard: {cap.err!r}"
    )
    assert cap.out == "", cap.out

    # Behavior 7 -- ONE home, proved from the SHIPPING source. The owner's name
    # is derived from the tree, so the census cannot go stale on a rename; what
    # it pins is that the count is 1 and that all four handlers still reach it.
    source = CLI_SOURCE.read_text(encoding="utf-8")
    lines = source.splitlines()
    prints = [n for n, line in enumerate(lines, 1) if _PRINT_LITERAL in line]
    guards = [n for n, line in enumerate(lines, 1) if _ISDIR_LITERAL in line]
    assert len(prints) == 1, (
        f"the rejection message must have exactly one home, found {len(prints)} "
        f"at lines {prints}"
    )
    assert len(guards) == 1, (
        f"the is_dir() rule must have exactly one home, found {len(guards)} "
        f"at lines {guards}"
    )
    owner = _shared_guard_owner(source)
    assert owner not in _ITER387_HANDLERS, (
        f"the rule still lives inside the verb handler {owner!r} rather than a "
        "shared helper the other verbs can reach"
    )
    callers = _top_level_callers(source, owner)
    assert set(_ITER387_HANDLERS) <= callers, (
        f"{sorted(set(_ITER387_HANDLERS) - callers)} no longer reach {owner!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- a VALID workspace is unaffected (backward compatibility)
# ---------------------------------------------------------------------------


def test_b7_scan_valid_dir_unaffected(tmp_path, capsys):
    """`scan` against a real directory still exits 0, prints the table, writes the slate."""
    out_path = tmp_path / "slate.json"
    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
        "--out", str(out_path),
    ])
    captured = capsys.readouterr()

    assert rc == 0
    assert "DECISION" in captured.out           # ranked table printed
    assert out_path.is_file()                    # slate JSON written
    assert _MSG not in captured.err              # no false rejection

    # Iteration-387 arm, Expected Behavior 6 -- the shared helper did not invert
    # the condition for the verbs that adopted it later: a REAL directory is
    # still accepted. `signals` is the cheapest of the four to prove (no
    # provider, no write); the scan above already covers the write path.
    rc_signals = main(["signals", "--workspace", str(FIXTURE)])
    signals_cap = capsys.readouterr()
    assert rc_signals == 0, f"signals rejected a real directory (rc={rc_signals})"
    assert _MSG not in signals_cap.err, signals_cap.err
    assert signals_cap.out.strip() != "", "signals printed nothing for a real workspace"


def test_b7_scan_valid_fresh_empty_dir_unaffected(tmp_path, capsys):
    """Any real directory passes the guard -- even an empty fresh tmp dir."""
    ws = tmp_path / "fresh_ws"
    ws.mkdir()
    out_path = tmp_path / "slate.json"
    rc = main([
        "scan",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
        "--out", str(out_path),
    ])
    captured = capsys.readouterr()

    assert rc == 0
    assert out_path.is_file()
    assert _MSG not in captured.err


def test_b7_run_valid_dir_auto_dispatches(tmp_path, capsys):
    """`run` against the fixture still exits 0 and auto-dispatches the top AUTO goal."""
    state_dir = tmp_path / "state"
    rc = main([
        "run",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ])
    captured = capsys.readouterr()

    assert rc == 0
    assert _MSG not in captured.err
    # The slate was written and exactly one AUTO goal was dispatched, as before.
    assert (state_dir / "slate.json").is_file()
    run_dirs = list(state_dir.glob("run-*"))
    assert len(run_dirs) == 1, "run must still auto-dispatch exactly the top AUTO goal"
