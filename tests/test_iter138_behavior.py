"""Black-box behavior tests for commit-seq **factory iter 138** (state dir iter-131):
``pla signals --baseline FILE`` -- the perception inspector's first INSTANCE-aware
selection axis (a baseline ratchet: report NEW findings only).

ISOLATION CONTRACT: every assertion below was derived from this iteration's spec
(``pm.md`` "Expected Behaviors" 1-11) plus the conventions of the existing modules
under ``tests/`` (chiefly ``tests/test_iter132_behavior.py``, the sibling
``--exclude-path`` module).  Where the shape of the output was needed it was obtained
by RUNNING the installed ``pla`` console script against throwaway fixture trees and
reading its stdout/stderr/exit status.

PROVENANCE, stated because the contract above is scoped: behavior 1's oracle was
written by the tester stage under FULL isolation -- no file under ``src/`` read, no
upstream stage note opened, no ``git diff`` consulted.  That stage was then killed
mid-run by an infrastructure stall, so behaviors 2-11 and the two regression cases
were added by the FIX-TESTS stage, which is NOT isolated: it read the implementation
and the fix pass's own note.  What that changes, honestly: every expectation here is
still taken from ``pm.md`` and confirmed by RUNNING the shipped console script, but
two clauses were re-derived rather than trusted, and both deviations are recorded at
their tests -- the ``--timings`` block cannot be "byte-identical" (the elapsed-ms
column is wall-clock, so the (row, count) pairing is asserted instead), and behavior
3's live half is unreachable through the CLI (no fixture tree yields two signals with
equal 6-tuples), so it is asserted against the shared selection predicate directly.
The two regression cases came from the fix pass's handoff: a present-but-UNHASHABLE
identity value used to escape as a raw traceback, and the ``--help`` used to claim the
wrong exit code for an unreadable file.

Fully offline and deterministic: synthetic ``tmp_path_factory`` trees only (never the
in-repo tree, so no collector can leak repo state -- iter-15 lesson), no network, no
API key, no ``git`` subprocess, and NO DURATION IS ASSERTED ANYWHERE (roadmap row
 #129's standing constraint).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from proactive_loop.cli import _select_signals, _signal_identity
from proactive_loop.models import ContextSignal, WorkspaceSnapshot

_KEYS = ("source", "kind", "summary", "detail", "path", "weight")


def _console_script() -> Path:
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, "the `pla` console script must be installed"
    return script


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _signals(ws: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run("signals", "--workspace", ".", *extra, cwd=ws)


def _records(ws: Path, *extra: str) -> list[dict]:
    proc = _signals(ws, "--json", *extra)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    doc = json.loads(proc.stdout)
    return list(doc["signals"])


def _build(root: Path) -> None:
    (root / "sub").mkdir()
    (root / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "keep.py").write_text("k = 5\n", encoding="utf-8")
    filler = "\n".join(f"line {i}" for i in range(1, 12))
    (root / "notes.md").write_text(
        filler + "\n- TODO: alpha here\n- TODO: beta here\n", encoding="utf-8"
    )


@pytest.fixture(scope="module")
def ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("iter138_main")
    _build(root)
    return root


def _baseline(ws: Path, path: Path, records: list[dict]) -> str:
    path.write_text(
        json.dumps({"workspace_root": ".", "signals": records}), encoding="utf-8"
    )
    return str(path)


# Behavior 1 (checkpoint oracle): a full baseline empties the --json surface.
def test_b01_full_baseline_suppresses_every_signal(ws: Path, tmp_path: Path) -> None:
    base = _records(ws)
    assert base, "fixture precondition: the workspace must emit signals"
    bl = _baseline(ws, tmp_path / "base.json", base)
    assert _records(ws, "--baseline", bl) == []


# ======================================================================================
# Behaviors 2-11, plus the two regression cases the fix pass handed over.
# Added at the FIX-TESTS stage after the tester stage was killed mid-run -- see the
# PROVENANCE paragraph in the module docstring for exactly what that changes.
# ======================================================================================

_EMPTY_MARKER = "(no signals collected)\n"

# The four surfaces the spec requires to narrow IDENTICALLY. Kept as data so every
# "same on every surface" behavior below iterates the same list.
_SURFACES: tuple[tuple[str, ...], ...] = (
    (),
    ("--json",),
    ("--summary",),
    ("--summary", "--json"),
)


def _stdout(ws: Path, *extra: str) -> str:
    """stdout of a successful `signals` run, asserting exit 0 first."""
    proc = _signals(ws, *extra)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    return proc.stdout


def _raw_baseline(path: Path, text: str) -> str:
    """Write a baseline file VERBATIM, for the malformed cases JSON cannot express."""
    path.write_text(text, encoding="utf-8")
    return str(path)


# Behavior 1, remaining three surfaces. The checkpoint oracle above pins `--json`; the
# human listing and both `--summary` forms must empty out with it, each degrading to the
# marker the pre-existing `--min-weight`/`--exclude-path` knobs already established.
def test_b01_full_baseline_empties_the_other_three_surfaces(ws: Path, tmp_path: Path) -> None:
    bl = _baseline(ws, tmp_path / "full.json", _records(ws))
    assert _stdout(ws, "--baseline", bl) == _EMPTY_MARKER
    assert _stdout(ws, "--summary", "--baseline", bl) == _EMPTY_MARKER
    doc = json.loads(_stdout(ws, "--summary", "--json", "--baseline", bl))
    assert doc["summary"] == {}
    assert doc["total"] == 0


# Behavior 2: staleness fails toward REPORTING. A baseline entry whose text has moved on
# matches nothing, so every surface is byte-identical to the same command without a
# baseline -- noise, never a missed finding.
def test_b02_a_stale_baseline_entry_hides_nothing_on_any_surface(
    ws: Path, tmp_path: Path
) -> None:
    live = _records(ws)
    stale = dict(live[0])
    stale["summary"] = f"{stale['summary']} -- subject text that has since moved on"
    bl = _baseline(ws, tmp_path / "stale.json", [stale])
    for surface in _SURFACES:
        assert _stdout(ws, *surface, "--baseline", bl) == _stdout(ws, *surface), surface


# Behavior 3, baseline side: the document is loaded into a SET, so repeating an entry is
# idempotent -- three copies suppress exactly what one copy suppresses.
def test_b03_repeating_a_baseline_entry_is_idempotent(ws: Path, tmp_path: Path) -> None:
    live = _records(ws)
    once = _baseline(ws, tmp_path / "once.json", [live[0]])
    thrice = _baseline(ws, tmp_path / "thrice.json", [live[0], live[0], live[0]])
    expected = [s for s in live if s != live[0]]
    assert _records(ws, "--baseline", once) == expected
    assert _records(ws, "--baseline", thrice) == expected


# Behavior 3, live side: "two live signals with identical 6-tuples are both hidden by one
# entry" -- SET semantics, not multiset. This is the one clause no CLI fixture can reach
# (measured: 12 of 12 and 9 of 9 live identities are unique on these trees, because every
# collector's identity carries either a distinct `path` or a distinct line-anchored
# `detail`). Asserted directly against the shared selection predicate instead, which is
# the code path all four surfaces and the exit gate call.
def test_b03_one_baseline_entry_hides_every_identical_live_signal() -> None:
    signal = ContextSignal(
        source="todos",
        kind="todo",
        summary="TODO: same text",
        detail="an identical excerpt",
        path="notes.md",
        weight=0.6,
    )
    snapshot = WorkspaceSnapshot(
        root=".", signals=[signal, signal.model_copy(), signal.model_copy()]
    )
    assert len({_signal_identity(s) for s in snapshot.signals}) == 1, "fixture precondition"
    assert len(_select_signals(snapshot)) == 3
    assert _select_signals(snapshot, baseline={_signal_identity(signal)}) == []


# Behavior 4: identity spans EVERY published key, so agreeing on five of six is a
# different signal. `weight` and `path` null are called out by the spec and are the two
# most likely to have been folded into a looser comparison.
_MUTATIONS: tuple[tuple[str, object], ...] = (
    ("source", "a-collector-name-that-does-not-exist"),
    ("kind", "note"),
    ("summary", "TODO: something else entirely"),
    ("detail", "a detail the live signal does not carry"),
    ("path", "some/other/file.md"),
    ("path", None),
    ("weight", 0.123456),
)


@pytest.mark.parametrize(
    ("key", "value"), _MUTATIONS, ids=[f"{k}-{v!r}" for k, v in _MUTATIONS]
)
def test_b04_differing_in_any_one_key_is_a_different_identity(
    ws: Path, tmp_path: Path, key: str, value: object
) -> None:
    live = _records(ws)
    victim = next(s for s in live if s["kind"] == "todo")
    entry = dict(victim)
    entry[key] = value
    assert entry != victim, "fixture precondition: the mutation must change the entry"
    bl = _baseline(ws, tmp_path / "mutated.json", [entry])
    assert _records(ws, "--baseline", bl) == live


# Behavior 5: the exit gate narrows with the view, and the tripped line counts only the
# SURVIVORS. Two-sided, as the acceptance criteria require: exit 0 when the baseline
# covers every gated signal, exit 5 when one survives.
def test_b05_the_fail_on_kind_gate_narrows_with_the_view(ws: Path, tmp_path: Path) -> None:
    live = _records(ws)
    todos = [s for s in live if s["kind"] == "todo"]
    assert len(todos) >= 2, "fixture precondition: at least two todo signals"

    armed = _signals(ws, "--fail-on-kind", "todo")
    assert armed.returncode == 5
    assert f"gate: fail-on-kind tripped -- todo={len(todos)}" in armed.stderr

    covered = _baseline(ws, tmp_path / "all_todos.json", todos)
    quiet = _signals(ws, "--fail-on-kind", "todo", "--baseline", covered)
    assert quiet.returncode == 0
    assert "gate:" not in quiet.stderr

    most = _baseline(ws, tmp_path / "most_todos.json", todos[:-1])
    tripped = _signals(ws, "--fail-on-kind", "todo", "--baseline", most)
    assert tripped.returncode == 5
    assert "gate: fail-on-kind tripped -- todo=1" in tripped.stderr


# Behavior 6, composition: a logical AND with the other selection knobs, in any order.
def test_b06_composes_as_a_logical_and_with_the_other_knobs(
    ws: Path, tmp_path: Path
) -> None:
    live = _records(ws)
    todos = [s for s in live if s["kind"] == "todo"]
    one_todo = _baseline(ws, tmp_path / "one_todo.json", todos[:1])
    full = _baseline(ws, tmp_path / "full.json", live)

    assert _records(ws, "--kind", "todo", "--baseline", one_todo) == todos[1:]
    assert _records(ws, "--min-weight", "0.0", "--baseline", full) == []

    excluded = _records(ws, "--exclude-path", "sub/*")
    assert excluded != live, "fixture precondition: the glob must exclude something"
    assert todos[0] in excluded, "fixture precondition: the glob must not hide the todo"
    both = _records(ws, "--exclude-path", "sub/*", "--baseline", one_todo)
    assert both == [s for s in excluded if s != todos[0]]


def _timing_rows(stderr: str) -> list[tuple[str, str]]:
    """(collector name, signal count) per --timings row -- never the elapsed-ms column,
    which is wall-clock (roadmap row #129: no duration is ever asserted)."""
    rows: list[tuple[str, str]] = []
    for line in stderr.splitlines():
        if not line.startswith("  "):
            continue
        fields = line.split()
        if len(fields) >= 2:
            rows.append((fields[0], fields[-1]))
    return rows


# Behavior 6, cost side: the flag is display-only, so which collectors RUN and what they
# each emitted are unchanged. NOTE the spec says the --timings block is "byte-identical";
# measured, it cannot be -- the elapsed-ms column is wall-clock and differs between two
# runs of the SAME command. The checkable claim, and the one the sibling --exclude-path
# module already pins, is that every (row name, signal count) pair is identical.
def test_b06_the_timings_block_is_unchanged_by_the_flag(ws: Path, tmp_path: Path) -> None:
    full = _baseline(ws, tmp_path / "full.json", _records(ws))
    without = _signals(ws, "--timings")
    with_flag = _signals(ws, "--timings", "--baseline", full)
    assert without.returncode == 0
    assert with_flag.returncode == 0
    assert "collector timings" in without.stderr
    rows = _timing_rows(without.stderr)
    assert rows, "fixture precondition: the timings block must have rows"
    assert _timing_rows(with_flag.stderr) == rows


# Behavior 7: an empty `signals` array is VALID and suppresses nothing, byte-identically
# to omitting the flag -- which is also the checkable form of behavior 10's "the default
# is inert" (the pre-feature stdout is not reachable from inside the commit that adds the
# flag). The second file also pins the documented OUT-OF-SCOPE decision that
# `workspace_root` is ignored: a foreign root still loads and still suppresses nothing.
def test_b07_an_empty_baseline_is_valid_and_suppresses_nothing(
    ws: Path, tmp_path: Path
) -> None:
    empty = _baseline(ws, tmp_path / "empty.json", [])
    foreign = _raw_baseline(
        tmp_path / "foreign.json",
        json.dumps({"workspace_root": "/some/other/checkout", "signals": []}),
    )
    for surface in _SURFACES:
        bare = _stdout(ws, *surface)
        assert _stdout(ws, *surface, "--baseline", empty) == bare, surface
        assert _stdout(ws, *surface, "--baseline", foreign) == bare, surface


# Behavior 8: every malformed baseline is a USAGE error. The last three cases are NOT in
# the spec's enumerated list -- they are the regression the fix pass closed, where a
# present-but-UNHASHABLE identity value (a JSON array or object) escaped as a raw
# TypeError traceback with exit 1. The `Traceback` assertion is the real oracle there.
_MALFORMED_CASES: tuple[str, ...] = (
    "8a_path_does_not_exist",
    "8a_path_is_a_directory",
    "8b_not_valid_json",
    "8b_zero_byte_file",
    "8c_top_level_is_a_list",
    "8d_no_signals_key",
    "8d_signals_is_not_a_list",
    "8e_entry_is_not_an_object",
    "8e_entry_is_missing_a_key",
    "regression_array_identity_value",
    "regression_object_identity_value",
    "regression_array_on_the_second_entry",
)


@pytest.fixture(scope="module")
def malformed(ws: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """One baseline file per behavior-8 case, all OUTSIDE the scanned tree."""
    out = tmp_path_factory.mktemp("iter138_malformed")
    live = _records(ws)
    missing_key = {k: v for k, v in live[0].items() if k != "weight"}
    array_value = dict(live[0], path=["a", "b"])
    object_value = dict(live[0], summary={"nested": 1})
    second_entry = dict(live[1], detail=["an array where a scalar belongs"])
    cases = {
        "8a_path_does_not_exist": str(out / "no_such_file.json"),
        "8a_path_is_a_directory": str(out),
        "8b_not_valid_json": _raw_baseline(out / "not_json.json", "{nope"),
        "8b_zero_byte_file": _raw_baseline(out / "zero.json", ""),
        "8c_top_level_is_a_list": _raw_baseline(out / "list.json", "[1, 2]"),
        # Exactly what a `--summary --json` document saved by mistake looks like.
        "8d_no_signals_key": _raw_baseline(
            out / "summary_doc.json",
            json.dumps({"workspace_root": ".", "summary": {"todo": 1}, "total": 1}),
        ),
        "8d_signals_is_not_a_list": _raw_baseline(
            out / "signals_object.json", json.dumps({"signals": {}})
        ),
        "8e_entry_is_not_an_object": _raw_baseline(
            out / "entry_scalar.json", json.dumps({"signals": [1]})
        ),
        "8e_entry_is_missing_a_key": _raw_baseline(
            out / "missing_key.json", json.dumps({"signals": [missing_key]})
        ),
        "regression_array_identity_value": _raw_baseline(
            out / "array_value.json", json.dumps({"signals": [array_value]})
        ),
        "regression_object_identity_value": _raw_baseline(
            out / "object_value.json", json.dumps({"signals": [object_value]})
        ),
        "regression_array_on_the_second_entry": _raw_baseline(
            out / "array_second.json", json.dumps({"signals": [live[0], second_entry]})
        ),
    }
    assert set(cases) == set(_MALFORMED_CASES)
    return cases


@pytest.mark.parametrize("case", _MALFORMED_CASES)
def test_b08_a_malformed_baseline_is_a_usage_error(
    ws: Path, malformed: dict[str, str], case: str
) -> None:
    proc = _signals(ws, "--baseline", malformed[case])
    assert proc.returncode == 2, f"stderr={proc.stderr!r}"
    assert proc.stdout == ""
    assert "Traceback" not in proc.stderr
    lines = proc.stderr.splitlines()
    assert len(lines) == 1, lines
    assert lines[0].startswith("error: ")


# The reported index must name the offending entry, not always the first one.
def test_b08_the_reported_index_names_the_offending_entry(
    ws: Path, malformed: dict[str, str]
) -> None:
    proc = _signals(ws, "--baseline", malformed["regression_array_on_the_second_entry"])
    assert proc.returncode == 2
    assert "signals[1]" in proc.stderr


# Behavior 8, "before `_collect` runs": with --timings armed, a malformed baseline
# produces NO timings block, which is the observable proof nothing was scanned.
def test_b08_a_malformed_baseline_is_rejected_before_anything_is_scanned(
    ws: Path, malformed: dict[str, str]
) -> None:
    proc = _signals(ws, "--timings", "--baseline", malformed["8b_not_valid_json"])
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "collector timings" not in proc.stderr
    assert len(proc.stderr.splitlines()) == 1


# Behavior 9: extra keys are IGNORED, not an error, so a document written by a future
# version that adds a field still loads and still matches on the six contract keys.
def test_b09_extra_keys_on_a_baseline_entry_are_ignored(ws: Path, tmp_path: Path) -> None:
    live = _records(ws)
    entry = dict(live[0])
    entry["timestamp"] = "2026-01-01T00:00:00Z"
    entry["a_field_a_future_version_adds"] = 42
    bl = _baseline(ws, tmp_path / "extra_keys.json", [entry])
    assert _records(ws, "--baseline", bl) == [s for s in live if s != live[0]]


# Behavior 10: single-value, NOT repeatable like --exclude-path -- so the last occurrence
# wins rather than the two documents unioning.
def test_b10_the_flag_is_single_value_and_the_last_one_wins(
    ws: Path, tmp_path: Path
) -> None:
    live = _records(ws)
    full = _baseline(ws, tmp_path / "full.json", live)
    empty = _baseline(ws, tmp_path / "empty.json", [])
    assert _records(ws, "--baseline", empty, "--baseline", full) == []
    assert _records(ws, "--baseline", full, "--baseline", empty) == live


# Behavior 11: the shipped --help documents the flag. Each assertion is one claim the
# spec requires the help to make, read as a testable sentence.
def test_b11_the_help_documents_the_flag(ws: Path) -> None:
    proc = _run("signals", "--help", cwd=ws)
    assert proc.returncode == 0
    text = " ".join(proc.stdout.split())
    assert "--baseline FILE" in text
    assert "source, kind, summary, detail, path, weight" in text
    assert "STALENESS FAILS TOWARD REPORTING" in text
    assert "usage error (exit 2)" in text
    # Declared among the SELECTION knobs, BEFORE --timings: the iter-112 help-window
    # guard reads a fixed-width window anchored at the first --timings token.
    assert "[--baseline FILE] [--timings]" in text
    # Regression (fix pass, finding 2): the help must NOT claim an exit code for an
    # UNREADABLE baseline, because EACCES exits 1 -- see the next test.
    assert "unreadable" not in proc.stdout.lower()


def test_b11_an_unreadable_baseline_exits_1_so_the_help_and_the_behavior_agree(
    ws: Path, tmp_path: Path
) -> None:
    blocked = tmp_path / "blocked.json"
    blocked.write_text(json.dumps({"workspace_root": ".", "signals": []}), encoding="utf-8")
    blocked.chmod(0o000)
    try:
        try:
            blocked.read_text(encoding="utf-8")
        except OSError:
            pass
        else:
            pytest.skip("mode 000 is readable here (root or non-POSIX): EACCES unreachable")
        proc = _signals(ws, "--baseline", str(blocked))
    finally:
        blocked.chmod(0o600)
    # Exit 1, not 2: a permission error matches main()'s exit table and every other
    # file-reading flag on this verb. What matters is that it is still ONE `error:` line
    # and never a traceback.
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "Traceback" not in proc.stderr
    assert len(proc.stderr.splitlines()) == 1
    assert proc.stderr.startswith("error: ")


# The premise the whole feature rests on: the published per-signal contract is EXACTLY
# the six identity keys (no `timestamp`), so a saved `--json` document is a complete
# identity record and a baseline can never be silently partial.
def test_the_published_signal_contract_is_exactly_the_six_identity_keys(ws: Path) -> None:
    live = _records(ws)
    assert live, "fixture precondition: the workspace must emit signals"
    for record in live:
        assert tuple(sorted(record)) == tuple(sorted(_KEYS)), record
