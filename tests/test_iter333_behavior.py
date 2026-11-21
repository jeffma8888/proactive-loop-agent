"""Black-box oracle for foundry iter 597 (factory iter 333): the syntax_error collector's
pyc probe consults ONE cached ``__pycache__`` listing per directory, so ``_pyc_says_ok``
opens only the pyc files that listing actually shows -- no doomed interpreter-pyc open
when only a pytest-rewritten pyc exists, and no open at all when no pyc can vouch.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``), ``README.md``
and the conventions under ``tests/`` (the pyc forging mirrors test_iter288). It counts
header probes by wrapping the module-level ``_pyc_header_matches`` seam the spec names,
and drives the public ``SyntaxErrorCollector().collect`` for the trusted-count checks.
No wall-clock bound, no sha pin, no network.

The module collects ZERO items on purpose (the suite-size binding wall in
test_iter263 b6 / test_iter270 b7 leaves no headroom for new items):
``iter597_pyc_listing`` is called from
``tests/test_iter317_behavior.py::test_runs_older_than_filters_by_checkpoint_age``,
which asserts its returned check-group count.

Spec ambiguity noted: behaviour 2 says ``pyc_trusted_count()`` rises when
``_pyc_says_ok`` is called; the count is asserted here through a collect pass (the
caller-visible effect), and the probe count on the direct call.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path
from typing import Any

import pytest

from proactive_loop.collectors import syntax_error
from proactive_loop.collectors.syntax_error import (
    SyntaxErrorCollector,
    _pyc_says_ok,
    clear_parse_memo,
    pyc_trusted_count,
)


def _src(root: Path, name: str = "a") -> Path:
    pkg = root / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    src = pkg / f"{name}.py"
    src.write_text("x = 1\n", encoding="utf-8")
    return src


def _forge(src: Path, pyc_name: str, *, mtime_delta: int = 0, flags: int = 0) -> Path:
    cache_dir = src.parent / "__pycache__"
    cache_dir.mkdir(parents=True, exist_ok=True)
    st = src.stat()
    header = (
        importlib.util.MAGIC_NUMBER
        + struct.pack("<I", flags)
        + struct.pack(
            "<II",
            (int(st.st_mtime) + mtime_delta) & 0xFFFFFFFF,
            st.st_size & 0xFFFFFFFF,
        )
    )
    path = cache_dir / pyc_name
    path.write_bytes(header + b"\x00" * 8)
    return path


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    real = syntax_error._pyc_header_matches

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(syntax_error, "_pyc_header_matches", wrapper)
    return calls


def _probe(src: Path) -> bool:
    st = src.stat()
    return _pyc_says_ok(src, st.st_mtime, st.st_size)


def iter597_pyc_listing(monkeypatch: pytest.MonkeyPatch, root: Path) -> int:
    """Run every behaviour check; return the number of check groups that ran."""
    monkeypatch.setattr(sys, "pycache_prefix", None)
    tag = sys.implementation.cache_tag
    calls = _spy(monkeypatch)
    groups = 0

    # B1: no __pycache__ at all -> False with zero header probes.
    clear_parse_memo()
    src = _src(root / "b1")
    assert _probe(src) is False
    assert len(calls) == 0, f"B1: expected 0 pyc probes, got {len(calls)}: {calls}"
    groups += 1

    # B2: only a valid pytest-rewritten pyc -> True with exactly ONE probe.
    clear_parse_memo()
    calls.clear()
    src = _src(root / "b2")
    _forge(src, f"a.{tag}-pytest-8.3.4.pyc")
    assert _probe(src) is True
    assert len(calls) == 1, f"B2: expected exactly 1 pyc probe, got {len(calls)}: {calls}"
    clear_parse_memo()
    before = pyc_trusted_count()
    SyntaxErrorCollector().collect(root / "b2")
    assert pyc_trusted_count() == before + 1, (before, pyc_trusted_count())
    groups += 1

    # B3: a valid interpreter pyc -> True with exactly one probe (unchanged).
    clear_parse_memo()
    calls.clear()
    src = _src(root / "b3")
    _forge(src, f"a.{tag}.pyc")
    assert _probe(src) is True
    assert len(calls) == 1, f"B3: expected 1 pyc probe, got {len(calls)}: {calls}"
    groups += 1

    # B4: __pycache__ holds pycs for OTHER stems only -> False with zero probes.
    clear_parse_memo()
    calls.clear()
    src = _src(root / "b4")
    _forge(src, f"b.{tag}.pyc")
    _forge(src, f"ab.{tag}-pytest-1.0.pyc")
    assert _probe(src) is False
    assert len(calls) == 0, f"B4: expected 0 pyc probes, got {len(calls)}: {calls}"
    groups += 1

    # B5: rejection verdicts unchanged -- stale header, hash-based flags and invalid
    # pytest version suffixes never vouch.
    rejects = {
        "stale": (f"a.{tag}.pyc", 7, 0),
        "hashflags": (f"a.{tag}.pyc", 0, 1),
        "empty-ver": (f"a.{tag}-pytest-.pyc", 0, 0),
        "double-dot": (f"a.{tag}-pytest-1..2.pyc", 0, 0),
        "trailing-dot": (f"a.{tag}-pytest-1..pyc", 0, 0),
        "alpha": (f"a.{tag}-pytest-x1.pyc", 0, 0),
    }
    for label, (name, delta, flags) in rejects.items():
        clear_parse_memo()
        src = _src(root / "b5" / label)
        _forge(src, name, mtime_delta=delta, flags=flags)
        assert _probe(src) is False, f"B5 {label}: {name} must not vouch"
    groups += 1

    # B6: freshness -- clear_parse_memo() empties the listing cache, and each collect
    # pass starts from a fresh listing (no clear between the two collects).
    clear_parse_memo()
    src = _src(root / "b6a")
    assert _probe(src) is False
    _forge(src, f"a.{tag}.pyc")
    clear_parse_memo()
    assert _probe(src) is True, "B6: a pyc written before clear_parse_memo() must be seen"
    clear_parse_memo()
    ws = root / "b6b"
    src = _src(ws)
    before = pyc_trusted_count()
    SyntaxErrorCollector().collect(ws)
    assert pyc_trusted_count() == before, "B6: nothing can vouch on the first pass"
    _forge(src, f"a.{tag}.pyc")
    SyntaxErrorCollector().collect(ws)
    assert pyc_trusted_count() == before + 1, (
        f"B6: the second collect must see the new pyc; count {pyc_trusted_count()}"
    )
    groups += 1

    clear_parse_memo()
    return groups
