"""Black-box behavior tests for iteration 92 (ships as commit-sequence **factory
iter 99**): ``pla signals --summary`` --- the FIRST AGGREGATE view on the
read-only signals inspector. Every prior ``signals`` knob (``--kind`` /
``--min-weight`` / ``--collector``) is a FILTER that narrows the per-signal
listing; ``--summary`` instead emits a per-``kind`` COUNT rollup (kind -> count
plus a grand total) over the SAME selected set. With ``--json`` it emits one
``{workspace_root, summary, total}`` object; without it, a human count table
(``"{kind}  {count}"`` lines, ascending kind order, trailing ``"total  {N}"``).
It composes (logical AND) with the three existing filters and never changes
WHICH signals are selected --- only how they are RENDERED (ROADMAP #99).

ISOLATION CONTRACT (honored): every assertion here is written strictly against
THIS iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and the product's own observable output --- and drives ONLY the
documented public surface: the ``pla`` CLI via ``proactive_loop.cli.main(argv)``
(observable stdout / stderr / exit code), ``build_parser()``, the public model
constructors ``ContextSignal(...)`` / ``WorkspaceSnapshot(...)``, and the two
spec-mandated pure helpers ``_render_signals_summary`` /
``_signals_summary_payload`` (the same way ``tests/test_iter88_behavior.py``
drives ``_render_signals`` / ``_signals_json_payload``). **No file under
``src/`` was read, no engineer/reviewer note was consulted, and no ``git diff``
was inspected** to author these assertions. Every test is fully offline:
zero network, zero API keys; synthetic in-memory snapshots for exact-count
assertions and the bundled ``examples/fixture_workspace`` (never hardcoding its
mutable per-kind counts) plus ``tmp_path`` for the CLI envelope. Where the CLI
requires a provider, ``--provider scripted`` (the default, offline) is used;
``signals`` builds no ``LLMClient`` regardless.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
import re
import shutil
from collections import Counter
from pathlib import Path

import pytest

from proactive_loop import __version__
from proactive_loop.cli import (
    _render_signals_summary,
    _signals_summary_payload,
    build_parser,
    main,
)
from proactive_loop.models import ContextSignal, WorkspaceSnapshot

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"

_EMPTY_MARKER = "(no signals collected)"

# A kind that is VALID (in SIGNAL_KINDS, so it parses) but that this fixture
# never emits -- the vehicle for the empty-SELECTION cases now that
# `pla signals --kind` rejects unknown kinds at parse time (exit 2). Paired with
# _assert_vehicle_absent so the vehicle cannot silently become present.
_ABSENT_KIND = "merge_conflict"


def _assert_vehicle_absent() -> None:
    """Fail closed if the empty-selection vehicle kind starts appearing.

    WHY: an empty result is indistinguishable from a filter that matched
    everything-but-nothing-was-there. Anchoring on the UNFILTERED listing keeps
    the degrade assertions honest if the fixture ever grows a merge conflict.
    """
    present = _listing_counts_via_cli([])
    assert _ABSENT_KIND not in present, (
        f"vehicle kind {_ABSENT_KIND!r} is now emitted by the fixture "
        f"({sorted(present)}); pick another absent kind"
    )
# One human table line: kind, EXACTLY two spaces, an integer count. `\S+`/`\d+`
# forbid interior spaces, so this pattern enforces the "exactly two spaces" and
# "no column padding" contract from behavior 1.
_LINE_RE = re.compile(r"^(?P<kind>\S+)  (?P<count>\d+)$")


# ---------------------------------------------------------------------------
# Black-box helpers (public constructors / public CLI only; no src/ read).
# ---------------------------------------------------------------------------
def _sig(kind: str, summary: str, weight: float, *, source: str = "probe") -> ContextSignal:
    return ContextSignal(source=source, kind=kind, summary=summary, detail="", path=None, weight=weight)


def _snap(signals) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(root="/w", signals=list(signals))


def _run(argv) -> tuple[int, str, str]:
    """Drive main(argv); return (exit_code, stdout, stderr). Normalizes the
    normal int return AND an argparse SystemExit(2) usage error to a code, so
    behavior 7/10 parse/guard paths are observable without pytest.raises."""
    out, err = io.StringIO(), io.StringIO()
    code: int
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rv = main(argv)
            code = rv if isinstance(rv, int) else 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return code, out.getvalue(), err.getvalue()


def _isolated_fixture_copy(dest: Path) -> Path:
    """Copy the bundled fixture to `dest` (a `tmp_path` child) and return it, so
    a run over it cannot observe THIS repo's git state.

    WHY: the bundled fixture directory carries no `.git` of its own, so it
    inherits the enclosing product repo and every git-family collector reports
    the REPO rather than the fixture. Measured on the same tree: the in-repo
    path emits `git_commit  15` and `total  34`, while an identical copy with no
    enclosing repo emits `total  23` and no git kind at all -- and the extra
    `working_tree  1` row appears only while the repo happens to be dirty.
    Byte-comparing two runs over the in-repo path therefore compares a SHARED
    MUTABLE tree: any concurrent process that dirties the repo between the two
    runs flips the counts and the comparison fails for a reason that has nothing
    to do with the product's determinism. A copy under `tmp_path` removes that
    input entirely, so the compared bytes depend only on the fixture's content.

    `.git` and byte-cache directories are ignored so the copy is the fixture as
    committed, even when a local working tree carries build cruft.
    """
    shutil.copytree(
        FIXTURE, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc")
    )
    return dest


def _parse_human_summary(stdout: str) -> tuple[dict[str, int], int, list[str]]:
    """Parse a human summary table. Returns (per-kind counts, total, ordered
    kind list). Asserts structure: every non-final line is a `kind  count`
    row, the final line is `total  N`, and there are no blank/other lines."""
    lines = stdout.split("\n")
    assert lines and lines[-1] == "", f"CLI must end with a trailing newline; got {stdout!r}"
    lines = lines[:-1]  # drop the trailing '' from the final print newline
    assert lines, f"summary must print at least a total line; got {stdout!r}"
    assert lines[-1].startswith("total  "), f"last line must be 'total  N'; got {lines[-1]!r}"
    total = int(lines[-1][len("total  "):])
    counts: dict[str, int] = {}
    order: list[str] = []
    for ln in lines[:-1]:
        m = _LINE_RE.match(ln)
        assert m, f"each row must be exactly '{{kind}}  {{count}}' (two spaces); got {ln!r}"
        assert m.group("kind") != "total", "a real kind row must not be named 'total'"
        counts[m.group("kind")] = int(m.group("count"))
        order.append(m.group("kind"))
    return counts, total, order


def _listing_counts_via_cli(argv_filters: list[str]) -> dict[str, int]:
    """Ground truth: per-kind counts derived from the NON-summary --json listing
    over the same workspace/filters. Cross-checks the summary against the
    already-shipped listing without hardcoding the fixture's mutable counts."""
    code, out, err = _run(["signals", "--workspace", str(FIXTURE), "--json", *argv_filters])
    assert code == 0, f"listing must exit 0; stderr={err!r}"
    doc = json.loads(out)
    assert set(doc.keys()) == {"workspace_root", "signals"}, doc.keys()
    return dict(Counter(s["kind"] for s in doc["signals"]))


