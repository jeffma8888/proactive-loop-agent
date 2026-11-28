"""Black-box oracle for factory iter 602: un-host the 13 zero-item harnesses.

Before this iteration the behavior modules tests/test_iter324..336 collected
ZERO items and ran inside ``test_iter317::test_runs_older_than_filters_by_checkpoint_age``,
so a regression there carried the wrong name. Each module now collects exactly
one ``test_*`` wrapper named for its behavior, the host imports none of them,
and the README's published floor moved up one hundred (see NEW_FLOOR).

The checks below read the test modules as text (AST) and drive each wrapper with
its harness stubbed, so they never depend on the product's internals.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# module number -> (harness function name, count the old host asserted)
HARNESSES: dict[int, tuple[str, int]] = {
    324: ("iter587_trace_newest", 5),
    325: ("iter588_run_dir_not_a_directory", 5),
    326: ("iter589_scripted_file_faults", 3),
    327: ("iter590_emit_tails", 5),
    328: ("iter591_live_count_memo", 9),
    329: ("iter592_readme_cli_census", 7),
    330: ("iter593_dispatch_default_slate", 8),
    331: ("iter595_empty_workspace", 4),
    332: ("iter596_ranked_pairs", 5),
    333: ("iter597_pyc_listing", 6),
    334: ("iter598_shared_flags_census", 7),
    335: ("iter600_empty_path_flags", 8),
    336: ("iter601_demo_default_slate", 6),
}

MARKER = "PORTFOLIO INTRO \u2014 human-owned"
# Spelled in pieces so this module is not itself a floor carrier for the census.
OLD_FLOOR = "6," + "000"
NEW_FLOOR = "6," + "100"


def _module_tests(n: int) -> list[ast.FunctionDef]:
    tree = ast.parse((TESTS / f"test_iter{n}_behavior.py").read_text(encoding="utf-8"))
    classes = [c.name for c in tree.body if isinstance(c, ast.ClassDef) and c.name.startswith("Test")]
    assert classes == [], f"test_iter{n}: unexpected collected classes {classes}"
    return [f for f in tree.body if isinstance(f, ast.FunctionDef) and f.name.startswith("test")]


def _asserted_harness_counts(fn: ast.FunctionDef) -> list[tuple[str, int]]:
    """Every ``assert <name>(...) == <int>`` inside ``fn``."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare):
            continue
        cmp = node.test
        if (
            isinstance(cmp.left, ast.Call)
            and isinstance(cmp.left.func, ast.Name)
            and len(cmp.ops) == 1
            and isinstance(cmp.ops[0], ast.Eq)
            and isinstance(cmp.comparators[0], ast.Constant)
            and isinstance(cmp.comparators[0].value, int)
        ):
            found.append((cmp.left.func.id, cmp.comparators[0].value))
    return found


def test_each_harness_module_collects_one_wrapper_asserting_the_host_count() -> None:
    """B1: one module-level test per module, asserting the host's count."""
    problems: list[str] = []
    for n, (harness, count) in HARNESSES.items():
        tests = _module_tests(n)
        if len(tests) != 1:
            problems.append(f"test_iter{n}: {len(tests)} collected tests {[t.name for t in tests]}")
            continue
        wrapper = tests[0]
        # named for its behavior, not a generic placeholder
        if wrapper.name in {"test", "test_harness", "test_behavior", "test_it"} or len(wrapper.name) < 12:
            problems.append(f"test_iter{n}: wrapper name {wrapper.name!r} is not descriptive")
        if (harness, count) not in _asserted_harness_counts(wrapper):
            problems.append(f"test_iter{n}: {wrapper.name} does not assert {harness}(...) == {count}")
    assert problems == []


def test_host_no_longer_imports_or_calls_the_harnesses() -> None:
    """B2: test_iter317 hosts none of the 13 and keeps its own single test."""
    text = (TESTS / "test_iter317_behavior.py").read_text(encoding="utf-8")
    assert "from tests.test_iter3" not in text
    leaked = [h for h, _ in HARNESSES.values() if h in text]
    assert leaked == []
    tests = [
        f.name
        for f in ast.parse(text).body
        if isinstance(f, ast.FunctionDef) and f.name.startswith("test")
    ]
    assert tests == ["test_runs_older_than_filters_by_checkpoint_age"]
    for kept in ("_iter583", "_iter584", "_iter586"):
        assert kept in text, f"host lost its own half {kept}"


@pytest.mark.parametrize("n", sorted(HARNESSES))
def test_harness_regression_fails_under_its_own_name(
    n: int, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """B7 (+B1 env hygiene): a stubbed wrong count fails THIS module's wrapper,
    and the wrapper has cleared every PLA_* variable before the harness runs."""
    harness, count = HARNESSES[n]
    module = importlib.import_module(f"tests.test_iter{n}_behavior")
    (wrapper_def,) = _module_tests(n)
    wrapper = getattr(module, wrapper_def.name)

    seen_env: list[list[str]] = []

    def _stub(*_a: Any, **_k: Any) -> int:
        seen_env.append(sorted(k for k in os.environ if k.startswith("PLA_")))
        return count - 1

    monkeypatch.setenv("PLA_ITER337_SENTINEL", "1")
    monkeypatch.setattr(module, harness, _stub)
    kwargs = {p: request.getfixturevalue(p) for p in inspect.signature(wrapper).parameters}
    with pytest.raises(AssertionError):
        wrapper(**kwargs)
    assert len(seen_env) == 1, f"{wrapper_def.name} did not call {harness} exactly once"
    assert seen_env[0] == [], f"{wrapper_def.name} left PLA_* set: {seen_env[0]}"


def test_readme_publishes_the_raised_floor_and_keeps_the_intro() -> None:
    """B4: only the two floor tokens moved; the old floor is gone from README."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert MARKER in readme
    intro = readme.split(MARKER, 1)[0]
    assert f"**{NEW_FLOOR}+ tests**" in intro
    assert f"**{NEW_FLOOR}+ passing tests**" in intro
    assert "What this project demonstrates" in intro
    assert OLD_FLOOR not in readme


def test_roadmap_records_the_raise_once() -> None:
    """B6: exactly one #387 row naming the raise (archive-tolerant)."""
    row = f"#387 Floor {OLD_FLOOR} -> {NEW_FLOOR}; 13 harnesses collected (foundry iter 327)"
    texts = [
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("ROADMAP.md", "ROADMAP_ARCHIVE.md")
        if (ROOT / name).exists()
    ]
    assert sum(t.count(row) for t in texts) == 1
