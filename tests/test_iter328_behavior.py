"""Black-box oracle for foundry iter 591 (factory iter 328): the default
``collect_live_test_count()`` call is memoized once per process and per resolved
``subprocess.run`` object, while every ``cwd=``/``env=`` call, every failed
collection and every replaced ``subprocess`` seam still spawns and fails loudly.

ISOLATION CONTRACT (honored): written only from the iteration spec (pm.md), the
README, the existing ``tests/`` tree (the guard module lives there) and real
runs. No ``src/`` implementation, no engineer/reviewer notes, no ``git diff``.

Measured win (behaviour 8, recorded here and NOT asserted -- ship hazard H2):
within one process N default calls cost ONE collection child; behaviour 1 below
proves it structurally by counting runner invocations through a seam.

The module collects ONE item, ``test_live_count_collection_is_memoized``, which clears
every ``PLA_*`` env var and asserts ``iter591_live_count_memo``'s returned check count
(until factory iter 602 it was hosted, uncollected, in test_iter317 under the 6-item
binding wall). The ROADMAP byte budget (behaviour 10) is owned by test_iter280/308 and
the ledger row count by test_iter264; this module only checks the row text, so it
re-pins no size.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import subprocess
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests import test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parents[1]
_TOTAL = re.compile(r"(\d+) tests? collected")
_REAL_RUN = subprocess.run


class _Counting:
    """A runner seam that records each call and returns a scripted result
    (or delegates to the real ``subprocess.run`` when ``delegate`` is set)."""

    def __init__(self, *, delegate: bool = False) -> None:
        self.delegate = delegate
        self.calls: list[list[str]] = []
        self.returncode = 0
        self.stdout = "11 tests collected in 0.01s\n"
        self.last_stdout = ""

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if self.delegate:
            proc = _REAL_RUN(argv, **kwargs)
            self.last_stdout = proc.stdout
            return proc
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "")


class _ExplodingModule:
    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"iter591 seam exploded on {name!r}")


def _use(monkeypatch: pytest.MonkeyPatch, run: Callable[..., Any]) -> None:
    monkeypatch.setattr(guard, "subprocess", types.SimpleNamespace(run=run))


def _b1_default_calls_spawn_once(monkeypatch: pytest.MonkeyPatch) -> int:
    guard.clear_live_count_memo()
    real = _Counting(delegate=True)
    _use(monkeypatch, real)
    first = guard.collect_live_test_count()
    second = guard.collect_live_test_count()
    assert len(real.calls) == 1, real.calls
    assert isinstance(first, int) and first > 0
    assert first == second
    argv = real.calls[0]
    for flag in ("--collect-only", "-q", "-o", "addopts=", "-p", "no:cacheprovider"):
        assert flag in argv, (flag, argv)
    m = _TOTAL.search(real.last_stdout)
    assert m is not None, real.last_stdout[-400:]
    assert first == int(m.group(1))
    return first


def _b2_cwd_and_env_bypass(monkeypatch: pytest.MonkeyPatch, tmp: Path) -> None:
    empty = tmp / "empty"
    empty.mkdir(parents=True)
    real = _Counting(delegate=True)
    _use(monkeypatch, real)
    for _ in range(2):
        with pytest.raises(AssertionError) as exc:
            guard.collect_live_test_count(cwd=empty)
        assert "exited" in str(exc.value)
    assert len(real.calls) == 2
    fake = _Counting()
    _use(monkeypatch, fake)
    assert guard.collect_live_test_count(env={}) == 11
    assert guard.collect_live_test_count(env={"X": "1"}) == 11
    assert len(fake.calls) == 2
    # an env= success did not seed the default memo for this runner
    assert guard.collect_live_test_count() == 11
    assert len(fake.calls) == 3


def _b3_failures_never_memoized(monkeypatch: pytest.MonkeyPatch) -> None:
    guard.clear_live_count_memo()
    fake = _Counting()
    _use(monkeypatch, fake)
    fake.returncode = 1
    with pytest.raises(AssertionError) as exc:
        guard.collect_live_test_count()
    assert "pytest --collect-only exited 1" in str(exc.value)
    fake.returncode, fake.stdout = 0, "no total here\n"
    with pytest.raises(AssertionError) as exc:
        guard.collect_live_test_count()
    msg = str(exc.value)
    assert "could not parse a '<N> tests collected' total" in msg
    assert "addopts" in msg and "Output tail" in msg
    fake.stdout = "23 tests collected in 0.02s\n"
    assert guard.collect_live_test_count() == 23
    assert len(fake.calls) == 3
    assert guard.collect_live_test_count() == 23
    assert len(fake.calls) == 3


def _b4_replaced_seam_bypasses_memo(monkeypatch: pytest.MonkeyPatch, genuine: int) -> None:
    monkeypatch.setattr(guard, "subprocess", subprocess)
    assert guard.collect_live_test_count() == genuine  # real runner, may warm memo
    garbage = _Counting()
    garbage.stdout = "garbage\n"
    _use(monkeypatch, garbage)
    with pytest.raises(AssertionError, match="could not parse"):
        guard.collect_live_test_count()
    assert len(garbage.calls) == 1
    monkeypatch.setattr(guard, "subprocess", _ExplodingModule())
    with pytest.raises(RuntimeError, match="iter591 seam exploded"):
        guard.collect_live_test_count()
    monkeypatch.setattr(guard, "subprocess", subprocess)
    assert guard.collect_live_test_count() == genuine  # memo survives the detour


def _b5_clear_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Counting()
    _use(monkeypatch, fake)
    assert guard.collect_live_test_count() == 11
    assert guard.collect_live_test_count() == 11
    assert len(fake.calls) == 1
    assert guard.clear_live_count_memo() is None
    assert guard.collect_live_test_count() == 11
    assert len(fake.calls) == 2


def _b6_docstring() -> None:
    doc = inspect.getdoc(guard.collect_live_test_count) or ""
    flat = " ".join(doc.split())
    low = flat.lower()
    assert "no cached constant" not in low
    assert "FAILS LOUDLY" in flat
    assert "memo" in low and "real successful collection" in low
    assert "per process" in low and "never cached" in low
    assert "cwd=" in flat and "env=" in flat and "bypass" in low


def _b7_callers_unchanged() -> None:
    host = (REPO / "tests" / "test_iter143_behavior.py").read_text(encoding="utf-8")
    assert "live = guard.collect_live_test_count()" in host
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^readme-headroom:", makefile, re.M), "readme-headroom target gone"


def _b9_one_collected_test() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    names = [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert names, "module parsed to nothing"
    collected = [n for n in names if n.startswith("test") or n.startswith("Test")]
    assert collected == ["test_live_count_collection_is_memoized"], names


def _b10_ledger_row() -> None:
    text = (REPO / "ROADMAP.md").read_text(encoding="utf-8")
    row = "- #378 Live-count collection memoized per process (foundry iter 327)"
    assert row in text
    assert text.count("#378 ") == 1


def iter591_live_count_memo(monkeypatch: pytest.MonkeyPatch, tmp: Path) -> int:
    """Run every iter-591 check; returns how many ran (asserted by the host)."""
    try:
        genuine = _b1_default_calls_spawn_once(monkeypatch)
        _b2_cwd_and_env_bypass(monkeypatch, tmp)
        _b3_failures_never_memoized(monkeypatch)
        _b4_replaced_seam_bypasses_memo(monkeypatch, genuine)
        _b5_clear_hook(monkeypatch)
    finally:
        monkeypatch.setattr(guard, "subprocess", subprocess)
    _b6_docstring()
    _b7_callers_unchanged()
    _b9_one_collected_test()
    _b10_ledger_row()
    return 9


def test_live_count_collection_is_memoized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Own collected item (no longer hosted in test_iter317), so a regression is reported
    under THIS behavior's name and cannot hide the other harnesses."""
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    assert iter591_live_count_memo(monkeypatch, tmp_path / "h") == 9