def _summary_key_order(json_text: str) -> list[str]:
    """Serialized key order of the JSON `summary` object (order-preserving parse)."""
    doc = json.loads(json_text, object_pairs_hook=collections.OrderedDict)
    return list(doc["summary"].keys())


# ===========================================================================
# Behavior 1 -- Human summary, non-empty: one `"{kind}  {count}"` line per
# distinct selected kind in ASCENDING kind order, trailing `"total  {N}"` last,
# N == sum of the per-kind counts, no other lines.
# ===========================================================================
def test_b01_human_summary_format_order_and_total_pure():
    snap = _snap([
        _sig("todo", "a", 1.0),
        _sig("todo", "b", 0.5),
        _sig("note", "c", 0.9),
        _sig("git_commit", "d", 0.3),
    ])
    text = _render_signals_summary(snap)
    assert text == "git_commit  1\nnote  1\ntodo  2\ntotal  4", (
        f"kinds ascending, exactly two spaces, total last; got {text!r}"
    )
    # No trailing newline in the pure helper (the CLI adds the newline via print).
    assert not text.endswith("\n")


def test_b01_human_summary_end_to_end_via_cli():
    code, out, err = _run(["signals", "--workspace", str(FIXTURE), "--summary"])
    assert code == 0, f"--summary must exit 0; stderr={err!r}"
    counts, total, order = _parse_human_summary(out)
    assert order == sorted(order), f"kinds must be ascending; got {order}"
    assert total == sum(counts.values()), f"total ({total}) must equal sum of counts {counts}"
    # Cross-check against the shipped per-signal listing (no hardcoded fixture counts).
    assert counts == _listing_counts_via_cli([]), "summary counts must match the listing view"


