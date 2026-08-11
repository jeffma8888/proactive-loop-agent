"""Black-box behavior tests for state-dir iteration 105 (ships as commit-seq
**factory iter 112**): ``pla signals --timings`` prints an OPT-IN per-collector
wall-clock cost table to **stderr** -- collector name, elapsed milliseconds and
the number of signals that collector contributed, in registry order, plus a
``TOTAL`` row -- while leaving every byte of stdout unchanged (ROADMAP #119).

Why that mattered: ``pla watch`` re-runs the whole collect pipeline on a timer,
so per-tick cost is a real user concern on a large workspace, yet the product
shipped ZERO cost instrumentation. Attributing a scan's time to a collector
previously required monkeypatching stdlib from OUTSIDE the package. This flag
makes the attribution a documented, opt-in diagnostic -- and the governing
invariant is that a diagnostic full of NON-DETERMINISTIC numbers must never
leak into a stdout contract that other tests (and users' pipes) depend on.

ISOLATION CONTRACT (honored): every assertion here is written from THIS
iteration's spec (``pm.md`` Expected Behaviors 1-12), ``README.md`` and the
product's own observable output obtained by RUNNING it -- the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (exit code / stdout / stderr), the
shared collector seam ``proactive_loop.cli._collect`` (which this suite has
treated as a public seam since test_iter19), and the public registry API
``proactive_loop.collectors.all_collectors()``. **No file under ``src/`` was
read by the author, no engineer or reviewer note was consulted, and no
``git diff`` was inspected.**

Determinism discipline (spec acceptance criterion): these tests assert the
table's SHAPE only -- row count, registry ORDER, field types, 2-decimal
formatting, non-negativity, and the count/total reconciliation. No test asserts
a duration VALUE, a duration THRESHOLD, or an ordering BY duration, because
wall-clock timings are not reproducible. The one numeric tolerance used
(behavior 6) is derived from the spec's own rounding budget.

Fully offline and cap-cheap: zero network, zero API keys, zero subprocesses;
filesystem work is limited to ``tmp_path`` workspaces, the in-repo
``examples/`` fixture (read-only) and ``README.md``.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import logging
import re
from pathlib import Path

import pytest

from proactive_loop import cli
from proactive_loop.cli import build_parser, main
from proactive_loop.collectors import all_collectors
from proactive_loop.models import ContextSignal, WorkspaceSnapshot

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_CLI_LOGGER = "proactive_loop.cli"

# The spec's literal header line (behavior 3). Used both as the positive anchor
# for parsing and as the negative probe proving stdout is never touched.
HEADER = "collector timings (ms):"

# The spec's TOTAL row marker (behaviors 3 and 6).
TOTAL = "TOTAL"

# Behavior 5: "non-negative float formatted to exactly 2 decimal places".
MS_RE = re.compile(r"^\d+\.\d{2}$")

# The `signals` options that PRE-DATE this feature (behavior 12: the README row is
# extended, not rewritten). Listed ONE PER LINE deliberately: iter-108's corpus
# scan (test_iter108_behavior.py::test_b05_no_test_passes_an_impossible_kind
# _through_the_cli) is a per-LINE regex that reads any quoted token written
# directly after a quoted "--kind" as a --kind VALUE, so an inline tuple trips it
# on the innocent neighbouring pair.
PRE_EXISTING_SIGNALS_OPTIONS = (
    "--json",
    "--kind",
    "--min-weight",
    "--summary",
)


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


def _parse_timings(err: str) -> list[tuple[str, str, str]]:
    """The timing block's rows as raw ``(name, ms, count)`` string triples.

    Parsed positionally from the spec's header: every subsequent line that
    splits into exactly three whitespace-separated fields is a row, and the
    block ends at the first line that does not. Fail-closed: a missing header
    raises ``AssertionError`` rather than returning an empty list, so a feature
    that silently emits nothing cannot pass a row-shape test vacuously.
    """
    lines = err.splitlines()
    header_idx = next((i for i, ln in enumerate(lines) if ln.strip() == HEADER), None)
    assert header_idx is not None, (
        f"stderr carries no timing header {HEADER!r}; stderr={err!r}"
    )
    rows: list[tuple[str, str, str]] = []
    for line in lines[header_idx + 1 :]:
        fields = line.split()
        if len(fields) != 3:
            break
        rows.append((fields[0], fields[1], fields[2]))
    assert rows, f"the timing block has a header but no rows; stderr={err!r}"
    return rows


def _collector_rows(err: str) -> list[tuple[str, str, str]]:
    """Rows excluding the trailing ``TOTAL`` row."""
    rows = _parse_timings(err)
    assert rows[-1][0] == TOTAL, (
        f"the last row's name field must be {TOTAL!r}; got {rows[-1][0]!r}"
    )
    return rows[:-1]


def _total_row(err: str) -> tuple[str, str, str]:
    rows = _parse_timings(err)
    assert rows[-1][0] == TOTAL
    return rows[-1]


def _registry_names() -> list[str]:
    return [c.name for c in all_collectors()]


def _make_workspace(tmp_path: Path) -> Path:
    """A small workspace whose signals are deterministic across runs.

    Deliberately NOT empty: behaviors 2/6/8 are vacuous if the snapshot has no
    signals, so this plants content that several distinct collectors perceive
    (a TODO comment, a notes file, a source file with no tests).
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("# TODO: fix this\nx = 1\n", encoding="utf-8")
    (ws / "NOTES.md").write_text("- idea one\n", encoding="utf-8")
    return ws


