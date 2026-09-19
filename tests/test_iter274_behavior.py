"""Black-box behavior tests for foundry iteration 316 (ROADMAP #295) -- the goals-less
``--slate`` guard moves INTO ``_load_slate`` so EVERY slate-consuming verb fails closed.

WHY THIS ITERATION EXISTS. Foundry iter 298 taught ``verify`` to refuse a JSON object with
no top-level ``goals`` key (``GoalSlate`` defaults every field, so after validation "no
``goals`` key" and "zero goals" are the SAME object). That argument is not specific to
``verify``: at HEAD ``explain`` printed ``(no goals in slate)`` at exit 0, ``diff`` printed
``(no differences)`` at exit 0, ``trend --dir`` printed ``ticks read: 2`` at exit 0 and
``dispatch`` blamed the goal id (exit 2) when handed a document that is not a slate -- an
audit verb that reports a clean result on a non-slate is a gate that cannot fail. This
iteration folds the check into the shared loader so the five verbs share one read, one
code path and one message.

WHAT THIS MODULE GRADES: Expected Behaviors 1-7 of the iteration spec, one item each
(the spec caps the module at 7 collected items; every verb/flag combination of a behavior
lives INSIDE its item). ``README.md`` byte-identity with HEAD is a commit-time measurement
that belongs in the tester's report, not in a test that is vacuous in every fresh clone.

ISOLATION CONTRACT (honored). Every assertion is written from the spec's Expected
Behaviors; the implementation was not read. The CLI is driven through the installed
``pla`` console script in a child process so stdout/stderr are real fds (the convention of
``tests/test_iter177_behavior.py``). Behavior 6's source-level clause is checked the way
the spec words it -- an ``ast`` walk of the two public helper bodies -- without a human
reading them.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

_PHRASE = "no top-level 'goals' array"
_REPO = Path(__file__).resolve().parents[1]
_ROW_295 = (
    "- #295 Every slate verb refuses a goals-less object via `_load_slate`; "
    "`verify`'s pre-check retires (foundry iter 316)"
)


def _console_script() -> Path:
    """The installed ``pla`` console script (declared in pyproject, installed by ``uv sync``)."""
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, (
        f"the `pla` console script must be installed; searched {[str(c) for c in candidates]}"
    )
    return script


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the real CLI in its own process so stdout/stderr are real fds."""
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def _doc(tmp_path: Path, name: str, text: str) -> str:
    """Write ``text`` under ``tmp_path`` and return the path AS IT WILL APPEAR ON ARGV."""
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).write_text(text, encoding="utf-8")
    return name  # relative to cwd=tmp_path, so the message must echo exactly this


def _goals_less_shapes(tmp_path: Path) -> dict[str, str]:
    """The spec's three goals-less shapes: ``{}``, workspace_root-only, a real snapshot."""
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    snap = _run("signals", "--json", "--workspace", str(ws), cwd=tmp_path)
    assert snap.returncode == 0, (snap.returncode, snap.stderr)
    body = json.loads(snap.stdout)
    assert isinstance(body, dict) and "goals" not in body, (
        "the swapped-argument arm needs a snapshot document with no top-level `goals` key"
    )
    return {
        "empty_object": _doc(tmp_path, "gl_empty.json", "{}"),
        "workspace_root_only": _doc(tmp_path, "gl_ws.json", json.dumps({"workspace_root": "/x"})),
        "real_snapshot": _doc(tmp_path, "gl_snap.json", snap.stdout),
    }