# ===========================================================================
# Behavior 2 -- Human summary, empty selection -> EXACTLY `(no signals
# collected)` and NO total line; exit 0.
# ===========================================================================
def test_b02_human_empty_selection_marker_no_total_pure():
    assert _render_signals_summary(_snap([])) == _EMPTY_MARKER
    # Filtered-to-empty (a kind that matches nothing) is also the marker.
    snap = _snap([_sig("todo", "x", 1.0)])
    assert _render_signals_summary(snap, "no_such_kind") == _EMPTY_MARKER


def test_b02_human_empty_selection_via_cli():
    _assert_vehicle_absent()
    code, out, err = _run(
        ["signals", "--workspace", str(FIXTURE), "--summary", "--kind", _ABSENT_KIND]
    )
    assert code == 0, f"empty-selection --summary must exit 0; stderr={err!r}"
    assert out == _EMPTY_MARKER + "\n", f"must be exactly the empty marker; got {out!r}"
    assert "total" not in out, "no total line on an empty human summary"


# ===========================================================================
# Behavior 3 -- JSON summary, non-empty: ONE object with EXACTLY the three keys
# {workspace_root(str), summary(kind->int), total(int)}, total == sum of the
# summary values, keys serialized ascending, no `signals` array.
# ===========================================================================
def test_b03_json_summary_schema_and_total_pure():
    snap = _snap([_sig("todo", "a", 1.0), _sig("todo", "b", 0.5), _sig("note", "c", 0.9)])
    payload = _signals_summary_payload(snap)
    assert set(payload.keys()) == {"workspace_root", "summary", "total"}, payload.keys()
    assert "signals" not in payload, "summary mode must not carry a signals array"
    assert payload["workspace_root"] == snap.root
    assert payload["summary"] == {"note": 1, "todo": 2}
    assert all(isinstance(v, int) for v in payload["summary"].values())
    assert payload["total"] == 3 == sum(payload["summary"].values())
    keys = list(payload["summary"].keys())
    assert keys == sorted(keys), f"summary keys must be ascending; got {keys}"


def test_b03_json_summary_end_to_end_via_cli():
    code, out, err = _run(["signals", "--workspace", str(FIXTURE), "--summary", "--json"])
    assert code == 0, f"--summary --json must exit 0; stderr={err!r}"
    doc = json.loads(out)  # ENTIRE stdout parses as exactly one object
    assert set(doc.keys()) == {"workspace_root", "summary", "total"}, doc.keys()
    assert "signals" not in doc
    assert isinstance(doc["workspace_root"], str) and doc["workspace_root"] == str(FIXTURE)
    assert isinstance(doc["total"], int)
    assert all(isinstance(v, int) for v in doc["summary"].values())
    assert doc["total"] == sum(doc["summary"].values())
    assert _summary_key_order(out) == sorted(doc["summary"].keys()), "keys serialized ascending"
    # Cross-check the aggregate against the shipped listing view.
    assert doc["summary"] == _listing_counts_via_cli([])


