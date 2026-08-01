"""Black-box behavior tests for iteration 56.

Feature under test: ``pla scan --format html`` — a fifth, backward-compatible
``--format`` value on the ``scan`` verb that renders the ranked, gated slate as
ONE self-contained, dependency-free HTML document on stdout
(``pla scan --workspace W --format html > slate.html`` opens directly in a
browser / pastes into a wiki or PR). Like ``json``/``csv`` it is a pure document
(NO ``slate written:`` trailer, NO ``... showing top N of M`` note), but like
``table``/``markdown`` an EMPTY slate degrades to a header table plus a single
``(no candidate goals)`` marker row (it is a rendered presentation format, not a
bare data stream). Every dynamic cell (title, decision ``.value``, category
``.value``) is routed through stdlib ``html.escape`` so a title's markup can
never inject. ``--top`` caps the RENDERED rows uniformly across all five formats
while the persisted slate file always stays the COMPLETE record. Existing
formats (bare / table / json / markdown / csv) are unperturbed, the workspace
guard and invalid-format usage error hold for every ``--format`` including
``html``, and there is no ``__version__`` bump (additive, non-breaking).

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract — this iteration's PM spec Expected Behaviors (``pm.md``),
``README.md``, and ``SPEC.md`` §4.5 (the ``scan`` CLI contract) — and drive ONLY
the documented public surface: the ``pla`` CLI via ``cli.main([...])`` (its
observable stdout / stderr / exit code / written slate file), plus the public
domain models (``GoalSlate`` from ``proactive_loop.models``), the public gate
``gate_slate`` from ``proactive_loop.scout``, and ``Settings`` from
``proactive_loop.config`` — exactly the surface iter-12/27/34/40's format tests
use. **No file under ``src/`` was read, no engineer/reviewer note was read, and
no ``git diff`` was consulted.** No internal (``_``-prefixed) render helper is
imported; every HTML assertion is made by parsing the CLI's real stdout with the
Python standard-library ``html.parser.HTMLParser`` (so counts/labels are robust
to inter-tag whitespace and attributes), and every escaping assertion is made on
the raw stdout string. All tests are fully offline via the bundled scripted
provider (no network, no API keys) and use fresh ``tmp_path`` state/out dirs.
Random per-scan goal ``id`` values are never hard-coded — expected rows are
always derived from the slate persisted by that same run.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
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

# The fixed 5-column header the spec (behavior 3) locks, in order.
HEADER = ["#", "decision", "score", "category", "title"]

# A title carrying HTML metacharacters — the exact one correctness hazard the
# spec (behavior 5) says html MUST escape so markup can never inject.
HOSTILE_TITLE = 'Fix <script>alert("x")</script> & <b>bold</b>'


# ---------------------------------------------------------------------------
# Helpers — all black-box: build argv, drive main(), read back artifacts,
# parse the emitted HTML with the stdlib parser (never a src helper).
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


def _load(out: Path) -> GoalSlate:
    return GoalSlate.model_validate_json(out.read_text())


def _expected_rows(slate: GoalSlate) -> list[list[str]]:
    """The rows the spec (behavior 4) says html must render, derived from the
    SAME public seam the other formats consume — slate.ranked() zipped with
    gate_slate — so no format can disagree on order/score/gate outcome: one row
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


