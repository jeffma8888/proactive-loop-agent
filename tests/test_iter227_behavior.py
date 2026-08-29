"""Black-box oracle for factory iteration 249 -- ``pla run --exclude-path GLOB``.

The LOCATION half of ``run``'s perception filter. Iteration 245 gave the product's only
autonomous verb the ``--collector`` allowlist (narrowing by WHICH collector runs) and
deliberately left "where it looks" unbought, so ``scan``/``signals`` carried
``--exclude-path`` while ``run`` silently dropped the scoping a user had armed on
``scan``. This module drives the CLI boundary only and asserts observable output.

Expected Behaviors covered (numbered as in the iteration spec):

1.  ``--exclude-path`` is accepted on ``run``: repeatable (``append``),
    ``dest="exclude_path"``, ``metavar="GLOB"``, default ``None`` when absent.
2.  A bare ``run`` is unchanged -- no narrowing line on stdout OR stderr, and its stdout
    equals the filtered run's stdout with the one announce line removed.
3.  Signals whose path matches the glob are absent from the perceived snapshot; every
    non-matching signal survives.
4.  ``--exclude-path '*'`` is survivable: it empties perception and the verb still
    completes cleanly rather than crashing. (See the module note on behavior 4 --
    the ``path is None`` case is not reachable from the CLI.)
5.  Repeated flags compose with OR semantics.
6.  ``run`` and the ``signals`` verb select the IDENTICAL set for the same globs over
    the same workspace -- one shared matcher, no second implementation. Checked across
    the four matcher properties the help text advertises.
7.  The filter runs before the snapshot document is written, so ``--snapshot`` records
    the FILTERED perception and ``--dry-run`` inherits it.
8.  ``workspace_root`` survives verbatim and collector order is preserved (the kept
    signals are a SUBSEQUENCE of the unfiltered ones).
9.  Every collector still RUNS -- the announce line's denominator equals the bare run's
    signal count -- so the flag composes with ``--collector`` as a logical AND.
10. When and only when the flag is supplied, exactly ONE deterministic narrowing line is
    printed, with globs rendered ``sorted(set(...))`` so flag order and repetition
    cannot change it; it is a separate line from the ``--collector`` announce, and under
    ``--json`` it goes to stderr leaving the payload's key set untouched.
11. ``run --help`` documents ``--exclude-path`` and that help text does NOT contain the
    literal ``--json`` (``tests/test_iter158_behavior.py`` locates the ``--json`` entry
    with ``rindex``, so a later option naming it would make that oracle grade the wrong
    string).
12. An empty/whitespace-only pattern is a usage error (exit 2, empty stdout).
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

#: The narrowing line's stable ASCII prefix -- matched, never reconstructed.
EXCLUDE_PREFIX = "perception excluded"

#: iteration 245's sibling announce, asserted UNCHANGED by a ``--collector``-only run.
COLLECTOR_PREFIX = "perception narrowed"

#: Run-scoped goal ids, which churn between two otherwise identical invocations.
_ID_RE = re.compile(r"\b[0-9a-f]{12}\b")


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


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """A workspace holding a vendored subtree several collectors perceive.

    Measured shape (8 signals): repo-level ``ci_config``/``license``/``test_posture``
    at ``.``, a ``test_posture`` at ``vendor``, ``recent_file`` + ``todo`` for each of
    ``a.py`` and ``vendor/v.py``. Nothing below pins that exact set -- it is
    collector-set sensitive -- only relations between two runs over the SAME tree.
    """
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


def _snapshot_keys(path: Path) -> list[tuple[str, str | None]]:
    """``(kind, path)`` for every signal in a ``--snapshot`` document, IN ORDER."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [(s["kind"], s.get("path")) for s in doc["signals"]]


def _announce_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith(EXCLUDE_PREFIX)]


def _normalize(text: str, *, state: Path) -> str:
    """Strip the two things that legitimately churn: goal ids and the state path."""
    return _ID_RE.sub("<id>", text.replace(str(state), "<state>"))


def _is_subsequence(small: list[object], big: list[object]) -> bool:
    it = iter(big)
    return all(item in it for item in small)


