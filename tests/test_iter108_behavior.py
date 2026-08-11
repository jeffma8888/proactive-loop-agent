"""Black-box behavior tests for state-dir iteration 101 (ships as commit-seq
**factory iter 108**): ``pla signals --kind`` is VALIDATED against a single
source-derived registry constant, so an unknown kind is a fail-fast parse-time
usage error (exit 2, all accepted kinds named) instead of a silent exit-0 empty
listing that is byte-identical to a genuinely quiet workspace.

Why that mattered: ``signals`` is the product's auditability inspector, and
``--kind`` was its only unvalidated filter. ``pla signals --kind todos`` (the
NATURAL typo -- the COLLECTOR is ``todos`` while the KIND is ``todo``) printed
exactly what a healthy empty workspace prints, in the human view, the ``--json``
view and the ``--summary`` view. A false negative on the tool whose whole job is
to report what is perceived is the worst available failure mode for this repo.

ISOLATION CONTRACT (honored): every assertion here is written from THIS
iteration's spec (``pm.md`` Expected Behaviors), ``README.md``, ``tests/``, and
the product's own observable output obtained by RUNNING it. **No file under
``src/`` was read by the author, no engineer/reviewer note was consulted, and no
``git diff`` was inspected.** The drift guard in behaviors 7/8 does parse the
shipped collector modules, but MECHANICALLY at runtime (``ast``) -- that is the
oracle the spec mandates, not a human reading of the implementation, and it is
re-derived here independently of any shipped guard.

Fully offline: zero network, zero API keys, zero subprocesses. Exact-count
assertions use synthetic in-memory snapshots; the CLI envelope uses the bundled
``examples/fixture_workspace`` and NEVER hardcodes its mutable per-kind counts
(``working_tree`` fires on the enclosing repo's uncommitted files, so it is 7
here and 0 in a clean CI checkout).
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import re
from pathlib import Path

import pytest

from proactive_loop import collectors as collectors_pkg
from proactive_loop.cli import (
    _render_signals_summary,
    _signals_json_payload,
    build_parser,
    main,
)
from proactive_loop.collectors import SIGNAL_KINDS, all_collectors
from proactive_loop.models import ContextSignal, WorkspaceSnapshot

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
COLLECTORS_DIR = REPO / "src" / "proactive_loop" / "collectors"
README = REPO / "README.md"
TESTS_DIR = Path(__file__).resolve().parent

_EMPTY_MARKER = "(no signals collected)"

# The universe as the SPEC states it (behavior 1). Written out here so this file
# is an independent oracle: if the shipped tuple drifts, this literal disagrees.
_SPEC_KINDS: tuple[str, ...] = (
    "broken_link",
    "ci_config",
    "dependency",
    "git_commit",
    "git_stash",
    "git_state",
    "large_file",
    "license",
    "lockfile_drift",
    "merge_conflict",
    "note",
    "recent_file",
    "secret_file",
    "syntax_error",
    "test_posture",
    "todo",
    "working_tree",
)

# A kind that IS valid (parses) but that the fixture never emits -- the vehicle
# for every empty-SELECTION assertion now that an unknown kind exits 2. Paired
# with _assert_vehicle_absent() so it can never silently become present.
_ABSENT_KIND = "merge_conflict"

# Rejected values, kept in a VARIABLE (never inline after a `"--kind"` literal)
# so the fail-closed test-corpus scan in behavior 5 does not flag this file.
_UNKNOWN_KINDS: tuple[str, ...] = (
    "todos",          # the natural typo: collector `todos` vs kind `todo`
    "notes",          # collector `notes` vs kind `note`
    "git_activity",   # collector name, not a kind
    "filesystem",     # collector-ish name; the kind is `recent_file`
    "TODO",           # case matters
    "todo ",          # trailing space
    "",               # empty string
    "no_such_kind_xyz",
)

# The single most likely real-world typo, used by name (never inline) so the
# fail-closed corpus scan in behavior 5 can stay strict about INLINE literals.
_TYPO = _UNKNOWN_KINDS[0]


# ---------------------------------------------------------------------------
# Black-box helpers: public CLI + public constructors only.
# ---------------------------------------------------------------------------
def _run(argv: list[str]) -> tuple[int, str, str]:
    """Drive ``main(argv)``; return ``(exit_code, stdout, stderr)``.

    Normalizes both the normal int return and argparse's ``SystemExit(2)`` so a
    usage error is observable without ``pytest.raises``.
    """
    out, err = io.StringIO(), io.StringIO()
    code: int
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rv = main(argv)
            code = rv if isinstance(rv, int) else 0
        except SystemExit as exc:  # argparse usage error
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return code, out.getvalue(), err.getvalue()


def _signals_argv(*extra: str, workspace: str | None = None) -> list[str]:
    return ["signals", "--workspace", workspace or str(FIXTURE), *extra]


def _json_signals(*extra: str) -> list[dict]:
    code, out, err = _run(_signals_argv("--json", *extra))
    assert code == 0, f"expected exit 0 for {extra}; got {code}, stderr={err!r}"
    doc = json.loads(out)
    assert set(doc) == {"workspace_root", "signals"}, doc.keys()
    return doc["signals"]


def _key(sig: dict) -> tuple[str, str, str]:
    return (sig["source"], sig["kind"], sig["summary"])


def _assert_vehicle_absent() -> None:
    """Fail closed if the empty-selection vehicle kind starts appearing."""
    present = {s["kind"] for s in _json_signals()}
    assert _ABSENT_KIND not in present, (
        f"vehicle kind {_ABSENT_KIND!r} is now emitted by the fixture "
        f"({sorted(present)}); pick another valid-but-absent kind"
    )


def _sig(kind: str, summary: str, weight: float = 1.0) -> ContextSignal:
    return ContextSignal(
        source="probe", kind=kind, summary=summary, detail="", path=None, weight=weight
    )


def _snap(signals: list[ContextSignal]) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(root="/w", signals=list(signals))


def _readme_intro_and_body() -> tuple[str, str]:
    text = README.read_text(encoding="utf-8")
    marker = "PORTFOLIO INTRO"
    idx = text.find(marker)
    assert idx > 0, "README must still carry the human-owned PORTFOLIO INTRO marker"
    return text[:idx], text[idx:]


# ---------------------------------------------------------------------------
# The drift-guard mechanism (behavior 7), re-implemented here from the spec so
# behavior 8 can prove it against known-bad AND known-good samples.
# ---------------------------------------------------------------------------
def _scan_kind_kwargs(source: str) -> tuple[set[str], list[str]]:
    """Return ``(string-literal kind= values, descriptions of non-literal ones)``.

    Fail-closed by construction: anything that is not a plain ``ast.Constant``
    string lands in the second list, so a computed kind such as
    ``kind=f"git_{x}"`` can never silently shrink the derived universe.
    """
    literals: set[str] = set()
    non_literals: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.keyword) and node.arg == "kind":
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                literals.add(value.value)
            else:
                non_literals.append(f"line {getattr(value, 'lineno', '?')}: {type(value).__name__}")
    return literals, non_literals


def _scan_shipped_collectors() -> tuple[set[str], list[str], int]:
    literals: set[str] = set()
    non_literals: list[str] = []
    scanned = 0
    for path in sorted(COLLECTORS_DIR.glob("*.py")):
        lits, bad = _scan_kind_kwargs(path.read_text(encoding="utf-8"))
        literals |= lits
        non_literals += [f"{path.name} {b}" for b in bad]
        scanned += 1
    return literals, non_literals, scanned


# ===========================================================================
# Behavior 1 -- the constant exists and is exact.
# ===========================================================================
def test_b01_signal_kinds_is_an_exact_sorted_deduped_tuple() -> None:
    assert isinstance(SIGNAL_KINDS, tuple), f"must be a tuple, got {type(SIGNAL_KINDS)}"
    assert all(isinstance(k, str) for k in SIGNAL_KINDS), SIGNAL_KINDS
    assert list(SIGNAL_KINDS) == sorted(SIGNAL_KINDS), f"must be sorted; got {SIGNAL_KINDS}"
    assert len(set(SIGNAL_KINDS)) == len(SIGNAL_KINDS), "must contain no duplicates"
    assert SIGNAL_KINDS == _SPEC_KINDS, (
        "SIGNAL_KINDS disagrees with the spec's measured 17-kind universe; "
        f"extra={sorted(set(SIGNAL_KINDS) - set(_SPEC_KINDS))} "
        f"missing={sorted(set(_SPEC_KINDS) - set(SIGNAL_KINDS))}"
    )
    assert len(SIGNAL_KINDS) == 17


def test_b01_signal_kinds_is_a_public_export() -> None:
    assert "SIGNAL_KINDS" in getattr(collectors_pkg, "__all__", ()), (
        "SIGNAL_KINDS must be listed in proactive_loop.collectors.__all__ -- it "
        "is the published vocabulary, not an internal detail"
    )


# ===========================================================================
# Behavior 2 -- an unknown kind is a PARSE-TIME usage error.
# ===========================================================================
@pytest.mark.parametrize("bad", _UNKNOWN_KINDS)
def test_b02_unknown_kind_exits_2_with_empty_stdout(bad: str) -> None:
    code, out, err = _run(_signals_argv("--kind", bad))
    assert code == 2, f"unknown kind {bad!r} must exit 2; got {code} (stderr={err!r})"
    assert out == "", f"nothing may reach stdout on a usage error; got {out!r}"
    assert _EMPTY_MARKER not in out + err, "must not degrade to the empty-listing marker"


def test_b02_stderr_names_the_rejected_value_and_all_16_kinds() -> None:
    code, out, err = _run(_signals_argv("--kind", _TYPO))
    assert code == 2 and out == ""
    assert "todos" in err, f"stderr must name the rejected value; got {err!r}"
    assert "--kind" in err, f"stderr must name the offending option; got {err!r}"
    missing = [k for k in SIGNAL_KINDS if k not in err]
    assert not missing, f"stderr must enumerate every accepted kind; missing {missing}"


@pytest.mark.parametrize("extra", [(), ("--json",), ("--summary",), ("--summary", "--json")])
def test_b02_unknown_kind_fails_in_every_render_mode(extra: tuple[str, ...]) -> None:
    code, out, err = _run(_signals_argv("--kind", _TYPO, *extra))
    assert code == 2, f"mode {extra} must still exit 2; got {code}"
    assert out == "", f"mode {extra} leaked stdout: {out!r}"
    assert "total" not in out, "a typo must never produce a total a CI script could read as health"


def test_b02_rejection_happens_before_any_collection_runs() -> None:
    """Observable proof that no collection is attempted: the SAME nonexistent
    workspace fails as an argparse usage error with an unknown kind, and does
    NOT produce that usage error with a valid kind."""
    missing_ws = str(REPO / "definitely" / "not" / "a" / "workspace")
    code_bad, out_bad, err_bad = _run(_signals_argv("--kind", _TYPO, workspace=missing_ws))
    assert code_bad == 2 and out_bad == ""
    assert "invalid choice" in err_bad, f"expected an argparse choice error; got {err_bad!r}"

    code_ok, _out_ok, err_ok = _run(_signals_argv("--kind", "todo", workspace=missing_ws))
    assert "invalid choice" not in err_ok, (
        "a VALID kind against the same missing workspace must get past argparse; "
        f"got {err_ok!r}"
    )
    assert code_ok != 2 or "--kind" not in err_ok, (
        "a valid kind must never be reported as a --kind usage error"
    )


# ===========================================================================
# Behavior 3 -- EVERY valid kind parses (whole universe, not a spot-check).
# ===========================================================================
@pytest.mark.parametrize("kind", SIGNAL_KINDS)
def test_b03_every_valid_kind_exits_0_via_cli(kind: str) -> None:
    code, _out, err = _run(_signals_argv("--kind", kind))
    assert code == 0, f"valid kind {kind!r} must exit 0; got {code} (stderr={err!r})"
    assert "invalid choice" not in err, f"valid kind {kind!r} was rejected: {err!r}"


@pytest.mark.parametrize("kind", SIGNAL_KINDS)
def test_b03_every_valid_kind_survives_the_parser_unmodified(kind: str) -> None:
    ns = build_parser().parse_args(["signals", "--workspace", str(FIXTURE), "--kind", kind])
    assert ns.kind == kind, f"parser mangled the kind: {ns.kind!r} != {kind!r}"


def test_b03_kind_default_is_none_when_the_flag_is_absent() -> None:
    ns = build_parser().parse_args(["signals", "--workspace", str(FIXTURE)])
    assert ns.kind is None, f"absent --kind must stay None (no filtering); got {ns.kind!r}"


# ===========================================================================
# Behavior 4 -- a VALID kind matching nothing still degrades to EMPTY, not to
# an error (the pre-existing iter-15 / iter-99 contract, vehicle-migrated).
# ===========================================================================
def test_b04_absent_kind_human_view() -> None:
    _assert_vehicle_absent()
    code, out, err = _run(_signals_argv("--kind", _ABSENT_KIND))
    assert code == 0, f"valid-but-absent kind must exit 0; stderr={err!r}"
    assert out == _EMPTY_MARKER + "\n", f"expected exactly the marker; got {out!r}"


def test_b04_absent_kind_json_view() -> None:
    _assert_vehicle_absent()
    code, out, err = _run(_signals_argv("--json", "--kind", _ABSENT_KIND))
    assert code == 0, f"stderr={err!r}"
    doc = json.loads(out)
    assert set(doc) == {"workspace_root", "signals"}, doc.keys()
    assert doc["signals"] == [], f"expected an empty array; got {doc['signals']!r}"
    assert _EMPTY_MARKER not in out, "the JSON view must never emit the human marker"


def test_b04_absent_kind_summary_view() -> None:
    _assert_vehicle_absent()
    code, out, err = _run(_signals_argv("--summary", "--kind", _ABSENT_KIND))
    assert code == 0, f"stderr={err!r}"
    assert out == _EMPTY_MARKER + "\n", f"expected exactly the marker; got {out!r}"
    assert "total" not in out, "no total line on an empty human summary"


def test_b04_absent_kind_summary_json_view() -> None:
    _assert_vehicle_absent()
    code, out, err = _run(_signals_argv("--summary", "--json", "--kind", _ABSENT_KIND))
    assert code == 0, f"stderr={err!r}"
    doc = json.loads(out)
    assert set(doc) == {"workspace_root", "summary", "total"}, doc.keys()
    assert doc["summary"] == {} and doc["total"] == 0, doc


# ===========================================================================
# Behavior 5 -- render-layer tolerance survives; no test may re-introduce an
# impossible kind through the CLI.
# ===========================================================================
def test_b05_pure_render_helpers_still_tolerate_an_arbitrary_unknown_string() -> None:
    """The argparse gate is a CLI-boundary guarantee, NOT a new precondition on
    the render layer -- these two helpers must stay total."""
    snap = _snap([_sig("todo", "a"), _sig("note", "b")])
    payload = _signals_json_payload(snap, kind="no_such_kind")
    assert payload["signals"] == [], payload
    assert _render_signals_summary(snap, "no_such_kind") == _EMPTY_MARKER


def test_b05_no_test_passes_an_impossible_kind_through_the_cli() -> None:
    """Fail-closed corpus scan: every string literal used as a ``--kind`` value
    anywhere under ``tests/`` must be a member of SIGNAL_KINDS, or it is dead
    code that exits 2 and asserts nothing about the feature it claims to test.

    NO exemption list, deliberately (an exempted file is the one place a gate can
    never look). The convention this enforces instead: a test that WANTS to drive
    a rejected value routes it through a named variable (see ``_UNKNOWN_KINDS`` /
    ``_TYPO`` above), which is self-documenting at the call site; an accidental
    hardcoded typo trips the scan."""
    pattern = re.compile(r"""["']--kind["']\s*,\s*["']([^"']*)["']""")
    scanned = 0
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        scanned += 1
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for value in pattern.findall(line):
                if value not in SIGNAL_KINDS:
                    offenders.append(f"{path.name}:{lineno}: {value!r}")
    assert scanned >= 100, f"corpus scan found only {scanned} test files -- glob is fail-open"
    assert not offenders, (
        "these CLI --kind literals are no longer accepted values (they now exit "
        f"2 at parse time): {offenders}"
    )


# ===========================================================================
# Behavior 6 -- the vocabulary is self-documenting.
# ===========================================================================
def test_b06_help_enumerates_every_kind_and_drops_the_3_value_teaser() -> None:
    code, out, err = _run(["signals", "--help"])
    assert code == 0, f"--help must exit 0; got {code} (stderr={err!r})"
    missing = [k for k in SIGNAL_KINDS if k not in out]
    assert not missing, f"pla signals --help must name every kind; missing {missing}"
    assert "todo|note|git_commit" not in out, (
        "help still advertises the old closed 3-value teaser 'todo|note|git_commit', "
        "which understates a 17-value vocabulary"
    )


# ===========================================================================
# Behavior 7 -- fail-closed drift guard, stdlib only.
# ===========================================================================
def test_b07_ast_derived_universe_equals_signal_kinds() -> None:
    literals, non_literals, scanned = _scan_shipped_collectors()
    assert scanned >= 16, f"only {scanned} collector modules scanned -- glob is fail-open"
    assert literals, "AST scan derived ZERO kinds -- the guard would pass vacuously"
    assert literals == set(SIGNAL_KINDS), (
        "SIGNAL_KINDS has drifted from the kinds the collectors actually emit; "
        f"source-only={sorted(literals - set(SIGNAL_KINDS))} "
        f"constant-only={sorted(set(SIGNAL_KINDS) - literals)}"
    )


def test_b07_every_shipped_kind_argument_is_a_plain_string_literal() -> None:
    _literals, non_literals, _scanned = _scan_shipped_collectors()
    assert non_literals == [], (
        "a computed kind= argument would make the derived universe silently "
        f"incomplete: {non_literals}"
    )


# ===========================================================================
# Behavior 8 -- the guard is PROVEN, both ways, on synthetic sources.
# ===========================================================================
@pytest.mark.parametrize(
    "bad_source",
    [
        'ContextSignal(kind=f"git_{x}", summary="s")',
        'ContextSignal(kind=SOME_CONST, summary="s")',
        'ContextSignal(kind="a" if y else "b", summary="s")',
        'ContextSignal(kind=prefix + "todo", summary="s")',
        'ContextSignal(kind=KINDS[0], summary="s")',
    ],
)
def test_b08_non_literal_kind_is_rejected(bad_source: str) -> None:
    literals, non_literals = _scan_kind_kwargs(bad_source)
    assert non_literals, f"guard failed to flag a computed kind: {bad_source!r}"
    assert literals == set() or "todo" not in literals


def test_b08_known_good_sample_does_not_fire() -> None:
    """Two-sided self-test: the guard must stay silent on legitimate source, or
    it is a permanently-red check nobody can satisfy."""
    literals, non_literals = _scan_kind_kwargs(
        'ContextSignal(source="s", kind="todo", summary="x")\n'
        'ContextSignal(source="s", kind="note", summary="y")\n'
    )
    assert literals == {"todo", "note"} and non_literals == []


@pytest.mark.parametrize("dropped", SIGNAL_KINDS)
def test_b08_dropping_any_single_kind_breaks_set_equality(dropped: str) -> None:
    literals, _non_literals, _scanned = _scan_shipped_collectors()
    mutilated = set(SIGNAL_KINDS) - {dropped}
    assert literals != mutilated, (
        f"the guard would NOT notice {dropped!r} disappearing from the registry"
    )


def test_b08_an_extra_phantom_kind_breaks_set_equality() -> None:
    literals, _non_literals, _scanned = _scan_shipped_collectors()
    assert literals != set(SIGNAL_KINDS) | {"phantom_kind"}


# ===========================================================================
# Behavior 9 -- no regression on the neighbouring flags.
# ===========================================================================
def test_b09_collector_choices_still_validate() -> None:
    code, out, err = _run(_signals_argv("--collector", "todo"))  # kind, not collector
    assert code == 2 and out == "", f"got {code}, stdout={out!r}"
    assert "invalid choice" in err and "todos" in err, err
    live = {c.name for c in all_collectors()}
    missing = [n for n in sorted(live) if n not in err]
    assert not missing, f"--collector error must still list every collector; missing {missing}"


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "abc"])
def test_b09_min_weight_still_rejects_non_finite_values(bad: str) -> None:
    code, out, _err = _run(_signals_argv("--min-weight", bad))
    assert code == 2 and out == "", f"--min-weight {bad!r}: got {code}, stdout={out!r}"


