"""Black-box behavior tests for iteration 79 (ships as commit-seq **factory iter
89**) --- ``RecentFilesCollector``'s recency sort now applies a deterministic
ASCENDING-PATH tie-break, so files that share an ``mtime`` order --- and survive
the ``max_files`` cap --- by a total, ``os.walk``-order-independent rule instead
of arbitrary filesystem-entry order (ROADMAP row #89, SPEC S4.1).

ISOLATION CONTRACT (honored): these tests were written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, ``ROADMAP.md`` --- and the collector's existing PUBLIC
conventions in ``tests/test_collectors.py`` / ``tests/test_iter82_behavior.py``.
They drive ONLY the public surface
``RecentFilesCollector(...).collect(root) -> list[ContextSignal]`` (plus the
public ``all_collectors()`` / ``ToolRegistry`` / ``VALID_PROVIDERS`` /
``build_parser()`` / ``__version__`` registries for the count-lock). **No file
under ``src/`` was read, no engineer/reviewer note was read, and no ``git diff``
was consulted.** Every test is fully offline/deterministic: real files under a
pytest ``tmp_path`` with mtimes forced by ``os.utime``; the one seam
monkeypatched (``proactive_loop.collectors.filesystem.os.walk``) is the seam the
spec names explicitly, and ``monkeypatch`` auto-restores it.

File naming: the prompt's state-dir iteration is 79, but
``tests/test_iter79_behavior.py`` already exists (an earlier commit-seq
iteration). The repo names behavior files after the COMMIT SEQUENCE, which for
this iteration is factory iter 89 (pm.md header + ROADMAP row #89 + Acceptance
Criteria); ``test_iter89_behavior.py`` was confirmed unused before creation.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import proactive_loop.collectors.filesystem as _fs
from proactive_loop import __version__
from proactive_loop.cli import build_parser
from proactive_loop.collectors import RecentFilesCollector, all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry


# ---------------------------------------------------------------------------
# Black-box helpers -- real files under tmp_path, mtimes forced with os.utime.
# ``collect()`` is handed a pathlib.Path (the existing suite's convention).
# ---------------------------------------------------------------------------


def _make_file(root: Path, name: str, *, mtime: float, content: str = "x = 1") -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


def _names(sigs) -> list[str]:
    """The emitted signals' file basenames, in emission order."""
    return [Path(s.path).name for s in sigs]


def _fake_walk(root: Path, order: list[str]):
    """A ``os.walk`` replacement yielding exactly ``order`` under ``root`` (all
    files live directly in ``root``; no subdirs). Used to force a specific
    discovery order and prove input-order independence."""

    def _walk(_top, *args, **kwargs):
        yield (str(root), [], list(order))

    return _walk


# ===========================================================================
# B1 -- equal-mtime emission order is ASCENDING PATH.
# ===========================================================================


def test_b1_equal_mtime_emission_order_is_ascending_path(tmp_path: Path) -> None:
    t = time.time() - 3600.0
    for name in ("c.txt", "a.txt", "b.txt"):
        _make_file(tmp_path, name, mtime=t)

    sigs = RecentFilesCollector().collect(tmp_path)

    assert _names(sigs) == ["a.txt", "b.txt", "c.txt"], (
        "equal-mtime files must be emitted in ascending-path order; "
        f"got {_names(sigs)!r}"
    )


# ===========================================================================
# B2 -- ascending, NOT descending (negation-form guard). Force a discovery
# order whose naive stable sort would leave ties UNSORTED, so a careless
# ``key=(t[0], str(t[1])), reverse=True`` (descending path) bug is caught.
# ===========================================================================


def test_b2_negation_form_guard_ascending_not_descending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = time.time() - 3600.0
    for name in ("c.txt", "a.txt", "b.txt"):
        _make_file(tmp_path, name, mtime=t)

    monkeypatch.setattr(_fs.os, "walk", _fake_walk(tmp_path, ["c.txt", "a.txt", "b.txt"]))
    result = _names(RecentFilesCollector().collect(tmp_path))

    assert result == ["a.txt", "b.txt", "c.txt"], (
        f"equal-mtime ties must sort ASCENDING path; got {result!r}"
    )
    assert result != ["c.txt", "b.txt", "a.txt"], (
        "a reverse=True-on-(mtime, path) bug would order ties DESCENDING path; "
        f"got {result!r}"
    )