# ---------------------------------------------------------------------------
# Behavior 1 -- the flag exists on ``run`` with the specified argparse shape.
# ---------------------------------------------------------------------------
def test_b1_flag_is_repeatable_appends_and_defaults_to_none() -> None:
    parser = build_parser()

    absent = parser.parse_args(["run", "--workspace", "W"])
    assert absent.exclude_path is None, (
        "with the flag ABSENT the dest must be None so the filter block is skipped "
        f"entirely; got {absent.exclude_path!r}"
    )

    once = parser.parse_args(["run", "--workspace", "W", "--exclude-path", "vendor/*"])
    assert once.exclude_path == ["vendor/*"], f"got {once.exclude_path!r}"

    twice = parser.parse_args(
        ["run", "--workspace", "W", "--exclude-path", "a/*", "--exclude-path", "b/*"]
    )
    assert twice.exclude_path == ["a/*", "b/*"], (
        f"the flag must be action='append', not overwrite; got {twice.exclude_path!r}"
    )


def test_b1_usage_line_advertises_the_glob_metavar() -> None:
    code, out, _err = _run(["run", "--help"])
    assert code == 0
    assert "[--exclude-path GLOB]" in out, (
        "the usage line must show metavar='GLOB'; got:\n" + out[:400]
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- a bare run is untouched.
# ---------------------------------------------------------------------------
def test_b2_bare_run_prints_no_narrowing_line_on_either_stream(
    ws: Path, tmp_path: Path
) -> None:
    state = tmp_path / "bare"
    code, out, err = _run(_base(ws, state))
    assert code == 0, f"bare run must still exit 0; stderr={err!r}"
    assert _announce_lines(out) == [], f"stdout gained a narrowing line: {out!r}"
    assert _announce_lines(err) == [], f"stderr gained a narrowing line: {err!r}"


def test_b2_bare_stdout_equals_filtered_stdout_minus_the_one_announce_line(
    ws: Path, tmp_path: Path
) -> None:
    """The strongest in-suite proxy for "byte-identical to the pre-change baseline".

    A tester cannot run the pre-change build, so this pins the next best invariant: the
    ONLY difference the feature may make to a filtered run's stdout is the single
    announce line. Remove it and the two transcripts must match exactly, once the two
    things that legitimately churn between runs (goal ids, the state dir path) are
    normalized.
    """
    bare_state, filt_state = tmp_path / "b", tmp_path / "f"
    code_b, out_b, _ = _run(_base(ws, bare_state))
    code_f, out_f, _ = _run(_base(ws, filt_state) + ["--exclude-path", "zzz-nothing/*"])
    assert (code_b, code_f) == (0, 0)

    stripped = "\n".join(
        ln for ln in out_f.splitlines() if not ln.startswith(EXCLUDE_PREFIX)
    )
    assert _normalize(stripped, state=filt_state) == _normalize(
        out_b.rstrip("\n"), state=bare_state
    ), "the feature changed a run's stdout beyond its single announce line"


# ---------------------------------------------------------------------------
# Behavior 3 -- matching signals leave perception, non-matching stay.
# ---------------------------------------------------------------------------
def test_b3_matching_paths_are_dropped_and_others_survive(
    ws: Path, tmp_path: Path
) -> None:
    bare_snap, filt_snap = tmp_path / "bare.json", tmp_path / "filt.json"
    _run(_base(ws, tmp_path / "b") + ["--snapshot", str(bare_snap)])
    _run(
        _base(ws, tmp_path / "f")
        + ["--exclude-path", "vendor/*", "--snapshot", str(filt_snap)]
    )
    before, after = _snapshot_keys(bare_snap), _snapshot_keys(filt_snap)

    assert before, "fixture produced no signals -- the rest of this module would be vacuous"
    dropped = [k for k in before if k not in after]
    assert dropped, f"nothing was excluded by 'vendor/*'; snapshot was {before}"
    assert all(
        (p or "").lower().startswith("vendor/") for _kind, p in dropped
    ), f"a signal outside vendor/ was dropped: {dropped}"
    for key in before:
        if key not in dropped:
            assert key in after, f"non-matching signal {key} was wrongly excluded"


def test_b3_a_trailing_line_suffix_does_not_defeat_the_match(
    ws: Path, tmp_path: Path
) -> None:
    """``todo`` signals carry ``a.py:1``; the glob ``a.py`` must still exclude them."""
    snap = tmp_path / "s.json"
    _run(_base(ws, tmp_path / "st") + ["--exclude-path", "a.py", "--snapshot", str(snap)])
    kept = _snapshot_keys(snap)
    assert not [k for k in kept if (k[1] or "").startswith("a.py")], (
        f"'a.py' left a path-with-:LINE signal in perception: {kept}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- total exclusion is survivable.
#
# NOTE ON THE SPEC'S WORDING: the behavior is stated as "a path-less (repo-level)
# signal is NEVER excluded, not even by '*'". The ``path is None`` half is NOT
# reachable from the CLI -- measured over four workspace shapes (empty, plain, the
# vendored fixture, and a ``git init``-ed tree) every emitted signal carries a path,
# and repo-level ones use ``"."``, which '*' DOES match. So this asserts what is
# observable: '*' empties perception and the autonomous verb survives it.
# ---------------------------------------------------------------------------
def test_b4_star_empties_perception_without_crashing(ws: Path, tmp_path: Path) -> None:
    snap = tmp_path / "star.json"
    code, out, err = _run(
        _base(ws, tmp_path / "st") + ["--exclude-path", "*", "--snapshot", str(snap)]
    )
    assert code == 0, f"total exclusion must not crash the verb; stderr={err!r}"
    assert _snapshot_keys(snap) == [], "'*' left signals in the recorded snapshot"
    line = _announce_lines(out)
    assert len(line) == 1 and line[0].endswith("by path: *"), line


def test_b4_help_states_the_no_path_carve_out(ws: Path) -> None:
    """The carve-out is user-facing prose, so pin that it is documented."""
    _code, out, _err = _run(["run", "--help"])
    flat = " ".join(out.split())
    assert "NEVER excluded" in flat, "the no-path carve-out is undocumented"


# ---------------------------------------------------------------------------
# Behavior 5 -- OR semantics across repeats.
# ---------------------------------------------------------------------------
def test_b5_repeated_flags_are_a_union(ws: Path, tmp_path: Path) -> None:
    one, two, both = tmp_path / "1.json", tmp_path / "2.json", tmp_path / "3.json"
    _run(_base(ws, tmp_path / "a") + ["--exclude-path", "a.py", "--snapshot", str(one)])
    _run(
        _base(ws, tmp_path / "b") + ["--exclude-path", "vendor/*", "--snapshot", str(two)]
    )
    _run(
        _base(ws, tmp_path / "c")
        + [
            "--exclude-path",
            "a.py",
            "--exclude-path",
            "vendor/*",
            "--snapshot",
            str(both),
        ]
    )
    kept_one, kept_two, kept_both = (
        set(_snapshot_keys(one)),
        set(_snapshot_keys(two)),
        set(_snapshot_keys(both)),
    )
    assert kept_both == kept_one & kept_two, (
        "two globs must exclude the UNION of what each excludes alone "
        f"(kept: both={sorted(kept_both)} one={sorted(kept_one)} two={sorted(kept_two)})"
    )
    assert kept_both != kept_one and kept_both != kept_two, (
        "fixture is too weak: each glob must exclude something the other does not"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- one shared matcher: run and signals agree, glob for glob.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "glob",
    [
        "vendor/*",  # subtree by explicit glob
        "vendor",  # bare directory name -> whole subtree via ancestor match
        "VENDOR",  # case-insensitive
        "*.py",  # suffix glob, must survive the ':LINE' suffix
        "a.py",  # single file, both its signals
        "zzz-nothing/*",  # matches nothing
        "*",  # matches everything with a path
    ],
)
def test_b6_run_and_signals_select_the_identical_set(
    ws: Path, tmp_path: Path, glob: str
) -> None:
    snap = tmp_path / "run.json"
    code_r, _out, err_r = _run(
        _base(ws, tmp_path / "st") + ["--exclude-path", glob, "--snapshot", str(snap)]
    )
    assert code_r == 0, f"run failed for glob {glob!r}: {err_r!r}"
    code_s, out_s, err_s = _run(
        ["signals", "--workspace", str(ws), "--exclude-path", glob, "--json"]
    )
    assert code_s == 0, f"signals failed for glob {glob!r}: {err_s!r}"
    from_signals = [
        (s["kind"], s.get("path")) for s in json.loads(out_s)["signals"]
    ]
    assert sorted(_snapshot_keys(snap)) == sorted(from_signals), (
        f"run and signals disagree for glob {glob!r} -- there are two matchers"
    )


# ---------------------------------------------------------------------------
# Behaviors 7 + 8 -- position of the filter, and what the rebuild preserves.
# ---------------------------------------------------------------------------
def test_b7_snapshot_document_records_the_filtered_perception(
    ws: Path, tmp_path: Path
) -> None:
    snap = tmp_path / "s.json"
    code, _out, err = _run(
        _base(ws, tmp_path / "st")
        + ["--exclude-path", "vendor/*", "--snapshot", str(snap)]
    )
    assert code == 0, err
    assert snap.exists(), "--snapshot wrote nothing"
    kept = _snapshot_keys(snap)
    assert kept, "the filtered snapshot is empty for a glob that should keep signals"
    assert not [k for k in kept if (k[1] or "").startswith("vendor/")], (
        f"--snapshot recorded the UNFILTERED perception: {kept}"
    )


def test_b8_root_survives_and_collector_order_is_preserved(
    ws: Path, tmp_path: Path
) -> None:
    bare, filt = tmp_path / "b.json", tmp_path / "f.json"
    _run(_base(ws, tmp_path / "b") + ["--snapshot", str(bare)])
    _run(
        _base(ws, tmp_path / "f")
        + ["--exclude-path", "vendor/*", "--snapshot", str(filt)]
    )
    doc_b = json.loads(bare.read_text(encoding="utf-8"))
    doc_f = json.loads(filt.read_text(encoding="utf-8"))
    assert doc_f["workspace_root"] == doc_b["workspace_root"], (
        "the snapshot rebuild lost or rewrote workspace_root"
    )
    assert sorted(doc_f.keys()) == sorted(doc_b.keys()), (
        f"the rebuild changed the document's key set: {sorted(doc_f)} vs {sorted(doc_b)}"
    )
    assert _is_subsequence(_snapshot_keys(filt), _snapshot_keys(bare)), (
        "kept signals are not a subsequence of the unfiltered ones -- collector order "
        f"was not preserved: {_snapshot_keys(filt)} vs {_snapshot_keys(bare)}"
    )


# ---------------------------------------------------------------------------
# Behavior 9 -- collectors all run; the flag ANDs with --collector.
# ---------------------------------------------------------------------------
def test_b9_denominator_is_the_full_unfiltered_signal_count(
    ws: Path, tmp_path: Path
) -> None:
    bare = tmp_path / "b.json"
    _run(_base(ws, tmp_path / "b") + ["--snapshot", str(bare)])
    total = len(_snapshot_keys(bare))
    assert total > 0
    _code, out, _err = _run(_base(ws, tmp_path / "f") + ["--exclude-path", "vendor/*"])
    line = _announce_lines(out)[0]
    assert line.endswith(f"of {total} signals by path: vendor/*"), (
        "the announce denominator must be the FULL collected count -- proof that every "
        f"collector still ran; total={total} line={line!r}"
    )


def test_b9_composes_with_collector_as_a_logical_and(ws: Path, tmp_path: Path) -> None:
    only, both = tmp_path / "o.json", tmp_path / "b.json"
    _run(
        _base(ws, tmp_path / "o")
        + ["--collector", "todos", "--snapshot", str(only)]
    )
    _run(
        _base(ws, tmp_path / "b")
        + [
            "--collector",
            "todos",
            "--exclude-path",
            "vendor/*",
            "--snapshot",
            str(both),
        ]
    )
    kept_only, kept_both = _snapshot_keys(only), _snapshot_keys(both)
    assert all(kind == "todo" for kind, _p in kept_only), kept_only
    assert set(kept_both) < set(kept_only), (
        "AND semantics: the two flags together must keep a strict subset of what "
        f"--collector keeps alone; only={kept_only} both={kept_both}"
    )
    assert not [k for k in kept_both if (k[1] or "").startswith("vendor/")], kept_both


# ---------------------------------------------------------------------------
# Behavior 10 -- exactly one deterministic line, and it does not disturb siblings.
# ---------------------------------------------------------------------------
def test_b10_line_is_invariant_to_flag_order_and_repetition(
    ws: Path, tmp_path: Path
) -> None:
    _c1, out_a, _e = _run(
        _base(ws, tmp_path / "a")
        + ["--exclude-path", "vendor/*", "--exclude-path", "a.py"]
    )
    _c2, out_b, _e = _run(
        _base(ws, tmp_path / "b")
        + [
            "--exclude-path",
            "a.py",
            "--exclude-path",
            "vendor/*",
            "--exclude-path",
            "a.py",
        ]
    )
    line_a, line_b = _announce_lines(out_a), _announce_lines(out_b)
    assert len(line_a) == 1 and len(line_b) == 1, (line_a, line_b)
    assert line_a == line_b, (
        "the line must render sorted(set(globs)) so neither flag order nor a repeat "
        f"can change it: {line_a} vs {line_b}"
    )
    assert line_a[0].endswith("by path: a.py, vendor/*"), line_a


def test_b10_collector_only_run_keeps_its_announce_untouched(
    ws: Path, tmp_path: Path
) -> None:
    _code, out, _err = _run(
        _base(ws, tmp_path / "st") + ["--collector", "todos"]
    )
    assert _announce_lines(out) == [], (
        "a --collector-only run must print NO exclusion line: " + repr(out)
    )
    assert [ln for ln in out.splitlines() if ln.startswith(COLLECTOR_PREFIX)], (
        "iteration 245's own announce line went missing: " + repr(out)
    )


def test_b10_both_announces_appear_as_separate_lines(ws: Path, tmp_path: Path) -> None:
    _code, out, _err = _run(
        _base(ws, tmp_path / "st")
        + ["--collector", "todos", "--exclude-path", "vendor/*"]
    )
    lines = out.splitlines()
    narrowed = [i for i, ln in enumerate(lines) if ln.startswith(COLLECTOR_PREFIX)]
    excluded = [i for i, ln in enumerate(lines) if ln.startswith(EXCLUDE_PREFIX)]
    assert len(narrowed) == 1 and len(excluded) == 1, (narrowed, excluded)
    assert narrowed[0] < excluded[0], (
        "the collector announce must stay first so its own pinned position is unchanged"
    )


def test_b10_under_json_the_line_goes_to_stderr_and_the_payload_is_unchanged(
    ws: Path, tmp_path: Path
) -> None:
    _c, out_plain, _e = _run(_base(ws, tmp_path / "p") + ["--json"])
    code, out, err = _run(
        _base(ws, tmp_path / "f") + ["--exclude-path", "vendor/*", "--json"]
    )
    assert code == 0, err
    payload = json.loads(out)
    assert sorted(payload.keys()) == sorted(json.loads(out_plain).keys()), (
        "the feature changed the --json payload's key set"
    )
    assert _announce_lines(out) == [], "the narrowing line polluted the JSON stdout"
    assert len(_announce_lines(err)) == 1, (
        "under --json the narrowing line must appear on stderr: " + repr(err)
    )


# ---------------------------------------------------------------------------
# Behavior 11 -- help documents the flag, and must not name --json.
# ---------------------------------------------------------------------------
def test_b11_help_documents_the_flag_without_naming_json() -> None:
    code, out, _err = _run(["run", "--help"])
    assert code == 0
    assert "--exclude-path" in out
    start = out.rindex("--exclude-path")
    entry = out[start:]
    assert "--json" not in entry, (
        "the --exclude-path help must not contain the literal '--json': "
        "tests/test_iter158_behavior.py finds the --json entry with rindex('--json') "
        "and grades the 240 chars after it, so a later option naming that flag makes "
        "that oracle read the wrong help string.\n" + entry[:600]
    )
    assert "OUT OF PERCEPTION" in entry or "perception" in entry, entry[:300]


# ---------------------------------------------------------------------------
# Behavior 12 -- an unusable pattern is a usage error, not a silent no-op.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", "   "])
def test_b12_empty_pattern_is_a_usage_error(ws: Path, tmp_path: Path, bad: str) -> None:
    code, out, err = _run(_base(ws, tmp_path / "st") + ["--exclude-path", bad])
    assert code == 2, f"an unusable glob must be exit 2, got {code}; stderr={err!r}"
    assert out == "", f"stdout must stay EMPTY on a refusal, got {out!r}"
    assert "--exclude-path" in err, err
