"""Black-box behavior tests for iteration 74 (foundry state iter-64) --- pinning
``git_activity.py``'s degradation + parse-robustness branches (ROADMAP row #67).

Iteration 74 is a TEST-ONLY coverage pin: it adds NO ``src/`` change. The
``GitActivityCollector`` is the repo's lowest-covered module, and every dark
line is one of the SPEC S4.1 resilience paths --- "a collector never aborts a
scan; it degrades to ``[]``". These tests exercise each of those paths through
the collector's PUBLIC API so that a future refactor cannot silently delete a
degradation branch while the full suite stays green.

ISOLATION CONTRACT (honored): these tests were written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md`` --- and the collector's existing public conventions in
``tests/test_collectors.py``. They drive ONLY the public surface
``GitActivityCollector().collect(path) -> list[ContextSignal]``. The two
module-level seams that are monkeypatched (``subprocess.run`` and
``Path.iterdir`` on ``proactive_loop.collectors.git_activity``) are the seams
the spec names explicitly; ``monkeypatch`` auto-restores both. **No file under
``src/`` was read, no engineer/reviewer note was read, and no ``git diff`` was
consulted.** Every test is fully offline/deterministic: NO ``git`` binary,
network, or real repo is required --- ``subprocess.run`` is always stubbed.
"""

from __future__ import annotations

import subprocess
import types
from datetime import timezone
from pathlib import Path

import pytest

import proactive_loop.collectors.git_activity as git_activity
from proactive_loop.collectors import GitActivityCollector
from proactive_loop.models import ContextSignal

# ``git log`` emits its fields separated by the ASCII unit separator (\x1f)
# under the "%H\x1f%ai\x1f%s\x1f%an" pretty format: hash, author-date (ISO,
# with a space before the tz offset), subject, author-name.
SEP = "\x1f"


# ---------------------------------------------------------------------------
# Helpers --- install the two offline seams. monkeypatch auto-restores.
# ---------------------------------------------------------------------------


def _line(commit_hash: str, date: str, subject: str, author: str) -> str:
    """One well-formed ``git log`` output line (4 \x1f-separated fields)."""
    return SEP.join([commit_hash, date, subject, author])


def _stub_run(monkeypatch, *, stdout: str = "", returncode: int = 0) -> None:
    """Replace the module-level ``subprocess.run`` with a stub returning a
    ``SimpleNamespace(returncode=..., stdout=...)``. The collector reads only
    those two attributes, so this is a faithful stand-in; NO real subprocess
    (and hence no ``git`` binary) is ever spawned."""

    def _fake_run(*args, **kwargs):
        return types.SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(git_activity.subprocess, "run", _fake_run)


def _stub_run_raises(monkeypatch, exc: BaseException) -> None:
    """Replace the module-level ``subprocess.run`` with a stub that raises."""

    def _fake_run(*args, **kwargs):
        raise exc

    monkeypatch.setattr(git_activity.subprocess, "run", _fake_run)


def _collect(path: Path) -> list[ContextSignal]:
    signals = GitActivityCollector().collect(path)
    assert isinstance(signals, list), f"collect() must return a list; got {type(signals)!r}"
    return signals


# ===========================================================================
# Behavior 1 --- Subprocess-level failure -> [] (no raise).
# ===========================================================================


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError("git not installed"),
        subprocess.TimeoutExpired(cmd=["git"], timeout=10),
        OSError("boom"),
    ],
    ids=["FileNotFoundError", "TimeoutExpired", "OSError"],
)
def test_eb1_subprocess_failure_degrades_to_empty(monkeypatch, tmp_path, exc) -> None:
    _stub_run_raises(monkeypatch, exc)
    assert _collect(tmp_path) == [], (
        f"a {type(exc).__name__} from subprocess.run must degrade to [] (SPEC S4.1: "
        f"a collector never aborts a scan)"
    )


# ===========================================================================
# Behavior 2 --- Non-zero return code -> [] (stdout never parsed).
# ===========================================================================


def test_eb2_nonzero_return_code_degrades_to_empty(monkeypatch, tmp_path) -> None:
    # A deliberately non-empty, unparseable stdout: it must NEVER be parsed when
    # the return code is non-zero (a not-a-git-repo directory).
    _stub_run(monkeypatch, stdout="this must never be parsed\nnor this\n", returncode=1)
    assert _collect(tmp_path) == []


# ===========================================================================
# Behavior 3 --- Well-formed stdout -> one signal per line, documented shape.
# ===========================================================================


def test_eb3_wellformed_lines_parse_with_documented_shape(monkeypatch, tmp_path) -> None:
    commits = [
        ("deadbeefcafefeed", "2024-01-15 10:30:00 -0700", "Fix the parser", "Alice"),
        ("0123456789abcdef", "2024-02-20 08:00:00 +0000", "Add feature X", "Bob"),
        ("fedcba9876543210", "2024-03-25 23:59:59 +0200", "Refactor module", "Carol"),
    ]
    _stub_run(monkeypatch, stdout="".join(_line(*c) + "\n" for c in commits))

    signals = _collect(tmp_path)
    assert len(signals) == len(commits)

    for sig, (chash, _date, subject, author) in zip(signals, commits):
        assert isinstance(sig, ContextSignal)
        assert sig.source == "git_activity"
        assert sig.kind == "git_commit"
        assert sig.weight == 1.0
        assert sig.path == str(tmp_path)
        assert sig.summary.endswith(subject), sig.summary
        assert tmp_path.name in sig.summary, sig.summary
        assert sig.detail == f"hash={chash[:8]} author={author}", sig.detail
        # Timezone-AWARE datetime: tzinfo present AND a concrete offset resolves.
        assert sig.timestamp is not None
        assert sig.timestamp.tzinfo is not None
        assert sig.timestamp.utcoffset() is not None