class _TableParser(HTMLParser):
    """Collect every table row as its list of cell texts + a per-row kind
    ('th' for the header row, 'td' for data rows), plus a start-tag histogram.
    convert_charrefs=True decodes entities back to text (so a cell's recovered
    text equals the original title) AND CDATA mode means CSS inside <style> is
    never mis-parsed as tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.tag_count: dict[str, int] = {}
        self._row: dict | None = None
        self._buf: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        self.tag_count[tag] = self.tag_count.get(tag, 0) + 1
        if tag == "tr":
            self._row = {"cells": [], "kind": None}
        elif tag in ("th", "td"):
            self._buf = []
            if self._row is not None and self._row["kind"] is None:
                self._row["kind"] = tag

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._buf is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in ("th", "td") and self._buf is not None:
            text = "".join(self._buf).strip()
            if self._row is not None:
                self._row["cells"].append(text)
            self._buf = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _extract(html_str: str) -> tuple[list[list[str]], list[list[str]], dict[str, int]]:
    """Parse the document into (header_rows, data_rows, tag_counts). header_rows
    are the rows carrying <th>; data_rows the rows carrying <td>."""
    p = _TableParser()
    p.feed(html_str)
    p.close()
    header = [r["cells"] for r in p.rows if r["kind"] == "th"]
    data = [r["cells"] for r in p.rows if r["kind"] == "td"]
    return header, data, dict(p.tag_count)


def _empty_script(tmp_path: Path) -> Path:
    """A scripted-responses file whose synthesize reply parses to zero goals."""
    p = tmp_path / "empty_script.json"
    p.write_text(json.dumps({"responses": [{"tag": "synthesize", "text": "[]"}]}))
    return p


def _single_goal_script(tmp_path: Path, title: str, *, category: str = "project") -> Path:
    """A single-goal script (mirrors iter-12/34's tricky-title fixture shape)."""
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
# Behavior 1 — New choice accepted; html is a valid --format alongside the 4
# ===========================================================================


def test_b01_html_format_accepted_exit0(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, fmt="html")
    rc, o, e = _run(argv, capsys)

    assert rc == 0, f"scan --format html must exit 0; stderr={e!r}"
    assert e == ""
    assert out.is_file()
    # All FIVE documented values are accepted (exit 0); rejection of any other
    # value is behavior 11.
    for fmt in ("table", "json", "markdown", "csv", "html"):
        argv_f, _ = _scan_argv(tmp_path, fmt=fmt, tag=f"ok_{fmt}")
        rc_f, _o, e_f = _run(argv_f, capsys)
        assert rc_f == 0, f"--format {fmt} must be accepted; stderr={e_f!r}"


# ===========================================================================
# Behavior 2 — Self-contained, well-formed HTML document; no external resource
# ===========================================================================


def test_b02_self_contained_document(tmp_path, capsys):
    argv, _ = _scan_argv(tmp_path, fmt="html")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    assert o.startswith("<!DOCTYPE html>"), f"document must begin with the literal DOCTYPE; got {o[:40]!r}"
    for tag in ("<html", "<head", "<style", "<body", "<table"):
        assert tag in o, f"document must contain {tag!r}"
    # Ends with </html>, optionally followed by a single trailing newline —
    # nothing stray after it (behavior 7 pure-document overlap).
    tail = o[o.rindex("</html>") + len("</html>"):]
    assert tail in ("", "\n"), f"only an optional single newline may follow </html>; tail={tail!r}"
    # References NO external resource: no URLs, no <link>, no <script> (the
    # <script>-absent check also doubles as an escaping check — behavior 5).
    assert "http://" not in o and "https://" not in o
    assert "<link " not in o
    assert "<script" not in o


# ===========================================================================
# Behavior 3 — Exactly one header row of five labelled <th> cells, in order
# ===========================================================================


def test_b03_header_row_five_labels(tmp_path, capsys):
    argv, _ = _scan_argv(tmp_path, fmt="html")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    header, _data, counts = _extract(o)
    assert counts.get("th") == 5, f"exactly five <th> cells expected; got {counts.get('th')}"
    assert len(header) == 1, f"exactly one header row expected; got {len(header)}"
    assert header[0] == HEADER, f"header labels must be {HEADER} in order; got {header[0]}"


# ===========================================================================
# Behavior 4 — One data row per ranked goal, correct fields, in ranked order
# ===========================================================================


def test_b04_one_data_row_per_goal_in_ranked_order(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, fmt="html")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    slate = _load(out)
    expected = _expected_rows(slate)
    _header, data, _counts = _extract(o)

    assert len(data) == len(expected) == len(slate.ranked())
    assert all(len(r) == 5 for r in data), f"each data row must have five <td> cells; got {data}"
    # Row-for-row: rank, decision.value, score(:.2f), category.value, title,
    # in slate.ranked() order (the same order table/markdown/json/csv use).
    assert data == expected, f"html rows mismatch:\n  got:  {data}\n  want: {expected}"

    # The spec's explicit ordering phrasing: the first ranked goal's title
    # appears earlier in stdout than the second's.
    ranked = slate.ranked()
    assert o.index(ranked[0].title) < o.index(ranked[1].title)


# ===========================================================================
# Behavior 5 — Every interpolated cell is HTML-escaped (the correctness hazard)
# ===========================================================================


def test_b05_dynamic_cells_are_html_escaped(tmp_path, capsys):
    script = _single_goal_script(tmp_path, HOSTILE_TITLE)
    argv, out = _scan_argv(tmp_path, fmt="html", script=script, tag="hostile")
    rc, o, e = _run(argv, capsys)
    assert rc == 0, e

    slate = _load(out)
    ranked = slate.ranked()
    assert len(ranked) == 1
    # The persisted title kept every hostile character verbatim.
    assert ranked[0].title == HOSTILE_TITLE, repr(ranked[0].title)

    # Escaped forms present in the raw document...
    assert "&lt;script&gt;" in o, "the < and > of <script> must be escaped"
    assert "&quot;" in o, 'the double-quote must be escaped (html.escape quote=True)'
    assert "&amp;" in o, "the ampersand must be escaped"
    # ...and the RAW markup must never survive into the document.
    assert "<script>" not in o, "raw <script> must not appear (would be an injection)"
    assert "<b>" not in o, "raw <b> must not appear"

    # And the cell round-trips: decoding entities recovers the original title.
    _header, data, _counts = _extract(o)
    assert len(data) == 1
    assert data[0][4] == HOSTILE_TITLE, f"decoded title cell must equal original; got {data[0][4]!r}"

    # Decision + category .value cells are likewise routed through html.escape;
    # for safe enum strings they render as the .value text.
    assert data[0][1] == gate_slate(slate, Settings())[0].decision.value
    assert data[0][3] == ranked[0].category.value


# ===========================================================================
# Behavior 6 — --top N slices the shown rows; the slate file stays complete
# ===========================================================================


def test_b06_top_slices_rows_uniformly_no_reorder(tmp_path, capsys):
    # Full (no --top) first, to learn M and the ranked order.
    argv_all, out_all = _scan_argv(tmp_path, fmt="html", tag="all")
    rc, o_all, _e = _run(argv_all, capsys)
    assert rc == 0
    _h, all_data, _c = _extract(o_all)
    m = len(all_data)
    assert m == 4

    # 1 <= N < M -> exactly N data rows, the N highest-ranked, in order; and the
    # persisted slate file still holds ALL M goals (behavior 8 overlap).
    for n in (1, 2, 3):
        argv_n, out_n = _scan_argv(tmp_path, fmt="html", top=n, tag=f"top{n}")
        rc_n, o_n, e_n = _run(argv_n, capsys)
        assert rc_n == 0, e_n
        _hn, data_n, _cn = _extract(o_n)
        assert len(data_n) == n, f"--top {n} must render {n} data rows; got {len(data_n)}"
        assert data_n == all_data[:n], (data_n, all_data[:n])  # never re-ordered
        assert [r[0] for r in data_n] == [str(i) for i in range(1, n + 1)]
        # No count field / extra row / truncation note added.
        assert "showing top" not in o_n
        assert "of 4" not in o_n
        # Slate file complete regardless of --top.
        assert len(_load(out_n).goals) == m

    # N >= M -> all M rows (a cap hiding nothing).
    argv_big, _ = _scan_argv(tmp_path, fmt="html", top=99, tag="topbig")
    rc_b, o_b, _eb = _run(argv_big, capsys)
    assert rc_b == 0
    _hb, data_b, _cb = _extract(o_b)
    assert data_b == all_data


# ===========================================================================
# Behavior 7 — Pure-document output: no trailer, no truncation note
# ===========================================================================


def test_b07_pure_document_no_trailer_no_note(tmp_path, capsys):
    # --top 2 < M is the case where table/markdown WOULD print a note; html must not.
    argv, _ = _scan_argv(tmp_path, fmt="html", top=2, tag="pure")
    rc, o, e = _run(argv, capsys)
    assert rc == 0
    assert e == ""

    assert "slate written:" not in o, "html must suppress the slate-written trailer"
    assert "showing top" not in o, "html must suppress the '... showing top N of M' note"
    # The ENTIRE stdout is the single HTML document: starts at the DOCTYPE and
    # nothing stray follows </html> (so redirecting to a .html file is valid).
    assert o.startswith("<!DOCTYPE html>")
    tail = o[o.rindex("</html>") + len("</html>"):]
    assert tail in ("", "\n"), f"no stray text after </html>; tail={tail!r}"


# ===========================================================================
# Behavior 8 — Slate file written identically & COMPLETE (behavior 10 preserved)
# ===========================================================================


def test_b08_slate_file_written_complete(tmp_path, capsys):
    # Explicit --out, with --top 1 to prove the file ignores the stdout cap.
    out = tmp_path / "explicit_out.json"
    argv, _ = _scan_argv(tmp_path, fmt="html", top=1, out=out, tag="complete")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    _h, data, _c = _extract(o)
    assert len(data) == 1, "stdout is a capped view under --top 1"

    # The file at --out is the COMPLETE record: valid JSON, full slate schema.
    raw = json.loads(out.read_text())
    assert "created_at" in raw, "the persisted file must be the full slate schema"
    slate = _load(out)
    assert len(slate.goals) == 4, "stdout is a view; the file must hold every goal"


def test_b08b_default_out_path_used_when_no_out(tmp_path, capsys):
    # Absent --out, the slate is written to <state-dir>/slate.json, same as any
    # other --format.
    state = tmp_path / "state_default_out"
    argv = [
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state),
        "--format", "html",
    ]
    rc, o, e = _run(argv, capsys)
    assert rc == 0, e
    default_out = state / "slate.json"
    assert default_out.is_file(), "html must still write <state-dir>/slate.json by default"
    assert len(_load(default_out).goals) == 4