def test_b09_kind_composes_as_a_logical_and_with_collector() -> None:
    by_kind = {_key(s) for s in _json_signals("--kind", "todo")}
    by_collector = {_key(s) for s in _json_signals("--collector", "todos")}
    both = {_key(s) for s in _json_signals("--kind", "todo", "--collector", "todos")}
    assert both == by_kind & by_collector, (
        f"AND composition broken: kind={len(by_kind)} collector={len(by_collector)} "
        f"both={len(both)} expected={len(by_kind & by_collector)}"
    )


def test_b09_kind_composes_as_a_logical_and_with_min_weight() -> None:
    by_kind = _json_signals("--kind", "todo")
    both = _json_signals("--kind", "todo", "--min-weight", "0.5")
    assert {_key(s) for s in both} == {_key(s) for s in by_kind if s["weight"] >= 0.5}
    code, out, _err = _run(_signals_argv("--kind", "todo", "--min-weight", "999"))
    assert code == 0 and out == _EMPTY_MARKER + "\n", (
        f"AND-narrowing to empty must still degrade, not error; got {code} {out!r}"
    )


# ===========================================================================
# Behavior 10 -- absent-flag behavior is unchanged, and --kind only SELECTS.
# ===========================================================================
def test_b10_no_flag_listing_is_deterministic() -> None:
    """NOTE on scope: comparing bytes against the PRE-change build is not
    available to this role (reading src/ or git diff is forbidden), so the
    invariant asserted here is determinism plus the partition property below,
    which together mean --kind cannot have altered WHICH signals are selected."""
    first = _run(_signals_argv())
    second = _run(_signals_argv())
    assert first[0] == 0 and first[1], f"no-flag listing must print something; got {first!r}"
    assert first[1] == second[1], "repeated no-flag listings must be byte-identical"


