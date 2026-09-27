"""Black-box oracle for foundry iteration 323 (state-dir iteration 471, ROADMAP #299):
``SyntaxErrorCollector`` trusts a VALID PEP 552 timestamp pyc before ``compile()`` --
written by the tester from the spec alone (pm.md ``## Expected Behaviors``), the repo's
own ``tests/`` tree, ``ROADMAP.md`` / ``ROADMAP_ARCHIVE.md`` and by RUNNING the collector.

WHY THIS MODULE EXISTS. At the parent commit every ``pla signals`` / ``pla scan`` re-parsed
each ``.py`` the interpreter had already proved parseable: a ``__pycache__`` pyc whose
16-byte timestamp header (``importlib.util.MAGIC_NUMBER``, flags ``0``, source mtime and
size) matches the source ``stat`` is exactly what ``import`` trusts. This module pins that
trust to the interpreter's OWN record and nothing looser: a hash-based pyc, a wrong magic,
a short header or a mtime/size mismatch must all fall through to today's parse, so a real
``SyntaxError`` is still reported when only a bogus pyc exists.

WHAT THIS MODULE GRADES (FOUR collected items -- the gauge read ``binding_headroom=6 ==
MIN_BINDING_HEADROOM`` at the parent commit, so the module is funded 1:1 by four retired
assert-message-only duplicates, see ``RETIRED_TESTS``; extra assertions live INSIDE these
four bodies, never as a fifth item or a parametrization):
(1) a timestamp pyc built by ``py_compile`` under the RUNNING interpreter makes
``collect`` return ``[]`` with ZERO ``compile`` calls, ``pyc_trusted_count() == 1`` and an
untouched parse memo (``{"hits": 0, "misses": 0, "entries": 0}`` -- the D3 3-key shape),
and (behavior 4) ``clear_parse_memo()`` zeroes the counter;
(2) a CHECKED_HASH pyc (flags != 0) falls back to ``compile`` (>= 1 call, counter 0,
exactly one memo miss, ``[]``);
(3) a forged pyc for a genuinely broken file -- wrong magic with correct mtime/size, size
word off by one, mtime word off by one, or a short header -- never excuses the error: the
signal list is IDENTICAL to the no-pyc (parent-commit) path and the counter stays 0;
(4) the records: ROADMAP.md drops index row ``#299``, gains exactly one ``#299`` Done-ledger
row (<= 120 chars, tagged ``(foundry iter 323)``), carries the replacement row ``#302`` and
keeps >= 20 index rows; ROADMAP_ARCHIVE.md gains the ``- **#299 -- `` bullet (no pipe, so it
cannot parse as a table row); the four named duplicates are gone and their canonical copies
survive; this module holds exactly four collected items; the module docstring carries the
stale-pyc exception; no interpreter cache-tag literal exists under ``src/`` or in this module.

ISOLATION CONTRACT (honored). Every assertion was written from pm.md's Expected Behaviors,
the ``tests/`` tree, the two roadmap files and by RUNNING ``SyntaxErrorCollector``. No
file under ``src/`` was read, no engineer/reviewer notes, no ``git diff``.

Offline and deterministic: no subprocess, no network; every pyc is built into ``tmp_path``
AFTER its source is final (an ``os.utime`` or copy after compiling would invalidate it --
the iter-278 mtime lesson) at ``importlib.util.cache_from_source`` so the 3.13 CI leg
sees its own tag, never a hardcoded one. Nothing here asserts on docstring LAYOUT
(3.13 strips the common indent, 3.12 does not) -- only on substrings.
"""

from __future__ import annotations

import ast
import builtins
import importlib.util
import py_compile
import struct
import sys
from pathlib import Path
from typing import Any

import pytest

from proactive_loop.collectors import syntax_error
from proactive_loop.collectors.syntax_error import (
    SyntaxErrorCollector,
    clear_parse_memo,
    parse_memo_stats,
    pyc_trusted_count,
)
from tests.test_iter172_behavior import roadmap_size_bounds

REPO = Path(__file__).resolve().parents[1]
ROADMAP = REPO / "ROADMAP.md"
ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"

#: The row this ship retires and the row the PM queued to hold the 20-row floor.
RETIRED_ROW = 299
REPLACEMENT_ROW = 302
ITER_TAG = "(foundry iter 323)"
MIN_INDEX_ROWS = 20  # tests/test_iter280_behavior.py::MIN_INDEX_ROWS
LEDGER_ROW_MAX_CHARS = 120  # tests/test_iter241_behavior.py cap
EMPTY_MEMO = {"hits": 0, "misses": 0, "entries": 0}
COLLECTED_ITEMS = 4

