"""Behavior tests for state-dir iteration 111 (ships as commit-seq ``factory iter 118``).

Feature under test: ``pla signals --kind K`` is now an UPSTREAM collector
allowlist, not a display-only post-filter. Asking for one kind must do a
kind-sized amount of perception work while printing byte-identical output.

THE TWO ORACLES
"Which collectors RAN" is read off the ``--timings`` table on STDERR (one row
per collector that ran, plus a trailing ``TOTAL`` row) -- the same oracle
iteration 112 shipped. "What the user sees" is STDOUT. Every narrowing claim
here is therefore a stderr row-set claim, and every preservation claim is a
stdout claim; the two never share an assertion, so a change that speeds up
perception by dropping a signal cannot pass.

WHY THE PRESERVATION TESTS COMPARE ADJACENT RUNS
``recent_file`` weights are derived from ``time.time()`` (an age ratio), so two
runs of the SAME command minutes apart do not produce byte-identical stdout.
Every full-vs-narrowed comparison in this module therefore takes both captures
back to back inside one test, and behavior 3 additionally runs a full-vs-full
control so a clock-drift mismatch can never be reported as a narrowing bug.

Isolation: black-box. Seams used are (a) ``proactive_loop.cli.main`` driven with
argv, (b) the public registries ``proactive_loop.collectors.SIGNAL_KINDS`` /
``all_collectors()``, (c) the two module-level maps the spec's behavior 10 names
directly (``cli._COLLECTOR_KINDS`` and the derived ``cli._KIND_COLLECTORS``),
(d) the live ``--help`` text, and (e) ``README.md`` as text. No implementation
source was read while writing this file; no engineer, reviewer or fix note was
opened.

Offline and cap-cheap: no network, no API keys, no subprocesses; filesystem
work is limited to ``tmp_path`` workspaces and reading ``README.md``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
from pathlib import Path

import pytest

from proactive_loop import cli
from proactive_loop.cli import build_parser, main
from proactive_loop.collectors import SIGNAL_KINDS, all_collectors

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"

# Iteration 112's literal timing-block markers -- reused, not redefined.
HEADER = "collector timings (ms):"
TOTAL = "TOTAL"

MS_RE = re.compile(r"^\d+\.\d{2}$")

# Behavior 11 drives a value the parser MUST reject. It is bound to a name
# rather than written inline because ``test_iter108_behavior.py``'s fail-closed
# corpus scan reads any literal written directly after a literal "--kind" as an
# intended --kind VALUE and requires it to be a live SIGNAL_KINDS member; the
# repo convention for a deliberately-invalid value is exactly this indirection.
# It is the COLLECTOR name whose kind is the singular `todo` -- the most likely
# real user typo, and a value that must not be quietly accepted as an alias.
_UNKNOWN_KIND = "todos"


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

    Fail-closed: a missing header raises rather than returning ``[]``, so a run
    that emitted no table cannot satisfy a row-count assertion vacuously.
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
    """Rows excluding the trailing ``TOTAL`` row (may legitimately be empty)."""
    rows = _parse_timings(err)
    assert rows[-1][0] == TOTAL, (
        f"the last row's name field must be {TOTAL!r}; got {rows[-1][0]!r}"
    )
    return rows[:-1]


def _ran(err: str) -> list[str]:
    """Names of the collectors that RAN, in table order."""
    return [name for name, _ms, _count in _collector_rows(err)]


def _registry_names() -> list[str]:
    return [c.name for c in all_collectors()]


def _make_workspace(tmp_path: Path) -> Path:
    """A workspace several DIFFERENT collectors perceive.

    Narrowing tests are vacuous against an empty workspace, so this plants a
    TODO comment, a notes file, a source file with no tests, a lockfile and a
    CI config -- enough that the full run and the narrowed runs differ.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("# TODO: fix this\nx = 1\n", encoding="utf-8")
    (ws / "b.py").write_text("# FIXME: later\ny = 2\n", encoding="utf-8")
    (ws / "NOTES.md").write_text("- idea one\n- [ ] idea two\n", encoding="utf-8")
    (ws / "requirements.txt").write_text("pydantic==2.9.0\n", encoding="utf-8")
    (ws / "uv.lock").write_text("# lock\n", encoding="utf-8")
    (ws / ".github").mkdir()
    (ws / ".github" / "workflows").mkdir()
    (ws / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    return ws


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return _make_workspace(tmp_path)


def _emitter_of(kind: str) -> str:
    """The collector ``pla collectors --kind K --json`` names as K's emitter."""
    code, out, _err = _run(["collectors", "--kind", kind, "--json"])
    assert code == 0, f"collectors --kind {kind} --json exited {code}"
    entries = json.loads(out)["collectors"]
    assert len(entries) == 1, (
        f"kind {kind!r} must have exactly one emitting collector; got {entries!r}"
    )
    return str(entries[0]["name"])


# ---------------------------------------------------------------------------
# Behavior 1 -- the headline: --kind todo runs only `todos`.
# ---------------------------------------------------------------------------
def test_b01_kind_todo_runs_only_the_todos_collector(ws: Path) -> None:
    code, out, err = _run(
        ["signals", "--workspace", str(ws), "--kind", "todo", "--timings"]
    )
    assert code == 0, f"exit {code}; stderr={err!r}"
    assert _ran(err) == ["todos"], (
        "--kind todo must narrow collection to the single collector that emits "
        f"`todo`; the timings table says these ran: {_ran(err)!r}"
    )
    assert out.strip(), "the narrowed run must still print the todo signals"


# ---------------------------------------------------------------------------
# Behavior 2 -- every kind narrows to its own emitter.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", SIGNAL_KINDS)
def test_b02_every_kind_narrows_to_its_declared_emitter(ws: Path, kind: str) -> None:
    expected = _emitter_of(kind)
    code, _out, err = _run(
        ["signals", "--workspace", str(ws), "--kind", kind, "--timings"]
    )
    assert code == 0, f"--kind {kind} exited {code}; stderr={err!r}"
    assert _ran(err) == [expected], (
        f"--kind {kind} must run exactly [{expected!r}] (the collector the "
        f"`collectors --kind` reverse lookup names); ran {_ran(err)!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- the default path still perceives everything.
# ---------------------------------------------------------------------------
def test_b05_default_path_still_runs_every_collector(ws: Path) -> None:
    code, _out, err = _run(["signals", "--workspace", str(ws), "--timings"])
    assert code == 0
    assert _ran(err) == _registry_names(), (
        "with no --kind and no --collector the run must still visit every "
        f"registered collector; ran {_ran(err)!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 10 -- the inverse map is DERIVED, and keyed to sets of names.
# ---------------------------------------------------------------------------
def test_b10_inverse_map_is_derived_from_the_forward_map() -> None:
    forward = cli._COLLECTOR_KINDS
    inverse = cli._KIND_COLLECTORS
    assert set(inverse) == set(forward.values()), (
        "_KIND_COLLECTORS must be the exact inverse of _COLLECTOR_KINDS, so a "
        "new collector cannot appear in one map and be missing from the other"
    )
    for kind, owners in inverse.items():
        assert not isinstance(owners, str), (
            f"_KIND_COLLECTORS[{kind!r}] must be a SET of collector names, not a "
            "single name, so a kind emitted by two collectors cannot silently "
            f"narrow to one; got {owners!r}"
        )
        assert set(owners), f"_KIND_COLLECTORS[{kind!r}] must not be empty"
    for name, kind in forward.items():
        assert name in inverse[kind], (
            f"{name!r} emits {kind!r} but is missing from that kind's owner set"
        )
        elsewhere = [k for k, v in inverse.items() if name in v]
        assert elsewhere == [kind], (
            f"{name!r} must appear in exactly one owner set; found in {elsewhere!r}"
        )


# ---------------------------------------------------------------------------
# Behavior 11 -- an unknown kind still fails CLOSED at parse time.
# ---------------------------------------------------------------------------
def test_b11_unknown_kind_still_fails_closed_before_any_collection(ws: Path) -> None:
    code, out, err = _run(
        ["signals", "--workspace", str(ws), "--kind", _UNKNOWN_KIND, "--timings"]
    )
    assert code == 2, f"a bogus --kind must exit 2, got {code}; stderr={err!r}"
    assert _UNKNOWN_KIND in err, "the parse error must name the rejected value"
    assert "todo" in err, "the parse error must list the accepted kinds"
    assert HEADER not in err, (
        "a rejected --kind must not have run any collection, so no timings "
        f"table may be printed; stderr={err!r}"
    )
    assert out == "", f"a parse error must print nothing on stdout; stdout={out!r}"


# ---------------------------------------------------------------------------
# Output-preservation helpers (behaviors 3, 4, 7, 9).
# ---------------------------------------------------------------------------
EMPTY_LISTING = "(no signals collected)\n"


def _kind_block(full_stdout: str, kind: str) -> str | None:
    """The contiguous ``## <kind> (N)`` block of a full human listing.

    ``None`` when the kind fired no signals, which is the case the narrowed run
    must render as the empty-listing sentinel rather than an empty group.
    """
    lines = full_stdout.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith(f"## {kind} (")), None
    )
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end]) + "\n"