# ===========================================================================
# Behavior 9 — Empty slate -> well-formed document with the (no candidate goals) marker
# ===========================================================================


def test_b09_empty_slate_wellformed_with_marker(tmp_path, capsys):
    script = _empty_script(tmp_path)
    argv, _ = _scan_argv(tmp_path, fmt="html", script=script, tag="empty")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    # Behavior 2 still holds (well-formed, self-contained).
    assert o.startswith("<!DOCTYPE html>")
    tail = o[o.rindex("</html>") + len("</html>"):]
    assert tail in ("", "\n")
    for tag in ("<html", "<head", "<style", "<body", "<table"):
        assert tag in o

    header, data, counts = _extract(o)
    assert counts.get("th") == 5 and header[0] == HEADER, "header table still present on empty"
    # Exactly ONE data row whose text content is exactly the human marker (NOT
    # csv/json's bare data-stream behavior).
    assert len(data) == 1, f"empty slate must show exactly one marker row; got {data}"
    assert " ".join(c for c in data[0]).strip() == "(no candidate goals)", data[0]
    # Still a pure document — no trailer/note.
    assert "slate written:" not in o
    assert "showing top" not in o


def test_b09b_empty_marker_keys_off_full_slate_not_top(tmp_path, capsys):
    # An empty slate shows the marker regardless of --top.
    script = _empty_script(tmp_path)
    argv, _ = _scan_argv(tmp_path, fmt="html", top=5, script=script, tag="empty_top")
    rc, o, e = _run(argv, capsys)
    assert rc == 0
    assert "(no candidate goals)" in o


