"""Black-box oracle for foundry iter 603 (factory iter 338): ``SyntaxErrorCollector``
remembers, per process, every source stat a timestamp pyc has already vouched for, so a
warm collect over an unchanged file skips the pyc probe and returns the same verdict.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``), ``README.md``,
``ROADMAP.md`` and the conventions under ``tests/`` (pyc forging mirrors test_iter288 /
test_iter333). Header probes are counted by wrapping the module-level
``_pyc_header_matches`` seam the spec names; everything else drives the public
``SyntaxErrorCollector().collect``, ``pyc_vouch_memo_stats``, ``pyc_trusted_count`` and
``clear_parse_memo``. No wall-clock bound, no sha pin, no network.

Every source mtime is pinned to a whole second before its pyc is forged, so a +1 ns
utime (behavior 4) can never cross a second boundary.
"""

from __future__ import annotations

import importlib.util
import os
import re
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
    pyc_vouch_memo_stats,
)

REPO = Path(__file__).resolve().parents[1]
T = 1_700_000_000  # a fixed whole-second source mtime


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Any:
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "pycache_prefix", None)
    clear_parse_memo()
    yield
    clear_parse_memo()


def _write(ws: Path, name: str, text: str = "x = 1\n") -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    src = ws / name
    src.write_text(text, encoding="utf-8")
    os.utime(src, ns=(T * 10**9, T * 10**9))
    return src


def _forge(src: Path) -> Path:
    """Write a valid interpreter (timestamp) pyc whose header matches ``src``'s stat."""
    cache_dir = src.parent / "__pycache__"
    cache_dir.mkdir(parents=True, exist_ok=True)
    st = src.stat()
    header = (
        importlib.util.MAGIC_NUMBER
        + struct.pack("<I", 0)
        + struct.pack("<II", int(st.st_mtime) & 0xFFFFFFFF, st.st_size & 0xFFFFFFFF)
    )
    path = cache_dir / f"{src.stem}.{sys.implementation.cache_tag}.pyc"
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


def _collect(ws: Path) -> list[str]:
    return [s.model_dump_json() for s in SyntaxErrorCollector().collect(ws)]


def test_b1_b2_warm_skip_and_stats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "ws"
    _forge(_write(ws, "a.py"))
    calls = _spy(monkeypatch)

    first_stats = pyc_vouch_memo_stats()
    assert first_stats == {"hits": 0, "entries": 0}
    first_stats["hits"] = 999
    first_stats["entries"] = 999
    assert pyc_vouch_memo_stats() == {"hits": 0, "entries": 0}, "stats must be a fresh copy"

    before = pyc_trusted_count()
    cold = _collect(ws)
    assert len(calls) >= 1, "B1: the first collect must probe the pyc"
    assert pyc_trusted_count() == before + 1
    assert pyc_vouch_memo_stats() == {"hits": 0, "entries": 1}

    calls.clear()
    warm = _collect(ws)
    assert len(calls) == 0, f"B1: warm collect must make 0 header probes, got {calls}"
    assert warm == cold, "B1: warm and cold signals must be identical"
    assert pyc_trusted_count() == before + 2, "B1: a memo hit still counts as trusted"
    stats = pyc_vouch_memo_stats()
    assert set(stats) == {"hits", "entries"}
    assert stats == {"hits": 1, "entries": 1}


def test_b3_edit_reprobes_and_syntax_error_matches_cold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    src = _write(ws, "a.py")
    _forge(src)
    calls = _spy(monkeypatch)
    _collect(ws)
    _collect(ws)
    hits = pyc_vouch_memo_stats()["hits"]
    assert hits == 1

    # (a) different byte size -> memo miss, probe happens, hits does not rise.
    _write(ws, "a.py", "x = 12345\n")
    calls.clear()
    clean = _collect(ws)
    assert len(calls) >= 1, "B3a: a size change must re-probe"
    assert pyc_vouch_memo_stats()["hits"] == hits

    # (b) a SyntaxError edit: the warm process reports exactly what a cold one does.
    _write(ws, "a.py", "def broken(:\n    pass\n")
    warm = _collect(ws)
    assert warm != clean and warm, "B3b: the syntax error must surface"
    assert pyc_vouch_memo_stats()["hits"] == hits
    clear_parse_memo()
    cold = _collect(ws)
    assert warm == cold, f"B3b: warm {warm} != cold {cold}"