# ---------------------------------------------------------------------------
# Behavior 3 -- stdout preservation: the per-signal listing.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", SIGNAL_KINDS)
def test_b03_json_listing_is_preserved_for_every_kind(ws: Path, kind: str) -> None:
    """Narrowing must not change WHAT is printed -- only what is computed.

    The two captures are taken back to back because ``recent_file`` weights are
    an age ratio off the wall clock; see the module docstring.
    """
    full_code, full_out, _ = _run(["signals", "--workspace", str(ws), "--json"])
    narrow_code, narrow_out, _ = _run(
        ["signals", "--workspace", str(ws), "--kind", kind, "--json"]
    )
    assert full_code == 0 and narrow_code == 0

    full = json.loads(full_out)
    narrow = json.loads(narrow_out)
    assert narrow["workspace_root"] == full["workspace_root"], (
        "narrowing must not change the reported workspace_root"
    )
    expected = [s for s in full["signals"] if s["kind"] == kind]
    assert narrow["signals"] == expected, (
        f"--kind {kind} must emit exactly the kind-{kind} signals of the full "
        "run, in the same order with identical field values"
    )


def test_b03_full_vs_full_control_is_stable(ws: Path) -> None:
    """Control for behavior 3: two adjacent FULL runs agree.

    Without this, a wall-clock-derived weight drifting between captures would
    be indistinguishable from a narrowing bug.
    """
    _, first, _ = _run(["signals", "--workspace", str(ws), "--json"])
    _, second, _ = _run(["signals", "--workspace", str(ws), "--json"])
    assert json.loads(first) == json.loads(second), (
        "two adjacent full runs must agree, otherwise the preservation tests "
        "cannot attribute a mismatch to narrowing"
    )


