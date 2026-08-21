"""Behavior tests for commit-seq factory iter 82 (state-dir iter-72).

Feature under test: ``RecentFilesCollector`` must CLAMP its recency ``weight``
to the documented ``[0.0, 1.0]`` range. A file whose ``mtime`` is in the FUTURE
(clock skew on a shared/NFS mount, or archive extraction preserving stored
future timestamps) yields a NEGATIVE ``age_days`` and, pre-fix, a ``weight`` > 1.0
(e.g. 1.5 for a 7-day-future file with ``within_days=14``). That over-ranked the
noise file above genuinely just-modified work in the L2 synthesizer prompt and
violated the repo's own tested ``0.0 <= weight <= 1.0`` invariant. Post-fix the
weight is clamped to exactly 1.0 for any future-dated file, while every
``age_days >= 0`` (past/present) file is byte-identical (the ``min(1.0, ...)``
wrap is a proven no-op there).

ISOLATION: black-box. These tests drive only the public interface
(``RecentFilesCollector(...).collect(root)`` + the public ``all_collectors()`` /
``ToolRegistry`` / ``VALID_PROVIDERS`` / ``build_parser()`` / ``__version__``
registries). No file under ``src/`` was read, nor the engineer's/reviewer's
notes, nor ``git diff``; the assertions encode the pm.md Expected Behaviors, not
the implementation.

File naming: the prompt's state-dir iteration is 72, but ``tests/test_iter72_
behavior.py`` already exists (an earlier commit-seq iteration). The repo names
behavior files after the COMMIT SEQUENCE, which for this iteration is factory
iter 82 (pm.md header + ROADMAP row #82 + Acceptance Criteria); ``test_iter82_
behavior.py`` was confirmed unused before creation.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from proactive_loop import __version__
from proactive_loop.cli import build_parser
from proactive_loop.collectors import RecentFilesCollector, all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry

_DAY = 86_400.0


# ---------------------------------------------------------------------------
# Black-box helpers -- create real files under a pytest tmp_path (a Path) and
# collect the emitted signals. NOTE: collect() must be handed a pathlib.Path
# (the existing suite drives it via the tmp_path fixture); a positive
# offset_sec puts the mtime in the FUTURE, negative in the PAST.
# ---------------------------------------------------------------------------


def _make_file(root: Path, name: str, *, offset_sec: float = 0.0, content: str = "x = 1") -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    if offset_sec:
        mtime = time.time() + offset_sec
        os.utime(p, (mtime, mtime))
    return p


def _recent(root: Path, **kwargs) -> list:
    sigs = RecentFilesCollector(**kwargs).collect(root)
    return [s for s in sigs if s.kind == "recent_file"]


# ---------------------------------------------------------------------------
# Behavior 1 -- Future-dated file weight is clamped to 1.0 (was 1.5 pre-fix).
# ---------------------------------------------------------------------------


def test_b1_future_file_weight_clamped_to_one(tmp_path: Path) -> None:
    _make_file(tmp_path, "future.py", offset_sec=7 * _DAY)
    recent = _recent(tmp_path, within_days=14)
    assert len(recent) == 1, f"expected exactly one recent_file signal; got {len(recent)}"
    w = recent[0].weight
    assert w == 1.0, f"future-7d file weight must clamp to 1.0 (was 1.5 pre-fix); got {w}"
    assert w <= 1.0, f"weight must never exceed 1.0; got {w}"


# ---------------------------------------------------------------------------
# Behavior 2 -- Weight invariant holds for ANY mtime mix (past/now/future),
# and an extreme 100-day-future file still yields weight == 1.0.
# ---------------------------------------------------------------------------


def test_b2_weight_invariant_across_mixed_mtimes(tmp_path: Path) -> None:
    _make_file(tmp_path, "past.py", offset_sec=-7 * _DAY)
    _make_file(tmp_path, "now.py")
    _make_file(tmp_path, "future.py", offset_sec=7 * _DAY)
    _make_file(tmp_path, "far_future.py", offset_sec=100 * _DAY)
    recent = _recent(tmp_path, within_days=14)
    assert recent, "expected at least one recent_file signal for a mixed workspace"
    for s in recent:
        assert 0.0 <= s.weight <= 1.0, (
            f"weight out of [0,1] for {s.summary!r}: {s.weight}"
        )


def test_b2_extreme_future_never_exceeds_one(tmp_path: Path) -> None:
    _make_file(tmp_path, "far.py", offset_sec=100 * _DAY)
    recent = _recent(tmp_path, within_days=14)
    assert len(recent) == 1
    assert recent[0].weight == 1.0, (
        f"a 100-day-future file must still clamp to exactly 1.0; got {recent[0].weight}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- Backward-compat: past-file weight is unchanged (clamp no-op).
# D=7 days past, within_days=14 -> round(1.0 - 7/14, 4) == 0.5, tol 1e-3.
# ---------------------------------------------------------------------------


def test_b3_past_file_weight_is_unchanged_decay(tmp_path: Path) -> None:
    _make_file(tmp_path, "past.py", offset_sec=-7 * _DAY)
    recent = _recent(tmp_path, within_days=14)
    assert len(recent) == 1
    expected = round(1.0 - 7.0 / 14.0, 4)  # 0.5
    got = recent[0].weight
    assert abs(got - expected) <= 1e-3, (
        f"past-7d/within-14 weight must equal the pre-fix decay {expected} "
        f"(min(1.0, ...) is a no-op for age>=0); got {got}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- Just-modified file (mtime ~= now) stays at weight 1.0.
# ---------------------------------------------------------------------------


def test_b4_just_modified_file_weight_one(tmp_path: Path) -> None:
    _make_file(tmp_path, "fresh.py")  # mtime == now (no utime offset)
    recent = _recent(tmp_path, within_days=14)
    assert len(recent) == 1
    assert recent[0].weight == 1.0, (
        f"a just-modified (age ~= 0) file must yield weight 1.0; got {recent[0].weight}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- Future file is STILL surfaced (correct fields) and the list is
# ordered newest-first by mtime (future file first) even though both clamp to 1.0.
# ---------------------------------------------------------------------------


def test_b5_future_file_still_surfaced_with_correct_fields(tmp_path: Path) -> None:
    _make_file(tmp_path, "future.py", offset_sec=7 * _DAY)
    recent = _recent(tmp_path, within_days=14)
    assert len(recent) == 1, "future-dated file must NOT be dropped"
    s = recent[0]
    assert s.source == "recent_files", f"source; got {s.source!r}"
    assert s.kind == "recent_file", f"kind; got {s.kind!r}"
    assert s.summary == "Recently modified: future.py", f"summary; got {s.summary!r}"
    assert s.path is not None, "path must be non-None"
    assert s.timestamp is not None, "timestamp must be non-None"


def test_b5_ordering_future_before_now_newest_first(tmp_path: Path) -> None:
    _make_file(tmp_path, "now.py")
    _make_file(tmp_path, "future.py", offset_sec=7 * _DAY)
    recent = _recent(tmp_path, within_days=14)
    assert len(recent) == 2, f"expected both files surfaced; got {len(recent)}"
    summaries = [s.summary for s in recent]
    assert summaries[0] == "Recently modified: future.py", (
        f"future file (highest mtime) must be FIRST; order was {summaries}"
    )
    assert summaries[1] == "Recently modified: now.py", (
        f"now file must be SECOND; order was {summaries}"
    )
    # ordering keys off mtime, NOT weight -- both clamp to 1.0 yet order is preserved.
    assert recent[0].weight == 1.0
    assert recent[1].weight == 1.0


# ---------------------------------------------------------------------------
# Behavior 6 -- No registry / never-raises drift: missing dir -> [], and the
# count-lock invariants stay 15 collectors / 14 tools / 7 providers / 15 verbs,
# __version__ frozen at 0.1.1 (a behavior-only clamp adds no public surface).
# ---------------------------------------------------------------------------


def test_b6_missing_directory_returns_empty(tmp_path: Path) -> None:
    sigs = RecentFilesCollector().collect(tmp_path / "does_not_exist")
    assert sigs == [], f"nonexistent dir must degrade to []; got {sigs!r}"


def test_b6_collector_registry_count_unchanged() -> None:
    assert len(all_collectors()) == 17, (
        "a weight-clamp fix on RecentFilesCollector must add NO collector; "
        f"expected 17, got {len(all_collectors())}"
    )


def test_b6_tool_registry_count_unchanged() -> None:
    assert len(ToolRegistry.tool_names()) == 14, (
        f"tool registry count must stay 14; got {len(ToolRegistry.tool_names())}"
    )


def test_b6_provider_count_unchanged() -> None:
    assert len(VALID_PROVIDERS) == 7, (
        f"provider count must stay 7; got {len(VALID_PROVIDERS)}"
    )


def test_b6_cli_subcommand_count_unchanged() -> None:
    parser = build_parser()
    subactions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert len(subactions) == 1, "expected exactly one subparsers action"
    assert len(subactions[0].choices) == 17, (
        f"CLI subcommand count must stay 17; got {len(subactions[0].choices)}"
    )


def test_b6_version_frozen() -> None:
    assert __version__ == "0.1.1", (
        f"a behavior-only collector fix must NOT bump the version; got {__version__!r}"
    )