# ===========================================================================
# Behavior 4 -- JSON summary, empty selection: the object with summary=={} and
# total==0 (never the human marker, never blank); workspace_root still present.
# ===========================================================================
def test_b04_json_empty_selection_pure():
    payload = _signals_summary_payload(_snap([]))
    assert payload == {"workspace_root": "/w", "summary": {}, "total": 0}


def test_b04_json_empty_selection_via_cli():
    _assert_vehicle_absent()
    code, out, err = _run(
        ["signals", "--workspace", str(FIXTURE), "--summary", "--json", "--kind", _ABSENT_KIND]
    )
    assert code == 0, f"empty --summary --json must exit 0; stderr={err!r}"
    doc = json.loads(out)
    assert doc["summary"] == {} and doc["total"] == 0
    assert set(doc.keys()) == {"workspace_root", "summary", "total"}
    assert doc["workspace_root"] == str(FIXTURE)
    assert _EMPTY_MARKER not in out, "JSON mode must never emit the human marker"


# ===========================================================================
# Behavior 5 -- Composition with --kind: counts only signals of kind K.
# ===========================================================================
def test_b05_kind_composition_pure():
    snap = _snap([_sig("todo", "a", 1.0), _sig("todo", "b", 0.4), _sig("note", "c", 0.9)])
    assert _render_signals_summary(snap, "todo") == "todo  2\ntotal  2"
    assert _signals_summary_payload(snap, "todo") == {
        "workspace_root": "/w",
        "summary": {"todo": 2},
        "total": 2,
    }
    # A kind that matches none -> empty human marker / empty JSON object.
    assert _render_signals_summary(snap, "no_such") == _EMPTY_MARKER
    assert _signals_summary_payload(snap, "no_such")["summary"] == {}
    assert _signals_summary_payload(snap, "no_such")["total"] == 0


def test_b05_kind_composition_via_cli():
    # Pick a kind the fixture actually surfaces (do not hardcode the count).
    listing = _listing_counts_via_cli([])
    assert listing, "fixture must surface at least one kind"
    kind = sorted(listing)[0]
    code, out, err = _run(
        ["signals", "--workspace", str(FIXTURE), "--summary", "--json", "--kind", kind]
    )
    assert code == 0, f"stderr={err!r}"
    doc = json.loads(out)
    assert doc["summary"] == {kind: listing[kind]}, doc["summary"]
    assert doc["total"] == listing[kind]


# ===========================================================================
# Behavior 6 -- Composition with --min-weight: counts only weight >= W; a W
# above every weight empties the selection.
# ===========================================================================
def test_b06_min_weight_composition_pure():
    snap = _snap([_sig("todo", "hi", 0.9), _sig("todo", "mid", 0.5), _sig("todo", "lo", 0.2)])
    # Inclusive lower bound: 0.9 and the exact-boundary 0.5 survive, 0.2 dropped.
    assert _signals_summary_payload(snap, None, 0.5)["summary"] == {"todo": 2}
    assert _signals_summary_payload(snap, None, 0.5)["total"] == 2
    assert _render_signals_summary(snap, None, 0.5) == "todo  2\ntotal  2"
    # A threshold above every weight empties the selection (behavior 2 / 4).
    assert _render_signals_summary(snap, None, 5.0) == _EMPTY_MARKER
    assert _signals_summary_payload(snap, None, 5.0) == {
        "workspace_root": "/w",
        "summary": {},
        "total": 0,
    }


def test_b06_min_weight_extreme_empties_via_cli():
    code, out, err = _run(
        ["signals", "--workspace", str(FIXTURE), "--summary", "--min-weight", "1000.0"]
    )
    assert code == 0, f"stderr={err!r}"
    assert out == _EMPTY_MARKER + "\n", f"extreme threshold must empty the summary; got {out!r}"


