"""Black-box oracle for foundry iteration 327 (state-dir iteration 477, ROADMAP #307):
``SyntaxErrorCollector`` trusts a VALID pytest assertion-rewritten PEP 552 timestamp pyc
before ``compile()`` -- written by the tester from the spec alone (pm.md
``## Expected Behaviors``), the repo's own ``tests/`` tree, ``SPEC.md``,
``ROADMAP.md`` / ``ROADMAP_ARCHIVE.md`` and by RUNNING the collector.

WHY THIS MODULE EXISTS.  Commit 3f1455d (ROADMAP #299) taught ``_pyc_says_ok`` to skip
any ``.py`` whose interpreter pyc carries a valid PEP 552 timestamp header.  This iteration
extends that trust to pytest assertion-rewritten pyc files
(``<stem>.<cache_tag>-pytest-<NNN>.pyc``, NNN any positive integer) so that the 297 test
modules that only carry a pytest pyc (not an interpreter pyc) also skip ``compile()``.

WHAT THIS MODULE GRADES (ONE collected item -- the gauge read ``binding_headroom=7`` at the
reviewer commit, and pm.md funds the new item by retiring
``test_iter83_behavior.py::test_b8_version_frozen`` whose keeper is
``test_iter81_behavior.py::test_b8_version_frozen``):
(1) EB1: a pytest assertion-rewritten pyc with a valid PEP 552 timestamp header matching
the source stat makes ``_pyc_says_ok`` return True, ``pyc_trusted_count()`` increment by 1,
and no ``syntax_error`` signal emitted; stale / missing / non-timestamp pytest pyc falls
through to ``compile()`` as before; when neither the interpreter pyc NOR any pytest pyc
matches, ``_pyc_says_ok`` returns False.

ISOLATION CONTRACT (honored).  Every assertion was written from pm.md's Expected Behaviors,
the ``tests/`` tree, ``SPEC.md``, the two roadmap files, and by RUNNING
``SyntaxErrorCollector``.  No file under ``src/`` was read by the tester; no
engineer/reviewer notes, no ``git diff``.

Offline and deterministic: no subprocess, no network; every pyc is built into ``tmp_path``
at runtime.  Nothing here asserts on docstring LAYOUT (3.13 strips the common indent, 3.12
does not) -- only on substrings.
"""

from __future__ import annotations

import ast
import builtins
import importlib.util
import struct
import sys
from pathlib import Path
from typing import Any

from proactive_loop.collectors import syntax_error
from proactive_loop.collectors.syntax_error import (
    SyntaxErrorCollector,
    _pyc_says_ok,
    clear_parse_memo,
    pyc_trusted_count,
)
from tests.test_iter172_behavior import roadmap_size_bounds

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "SPEC.md"
ROADMAP = REPO / "ROADMAP.md"
ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"

COLLECTED_ITEMS = 1
ITER_TAG = "(foundry iter 327)"
LEDGER_ROW_NUMBER = 307

RETIRED_TESTS: tuple[tuple[str, str], ...] = (
    ("test_iter83_behavior.py", "test_b8_version_frozen"),
)
KEEPERS: tuple[tuple[str, str], ...] = (
    ("test_iter81_behavior.py", "test_b8_version_frozen"),
)

_REAL_COMPILE = builtins.compile


class _CompileSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(args)
        return _REAL_COMPILE(*args, **kwargs)


def _forge_pytest_pyc(
    src: Path,
    *,
    nnn: int | str = 1,
    magic: bytes | None = None,
    mtime_delta: int = 0,
    size_delta: int = 0,
    short: bool = False,
    flags: int = 0,
) -> Path:
    """Write a pytest assertion-rewritten pyc with a PEP 552 header.

    ``<stem>.<cache_tag>-pytest-<NNN>.pyc`` in ``__pycache__/``.
    """
    if magic is None:
        magic = importlib.util.MAGIC_NUMBER
    tag = sys.implementation.cache_tag
    stem = src.stem
    pyc_name = f"{stem}.{tag}-pytest-{nnn}.pyc"
    cache_dir = src.parent / "__pycache__"
    cache_dir.mkdir(parents=True, exist_ok=True)
    pyc_path = cache_dir / pyc_name

    st = src.stat()
    mtime_word = (int(st.st_mtime) + mtime_delta) & 0xFFFFFFFF
    size_word = (st.st_size + size_delta) & 0xFFFFFFFF

    header = magic + struct.pack("<I", flags) + struct.pack("<II", mtime_word, size_word)
    if short:
        header = header[:8]
    pyc_path.write_bytes(header + b"\x00" * 8)
    return pyc_path