# ===========================================================================
# B3 -- input-order independence. Same set of equal-mtime files, two different
# discovery orders -> byte-identical emitted signal list (order AND membership).
# ===========================================================================


def test_b3_input_order_independence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = time.time() - 3600.0
    for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
        _make_file(tmp_path, name, mtime=t)

    monkeypatch.setattr(
        _fs.os, "walk", _fake_walk(tmp_path, ["c.txt", "a.txt", "b.txt", "d.txt"])
    )
    r1 = _names(RecentFilesCollector().collect(tmp_path))

    monkeypatch.setattr(
        _fs.os, "walk", _fake_walk(tmp_path, ["d.txt", "b.txt", "a.txt", "c.txt"])
    )
    r2 = _names(RecentFilesCollector().collect(tmp_path))

    assert r1 == r2 == ["a.txt", "b.txt", "c.txt", "d.txt"], (
        "collect() must be a function of filesystem CONTENT, not discovery "
        f"order; walk1={r1!r} walk2={r2!r}"
    )


# ===========================================================================
# B4 -- deterministic cap SELECTION (the load-bearing behavior). max_files=2
# over 4 equal-mtime files -> EXACTLY the 2 lexicographically-smallest paths,
# regardless of walk order. A dropped signal is unrecoverable downstream.
# ===========================================================================


def test_b4_cap_selection_is_lexicographically_smallest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = time.time() - 3600.0
    for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
        _make_file(tmp_path, name, mtime=t)

    monkeypatch.setattr(
        _fs.os, "walk", _fake_walk(tmp_path, ["c.txt", "a.txt", "b.txt", "d.txt"])
    )
    kept1 = _names(RecentFilesCollector(max_files=2).collect(tmp_path))

    monkeypatch.setattr(
        _fs.os, "walk", _fake_walk(tmp_path, ["d.txt", "b.txt", "a.txt", "c.txt"])
    )
    kept2 = _names(RecentFilesCollector(max_files=2).collect(tmp_path))

    assert kept1 == kept2 == ["a.txt", "b.txt"], (
        "the max_files cap must keep the N lexicographically-smallest equal-mtime "
        f"files independent of walk order; walk1={kept1!r} walk2={kept2!r}"
    )
    for dropped in ("c.txt", "d.txt"):
        assert dropped not in kept1, f"{dropped!r} should have been dropped by the cap"


# ===========================================================================
# B5 -- mtime precedence preserved (backward-compat): a NEWER file with a
# lexicographically-LARGER name still precedes an OLDER smaller-named file, so
# mtime dominates the path tie-break when mtimes differ.
# ===========================================================================


def test_b5_mtime_dominates_path_when_mtimes_differ(tmp_path: Path) -> None:
    now = time.time()
    _make_file(tmp_path, "z.txt", mtime=now - 60.0)      # newer, larger name
    _make_file(tmp_path, "a.txt", mtime=now - 7200.0)    # older, smaller name

    sigs = RecentFilesCollector().collect(tmp_path)

    assert _names(sigs) == ["z.txt", "a.txt"], (
        "when mtimes differ the file order is strictly newest-first; the path "
        f"tie-break must NOT participate; got {_names(sigs)!r}"
    )


# ===========================================================================
# B6 -- all other invariants unchanged.
# ===========================================================================


def test_b6_source_and_kind_labels(tmp_path: Path) -> None:
    _make_file(tmp_path, "note.txt", mtime=time.time() - 60.0)
    sigs = RecentFilesCollector().collect(tmp_path)
    assert sigs, "a recently-modified file must emit at least one signal"
    for s in sigs:
        assert s.source == "recent_files", f"source must be 'recent_files'; got {s.source!r}"
        assert s.kind == "recent_file", f"kind must be 'recent_file'; got {s.kind!r}"


