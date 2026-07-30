"""Black-box behavior tests for iteration 12.

Feature under test: ``pla scan --format {table,json,markdown}`` -- a
backward-compatible output-format flag on the ``scan`` verb (default ``table``)
that adds (a) a machine-pipeable JSON document on stdout and (b) a paste-ready
GitHub-flavored Markdown table, each carrying the live autonomy-gate decision
per goal in ``ranked()`` order. ``table`` stays the default so every existing
invocation is byte-for-byte unchanged; ``--format`` selects the STDOUT rendering
only and never changes the persisted slate file.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.5 (the ``scan`` CLI bullet) -- and drive
only the documented public surface: the ``pla`` CLI via ``main([...])`` (its
observable stdout/stderr/exit-code/written-artifacts), plus the public domain
models (``GoalSlate``/``AutonomyDecision`` from ``proactive_loop.models``), the
public gate ``gate_slate`` from ``proactive_loop.scout``, and ``Settings`` from
``proactive_loop.config`` -- exactly the surface the spec authorizes ("The tester
may also construct a ``GoalSlate`` + ``gate_slate(...)`` directly"). **No file
under ``src/`` was read, no engineer/reviewer notes were read, and no
``git diff`` was consulted.** No internal (``_``-prefixed) render helper is
imported; every rendering assertion is made against the CLI's real stdout. All
tests are fully offline via the bundled scripted provider (no network, no API
keys) and use fresh ``tmp_path`` state/out dirs. Goal ``id`` values are NOT
deterministic across runs, so no test hard-codes an id -- ids are always read
back from the persisted slate written by that same run.
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

# The bundled fixture script `S` yields a 4-goal slate whose ranked() order and
# live gate outcomes are: finance_legal(25.0)->needs_approval[sensitive],
# learning(18.0)->auto_dispatch, career(1.5)->needs_approval[below-threshold],
# maintenance(2.4, not-now)->blocked.
MD_HEADER = "| # | decision | score | category | title |"
MD_SEP = "| --- | --- | --- | --- | --- |"


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
    return argv, out


def _write_empty_script(tmp_path: Path) -> Path:
    """A scripted-responses file whose synthesize reply parses to zero goals."""
    p = tmp_path / "empty_script.json"
    p.write_text(json.dumps({"responses": [{"tag": "synthesize", "text": "[]"}]}))
    return p


def _write_tricky_title_script(tmp_path: Path) -> Path:
    """A single-goal script whose title contains a raw `|` and a newline plus a
    whitespace run -- the exact input that must not break a Markdown row."""
    goal = {
        "title": "Fix a | b\nand   c",
        "category": "project",
        "impact": 5.0,
        "urgency": 5.0,
        "confidence": 1.0,
        "effort_weight": 1.0,
        "appropriate_now": True,
    }
    p = tmp_path / "pipe_script.json"
    p.write_text(json.dumps({"responses": [{"tag": "synthesize", "text": json.dumps([goal])}]}))
    return p


def _load(out: Path) -> GoalSlate:
    return GoalSlate.model_validate_json(out.read_text())


# ===========================================================================
# Behavior 1 -- Default (no --format) is unchanged: table + blank line + trailer
# ===========================================================================


def test_b01_default_prints_table_blank_line_and_trailer(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path)
    rc, o, e = _run(argv, capsys)

    assert rc == 0
    # The existing ranked table is present with its header + all gate decisions.
    assert "DECISION" in o
    for token in ("auto_dispatch", "needs_approval", "blocked"):
        assert token in o, f"table must show gate decision {token!r}; got:\n{o}"
    # ...followed by a blank line and a `slate written: <path>` trailer.
    assert f"\n\nslate written: {out}" in o, f"missing blank-line+trailer; got:\n{o}"
    assert o.rstrip("\n").endswith(f"slate written: {out}")
    # ...and the slate JSON was written to the chosen --out path.
    assert out.is_file()
    assert len(_load(out).goals) == 4
    assert e == ""


# ===========================================================================
# Behavior 2 -- `--format table` is byte-identical to the default
# ===========================================================================


def test_b02_format_table_byte_identical_to_default(tmp_path, capsys):
    out = tmp_path / "slate.json"
    argv_default, _ = _scan_argv(tmp_path, out=out, tag="def")
    rc0, o0, e0 = _run(argv_default, capsys)

    # Same inputs (same --out so the trailer path is identical), only add
    # --format table.
    argv_table = argv_default + ["--format", "table"]
    rc1, o1, e1 = _run(argv_table, capsys)

    assert rc0 == 0 and rc1 == 0
    assert o1 == o0, "`--format table` stdout must equal the default character-for-character"
    assert e0 == "" and e1 == ""


# ===========================================================================
# Behavior 3 -- `--format json` emits ONE JSON document and nothing else
# ===========================================================================


def test_b03_format_json_single_document_no_trailer(tmp_path, capsys):
    argv, _ = _scan_argv(tmp_path, fmt="json")
    rc, o, e = _run(argv, capsys)

    assert rc == 0
    # The ENTIRE stdout parses as a single JSON object (pipes cleanly into jq).
    doc = json.loads(o)
    assert isinstance(doc, dict)
    # No human table, no `slate written:` trailer on stdout.
    assert "slate written:" not in o
    assert "DECISION" not in o
    assert e == ""


# ===========================================================================
# Behavior 4 -- JSON document shape (exact top-level + per-goal key sets, order)
# ===========================================================================


def test_b04_json_document_shape(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, fmt="json")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    doc = json.loads(o)
    assert set(doc.keys()) == {"workspace_root", "goals"}, "exactly two top-level keys"

    slate = _load(out)
    ranked = slate.ranked()
    assert doc["workspace_root"] == slate.workspace_root
    assert isinstance(doc["goals"], list)
    assert len(doc["goals"]) == len(ranked) == 4

    # Each element has EXACTLY these seven keys.
    for g in doc["goals"]:
        assert set(g.keys()) == {
            "id", "title", "category", "score", "appropriate_now", "decision", "reason",
        }

    # goals[] is in slate.ranked() order (same order as the table).
    assert [g["id"] for g in doc["goals"]] == [gg.id for gg in ranked]
    assert [g["title"] for g in doc["goals"]] == [gg.title for gg in ranked]
    # Enums render as their .value strings only.
    assert [g["category"] for g in doc["goals"]] == [gg.category.value for gg in ranked]
    assert [g["score"] for g in doc["goals"]] == [gg.score for gg in ranked]
    assert [g["appropriate_now"] for g in doc["goals"]] == [gg.appropriate_now for gg in ranked]
    for g in doc["goals"]:
        assert isinstance(g["id"], str)
        assert isinstance(g["title"], str)
        assert isinstance(g["category"], str)
        assert isinstance(g["score"], (int, float))
        assert isinstance(g["appropriate_now"], bool)
    # No enum reprs anywhere in the stream, only .value strings.
    assert "GoalCategory." not in o
    assert "AutonomyDecision." not in o
    assert "RunStatus." not in o


# ===========================================================================
# Behavior 5 -- JSON gate decisions ARE the live gate outcome
# ===========================================================================


def test_b05_json_decisions_are_live_gate_outcome(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, fmt="json")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    doc = json.loads(o)
    slate = _load(out)
    decisions = gate_slate(slate, Settings())

    # decision/reason equal gate(goal, settings) for every goal, in ranked order.
    assert [g["decision"] for g in doc["goals"]] == [d.decision.value for d in decisions]
    assert [g["reason"] for g in doc["goals"]] == [d.reason for d in decisions]

    # Fixture-specific safety facts.
    by_cat = {g["category"]: g for g in doc["goals"]}
    assert by_cat["learning"]["decision"] == "auto_dispatch"
    # The sensitive category is NEVER auto_dispatch even though it scores highest.
    assert by_cat["finance_legal"]["decision"] == "needs_approval"
    assert by_cat["finance_legal"]["decision"] != "auto_dispatch"
    # The not-appropriate-now goal is blocked.
    not_now = [g for g in doc["goals"] if not g["appropriate_now"]]
    assert not_now, "fixture must contain a not-appropriate-now goal"
    assert all(g["decision"] == "blocked" for g in not_now)


# ===========================================================================
# Behavior 6 -- Empty slate under `--format json`
# ===========================================================================


def test_b06_empty_slate_json_is_one_object(tmp_path, capsys):
    script = _write_empty_script(tmp_path)
    argv, _ = _scan_argv(tmp_path, fmt="json", script=script)
    rc, o, e = _run(argv, capsys)

    assert rc == 0
    doc = json.loads(o)  # whole stdout still parses as one JSON object
    assert isinstance(doc, dict)
    assert set(doc.keys()) == {"workspace_root", "goals"}
    assert doc["goals"] == []
    assert "slate written:" not in o


# ===========================================================================
# Behavior 7 -- `--format markdown` emits a GitHub-flavored Markdown table
# ===========================================================================


def test_b07_format_markdown_gfm_table(tmp_path, capsys):
    argv, out = _scan_argv(tmp_path, fmt="markdown")
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    lines = o.splitlines()
    assert lines[0] == MD_HEADER
    assert lines[1] == MD_SEP

    slate = _load(out)
    ranked = slate.ranked()
    decisions = gate_slate(slate, Settings())
    # One row per goal in ranked() order, 1-based rank, .2f score, enum .values.
    for rank, (g, d) in enumerate(zip(ranked, decisions), start=1):
        row = lines[1 + rank]  # header=0, separator=1, first data row=2
        expected = (
            f"| {rank} | {d.decision.value} | {g.score:.2f} | "
            f"{g.category.value} | {g.title} |"
        )
        assert row == expected, f"row {rank} mismatch:\n  got:  {row}\n  want: {expected}"

    # markdown (unlike json) KEEPS the human trailer.
    assert f"slate written: {out}" in o
    assert e == ""


# ===========================================================================
# Behavior 8 -- Markdown cells stay well-formed (pipe escaped, newline collapsed)
# ===========================================================================


def test_b08_markdown_cells_escaped_and_single_line(tmp_path, capsys):
    script = _write_tricky_title_script(tmp_path)  # title: "Fix a | b\nand   c"
    argv, out = _scan_argv(tmp_path, fmt="markdown", script=script)
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    lines = o.splitlines()
    assert lines[0] == MD_HEADER
    assert lines[1] == MD_SEP

    # The one goal must render as EXACTLY one physical data row -- the embedded
    # newline must not spill the title onto a second line.
    data_rows = [ln for ln in lines if re.match(r"^\| \d+ \|", ln)]
    assert len(data_rows) == 1, f"a title with a newline must not add rows; got {data_rows}"
    row = data_rows[0]

    # The raw `|` is escaped to `\|`; the newline + whitespace-run collapse to a
    # single space; so exactly the 6 renderer-emitted delimiters remain unescaped.
    assert r"Fix a \| b and c" in row
    assert "\n" not in row
    unescaped_pipes = row.replace(r"\|", "").count("|")
    assert unescaped_pipes == 6, f"row must have a constant 6 unescaped delimiters; row={row!r}"
    # Header and separator carry the same constant delimiter count.
    assert lines[0].count("|") == 6
    assert lines[1].count("|") == 6


# ===========================================================================
# Behavior 9 -- Empty slate under `--format markdown`
# ===========================================================================


def test_b09_empty_slate_markdown_fallback(tmp_path, capsys):
    script = _write_empty_script(tmp_path)
    argv, out = _scan_argv(tmp_path, fmt="markdown", script=script)
    rc, o, e = _run(argv, capsys)
    assert rc == 0

    lines = o.splitlines()
    assert lines[0] == MD_HEADER
    assert lines[1] == MD_SEP
    assert lines[2] == "(no candidate goals)"
    # The trailer is still printed after the empty-marker.
    assert f"slate written: {out}" in o


# ===========================================================================
# Behavior 10 -- Every format writes the identical slate file; dispatch works
# ===========================================================================


def test_b10_persisted_slate_is_format_independent_and_dispatchable(tmp_path, capsys):
    def _run_fmt(fmt: str) -> Path:
        argv, out = _scan_argv(tmp_path, fmt=fmt, tag=fmt)
        rc, o, e = _run(argv, capsys)
        assert rc == 0, f"scan --format {fmt} must exit 0; stderr={e}"
        return out

    def _normalize(slate: GoalSlate):
        # Everything the persisted slate carries EXCEPT inherently per-run fields
        # (created_at timestamp, randomly-generated goal id).
        return [
            (g.title, g.category.value, g.score, g.appropriate_now)
            for g in slate.ranked()
        ]

    outs = {fmt: _run_fmt(fmt) for fmt in ("table", "json", "markdown")}
    slates = {fmt: _load(p) for fmt, p in outs.items()}

    # The persisted file is the FULL slate schema (has created_at) -- NOT the
    # trimmed 2-key stdout json object -- for every format.
    for fmt, p in outs.items():
        raw = json.loads(p.read_text())
        assert "created_at" in raw, f"{fmt} slate file must be the full slate schema"
        assert len(slates[fmt].goals) == 4

    # --format affects stdout ONLY: the persisted slate content is identical
    # across the three formats (modulo the per-run created_at/id).
    base = _normalize(slates["table"])
    assert _normalize(slates["json"]) == base
    assert _normalize(slates["markdown"]) == base

    # dispatch behaves identically no matter which format printed the slate:
    # the top AUTO_DISPATCH goal from each file runs to a clean exit.
    for fmt, p in outs.items():
        slate = slates[fmt]
        decs = {d.goal_id: d for d in gate_slate(slate, Settings())}
        auto = next(
            g for g in slate.goals if decs[g.id].decision is AutonomyDecision.AUTO_DISPATCH
        )
        rc, o, e = _run(
            [
                "dispatch",
                "--slate", str(p),
                "--goal-id", auto.id,
                "--provider", "scripted",
                "--scripted-responses", str(SCRIPT),
                "--state-dir", str(tmp_path / f"disp_{fmt}"),
            ],
            capsys,
        )
        assert rc == 0, f"dispatch from a {fmt}-printed slate must succeed; stderr={e}"
        assert (tmp_path / f"disp_{fmt}" / f"run-{auto.id}").exists()


# ===========================================================================
# Behavior 11 -- Invalid --format value is rejected BEFORE any work
# ===========================================================================


def test_b11_invalid_format_is_argparse_systemexit_2(tmp_path, capsys):
    out = tmp_path / "slate.json"
    state = tmp_path / "state"
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
    # argparse rejects the choice at parse time -> SystemExit(2).
    assert excinfo.value.code == 2

    err = capsys.readouterr().err
    assert "xml" in err, f"usage error must name the invalid choice; got:\n{err}"
    assert "--format" in err
    # No work happened: no slate file written, no run dirs created.
    assert not out.exists()
    assert list(state.glob("run-*")) == [] if state.exists() else True


# ===========================================================================
# Behavior 12 -- --workspace guard precedence is unchanged (exit 2, distinct)
# ===========================================================================


@pytest.mark.parametrize("fmt", [None, "table", "json", "markdown"])
def test_b12_workspace_guard_precedes_format_handling(tmp_path, capsys, fmt):
    missing = tmp_path / "no_such_ws"
    assert not missing.exists()
    out = tmp_path / f"slate_{fmt}.json"
    state = tmp_path / f"state_{fmt}"

    argv = [
        "scan",
        "--workspace", str(missing),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state),
        "--out", str(out),
    ]
    if fmt is not None:
        argv += ["--format", fmt]

    rc, o, e = _run(argv, capsys)

    # main() RETURNS 2 (distinct from behavior 11's argparse SystemExit(2)).
    assert rc == 2, f"missing workspace with --format {fmt} must exit 2; got {rc}"
    assert f"error: workspace not found: {missing}" in e
    # The guard runs before any format handling: nothing rendered, nothing written.
    assert o == "", f"no format rendering must occur for a bad workspace; got:\n{o}"
    assert not out.exists()
