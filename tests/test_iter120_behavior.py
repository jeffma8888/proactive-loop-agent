"""Black-box behavior tests for iteration 120 --- ``pla watch --out-dir DIR``.

Feature under test: an OPT-IN ``--out-dir DIR`` flag on the ``pla watch`` verb
that persists each tick's slate as ``DIR/slate-<NNN>.json`` (1-based tick index,
zero-padded to 3) and prints a per-tick ``slate written: <path>`` trailer, making
the namesake watch loop the *producer* of the slate stream ``pla diff`` is
documented to consume. With the flag ABSENT the verb stays byte-identical to
today: a live monitor that writes nothing and prints no trailer. Missing parent
directories are created on demand; an existing non-directory at ``DIR`` --- or
anywhere on its path --- is a usage error (exit 2) reported BEFORE the first
scan. Only a tick whose scan completed persists anything.

ISOLATION CONTRACT (honored): these tests are written strictly against this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``) and
``README.md`` --- and drive ONLY documented public surfaces: the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (its observable stdout / stderr / exit
codes / on-disk artifacts), the ``pla watch --help`` text, the published
``README.md``, and the public ``proactive_loop.models.GoalSlate`` model used
ONLY as the schema oracle for a persisted slate. **No file under ``src/`` was
read, no engineer or reviewer notes were read, and no ``git diff`` was
consulted.** Every test is fully offline: zero network, zero API keys, driven
through the scripted provider seam. Synthetic ``tmp_path`` workspaces are used
throughout (never the in-repo tree), so the git_activity / working_tree /
test_posture collectors cannot leak repo state (iter-15 lesson), and no
``watch`` is ever invoked without a small ``--max-scans`` (an unbounded run
would hang the suite).

AMBIGUITY NOTE (PM feedback, behavior 9c): the spec says "EVERY sentence in
README.md that asserts watch writes no slate file ... also names ``--out-dir``".
Taken literally that keys on the CLAIM PHRASE alone, which is what
``_unqualified_slate_claim_sentences`` does here (currently exact: the only two
occurrences of the phrase in the file are both about ``watch``). If a future
edit ever asserts "writes no slate file" about a DIFFERENT read-only verb --- for
which no ``--out-dir`` qualifier would be correct --- this guard would go red on
true prose; the fix then is to scope the detector to watch-context sentences,
not to weaken the qualifier requirement.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser, main
from proactive_loop.models import GoalSlate

_README = Path(__file__).resolve().parents[1] / "README.md"

# The two prose absolutes that the new opt-in flag must never leave unqualified.
_SLATE_CLAIM_PHRASES = ("writes no slate file", "prints no `slate written:`")

_TRAILER = "slate written:"
_SLATE_NAME_RE = re.compile(r"^slate-\d{3}\.json$")


# ---------------------------------------------------------------------------
# Helpers --- all black-box: build a synthetic workspace + scripted script,
# drive main(), read back stdout / stderr / exit code / on-disk artifacts.
# (Local copies of the iter-18 / iter-80 watch helpers: a local copy is lower
# risk than a cross-module test import.)
# ---------------------------------------------------------------------------


def _workspace(tmp_path: Path) -> Path:
    """A minimal, real, synthetic workspace directory (one source file)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    return ws


def _goal_dict(title: str) -> dict:
    """One goal dict matching the documented synthesize JSON contract."""
    return {
        "title": title,
        "rationale": "black-box watch --out-dir probe",
        "category": "learning",
        "impact": 5.0,
        "urgency": 5.0,
        "confidence": 1.0,
        "effort_weight": 1.0,
        "appropriate_now": True,
        "sources": ["foo.py"],
        "suggested_first_steps": ["do a thing"],
    }


def _script(tmp_path: Path, titles: list[str], *, name: str = "script.json") -> Path:
    """One ``synthesize`` response per title (one per scan tick)."""
    responses = [
        {"tag": "synthesize", "text": json.dumps([_goal_dict(t)])} for t in titles
    ]
    path = tmp_path / name
    path.write_text(json.dumps({"responses": responses}), encoding="utf-8")
    return path