def test_b4_mtime_ns_alone_reprobes_but_stays_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    src = _write(ws, "a.py")
    _forge(src)
    calls = _spy(monkeypatch)
    _collect(ws)
    size = src.stat().st_size
    os.utime(src, ns=(T * 10**9 + 1, T * 10**9 + 1))
    assert src.stat().st_size == size and src.stat().st_mtime_ns == T * 10**9 + 1
    calls.clear()
    before_hits = pyc_vouch_memo_stats()["hits"]
    before = pyc_trusted_count()
    _collect(ws)
    assert len(calls) >= 1, "B4: a +1 ns mtime change must be a memo miss"
    assert pyc_vouch_memo_stats()["hits"] == before_hits
    assert pyc_trusted_count() == before + 1, "B4: whole-second header still vouches"


def test_b5_only_trust_is_remembered(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    src = _write(ws, "a.py")
    before = pyc_trusted_count()
    one = _collect(ws)
    two = _collect(ws)
    assert one == two
    assert pyc_vouch_memo_stats() == {"hits": 0, "entries": 0}
    assert pyc_trusted_count() == before
    _forge(src)
    _collect(ws)
    assert pyc_trusted_count() == before + 1, "B5: a new pyc is honoured next collect"
    assert pyc_vouch_memo_stats()["entries"] == 1


def test_b6_clear_empties_memo_and_reprobes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    _forge(_write(ws, "a.py"))
    calls = _spy(monkeypatch)
    _collect(ws)
    _collect(ws)
    assert pyc_vouch_memo_stats() == {"hits": 1, "entries": 1}
    assert clear_parse_memo() is None
    assert pyc_vouch_memo_stats() == {"hits": 0, "entries": 0}
    calls.clear()
    _collect(ws)
    assert len(calls) >= 1, "B6: after clear the next collect must probe again"


def test_b7_cap_fifo_and_zero_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "ws"
    for name in ("a.py", "b.py", "c.py"):
        _forge(_write(ws, name))
    monkeypatch.setattr(syntax_error, "PYC_VOUCH_MEMO_MAX_ENTRIES", 2)
    _collect(ws)
    assert pyc_vouch_memo_stats()["entries"] == 2
    names = {Path(key[0]).name for key in syntax_error._PYC_VOUCH_MEMO}
    assert names == {"b.py", "c.py"}, f"B7: oldest must be evicted first, kept {names}"
    _collect(ws)
    assert pyc_vouch_memo_stats() == {"hits": 0, "entries": 2}, "B7: cyclic FIFO thrash"
    assert len(syntax_error._PYC_VOUCH_MEMO) <= 2

    clear_parse_memo()
    monkeypatch.setattr(syntax_error, "PYC_VOUCH_MEMO_MAX_ENTRIES", 0)
    before = pyc_trusted_count()
    _collect(ws)
    _collect(ws)
    assert pyc_vouch_memo_stats() == {"hits": 0, "entries": 0}
    assert pyc_trusted_count() == before + 6, "cap 0 still trusts via the probe"


def test_b8_direct_probe_is_unmemoized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "ws"
    src = _write(ws, "a.py")
    _forge(src)
    _collect(ws)
    _collect(ws)
    assert pyc_vouch_memo_stats()["hits"] == 1
    calls = _spy(monkeypatch)
    st = src.stat()
    for _ in range(2):
        calls.clear()
        assert _pyc_says_ok(src, st.st_mtime, st.st_size) is True
        assert len(calls) >= 1, "B8: a direct _pyc_says_ok call must always probe"


def test_b9_records() -> None:
    row = "- #388 syntax_error memoizes pyc vouches (foundry iter 327)"
    texts = [
        (REPO / name).read_text(encoding="utf-8")
        for name in ("ROADMAP.md", "ROADMAP_ARCHIVE.md")
        if (REPO / name).exists()
    ]
    hits = sum(
        1 for text in texts for line in text.splitlines() if line.startswith("- #388 ")
    )
    assert hits == 1, f"B9: exactly one #388 row across roadmap files, got {hits}"
    assert any(row in text for text in texts)
    ledger = (REPO / "tests" / "test_iter264_behavior.py").read_text(encoding="utf-8")
    match = re.search(r"^EXPECTED_LEDGER_ROWS\s*=\s*(\d+)", ledger, re.M)
    assert match and int(match.group(1)) >= 177