#: Behavior 6 funding: the assert-message-only duplicates pm.md named, in order, none of
#: which is a ``test_iter263::FAMILIES`` keeper nor lives in a ``REMAINDERS`` module.
RETIRED_TESTS: tuple[tuple[str, str], ...] = (
    ("test_iter92_behavior.py", "test_b7_collector_count_unchanged"),
    ("test_iter92_behavior.py", "test_b7_provider_count_unchanged"),
    ("test_iter128_behavior.py", "test_b8_no_new_runtime_dependency"),
    ("test_iter97_behavior.py", "test_b5_readme_sections_preserved"),
)
#: The canonical copy that must SURVIVE for each retirement above.
KEEPERS: tuple[tuple[str, str], ...] = (
    ("test_iter75_behavior.py", "test_b12_collector_count_fifteen"),
    ("test_iter81_behavior.py", "test_b8_provider_count_unchanged"),
    ("test_iter110_behavior.py", "test_b7_no_new_runtime_dependency"),
    ("test_iter58_behavior.py", "test_b6_readme_sections_preserved"),
)

PYC_HEADER_SIZE = 16
_REAL_COMPILE = builtins.compile


class _CompileSpy:
    """Records every ``compile`` call the collector makes and delegates to the builtin."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(args)
        return _REAL_COMPILE(*args, **kwargs)


def _cache_path(src: Path) -> Path:
    if sys.implementation.cache_tag is None:  # pragma: no cover -- CPython always tags
        pytest.skip("this interpreter writes no pyc, so nothing can be trusted")
    return Path(importlib.util.cache_from_source(str(src)))


def _compile_pyc(src: Path, mode: py_compile.PycInvalidationMode) -> Path:
    """Build the interpreter's own pyc for ``src`` AFTER the source is final."""
    cfile = _cache_path(src)
    py_compile.compile(str(src), cfile=str(cfile), invalidation_mode=mode, doraise=True)
    assert cfile.is_file(), f"precondition: py_compile wrote no pyc at {cfile}"
    return cfile


def _header(pyc: Path) -> bytes:
    return pyc.read_bytes()[:PYC_HEADER_SIZE]


def _forge_pyc(src: Path, *, magic: bytes, mtime_delta: int = 0, size_delta: int = 0) -> Path:
    """Write a 16-byte PEP 552 header (flags 0) at the interpreter's cache path for ``src``.

    With ``magic == importlib.util.MAGIC_NUMBER`` and zero deltas this is the header a
    trusted timestamp pyc carries; each keyword breaks exactly one of the four fields.
    """
    st = src.stat()
    words = struct.pack(
        "<II",
        (int(st.st_mtime) + mtime_delta) & 0xFFFFFFFF,
        (st.st_size + size_delta) & 0xFFFFFFFF,
    )
    cfile = _cache_path(src)
    cfile.parent.mkdir(parents=True, exist_ok=True)
    cfile.write_bytes(magic + struct.pack("<I", 0) + words + b"\x00" * 8)
    return cfile


def _install_spy(monkeypatch: pytest.MonkeyPatch) -> _CompileSpy:
    spy = _CompileSpy()
    monkeypatch.setattr(syntax_error, "compile", spy, raising=False)
    return spy


def _signal_shape(sigs: list[Any]) -> list[tuple[str, str, str]]:
    return [(s.kind, s.path, s.summary) for s in sigs]


# ===========================================================================
# Behavior 1 (+ behavior 4) -- a trusted timestamp pyc skips read, compile and memo;
# clear_parse_memo() zeroes the counter.
# ===========================================================================