def test_b10_per_kind_filters_partition_the_unfiltered_listing() -> None:
    unfiltered = _json_signals()
    assert unfiltered, "fixture must emit at least one signal for this to mean anything"
    seen: list[tuple[str, str, str]] = []
    for kind in SIGNAL_KINDS:
        subset = _json_signals("--kind", kind)
        assert all(s["kind"] == kind for s in subset), f"--kind {kind} leaked other kinds"
        expected = [_key(s) for s in unfiltered if s["kind"] == kind]
        assert [_key(s) for s in subset] == expected, (
            f"--kind {kind} is no longer a pure selection of the unfiltered listing"
        )
        seen += expected
    assert sorted(seen) == sorted(_key(s) for s in unfiltered), (
        "every emitted signal must be reachable by exactly one valid --kind value; "
        f"unreachable kinds: {sorted({s['kind'] for s in unfiltered} - set(SIGNAL_KINDS))}"
    )


def test_b10_live_output_never_contains_a_kind_outside_the_registry() -> None:
    live_kinds = {s["kind"] for s in _json_signals()}
    assert live_kinds <= set(SIGNAL_KINDS), (
        f"collectors emit kinds the registry does not accept: "
        f"{sorted(live_kinds - set(SIGNAL_KINDS))} -- those signals would be "
        "invisible to --kind"
    )