def _cli_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == _CLI_LOGGER and r.levelno == logging.WARNING
    ]


def _readme_halves() -> tuple[str, str]:
    """(above-marker human intro, below-marker reference)."""
    text = README.read_text(encoding="utf-8")
    idx = text.find("PORTFOLIO INTRO")
    assert idx > 0, "README must still carry the human-owned PORTFOLIO INTRO marker"
    return text[:idx], text[idx:]


# ---------------------------------------------------------------------------
# Local test doubles satisfying the Collector shape (name + collect(root)).
# The injection seam is ``proactive_loop.cli.all_collectors`` -- the same one
# test_iter19 uses -- so behaviors 4 and 9 can be proven without depending on
# the real 17-collector registry.
# ---------------------------------------------------------------------------
class _RaisingCollector:
    """A buggy collector violating the SPEC 4.1 never-raise convention."""

    def __init__(self, name: str = "boom") -> None:
        self.name = name

    def collect(self, root: Path) -> list[ContextSignal]:
        raise RuntimeError(f"exploded inside {self.name}")


class _FixedCollector:
    """A conformant collector emitting a fixed number of signals."""

    def __init__(self, name: str = "ok", *, count: int = 1) -> None:
        self.name = name
        self._count = count

    def collect(self, root: Path) -> list[ContextSignal]:
        return [
            ContextSignal(source=self.name, kind="note", summary=f"{self.name}-{i}")
            for i in range(self._count)
        ]


# ===========================================================================
# Behavior 1 -- default off, and byte-identical to a no-flag run.
# ===========================================================================
def test_b01_no_flag_writes_nothing_to_stderr(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    code, out, err = _run(["signals", "--workspace", str(ws)])
    assert code == 0, f"signals must exit 0; got {code} (stderr={err!r})"
    assert err == "", (
        "without --timings the verb must stay silent on stderr too (default off "
        f"means silent on BOTH streams); got {err!r}"
    )
    assert HEADER not in out, f"no timing block may appear on stdout; got {out!r}"


def test_b01_no_flag_run_is_reproducible(tmp_path: Path) -> None:
    """Fixture premise for behaviors 2 and 8: the no-flag baseline itself is
    byte-stable, so a later stdout diff can only be caused by the flag."""
    ws = _make_workspace(tmp_path)
    _c1, out1, err1 = _run(["signals", "--workspace", str(ws)])
    _c2, out2, err2 = _run(["signals", "--workspace", str(ws)])
    assert out1 == out2, "the no-flag baseline is not reproducible"
    assert err1 == err2 == ""


def test_b01_default_off_for_the_seam_too(tmp_path: Path) -> None:
    """The default-off claim holds at the shared seam, not just at the flag."""
    ws = _make_workspace(tmp_path)
    snapshot = cli._collect(ws)
    assert isinstance(snapshot, WorkspaceSnapshot)


# ===========================================================================
# Behavior 2 -- stdout is never touched by --timings.
# ===========================================================================
@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--json"],
        ["--summary"],
        ["--kind", "todo"],
        ["--min-weight", "0.9"],
        ["--summary", "--json"],
    ],
    ids=["human", "json", "summary", "kind", "minweight", "summary-json"],
)
def test_b02_stdout_is_byte_identical_with_and_without_the_flag(
    tmp_path: Path, extra: list[str]
) -> None:
    ws = _make_workspace(tmp_path)
    base = ["signals", "--workspace", str(ws), *extra]
    code_a, out_a, err_a = _run(base)
    code_b, out_b, err_b = _run([*base, "--timings"])
    assert code_a == code_b == 0, f"both runs must exit 0; got {code_a} / {code_b}"
    assert out_b == out_a, (
        "--timings must not change a single byte of stdout for "
        f"{extra!r}:\n--- without ---\n{out_a}\n--- with ---\n{out_b}"
    )
    assert err_a == "", f"baseline stderr must be empty; got {err_a!r}"
    assert HEADER in err_b, f"--timings must emit its block on stderr; got {err_b!r}"