def test_b1_trusted_timestamp_pyc_skips_compile_and_memo_and_clear_zeroes_the_counter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok = tmp_path / "ok.py"
    ok.write_text("x = 1\n", encoding="utf-8")
    pyc = _compile_pyc(ok, py_compile.PycInvalidationMode.TIMESTAMP)

    hdr = _header(pyc)
    st = ok.stat()
    assert hdr[:4] == importlib.util.MAGIC_NUMBER, "precondition: interpreter magic"
    assert struct.unpack("<I", hdr[4:8])[0] == 0, "precondition: timestamp pyc has flags 0"
    assert struct.unpack("<II", hdr[8:16]) == (
        int(st.st_mtime) & 0xFFFFFFFF,
        st.st_size & 0xFFFFFFFF,
    ), "precondition: header mtime/size words match the source stat"

    clear_parse_memo()
    spy = _install_spy(monkeypatch)

    assert SyntaxErrorCollector().collect(tmp_path) == [], (
        "behavior 1: a file the interpreter compiled clean yields no signal"
    )
    assert spy.calls == [], (
        f"behavior 1: a trusted pyc must skip compile(); recorded {len(spy.calls)} call(s)"
    )
    assert pyc_trusted_count() == 1, (
        f"behavior 1: exactly one file was trusted; got {pyc_trusted_count()}"
    )
    assert parse_memo_stats() == EMPTY_MEMO, (
        "behavior 1 / D3: a trusted file never enters the parse memo and the stats keep "
        f"their exact 3-key shape; got {parse_memo_stats()!r}"
    )

    # Behavior 4 -- clear_parse_memo() zeroes the counter (and returns None, as before).
    assert clear_parse_memo() is None, "behavior 4: clear_parse_memo() returns None"
    assert pyc_trusted_count() == 0, (
        f"behavior 4: clear_parse_memo() must zero the counter; got {pyc_trusted_count()}"
    )
    assert parse_memo_stats() == EMPTY_MEMO

    # The counter is process-wide and cumulative between clears: a second trusted collect
    # counts the same file again, and a fresh instance reads the same counter.
    assert SyntaxErrorCollector().collect(tmp_path) == []
    assert SyntaxErrorCollector().collect(tmp_path) == []
    assert pyc_trusted_count() == 2, (
        f"behavior 1: the counter is process-wide, not per instance; got {pyc_trusted_count()}"
    )
    assert spy.calls == [], "behavior 1: still no compile() after two trusted collects"
    assert parse_memo_stats() == EMPTY_MEMO, "behavior 1: still no memo traffic"

    # Editing the source (new size) invalidates the trust: the next collect parses.
    ok.write_text("x = 1\ny = 2\n", encoding="utf-8")
    clear_parse_memo()
    assert SyntaxErrorCollector().collect(tmp_path) == []
    assert len(spy.calls) >= 1, "behavior 1: a size-changed source is parsed again"
    assert pyc_trusted_count() == 0, "behavior 1: a stale pyc is not trusted"
    assert parse_memo_stats()["misses"] == 1, "behavior 1: the parse is memoised as before"


# ===========================================================================
# Behavior 2 -- a hash-based pyc (flags != 0) falls back to compile.
# ===========================================================================


def test_b2_hash_based_pyc_falls_back_to_compile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok = tmp_path / "ok.py"
    ok.write_text("x = 1\n", encoding="utf-8")
    pyc = _compile_pyc(ok, py_compile.PycInvalidationMode.CHECKED_HASH)

    hdr = _header(pyc)
    assert hdr[:4] == importlib.util.MAGIC_NUMBER, "precondition: interpreter magic"
    assert struct.unpack("<I", hdr[4:8])[0] & 0b1, "precondition: hash-based flag bit set"

    clear_parse_memo()
    spy = _install_spy(monkeypatch)

    assert SyntaxErrorCollector().collect(tmp_path) == [], "behavior 2: valid source -> []"
    assert len(spy.calls) >= 1, (
        "behavior 2: a hash-based pyc must fall back to compile(); recorded 0 calls"
    )
    assert pyc_trusted_count() == 0, (
        f"behavior 2: a hash-based pyc is never trusted; got {pyc_trusted_count()}"
    )
    assert parse_memo_stats()["misses"] == 1, (
        f"behavior 2: the fallback parse is memoised exactly once; got {parse_memo_stats()!r}"
    )
    assert parse_memo_stats()["entries"] == 1
    assert set(parse_memo_stats()) == set(EMPTY_MEMO), "D3: no new stats key"

    # The interpreter's UNCHECKED_HASH flavour (flags 0b01) is hash-based too.
    pyc.unlink()
    _compile_pyc(ok, py_compile.PycInvalidationMode.UNCHECKED_HASH)
    clear_parse_memo()
    spy.calls.clear()
    assert SyntaxErrorCollector().collect(tmp_path) == []
    assert len(spy.calls) >= 1, "behavior 2: an unchecked-hash pyc also falls back"
    assert pyc_trusted_count() == 0


# ===========================================================================
# Behavior 3 -- a wrong-magic, mismatched or short pyc never excuses a real error.
# ===========================================================================