# ===========================================================================
# Behavior 11 -- README, below the human-owned marker only.
# ===========================================================================
def test_b11_cli_reference_documents_the_kind_validation() -> None:
    _intro, body = _readme_intro_and_body()
    rows = [ln for ln in body.splitlines() if ln.startswith("| `signals`")]
    assert len(rows) == 1, f"expected exactly one `signals` CLI row; found {len(rows)}"
    row = rows[0]
    for needle in ("`--kind K`", "validated", "usage error", "exit 2", "pla signals --help"):
        assert needle in row, f"the `signals` CLI row must mention {needle!r}; got {row!r}"


def test_b11_portfolio_intro_numbers_still_match_the_live_registries() -> None:
    intro, _body = _readme_intro_and_body()
    m = re.search(r"(\d+) context collectors", intro)
    assert m, "intro must state the collector count"
    assert int(m.group(1)) == len(all_collectors()) == 17, m.group(0)
    m = re.search(r"(\d+) CLI verbs", intro)
    assert m, "intro must state the CLI-verb count"
    assert int(m.group(1)) == 15, m.group(0)


def test_b11_no_16_row_kind_table_was_added() -> None:
    """The deferred half of roadmap row 110 must stay deferred: no new heading
    and no full kind table in this iteration."""
    text = README.read_text(encoding="utf-8")
    headings = [ln for ln in text.splitlines() if re.match(r"^#{2,}\s", ln)]
    offenders = [h for h in headings if "kind" in h.lower()]
    assert not offenders, f"a new kind-table heading was added out of scope: {offenders}"
    table_rows = [ln for ln in text.splitlines() if re.match(r"^\|\s*`(ci_config|todo)`", ln)]
    assert not table_rows, f"a per-kind reference table was added out of scope: {table_rows}"
