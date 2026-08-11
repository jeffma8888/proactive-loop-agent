"""Black-box behavior tests for iteration 80 (ships as commit-seq **factory iter
90**) --- ``TodoCollector._collect`` is now DETERMINISTIC: it collects every
todo across the ``os.walk``, sorts the accumulated items by ``(relpath,
lineno)`` ascending (an INTEGER line number), THEN caps at ``max_items`` ---
instead of walking in arbitrary ``os.walk`` order and ``return``-ing early the
moment ``len(signals) >= max_items``. So both WHICH todos survive the cap AND
their emission order are a total, ``os.walk``-order-independent function of the
filesystem, matching the five sibling file-scanning collectors (ROADMAP row #90,
SPEC S4.1).

ISOLATION CONTRACT (honored): these tests were written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, ``ROADMAP.md`` --- and the collector's existing PUBLIC
conventions in ``tests/test_collectors.py`` / ``tests/test_iter83_behavior.py``.
They drive ONLY the public surface
``TodoCollector(...).collect(root) -> list[ContextSignal]`` (plus the public
``all_collectors()`` / ``ToolRegistry`` / ``VALID_PROVIDERS`` /
``build_parser()`` / ``__version__`` registries for the count-lock). **No file
under ``src/`` was read, no engineer/reviewer note was consulted, and no ``git
diff`` was read.** Every test is fully offline/deterministic: real files under a
pytest ``tmp_path``; the one seam monkeypatched
(``proactive_loop.collectors.todos.os.walk``) is the seam the spec names
explicitly, and ``monkeypatch`` auto-restores it.

File naming: the prompt's state-dir iteration is 80, but
``tests/test_iter80_behavior.py`` already exists (an earlier commit-seq
iteration). The repo names behavior files after the COMMIT SEQUENCE, which for
this iteration is factory iter 90 (pm.md header + ROADMAP row #90 + Acceptance
Criteria); ``test_iter90_behavior.py`` was confirmed unused before creation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import proactive_loop.collectors.todos as _td
from proactive_loop import __version__
from proactive_loop.cli import build_parser
from proactive_loop.collectors import TodoCollector, all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry


# ---------------------------------------------------------------------------
# Black-box helpers -- real files under tmp_path; collect() is handed a
# pathlib.Path root (the existing suite's convention).
# ---------------------------------------------------------------------------


def _write(root: Path, relpath: str, content: str) -> Path:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _paths(sigs) -> list[str]:
    """The emitted signals' ``<relpath>:<lineno>`` paths, in emission order."""
    return [s.path for s in sigs]


def _fake_walk(root: Path, order: list[str]):
    """An ``os.walk`` replacement yielding exactly ``order`` under ``root`` (a
    flat dir; no subdirs). Used to force a specific discovery order and prove
    input-order independence. Files must already exist on disk (the collector
    reads each ``root / name``)."""

    def _walk(_top, *args, **kwargs):
        yield (str(root), [], list(order))

    return _walk


# ===========================================================================
# B1 -- Deterministic cap SELECTION (the load-bearing behavior). Three files
# z.py / a.py / m.py, each with two todos (lines 1 and 2); max_items=3 ->
# EXACTLY the 3 smallest (relpath, lineno) keys: a.py:1, a.py:2, m.py:1. Both
# z.py todos AND m.py:2 are dropped. A dropped todo is UNRECOVERABLE downstream
# (pla signals + the synthesizer per-kind cap only re-sort what they RECEIVE,
# and both todo weights are fixed 1.0/0.8 so weight cannot rescue a dropped one).
# ===========================================================================


def test_b1_cap_selection_is_smallest_relpath_lineno_keys(tmp_path: Path) -> None:
    for nm in ("z.py", "a.py", "m.py"):
        _write(tmp_path, nm, f"# TODO: {nm}-1\n# TODO: {nm}-2\n")

    kept = _paths(TodoCollector(max_items=3).collect(tmp_path))

    assert kept == ["a.py:1", "a.py:2", "m.py:1"], (
        "the max_items cap must keep the 3 smallest (relpath, lineno) todos; "
        f"got {kept!r}"
    )
    for dropped in ("m.py:2", "z.py:1", "z.py:2"):
        assert dropped not in kept, f"{dropped!r} must be dropped by the cap"


def test_b1_cap_selection_independent_of_walk_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for nm in ("z.py", "a.py", "m.py"):
        _write(tmp_path, nm, f"# TODO: {nm}-1\n# TODO: {nm}-2\n")

    monkeypatch.setattr(_td.os, "walk", _fake_walk(tmp_path, ["z.py", "a.py", "m.py"]))
    kept1 = _paths(TodoCollector(max_items=3).collect(tmp_path))

    monkeypatch.setattr(_td.os, "walk", _fake_walk(tmp_path, ["m.py", "z.py", "a.py"]))
    kept2 = _paths(TodoCollector(max_items=3).collect(tmp_path))

    assert kept1 == kept2 == ["a.py:1", "a.py:2", "m.py:1"], (
        "the surviving todo SET must be a function of filesystem content, not "
        f"os.walk order; walk1={kept1!r} walk2={kept2!r}"
    )