# ===========================================================================
# Behavior 10 — Existing formats unchanged (bare == table; json/markdown/csv shapes)
# ===========================================================================


def test_b10_existing_formats_unperturbed(tmp_path, capsys):
    # Bare scan is byte-for-byte identical to --format table (same --out so the
    # trailer path matches) — adding html perturbs neither.
    out = tmp_path / "slate.json"
    argv_bare, _ = _scan_argv(tmp_path, out=out, tag="bare")
    rc0, o0, e0 = _run(argv_bare, capsys)
    argv_table = argv_bare + ["--format", "table"]
    rc1, o1, e1 = _run(argv_table, capsys)
    assert rc0 == 0 and rc1 == 0
    assert o1 == o0, "bare scan must stay byte-identical to --format table"
    assert e0 == "" and e1 == ""

    # json stays one pure JSON object (keys {workspace_root, goals}, no trailer).
    argv_json, _ = _scan_argv(tmp_path, fmt="json", tag="json")
    rc_j, o_j, _ej = _run(argv_json, capsys)
    assert rc_j == 0
    doc = json.loads(o_j)
    assert set(doc.keys()) == {"workspace_root", "goals"}
    assert "slate written:" not in o_j

    # csv keeps its RFC-4180 header (unchanged by html).
    argv_csv, _ = _scan_argv(tmp_path, fmt="csv", tag="csv")
    rc_c, o_c, _ec = _run(argv_csv, capsys)
    assert rc_c == 0
    assert o_c.splitlines()[0] == "rank,decision,score,category,title"
    assert "slate written:" not in o_c

    # markdown keeps its GFM 5-column table + the human trailer.
    argv_md, out_md = _scan_argv(tmp_path, fmt="markdown", tag="md")
    rc_m, o_m, _em = _run(argv_md, capsys)
    assert rc_m == 0
    md_lines = o_m.splitlines()
    assert md_lines[0] == "| # | decision | score | category | title |"
    assert md_lines[1] == "| --- | --- | --- | --- | --- |"
    assert f"slate written: {out_md}" in o_m  # markdown keeps the trailer, html does not


