"""Iteration 161 (factory iter 167) -- black-box verification of `scan --snapshot FILE`.

WHAT THIS ITERATION CLAIMS (restated from the PM spec so this file stands alone)
``_cmd_scan`` collected a workspace snapshot, handed it to the synthesizer, and then
dropped it, so a written slate was a claim with no evidence on disk. ``pla scan
--snapshot FILE`` now persists the snapshot the scan actually perceived as ONE JSON
document of the same ``{workspace_root, signals[]}`` shape ``signals --json`` prints,
carrying exactly the six identity keys and no timestamp -- so it is diffable across
runs AND directly loadable as a ``signals --baseline`` document. Nothing on stdout,
in the slate, or in the three pre-existing path-guard messages may change.

HOW THIS FILE VERIFIES IT, INDEPENDENTLY
Every assertion drives the public CLI entry point (``proactive_loop.cli.main``) with
an argv list and reads back the exit code, captured stdout/stderr, and on-disk files.
Nothing here imports the writer, the payload builder, or the guard: the document is
only ever parsed from the file the CLI wrote, and the "equals ``signals --json``"
claim is checked by running that OTHER verb and comparing PARSED documents, so the
two surfaces cannot agree merely by sharing a bug this file also encodes.

Four traps this file respects on purpose.
1. AMBIENT TREE. Every fixture workspace is built inside ``tmp_path`` and every
   output path is inside ``tmp_path``; no assertion reads the checkout or any
   gitignored path, because a fresh clone re-verifies every ship.
2. SLATE NON-DETERMINISM THAT PREDATES THIS FEATURE. Two identical scans always
   differ in the slate's ``created_at`` and in every goal ``id`` derived from it, so
   behavior 7 compares slates MODULO those fields. A naive byte comparison would fail
   a correct implementation; test_b07c pins that the difference is confined to them.
3. TRAILER PATHS. "stdout is byte-identical" is only meaningful when both runs are
   pointed at the SAME ``--out`` and ``--state-dir``; any other harness bakes a path
   difference into the trailer and reports the fixture as the regression.
4. INTERPRETER SKEW. CI runs 3.12 and 3.13 and 3.13 strips the common leading
   docstring indent at compile time, so nothing here asserts on indentation: help
   text is matched by substring and README prose by ``in``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"
README = REPO / "README.md"

# The document's per-signal contract: exactly these six keys, in any order.
_IDENTITY_KEYS = {"source", "kind", "summary", "detail", "path", "weight"}
# Deliberately absent (spec behavior 3): the document must stay diffable.
_FORBIDDEN_KEYS = ("timestamp", "collected_at")
# The human-owned block of the README; the CLI reference lives BELOW it.
_INTRO_MARKER = "PORTFOLIO INTRO"


# ---------------------------------------------------------------------------
# Helpers -- black-box only: build argv, drive main(), read exit code, stdout,
# stderr and on-disk artifacts. Guards return 2 rather than raising, but
# SystemExit is tolerated so these tests stay correct either way.
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        rc = main(argv)
    except SystemExit as exc:  # defensive: guards return 2, but tolerate exit()
        rc = exc.code if isinstance(exc.code, int) else 1
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _build_workspace(root: Path) -> Path:
    """A small tree that provably emits signals from several collectors."""
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "keep.py").write_text("k = 5\n", encoding="utf-8")
    filler = "\n".join(f"line {i}" for i in range(1, 12))
    (root / "notes.md").write_text(
        filler + "\n- TODO: alpha here\n- TODO: beta here\n", encoding="utf-8"
    )
    return root


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    return _build_workspace(tmp_path / "ws")


def _scan_argv(
    ws_dir: Path,
    *,
    out: Path | None = None,
    state_dir: Path | None = None,
    snapshot: Path | None = None,
    fmt: str | None = None,
    collector: str | None = None,
    responses: Path = SCRIPT,
) -> list[str]:
    argv = [
        "scan",
        "--workspace", str(ws_dir),
        "--provider", "scripted",
        "--scripted-responses", str(responses),
    ]
    if out is not None:
        argv += ["--out", str(out)]
    if state_dir is not None:
        argv += ["--state-dir", str(state_dir)]
    if fmt is not None:
        argv += ["--format", fmt]
    if collector is not None:
        argv += ["--collector", collector]
    if snapshot is not None:
        argv += ["--snapshot", str(snapshot)]
    return argv


def _scan_ok(
    ws_dir: Path, capsys: pytest.CaptureFixture[str], **kwargs: object
) -> tuple[str, str]:
    argv = _scan_argv(ws_dir, **kwargs)  # type: ignore[arg-type]
    rc, out, err = _run(argv, capsys)
    assert rc == 0, f"scan must exit 0 for {argv!r}; rc={rc}, stderr={err!r}"
    return out, err


def _signals_json(
    ws_dir: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[dict, str]:
    argv = ["signals", "--workspace", str(ws_dir), "--json", *extra]
    rc, out, err = _run(argv, capsys)
    assert rc == 0, f"`{' '.join(argv)}` must exit 0; rc={rc}, stderr={err!r}"
    return json.loads(out), err


def _read_doc(path: Path) -> dict:
    assert path.is_file(), f"expected a snapshot document at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot_doc(
    ws_dir: Path, capsys: pytest.CaptureFixture[str], dest: Path, **kwargs: object
) -> dict:
    _scan_ok(ws_dir, capsys, snapshot=dest, **kwargs)
    return _read_doc(dest)


def _scrub_slate(doc: dict) -> dict:
    """Drop the two fields that differ between ANY two scans (wall-clock
    ``created_at`` and the goal ids derived from it), so what remains is the
    content this feature must not touch."""
    scrubbed = json.loads(json.dumps(doc))
    scrubbed.pop("created_at", None)
    for goal in scrubbed.get("goals", []):
        goal.pop("id", None)
    return scrubbed


def _assert_clean_rejection(rc: int, out: str, err: str, expected_msg: str) -> None:
    """The rejection invariant every path guard already honors: exit 2, 0-byte
    stdout, stderr is EXACTLY one ``error: <msg>`` line, no errno, no traceback."""
    assert rc == 2, f"rejection must exit 2; got {rc}; stderr={err!r}"
    assert out == "", f"stdout must be empty on rejection; got:\n{out!r}"
    assert err.splitlines() == [expected_msg], (
        f"stderr must be exactly one line equal to {expected_msg!r}; got:\n{err!r}"
    )
    combined = out + err
    assert "[Errno" not in combined, f"no leaked OS errno allowed; got:\n{combined!r}"
    assert "Traceback" not in combined, f"no traceback allowed; got:\n{combined!r}"


# ===========================================================================
# Behavior 1 --- `scan --snapshot FILE` exits 0 and creates FILE, whose text is
# ONE JSON object with EXACTLY the two keys `workspace_root` and `signals`.
# ===========================================================================


def test_b01_snapshot_flag_writes_one_two_key_json_document(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = tmp_path / "snap.json"
    doc = _snapshot_doc(ws, capsys, snap, out=tmp_path / "slate.json")
    assert isinstance(doc, dict), f"the snapshot must be one JSON object; got {type(doc)!r}"
    assert set(doc) == {"workspace_root", "signals"}, (
        f"exactly two top-level keys are allowed; got {sorted(doc)}"
    )


# ===========================================================================
# Behavior 2 --- `workspace_root` is the scanned root, `signals` is an array.
# ===========================================================================


def test_b02_root_is_the_scanned_workspace_and_signals_is_an_array(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = tmp_path / "snap.json"
    doc = _snapshot_doc(ws, capsys, snap, out=tmp_path / "slate.json")
    assert isinstance(doc["workspace_root"], str), (
        f"workspace_root must be a string; got {type(doc['workspace_root'])!r}"
    )
    assert Path(doc["workspace_root"]).resolve() == ws.resolve(), (
        f"workspace_root must name the scanned workspace; got {doc['workspace_root']!r}"
    )
    assert isinstance(doc["signals"], list), (
        f"signals must be a JSON array; got {type(doc['signals'])!r}"
    )
    assert doc["signals"], "fixture precondition: the workspace must emit signals"


# ===========================================================================
# Behavior 3 --- every entry carries EXACTLY the six identity keys: no
# timestamp, no collected_at, nothing else.
# ===========================================================================


def test_b03_every_entry_has_exactly_the_six_identity_keys(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = tmp_path / "snap.json"
    doc = _snapshot_doc(ws, capsys, snap, out=tmp_path / "slate.json")
    for index, entry in enumerate(doc["signals"]):
        assert isinstance(entry, dict), f"signals[{index}] must be an object; got {entry!r}"
        assert set(entry) == _IDENTITY_KEYS, (
            f"signals[{index}] keys must be exactly {sorted(_IDENTITY_KEYS)}; "
            f"got {sorted(entry)}"
        )
    raw = snap.read_text(encoding="utf-8")
    for forbidden in _FORBIDDEN_KEYS:
        assert forbidden not in raw, (
            f"a {forbidden!r} field would make the document undiffable across runs; "
            f"found it in:\n{raw[:400]}"
        )


# ===========================================================================
# Behavior 4 --- the document's PARSED content equals the PARSED stdout of
# `signals --workspace <same> --json` (compare parsed JSON, not bytes).
# ===========================================================================


def test_b04_document_equals_the_signals_json_surface(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = tmp_path / "snap.json"
    doc = _snapshot_doc(ws, capsys, snap, out=tmp_path / "slate.json")
    printed, _err = _signals_json(ws, capsys)
    assert doc == printed, (
        "the snapshot document must equal the `signals --json` surface over the same "
        f"tree.\nsnapshot: {json.dumps(doc, sort_keys=True)[:600]}\n"
        f"signals : {json.dumps(printed, sort_keys=True)[:600]}"
    )


# ===========================================================================
# Behavior 5 --- the written document is accepted by the shipped ratchet:
# `signals --json --baseline FILE` exits 0, raises no schema error, and every
# live signal is suppressed by its own baseline entry.
# ===========================================================================


def test_b05_document_loads_as_a_signals_baseline_and_suppresses_everything(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = tmp_path / "base.json"
    doc = _snapshot_doc(ws, capsys, snap, out=tmp_path / "slate.json")
    assert doc["signals"], "fixture precondition: the baseline must not be empty"

    ratcheted, err = _signals_json(ws, capsys, "--baseline", str(snap))
    assert "error:" not in err, f"the baseline must load without a schema error; err={err!r}"
    assert ratcheted["signals"] == [], (
        "a baseline built from this very scan must suppress every live signal; "
        f"survivors={json.dumps(ratcheted['signals'])[:600]}"
    )


# ===========================================================================
# Behavior 6 --- `--collector NAME --snapshot FILE` records ONLY what that scan
# perceived: no entry has a `source` outside the requested collector set.
# ===========================================================================


def test_b06_collector_filter_is_reflected_in_the_document(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = tmp_path / "snap.json"
    doc = _snapshot_doc(
        ws, capsys, snap, out=tmp_path / "slate.json", collector="todos"
    )
    sources = {entry["source"] for entry in doc["signals"]}
    assert sources == {"todos"}, (
        f"--collector todos must confine the document to that collector; got {sorted(sources)}"
    )

    unfiltered = _read_doc(
        _snapshot_target(ws, capsys, tmp_path / "all.json", tmp_path / "slate2.json")
    )
    assert len({entry["source"] for entry in unfiltered["signals"]}) > 1, (
        "control: an unfiltered scan must see more than one collector, otherwise "
        "the filtered assertion above proves nothing"
    )


def _snapshot_target(
    ws_dir: Path, capsys: pytest.CaptureFixture[str], snap: Path, out: Path
) -> Path:
    _scan_ok(ws_dir, capsys, snapshot=snap, out=out)
    return snap


# ===========================================================================
# Behavior 7 --- STDOUT AND THE SLATE ARE UNCHANGED, and with no --snapshot no
# snapshot document is written anywhere.
# ===========================================================================


def test_b07a_stdout_is_byte_identical_with_and_without_the_flag(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # SAME --out and --state-dir for both runs, so the trailer cannot differ.
    out_path = tmp_path / "slate.json"
    state = tmp_path / "state"
    bare_out, bare_err = _scan_ok(ws, capsys, out=out_path, state_dir=state)
    flagged_out, flagged_err = _scan_ok(
        ws, capsys, out=out_path, state_dir=state, snapshot=tmp_path / "snap.json"
    )
    assert flagged_out == bare_out, (
        "stdout must be byte-identical with and without --snapshot.\n"
        f"bare   : {bare_out!r}\nflagged: {flagged_out!r}"
    )
    assert flagged_err == bare_err, (
        f"stderr must be byte-identical too.\nbare: {bare_err!r}\nflagged: {flagged_err!r}"
    )
    assert "snapshot" not in flagged_out, (
        f"--snapshot must add no success-path trailer to stdout; got:\n{flagged_out!r}"
    )


def test_b07b_slate_content_is_unchanged_modulo_wall_clock_fields(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_path = tmp_path / "slate.json"
    state = tmp_path / "state"
    _scan_ok(ws, capsys, out=out_path, state_dir=state)
    bare = json.loads(out_path.read_text(encoding="utf-8"))
    _scan_ok(ws, capsys, out=out_path, state_dir=state, snapshot=tmp_path / "snap.json")
    flagged = json.loads(out_path.read_text(encoding="utf-8"))
    assert _scrub_slate(flagged) == _scrub_slate(bare), (
        "the slate must be unchanged modulo created_at and the ids derived from it"
    )


def test_b07c_slate_difference_is_confined_to_created_at_and_goal_ids(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Control for test_b07b's scrubbing: two BARE scans differ in exactly the
    same two places, so the scrub is pre-existing non-determinism and not a hole
    this feature slipped through."""
    out_path = tmp_path / "slate.json"
    state = tmp_path / "state"
    _scan_ok(ws, capsys, out=out_path, state_dir=state)
    first = json.loads(out_path.read_text(encoding="utf-8"))
    _scan_ok(ws, capsys, out=out_path, state_dir=state)
    second = json.loads(out_path.read_text(encoding="utf-8"))
    assert _scrub_slate(first) == _scrub_slate(second), (
        "control: two bare scans must agree once created_at and goal ids are removed"
    )