# ===========================================================================
# B2 -- Emission order is (relpath, lineno) ascending; relpath dominates. Two
# single-todo files b.py and a.py yield a.py:1 BEFORE b.py:1 regardless of
# discovery order.
# ===========================================================================


def test_b2_emission_order_relpath_ascending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "b.py", "# TODO: bee\n")
    _write(tmp_path, "a.py", "# TODO: ay\n")

    # Force a discovery order that a naive emit-in-walk-order impl would keep.
    monkeypatch.setattr(_td.os, "walk", _fake_walk(tmp_path, ["b.py", "a.py"]))
    order = _paths(TodoCollector().collect(tmp_path))

    assert order == ["a.py:1", "b.py:1"], (
        "signals must be emitted in ascending-relpath order, not walk order; "
        f"got {order!r}"
    )


# ===========================================================================
# B3 -- Line-number ordering is NUMERIC within a file (the wrong-but-green
# guard). A file with a todo on line 2 AND line 10 emits line 2 FIRST. A
# careless sort on the concatenated path string ("a.py:10" < "a.py:2"
# lexicographically because "1" < "2") would order line 10 first.
# ===========================================================================


def test_b3_line_number_ordering_is_numeric_not_lexicographic(tmp_path: Path) -> None:
    lines = ["x = 1"] * 11
    lines[1] = "# TODO: on-line-2"    # source line 2
    lines[9] = "# TODO: on-line-10"   # source line 10
    _write(tmp_path, "a.py", "\n".join(lines) + "\n")

    order = _paths(TodoCollector().collect(tmp_path))

    assert order == ["a.py:2", "a.py:10"], (
        "within a file, todos must sort by NUMERIC line number (line 2 before "
        f"line 10), not by the lexicographic path string; got {order!r}"
    )
    assert order != ["a.py:10", "a.py:2"], (
        "a sort on the concatenated 'a.py:<n>' string would order line 10 first "
        f"('1' < '2'); got {order!r}"
    )


# ===========================================================================
# B4 -- Input-order independence. Same files/todos, two different discovery
# orders -> byte-identical result (order AND membership).
# ===========================================================================


def test_b4_input_order_independence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for nm in ("z.py", "a.py", "m.py"):
        _write(tmp_path, nm, f"# TODO: {nm}\n")

    monkeypatch.setattr(_td.os, "walk", _fake_walk(tmp_path, ["z.py", "a.py", "m.py"]))
    r1 = _paths(TodoCollector().collect(tmp_path))

    monkeypatch.setattr(_td.os, "walk", _fake_walk(tmp_path, ["m.py", "z.py", "a.py"]))
    r2 = _paths(TodoCollector().collect(tmp_path))

    assert r1 == r2 == ["a.py:1", "m.py:1", "z.py:1"], (
        "collect() must be a function of filesystem CONTENT, not discovery "
        f"order; walk1={r1!r} walk2={r2!r}"
    )


# ===========================================================================
# B5 -- Single-file cap preserves line order (backward-compat). One file with
# 50 todos, max_items=5 -> EXACTLY the first 5 by line number (lines 1..5). This
# is the existing test_respects_max_items case, whose result is unchanged.
# ===========================================================================


def test_b5_single_file_cap_preserves_line_order(tmp_path: Path) -> None:
    _write(tmp_path, "big.py", "\n".join(f"# TODO: item {i}" for i in range(50)) + "\n")

    sigs = TodoCollector(max_items=5).collect(tmp_path)

    assert _paths(sigs) == [f"big.py:{i}" for i in range(1, 6)], (
        "a single file's todos are line-ordered, so the kept set under the cap "
        f"is lines 1..5; got {_paths(sigs)!r}"
    )
    assert len(sigs) == 5, f"max_items=5 must cap at 5; got {len(sigs)}"


# ===========================================================================
# B6 -- All other invariants unchanged.
# ===========================================================================


def test_b6_source_and_kind_labels(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "# TODO: check this\n")
    sigs = TodoCollector().collect(tmp_path)
    assert sigs, "a file with a TODO must emit at least one signal"
    for s in sigs:
        assert s.source == "todos", f"source must be 'todos'; got {s.source!r}"
        assert s.kind == "todo", f"kind must be 'todo'; got {s.kind!r}"


def test_b6_inline_tag_weight_is_one(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "# TODO: t\n")
    _write(tmp_path, "b.py", "# FIXME: f\n")
    _write(tmp_path, "c.js", "// XXX: x\n")
    sigs = TodoCollector().collect(tmp_path)
    assert len(sigs) == 3, f"expected 3 inline-tag todos; got {_paths(sigs)!r}"
    for s in sigs:
        assert s.weight == 1.0, f"inline TODO/FIXME/XXX weight must be 1.0; got {s.weight}"