def _install_spy(monkeypatch: "Any") -> _CompileSpy:
    spy = _CompileSpy()
    monkeypatch.setattr(syntax_error, "compile", spy, raising=False)
    return spy


def test_b1_pytest_pyc_trust_skips_compile_and_stale_falls_through(
    tmp_path: Path, monkeypatch: Any
) -> None:
    ok = tmp_path / "ok.py"
    ok.write_text("x = 1\n", encoding="utf-8")

    # -- PART A: a valid pytest pyc with matching header trusts the file --
    pyc = _forge_pytest_pyc(ok, nnn=42)
    assert pyc.is_file(), "precondition: pytest pyc was written"
    assert f"-pytest-42.pyc" in pyc.name, "precondition: name matches pattern"

    clear_parse_memo()
    spy = _install_spy(monkeypatch)
    count_before = pyc_trusted_count()

    result = _pyc_says_ok(ok, ok.stat().st_mtime, ok.stat().st_size)
    assert result is True, (
        "EB1: _pyc_says_ok must return True for a valid pytest pyc"
    )

    monkeypatch.undo()
    clear_parse_memo()
    spy2 = _install_spy(monkeypatch)

    sigs = SyntaxErrorCollector().collect(tmp_path)
    assert sigs == [], (
        f"EB1: no syntax_error signal when a valid pytest pyc exists; got {sigs!r}"
    )
    assert spy2.calls == [], (
        f"EB1: compile() must be skipped for a pytest-pyc-trusted file; "
        f"got {len(spy2.calls)} call(s)"
    )
    assert pyc_trusted_count() >= 1, (
        f"EB1: pyc_trusted_count() must increment; got {pyc_trusted_count()}"
    )

    # -- PART B: different NNN values work (positive integers) --
    monkeypatch.undo()
    pyc.unlink()
    for nnn in (1, 999):
        pyc_n = _forge_pytest_pyc(ok, nnn=nnn)
        clear_parse_memo()
        assert _pyc_says_ok(ok, ok.stat().st_mtime, ok.stat().st_size) is True, (
            f"EB1: _pyc_says_ok must accept NNN={nnn}"
        )
        pyc_n.unlink()

    # -- PART B2: dotted version strings (real pytest naming) --
    for ver in ("9.1.1", "8.0.0", "10.2.3"):
        pyc_v = _forge_pytest_pyc(ok, nnn=ver)
        clear_parse_memo()
        assert _pyc_says_ok(ok, ok.stat().st_mtime, ok.stat().st_size) is True, (
            f"EB1: _pyc_says_ok must accept dotted version NNN={ver!r}"
        )
        pyc_v.unlink()

    # -- PART B3: invalid suffixes are rejected --
    for bad in ("abc", "9..1", ".9", "9.", ""):
        if bad == "":
            bad_name = f"{ok.stem}.{sys.implementation.cache_tag}-pytest-.pyc"
        else:
            bad_name = f"{ok.stem}.{sys.implementation.cache_tag}-pytest-{bad}.pyc"
        cache_dir_b3 = ok.parent / "__pycache__"
        cache_dir_b3.mkdir(parents=True, exist_ok=True)
        bad_path = cache_dir_b3 / bad_name
        st = ok.stat()
        hdr = (
            importlib.util.MAGIC_NUMBER
            + struct.pack("<I", 0)
            + struct.pack("<II", int(st.st_mtime) & 0xFFFFFFFF, st.st_size & 0xFFFFFFFF)
        )
        bad_path.write_bytes(hdr + b"\x00" * 8)
        clear_parse_memo()
        assert _pyc_says_ok(ok, ok.stat().st_mtime, ok.stat().st_size) is False, (
            f"EB1: _pyc_says_ok must reject invalid suffix {bad!r}"
        )
        bad_path.unlink()

    # -- PART C: stale pytest pyc (mtime off by 1) falls through --
    stale = _forge_pytest_pyc(ok, nnn=1, mtime_delta=1)
    clear_parse_memo()
    assert _pyc_says_ok(ok, ok.stat().st_mtime, ok.stat().st_size) is False, (
        "EB1: a stale pytest pyc (mtime mismatch) must not be trusted"
    )
    stale.unlink()

    # -- PART D: stale pytest pyc (size off by 1) falls through --
    stale_sz = _forge_pytest_pyc(ok, nnn=1, size_delta=1)
    clear_parse_memo()
    assert _pyc_says_ok(ok, ok.stat().st_mtime, ok.stat().st_size) is False, (
        "EB1: a stale pytest pyc (size mismatch) must not be trusted"
    )
    stale_sz.unlink()

    # -- PART E: wrong magic falls through --
    bad_magic = _forge_pytest_pyc(ok, nnn=1, magic=b"\x00\x00\r\n")
    clear_parse_memo()
    assert _pyc_says_ok(ok, ok.stat().st_mtime, ok.stat().st_size) is False, (
        "EB1: a wrong-magic pytest pyc must not be trusted"
    )
    bad_magic.unlink()

    # -- PART F: short header falls through --
    short_hdr = _forge_pytest_pyc(ok, nnn=1, short=True)
    clear_parse_memo()
    assert _pyc_says_ok(ok, ok.stat().st_mtime, ok.stat().st_size) is False, (
        "EB1: a short-header pytest pyc must not be trusted"
    )
    short_hdr.unlink()

    # -- PART G: non-timestamp (hash-based, flags != 0) falls through --
    hash_pyc = _forge_pytest_pyc(ok, nnn=1, flags=1)
    clear_parse_memo()
    assert _pyc_says_ok(ok, ok.stat().st_mtime, ok.stat().st_size) is False, (
        "EB1: a hash-based pytest pyc (flags != 0) must not be trusted"
    )
    hash_pyc.unlink()

    # -- PART H: missing __pycache__ dir -- no pyc at all --
    cache_dir = ok.parent / "__pycache__"
    if cache_dir.exists():
        import shutil
        shutil.rmtree(cache_dir)
    clear_parse_memo()
    assert _pyc_says_ok(ok, ok.stat().st_mtime, ok.stat().st_size) is False, (
        "EB1: with no pyc at all, _pyc_says_ok must return False"
    )

    # -- PART I: records -- SPEC.md mentions pytest pyc, ROADMAP Done row, funding --
    spec_text = SPEC.read_text(encoding="utf-8")
    assert "pytest" in spec_text and "assertion-rewritten" in spec_text, (
        "EB1 / AC5: SPEC.md §4.1 must mention pytest assertion-rewritten pyc trust"
    )
    assert "<cache_tag>-pytest-<NNN>" in spec_text or "cache_tag" in spec_text, (
        "EB1 / AC5: SPEC.md must describe the pytest pyc naming pattern"
    )

    roadmap_text = ROADMAP.read_text(encoding="utf-8")
    ledger_lines = [
        line for line in roadmap_text.splitlines()
        if line.startswith(f"- #{LEDGER_ROW_NUMBER} ")
    ]
    assert len(ledger_lines) == 1, (
        f"EB1 / AC6: exactly one Done-ledger row for #{LEDGER_ROW_NUMBER}; got {ledger_lines!r}"
    )
    row = ledger_lines[0]
    assert ITER_TAG in row, f"EB1 / AC6: ledger row tagged {ITER_TAG}"
    assert "pytest" in row.lower() or "pyc" in row.lower(), (
        "EB1 / AC6: ledger row mentions the feature"
    )

    # Funding: retired test is gone, keeper survives
    tests_dir = REPO / "tests"
    for module, name in RETIRED_TESTS:
        source = (tests_dir / module).read_text(encoding="utf-8")
        assert f"def {name}(" not in source, (
            f"EB1 / AC7: {module}::{name} was retired; it is back"
        )
    for module, name in KEEPERS:
        source = (tests_dir / module).read_text(encoding="utf-8")
        assert f"def {name}(" in source, (
            f"EB1 / AC7: keeper {module}::{name} must survive"
        )

    # Self-check: this module holds exactly COLLECTED_ITEMS test functions
    own_source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(own_source)
    collected = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert len(collected) == COLLECTED_ITEMS, (
        f"self-check: this module holds exactly {COLLECTED_ITEMS} collected items; "
        f"got {collected}"
    )
    marker = "param" + "etrize"
    assert marker not in own_source.replace('"param" + "etrize"', ""), (
        "self-check: no parametrization multiplies the collected count"
    )
    assert roadmap_size_bounds(own_source) == (), (
        "this module must not bound ROADMAP.md by size; "
        f"found {roadmap_size_bounds(own_source)}"
    )
