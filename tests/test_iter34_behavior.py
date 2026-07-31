"""Black-box behavior tests for iteration 34.

Feature under test: ``pla scan --format csv`` — a fourth, backward-compatible
``--format`` value on the ``scan`` verb that exports the ranked, gated slate as
an RFC-4180 CSV data stream (``pandas.read_csv`` / spreadsheet / ``csvkit``
consumable). ``csv`` is a PURE data stream like ``json``: header row
``rank,decision,score,category,title`` then one row per ranked goal, with NO
``slate written:`` trailer and NO ``... showing top N of M`` truncation note.
Unlike ``markdown`` (which collapses whitespace and escapes ``|``), ``csv`` uses
the stdlib ``csv`` module's RFC-4180 quoting, so a title carrying a comma, a
double-quote AND an embedded newline round-trips EXACTLY. ``--top`` caps the
emitted rows uniformly across all four formats while the persisted slate file
always stays the COMPLETE record. Existing formats (bare / table / json /
markdown) are unperturbed and there is no ``__version__`` bump (additive).

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract — this iteration's PM spec Expected Behaviors (``pm.md``),
``README.md``, and ``SPEC.md`` §4.5 (the ``scan`` CLI contract) — and drive ONLY
the documented public surface: the ``pla`` CLI via ``cli.main([...])`` (its
observable stdout / stderr / exit code / written artifacts), plus the public
domain models (``GoalSlate`` from ``proactive_loop.models``), the public gate
``gate_slate`` from ``proactive_loop.scout``, and ``Settings`` from
``proactive_loop.config`` — exactly the surface iter-12's format tests use.
**No file under ``src/`` was read, no engineer/reviewer note was read, and no
``git diff`` was consulted.** No internal (``_``-prefixed) render helper is
imported; every CSV assertion is made by parsing the CLI's real stdout with the
Python standard-library ``csv`` module (``csv.reader(io.StringIO(stdout))``).
All tests are fully offline via the bundled scripted provider (no network, no
API keys) and use fresh ``tmp_path`` state/out dirs. Random per-scan goal ``id``
values are never hard-coded — expected rows are always derived from the slate
persisted by that same run.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.models import GoalSlate
from proactive_loop.scout import gate_slate

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

HEADER = ["rank", "decision", "score", "category", "title"]

# A title carrying a comma, a double-quote AND an embedded newline — the exact
# hostile input the spec (behavior 4) says csv MUST round-trip and markdown
# provably cannot.
HOSTILE_TITLE = 'he said, "hi"\nbye'


# ---------------------------------------------------------------------------
# Helpers — all black-box: build argv, drive main(), read back artifacts.
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
    top: int | None = None,
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


def _parse_csv(stdout: str) -> list[list[str]]:
    """The parsed rows == the list csv.reader yields over the captured stdout."""
    return list(csv.reader(io.StringIO(stdout)))


def _load(out: Path) -> GoalSlate:
    return GoalSlate.model_validate_json(out.read_text())


def _expected_rows(slate: GoalSlate) -> list[list[str]]:
    """The rows the spec says csv must emit, derived from the SAME public
    surface (slate.ranked() + gate_slate) the other formats consume — one row
    per ranked goal, 1-based rank, decision.value, score :.2f, category.value,
    title verbatim."""
    ranked = slate.ranked()
    decisions = gate_slate(slate, Settings())
    rows: list[list[str]] = []
    for rank, (g, d) in enumerate(zip(ranked, decisions), start=1):
        rows.append([
            str(rank),
            d.decision.value,
            f"{g.score:.2f}",
            g.category.value,
            g.title,
        ])
    return rows


def _empty_script(tmp_path: Path) -> Path:
    """A scripted-responses file whose synthesize reply parses to zero goals."""
    p = tmp_path / "empty_script.json"
    p.write_text(json.dumps({"responses": [{"tag": "synthesize", "text": "[]"}]}))
    return p


def _single_goal_script(tmp_path: Path, title: str, *, category: str = "project") -> Path:
    """A single-goal script (mirrors iter-12's tricky-title fixture shape)."""
    goal = {
        "title": title,
        "category": category,
        "impact": 5.0,
        "urgency": 5.0,
        "confidence": 1.0,
        "effort_weight": 1.0,
        "appropriate_now": True,
    }
    p = tmp_path / "single_goal.json"
    p.write_text(json.dumps({"responses": [{"tag": "synthesize", "text": json.dumps([goal])}]}))
    return p


# ===========================================================================
# Behavior 1 — New format value accepted; exactly four choices
# ===========================================================================


def test_b01_csv_format_accepted_exit0(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, fmt="csv")
    rc, o, e = _run(argv, capsys)

    assert rc == 0, f"scan --format csv must exit 0; stderr={e!r}"
    assert e == ""
    assert out.is_file()
    # The four documented values are all accepted (exit 0); the rejection of any
    # other value is behavior 9.
    for fmt in ("table", "json", "markdown", "csv"):
        argv_f, _ = _scan_argv(tmp_path, fmt=fmt, tag=f"ok_{fmt}")
        rc_f, _o, e_f = _run(argv_f, capsys)
        assert rc_f == 0, f"--format {fmt} must be accepted; stderr={e_f!r}"


# ===========================================================================
# Behavior 2 — Header row is exactly the five-element list
# ===========================================================================


def test_b02_header_row(tmp_path, capsys):
    argv, _ = _scan_argv(tmp_path, fmt="csv")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    rows = _parse_csv(o)
    assert rows, "csv stdout must not be empty"
    assert rows[0] == HEADER, f"first parsed row must be {HEADER}; got {rows[0]!r}"


# ===========================================================================
# Behavior 3 — One row per ranked goal, correct fields (+ score matches markdown)
# ===========================================================================


def test_b03_one_row_per_goal_correct_fields(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, fmt="csv")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    slate = _load(out)
    expected = _expected_rows(slate)
    rows = _parse_csv(o)

    assert rows[0] == HEADER
    data = rows[1:]
    assert len(data) == len(expected) == len(slate.ranked())
    # Row-for-row: rank, decision.value, score(:.2f), category.value, title verbatim,
    # in slate.ranked() order (the same order table/markdown/json use).
    assert data == expected, f"csv rows mismatch:\n  got:  {data}\n  want: {expected}"


def test_b03b_csv_score_column_equals_markdown_score_cell(tmp_path, capsys):
    # Cross-format score-consistency check (AC): csv's score column == the
    # markdown score cell for the same inputs, per rank.
    argv_csv, out = _scan_argv(tmp_path, fmt="csv", tag="score_csv")
    rc_c, o_c, _e = _run(argv_csv, capsys)
    assert rc_c == 0
    slate = _load(out)
    ranked = slate.ranked()

    csv_scores = [r[2] for r in _parse_csv(o_c)[1:]]
    expected_scores = [f"{g.score:.2f}" for g in ranked]
    assert csv_scores == expected_scores, (csv_scores, expected_scores)

    # And the SAME two-decimal string appears as the markdown score cell.
    argv_md, _ = _scan_argv(tmp_path, fmt="markdown", tag="score_md")
    rc_m, o_m, _em = _run(argv_md, capsys)
    assert rc_m == 0
    md_data_rows = [ln for ln in o_m.splitlines() if ln.startswith("| ") and ln[2:3].isdigit()]
    assert len(md_data_rows) == len(ranked)
    for rank, (row, score) in enumerate(zip(md_data_rows, expected_scores), start=1):
        # markdown cell layout: | rank | decision | score | category | title |
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        assert cells[2] == score, f"rank {rank}: markdown score {cells[2]!r} != csv {score!r}"


# ===========================================================================
# Behavior 4 — RFC-4180 quoting round-trips a hostile title (markdown cannot)
# ===========================================================================


def test_b04_hostile_title_round_trips(tmp_path, capsys):
    script = _single_goal_script(tmp_path, HOSTILE_TITLE)
    argv, out = _scan_argv(tmp_path, fmt="csv", script=script, tag="hostile")
    rc, o, e = _run(argv, capsys)
    assert rc == 0, e

    slate = _load(out)
    ranked = slate.ranked()
    assert len(ranked) == 1
    goal_title = ranked[0].title
    # The goal's title (persisted) preserved every hostile character verbatim.
    assert "," in goal_title and '"' in goal_title and "\n" in goal_title, repr(goal_title)
    assert goal_title == HOSTILE_TITLE, repr(goal_title)

    rows = _parse_csv(o)
    assert rows[0] == HEADER
    data = rows[1:]
    assert len(data) == 1, f"one goal must yield exactly one data row; got {data}"
    recovered = data[0][4]
    # csv.reader recovers the title field EXACTLY — comma, quote, newline intact.
    assert recovered == goal_title == HOSTILE_TITLE, repr(recovered)
    assert "\n" in recovered, "the embedded newline must survive the csv round-trip"


def test_b04b_markdown_cannot_round_trip_the_same_title(tmp_path, capsys):
    # Contrast axis the PM makes falsifiable: markdown collapses the newline (so
    # the hostile title stays a SINGLE physical row, newline gone) — proving csv
    # is not a near-copy of markdown.
    script = _single_goal_script(tmp_path, HOSTILE_TITLE)
    argv, _ = _scan_argv(tmp_path, fmt="markdown", script=script, tag="hostile_md")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    data_rows = [ln for ln in o.splitlines() if ln.startswith("| ") and ln[2:3].isdigit()]
    assert len(data_rows) == 1, f"markdown must not spill the newline onto a 2nd row; got {data_rows}"
    row = data_rows[0]
    # The raw newline is collapsed to a space (markdown cannot preserve it).
    assert "\n" not in row
    assert "bye" in row and "he said" in row  # both halves land on the one line


# ===========================================================================
# Behavior 5 — No trailer, no note: the ENTIRE stdout is one valid CSV document
# ===========================================================================


def test_b05_pure_data_stream_no_trailer_no_note(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, fmt="csv", tag="pure")
    rc, o, e = _run(argv, capsys)
    assert rc == 0
    assert e == ""

    slate = _load(out)
    rows = _parse_csv(o)
    # csv.reader over the FULL stdout yields ONLY header + data rows — nothing else.
    assert rows[0] == HEADER
    assert len(rows) == 1 + len(slate.ranked())
    assert all(len(r) == 5 for r in rows), f"no ragged/blank rows allowed; rows={rows}"
    # No human trailer, no truncation note anywhere on stdout (json-style purity).
    assert "slate written:" not in o
    assert "showing top" not in o


# ===========================================================================
# Behavior 6 — Slate file still written and COMPLETE (stdout is only a view)
# ===========================================================================


def test_b06_slate_file_complete_while_stdout_is_capped(tmp_path, capsys):
    out = tmp_path / "explicit_out.json"
    argv, _ = _scan_argv(tmp_path, fmt="csv", top=1, out=out, tag="complete")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    rows = _parse_csv(o)
    # stdout: header + exactly 1 data row (behavior 7 with --top 1).
    assert rows[0] == HEADER
    assert len(rows) == 2, f"--top 1 must print header + 1 row; got {rows}"

    # The file at --out is the COMPLETE record: parses as JSON, ALL goals present.
    raw = json.loads(out.read_text())
    assert "created_at" in raw, "the persisted file must be the full slate schema"
    slate = _load(out)
    assert len(slate.goals) > 1, "stdout is a view; the file must hold every goal"
    assert len(slate.goals) == 4  # bundled fixture yields four goals


def test_b06b_default_out_path_used_when_no_out(tmp_path, capsys):
    # Absent --out, the slate is written to <state-dir>/slate.json.
    state = tmp_path / "state_default_out"
    argv = [
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state),
        "--format", "csv",
    ]
    rc, o, e = _run(argv, capsys)
    assert rc == 0, e
    default_out = state / "slate.json"
    assert default_out.is_file(), "csv must still write <state-dir>/slate.json by default"
    assert len(_load(default_out).goals) == 4