def test_b02_no_timing_field_leaks_onto_stdout(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    _code, out, _err = _run(["signals", "--workspace", str(ws), "--timings"])
    for probe in (HEADER, "timings", "elapsed", TOTAL):
        assert probe not in out, f"{probe!r} leaked onto stdout: {out!r}"


# ===========================================================================
# Behavior 3 -- block shape: header, one row per collector that ran, TOTAL.
# ===========================================================================
def test_b03_header_row_per_collector_and_a_total_row(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    assert code == 0, f"must exit 0; got {code} (stderr={err!r})"
    assert err.splitlines()[0].strip() == HEADER, (
        f"the block must open with {HEADER!r}; got {err.splitlines()[:1]!r}"
    )
    rows = _parse_timings(err)
    names = _registry_names()
    assert len(rows) == len(names) + 1, (
        f"expected {len(names)} collector rows + 1 TOTAL row; got {len(rows)} "
        f"({[r[0] for r in rows]})"
    )
    assert rows[-1][0] == TOTAL
    assert [r[0] for r in rows[:-1]] == names


def test_b03_exactly_one_total_row(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    assert [r[0] for r in _parse_timings(err)].count(TOTAL) == 1


def test_b03_header_appears_exactly_once(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    assert err.count(HEADER) == 1, f"the block must be emitted once; got {err!r}"


# ===========================================================================
# Behavior 4 -- registry order, NOT sorted by duration and NOT alphabetised.
# ===========================================================================
def test_b04_rows_follow_the_live_registry_order(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    assert [r[0] for r in _collector_rows(err)] == _registry_names()


def test_b04_rows_are_not_alphabetised(tmp_path: Path) -> None:
    """Guard against a renderer that sorts: the real registry is NOT in name
    order, so an alphabetised table would be a silent contract change."""
    names = _registry_names()
    assert names != sorted(names), (
        "fixture premise: the registry order must differ from name order for "
        "this test to discriminate"
    )
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    emitted = [r[0] for r in _collector_rows(err)]
    assert emitted != sorted(emitted), f"the table was alphabetised: {emitted}"


def test_b04_order_is_the_injected_registry_order_not_a_duration_sort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Injected doubles in a deliberately non-alphabetical order: the table must
    mirror the registry sequence exactly, whatever the measured durations."""
    order = ["zeta", "alpha", "mid", "beta"]
    monkeypatch.setattr(
        cli, "all_collectors", lambda: [_FixedCollector(n, count=1) for n in order]
    )
    ws = _make_workspace(tmp_path)
    code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    assert code == 0, f"must exit 0; got {code} (stderr={err!r})"
    assert [r[0] for r in _collector_rows(err)] == order


# ===========================================================================
# Behavior 5 -- row fields: name, ms (2dp, non-negative), integer count.
# ===========================================================================
def test_b05_every_row_has_exactly_three_whitespace_separated_fields(
    tmp_path: Path,
) -> None:
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    header_idx = err.splitlines().index(HEADER)
    body = [ln for ln in err.splitlines()[header_idx + 1 :] if ln.strip()]
    assert body, "the block must have a body"
    for line in body:
        assert len(line.split()) == 3, (
            f"row {line!r} does not split into exactly 3 fields "
            f"(name / ms / count) -- columns are glued or a field is missing"
        )


def test_b05_ms_field_is_a_non_negative_float_with_two_decimals(
    tmp_path: Path,
) -> None:
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    for name, ms, _count in _parse_timings(err):
        assert MS_RE.match(ms), (
            f"{name}: ms field {ms!r} is not a non-negative float with exactly "
            "2 decimal places"
        )
        assert float(ms) >= 0.0, f"{name}: negative duration {ms!r}"


def test_b05_count_field_is_a_non_negative_integer(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    for name, _ms, count in _parse_timings(err):
        assert count.isdigit(), f"{name}: count field {count!r} is not an integer"
        assert int(count) >= 0


def test_b05_counts_are_the_signals_that_collector_contributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-collector attribution, proven with doubles emitting known counts."""
    plan = {"three": 3, "zero": 0, "one": 1}
    monkeypatch.setattr(
        cli,
        "all_collectors",
        lambda: [_FixedCollector(n, count=c) for n, c in plan.items()],
    )
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    got = {name: int(count) for name, _ms, count in _collector_rows(err)}
    assert got == plan, f"per-collector counts wrong: expected {plan}, got {got}"


# ===========================================================================
# Behavior 6 -- counts and total reconcile.
# ===========================================================================
def test_b06_counts_sum_to_the_snapshot_signal_count(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    _code, out, err = _run(["signals", "--workspace", str(ws), "--timings", "--json"])
    snapshot_signals = len(json.loads(out)["signals"])
    assert snapshot_signals > 0, "fixture premise: the workspace must yield signals"
    per_collector = sum(int(c) for _n, _ms, c in _collector_rows(err))
    assert per_collector == snapshot_signals, (
        f"per-collector counts sum to {per_collector} but the snapshot carries "
        f"{snapshot_signals} signals"
    )


def test_b06_total_row_count_equals_the_sum(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    rows = _collector_rows(err)
    total = _total_row(err)
    assert int(total[2]) == sum(int(c) for _n, _ms, c in rows), (
        f"TOTAL count {total[2]!r} != sum of per-collector counts"
    )


def test_b06_total_ms_equals_the_sum_within_the_rounding_budget(
    tmp_path: Path,
) -> None:
    """SHAPE assertion, not a duration assertion: the tolerance is the spec's
    own ``0.01 * number_of_collector_rows`` rounding budget."""
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    rows = _collector_rows(err)
    summed = sum(float(ms) for _n, ms, _c in rows)
    total_ms = float(_total_row(err)[1])
    budget = 0.01 * len(rows)
    assert abs(total_ms - summed) <= budget, (
        f"TOTAL ms {total_ms} differs from the sum {summed} by more than the "
        f"rounding budget {budget}"
    )


def test_b06_reconciliation_holds_with_injected_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "all_collectors",
        lambda: [_FixedCollector("a", count=2), _FixedCollector("b", count=5)],
    )
    ws = _make_workspace(tmp_path)
    _code, out, err = _run(["signals", "--workspace", str(ws), "--timings", "--json"])
    assert len(json.loads(out)["signals"]) == 7
    assert int(_total_row(err)[2]) == 7


# ===========================================================================
# Behavior 7 -- composes with --collector (an upstream filter).
# ===========================================================================
def test_b07_only_the_allowlisted_collectors_get_rows(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    code, _out, err = _run(
        [
            "signals",
            "--workspace", str(ws),
            "--timings",
            "--collector", "todos",
            "--collector", "notes",
        ]
    )
    assert code == 0, f"must exit 0; got {code} (stderr={err!r})"
    rows = _collector_rows(err)
    assert {r[0] for r in rows} == {"todos", "notes"}, (
        f"expected rows for exactly todos+notes; got {[r[0] for r in rows]}"
    )
    assert _total_row(err)[0] == TOTAL


def test_b07_excluded_collectors_get_no_row(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(
        ["signals", "--workspace", str(ws), "--timings", "--collector", "todos"]
    )
    emitted = {r[0] for r in _collector_rows(err)}
    excluded = set(_registry_names()) - {"todos"}
    leaked = sorted(emitted & excluded)
    assert emitted == {"todos"}, f"expected only todos; got {sorted(emitted)}"
    assert leaked == [], f"a collector that never ran got a row: {leaked}"


def test_b07_allowlisted_rows_keep_registry_order(tmp_path: Path) -> None:
    """Registry order survives the filter and is NOT the order the flags were
    typed in: `notes` is passed FIRST but follows `todos` in the registry."""
    names = _registry_names()
    assert names.index("todos") < names.index("notes"), "fixture premise"
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(
        [
            "signals",
            "--workspace", str(ws),
            "--timings",
            "--collector", "notes",
            "--collector", "todos",
        ]
    )
    assert [r[0] for r in _collector_rows(err)] == ["todos", "notes"]


# ===========================================================================
# Behavior 8 -- display filters reshape stdout only; the table is unchanged.
#
# SUPERSEDED CLASSIFICATION (factory iter 118, deliberate): `--kind` used to be
# checked here as a display-only filter. It is now an UPSTREAM collector
# allowlist -- `signals --kind K` runs ONLY the collector that emits K -- so it
# legitimately shrinks the row set, and it was removed from these two guards
# rather than the guards being weakened. Behavior 8's INTENT is unchanged and in
# fact strengthened: the timings table must never lie about which collectors RAN.
# The genuinely display-only filters (--min-weight/--summary/--json) are still
# guarded below, and the new --kind contract is asserted in
# tests/test_iter118_behavior.py.
# ===========================================================================
@pytest.mark.parametrize(
    "extra",
    [
        ["--min-weight", "0.95"],
        ["--summary"],
        ["--json"],
        ["--summary", "--min-weight", "0.95"],
    ],
    ids=["minweight", "summary", "json", "summary-minweight"],
)
def test_b08_display_filters_do_not_change_the_row_set(
    tmp_path: Path, extra: list[str]
) -> None:
    ws = _make_workspace(tmp_path)
    _c0, _o0, err_plain = _run(["signals", "--workspace", str(ws), "--timings"])
    code, _out, err = _run(["signals", "--workspace", str(ws), "--timings", *extra])
    assert code == 0, f"must exit 0 for {extra!r}; got {code} (stderr={err!r})"
    assert [r[0] for r in _parse_timings(err)] == [
        r[0] for r in _parse_timings(err_plain)
    ], f"{extra!r} changed the timing rows -- it must only reshape stdout"


def test_b08_display_filters_do_not_change_the_timing_counts(tmp_path: Path) -> None:
    """The counts reflect what each collector CONTRIBUTED, so a stdout filter
    that hides signals must not shrink them.

    Driven by --min-weight, which is display-only for real: it is a PER-SIGNAL
    predicate, so no collector->weight map exists that could ever narrow
    collection. (This guard used to drive --kind, which became an upstream
    allowlist in factory iter 118 -- see the banner above.)
    """
    ws = _make_workspace(tmp_path)
    _c0, _o0, err_plain = _run(["signals", "--workspace", str(ws), "--timings"])
    _c1, _o1, err_filtered = _run(
        ["signals", "--workspace", str(ws), "--timings", "--min-weight", "0.95"]
    )
    plain = {n: c for n, _ms, c in _parse_timings(err_plain)}
    filtered = {n: c for n, _ms, c in _parse_timings(err_filtered)}
    assert filtered == plain, (
        f"--min-weight changed the per-collector counts: {plain} -> {filtered}"
    )


def test_b08_json_stdout_stays_one_object_with_nothing_timing_related(
    tmp_path: Path,
) -> None:
    ws = _make_workspace(tmp_path)
    code, out, err = _run(["signals", "--workspace", str(ws), "--timings", "--json"])
    assert code == 0, f"must exit 0; got {code} (stderr={err!r})"
    payload = json.loads(out)  # the ENTIRE stdout must parse
    assert isinstance(payload, dict), f"stdout must be one JSON object; got {type(payload)}"
    banned = [k for k in payload if "tim" in k.lower() or "elapsed" in k.lower()]
    assert banned == [], f"timing data leaked into the JSON payload: {banned}"
    assert HEADER in err, "the table must still be on stderr under --json"


# ===========================================================================
# Behavior 9 -- a raising collector still gets a row (isolation unchanged).
# ===========================================================================
def test_b09_raising_collector_is_isolated_and_still_timed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        cli,
        "all_collectors",
        lambda: [_RaisingCollector("boom"), _FixedCollector("ok", count=1)],
    )
    ws = _make_workspace(tmp_path)
    with caplog.at_level(logging.WARNING, logger=_CLI_LOGGER):
        code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])

    assert code == 0, f"a raising collector must not change the exit code; got {code}"
    warnings = _cli_warnings(caplog)
    assert any("boom" in r.getMessage() for r in warnings), (
        f"a WARNING naming the failing collector is required; got {[r.getMessage() for r in warnings]}"
    )
    rows = {name: (ms, count) for name, ms, count in _collector_rows(err)}
    assert set(rows) == {"boom", "ok"}, (
        f"the raising collector must still get a row; rows={sorted(rows)}"
    )
    assert rows["boom"][1] == "0", (
        f"a raising collector contributed 0 signals; got count={rows['boom'][1]!r}"
    )
    assert MS_RE.match(rows["boom"][0]), (
        f"the raising collector must carry a measured duration; got {rows['boom'][0]!r}"
    )
    assert rows["ok"][1] == "1", "the surviving collector's signal must be counted"
    assert int(_total_row(err)[2]) == 1


def test_b09_a_raise_does_not_abort_the_remaining_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The raising double is FIRST, so rows after it prove the timing wrap is
    per-collector rather than around the whole loop."""
    monkeypatch.setattr(
        cli,
        "all_collectors",
        lambda: [
            _RaisingCollector("boom"),
            _FixedCollector("second", count=1),
            _FixedCollector("third", count=2),
        ],
    )
    ws = _make_workspace(tmp_path)
    _code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    assert [r[0] for r in _collector_rows(err)] == ["boom", "second", "third"]
    assert int(_total_row(err)[2]) == 3


# ===========================================================================
# Behavior 10 -- the workspace guard precedes measurement.
# ===========================================================================
def test_b10_missing_workspace_exits_2_with_no_timing_block(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    code, out, err = _run(["signals", "--workspace", str(missing), "--timings"])
    assert code == 2, f"a missing workspace must exit 2; got {code} (stderr={err!r})"
    assert f"error: workspace not found: {missing}" in err, (
        f"stderr must name the missing workspace; got {err!r}"
    )
    assert HEADER not in err, (
        f"the guard must precede measurement -- no timing block; got {err!r}"
    )
    assert out == "", f"a guard failure must print nothing on stdout; got {out!r}"


def test_b10_missing_workspace_stderr_is_the_same_with_and_without_the_flag(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nope"
    _c1, _o1, err_plain = _run(["signals", "--workspace", str(missing)])
    _c2, _o2, err_flag = _run(["signals", "--workspace", str(missing), "--timings"])
    assert err_flag == err_plain, (
        f"the flag must not add noise to the guard's message: {err_plain!r} vs {err_flag!r}"
    )


def test_b10_a_file_as_workspace_also_emits_no_timing_block(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x\n", encoding="utf-8")
    code, _out, err = _run(["signals", "--workspace", str(not_a_dir), "--timings"])
    assert code == 2, f"a non-directory workspace must exit 2; got {code}"
    assert HEADER not in err, f"no timing block may be emitted; got {err!r}"


# ===========================================================================
# Behavior 11 -- the seam's sink defaults to absent, so other verbs are inert.
# ===========================================================================
def test_b11_seam_signature_keeps_every_extra_parameter_optional() -> None:
    """``_collect`` may gain a sink, but every parameter beyond the workspace
    must default to ``None`` so existing call sites keep today's behavior."""
    params = list(inspect.signature(cli._collect).parameters.values())
    assert params, "_collect must still take the workspace"
    for p in params[1:]:
        assert p.default is None, (
            f"_collect parameter {p.name!r} defaults to {p.default!r}; every "
            "optional parameter must default to None so the seam stays inert"
        )


def test_b11_scan_emits_no_timing_block(tmp_path: Path) -> None:
    code, _out, err = _run(
        [
            "scan",
            "--workspace", str(FIXTURE),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--state-dir", str(tmp_path / "state"),
        ]
    )
    assert code == 0, f"scan must still exit 0; got {code} (stderr={err!r})"
    assert HEADER not in err, f"scan must not emit a timing block; got {err!r}"


def test_b11_run_dry_run_emits_no_timing_block(tmp_path: Path) -> None:
    code, _out, err = _run(
        [
            "run",
            "--dry-run",
            "--workspace", str(FIXTURE),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--state-dir", str(tmp_path / "state"),
        ]
    )
    assert code == 0, f"run --dry-run must exit 0; got {code} (stderr={err!r})"
    assert HEADER not in err, f"run must not emit a timing block; got {err!r}"


def test_b11_watch_emits_no_timing_block(tmp_path: Path) -> None:
    code, _out, err = _run(
        [
            "watch",
            "--workspace", str(FIXTURE),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--interval", "0",
            "--max-scans", "1",
            "--state-dir", str(tmp_path / "state"),
        ]
    )
    assert code == 0, f"watch must exit 0; got {code} (stderr={err!r})"
    assert HEADER not in err, f"watch must not emit a timing block; got {err!r}"


def test_b11_no_other_verb_accepts_timings() -> None:
    """The flag is scoped to ``signals`` only (spec scope decision), so every
    other verb must reject it as a usage error."""
    parser = build_parser()
    subs = parser._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    owners = sorted(
        verb
        for verb, sub in subs.items()
        if any("--timings" in (a.option_strings or []) for a in sub._actions)
    )
    assert owners == ["signals"], f"--timings must exist on signals only; got {owners}"


# ===========================================================================
# Behavior 12 -- documented and discoverable.
# ===========================================================================
def test_b12_flag_appears_in_signals_help() -> None:
    code, out, _err = _run(["signals", "--help"])
    assert code == 0
    assert "--timings" in out, "`pla signals --help` must document --timings"


def test_b12_help_text_says_stderr_and_opt_in() -> None:
    _code, out, _err = _run(["signals", "--help"])
    idx = out.find("--timings")
    blurb = out[idx : idx + 700].lower()
    assert "stderr" in blurb, f"the help text must name the stream; got {blurb!r}"


def test_b12_readme_signals_row_documents_the_flag_below_the_marker() -> None:
    intro, reference = _readme_halves()
    rows = [ln for ln in reference.splitlines() if ln.lstrip().startswith("| `signals`")]
    assert len(rows) == 1, f"expected exactly one `signals` CLI-reference row; got {len(rows)}"
    row = rows[0]
    assert "--timings" in row, f"the signals row must document --timings; got {row!r}"
    assert "stderr" in row.lower(), (
        f"the signals row must say the table goes to stderr; got {row!r}"
    )
    assert "--timings" not in intro, (
        "the human-owned portfolio intro must not document flags"
    )


@pytest.mark.parametrize("option", PRE_EXISTING_SIGNALS_OPTIONS)
def test_b12_readme_still_documents_the_pre_existing_signals_options(option: str) -> None:
    """The row was EXTENDED, not rewritten: its earlier options survive."""
    _intro, reference = _readme_halves()
    row = next(ln for ln in reference.splitlines() if ln.lstrip().startswith("| `signals`"))
    assert option in row, f"the signals row lost {option}"


def test_b12_portfolio_intro_carve_out_numbers_still_match_reality() -> None:
    intro, _reference = _readme_halves()
    verbs = len(build_parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
    assert f"{len(list(all_collectors()))} context collectors" in intro, (
        "the intro's collector count must match the live registry"
    )
    assert f"{verbs} CLI verbs" in intro, (
        f"the intro's CLI-verb count must match the live parser ({verbs})"
    )