@pytest.mark.parametrize("kind", SIGNAL_KINDS)
def test_b03_human_listing_equals_the_full_runs_kind_block(ws: Path, kind: str) -> None:
    _, full_out, _ = _run(["signals", "--workspace", str(ws)])
    code, narrow_out, _ = _run(["signals", "--workspace", str(ws), "--kind", kind])
    assert code == 0
    block = _kind_block(full_out, kind)
    if block is None:
        assert narrow_out == EMPTY_LISTING, (
            f"kind {kind!r} fires no signals here, so the narrowed listing must "
            f"be the empty-listing sentinel; got {narrow_out!r}"
        )
    else:
        assert narrow_out == block, (
            f"--kind {kind} must print exactly the '## {kind} (N)' block of the "
            "full listing, verbatim and with no count trailer"
        )


# ---------------------------------------------------------------------------
# Behavior 4 -- stdout preservation: the --summary rollup.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", SIGNAL_KINDS)
def test_b04_summary_rollup_is_preserved_for_every_kind(ws: Path, kind: str) -> None:
    _, full_out, _ = _run(["signals", "--workspace", str(ws), "--summary", "--json"])
    code, narrow_out, err = _run(
        ["signals", "--workspace", str(ws), "--kind", kind, "--summary", "--json"]
    )
    assert code == 0, f"--kind {kind} --summary exited {code}; stderr={err!r}"
    full = json.loads(full_out)
    narrow = json.loads(narrow_out)
    expected_summary = {k: v for k, v in full["summary"].items() if k == kind}
    assert narrow["summary"] == expected_summary
    assert narrow["total"] == sum(expected_summary.values())
    assert narrow["workspace_root"] == full["workspace_root"]


def test_b04_a_kind_with_no_signals_is_an_empty_rollup_not_an_error(ws: Path) -> None:
    _, full_out, _ = _run(["signals", "--workspace", str(ws), "--summary", "--json"])
    fired = set(json.loads(full_out)["summary"])
    silent = [k for k in SIGNAL_KINDS if k not in fired]
    assert silent, "fixture must leave at least one kind silent for this test"
    for kind in silent:
        code, out, err = _run(
            ["signals", "--workspace", str(ws), "--kind", kind, "--summary", "--json"]
        )
        assert code == 0, f"a silent kind must exit 0, not error; got {code} {err!r}"
        payload = json.loads(out)
        assert payload["summary"] == {}
        assert payload["total"] == 0