# ===========================================================================
# Behavior 7 — `--top` caps stdout uniformly (highest-ranked, ranked order)
# ===========================================================================


def test_b07_top_caps_stdout_in_ranked_order(tmp_path, capsys):
    # Full (no --top) first, to learn M and the ranked order.
    argv_all, out_all = _scan_argv(tmp_path, fmt="csv", tag="all")
    rc, o_all, _e = _run(argv_all, capsys)
    assert rc == 0
    all_data = _parse_csv(o_all)[1:]
    m = len(all_data)
    assert m == 4

    # 1 <= N < M -> header + exactly N data rows, the N highest-ranked, in order.
    for n in (1, 2, 3):
        argv_n, _ = _scan_argv(tmp_path, fmt="csv", top=n, tag=f"top{n}")
        rc_n, o_n, e_n = _run(argv_n, capsys)
        assert rc_n == 0, e_n
        rows_n = _parse_csv(o_n)
        assert rows_n[0] == HEADER
        data_n = rows_n[1:]
        assert len(data_n) == n, f"--top {n} must print {n} rows; got {len(data_n)}"
        # Same rows as the first N of the uncapped output (never re-ordered).
        assert data_n == all_data[:n], (data_n, all_data[:n])
        # Ranks are the natural 1..N sequence.
        assert [r[0] for r in data_n] == [str(i) for i in range(1, n + 1)]

    # N >= M -> header + all M rows (a cap hiding nothing).
    argv_big, _ = _scan_argv(tmp_path, fmt="csv", top=99, tag="topbig")
    rc_b, o_b, _eb = _run(argv_big, capsys)
    assert rc_b == 0
    assert _parse_csv(o_b)[1:] == all_data