# ===========================================================================
# Behavior 7 -- Composition with --collector (repeatable, logical AND); an
# UNKNOWN --collector value remains an argparse usage error (exit 2) BEFORE the
# handler runs, unchanged from today.
# ===========================================================================
def test_b07_collector_composition_via_cli():
    # Restrict to the `notes` collector; the summary must equal the
    # collector-restricted listing counts (same `selected` set, AND semantics).
    restricted_listing = _listing_counts_via_cli(["--collector", "notes"])
    code, out, err = _run(
        ["signals", "--workspace", str(FIXTURE), "--summary", "--json", "--collector", "notes"]
    )
    assert code == 0, f"--summary --collector notes must exit 0; stderr={err!r}"
    doc = json.loads(out)
    assert doc["summary"] == restricted_listing, (doc["summary"], restricted_listing)
    assert doc["total"] == sum(restricted_listing.values())


def test_b07_unknown_collector_is_exit2_before_handler():
    code, out, err = _run(
        ["signals", "--workspace", str(FIXTURE), "--summary", "--collector", "bogus_xyz"]
    )
    assert code == 2, f"an unknown --collector must be an argparse usage error (exit 2); got {code}"
    assert out == "", f"a parse error must write NOTHING to stdout; got {out!r}"
    assert "bogus_xyz" in err, f"stderr must name the invalid collector; got:\n{err}"


# ===========================================================================
# Behavior 8 -- Determinism: two runs over the same snapshot/filters are
# byte-identical (kinds ascending, total last / keys ascending).
# ===========================================================================
def test_b08_determinism_pure():
    snap = _snap([_sig("z", "a", 1.0), _sig("a", "b", 1.0), _sig("m", "c", 1.0)])
    assert _render_signals_summary(snap) == _render_signals_summary(snap)
    assert _signals_summary_payload(snap) == _signals_summary_payload(snap)
    # Ascending regardless of construction order.
    assert _render_signals_summary(snap) == "a  1\nm  1\nz  1\ntotal  3"


def test_b08_determinism_via_cli(tmp_path):
    # Drive an ISOLATED COPY, never the in-repo fixture: see
    # _isolated_fixture_copy for the measured reason the in-repo path made this
    # byte-comparison depend on the product repo's mutable git state.
    ws = str(_isolated_fixture_copy(tmp_path / "fixture_copy"))
    _, human_a, _ = _run(["signals", "--workspace", ws, "--summary"])
    _, human_b, _ = _run(["signals", "--workspace", ws, "--summary"])
    assert human_a == human_b, "two human --summary runs must be byte-identical"
    _, json_a, _ = _run(["signals", "--workspace", ws, "--summary", "--json"])
    _, json_b, _ = _run(["signals", "--workspace", ws, "--summary", "--json"])
    assert json_a == json_b, "two --summary --json runs must be byte-identical"
    # Fail closed rather than pass vacuously: two byte-identical EMPTY slates
    # would satisfy both assertions above without proving anything. Same
    # fail-closed discipline as _assert_vehicle_absent.
    assert human_a != _EMPTY_MARKER + "\n", (
        "the isolated copy must still surface signals, or this determinism "
        f"comparison is vacuous; got {human_a!r}"
    )


# ===========================================================================
# Behavior 9 -- Regression: WITHOUT --summary the listing view is untouched and
# --summary defaults OFF.
# ===========================================================================
def test_b09_bare_signals_still_lists_not_summarizes():
    code, out, err = _run(["signals", "--workspace", str(FIXTURE)])
    assert code == 0, f"bare signals must exit 0; stderr={err!r}"
    assert "## " in out, f"bare human view must be the grouped listing (## headers); got:\n{out}"
    # It must NOT be the summary table (which has no '## ' headers, only a trailing 'total  N').
    assert not out.strip().splitlines()[-1].startswith("total  "), (
        "bare signals must not print the summary's trailing total line"
    )


def test_b09_bare_json_is_listing_array_not_summary_object():
    code, out, err = _run(["signals", "--workspace", str(FIXTURE), "--json"])
    assert code == 0, f"stderr={err!r}"
    doc = json.loads(out)
    assert set(doc.keys()) == {"workspace_root", "signals"}, (
        f"bare --json must be the listing object, not the summary object; got {doc.keys()}"
    )
    assert "summary" not in doc and "total" not in doc