def _assert_one_error_line(proc: subprocess.CompletedProcess[str], path: str, where: str) -> None:
    """Spec's 'one error line': exit 1, EMPTY stdout, exactly one stderr line, named path."""
    assert proc.returncode == 1, (
        f"goals-less slate must fail CLOSED at exit 1 ({where}); got {proc.returncode}; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert proc.stdout == "", f"the guard must fire BEFORE any rendering ({where}); {proc.stdout!r}"
    errs = _lines(proc.stderr)
    assert len(errs) == 1, f"exactly ONE error line ({where}); got {errs}"
    prefix = f"error: invalid slate file '{path}': "
    assert errs[0].startswith(prefix), f"({where}) expected prefix {prefix!r}; got {errs[0]!r}"
    assert _PHRASE in errs[0], f"({where}) message must carry {_PHRASE!r}; got {errs[0]!r}"


# ----------------------------------------------------------------------------------------
# Behavior 1 -- `explain` fails closed (bare, --json, --goal-id) on all three shapes.
# ----------------------------------------------------------------------------------------
def test_b1_explain_fails_closed_on_goals_less_object(tmp_path: Path) -> None:
    shapes = _goals_less_shapes(tmp_path)
    for label, gl in shapes.items():
        _assert_one_error_line(_run("explain", "--slate", gl, cwd=tmp_path), gl, f"explain {label}")
    gl = shapes["empty_object"]
    # --json: no stdout at all, so no `[]`.
    _assert_one_error_line(_run("explain", "--slate", gl, "--json", cwd=tmp_path), gl, "explain --json")
    # --goal-id: the load precedes the id lookup, so exit 1, NOT the unknown-id exit 2.
    proc = _run("explain", "--slate", gl, "--goal-id", "abc", cwd=tmp_path)
    _assert_one_error_line(proc, gl, "explain --goal-id abc")
    assert "not found" not in proc.stderr, f"the id lookup must not run; got {proc.stderr!r}"


# ----------------------------------------------------------------------------------------
# Behavior 2 -- `dispatch --dry-run` fails closed; the argv-shape refusal still outranks it.
# ----------------------------------------------------------------------------------------
def test_b2_dispatch_dry_run_fails_closed_and_argv_refusal_outranks_load(tmp_path: Path) -> None:
    shapes = _goals_less_shapes(tmp_path)
    for label, gl in shapes.items():
        proc = _run("dispatch", "--slate", gl, "--goal-id", "abc", "--dry-run", cwd=tmp_path)
        _assert_one_error_line(proc, gl, f"dispatch --dry-run {label}")
        assert "goal id" not in proc.stderr, f"must not blame the id ({label}); {proc.stderr!r}"
    # --dry-run + --json is refused at exit 2 BEFORE the file is read: a path that does not
    # even exist yields the argv message, not `slate file not found` and not the load error.
    proc = _run(
        "dispatch", "--slate", "absent.json", "--goal-id", "abc", "--dry-run", "--json",
        cwd=tmp_path,
    )
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert proc.stdout == ""
    errs = _lines(proc.stderr)
    assert errs == ["error: --dry-run cannot be combined with --json"], errs


# ----------------------------------------------------------------------------------------
# Behavior 3 -- `diff` fails closed on either side, with --json, and in --dir mode.
# ----------------------------------------------------------------------------------------
def test_b3_diff_fails_closed_either_side_json_and_dir(tmp_path: Path) -> None:
    gl = _doc(tmp_path, "gl.json", "{}")
    valid = _doc(tmp_path, "valid.json", json.dumps({"goals": []}))
    _assert_one_error_line(_run("diff", "--old", gl, "--new", valid, cwd=tmp_path), gl, "diff old=GL")
    _assert_one_error_line(_run("diff", "--old", valid, "--new", gl, cwd=tmp_path), gl, "diff new=GL")
    proc = _run("diff", "--old", gl, "--new", valid, "--json", cwd=tmp_path)
    _assert_one_error_line(proc, gl, "diff --json")
    # --dir: slate-001 goals-less, slate-002 valid -> the message names slate-001 AS GIVEN.
    tick1 = _doc(tmp_path, "D/slate-001.json", "{}")
    _doc(tmp_path, "D/slate-002.json", json.dumps({"goals": []}))
    _assert_one_error_line(_run("diff", "--dir", "D", cwd=tmp_path), tick1, "diff --dir")
    _assert_one_error_line(_run("diff", "--dir", "D", "--json", cwd=tmp_path), tick1, "diff --dir --json")


# ----------------------------------------------------------------------------------------
# Behavior 4 -- `trend --dir` fails closed on one goals-less tick, human and --json.
# ----------------------------------------------------------------------------------------
def test_b4_trend_dir_fails_closed_on_goals_less_tick(tmp_path: Path) -> None:
    tick1 = _doc(tmp_path, "D/slate-001.json", "{}")
    _doc(tmp_path, "D/slate-002.json", json.dumps({"goals": []}))
    for flags in ([], ["--json"]):
        proc = _run("trend", "--dir", "D", *flags, cwd=tmp_path)
        _assert_one_error_line(proc, tick1, f"trend --dir {flags or ['(bare)']}")
        assert "ticks read" not in proc.stdout + proc.stderr
    # Same path as a schema-invalid tick (`{"goals": 4}`): exit 1, same `error:` prefix.
    bad = _doc(tmp_path, "E/slate-001.json", json.dumps({"goals": 4}))
    _doc(tmp_path, "E/slate-002.json", json.dumps({"goals": []}))
    proc = _run("trend", "--dir", "E", cwd=tmp_path)
    assert proc.returncode == 1 and proc.stdout == ""
    assert _lines(proc.stderr)[0].startswith(f"error: invalid slate file '{bad}': ")


# ----------------------------------------------------------------------------------------
# Behavior 5 -- structural, not a count: `{"goals": []}` stays legitimate on every verb;
# non-object / unparseable / wrong-typed documents keep the pydantic-sanitized message.
# ----------------------------------------------------------------------------------------
def test_b5_empty_goals_still_valid_and_malformed_docs_keep_pydantic_message(tmp_path: Path) -> None:
    empty = _doc(tmp_path, "e.json", json.dumps({"goals": []}))
    snap = _doc(tmp_path, "s.json", json.dumps({"signals": []}))
    _doc(tmp_path, "D/slate-001.json", json.dumps({"goals": []}))
    _doc(tmp_path, "D/slate-002.json", json.dumps({"goals": []}))
    checks: list[tuple[list[str], str]] = [
        (["explain", "--slate", empty], "(no goals in slate)"),
        (["diff", "--old", empty, "--new", empty], "(no differences)"),
        (["trend", "--dir", "D"], "ticks read: 2"),
        (["verify", "--slate", empty, "--snapshot", snap], ""),
    ]
    for argv, needle in checks:
        proc = _run(*argv, cwd=tmp_path)
        assert proc.returncode == 0, (argv, proc.returncode, proc.stdout, proc.stderr)
        assert needle in proc.stdout, (argv, proc.stdout)
        assert _PHRASE not in proc.stderr, (argv, proc.stderr)
    # dispatch: the load SUCCEEDS on an empty slate, so the id lookup runs and blames the id.
    proc = _run("dispatch", "--slate", empty, "--goal-id", "abc", "--dry-run", cwd=tmp_path)
    assert proc.returncode == 2 and "goal id 'abc' not found" in proc.stderr, (
        proc.returncode, proc.stderr
    )
    # Malformed documents: the presence check must step aside and let pydantic report --
    # one input class, one message: `invalid slate file '<path>': <N> validation error[s]...`
    sanitized = re.compile(r"^error: invalid slate file '(?P<p>[^']+)': \d+ validation errors?(; first at \S+)?$")
    docs = {
        "list.json": "[]",
        "number.json": "4",
        "notjson.json": "not json",
        "wrongtype.json": json.dumps({"goals": 4}),
    }
    for name, text in docs.items():
        path = _doc(tmp_path, name, text)
        for argv in (["explain", "--slate", path], ["diff", "--old", path, "--new", empty]):
            proc = _run(*argv, cwd=tmp_path)
            assert proc.returncode == 1 and proc.stdout == "", (argv, proc.returncode, proc.stdout)
            errs = _lines(proc.stderr)
            assert len(errs) == 1, (argv, errs)
            m = sanitized.match(errs[0])
            assert m is not None and m.group("p") == path, (argv, errs[0])
            assert _PHRASE not in errs[0], (argv, errs[0])
            for leak in ("GoalSlate", "input_value=", "[type=", "https://"):
                assert leak not in errs[0], (argv, leak, errs[0])


# ----------------------------------------------------------------------------------------
# Behavior 6 -- `verify` unchanged; the snapshot ladder still runs first; the goals-less
# check has ONE caller (`_load_slate`), and `_load_slate` reads the file exactly once.
# ----------------------------------------------------------------------------------------
def test_b6_verify_unchanged_and_check_reachable_only_through_loader(tmp_path: Path) -> None:
    gl = _doc(tmp_path, "gl.json", "{}")
    snap = _doc(tmp_path, "s.json", json.dumps({"signals": []}))
    for flags in ([], ["--json"], ["--fail-on-unresolved"]):
        proc = _run("verify", "--slate", gl, "--snapshot", snap, *flags, cwd=tmp_path)
        _assert_one_error_line(proc, gl, f"verify {flags or ['(bare)']}")
    # A BAD snapshot plus a goals-less slate reports the SNAPSHOT first, at exit 2.
    proc = _run("verify", "--slate", gl, "--snapshot", "absent.json", cwd=tmp_path)
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    errs = _lines(proc.stderr)
    assert len(errs) == 1 and "absent.json" in errs[0] and _PHRASE not in errs[0], errs

    # Source-level clause, exactly as the spec words it (no human read of the bodies).
    from proactive_loop import cli

    def _calls(fn: Callable[..., object]) -> list[str]:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name):
                    names.append(f.id)
                elif isinstance(f, ast.Attribute):
                    names.append(f.attr)
        return names

    assert hasattr(cli, "_reject_goals_less_slate"), "the shipped helper must still exist"
    verify_calls = _calls(cli._cmd_verify)
    assert "_reject_goals_less_slate" not in verify_calls, (
        "_cmd_verify must reach the goals-less check ONLY through _load_slate; "
        f"direct calls found: {verify_calls.count('_reject_goals_less_slate')}"
    )
    loader_calls = _calls(cli._load_slate)
    assert loader_calls.count("read_text") == 1, (
        "_load_slate must call path.read_text() exactly ONCE (one read serves the presence "
        f"check and model_validate_json); got {loader_calls.count('read_text')}"
    )
    assert "_reject_goals_less_slate" in loader_calls, (
        "_load_slate must be the caller of the goals-less check"
    )