def _empty_script(tmp_path: Path, *, name: str = "empty.json") -> Path:
    """An EMPTY scripted-responses file: every synthesize() raises at once
    (arrangement proven in tests/test_iter80_behavior.py)."""
    path = tmp_path / name
    path.write_text("[]", encoding="utf-8")
    return path


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and return (exit_code, stdout, stderr)."""
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _watch_argv(
    ws: Path,
    script: Path,
    *,
    state_dir: Path,
    interval: str = "0",
    max_scans: str | None = "1",
    out_dir: Path | str | None = None,
) -> list[str]:
    argv = [
        "watch",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--interval", interval,
        "--state-dir", str(state_dir),
    ]
    if max_scans is not None:
        argv += ["--max-scans", max_scans]
    if out_dir is not None:
        argv += ["--out-dir", str(out_dir)]
    return argv


def _error_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if ln.startswith("error:")]


def _trailer_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if _TRAILER in ln]


def _readme_text() -> str:
    return _README.read_text(encoding="utf-8")


def _sentences(text: str) -> list[str]:
    """Whitespace-NORMALIZED sentence split.

    The claim sentence at README:188 continues onto the next SOURCE LINE, so a
    per-line scan would truncate it before the ``--out-dir`` qualifier and the
    guard would pass vacuously (or fail on true prose). Normalize all runs of
    whitespace to one space FIRST, then split on sentence-final punctuation
    followed by whitespace.
    """
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if s.strip()]


def _slate_claim_sentences(text: str) -> list[str]:
    return [
        s for s in _sentences(text)
        if any(phrase in s for phrase in _SLATE_CLAIM_PHRASES)
    ]


def _unqualified_slate_claim_sentences(text: str) -> list[str]:
    """Sentences asserting the OLD absolute without naming the new opt-in."""
    return [s for s in _slate_claim_sentences(text) if "--out-dir" not in s]


def _cli_section() -> str:
    lines = _readme_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "## CLI")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _paragraph_containing(needle: str) -> str:
    for para in re.split(r"\n\s*\n", _readme_text()):
        if needle in para:
            return re.sub(r"\s+", " ", para)
    raise AssertionError(f"no README paragraph contains {needle!r}")


# ===========================================================================
# Behavior 1 --- Flag ABSENT -> byte-identical to today (no file, no trailer).
# ===========================================================================


def test_b01_flag_absent_persists_nothing_and_prints_no_trailer(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Absent flag tick one", "Absent flag tick two"])
    state_dir = tmp_path / "fresh_state"  # deliberately fresh (never created)

    rc, out, err = _run(
        _watch_argv(ws, script, state_dir=state_dir, max_scans="2"), capsys
    )

    assert rc == 0, f"no-flag watch must exit 0; stderr={err!r}"
    assert "=== scan 1 ===" in out and "=== scan 2 ===" in out, out
    assert out.count(_TRAILER) == 0, (
        f"a no-flag watch must print no {_TRAILER!r} trailer; got:\n{out}"
    )
    stray = sorted(p.name for p in state_dir.rglob("*.json")) if state_dir.exists() else []
    assert stray == [], f"no-flag watch must persist no JSON under the state dir; found {stray}"


# ===========================================================================
# Behavior 2 --- One slate file per successful tick, in a fresh dir.
# ===========================================================================


def test_b02_one_slate_per_tick_in_fresh_dir(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Tick one goal", "Tick two goal", "Tick three goal"])
    state_dir = tmp_path / "state"
    out_dir = tmp_path / "stream"  # does NOT exist beforehand
    assert not out_dir.exists()

    rc, out, err = _run(
        _watch_argv(ws, script, state_dir=state_dir, max_scans="3", out_dir=out_dir),
        capsys,
    )

    assert rc == 0, f"--out-dir watch must exit 0; stderr={err!r}"
    assert out_dir.is_dir(), "--out-dir must be created on demand"
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "slate-001.json",
        "slate-002.json",
        "slate-003.json",
    ], f"got {sorted(p.name for p in out_dir.iterdir())}"
    # The fixed single-file `scan --out` default name is never used.
    assert list(out_dir.rglob("slate.json")) == [], "must not write a fixed slate.json"
    if state_dir.exists():
        assert list(state_dir.rglob("slate.json")) == [], "no fixed slate.json under the state dir"


# ===========================================================================
# Behavior 3 --- The written files compose with `diff` as advertised.
# ===========================================================================


def test_b03_written_slates_compose_with_diff(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Stream goal one", "Stream goal two"])
    out_dir = tmp_path / "stream"

    rc, out, err = _run(
        _watch_argv(
            ws, script, state_dir=tmp_path / "state", max_scans="2", out_dir=out_dir
        ),
        capsys,
    )
    assert rc == 0, f"producer run must exit 0; stderr={err!r}"

    first, second = out_dir / "slate-001.json", out_dir / "slate-002.json"
    assert first.exists() and second.exists()

    # No `scan --out` invocation anywhere in this test: watch alone produced the
    # stream that `diff` consumes.
    rc, dout, derr = _run(
        ["diff", "--old", str(first), "--new", str(second)], capsys
    )
    assert rc == 0, f"diff over two watch-written slates must exit 0; stderr={derr!r}"
    assert "Traceback" not in derr and "Traceback" not in dout
    assert "unchanged:" in dout, f"diff must print its normal trailer; got:\n{dout}"
    assert "Stream goal two" in dout and "Stream goal one" in dout, dout

    rc, jout, jerr = _run(
        ["diff", "--old", str(first), "--new", str(second), "--json"], capsys
    )
    assert rc == 0, jerr
    obj = json.loads(jout)
    assert [g["title"] for g in obj["added"]] == ["Stream goal two"], obj["added"]
    assert [g["title"] for g in obj["removed"]] == ["Stream goal one"], obj["removed"]


# ===========================================================================
# Behavior 4 --- Deterministic, index-keyed names --- never timestamps.
# ===========================================================================


def test_b04_names_are_index_keyed_and_deterministic(tmp_path, capsys):
    ws = _workspace(tmp_path)
    titles = ["Deterministic one", "Deterministic two"]

    runs: list[list[str]] = []
    for run_id in ("a", "b"):
        script = _script(tmp_path, titles, name=f"script_{run_id}.json")
        out_dir = tmp_path / f"stream_{run_id}"
        rc, out, err = _run(
            _watch_argv(
                ws,
                script,
                state_dir=tmp_path / f"state_{run_id}",
                max_scans="2",
                out_dir=out_dir,
            ),
            capsys,
        )
        assert rc == 0, f"run {run_id} must exit 0; stderr={err!r}"
        names = sorted(p.name for p in out_dir.iterdir())
        runs.append(names)
        for name in names:
            assert _SLATE_NAME_RE.match(name), f"non-index-keyed filename {name!r}"
        assert names == ["slate-001.json", "slate-002.json"], names
        # Chronological == lexicographic: the tick-1 file holds tick 1's goal.
        assert titles[0] in (out_dir / "slate-001.json").read_text(encoding="utf-8")
        assert titles[1] in (out_dir / "slate-002.json").read_text(encoding="utf-8")

    # Two identical runs into two fresh dirs -> the SAME filenames (no clock).
    assert runs[0] == runs[1], f"filenames must not depend on the clock: {runs}"


# ===========================================================================
# Behavior 5 --- Absent parents are created on demand.
# ===========================================================================


def test_b05_absent_parents_created_on_demand(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Deep dir goal"])
    base = tmp_path / "base"
    base.mkdir()  # base exists, a/b/c does NOT
    out_dir = base / "a" / "b" / "c"

    rc, out, err = _run(
        _watch_argv(
            ws, script, state_dir=tmp_path / "state", max_scans="1", out_dir=out_dir
        ),
        capsys,
    )

    assert rc == 0, f"missing parents must be created, not fatal; stderr={err!r}"
    written = out_dir / "slate-001.json"
    assert written.exists(), f"{written} missing; out_dir contents: {list(base.rglob('*'))}"
    slate = GoalSlate.model_validate_json(written.read_text(encoding="utf-8"))
    assert slate.goals, "persisted slate must be schema-valid and non-empty"
    assert "Deep dir goal" in [g.title for g in slate.goals]


# ===========================================================================
# Behavior 6 --- Fail-fast structural guard, BEFORE any scan.
# ===========================================================================


def test_b06a_existing_file_as_out_dir_is_exit2_before_any_scan(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Never reached"])
    holder = tmp_path / "holder"
    holder.mkdir()
    target = holder / "not_a_dir.txt"
    target.write_text("original\n", encoding="utf-8")
    before = sorted(p.name for p in holder.iterdir())

    rc, out, err = _run(
        _watch_argv(
            ws, script, state_dir=tmp_path / "state", max_scans="1", out_dir=target
        ),
        capsys,
    )

    assert rc == 2, f"an existing regular file at --out-dir must exit 2, got {rc}"
    errs = _error_lines(err)
    assert len(errs) == 1, f"expected exactly one error: line, got {errs}"
    assert "--out-dir" in errs[0], f"error line must name --out-dir; got {errs[0]!r}"
    assert out.count("=== scan 1 ===") == 0, f"guard must run before any scan; got:\n{out}"
    assert target.read_text(encoding="utf-8") == "original\n", "target file was modified"
    assert sorted(p.name for p in holder.iterdir()) == before, "a new file appeared beside the target"


def test_b06b_non_directory_ancestor_is_exit2_before_any_scan(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Never reached"])
    holder = tmp_path / "holder"
    holder.mkdir()
    blocker = holder / "blocker.txt"
    blocker.write_text("original\n", encoding="utf-8")
    before = sorted(p.name for p in holder.iterdir())

    rc, out, err = _run(
        _watch_argv(
            ws,
            script,
            state_dir=tmp_path / "state",
            max_scans="1",
            out_dir=blocker / "child",
        ),
        capsys,
    )

    assert rc == 2, f"a non-directory ANCESTOR of --out-dir must exit 2, got {rc}"
    errs = _error_lines(err)
    assert len(errs) == 1, f"expected exactly one error: line, got {errs}"
    assert "--out-dir" in errs[0], f"error line must name --out-dir; got {errs[0]!r}"
    assert out.count("=== scan 1 ===") == 0, f"guard must run before any scan; got:\n{out}"
    assert blocker.read_text(encoding="utf-8") == "original\n", "blocker file was modified"
    assert sorted(p.name for p in holder.iterdir()) == before, "a new entry appeared beside the blocker"


# ===========================================================================
# Behavior 7 --- Per-tick trailer, only when persisting, after that tick's table.
# ===========================================================================


def test_b07_per_tick_trailer_names_its_own_file_after_its_table(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["Trailer one", "Trailer two"])
    out_dir = tmp_path / "stream"

    rc, out, err = _run(
        _watch_argv(
            ws, script, state_dir=tmp_path / "state", max_scans="2", out_dir=out_dir
        ),
        capsys,
    )

    assert rc == 0, f"stderr={err!r}"
    assert out.count(_TRAILER) == 2, f"expected exactly 2 trailers; got:\n{out}"
    lines = _trailer_lines(out)
    assert lines[0].rstrip().endswith("slate-001.json"), lines[0]
    assert lines[1].rstrip().endswith("slate-002.json"), lines[1]
    # Each trailer follows its OWN tick's table, and precedes the next header.
    i_h1 = out.index("=== scan 1 ===")
    i_t1 = out.index("slate-001.json")
    i_h2 = out.index("=== scan 2 ===")
    i_t2 = out.index("slate-002.json")
    i_table1 = out.index("DECISION")
    assert i_h1 < i_table1 < i_t1 < i_h2 < i_t2, (
        f"trailer ordering wrong (h1={i_h1} table1={i_table1} t1={i_t1} "
        f"h2={i_h2} t2={i_t2}); got:\n{out}"
    )


# ===========================================================================
# Behavior 8 --- A failed tick persists nothing and the watch still rides on.
# ===========================================================================


def test_b08_failed_ticks_persist_nothing_and_watch_survives(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _empty_script(tmp_path)
    out_dir = tmp_path / "stream"

    rc, out, err = _run(
        _watch_argv(
            ws, script, state_dir=tmp_path / "state", max_scans="2", out_dir=out_dir
        ),
        capsys,
    )

    assert rc == 0, f"every-tick-fails watch must still exit 0, got {rc}; stderr={err!r}"
    assert "=== scan 1 ===" in out and "=== scan 2 ===" in out, out
    assert "scan 1 failed" in err and "scan 2 failed" in err, err
    assert "Traceback" not in err and "Traceback" not in out
    written = list(out_dir.glob("slate-*.json")) if out_dir.exists() else []
    assert written == [], f"a failed tick must persist nothing; found {written}"
    assert out.count(_TRAILER) == 0, f"no trailer without a written slate; got:\n{out}"


# ===========================================================================
# Behavior 9 --- Docs tell the truth about the new flag.
# ===========================================================================


def test_b09a_watch_help_names_the_flag(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["watch", "--help"])
    assert ei.value.code == 0, f"`pla watch --help` must exit 0, got {ei.value.code}"
    out = capsys.readouterr().out
    assert "--out-dir" in out, f"watch --help must document --out-dir; got:\n{out}"


def test_b09b_cli_section_watch_row_documents_the_flag():
    section = _cli_section()
    rows = [ln for ln in section.splitlines() if ln.startswith("| `watch`")]
    assert len(rows) == 1, f"expected exactly one CLI-table watch row, got {rows}"
    assert "--out-dir" in rows[0], f"the watch CLI row must document --out-dir; got:\n{rows[0]}"


def test_b09c_no_sentence_claims_the_old_absolute_unqualified():
    text = _readme_text()
    claims = _slate_claim_sentences(text)
    # Non-vacuous: the prose really does make the claim (both known sites).
    assert len(claims) >= 2, f"expected >=2 slate-claim sentences, got {len(claims)}: {claims}"
    unqualified = _unqualified_slate_claim_sentences(text)
    assert unqualified == [], (
        "every sentence asserting watch writes no slate file must name --out-dir; "
        f"offenders: {unqualified}"
    )


def test_b09c_guard_is_two_sided_and_fails_on_a_planted_absolute():
    """The detector above is only evidence if it can go RED. Plant one
    unqualified sentence per claim phrase and prove each is caught."""
    text = _readme_text()
    planted_a = text + "\n\nThe watch verb writes no slate file, ever.\n"
    planted_b = text + "\n\nUnlike scan it prints no `slate written:` trailer at all.\n"
    for planted, label in ((planted_a, "phrase A"), (planted_b, "phrase B")):
        offenders = _unqualified_slate_claim_sentences(planted)
        assert offenders, f"detector missed a planted unqualified sentence ({label})"
    # ...and a QUALIFIED planted sentence is correctly ignored (no false positive).
    ok = text + "\n\nThe watch verb writes no slate file unless `--out-dir DIR` opts in.\n"
    assert _unqualified_slate_claim_sentences(ok) == []


def test_b09d_diff_paragraph_names_watch_out_dir_as_producer():
    para = _paragraph_containing("comparative companion to `watch`")
    assert "stream of point-in-time slates" in para, para
    assert "watch --out-dir" in para, (
        "the diff narrative must name `watch --out-dir` as the producer of the "
        f"advertised slate stream; got:\n{para}"
    )


def test_b09e_out_dir_is_exposed_on_watch_only():
    """Scope check: the new long option lands on `watch` and on no other verb
    (parser-derived, the same public `build_parser()` seam the iter-107
    documentation guards use)."""
    parser = build_parser()
    subparsers = [
        action.choices
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert len(subparsers) == 1, "expected exactly one subcommand action"
    carriers = sorted(
        name
        for name, sub in subparsers[0].items()
        if any(
            "--out-dir" in action.option_strings for action in sub._actions
        )
    )
    assert carriers == ["watch"], f"--out-dir must exist on watch only; got {carriers}"