def test_b3_bogus_pyc_never_excuses_a_real_syntax_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def f(:\n", encoding="utf-8")

    # Baseline: the parent-commit path (no pyc at all) reports exactly one signal.
    clear_parse_memo()
    baseline = SyntaxErrorCollector().collect(tmp_path)
    assert len(baseline) == 1, f"precondition: one syntax_error signal; got {baseline!r}"
    assert baseline[0].kind == "syntax_error"
    assert baseline[0].path == "bad.py"
    assert "bad.py" in baseline[0].summary and "line 1" in baseline[0].summary
    assert pyc_trusted_count() == 0, "precondition: nothing to trust without a pyc"

    magic = importlib.util.MAGIC_NUMBER
    cases: tuple[tuple[str, dict[str, Any]], ...] = (
        ("wrong magic, correct flags/mtime/size", {"magic": b"\x00\x00\r\n"}),
        ("correct magic, size word off by one", {"magic": magic, "size_delta": 1}),
        ("correct magic, mtime word off by one", {"magic": magic, "mtime_delta": 1}),
    )
    for label, kwargs in cases:
        pyc = _forge_pyc(bad, **kwargs)
        assert len(_header(pyc)) == PYC_HEADER_SIZE
        clear_parse_memo()
        spy = _install_spy(monkeypatch)

        sigs = SyntaxErrorCollector().collect(tmp_path)

        assert len(sigs) == 1, f"behavior 3 [{label}]: exactly one signal; got {sigs!r}"
        assert _signal_shape(sigs) == _signal_shape(baseline), (
            f"behavior 3 [{label}]: same kind, relpath and line as the no-pyc path"
        )
        assert sigs == baseline, f"behavior 3 [{label}]: field-identical to the no-pyc path"
        assert pyc_trusted_count() == 0, (
            f"behavior 3 [{label}]: a bogus pyc is never trusted; got {pyc_trusted_count()}"
        )
        assert len(spy.calls) >= 1, f"behavior 3 [{label}]: the file was parsed"
        monkeypatch.undo()

    # A short header (fewer than 16 bytes) at the right path falls through as well.
    short = _cache_path(bad)
    short.write_bytes(magic + struct.pack("<I", 0))
    clear_parse_memo()
    sigs = SyntaxErrorCollector().collect(tmp_path)
    assert sigs == baseline, "behavior 3 [short header]: still reported"
    assert pyc_trusted_count() == 0, "behavior 3 [short header]: not trusted"

    # And a header that WOULD be trusted (right magic, flags 0, exact mtime/size) attached to a
    # broken source is the documented stale-pyc blind spot -- the identical trust ``import``
    # places in that pyc -- so it is excused, and that is the ONLY way a broken file is.
    _forge_pyc(bad, magic=magic)
    clear_parse_memo()
    assert SyntaxErrorCollector().collect(tmp_path) == [], (
        "D4: a header identical to the interpreter's own record is trusted exactly as "
        "import would trust it"
    )
    assert pyc_trusted_count() == 1


# ===========================================================================
# Behaviors 5-7 -- records, funding and unchanged contracts (one collected item).
# ===========================================================================


def _index_rows(text: str) -> list[str]:
    rows = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) > 2 and line.startswith("|") and parts[1].strip().isdigit():
            rows.append(line)
    return rows