# ---------------------------------------------------------------------------
# Behavior 6 -- a DISJOINT --collector/--kind pair is empty, not an error.
# ---------------------------------------------------------------------------
def test_b06_disjoint_intersection_runs_nothing_and_is_not_an_error(ws: Path) -> None:
    argv = ["signals", "--workspace", str(ws), "--collector", "notes", "--kind", "todo"]

    code, _out, err = _run([*argv, "--timings"])
    assert code == 0, f"a disjoint pair must not be a usage error; exit {code}"
    assert _ran(err) == [], (
        "an empty intersection must run ZERO collectors -- never silently "
        f"re-add one; ran {_ran(err)!r}"
    )
    total = _parse_timings(err)[-1]
    assert total == (TOTAL, "0.00", "0"), (
        f"the degenerate table must still print header + TOTAL 0.00 0; got {total!r}"
    )

    code, out, _ = _run([*argv, "--json"])
    assert code == 0
    assert json.loads(out)["signals"] == []

    code, out, _ = _run([*argv, "--summary", "--json"])
    assert code == 0
    payload = json.loads(out)
    assert payload["summary"] == {} and payload["total"] == 0

    code, out, _ = _run(argv)
    assert code == 0
    assert out == EMPTY_LISTING


# ---------------------------------------------------------------------------
# Behavior 7 -- an AGREEING --collector/--kind pair narrows once.
# ---------------------------------------------------------------------------
def test_b07_agreeing_intersection_runs_one_collector_and_prints_the_same(
    ws: Path,
) -> None:
    code, both_out, err = _run(
        [
            "signals",
            "--workspace",
            str(ws),
            "--collector",
            "todos",
            "--kind",
            "todo",
            "--timings",
        ]
    )
    _, kind_only_out, _ = _run(["signals", "--workspace", str(ws), "--kind", "todo"])
    assert code == 0
    assert _ran(err) == ["todos"]
    assert both_out == kind_only_out, (
        "an agreeing intersection must print exactly what --kind alone prints"
    )
    assert both_out != EMPTY_LISTING, "this pair must not be vacuously empty"


# ---------------------------------------------------------------------------
# Behavior 8 -- --min-weight composes, and stays display-only.
# ---------------------------------------------------------------------------
def test_b08_min_weight_composes_with_kind_and_still_narrows_collection(
    ws: Path,
) -> None:
    threshold = 0.9
    _, full_out, _ = _run(["signals", "--workspace", str(ws), "--json"])
    code, narrow_out, err = _run(
        [
            "signals",
            "--workspace",
            str(ws),
            "--kind",
            "todo",
            "--min-weight",
            str(threshold),
            "--json",
            "--timings",
        ]
    )
    assert code == 0, f"exit {code}; stderr={err!r}"
    expected = [
        s
        for s in json.loads(full_out)["signals"]
        if s["kind"] == "todo" and s["weight"] >= threshold
    ]
    assert expected, "fixture must have at least one todo signal above the threshold"
    assert json.loads(narrow_out)["signals"] == expected, (
        "--kind AND --min-weight must select the same set as filtering the full "
        "run by both predicates"
    )
    assert _ran(err) == ["todos"], (
        f"adding a display filter must not widen collection; ran {_ran(err)!r}"
    )


