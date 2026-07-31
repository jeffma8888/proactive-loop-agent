"""Black-box behavior tests for iteration 27.

Feature under test: ``pla scan --top N`` -- a backward-compatible flag on the
``scan`` verb that caps the STDOUT-rendered slate to the top-N ranked goals
UNIFORMLY across all three ``--format`` renderings (table, markdown, json),
while the persisted slate JSON always stays COMPLETE. The load-bearing
invariant is **stdout is a view; the file is the complete record**: ``--top``
only shortens what is printed; ``_write_slate`` continues to persist every goal
so ``dispatch``/``explain``/``diff``/``runs`` still operate on the full slate.
``--top`` slices the EXISTING ``ranked()`` order (highest-ranked first) -- it
never re-orders. ``default=None`` = "show all", byte-identical to no flag. A
non-positive or non-integer ``--top`` is an argparse usage error (exit 2) that
fires BEFORE any client is built, any collector runs, or any slate is written.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.5 (the ``scan`` CLI bullet) -- and drive
only the documented public surface: the ``pla`` CLI via ``main([...])`` (its
observable stdout/stderr/exit-code/written-artifacts), plus the public domain
models (``GoalSlate``/``AutonomyDecision`` from ``proactive_loop.models``), the
public gate ``gate_slate`` from ``proactive_loop.scout``, and ``Settings`` from
``proactive_loop.config`` -- exactly the surface the iter-12 scan tests already
use. **No file under ``src/`` was read, no engineer/reviewer notes were read,
and no ``git diff`` was consulted.** No internal (``_``-prefixed) render helper
is imported; every rendering assertion is made against the CLI's real stdout.
All tests are fully offline via the bundled scripted provider (no network, no
API keys) and use fresh ``tmp_path`` state/out dirs. Goal ``id`` values are NOT
deterministic across runs, so no test hard-codes an id -- the top-N expectation
is always derived from ``GoalSlate.ranked()`` read back from the persisted slate
written by that same run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.models import AutonomyDecision, GoalSlate
from proactive_loop.scout import gate_slate

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

MD_HEADER = "| # | decision | score | category | title |"
MD_SEP = "| --- | --- | --- | --- | --- |"

# A data row in the plain-text table starts with a leading rank integer (the
# header starts with `#`, the note with `...`, the trailer with `slate`).
_TABLE_ROW = re.compile(r"^\s*(\d+)\s+\S")
_MD_ROW = re.compile(r"^\| \d+ \|")


# ---------------------------------------------------------------------------
# Helpers -- all black-box: build argv, drive main(), read back artifacts.
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _scan_argv(
    tmp_path: Path,
    *,
    fmt: str | None = None,
    top: int | str | None = None,
    script: Path = SCRIPT,
    workspace: Path = FIXTURE,
    out: Path | None = None,
    tag: str = "s",
) -> tuple[list[str], Path]:
    out = out or (tmp_path / f"slate_{tag}.json")
    argv = [
        "scan",
        "--workspace", str(workspace),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--state-dir", str(tmp_path / f"state_{tag}"),
        "--out", str(out),
    ]
    if fmt is not None:
        argv += ["--format", fmt]
    if top is not None:
        argv += ["--top", str(top)]
    return argv, out


def _write_empty_script(tmp_path: Path) -> Path:
    """A scripted-responses file whose synthesize reply parses to zero goals."""
    p = tmp_path / "empty_script.json"
    p.write_text(json.dumps({"responses": [{"tag": "synthesize", "text": "[]"}]}))
    return p


def _load(out: Path) -> GoalSlate:
    return GoalSlate.model_validate_json(out.read_text())


def _table_data_rows(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if _TABLE_ROW.match(ln)]


def _md_data_rows(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if _MD_ROW.match(ln)]


def _M(out: Path) -> int:
    """M = full-slate goal count (== len(ranked()) == len(decisions))."""
    return len(_load(out).goals)


# ===========================================================================
# Behavior 1 -- Cap the default (table) render: N data rows, top-N ranked order
# ===========================================================================


def test_b01_top_caps_table_data_rows_to_top_n_in_ranked_order(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, top=2, tag="b01")
    rc, o, e = _run(argv, capsys)

    assert rc == 0
    slate = _load(out)
    M = len(slate.goals)
    assert M >= 3, "fixture must yield M>=3 for this iteration's behaviors"
    N = 2
    assert 1 <= N < M

    rows = _table_data_rows(o)
    assert len(rows) == N, f"--top {N} must print exactly {N} table data rows; got:\n{o}"

    ranked = slate.ranked()
    # Rank labels are 1..N and each row carries the corresponding top-N goal
    # (in ranked() order -- highest-ranked first), not a re-ordering.
    for i, row in enumerate(rows):
        rank_label = int(_TABLE_ROW.match(row).group(1))
        assert rank_label == i + 1, f"row {i} must be rank {i + 1}; got {rank_label}"
        assert ranked[i].title in row, (
            f"row {i} must carry ranked()[{i}] title {ranked[i].title!r}; row={row!r}"
        )
    assert e == ""


# ===========================================================================
# Behavior 2 -- Truncation note (table, capped): `... showing top N of M`
#               positioned AFTER data rows and BEFORE the trailer
# ===========================================================================


def test_b02_table_truncation_note_between_rows_and_trailer(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, top=2, tag="b02")
    rc, o, e = _run(argv, capsys)

    assert rc == 0
    M = _M(out)
    N = 2
    assert 1 <= N < M

    note = f"... showing top {N} of {M}"
    lines = o.splitlines()
    assert note in lines, f"missing literal note {note!r}; got:\n{o}"

    note_idx = lines.index(note)
    last_row_idx = max(i for i, ln in enumerate(lines) if _TABLE_ROW.match(ln))
    trailer_idx = next(i for i, ln in enumerate(lines) if ln.startswith("slate written:"))

    assert last_row_idx < note_idx < trailer_idx, (
        f"note must sit AFTER the data rows and BEFORE the trailer; "
        f"rows_end={last_row_idx} note={note_idx} trailer={trailer_idx}\n{o}"
    )
    assert e == ""


# ===========================================================================
# Behavior 3 -- `--top N` with N >= M is a no-op view (byte-identical to bare)
# ===========================================================================


def test_b03_top_ge_M_is_byte_identical_noop_view(tmp_path, capsys):
    out = tmp_path / "slate.json"  # SAME --out so the trailer path matches.
    argv_bare, _ = _scan_argv(tmp_path, out=out, tag="b03")
    rc0, o0, e0 = _run(argv_bare, capsys)
    assert rc0 == 0
    M = _M(out)

    for N in (M, M + 1):
        argv_top, _ = _scan_argv(tmp_path, top=N, out=out, tag="b03")
        rc, o, e = _run(argv_top, capsys)
        assert rc == 0
        assert o == o0, (
            f"--top {N} (>= M={M}) stdout must be byte-identical to bare scan\n"
            f"--- bare ---\n{o0}\n--- top {N} ---\n{o}"
        )
        assert "... showing top" not in o, f"a cap that hides nothing must print no note; got:\n{o}"
        assert len(_table_data_rows(o)) == M
        assert e == ""


# ===========================================================================
# Behavior 4 -- No `--top` is byte-stable: full M rows + trailer, NO note
# ===========================================================================


def test_b04_no_top_is_full_slate_with_trailer_and_no_note(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, tag="b04")
    rc, o, e = _run(argv, capsys)

    assert rc == 0
    M = _M(out)
    assert len(_table_data_rows(o)) == M, f"bare scan must print all {M} rows; got:\n{o}"
    assert "... showing top" not in o, "bare scan must print no truncation note"
    assert o.rstrip("\n").endswith(f"slate written: {out}")
    assert e == ""


# ===========================================================================
# Behavior 5 -- Non-positive / non-integer `--top` -> usage error, exit 2,
#               with NO slate file written
# ===========================================================================


@pytest.mark.parametrize("bad", ["0", "-1", "abc"])
def test_b05_bad_top_is_argparse_exit_2_and_writes_nothing(tmp_path, capsys, bad):
    out = tmp_path / f"slate_{bad}.json"
    state = tmp_path / f"state_{bad}"
    argv = [
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state),
        "--out", str(out),
        "--top", bad,
    ]
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    # argparse rejects the value at PARSE time -> SystemExit(2).
    assert excinfo.value.code == 2, f"--top {bad!r} must exit 2; got {excinfo.value.code}"

    err = capsys.readouterr().err
    assert "--top" in err, f"usage error must name --top; got:\n{err}"
    # No work happened before the parse error: no slate file, no run dirs.
    assert not out.exists(), f"--top {bad!r} must NOT write a slate file"
    assert list(state.glob("run-*")) == [] if state.exists() else True


# ===========================================================================
# Behavior 6 -- Persisted-file goal-count INVARIANT: the written slate always
#               holds all M goals for every --top value and every --format
# ===========================================================================


def test_b06_persisted_slate_always_has_M_goals(tmp_path, capsys):
    # Establish M once from a bare run.
    _, base_out = _scan_argv(tmp_path, tag="b06_base")
    rc, _, _ = _run(_scan_argv(tmp_path, tag="b06_base")[0], capsys)
    assert rc == 0
    M = _M(base_out)
    assert M >= 3

    tops: list[int | None] = [1, 2, M, M + 1, None]
    for fmt in (None, "table", "markdown", "json"):
        for top in tops:
            tag = f"b06_{fmt}_{top}"
            argv, out = _scan_argv(tmp_path, fmt=fmt, top=top, tag=tag)
            rc, o, e = _run(argv, capsys)
            assert rc == 0, f"scan fmt={fmt} top={top} must exit 0; stderr={e}"
            persisted = _load(out)
            assert len(persisted.goals) == M, (
                f"persisted slate must always hold all M={M} goals "
                f"(fmt={fmt}, top={top}); got {len(persisted.goals)}"
            )


# ===========================================================================
# Behavior 7 -- Cap the markdown render: N GFM data rows + note before trailer,
#               file still M goals
# ===========================================================================


def test_b07_top_caps_markdown_render(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, fmt="markdown", top=2, tag="b07")
    rc, o, e = _run(argv, capsys)

    assert rc == 0
    slate = _load(out)
    M = len(slate.goals)
    N = 2
    assert 1 <= N < M

    lines = o.splitlines()
    assert lines[0] == MD_HEADER
    assert lines[1] == MD_SEP

    rows = _md_data_rows(o)
    assert len(rows) == N, f"--format markdown --top {N} must print {N} GFM rows; got:\n{o}"

    ranked = slate.ranked()
    decisions = gate_slate(slate, Settings())
    # Each row is exactly the iter-12 GFM row shape for the corresponding
    # top-N goal in ranked() order.
    for rank, (g, d) in enumerate(zip(ranked[:N], decisions[:N]), start=1):
        expected = (
            f"| {rank} | {d.decision.value} | {g.score:.2f} | "
            f"{g.category.value} | {g.title} |"
        )
        assert rows[rank - 1] == expected, (
            f"md row {rank} mismatch:\n  got:  {rows[rank - 1]}\n  want: {expected}"
        )

    note = f"... showing top {N} of {M}"
    assert note in lines
    note_idx = lines.index(note)
    trailer_idx = next(i for i, ln in enumerate(lines) if ln.startswith("slate written:"))
    last_row_idx = max(i for i, ln in enumerate(lines) if _MD_ROW.match(ln))
    assert last_row_idx < note_idx < trailer_idx

    assert len(slate.goals) == M  # written slate unaffected
    assert e == ""


# ===========================================================================
# Behavior 8 -- Cap the JSON render, pipe stays pure: one {workspace_root,goals}
#               object with N goals in ranked order, NO note, NO trailer
# ===========================================================================


def test_b08_top_caps_json_render_pipe_stays_pure(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, fmt="json", top=2, tag="b08")
    rc, o, e = _run(argv, capsys)

    assert rc == 0
    slate = _load(out)
    M = len(slate.goals)
    N = 2
    assert 1 <= N < M

    # The ENTIRE stdout parses as ONE JSON object (would raise on a note/trailer).
    doc = json.loads(o)
    assert isinstance(doc, dict)
    assert set(doc.keys()) == {"workspace_root", "goals"}, "exactly two top-level keys"
    assert isinstance(doc["goals"], list)
    assert len(doc["goals"]) == N, f"goals array must be capped to {N}; got {len(doc['goals'])}"

    ranked = slate.ranked()
    assert [g["id"] for g in doc["goals"]] == [gg.id for gg in ranked[:N]], (
        "json goals must be the top-N in ranked() order"
    )
    assert [g["title"] for g in doc["goals"]] == [gg.title for gg in ranked[:N]]

    assert "... showing top" not in o, "json stdout must carry NO truncation note"
    assert "slate written:" not in o, "json stdout must carry NO trailer"

    assert len(slate.goals) == M  # written slate still complete
    assert e == ""


# ===========================================================================
# Behavior 9 -- Empty slate + `--top` is unaffected (marker, no note; json [])
# ===========================================================================


def test_b09_empty_slate_top_is_unaffected(tmp_path, capsys):
    script = _write_empty_script(tmp_path)

    # Table: --top 3 byte-identical to bare on the same empty workspace.
    out = tmp_path / "empty.json"
    argv_bare, _ = _scan_argv(tmp_path, script=script, out=out, tag="b09")
    rc0, o0, e0 = _run(argv_bare, capsys)
    assert rc0 == 0
    assert _M(out) == 0, "empty script must yield M==0"

    argv_top, _ = _scan_argv(tmp_path, script=script, top=3, out=out, tag="b09")
    rc1, o1, e1 = _run(argv_top, capsys)
    assert rc1 == 0
    assert o1 == o0, f"empty-slate --top 3 must be byte-identical to bare\n{o0!r}\n{o1!r}"
    assert "(no candidate goals)" in o1
    assert "... showing top" not in o1, "empty slate must print no truncation note"

    # JSON: --top 3 -> goals array is [].
    argv_json, jout = _scan_argv(tmp_path, script=script, fmt="json", top=3, tag="b09json")
    rc2, o2, e2 = _run(argv_json, capsys)
    assert rc2 == 0
    doc = json.loads(o2)
    assert set(doc.keys()) == {"workspace_root", "goals"}
    assert doc["goals"] == []
    assert "... showing top" not in o2
    assert _M(jout) == 0


# ===========================================================================
# Behavior 10 -- `--top 1` shows exactly the single top-ranked goal + note
# ===========================================================================


def test_b10_top_1_shows_only_rank_1_goal(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, top=1, tag="b10")
    rc, o, e = _run(argv, capsys)

    assert rc == 0
    slate = _load(out)
    M = len(slate.goals)
    assert M > 1

    rows = _table_data_rows(o)
    assert len(rows) == 1, f"--top 1 must print exactly ONE data row; got:\n{o}"

    rank1 = slate.ranked()[0]  # the highest-ranked goal
    assert int(_TABLE_ROW.match(rows[0]).group(1)) == 1
    assert rank1.title in rows[0], (
        f"the single row must be the rank-1 goal {rank1.title!r}; row={rows[0]!r}"
    )

    assert f"... showing top 1 of {M}" in o
    assert e == ""
