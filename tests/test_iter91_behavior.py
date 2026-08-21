"""Black-box behavior tests for iteration 81 (ships as commit-seq **factory iter
91**) --- reject a NON-FINITE ``pla signals --min-weight`` value
(``nan`` / ``inf`` / ``-inf``) at PARSE time via a new ``_finite_float`` argparse
``type=`` validator. This is the LAST unguarded numeric CLI argument: its siblings
already reject bad input at parse time (``--top`` / ``_positive_int``,
``watch --interval`` / ``_non_negative_float`` which iter-40 hardened for exactly
this non-finite class, ``watch --max-scans`` / ``_positive_int``). Before this
change ``--min-weight nan`` / ``inf`` collected the signals, filtered with
``weight >= nan/inf`` (False for every signal), printed ``(no signals collected)``
and exited 0 -- a degenerate no-op reporting success. The guard is FINITE-ONLY
(NOT range-guarded): a finite negative ("show all") and a finite ``> 1.0``
("empty view") stay legal (ROADMAP row #91, SPEC §4.5).

ISOLATION CONTRACT (honored): these tests are written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, ``ROADMAP.md`` --- and the test conventions already public under
``tests/`` (``test_iter88_behavior.py`` introduced ``--min-weight``;
``test_iter40_behavior.py`` is the ``watch --interval`` non-finite twin). They
drive ONLY documented public surfaces: the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (observable stdout/stderr/exit codes),
``build_parser()``, and the module-level ``_finite_float`` argparse validator
called directly (mirrors how the suite unit-tests the sibling validators).
**No file under ``src/`` was read, no engineer/reviewer note was read, and no
``git diff`` was consulted.** Every test is fully offline/deterministic: the
workspace is built in ``tmp_path`` (no LLM, no network, no git activity).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from proactive_loop import __version__
from proactive_loop.cli import _finite_float, build_parser, main
from proactive_loop.collectors import all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry

_EMPTY_MARKER = "(no signals collected)"


# ---------------------------------------------------------------------------
# Black-box helpers (public CLI / public validator only).
# ---------------------------------------------------------------------------


def _make_ws(tmp_path: Path) -> Path:
    """A tmp workspace with a non-empty, deterministic collectable signal set.

    Produces (probed via the public CLI): a `note` (# heading), a `todo`
    (TODO: ...), two `recent_file`s, a `ci_config` (no CI), and a `test_posture`
    signal -- a mix of weights (0.7 / 0.8 / 1.0), all >= -1.0, min 0.7. No `.git`,
    so no git-activity noise: the signal set is stable across runs in one test.
    """
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "n.md").write_text("# Heading\n\nSome paragraph text about the project.\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1  # TODO: wire retry\n")
    return tmp_path


def _run(argv, capsys):
    """Invoke the CLI expecting a normal return; return (rc, stdout, stderr)."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _run_exit(argv, capsys):
    """Invoke the CLI expecting a SystemExit; return (code, stdout, stderr)."""
    capsys.readouterr()
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    cap = capsys.readouterr()
    return excinfo.value.code, cap.out, cap.err


def _signals(argv, capsys):
    """Run a `--json` signals invocation and return its `signals` list."""
    rc, out, err = _run(argv, capsys)
    assert rc == 0, f"expected exit 0; rc={rc} stderr={err!r}"
    return json.loads(out)["signals"]


# ===========================================================================
# Behavior 1 -- `--min-weight nan` -> exit 2 at parse time, no signal stdout,
# stderr names `--min-weight` and `finite`.
# ===========================================================================


def test_b01_nan_rejected_at_parse_time_no_stdout(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    code, out, err = _run_exit(["signals", "--workspace", str(ws), "--min-weight", "nan"], capsys)
    assert code == 2, f"--min-weight nan must exit 2 (parse-time); got {code}"
    # No signal output leaks to stdout on a parse error.
    assert out == "", f"nothing may reach stdout on a parse error; got {out!r}"
    assert "## " not in out and _EMPTY_MARKER not in out
    # The rejection names the argument and the finite constraint.
    assert "--min-weight" in err, f"stderr must name --min-weight; got:\n{err}"
    assert "finite" in err, f"stderr must explain the finite rule; got:\n{err}"


# ===========================================================================
# Behavior 2 -- `--min-weight inf` -> exit 2, same class of argparse usage error.
# ===========================================================================


def test_b02_inf_rejected_at_parse_time_no_stdout(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    code, out, err = _run_exit(["signals", "--workspace", str(ws), "--min-weight", "inf"], capsys)
    assert code == 2, f"--min-weight inf must exit 2 (parse-time); got {code}"
    assert out == "", f"nothing may reach stdout on a parse error; got {out!r}"
    assert "--min-weight" in err and "finite" in err, f"got:\n{err}"


# ===========================================================================
# Behavior 3 -- `--min-weight=-inf` (`=` form) -> exit 2, rejected as NON-FINITE
# (not as negative). The two-token `--min-weight -inf` would be swallowed by
# argparse as an unknown option, so the `=` form is used to reach the validator.
# ===========================================================================


def test_b03_negative_inf_rejected_as_non_finite(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    code, out, err = _run_exit(["signals", "--workspace", str(ws), "--min-weight=-inf"], capsys)
    assert code == 2, f"--min-weight=-inf must exit 2; got {code}"
    assert out == ""
    assert "--min-weight" in err and "finite" in err, f"got:\n{err}"
    # Pin: rejected as NON-FINITE, not via a `< 0.0` finite-negative branch.
    assert "negative" not in err.lower(), (
        f"-inf must be rejected as non-finite, NOT as negative; got:\n{err}"
    )


# ===========================================================================
# Behavior 4 -- a finite NEGATIVE threshold is STILL ACCEPTED and keeps the FULL
# unfiltered set (proves the guard is finite-only, does NOT reject negatives).
# ===========================================================================


def test_b04_finite_negative_accepted_keeps_full_set(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    full = _signals(["signals", "--workspace", str(ws), "--json"], capsys)
    negged = _signals(["signals", "--workspace", str(ws), "--min-weight=-1.0", "--json"], capsys)
    assert len(full) >= 1, "fixture workspace must produce at least one signal"
    # A negative threshold keeps every signal (>= holds for all): byte-identical.
    assert negged == full, "a finite negative --min-weight must keep the full unfiltered set"


# ===========================================================================
# Behavior 5 -- a finite value `> 1.0` is STILL ACCEPTED and empties the view
# WITHOUT erroring (proves the guard does NOT range-check).
# ===========================================================================


def test_b05_finite_above_one_accepted_empties_view_json(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    empty = _signals(["signals", "--workspace", str(ws), "--min-weight", "5.0", "--json"], capsys)
    assert empty == [], f"an impossibly-high finite bound must empty the view; got {empty!r}"


def test_b05_finite_above_one_accepted_empties_view_human(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    rc, out, err = _run(["signals", "--workspace", str(ws), "--min-weight", "5.0"], capsys)
    assert rc == 0, f"a finite > 1.0 threshold must exit 0 (no error); stderr={err!r}"
    assert out.strip() == _EMPTY_MARKER, f"human view must show the empty marker; got {out!r}"


# ===========================================================================
# Behavior 6 -- a valid in-range finite value filters inclusively (weight >=
# threshold) and is unchanged from the pre-change filter semantics.
# ===========================================================================


def test_b06_valid_finite_filters_inclusive_json(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    full = _signals(["signals", "--workspace", str(ws), "--json"], capsys)
    threshold = 0.75  # partitions the fixture set (min weight 0.7)
    got = _signals(["signals", "--workspace", str(ws), "--min-weight", "0.75", "--json"], capsys)
    expected = [s for s in full if s["weight"] >= threshold]
    # Exactly the survivors of an inclusive `weight >= 0.75`, same order.
    assert got == expected, f"filter must be inclusive >= and match pre-change semantics"
    # Discriminating: the filter actually dropped at least one and kept at least one.
    assert 0 < len(got) < len(full), (
        f"threshold 0.75 must partition the set; full={len(full)} got={len(got)}"
    )


def test_b06_valid_finite_filters_inclusive_human(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    rc, out, err = _run(["signals", "--workspace", str(ws), "--min-weight", "0.75"], capsys)
    assert rc == 0, f"stderr={err!r}"
    # The below-threshold test_posture signal (weight 0.7) is dropped from the
    # human view; a weight-1.0 todo survives.
    assert "untested" not in out, "below-threshold (0.7) signal must be filtered out"
    assert "TODO: wire retry" in out, "an above-threshold (1.0) signal must survive"


# ===========================================================================
# Behavior 7 -- a NON-NUMERIC value is still an argparse usage error (unchanged).
# ===========================================================================


def test_b07_non_numeric_still_exit2_no_stdout(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    code, out, _err = _run_exit(["signals", "--workspace", str(ws), "--min-weight", "abc"], capsys)
    assert code == 2, "a non-numeric --min-weight must remain an exit-2 usage error"
    assert out == "", f"nothing may reach stdout on a parse error; got {out!r}"


def test_b07_parse_error_fires_before_workspace_check(capsys):
    # A bad --min-weight is rejected at PARSE time, BEFORE the workspace guard --
    # so even a missing workspace still exits 2 (parse error wins), no stdout.
    code, out, _err = _run_exit(
        ["signals", "--workspace", "/no/such/dir", "--min-weight", "nan"], capsys
    )
    assert code == 2
    assert out == ""


# ===========================================================================
# Behavior 8 -- omitting --min-weight is unchanged; no public-surface growth /
# version lock; --min-weight still AND-composes with --kind.
# ===========================================================================


def test_b08_default_omitted_is_none_and_full_set(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    ns = build_parser().parse_args(["signals", "--workspace", str(ws)])
    assert ns.min_weight is None, "omitting --min-weight must default to None (no filtering)"
    # The default (no flag) view is the same full set as an all-passing threshold.
    default = _signals(["signals", "--workspace", str(ws), "--json"], capsys)
    allpass = _signals(["signals", "--workspace", str(ws), "--min-weight=-1.0", "--json"], capsys)
    assert default == allpass and len(default) >= 1


def test_b08_and_composition_with_kind_unchanged(tmp_path, capsys):
    ws = _make_ws(tmp_path)
    # --kind alone narrows by kind.
    only_todo = _signals(["signals", "--workspace", str(ws), "--kind", "todo", "--json"], capsys)
    assert {s["kind"] for s in only_todo} == {"todo"} and len(only_todo) >= 1
    # --kind AND a finite --min-weight compose (logical AND); still only todos.
    both = _signals(
        ["signals", "--workspace", str(ws), "--kind", "todo", "--min-weight", "0.5", "--json"],
        capsys,
    )
    assert {s["kind"] for s in both} <= {"todo"}


def test_b08_registry_counts_and_version_unchanged():
    assert len(all_collectors()) == 17
    assert len(ToolRegistry.tool_names()) == 14
    assert len(VALID_PROVIDERS) == 7
    assert __version__ == "0.1.1"


def test_b08_subparser_choice_count_unchanged():
    parser = build_parser()
    sub_actions = [
        a for a in parser._subparsers._group_actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(sub_actions) == 1
    assert len(sub_actions[0].choices) == 17
    assert "signals" in sub_actions[0].choices


# ===========================================================================
# Behavior 9 -- the `_finite_float` validator called DIRECTLY: raises
# ArgumentTypeError for non-finite (any case), returns the parsed float for
# finite inputs, and lets a non-number's ValueError propagate (argparse -> exit 2).
# ===========================================================================


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "NaN", "Inf", "INF", "-INF", "Infinity"])
def test_b09_direct_non_finite_raises_argument_type_error(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        _finite_float(bad)


@pytest.mark.parametrize("raw,expected", [("0.5", 0.5), ("-1", -1.0), ("5", 5.0), ("0", 0.0)])
def test_b09_direct_finite_returns_float_unchanged(raw, expected):
    value = _finite_float(raw)
    assert value == expected
    assert isinstance(value, float)


def test_b09_direct_non_number_raises_value_error():
    # A non-number raises ValueError (argparse converts it to the exit-2 usage
    # error); the validator does NOT catch it, mirroring the sibling validators.
    with pytest.raises(ValueError):
        _finite_float("abc")


# ===========================================================================
# Edge -- an overflowing finite-looking literal (1e400 -> inf) is also rejected
# as non-finite. A superset of the spec; the exact silent-empty harm targeted.
# ===========================================================================


def test_edge_overflow_literal_rejected_as_non_finite():
    with pytest.raises(argparse.ArgumentTypeError):
        _finite_float("1e400")