# ===========================================================================
# Behavior 11 — Invalid --format still a parse-time usage error (exit 2)
# ===========================================================================


def test_b11_invalid_format_rejected_at_parse_time(tmp_path, capsys):
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
    # argparse rejects the unknown choice at parse time -> SystemExit(2); adding
    # "html" to the choices list did not weaken parse-time validation.
    assert excinfo.value.code == 2

    cap = capsys.readouterr()
    assert cap.out == "", f"nothing on stdout for a rejected format; got {cap.out!r}"
    assert "xml" in cap.err, f"usage error must name the invalid choice; got:\n{cap.err}"
    assert "--format" in cap.err
    # No work happened: no slate file written (rejection precedes collect/render/write).
    assert not out.exists()


# ===========================================================================
# Behavior 12 — Workspace guard unchanged for html (front-door, format-independent)
# ===========================================================================


def test_b12_workspace_guard_precedes_html_handling(tmp_path, capsys):
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
        "--format", "html",
    ]
    rc, o, e = _run(argv, capsys)

    assert rc == 2, f"missing workspace with --format html must exit 2; got {rc}"
    assert f"error: workspace not found: {missing}" in e
    assert o == "", f"the guard runs before any html rendering; stdout must be empty, got {o!r}"
    assert not out.exists(), "no slate file may be written when the workspace guard fires"


# ===========================================================================
# Backward-compat guard — additive extension, no __version__ bump (AC).
# ===========================================================================


def test_version_unchanged_additive_extension():
    assert proactive_loop.__version__ == "0.1.1"