# ===========================================================================
# Behavior 8 — Empty slate -> header only (no prose marker)
# ===========================================================================


def test_b08_empty_slate_header_only(tmp_path, capsys):
    script = _empty_script(tmp_path)
    argv, _ = _scan_argv(tmp_path, fmt="csv", script=script, tag="empty")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    rows = _parse_csv(o)
    assert rows == [HEADER], f"empty slate must be the header row ONLY; got {rows}"
    # csv (unlike table/markdown) emits NO prose marker.
    assert "(no candidate goals)" not in o
    assert "slate written:" not in o


# ===========================================================================
# Behavior 9 — Invalid --format still rejected at parse time (exit 2)
# ===========================================================================


def test_b09_invalid_format_rejected_at_parse_time(tmp_path, capsys):
    out = tmp_path / "should_not_exist.json"
    state = tmp_path / "state_xml"
    with pytest.raises(SystemExit) as excinfo:
        main([
            "scan",
            "--workspace", str(FIXTURE),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--state-dir", str(state),
            "--out", str(out),
            "--format", "xml",
        ])
    # argparse rejects the unknown choice at parse time -> SystemExit(2), the
    # same contract the pre-existing invalid-format test locks; adding "csv" to
    # choices did not weaken parse-time validation.
    assert excinfo.value.code == 2

    cap = capsys.readouterr()
    assert cap.out == "", f"nothing on stdout for a rejected format; got {cap.out!r}"
    assert "xml" in cap.err, f"usage error must name the invalid choice; got:\n{cap.err}"
    assert "--format" in cap.err
    # No work happened: no slate file written.
    assert not out.exists()