def test_b6_checkbox_weight_is_point_eight_all_bullets(tmp_path: Path) -> None:
    _write(tmp_path, "t.md", "- [ ] dash\n* [ ] star\n+ [ ] plus\n")
    sigs = TodoCollector().collect(tmp_path)
    assert len(sigs) == 3, f"all three checkbox bullets must surface; got {_paths(sigs)!r}"
    for s in sigs:
        assert s.weight == 0.8, f"checkbox weight must be 0.8; got {s.weight}"


def test_b6_checked_checkbox_ignored(tmp_path: Path) -> None:
    _write(tmp_path, "done.md", "- [x] already finished\n- [ ] still open\n")
    sigs = TodoCollector().collect(tmp_path)
    summaries = [s.summary for s in sigs]
    assert not any("already finished" in s for s in summaries), (
        f"a checked '- [x]' box must be ignored; got {summaries!r}"
    )
    assert any("still open" in s for s in summaries), "the unchecked box must surface"


def test_b6_inline_tag_not_double_counted_as_checkbox(tmp_path: Path) -> None:
    """A line matching an inline tag is NOT also counted as a checkbox (the
    dedup 'continue')."""
    _write(tmp_path, "x.md", "- [ ] TODO: both patterns on one line\n")
    sigs = TodoCollector().collect(tmp_path)
    assert len(sigs) == 1, (
        f"a line matching both patterns must yield exactly ONE signal; got {_paths(sigs)!r}"
    )
    assert sigs[0].weight == 1.0, (
        f"the inline-tag match wins the dedup (weight 1.0, not 0.8); got {sigs[0].weight}"
    )


def test_b6_path_is_relpath_colon_lineno(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", "x = 1\n# TODO: nested\n")
    (sig,) = TodoCollector().collect(tmp_path)
    assert sig.path == "pkg/mod.py:2", (
        f"path must be '<relpath>:<lineno>' (forward-slash relpath); got {sig.path!r}"
    )


def test_b6_detail_is_the_source_line(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "# TODO: refactor\n")
    (sig,) = TodoCollector().collect(tmp_path)
    assert sig.detail == "# TODO: refactor", (
        f"detail must be the (stripped) source line; got {sig.detail!r}"
    )


def test_b6_unsupported_extension_ignored(tmp_path: Path) -> None:
    _write(tmp_path, "data.csv", "TODO: not a scanned file\n")
    assert TodoCollector().collect(tmp_path) == [], (
        "a .csv file is outside _SCAN_EXTENSIONS and must be ignored"
    )


def test_b6_hidden_files_and_skip_dirs_pruned(tmp_path: Path) -> None:
    _write(tmp_path, "visible.py", "# TODO: keep\n")
    _write(tmp_path, ".hidden.py", "# TODO: hidden\n")
    _write(tmp_path, "node_modules/pkg.py", "# TODO: vendored\n")
    _write(tmp_path, ".venv/lib.py", "# TODO: venv\n")
    _write(tmp_path, "__pycache__/mod.py", "# TODO: cache\n")

    summaries = [s.summary for s in TodoCollector().collect(tmp_path)]

    assert any("keep" in s for s in summaries), "a plain visible file must be scanned"
    for pruned in ("hidden", "vendored", "venv", "cache"):
        assert not any(pruned in s for s in summaries), (
            f"a todo under a hidden/skip path ({pruned!r}) must be pruned; got {summaries!r}"
        )


def test_b6_missing_directory_degrades_to_empty(tmp_path: Path) -> None:
    assert TodoCollector().collect(tmp_path / "does_not_exist") == [], (
        "a nonexistent dir must degrade to []"
    )


def test_b6_non_directory_root_degrades_to_empty(tmp_path: Path) -> None:
    f = tmp_path / "not_a_dir.txt"
    f.write_text("# TODO: file-as-root\n", encoding="utf-8")
    assert TodoCollector().collect(f) == [], "a non-directory root must degrade to []"


# ===========================================================================
# B7 -- count-lock: a behavior-only collector determinism fix adds NO registry
# entry; the suite stays FLAT at the iter-79 baseline.
# ===========================================================================


def test_b7_collector_registry_count_unchanged() -> None:
    assert len(all_collectors()) == 17, (
        "a determinism fix on TodoCollector must add NO collector; "
        f"expected 17, got {len(all_collectors())}"
    )


def test_b7_tool_registry_count_unchanged() -> None:
    assert len(ToolRegistry.tool_names()) == 14, (
        f"tool registry count must stay 14; got {len(ToolRegistry.tool_names())}"
    )


def test_b7_provider_count_unchanged() -> None:
    assert len(VALID_PROVIDERS) == 7, f"provider count must stay 7; got {len(VALID_PROVIDERS)}"


def test_b7_cli_subcommand_count_unchanged() -> None:
    parser = build_parser()
    subactions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert len(subactions) == 1, "expected exactly one subparsers action"
    assert len(subactions[0].choices) == 15, (
        f"CLI subcommand count must stay 15; got {len(subactions[0].choices)}"
    )


def test_b7_version_frozen() -> None:
    assert __version__ == "0.1.1", (
        f"a behavior-only collector fix must NOT bump the version; got {__version__!r}"
    )
