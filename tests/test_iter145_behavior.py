"""Black-box behavior tests for factory iteration 145 (foundry state iter-138) ---
``pla signals --fail-over N``, a COUNT-BUDGET exit gate: exit 5 when the number of
REPORTED signals is strictly greater than the non-negative integer budget N,
announced as exactly one ``gate:`` line on stderr.

This is the THIRD ratchet on the ``signals`` gate (after ``--fail-on-kind``'s
presence gate and ``--baseline``'s instance ratchet) and the first one with no state
file, so the two things these tests pin hardest are the two ways a count gate goes
wrong in someone else's CI: (a) the boundary --- ``count == N`` must exit 0 and only
``N + 1`` may fail, asserted from BOTH sides plus one step beyond each; and (b) the
gate may never disagree with the listing the same run printed, asserted as a relation
between the exit status and the ``--json`` row count across every filter the verb
offers, not as a hardcoded pair of numbers.

ISOLATION CONTRACT (honored): every assertion below is written against THIS
iteration's spec (``pm.md`` "Expected Behaviors" 1-12) and drives only public
surfaces --- the ``pla`` CLI through ``cli.main(argv) -> int``, its rendered
``--help``, and the two git-TRACKED human-facing documents the acceptance criteria
name (``README.md``, ``ROADMAP.md``).  **No file under ``src/`` was read, no engineer
/ reviewer / fix note was read, and no ``git diff`` was consulted.**

Fully offline and deterministic: no network, no LLM provider, every workspace fixture
under ``tmp_path``, no ``git`` subprocess of its own, and NO DURATION IS ASSERTED
ANYWHERE (roadmap row #129's standing constraint) --- the ``--timings`` cases assert
only the PRESENCE and ORDER of the trailer's lines, never a number in them.

NO COUNT LITERAL (deliberate; the acceptance criteria forbid one and
``test_iter106_behavior.py``'s docstring sets the precedent): the fixture's signal
count is never written down here.  Every budget is derived at run time from the
product's own ``--json`` listing, so no collector's future yield can make this module
lie, and registry/flag coverage is asserted by NAME MEMBERSHIP.

FRESH-CLONE SAFETY: the only files read outside ``tmp_path`` are ``README.md`` and
``ROADMAP.md``, both git-tracked, and neither is mutated.  No test here depends on
gitignored local state, on the repository directory's basename, or on this workspace
being a git repository (the fixture workspaces deliberately are not).

AMBIGUITY NOTES (PM feedback, reproduced in ``tester.md``):

* Behavior 2 says the gate line is printed "after the stdout view and after any
  ``--timings`` trailer".  Interleaving between two different streams is not
  observable from a captured pair of buffers, so the durable oracle used here is the
  half that is: the gate line is the LAST line of stderr, every ``--timings`` trailer
  line precedes it, and stdout is byte-identical to the un-armed run (so the whole
  view was still rendered).
* Behavior 5 says a negative budget scans nothing.  "Nothing was scanned" is
  asserted through the one surface that reports whether collection ran --- with
  ``--timings`` also armed, a rejected budget prints NO collector-timings trailer ---
  plus empty stdout on the default and ``--json`` renderers.
* Behavior 8's "exactly ONE JSON object" is asserted with ``raw_decode``, which
  proves the buffer holds one document and nothing but whitespace after it; a bare
  ``json.loads`` would also accept a document followed by nothing it could see.
"""

from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from proactive_loop import cli

_REPO = Path(__file__).resolve().parents[1]

# The exact stderr line the spec pins, as a shape -- the two numbers are captured and
# checked against the run's own listing rather than written down.
_FAIL_OVER_LINE = re.compile(r"^gate: fail-over tripped -- count=(\d+) budget=(\d+)$")
# The sibling gate's pinned text, behavior 11's regression oracle.
_FAIL_ON_KIND_LINE = re.compile(r"^gate: fail-on-kind tripped -- ([a-z_]+)=(\d+)$")

_PRESENT_KIND = "todo"  # emitted by the fixture below
_ABSENT_KIND = "merge_conflict"  # a registered kind the fixture cannot emit
_TODO_COLLECTOR = "todos"
_EMPTY_MARKER = "(no signals collected)\n"


