"""Black-box oracle for factory iteration 252 -- ``pla run --baseline FILE``.

The INSTANCE half of ``run``'s perception filter, and the move that CLOSES the trio.
Iteration 245 gave the product's only autonomous verb ``--collector`` (narrowing by
WHICH collector may speak) and iteration 249 gave it ``--exclude-path`` (narrowing by
WHERE it may speak from); the third axis -- "you already know about this one" -- shipped
only on ``signals``, a verb that produces a LISTING, so its effect evaporated at the one
verb that synthesizes a slate and may dispatch it.

This module drives the CLI boundary only and asserts observable output: exit codes,
stdout/stderr text, and ``--snapshot`` JSON documents.

Expected Behaviors covered (numbered as in the iteration spec):

1.  ``--baseline`` parses on ``run``, defaults to ``None``, and is SINGLE-VALUE (passing
    it twice keeps the last value), matching ``signals --baseline``.
2.  The ``run`` usage line advertises ``[--baseline FILE]``.
3.  A bare ``run`` is unchanged -- no ``perception suppressed`` line on either stream,
    and its stdout equals a filtered run's stdout minus the one announce line.
4.  Suppression is applied to the COLLECTED snapshot above every consumer of it: a
    ``--snapshot`` document excludes exactly the six-key identities present in the
    baseline, ``workspace_root`` survives verbatim, and survivors are a SUBSEQUENCE of
    an unfiltered run's (collector order preserved).
5.  Suppression reaches synthesis: a baseline covering every signal yields ``signals ==
    []`` in the recorded document and the run still exits 0.
6.  Exactly one deterministic announce line, when and only when the flag is supplied,
    reading ``perception suppressed <N> of <M> signals by baseline: <path>``; it is a
    SEPARATE line from the ``--collector`` and ``--exclude-path`` announces.
7.  A valid baseline whose ``signals`` array is ``[]`` still reports -- exit 0 and
    ``suppressed 0 of <M>`` -- because an empty user-supplied document is a real answer
    (``is not None``, not truthiness).
8.  Announce order is source, then location, then instance.
9.  It composes as a logical AND and changes what RUNS not at all: the ``<M>``
    denominator equals a bare run's signal count, and ``--baseline`` + ``--exclude-path``
    together yield exactly the intersection of what each yields alone.
10. A missing or malformed baseline is a usage error BEFORE anything is collected: exit
    2, exactly one ``error: `` line on stderr naming the path, EMPTY stdout, and no run
    directory or slate created.
11. ``run --help`` documents ``--baseline`` in perception/suppression terms and its prose
    contains neither the literal ``--json`` nor the literal ``--exclude-path`` (two
    shipped oracles locate those entries with ``rindex`` and would grade the wrong
    prose).

Fully offline and deterministic: synthetic ``tmp_path`` trees only, the shipped
``--provider scripted`` seam, no network, no API key, and no duration asserted
anywhere (roadmap row #129's standing constraint).
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser, main

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"

#: The instance-suppression announce line's stable ASCII prefix -- matched, never rebuilt.
SUPPRESS_PREFIX = "perception suppressed"

#: iteration 245's and 249's sibling announces, asserted UNCHANGED by this flag.
COLLECTOR_PREFIX = "perception narrowed"
EXCLUDE_PREFIX = "perception excluded"

#: The six published wire keys that make up a signal's identity.
_IDENTITY_KEYS = ("source", "kind", "summary", "detail", "path", "weight")

#: Run-scoped goal ids, which churn between two otherwise identical invocations.
_ID_RE = re.compile(r"\b[0-9a-f]{12}\b")

#: ``perception suppressed <N> of <M> signals by baseline: <path>``
_ANNOUNCE_RE = re.compile(
    r"^perception suppressed (?P<n>\d+) of (?P<m>\d+) signals by baseline: (?P<path>.+)$",
    re.M,
)


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Drive ``main(argv)``, normalizing argparse's ``SystemExit`` to a code."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
    except SystemExit as exc:  # argparse usage error / --help
        code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """A workspace holding a vendored subtree several collectors perceive."""
    w = tmp_path / "ws"
    (w / "vendor").mkdir(parents=True)
    (w / "a.py").write_text("# TODO: keep me\nx = 1\n", encoding="utf-8")
    (w / "vendor" / "v.py").write_text("# TODO: drop me\ny = 2\n", encoding="utf-8")
    return w


def _base(ws: Path, state: Path) -> list[str]:
    """The offline, non-executing ``run`` invocation every case here starts from."""
    return [
        "run",
        "--workspace",
        str(ws),
        "--state-dir",
        str(state),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--dry-run",
    ]


def _doc(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _identities(path: Path) -> list[tuple[object, ...]]:
    """The six-key identity of every signal in a ``--snapshot`` document, IN ORDER."""
    signals = _doc(path)["signals"]
    assert isinstance(signals, list)
    return [tuple(s.get(k) for k in _IDENTITY_KEYS) for s in signals]


# ---------------------------------------------------------------------------
# NOTE ON DETERMINISM (measured, and it shapes every strict assertion below).
#
# ``recent_file`` signals carry a weight that DECAYS with wall-clock file age --
# measured 1.0 -> 0.9999 over ~12 minutes on one unchanged fixture tree. Weight is one
# of the six identity keys, so a baseline captured earlier progressively stops matching
# those signals. That is the shipped, documented intent ("STALENESS FAILS TOWARD
# REPORTING -- a FILE entry that no longer matches produces noise, never a missed
# finding"), NOT a defect, but it means an oracle that captures a baseline and reuses it
# minutes later is inherently flaky.
#
# Two consequences, both applied below:
#   * every baseline is captured from a run made moments earlier in the SAME test
#     (two back-to-back bare runs were measured byte-identical, 8 signals each); and
#   * every assertion that requires SET EQUALITY between two separate runs is scoped to
#     ``STATIC_COLLECTORS`` -- collectors whose weights are fixed -- so no decay tick can
#     land between the two invocations. Count-based and disjointness-based assertions
#     are decay-proof and use the full collector set.
# ---------------------------------------------------------------------------

#: Collectors whose signal weights are constant (no wall-clock decay), so identities
#: captured in one run still match in the next. ``recent_files`` is deliberately absent.
STATIC_COLLECTORS = [
    "--collector",
    "todos",
    "--collector",
    "test_posture",
    "--collector",
    "ci_config",
    "--collector",
    "license",
]


def _write_baseline(path: Path, identities: list[dict[str, object]]) -> Path:
    """Write a baseline document in the schema ``--snapshot`` publishes."""
    path.write_text(
        json.dumps({"workspace_root": "unused-by-the-reader", "signals": identities}),
        encoding="utf-8",
    )
    return path


def _signal_dicts(path: Path) -> list[dict[str, object]]:
    """The raw signal entries of a ``--snapshot`` document, IN ORDER."""
    signals = _doc(path)["signals"]
    assert isinstance(signals, list)
    return signals


def _normalize(text: str, *, state: Path) -> str:
    """Strip the two things that legitimately churn: goal ids and the state dir path."""
    return _ID_RE.sub("<id>", text.replace(str(state), "<state>"))


def _is_subsequence(small: list[object], big: list[object]) -> bool:
    it = iter(big)
    return all(item in it for item in small)


def _announce_lines(text: str, prefix: str = SUPPRESS_PREFIX) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith(prefix)]


# ---------------------------------------------------------------------------
# Behavior 1 -- the flag exists on ``run`` with the specified argparse shape.
# ---------------------------------------------------------------------------
def test_b1_flag_parses_on_run_and_defaults_to_none() -> None:
    parser = build_parser()
    absent = parser.parse_args(["run", "--workspace", "W"])
    assert absent.baseline is None, (
        "with the flag ABSENT the dest must be None so the filter block is skipped "
        f"entirely; got {absent.baseline!r}"
    )

    once = parser.parse_args(["run", "--workspace", "W", "--baseline", "b.json"])
    assert once.baseline == "b.json", f"got {once.baseline!r}"


def test_b1_flag_is_single_value_and_keeps_the_last_occurrence() -> None:
    """NOT ``action="append"`` -- it must match ``signals --baseline``."""
    parser = build_parser()
    twice = parser.parse_args(
        ["run", "--workspace", "W", "--baseline", "x.json", "--baseline", "y.json"]
    )
    assert twice.baseline == "y.json", (
        "a single-value flag supplied twice must keep the LAST value, not append; "
        f"got {twice.baseline!r}"
    )
    assert not isinstance(twice.baseline, list), (
        f"dest must be a plain string, not a list; got {twice.baseline!r}"
    )


def test_b1_the_flag_is_scoped_to_run_and_signals_only() -> None:
    """``scan``/``watch``/``verify`` must be untouched by this iteration."""
    parser = build_parser()
    for verb, extra in (
        ("scan", ["--workspace", "W"]),
        ("watch", ["--workspace", "W"]),
    ):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args([verb, *extra, "--baseline", "b.json"])
        assert exc.value.code == 2, (
            f"{verb} must NOT gain --baseline in this iteration (exit 2 expected)"
        )


# ---------------------------------------------------------------------------
# Behavior 2 -- the usage line advertises the metavar.
# ---------------------------------------------------------------------------
def test_b2_usage_line_advertises_the_file_metavar() -> None:
    code, out, _err = _run(["run", "--help"])
    assert code == 0
    assert "[--baseline FILE]" in out, (
        "the usage line must show metavar='FILE'; got:\n" + out[:400]
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- a bare run is unchanged.
# ---------------------------------------------------------------------------
def test_b3_bare_run_prints_no_suppression_line_on_either_stream(
    ws: Path, tmp_path: Path
) -> None:
    state = tmp_path / "bare"
    code, out, err = _run(_base(ws, state))
    assert code == 0, f"bare run must still exit 0; stderr={err!r}"
    assert _announce_lines(out) == [], f"stdout gained a suppression line: {out!r}"
    assert _announce_lines(err) == [], f"stderr gained a suppression line: {err!r}"


def test_b3_bare_stdout_equals_filtered_stdout_minus_the_one_announce_line(
    ws: Path, tmp_path: Path
) -> None:
    """The strongest in-suite proxy for "byte-identical to before the flag existed".

    A tester cannot run the pre-change build, so this pins the next best invariant: with
    a baseline that suppresses NOTHING, the only difference the feature may make to a
    run's stdout is the single announce line.
    """
    bare_state, filt_state = tmp_path / "b", tmp_path / "f"
    empty = _write_baseline(tmp_path / "empty.json", [])
    code_b, out_b, _ = _run(_base(ws, bare_state))
    code_f, out_f, _ = _run(_base(ws, filt_state) + ["--baseline", str(empty)])
    assert (code_b, code_f) == (0, 0)

    stripped = "\n".join(
        ln for ln in out_f.splitlines() if not ln.startswith(SUPPRESS_PREFIX)
    )
    assert _normalize(stripped, state=filt_state) == _normalize(
        out_b.rstrip("\n"), state=bare_state
    ), "the feature changed a run's stdout beyond its single announce line"


# ---------------------------------------------------------------------------
# Behavior 4 -- suppression applies to the COLLECTED snapshot, above its consumers.
# ---------------------------------------------------------------------------
def test_b4_baseline_identities_leave_perception_and_others_survive(
    ws: Path, tmp_path: Path
) -> None:
    before_snap = tmp_path / "before.json"
    code, _out, err = _run(
        _base(ws, tmp_path / "b") + STATIC_COLLECTORS + ["--snapshot", str(before_snap)]
    )
    assert code == 0, err
    before = _signal_dicts(before_snap)
    assert len(before) >= 3, (
        f"fixture too weak: need >=3 static signals, got {len(before)} -- the rest of "
        "this test would be vacuous"
    )

    # Suppress exactly the vendor-pathed signals; keep the others as the control group.
    suppressed = [s for s in before if str(s.get("path") or "").startswith("vendor")]
    assert suppressed, f"fixture produced no vendor-pathed signal: {before}"
    bl = _write_baseline(tmp_path / "bl.json", suppressed)

    after_snap = tmp_path / "after.json"
    code, _out, err = _run(
        _base(ws, tmp_path / "a")
        + STATIC_COLLECTORS
        + ["--baseline", str(bl), "--snapshot", str(after_snap)]
    )
    assert code == 0, err

    before_ids = _identities(before_snap)
    after_ids = _identities(after_snap)
    bl_ids = {tuple(s.get(k) for k in _IDENTITY_KEYS) for s in suppressed}

    assert [i for i in after_ids if i in bl_ids] == [], (
        f"a baselined identity survived suppression: {after_ids}"
    )
    assert [i for i in before_ids if i not in bl_ids and i not in after_ids] == [], (
        "a signal absent from the baseline was wrongly suppressed; "
        f"before={before_ids} after={after_ids}"
    )
    assert after_ids, "the control group is empty -- fixture must keep some survivors"


def test_b4_workspace_root_survives_and_order_is_preserved(
    ws: Path, tmp_path: Path
) -> None:
    before_snap = tmp_path / "before.json"
    _run(_base(ws, tmp_path / "b") + STATIC_COLLECTORS + ["--snapshot", str(before_snap)])
    before = _signal_dicts(before_snap)
    bl = _write_baseline(
        tmp_path / "bl.json",
        [s for s in before if str(s.get("path") or "").startswith("vendor")],
    )
    after_snap = tmp_path / "after.json"
    _run(
        _base(ws, tmp_path / "a")
        + STATIC_COLLECTORS
        + ["--baseline", str(bl), "--snapshot", str(after_snap)]
    )

    assert _doc(after_snap)["workspace_root"] == _doc(before_snap)["workspace_root"], (
        "workspace_root must survive the rebuild verbatim"
    )
    assert _is_subsequence(_identities(after_snap), _identities(before_snap)), (
        "survivors must be a SUBSEQUENCE of the unfiltered run (collector order kept); "
        f"after={_identities(after_snap)} before={_identities(before_snap)}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- suppression reaches synthesis, not just the record.
# ---------------------------------------------------------------------------
def test_b5_a_baseline_covering_everything_empties_perception_and_still_exits_zero(
    ws: Path, tmp_path: Path
) -> None:
    before_snap = tmp_path / "before.json"
    _run(_base(ws, tmp_path / "b") + STATIC_COLLECTORS + ["--snapshot", str(before_snap)])
    everything = _signal_dicts(before_snap)
    assert everything, "fixture produced nothing to suppress"
    bl = _write_baseline(tmp_path / "all.json", everything)

    after_snap = tmp_path / "after.json"
    code, out, err = _run(
        _base(ws, tmp_path / "a")
        + STATIC_COLLECTORS
        + ["--baseline", str(bl), "--snapshot", str(after_snap)]
    )
    assert code == 0, f"total suppression must not crash the autonomous verb; err={err!r}"
    assert _doc(after_snap)["signals"] == [], (
        f"total suppression left signals in the record: {_doc(after_snap)['signals']}"
    )
    line = _announce_lines(out)
    assert len(line) == 1, line
    m = _ANNOUNCE_RE.search(out)
    assert m is not None and m.group("n") == m.group("m"), (
        f"a total suppression must report N == M; got {line}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- exactly one deterministic announce line, iff the flag is supplied.
# ---------------------------------------------------------------------------
def test_b6_announce_line_has_the_specified_shape_and_names_the_path_as_typed(
    ws: Path, tmp_path: Path
) -> None:
    bl = _write_baseline(tmp_path / "bl.json", [])
    code, out, err = _run(_base(ws, tmp_path / "s") + ["--baseline", str(bl)])
    assert code == 0, err

    lines = _announce_lines(out)
    assert len(lines) == 1, f"expected EXACTLY one announce line, got {lines}"
    m = _ANNOUNCE_RE.search(out)
    assert m is not None, (
        "the line must read 'perception suppressed <N> of <M> signals by baseline: "
        f"<path>'; got {lines[0]!r}"
    )
    assert m.group("path") == str(bl), (
        f"the line must name the path the operator typed; got {m.group('path')!r}"
    )
    assert _announce_lines(err) == [], f"the line must not be duplicated on stderr: {err!r}"


def test_b6_the_line_is_deterministic_across_two_identical_invocations(
    ws: Path, tmp_path: Path
) -> None:
    bl = _write_baseline(tmp_path / "bl.json", [])
    _c1, out1, _ = _run(_base(ws, tmp_path / "s1") + ["--baseline", str(bl)])
    _c2, out2, _ = _run(_base(ws, tmp_path / "s2") + ["--baseline", str(bl)])
    assert _announce_lines(out1) == _announce_lines(out2), "the announce line is unstable"


def test_b6_each_of_the_three_flags_alone_prints_only_its_own_line(
    ws: Path, tmp_path: Path
) -> None:
    bl = _write_baseline(tmp_path / "bl.json", [])
    arms = {
        "collector": (["--collector", "todos"], COLLECTOR_PREFIX),
        "exclude": (["--exclude-path", "vendor/*"], EXCLUDE_PREFIX),
        "baseline": (["--baseline", str(bl)], SUPPRESS_PREFIX),
    }
    for name, (extra, own) in arms.items():
        code, out, err = _run(_base(ws, tmp_path / name) + extra)
        assert code == 0, f"{name}: {err!r}"
        for prefix in (COLLECTOR_PREFIX, EXCLUDE_PREFIX, SUPPRESS_PREFIX):
            got = _announce_lines(out, prefix)
            expected = 1 if prefix == own else 0
            assert len(got) == expected, (
                f"{name}-only run: expected {expected} {prefix!r} line(s), got {got}"
            )


# ---------------------------------------------------------------------------
# Behavior 7 -- a valid baseline that suppresses nothing still reports.
# ---------------------------------------------------------------------------
def test_b7_an_empty_signals_array_is_valid_and_reports_zero(
    ws: Path, tmp_path: Path
) -> None:
    """``is not None``, not truthiness: an empty user-supplied document is a real answer."""
    bl = _write_baseline(tmp_path / "empty.json", [])
    ref_snap, snap = tmp_path / "ref.json", tmp_path / "s.json"
    _run(_base(ws, tmp_path / "r") + ["--snapshot", str(ref_snap)])
    code, out, err = _run(
        _base(ws, tmp_path / "s") + ["--baseline", str(bl), "--snapshot", str(snap)]
    )
    assert code == 0, f"an empty baseline is valid, not an error; stderr={err!r}"
    m = _ANNOUNCE_RE.search(out)
    assert m is not None, f"the report must still be printed; stdout={out!r}"
    assert m.group("n") == "0", f"an empty baseline suppresses nothing; got {m.group('n')}"
    assert int(m.group("m")) == len(_signal_dicts(ref_snap)), (
        "the denominator must be the full collected count"
    )


def test_b7_a_baseline_of_foreign_identities_suppresses_nothing(
    ws: Path, tmp_path: Path
) -> None:
    """Staleness fails toward REPORTING: an entry matching nothing live is noise, never
    a missed finding."""
    foreign = _write_baseline(
        tmp_path / "foreign.json",
        [
            {
                "source": "todos",
                "kind": "todo",
                "summary": "TODO: nothing like this exists",
                "detail": "# TODO: nothing like this exists",
                "path": "no/such/file.py:99",
                "weight": 1.0,
            }
        ],
    )
    ref_snap, snap = tmp_path / "ref.json", tmp_path / "s.json"
    _run(_base(ws, tmp_path / "r") + STATIC_COLLECTORS + ["--snapshot", str(ref_snap)])
    code, out, _err = _run(
        _base(ws, tmp_path / "s")
        + STATIC_COLLECTORS
        + ["--baseline", str(foreign), "--snapshot", str(snap)]
    )
    assert code == 0
    m = _ANNOUNCE_RE.search(out)
    assert m is not None and m.group("n") == "0", f"got {out!r}"
    assert _identities(snap) == _identities(ref_snap), (
        "a non-matching baseline entry must not remove anything"
    )


# ---------------------------------------------------------------------------
# Behavior 8 -- announce order is source, then location, then instance.
# ---------------------------------------------------------------------------
def test_b8_announce_order_is_source_then_location_then_instance(
    ws: Path, tmp_path: Path
) -> None:
    bl = _write_baseline(tmp_path / "bl.json", [])
    code, out, err = _run(
        _base(ws, tmp_path / "s")
        + [
            "--collector",
            "todos",
            "--exclude-path",
            "vendor/*",
            "--baseline",
            str(bl),
        ]
    )
    assert code == 0, err
    order = [
        ln.split(" by ")[0] if " by " in ln else ln
        for ln in out.splitlines()
        if ln.startswith("perception ")
    ]
    assert len(order) == 3, f"all three announces must be present; got {order}"
    idx = {
        "narrowed": out.index(COLLECTOR_PREFIX),
        "excluded": out.index(EXCLUDE_PREFIX),
        "suppressed": out.index(SUPPRESS_PREFIX),
    }
    assert idx["narrowed"] < idx["excluded"] < idx["suppressed"], (
        f"order must be source -> location -> instance; got offsets {idx}"
    )


# ---------------------------------------------------------------------------
# Behavior 9 -- logical AND; changes what RUNS not at all.
# ---------------------------------------------------------------------------
def test_b9_denominator_equals_an_otherwise_identical_run_without_the_flag(
    ws: Path, tmp_path: Path
) -> None:
    """Every collector still RUNS -- the flag subtracts afterwards."""
    ref_snap = tmp_path / "ref.json"
    _run(_base(ws, tmp_path / "r") + ["--snapshot", str(ref_snap)])
    bl = _write_baseline(tmp_path / "bl.json", [])
    _code, out, _err = _run(_base(ws, tmp_path / "s") + ["--baseline", str(bl)])
    m = _ANNOUNCE_RE.search(out)
    assert m is not None, out
    assert int(m.group("m")) == len(_signal_dicts(ref_snap)), (
        "M must equal the signal count of the same run with no --baseline"
    )


def test_b9_denominator_is_unchanged_by_a_baseline_that_suppresses_everything(
    ws: Path, tmp_path: Path
) -> None:
    before_snap = tmp_path / "before.json"
    _run(_base(ws, tmp_path / "b") + STATIC_COLLECTORS + ["--snapshot", str(before_snap)])
    n_before = len(_signal_dicts(before_snap))
    bl = _write_baseline(tmp_path / "all.json", _signal_dicts(before_snap))
    _code, out, _err = _run(
        _base(ws, tmp_path / "a") + STATIC_COLLECTORS + ["--baseline", str(bl)]
    )
    m = _ANNOUNCE_RE.search(out)
    assert m is not None and int(m.group("m")) == n_before, (
        f"collection must be untouched: expected M={n_before}, got {out!r}"
    )


def test_b9_composes_with_exclude_path_as_an_intersection(
    ws: Path, tmp_path: Path
) -> None:
    before_snap = tmp_path / "before.json"
    _run(_base(ws, tmp_path / "b") + STATIC_COLLECTORS + ["--snapshot", str(before_snap)])
    before = _signal_dicts(before_snap)
    # Baseline suppresses the two ``.``-rooted repo-level signals; the glob excludes the
    # vendor subtree. Neither alone yields what both together do.
    bl = _write_baseline(
        tmp_path / "bl.json", [s for s in before if s.get("path") == "."]
    )
    snaps = {}
    for name, extra in (
        ("excl", ["--exclude-path", "vendor/*"]),
        ("base", ["--baseline", str(bl)]),
        ("both", ["--exclude-path", "vendor/*", "--baseline", str(bl)]),
    ):
        out_path = tmp_path / f"{name}.json"
        code, _o, err = _run(
            _base(ws, tmp_path / name)
            + STATIC_COLLECTORS
            + extra
            + ["--snapshot", str(out_path)]
        )
        assert code == 0, f"{name}: {err!r}"
        snaps[name] = set(_identities(out_path))

    assert snaps["both"] == snaps["excl"] & snaps["base"], (
        "combining the two flags must yield exactly the intersection; "
        f"both={sorted(snaps['both'])} excl={sorted(snaps['excl'])} "
        f"base={sorted(snaps['base'])}"
    )
    assert snaps["both"] != snaps["excl"] and snaps["both"] != snaps["base"], (
        "fixture too weak: each flag must remove something the other does not"
    )


# ---------------------------------------------------------------------------
# Behavior 10 -- a missing or malformed baseline is a usage error BEFORE collection.
# ---------------------------------------------------------------------------
def _malformed(tmp_path: Path) -> dict[str, Path]:
    """One file per malformed arm named in the spec, plus the missing-path arm."""
    not_json = tmp_path / "not_json.json"
    not_json.write_text("not json at all", encoding="utf-8")
    not_object = tmp_path / "not_object.json"
    not_object.write_text("[1, 2, 3]", encoding="utf-8")
    no_signals = tmp_path / "no_signals.json"
    no_signals.write_text('{"workspace_root": "x"}', encoding="utf-8")
    missing_key = tmp_path / "missing_key.json"
    missing_key.write_text(
        json.dumps(
            {
                "workspace_root": "x",
                "signals": [
                    {
                        "source": "todos",
                        "kind": "todo",
                        "summary": "s",
                        "detail": "d",
                        "path": "a.py:1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return {
        "not_a_regular_file": tmp_path / "does_not_exist.json",
        "not_valid_json": not_json,
        "not_an_object": not_object,
        "no_signals_array": no_signals,
        "entry_missing_an_identity_key": missing_key,
    }


@pytest.mark.parametrize(
    "arm",
    [
        "not_a_regular_file",
        "not_valid_json",
        "not_an_object",
        "no_signals_array",
        "entry_missing_an_identity_key",
    ],
)
def test_b10_a_malformed_baseline_is_exit_2_with_empty_stdout(
    arm: str, ws: Path, tmp_path: Path
) -> None:
    bad = _malformed(tmp_path)[arm]
    state = tmp_path / f"state_{arm}"
    code, out, err = _run(_base(ws, state) + ["--baseline", str(bad)])

    assert code == 2, f"{arm}: expected exit 2, got {code} (stderr={err!r})"
    assert out == "", f"{arm}: stdout must be EMPTY, got {out!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, f"{arm}: expected exactly one stderr line, got {err_lines}"
    assert err_lines[0].startswith("error: "), f"{arm}: got {err_lines[0]!r}"
    assert "baseline file" in err_lines[0], (
        f"{arm}: the message must name the argument the operator typed; got {err_lines[0]!r}"
    )
    assert str(bad) in err_lines[0], f"{arm}: the message must name the path; got {err_lines[0]!r}"


@pytest.mark.parametrize(
    "arm",
    [
        "not_a_regular_file",
        "not_valid_json",
        "not_an_object",
        "no_signals_array",
        "entry_missing_an_identity_key",
    ],
)
def test_b10_the_load_happens_before_collection_so_no_artifact_is_created(
    arm: str, ws: Path, tmp_path: Path
) -> None:
    """A bad path must cost nothing and can never buy a real dispatch."""
    bad = _malformed(tmp_path)[arm]
    state = tmp_path / f"state_{arm}"
    snap = tmp_path / "never_written.json"
    code, _out, _err = _run(
        _base(ws, state) + ["--baseline", str(bad), "--snapshot", str(snap)]
    )
    assert code == 2
    assert not state.exists(), f"{arm}: a run directory was created at {state}"
    assert not snap.exists(), f"{arm}: a snapshot was written despite the usage error"


def test_b10_a_directory_is_rejected_as_not_a_regular_file(
    ws: Path, tmp_path: Path
) -> None:
    a_dir = tmp_path / "a_directory.json"
    a_dir.mkdir()
    code, out, err = _run(_base(ws, tmp_path / "st") + ["--baseline", str(a_dir)])
    assert code == 2, f"a directory must be rejected; got {code} / {err!r}"
    assert out == ""
    assert "baseline file" in err


# ---------------------------------------------------------------------------
# Behavior 11 -- documented in run --help, naming neither banned literal.
# ---------------------------------------------------------------------------
def _baseline_entry(help_text: str) -> str:
    """The ``--baseline`` options entry: everything from its LAST occurrence onward.

    ``--baseline FILE`` appears twice in ``run --help`` -- once in the wrapped usage
    line and once as the options entry -- and the entry is last because the flag is
    declared last.
    """
    return help_text[help_text.rindex("--baseline") :]


def test_b11_help_documents_the_flag_in_suppression_terms() -> None:
    code, out, _err = _run(["run", "--help"])
    assert code == 0
    entry = _baseline_entry(out)
    flat = " ".join(entry.split())
    assert "suppress" in flat.lower(), (
        "the entry must describe the flag in perception/suppression terms; got:\n" + flat[:400]
    )
    assert "FILE" in entry, "the entry must name its FILE argument"


def test_b11_help_prose_names_neither_json_nor_exclude_path() -> None:
    """Two shipped oracles locate their own entry with ``rindex`` and grade what FOLLOWS.

    ``tests/test_iter158_behavior.py::test_b09_run_help_documents_json`` grades the 240
    chars after ``rindex("--json")`` and
    ``tests/test_iter227_behavior.py::test_b11_help_documents_the_flag_without_naming_json``
    grades everything after ``rindex("--exclude-path")``. Because ``--baseline`` is
    declared LAST, either literal appearing in its prose would move those anchors into
    this flag's text and make a green test grade the wrong string.
    """
    code, out, _err = _run(["run", "--help"])
    assert code == 0
    entry = _baseline_entry(out)
    assert "--json" not in entry, (
        "the --baseline entry must not contain the literal '--json'; it would move "
        "test_iter158's rindex anchor. Entry:\n" + entry
    )
    assert "--exclude-path" not in entry, (
        "the --baseline entry must not contain the literal '--exclude-path'; it would "
        "move test_iter227's rindex anchor. Entry:\n" + entry
    )
    # The invariant those oracles actually depend on, asserted directly.
    assert out.rindex("--json") < out.rindex("--baseline"), (
        "the last '--json' occurrence must stay ABOVE the --baseline entry"
    )
    assert out.rindex("--exclude-path") < out.rindex("--baseline"), (
        "the last '--exclude-path' occurrence must stay ABOVE the --baseline entry"
    )


def test_b11_help_names_the_producer_without_a_banned_literal() -> None:
    """The round trip is taught with ``--snapshot``, the flag that writes this schema."""
    _code, out, _err = _run(["run", "--help"])
    entry = " ".join(_baseline_entry(out).split())
    assert "--snapshot" in entry, (
        "the entry must name the producer of the document it reads; got:\n" + entry[:400]
    )