# ===========================================================================
# Behavior 4 --- Blank / whitespace-only lines are skipped.
# ===========================================================================


def test_eb4_blank_and_whitespace_lines_are_skipped(monkeypatch, tmp_path) -> None:
    good = [
        ("h1", "2024-01-15 10:30:00 -0700", "Alpha change", "A"),
        ("h2", "2024-01-16 11:00:00 -0700", "Beta change", "B"),
        ("h3", "2024-01-17 12:00:00 -0700", "Gamma change", "C"),
    ]
    lines = [
        _line(*good[0]),
        "",           # blank
        "   ",        # spaces only
        _line(*good[1]),
        "\t",         # tab only
        _line(*good[2]),
        "",           # trailing blank
    ]
    _stub_run(monkeypatch, stdout="\n".join(lines) + "\n")

    signals = _collect(tmp_path)
    # Exactly M signals: the blank / whitespace lines contribute nothing.
    assert len(signals) == len(good)
    subjects = [g[2] for g in good]
    for sig, subject in zip(signals, subjects):
        assert sig.summary.endswith(subject), sig.summary


# ===========================================================================
# Behavior 5 --- Malformed (<4 field) line skipped; valid sibling still parses.
# ===========================================================================


def test_eb5_short_line_skipped_valid_sibling_parses(monkeypatch, tmp_path) -> None:
    # Only two fields (one \x1f separator) -> fewer than 4 fields -> dropped.
    short = "deadbeef" + SEP + "2024-01-01 00:00:00 +0000"
    good = _line("abc12345", "2024-02-02 09:09:09 +0000", "Real commit", "Zed")
    _stub_run(monkeypatch, stdout=short + "\n" + good + "\n")

    signals = _collect(tmp_path)
    assert len(signals) == 1, "the short line must be dropped; only the valid sibling survives"
    assert signals[0].summary.endswith("Real commit")
    assert signals[0].detail == "hash=abc12345 author=Zed"


# ===========================================================================
# Behavior 6 --- Date parsing: tz-naive -> UTC; unparseable -> None (kept).
# ===========================================================================


def test_eb6a_tznaive_date_normalized_to_utc(monkeypatch, tmp_path) -> None:
    _stub_run(
        monkeypatch,
        stdout=_line("naive001", "2024-01-15 10:30:00", "Naive date commit", "N") + "\n",
    )
    signals = _collect(tmp_path)
    assert len(signals) == 1
    ts = signals[0].timestamp
    assert ts is not None, "a tz-naive date must still yield a timestamp"
    assert ts.tzinfo == timezone.utc, "a tz-naive commit date must be normalized to UTC"


def test_eb6b_unparseable_date_yields_none_timestamp_but_signal_present(
    monkeypatch, tmp_path
) -> None:
    _stub_run(
        monkeypatch,
        stdout=_line("bad00001", "not-a-date", "Bad date commit", "M") + "\n",
    )
    signals = _collect(tmp_path)
    # The signal is STILL emitted; only its timestamp degrades to None.
    assert len(signals) == 1
    assert signals[0].timestamp is None
    assert signals[0].summary.endswith("Bad date commit")


# ===========================================================================
# Behavior 7 --- Child-directory enumeration OSError -> root signals preserved.
# ===========================================================================


def test_eb7_child_enumeration_oserror_preserves_root_signals(monkeypatch, tmp_path) -> None:
    _stub_run(
        monkeypatch,
        stdout=_line("root0001", "2024-03-03 03:03:03 +0000", "Root commit", "R") + "\n",
    )

    def _raising_iterdir(self, *args, **kwargs):
        raise OSError("cannot enumerate children")

    # Patch on the class the module references; monkeypatch auto-restores.
    monkeypatch.setattr(git_activity.Path, "iterdir", _raising_iterdir)

    signals = _collect(tmp_path)
    # The child-scan failure is swallowed; the root directory's signal survives.
    assert len(signals) == 1
    assert signals[0].summary.endswith("Root commit")
    assert signals[0].path == str(tmp_path)


# ===========================================================================
# Behavior 8 --- Duplicate summaries are deduplicated.
# ===========================================================================


def test_eb8_duplicate_summaries_are_deduplicated(monkeypatch, tmp_path) -> None:
    # Two DIFFERENT commits (distinct hash/date/author) sharing the SAME subject
    # -> identical "Commit in {name}: {subject}" summary -> collapse to one.
    subject = "Identical subject"
    dup = (
        _line("hashone1", "2024-01-15 10:30:00 -0700", subject, "Alice")
        + "\n"
        + _line("hashtwo2", "2024-01-16 11:00:00 -0700", subject, "Bob")
        + "\n"
    )
    _stub_run(monkeypatch, stdout=dup)

    signals = _collect(tmp_path)
    assert len(signals) == 1, "identical summaries must be deduplicated to a single signal"
    assert signals[0].summary == f"Commit in {tmp_path.name}: {subject}"


# ===========================================================================
# Behavior 9 --- Unexpected exception escaping _collect is contained -> [].
# ===========================================================================


def test_eb9_unexpected_exception_contained_to_empty(monkeypatch, tmp_path) -> None:
    # ValueError is OUTSIDE the inner narrow catch tuple (FileNotFoundError /
    # TimeoutExpired / OSError), so it escapes the fetch helper and must be
    # absorbed by collect()'s outer never-raise guard.
    _stub_run_raises(monkeypatch, ValueError("unexpected internal error"))
    assert _collect(tmp_path) == []