# ----------------------------------------------------------------------------------------
# Behavior 7 -- docs and record sites: SPEC §3 bullet, ROADMAP row #295, ledger provenance.
# ----------------------------------------------------------------------------------------
def test_b7_spec_bullet_roadmap_row_and_ledger_provenance() -> None:
    spec_lines = (_REPO / "SPEC.md").read_text(encoding="utf-8").splitlines()
    first = next(i for i, ln in enumerate(spec_lines) if ln.startswith("- Corrupt-load sanitization:"))
    body = [spec_lines[first]]
    for ln in spec_lines[first + 1 :]:
        if not ln.startswith("  "):  # the bullet ends at the first non-continuation line
            break
        body.append(ln)
    bullet = re.sub(r"\s+", " ", " ".join(body))  # the bullet is hard-wrapped; normalise
    for verb in ("`explain`", "`dispatch`", "`verify`", "`diff`", "`trend`"):
        assert verb in bullet, f"§3 corrupt-load bullet must name {verb}"
    assert "_load_slate" in bullet and _PHRASE in bullet, bullet
    assert "exit `1`" in bullet, "the bullet must state the goals-less refusal exits 1"

    roadmap = (_REPO / "ROADMAP.md").read_text(encoding="utf-8").splitlines()
    idx = roadmap.index(_ROW_295)
    assert roadmap[idx - 1].startswith("- #294 "), roadmap[idx - 1]
    assert len(_ROW_295) <= 120, len(_ROW_295)
    assert roadmap.count(_ROW_295) == 1

    ledger_src = (_REPO / "tests" / "test_iter264_behavior.py").read_text(encoding="utf-8")
    assert "82 -> 83" in ledger_src and "83 -> 84" in ledger_src, (
        "the provenance block must carry BOTH the #294 and #295 steps"
    )
    assert "#295" in ledger_src and "#294" in ledger_src
    from tests import test_iter264_behavior as ledger

    assert ledger.EXPECTED_LEDGER_ROWS >= 84, ledger.EXPECTED_LEDGER_ROWS