def _cli(argv: list[str]) -> tuple[int, str, str]:
    """Run the front door in-process; return (exit code, stdout, stderr).

    argparse usage errors raise ``SystemExit``; they are normalized to their exit code
    so a usage error, a clean run and a tripped gate are all observed through one seam.
    """
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
    except SystemExit as exc:  # `parser.error` / a `type=` callable rejection
        raw = exc.code
        code = 0 if raw is None else raw if isinstance(raw, int) else 2
    return code, out.getvalue(), err.getvalue()


def _signals(ws: Path, *extra: str) -> tuple[int, str, str]:
    return _cli(["signals", "--workspace", str(ws), *extra])


def _rows(ws: Path, *extra: str) -> list[dict]:
    """The REPORTED signal list, read off the product's own --json surface."""
    code, out, err = _signals(ws, "--json", *extra)
    assert code == 0, f"exit {code}; stderr={err!r}"
    return list(json.loads(out)["signals"])


def _count(ws: Path, *extra: str) -> int:
    return len(_rows(ws, *extra))


def _gate_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if ln.startswith("gate:")]


def _build(root: Path) -> None:
    """A deterministic workspace reporting several signals of several kinds."""
    (root / "sub").mkdir()
    (root / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "keep.py").write_text("k = 5\n", encoding="utf-8")
    filler = "\n".join(f"line {i}" for i in range(1, 12))
    (root / "notes.md").write_text(
        filler + "\n- TODO: alpha here\n- TODO: beta here\n- TODO: gamma here\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("iter145_main")
    _build(root)
    return root


@pytest.fixture(scope="module")
def total(ws: Path) -> int:
    n = len(_rows(ws))
    assert n >= 4, f"fixture precondition: the workspace must report signals, got {n}"
    return n


# ======================================================================================
# Behavior 1 -- exit 5 iff the reported count is STRICTLY greater than the budget
# ======================================================================================
def test_b01_boundary_is_strictly_greater_than(ws: Path, total: int) -> None:
    assert _signals(ws, "--fail-over", str(total))[0] == 0, "count == N must exit 0"
    assert _signals(ws, "--fail-over", str(total - 1))[0] == 5, "count == N+1 must exit 5"


def test_b01_one_step_beyond_the_boundary_each_way(ws: Path, total: int) -> None:
    assert _signals(ws, "--fail-over", str(total + 1))[0] == 0, "count < N must exit 0"
    assert _signals(ws, "--fail-over", str(total - 2))[0] == 5, "count > N must exit 5"


def test_b01_a_generous_budget_never_trips(ws: Path, total: int) -> None:
    code, out, err = _signals(ws, "--fail-over", str(total * 10))
    assert (code, _gate_lines(err)) == (0, [])


# ======================================================================================
# Behavior 2 -- exactly one stderr line, exact text, no `error:` prefix, printed last
# ======================================================================================
def test_b02_gate_line_text_is_exactly_as_specified(ws: Path, total: int) -> None:
    budget = total - 1
    code, _out, err = _signals(ws, "--fail-over", str(budget))
    assert code == 5
    assert err == f"gate: fail-over tripped -- count={total} budget={budget}\n"


def test_b02_the_reported_numbers_are_the_runs_own_count_and_budget(
    ws: Path, total: int
) -> None:
    code, _out, err = _signals(ws, "--fail-over", "0")
    assert code == 5
    match = _FAIL_OVER_LINE.match(err.strip())
    assert match is not None, f"stderr did not match the pinned shape: {err!r}"
    assert (int(match.group(1)), int(match.group(2))) == (total, 0)


def test_b02_gate_line_carries_no_error_prefix(ws: Path, total: int) -> None:
    _code, _out, err = _signals(ws, "--fail-over", str(total - 1))
    assert "error:" not in err
    assert not err.lstrip().startswith("error")


def test_b02_exactly_one_line_is_added_to_stderr(ws: Path, total: int) -> None:
    _c1, _o1, plain = _signals(ws, "--fail-over", str(total))
    _c2, _o2, tripped = _signals(ws, "--fail-over", str(total - 1))
    added = tripped.splitlines()[len(plain.splitlines()) :]
    assert len(added) == 1, f"expected one added stderr line, got {added!r}"
    assert _FAIL_OVER_LINE.match(added[0]) is not None


def test_b02_gate_line_follows_the_whole_timings_trailer(ws: Path, total: int) -> None:
    _c, _o, plain = _signals(ws, "--timings")
    code, _out, err = _signals(ws, "--timings", "--fail-over", str(total - 1))
    assert code == 5
    lines = err.splitlines()
    assert _FAIL_OVER_LINE.match(lines[-1]) is not None, f"gate line not last: {lines[-1]!r}"
    # Compare the trailer by SHAPE, never by its measured milliseconds (row #129):
    # same line count, same leading label on every line, in the same order.
    labels = [ln.split()[0] for ln in lines[:-1]]
    assert labels == [ln.split()[0] for ln in plain.splitlines()], (
        "the timings trailer must be untouched apart from the appended gate line"
    )
    assert any("collector timings" in ln for ln in lines[:-1]), "trailer must still print"


def test_b02_the_whole_stdout_view_is_still_rendered_on_a_trip(
    ws: Path, total: int
) -> None:
    _c1, plain, _e1 = _signals(ws)
    _c2, tripped, _e2 = _signals(ws, "--fail-over", str(total - 1))
    assert tripped == plain and tripped.strip() != ""


# ======================================================================================
# Behavior 3 -- no trip, no line, exit 0
# ======================================================================================
@pytest.mark.parametrize("extra", [(), ("--json",), ("--summary",), ("--timings",)])
def test_b03_an_untripped_gate_is_silent(
    ws: Path, total: int, extra: tuple[str, ...]
) -> None:
    code, _out, err = _signals(ws, *extra, "--fail-over", str(total))
    assert code == 0
    assert _gate_lines(err) == []
    assert "fail-over" not in err


# ======================================================================================
# Behavior 4 -- `--fail-over 0` is a legitimate strict mode
# ======================================================================================
def test_b04_zero_budget_trips_on_any_reported_signal(ws: Path, total: int) -> None:
    code, _out, err = _signals(ws, "--fail-over", "0")
    assert code == 5
    assert err == f"gate: fail-over tripped -- count={total} budget=0\n"


def test_b04_zero_budget_exits_zero_when_a_narrowing_hides_everything(ws: Path) -> None:
    narrowing = ("--min-weight", "2")
    assert _count(ws, *narrowing) == 0, "precondition: this narrowing must hide all"
    code, out, err = _signals(ws, *narrowing, "--fail-over", "0")
    assert (code, out, _gate_lines(err)) == (0, _EMPTY_MARKER, [])


def test_b04_zero_budget_exits_zero_on_an_empty_workspace(tmp_path: Path) -> None:
    empty = tmp_path / "bare"
    empty.mkdir()
    if _count(empty) == 0:  # a bare dir may still report repo-level signals
        code, _out, err = _signals(empty, "--fail-over", "0")
        assert (code, _gate_lines(err)) == (0, [])


# ======================================================================================
# Behaviors 5 and 6 -- a negative or non-integer budget is a usage error (exit 2)
# ======================================================================================
@pytest.mark.parametrize("budget", ["-1", "-30", "abc", "1.5", "", "3x", "0x1"])
def test_b05_b06_a_rejected_budget_exits_two_with_empty_stdout(
    ws: Path, budget: str
) -> None:
    code, out, err = _signals(ws, "--fail-over", budget)
    assert code == 2, f"budget {budget!r} should be a usage error"
    assert out == ""
    assert "--fail-over" in err
    assert _gate_lines(err) == []


@pytest.mark.parametrize("budget", ["-1", "abc"])
def test_b05_a_rejected_budget_scans_nothing(ws: Path, budget: str) -> None:
    """The observable proof: no collector-timings trailer, so no collection ran."""
    code, out, err = _signals(ws, "--timings", "--fail-over", budget)
    assert (code, out) == (2, "")
    assert "collector timings" not in err


@pytest.mark.parametrize("budget", ["-1", "abc"])
def test_b05_a_rejected_budget_emits_no_json_document(ws: Path, budget: str) -> None:
    code, out, _err = _signals(ws, "--json", "--fail-over", budget)
    assert (code, out) == (2, "")


def test_b06_zero_is_accepted_where_a_negative_is_not(ws: Path) -> None:
    """Guards the `_positive_int` mistake: 0 is legal, -1 is not."""
    assert _signals(ws, "--fail-over", "0")[0] == 5
    assert _signals(ws, "--fail-over", "-1")[0] == 2


# ======================================================================================
# Behavior 7 -- the gate counts the list the view rendered (logical AND with filters)
# ======================================================================================
def _baseline(path: Path, rows: list[dict]) -> str:
    path.write_text(
        json.dumps({"workspace_root": ".", "signals": rows}), encoding="utf-8"
    )
    return str(path)


def test_b07_a_narrowing_filter_lowers_the_count_and_can_disarm_the_gate(
    ws: Path, total: int
) -> None:
    narrowed = _count(ws, "--kind", _PRESENT_KIND)
    assert 0 < narrowed < total - 1, "precondition: --kind must narrow the fixture"
    budget = narrowed
    assert _signals(ws, "--fail-over", str(budget))[0] == 5, "unfiltered must trip"
    code, _out, err = _signals(ws, "--kind", _PRESENT_KIND, "--fail-over", str(budget))
    assert (code, _gate_lines(err)) == (0, []), "the narrowed view must disarm it"


@pytest.mark.parametrize(
    "filters",
    [
        (),
        ("--kind", _PRESENT_KIND),
        ("--min-weight", "0.95"),
        ("--min-weight", "2"),
        ("--collector", _TODO_COLLECTOR),
        ("--exclude-path", "notes.md"),
        ("--exclude-path", "*"),
        ("--kind", _PRESENT_KIND, "--min-weight", "0.5"),
    ],
)
@pytest.mark.parametrize("budget", ["0", "1", "2"])
def test_b07_exit_status_can_never_disagree_with_the_printed_listing(
    ws: Path, filters: tuple[str, ...], budget: str
) -> None:
    reported = _count(ws, *filters)
    code, _out, err = _signals(ws, *filters, "--fail-over", budget)
    should_trip = reported > int(budget)
    assert code == (5 if should_trip else 0), (
        f"filters={filters} budget={budget} reported={reported}"
    )
    assert bool(_gate_lines(err)) is should_trip


def test_b07_composes_with_the_baseline_ratchet(ws: Path, tmp_path: Path) -> None:
    bl = _baseline(tmp_path / "base.json", _rows(ws))
    assert _count(ws, "--baseline", bl) == 0, "precondition: a full baseline hides all"
    code, _out, err = _signals(ws, "--baseline", bl, "--fail-over", "0")
    assert (code, _gate_lines(err)) == (0, [])


def test_b07_the_gate_counts_rows_not_kinds(ws: Path) -> None:
    """`--summary` prints a rollup, but the budget is still counted over signals."""
    reported = _count(ws, "--kind", _PRESENT_KIND)
    code, _out, err = _signals(
        ws, "--summary", "--kind", _PRESENT_KIND, "--fail-over", str(reported - 1)
    )
    assert code == 5
    match = _FAIL_OVER_LINE.match(err.strip())
    assert match is not None and int(match.group(1)) == reported


# ======================================================================================
# Behavior 8 -- stdout is byte-identical, and a tripped --json run is still one object
# ======================================================================================
@pytest.mark.parametrize(
    "surface", [(), ("--json",), ("--summary",), ("--summary", "--json")]
)
def test_b08_stdout_is_byte_identical_with_and_without_the_gate(
    ws: Path, total: int, surface: tuple[str, ...]
) -> None:
    _c0, plain, _e0 = _signals(ws, *surface)
    _c1, tripped, _e1 = _signals(ws, *surface, "--fail-over", "0")
    _c2, untripped, _e2 = _signals(ws, *surface, "--fail-over", str(total))
    assert tripped == plain
    assert untripped == plain


def test_b08_a_tripped_json_run_emits_exactly_one_json_object(ws: Path) -> None:
    code, out, _err = _signals(ws, "--json", "--fail-over", "0")
    assert code == 5
    doc, end = json.JSONDecoder().raw_decode(out)
    assert isinstance(doc, dict)
    assert out[end:].strip() == "", "stdout held more than one JSON document"
    assert "signals" in doc


# ======================================================================================
# Behavior 9 -- when both gates trip, one line prints and it is the fail-on-kind one
# ======================================================================================
def test_b09_both_gates_tripping_prints_only_the_fail_on_kind_line(ws: Path) -> None:
    code, _out, err = _signals(
        ws, "--fail-on-kind", _PRESENT_KIND, "--fail-over", "0"
    )
    assert code == 5
    lines = _gate_lines(err)
    assert len(lines) == 1, f"expected exactly one gate line, got {lines!r}"
    match = _FAIL_ON_KIND_LINE.match(lines[0])
    assert match is not None and match.group(1) == _PRESENT_KIND
    assert "fail-over" not in err


def test_b09_only_the_count_budget_tripping_prints_the_fail_over_line(
    ws: Path, total: int
) -> None:
    code, _out, err = _signals(ws, "--fail-on-kind", _ABSENT_KIND, "--fail-over", "0")
    assert code == 5
    lines = _gate_lines(err)
    assert len(lines) == 1
    match = _FAIL_OVER_LINE.match(lines[0])
    assert match is not None and (int(match.group(1)), int(match.group(2))) == (total, 0)


def test_b09_only_the_kind_gate_tripping_is_unchanged(ws: Path, total: int) -> None:
    code, _out, err = _signals(
        ws, "--fail-on-kind", _PRESENT_KIND, "--fail-over", str(total)
    )
    assert code == 5
    lines = _gate_lines(err)
    assert len(lines) == 1 and _FAIL_ON_KIND_LINE.match(lines[0]) is not None


def test_b09_neither_gate_tripping_exits_zero_silently(ws: Path, total: int) -> None:
    code, _out, err = _signals(
        ws, "--fail-on-kind", _ABSENT_KIND, "--fail-over", str(total)
    )
    assert (code, _gate_lines(err)) == (0, [])


# ======================================================================================
# Behavior 10 -- `--kind K --fail-over N` is accepted (the deliberate asymmetry)
# ======================================================================================
def test_b10_kind_plus_fail_over_is_not_a_usage_error(ws: Path) -> None:
    code, _out, err = _signals(ws, "--kind", _PRESENT_KIND, "--fail-over", "0")
    assert code != 2, f"the pair must be accepted; stderr={err!r}"
    assert code == 5


def test_b10_the_pair_gates_on_the_narrowed_count(ws: Path) -> None:
    narrowed = _count(ws, "--kind", _PRESENT_KIND)
    code, _out, err = _signals(ws, "--kind", _PRESENT_KIND, "--fail-over", "0")
    match = _FAIL_OVER_LINE.match(err.strip())
    assert code == 5 and match is not None
    assert int(match.group(1)) == narrowed, "the gate must count the narrowed view"


def test_b10_control_the_unreachable_kind_pair_is_still_a_usage_error(ws: Path) -> None:
    """The asymmetry only means something if the sibling still refuses."""
    code, out, err = _signals(ws, "--kind", _PRESENT_KIND, "--fail-on-kind", _ABSENT_KIND)
    assert (code, out) == (2, "")
    assert "--fail-on-kind" in err


def test_b10_an_absent_kind_narrowing_with_a_zero_budget_exits_zero(ws: Path) -> None:
    assert _count(ws, "--kind", _ABSENT_KIND) == 0, "precondition: kind must be absent"
    code, _out, err = _signals(ws, "--kind", _ABSENT_KIND, "--fail-over", "0")
    assert (code, _gate_lines(err)) == (0, [])


# ======================================================================================
# Behavior 11 -- with the flag absent, nothing about today's behavior moved
# ======================================================================================
def test_b11_a_plain_run_is_unchanged_and_mentions_no_new_gate(ws: Path) -> None:
    code, out, err = _signals(ws)
    assert code == 0
    assert out.strip() != ""
    assert err == ""


def test_b11_the_sibling_gate_line_text_is_still_pinned(ws: Path) -> None:
    kind_count = _count(ws, "--kind", _PRESENT_KIND)
    code, _out, err = _signals(ws, "--fail-on-kind", _PRESENT_KIND)
    assert code == 5
    assert err == f"gate: fail-on-kind tripped -- {_PRESENT_KIND}={kind_count}\n"


@pytest.mark.parametrize(
    "extra",
    [
        (),
        ("--json",),
        ("--summary",),
        ("--kind", _PRESENT_KIND),
        ("--min-weight", "0.9"),
        ("--exclude-path", "*.md"),
    ],
)
def test_b11_every_gateless_invocation_still_exits_zero(
    ws: Path, extra: tuple[str, ...]
) -> None:
    code, _out, err = _signals(ws, *extra)
    assert code == 0
    assert "fail-over" not in err


# ======================================================================================
# Behavior 12 -- the flag is documented (help + the single README CLI-reference row)
# ======================================================================================
def _help_text() -> str:
    code, out, _err = _cli(["signals", "--help"])
    assert code == 0
    return " ".join(out.split())  # argparse wraps; compare on normalized whitespace


def test_b12_help_declares_the_flag_in_the_usage_line_and_the_options_block() -> None:
    text = _help_text()
    assert "[--fail-over N]" in text
    assert "--fail-over N " in text.split("options:", 1)[1]


def test_b12_help_states_the_strict_boundary_and_the_exit_code() -> None:
    text = _help_text().lower()
    assert "strictly greater" in text
    # "5" alone would be trivially true anywhere in the help; pin the phrasing.
    assert "exit 5" in text or "exits 5" in text


def test_b12_help_states_the_one_stderr_line_and_its_shape() -> None:
    text = _help_text()
    assert "gate: fail-over tripped -- count=<count> budget=<N>" in text
    assert "stderr" in text.lower()


def test_b12_help_states_composition_and_the_kind_asymmetry() -> None:
    text = _help_text()
    lowered = text.lower()
    assert "--kind" in text
    assert "not a usage error" in lowered or "not** a usage error" in lowered
    assert "compose" in lowered or "logical and" in lowered


def test_b12_the_single_readme_signals_row_documents_the_flag() -> None:
    rows = [
        line
        for line in (_REPO / "README.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| `signals` |")
    ]
    assert len(rows) == 1, f"expected exactly one `signals` CLI-reference row, got {len(rows)}"
    assert "--fail-over" in rows[0]
    assert "strictly greater" in rows[0]


def test_b12_the_roadmap_records_the_row_as_selected_for_this_iteration() -> None:
    """Row #168 must stay RECORDED in `ROADMAP.md` -- as an index row while it is
    live, or as a Done-ledger line once the PM retires it to `ROADMAP_ARCHIVE.md`.

    WHY two accepted shapes: `ROADMAP.md` is a required-reading file that the PM
    rewrites every iteration, so it gets COMPACTED whenever it nears the operator's
    40,000-char stall threshold, and shipped rows are moved out. The roadmap's own
    contract states the invariant that survives that move -- a shipped row "keeps a
    one-line record in the Done ledger at the foot of this file, so `grep` still
    answers 'did we ship that?'". Pinning only the index row made this oracle
    assert a TRANSIENT pre-retirement shape, so routine maintenance broke it (row
    #168 was retired in factory iter 151). Both shapes still fail CLOSED if the row
    stops being recorded at all, and every record must still name the flag and the
    iteration that sourced it, so the provenance claim is unweakened.
    """
    lines = (_REPO / "ROADMAP.md").read_text(encoding="utf-8").splitlines()
    index_rows = [line for line in lines if line.startswith("| 168 ")]
    ledger_rows = [line for line in lines if line.startswith("- #168 ")]
    assert len(index_rows) <= 1, f"at most one index row for #168, got {index_rows!r}"
    assert len(ledger_rows) <= 1, f"at most one Done-ledger line for #168, got {ledger_rows!r}"
    records = index_rows + ledger_rows
    assert records, "roadmap row #168 must be recorded (index row or Done-ledger line)"
    for record in records:
        assert "fail-over" in record, f"the #168 record must name the flag; got {record!r}"
        assert "iter-138" in record or "iter 138" in record, (
            f"the #168 record must name the sourcing iteration; got {record!r}"
        )