def test_b08_min_weight_alone_never_narrows_the_row_set(ws: Path) -> None:
    code, _out, err = _run(
        ["signals", "--workspace", str(ws), "--min-weight", "0.99", "--timings"]
    )
    assert code == 0
    assert _ran(err) == _registry_names(), (
        "--min-weight is a per-signal display filter with no collector mapping, "
        f"so it must never shrink the row set; ran {_ran(err)!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 9 -- narrowing fails OPEN (correct-but-slow beats fast-but-wrong).
# ---------------------------------------------------------------------------
def test_b09_a_kind_with_no_known_owner_runs_every_collector(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, expected_out, _ = _run(["signals", "--workspace", str(ws), "--kind", "todo"])

    orphaned = {**cli._KIND_COLLECTORS, "todo": frozenset()}
    monkeypatch.setattr(cli, "_KIND_COLLECTORS", orphaned)

    code, out, err = _run(
        ["signals", "--workspace", str(ws), "--kind", "todo", "--timings"]
    )
    assert code == 0, f"an owner-less kind must not error; exit {code}"
    assert _ran(err) == _registry_names(), (
        "a kind with an EMPTY owner set must fall back to running every "
        f"collector (correct-but-slow), not none (fast-but-wrong); ran {_ran(err)!r}"
    )
    assert out == expected_out, (
        "the fail-open path must still print exactly the kind's signals"
    )


# ---------------------------------------------------------------------------
# Behavior 12 -- documentation truth (drift guard on the LIVE prose).
# ---------------------------------------------------------------------------
# The old classification said only --collector shrinks the timings rows and
# lumped --kind in with the display filters. Both readings are now false.
STALE_FRAGMENTS = (
    "narrows them), not the display",
    "so --collector narrows them",
    "so ``--collector`` narrows them",
    "so `--collector` narrows them",
)

# Any enumeration of the display-only filters, so the guard can prove --kind is
# not listed among them rather than merely that some new sentence was added.
_ENUMERATION_RE = re.compile(r"display[- ](?:only )?filters?[^(.]*\(([^)]*)\)")

_UPSTREAM_CLAIM_RE = re.compile(
    r"upstream|narrows collection|narrows \*\*collection\*\*|narrows COLLECTION"
    r"|only that collector runs|only the collector that emits",
    re.IGNORECASE,
)


def _signals_help() -> str:
    code, out, _err = _run(["signals", "--help"])
    assert code == 0
    return out


def _readme_halves() -> tuple[str, str]:
    text = README.read_text(encoding="utf-8")
    idx = text.find("PORTFOLIO INTRO")
    assert idx > 0, "README must still carry the human-owned PORTFOLIO INTRO marker"
    return text[:idx], text[idx:]


def _prose_sites() -> dict[str, str]:
    """Every place this iteration had to correct, read from the LIVE artifact."""
    return {
        "signals --help": _signals_help(),
        "_render_collector_timings.__doc__": cli._render_collector_timings.__doc__ or "",
        "_cmd_signals.__doc__": cli._cmd_signals.__doc__ or "",
        "_collect.__doc__": cli._collect.__doc__ or "",
        "README (below marker)": _readme_halves()[1],
    }


@pytest.mark.parametrize("site", sorted(_prose_sites()))
def test_b12_no_prose_site_still_calls_kind_a_display_only_filter(site: str) -> None:
    text = _prose_sites()[site]
    for stale in STALE_FRAGMENTS:
        assert stale not in text, (
            f"{site} still carries the superseded phrasing {stale!r}, which now "
            "misinforms the user about what --kind costs"
        )
    for match in _ENUMERATION_RE.finditer(text):
        listed = match.group(1)
        assert "kind" not in listed, (
            f"{site} lists --kind among the display-only filters ({listed!r}); "
            "--kind is now an upstream collector allowlist"
        )


@pytest.mark.parametrize("site", sorted(_prose_sites()))
def test_b12_every_prose_site_states_that_kind_narrows_collection(site: str) -> None:
    text = _prose_sites()[site]
    assert "--kind" in text or "``--kind``" in text, f"{site} must mention --kind"
    assert _UPSTREAM_CLAIM_RE.search(text), (
        f"{site} must state that --kind narrows COLLECTION (upstream), not just "
        "the view -- that is the user-visible claim this iteration ships"
    )


def test_b12_the_new_claim_lives_below_the_human_owned_marker() -> None:
    above, below = _readme_halves()
    assert "narrows **collection**" in below, (
        "the README's `signals` row must publish the upstream-narrowing claim"
    )
    assert "narrows **collection**" not in above, (
        "the human-owned portfolio intro must not be edited by this feature"
    )


# ---------------------------------------------------------------------------
# Behavior 13 -- the neighbours are untouched.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", SIGNAL_KINDS)
def test_b13_collectors_reverse_lookup_is_unchanged(kind: str) -> None:
    code, out, _err = _run(["collectors", "--kind", kind, "--json"])
    assert code == 0
    entries = json.loads(out)["collectors"]
    assert len(entries) == 1
    assert entries[0]["kind"] == kind
    assert entries[0]["name"] in _registry_names()


def _option_strings(verb: str) -> set[str]:
    parser = build_parser()
    subparsers = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    sub = subparsers.choices[verb]
    return {opt for action in sub._actions for opt in action.option_strings}


def test_b13_narrowing_did_not_leak_into_run_or_watch() -> None:
    for verb in ("run", "watch"):
        opts = _option_strings(verb)
        assert "--collector" not in opts, f"{verb} must not accept --collector"
        assert "--kind" not in opts, f"{verb} must not accept --kind"


def test_b13_scan_still_takes_collector_and_still_takes_no_kind() -> None:
    opts = _option_strings("scan")
    assert "--collector" in opts, "scan's own upstream allowlist must survive"
    assert "--kind" not in opts, (
        "adding --kind to scan is explicitly out of scope this iteration"
    )