def test_b09_summary_flag_defaults_off():
    ns = build_parser().parse_args(["signals", "--workspace", "/w"])
    assert getattr(ns, "summary") is False, f"--summary must default to False; got {ns.summary!r}"
    ns2 = build_parser().parse_args(["signals", "--workspace", "/w", "--summary"])
    assert ns2.summary is True


# ===========================================================================
# Behavior 10 -- Workspace guard preserved: a missing/file workspace exits 2
# with `error: workspace not found: <path>` on stderr and NO stdout summary,
# for both --summary and --summary --json.
# ===========================================================================
def test_b10_workspace_guard_missing_dir():
    missing = "/no/such/dir_iter99_xyz"
    for extra in ([], ["--json"]):
        code, out, err = _run(["signals", "--workspace", missing, "--summary", *extra])
        assert code == 2, f"missing workspace must exit 2 (extra={extra}); got {code}"
        assert out == "", f"no stdout summary on the guard path (extra={extra}); got {out!r}"
        assert "workspace not found" in err and missing in err, (
            f"stderr must name the missing workspace (extra={extra}); got:\n{err}"
        )


def test_b10_workspace_guard_when_path_is_a_file(tmp_path):
    a_file = tmp_path / "not_a_dir.txt"
    a_file.write_text("hello")
    code, out, err = _run(["signals", "--workspace", str(a_file), "--summary"])
    assert code == 2, f"a file (not a dir) must trip the guard (exit 2); got {code}"
    assert out == ""
    assert "workspace not found" in err


# ===========================================================================
# Behavior 11 -- Version unchanged (a flag add, not a release bump).
# ===========================================================================
def test_b11_version_unchanged():
    assert __version__ == "0.1.1", f"adding a flag must NOT bump the version; got {__version__!r}"


# ===========================================================================
# Behavior 12 -- Human table and JSON object are mutually consistent (same
# per-kind counts, same total) for the same snapshot/filters.
# ===========================================================================
def test_b12_human_and_json_consistent_pure():
    snap = _snap([
        _sig("todo", "a", 1.0),
        _sig("todo", "b", 0.5),
        _sig("note", "c", 0.9),
        _sig("git_commit", "d", 0.3),
    ])
    payload = _signals_summary_payload(snap)
    text = _render_signals_summary(snap)
    # Re-derive the counts/total from the human table and compare to the JSON.
    counts: dict[str, int] = {}
    total = None
    for ln in text.split("\n"):
        if ln.startswith("total  "):
            total = int(ln[len("total  "):])
        else:
            k, c = ln.rsplit("  ", 1)
            counts[k] = int(c)
    assert counts == payload["summary"], (counts, payload["summary"])
    assert total == payload["total"]


def test_b12_human_and_json_consistent_via_cli(tmp_path):
    # Same isolation reason as test_b08_determinism_via_cli: the two runs
    # below are COMPARED, so they must not observe the enclosing repo's
    # mutable git state. See _isolated_fixture_copy.
    ws = str(_isolated_fixture_copy(tmp_path / "fixture_copy"))
    _, human, _ = _run(["signals", "--workspace", ws, "--summary"])
    _, js, _ = _run(["signals", "--workspace", ws, "--summary", "--json"])
    hcounts, htotal, _order = _parse_human_summary(human)
    doc = json.loads(js)
    assert hcounts == doc["summary"], "human table counts must equal the JSON summary counts"
    assert htotal == doc["total"], "human total must equal the JSON total"


# ===========================================================================
# Anchor -- --summary is a FLAG (store_true), not a new verb; `signals` remains
# a registered subcommand. The additive change must not grow the verb surface.
# ===========================================================================
def test_anchor_summary_is_store_true_flag_on_signals():
    parser = build_parser()
    sub_actions = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(sub_actions) == 1
    signals = sub_actions[0].choices["signals"]
    summary_act = [a for a in signals._actions if a.dest == "summary"][0]
    assert isinstance(summary_act, argparse._StoreTrueAction), (
        "--summary must be a store_true flag, not a value-taking option"
    )
    assert summary_act.default is False