def test_b07d_no_snapshot_flag_writes_no_snapshot_document(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    _scan_ok(ws, capsys, out=out_dir / "slate.json", state_dir=tmp_path / "state")
    written = sorted(p.name for p in out_dir.iterdir())
    assert written == ["slate.json"], (
        f"without --snapshot only the slate may appear; found {written}"
    )


# ===========================================================================
# Behavior 8 --- `--snapshot` is honored independently of `--format`.
# ===========================================================================


@pytest.mark.parametrize("fmt", ["table", "json"])
def test_b08_snapshot_is_written_for_every_format(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    snap = tmp_path / f"snap-{fmt}.json"
    doc = _snapshot_doc(ws, capsys, snap, out=tmp_path / "slate.json", fmt=fmt)
    assert set(doc) == {"workspace_root", "signals"}, (
        f"--format {fmt} must not change the snapshot document; got {sorted(doc)}"
    )
    assert doc["signals"], f"--format {fmt} must still record the perceived signals"


# ===========================================================================
# Behavior 9 --- path guarding is FAIL-FAST and names --snapshot; the three
# pre-existing guard messages stay byte-identical.
# ===========================================================================


def test_b09a_snapshot_pointing_at_a_directory_is_rejected(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "adir"
    target.mkdir()
    out_path = tmp_path / "slate.json"
    rc, out, err = _run(
        _scan_argv(ws, out=out_path, state_dir=tmp_path / "state", snapshot=target), capsys
    )
    _assert_clean_rejection(rc, out, err, f"error: --snapshot is a directory: {target}")
    assert not out_path.exists(), "a rejected scan must not write a slate"
    assert sorted(p.name for p in target.iterdir()) == [], (
        "a rejected scan must not write anything into the target directory"
    )


def test_b09b_snapshot_whose_ancestor_is_a_plain_file_is_rejected(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "afile"
    blocker.write_text("plain\n", encoding="utf-8")
    out_path = tmp_path / "slate.json"
    rc, out, err = _run(
        _scan_argv(
            ws, out=out_path, state_dir=tmp_path / "state", snapshot=blocker / "deep" / "s.json"
        ),
        capsys,
    )
    _assert_clean_rejection(
        rc, out, err, f"error: --snapshot parent is not a directory: {blocker}"
    )
    assert not out_path.exists(), "a rejected scan must not write a slate"
    assert blocker.read_text(encoding="utf-8") == "plain\n", "the blocking file must be untouched"


def test_b09c_guard_runs_before_any_client_construction(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FAIL-FAST evidence, black-box: a bad --snapshot wins over a --scripted-responses
    path that does not exist, so the guard must precede provider construction."""
    target = tmp_path / "adir"
    target.mkdir()
    rc, out, err = _run(
        _scan_argv(
            ws,
            out=tmp_path / "slate.json",
            snapshot=target,
            responses=tmp_path / "missing-responses.json",
        ),
        capsys,
    )
    _assert_clean_rejection(rc, out, err, f"error: --snapshot is a directory: {target}")


def test_b09d_the_three_pre_existing_guard_messages_are_unchanged(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a_dir = tmp_path / "adir"
    a_dir.mkdir()
    a_file = tmp_path / "afile"
    a_file.write_text("plain\n", encoding="utf-8")

    rc, out, err = _run(_scan_argv(ws, out=a_dir), capsys)
    _assert_clean_rejection(rc, out, err, f"error: --out is a directory: {a_dir}")

    rc, out, err = _run(_scan_argv(ws, out=a_file / "slate.json"), capsys)
    _assert_clean_rejection(rc, out, err, f"error: --out parent is not a directory: {a_file}")

    rc, out, err = _run(_scan_argv(ws, state_dir=a_file), capsys)
    _assert_clean_rejection(rc, out, err, f"error: --state-dir is not a directory: {a_file}")


# ===========================================================================
# Behavior 10 --- a fully-absent parent chain is LEGAL and leaves no .tmp
# sibling behind on success.
# ===========================================================================


def test_b10_absent_parent_chain_is_created_and_leaves_no_temp_sibling(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = tmp_path / "new" / "deep" / "snap.json"
    doc = _snapshot_doc(ws, capsys, snap, out=tmp_path / "slate.json")
    assert doc["signals"], "the document must be complete after creating its parents"
    siblings = sorted(p.name for p in snap.parent.iterdir())
    assert siblings == ["snap.json"], (
        f"a successful write must leave no temp sibling behind; found {siblings}"
    )


# ===========================================================================
# Behavior 11 --- `scan --help` documents `--snapshot FILE`, and the README CLI
# reference BELOW the human-owned intro marker documents the flag.
# ===========================================================================


def test_b11a_scan_help_documents_the_flag(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, err = _run(["scan", "--help"], capsys)
    assert rc == 0, f"--help must exit 0; rc={rc}, stderr={err!r}"
    assert "--snapshot" in out, f"scan --help must document --snapshot; got:\n{out}"
    assert "FILE" in out, f"scan --help must show the FILE metavar; got:\n{out}"


def test_b11b_readme_documents_the_flag_below_the_human_owned_marker() -> None:
    text = README.read_text(encoding="utf-8")
    marker_at = text.find(_INTRO_MARKER)
    assert marker_at != -1, f"the {_INTRO_MARKER!r} marker must exist in README.md"
    flag_at = text.find("--snapshot")
    assert flag_at != -1, "README.md must document the --snapshot flag"
    assert flag_at > marker_at, (
        "--snapshot must be documented BELOW the human-owned portfolio intro "
        f"(marker at {marker_at}, first mention at {flag_at})"
    )