def _b5_roadmap_records() -> None:
    roadmap = ROADMAP.read_text(encoding="utf-8")
    rows = _index_rows(roadmap)
    numbers = [int(r.split("|")[1].strip()) for r in rows]
    assert RETIRED_ROW not in numbers, (
        f"behavior 5(a): index row | {RETIRED_ROW} | must be deleted from ROADMAP.md"
    )
    assert numbers.count(REPLACEMENT_ROW) == 1, (
        f"behavior 5(d): exactly one replacement index row | {REPLACEMENT_ROW} |; got {numbers}"
    )
    assert len(rows) >= MIN_INDEX_ROWS, (
        f"behavior 5(d): the numeric index keeps >= {MIN_INDEX_ROWS} rows; got {len(rows)}"
    )
    replacement = next(r for r in rows if int(r.split("|")[1].strip()) == REPLACEMENT_ROW)
    assert "**QUEUED**" in replacement, "behavior 5(d): the replacement row is QUEUED"
    assert "prefetch" in replacement and "git_activity" in replacement, (
        "behavior 5(d): the replacement row is the git-children overlap slice (B2)"
    )

    ledger = [
        line for line in roadmap.splitlines() if line.startswith(f"- #{RETIRED_ROW} ")
    ]
    assert len(ledger) == 1, (
        f"behavior 5(c): exactly one Done-ledger row for #{RETIRED_ROW}; got {ledger!r}"
    )
    row = ledger[0]
    assert len(row) <= LEDGER_ROW_MAX_CHARS, (
        f"behavior 5(c): ledger row <= {LEDGER_ROW_MAX_CHARS} chars; got {len(row)}"
    )
    assert row.rstrip().endswith(ITER_TAG), f"behavior 5(c): ledger row tagged {ITER_TAG}"
    assert "syntax_error" in row and "pyc" in row, "behavior 5(c): names the feature"
    assert "-16%" in row and "-55%" in row, (
        "behavior 5(c): the ledger narrates the CORRECTED figure (-16%, not -55%)"
    )
    assert roadmap.count(ITER_TAG) == 1, (
        f"behavior 5(c): {ITER_TAG} appears exactly once in ROADMAP.md (one row per iteration)"
    )

    archive = ARCHIVE.read_text(encoding="utf-8")
    bullets = [
        line for line in archive.splitlines() if line.startswith(f"- **#{RETIRED_ROW} -- ")
    ]
    assert len(bullets) == 1, (
        f"behavior 5(b): exactly one archive bullet for #{RETIRED_ROW}; got {len(bullets)}"
    )
    bullet = bullets[0]
    assert "(retired from the index in iter-471, foundry iter 323)" in bullet
    assert "|" not in bullet, "behavior 5(b): pipes replaced so the bullet is not a table row"
    for cue in ("LAYER: L2", "STATUS: **QUEUED**", "SHIPPED:", "-106 ms", "-16%", "-55%"):
        assert cue in bullet, f"behavior 5(b): archive bullet carries {cue!r}"
    assert f"| {RETIRED_ROW} |" not in archive, "behavior 5(b): no table-row copy of #299"


def _b6_funding() -> None:
    tests_dir = REPO / "tests"
    for module, name in RETIRED_TESTS:
        source = (tests_dir / module).read_text(encoding="utf-8")
        assert f"def {name}(" not in source, (
            f"behavior 6: {module}::{name} was retired to fund this module; it is back"
        )
    for module, name in KEEPERS:
        source = (tests_dir / module).read_text(encoding="utf-8")
        assert f"def {name}(" in source, (
            f"behavior 6: canonical copy {module}::{name} must survive"
        )

    own_source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(own_source)
    collected = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert len(collected) == COLLECTED_ITEMS, (
        f"behavior 6: this module holds exactly {COLLECTED_ITEMS} collected items; "
        f"got {collected}"
    )
    marker = "param" + "etrize"
    assert marker not in own_source.replace('"param" + "etrize"', ""), (
        "behavior 6: no parametrization multiplies the collected count"
    )
    assert roadmap_size_bounds(own_source) == (), (
        "this module must not bound ROADMAP.md by size (test_iter172 census); "
        f"found {roadmap_size_bounds(own_source)}"
    )


def _b7_unchanged_contracts() -> None:
    doc = syntax_error.__doc__ or ""
    for cue in ("stale", "mtime", "size", "SyntaxError", "import"):
        assert cue in doc, f"behavior 7 / D4: module docstring carries {cue!r}"
    assert "exception" in doc.lower(), "behavior 7 / D4: the docstring names the exception"
    assert "MAGIC_NUMBER" in doc or "PEP 552" in doc, "behavior 7: names the trusted header"

    # The trust check must key on the RUNNING interpreter's cache tag (3.13 CI leg sees its
    # own pyc, never a 3.12 one), so no source file under src/ -- and not this module -- may
    # spell the tag out. (Two shipped pruning fixtures, test_iter52/178, write a fake
    # ``mod.<tag>.pyc`` byte to prove ``__pycache__`` is skipped; they predate this ship
    # and never decide trust, so the census is scoped to src/ plus this oracle.)
    tag_literal = "cpython-" + "312"
    offenders = []
    candidates = [p for p in sorted((REPO / "src").rglob("*.py")) if "__pycache__" not in p.parts]
    candidates.append(Path(__file__))
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        if tag_literal in text.replace('"cpython-" + "312"', ""):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], (
        f"behavior 7: no hardcoded interpreter cache tag under src/ or in this module; found {offenders}"
    )

    assert callable(pyc_trusted_count) and isinstance(pyc_trusted_count(), int)
    assert set(parse_memo_stats()) == set(EMPTY_MEMO), "D3: parse_memo_stats keeps 3 keys"


def test_b5_b6_b7_records_funding_and_unchanged_contracts() -> None:
    _b5_roadmap_records()
    _b6_funding()
    _b7_unchanged_contracts()