def test_b6_weight_within_unit_interval(tmp_path: Path) -> None:
    now = time.time()
    _make_file(tmp_path, "fresh.txt", mtime=now - 60.0)
    _make_file(tmp_path, "old.txt", mtime=now - 10.0 * 86_400.0)  # ~10 days, still within 14
    sigs = RecentFilesCollector().collect(tmp_path)
    assert sigs, "expected signals for files inside within_days"
    for s in sigs:
        assert 0.0 <= s.weight <= 1.0, (
            f"recency weight must stay in [0.0, 1.0] (iter-82 clamp); got {s.weight!r}"
        )
    # A fresher file must not rank BELOW an older one (weight monotone in recency).
    by_name = {Path(s.path).name: s.weight for s in sigs}
    assert by_name["fresh.txt"] >= by_name["old.txt"], (
        f"fresher file must have >= recency weight; {by_name!r}"
    )


def test_b6_timestamp_is_utc_mtime(tmp_path: Path) -> None:
    mtime = time.time() - 1234.0
    _make_file(tmp_path, "stamped.txt", mtime=mtime)
    (sig,) = RecentFilesCollector().collect(tmp_path)
    assert sig.timestamp is not None, "timestamp must be set"
    assert sig.timestamp.tzinfo is not None, "timestamp must be timezone-aware"
    expected = datetime.fromtimestamp(mtime, tz=timezone.utc)
    delta = abs((sig.timestamp - expected).total_seconds())
    assert delta < 2.0, (
        f"timestamp must be the file's UTC mtime; expected ~{expected}, "
        f"got {sig.timestamp} (delta {delta}s)"
    )


def test_b6_hidden_and_skip_dirs_pruned(tmp_path: Path) -> None:
    t = time.time() - 60.0
    _make_file(tmp_path, "visible.txt", mtime=t)
    _make_file(tmp_path, ".hidden.txt", mtime=t)
    _make_file(tmp_path, "node_modules/pkg.txt", mtime=t)
    _make_file(tmp_path, ".venv/lib.txt", mtime=t)
    _make_file(tmp_path, "__pycache__/mod.txt", mtime=t)

    names = _names(RecentFilesCollector().collect(tmp_path))

    assert "visible.txt" in names, "a plain visible file must be emitted"
    for pruned in (".hidden.txt", "pkg.txt", "lib.txt", "mod.txt"):
        assert pruned not in names, (
            f"{pruned!r} lives under a hidden/skip path and must be pruned; got {names!r}"
        )


def test_b6_missing_directory_degrades_to_empty(tmp_path: Path) -> None:
    sigs = RecentFilesCollector().collect(tmp_path / "does_not_exist")
    assert sigs == [], f"a nonexistent dir must degrade to []; got {sigs!r}"


def test_b6_non_directory_root_degrades_to_empty(tmp_path: Path) -> None:
    a_file = tmp_path / "not_a_dir.txt"
    a_file.write_text("hello", encoding="utf-8")
    sigs = RecentFilesCollector().collect(a_file)
    assert sigs == [], f"a non-directory root must degrade to []; got {sigs!r}"


# ===========================================================================
# B7 -- count-lock: a behavior-only collector-sort fix adds NO registry entry.
# ===========================================================================


def test_b7_collector_registry_count_unchanged() -> None:
    assert len(all_collectors()) == 16, (
        "a sort tie-break on RecentFilesCollector must add NO collector; "
        f"expected 16, got {len(all_collectors())}"
    )


def test_b7_tool_registry_count_unchanged() -> None:
    assert len(ToolRegistry.tool_names()) == 14, (
        f"tool registry count must stay 14; got {len(ToolRegistry.tool_names())}"
    )


def test_b7_provider_count_unchanged() -> None:
    assert len(VALID_PROVIDERS) == 7, (
        f"provider count must stay 7; got {len(VALID_PROVIDERS)}"
    )


def test_b7_cli_subcommand_count_unchanged() -> None:
    parser = build_parser()
    subactions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert len(subactions) == 1, "expected exactly one subparsers action"
    assert len(subactions[0].choices) == 14, (
        f"CLI subcommand count must stay 14; got {len(subactions[0].choices)}"
    )


def test_b7_version_frozen() -> None:
    assert __version__ == "0.1.1", (
        f"a behavior-only collector fix must NOT bump the version; got {__version__!r}"
    )