# ===========================================================================
# Behavior 10 — Existing formats unperturbed (bare == table; json/markdown shapes)
# ===========================================================================


def test_b10_existing_formats_unperturbed(tmp_path, capsys):
    # Bare scan is byte-for-byte identical to --format table (same --out so the
    # trailer path matches) — the core "no pre-existing render path is perturbed"
    # invariant. (The full iter-12 suite locks the exact table/json/markdown bytes.)
    out = tmp_path / "slate.json"
    argv_bare, _ = _scan_argv(tmp_path, out=out, tag="bare")
    rc0, o0, e0 = _run(argv_bare, capsys)
    argv_table = argv_bare + ["--format", "table"]
    rc1, o1, e1 = _run(argv_table, capsys)
    assert rc0 == 0 and rc1 == 0
    assert o1 == o0, "bare scan must stay byte-identical to --format table"
    assert e0 == "" and e1 == ""

    # json stays one pure JSON object (no trailer); markdown keeps its GFM header
    # + separator + the human trailer.
    argv_json, _ = _scan_argv(tmp_path, fmt="json", tag="json")
    rc_j, o_j, _ej = _run(argv_json, capsys)
    assert rc_j == 0
    doc = json.loads(o_j)
    assert set(doc.keys()) == {"workspace_root", "goals"}
    assert "slate written:" not in o_j

    argv_md, out_md = _scan_argv(tmp_path, fmt="markdown", tag="md")
    rc_m, o_m, _em = _run(argv_md, capsys)
    assert rc_m == 0
    md_lines = o_m.splitlines()
    assert md_lines[0] == "| # | decision | score | category | title |"
    assert md_lines[1] == "| --- | --- | --- | --- | --- |"
    assert f"slate written: {out_md}" in o_m  # markdown keeps the trailer, csv does not


# ===========================================================================
# Behavior 11 — Workspace guard holds under csv (front-door, format-independent)
# ===========================================================================


def test_b11_workspace_guard_precedes_csv_handling(tmp_path, capsys):
    missing = tmp_path / "no_such_ws"
    assert not missing.exists()
    out = tmp_path / "guard_slate.json"
    argv = [
        "scan",
        "--workspace", str(missing),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "guard_state"),
        "--out", str(out),
        "--format", "csv",
    ]
    rc, o, e = _run(argv, capsys)

    assert rc == 2, f"missing workspace with --format csv must exit 2; got {rc}"
    assert f"error: workspace not found: {missing}" in e
    assert o == "", f"the guard runs before any csv rendering; stdout must be empty, got {o!r}"
    assert not out.exists(), "no slate file may be written when the workspace guard fires"


# ===========================================================================
# Backward-compat guard — additive extension, no __version__ bump (AC).
# ===========================================================================


def test_version_unchanged_additive_extension():
    assert proactive_loop.__version__ == "0.1.1"
