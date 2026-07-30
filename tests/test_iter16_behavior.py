"""Black-box behavior tests for iteration 16.

Feature under test: a new **L2 perception collector**, ``TestPostureCollector``
(``kind == "test_posture"``). It walks a workspace and emits one signal per
top-level project directory (a direct child of ``root``, or ``"."`` for files
sitting directly in ``root``) that contains at least one *source* file, reporting
the ``(src, test)`` file counts and flagging the ``(untested)`` case so the
scout can surface an "add tests to X" goal it could not perceive before. It is
pure stdlib, deterministic, offline, and (like every collector) degrades to
``[]`` rather than raising.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.1 (the ``collectors`` module contract)
-- and drive only the documented public surface: the public collector API
``TestPostureCollector().collect(root)``, the ``all_collectors()`` registry, the
``Collector`` protocol, the ``ContextSignal`` domain model, and (behavior 13
only) the existing ``pla signals`` CLI via ``cli.main([...])``. **No file under
``src/`` was read, no engineer/reviewer notes were read, and no ``git diff`` was
consulted.** Signal field names (``source``/``kind``/``summary``/``detail``/
``path``/``weight``/``timestamp``) were taken from the public spec + model schema
and the existing published tests, never from the implementation. Every test runs
under a fresh ``tmp_path`` synthetic workspace it constructs itself; NONE assert
against ``examples/fixture_workspace`` (which is real source-without-tests inside
a git repo and would leak git-based kinds -- the iter-15 env-stability lesson).
Fully offline: zero network, zero API keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# NOTE: the collector class name starts with "Test", which pytest would try to
# collect as a test class. Alias it to a non-"Test" name so the module binding
# pytest sees is inert, while the class object itself is unchanged.
from proactive_loop.collectors import (
    TestPostureCollector as PostureCollector,
    all_collectors,
)
from proactive_loop.collectors.base import Collector
from proactive_loop.collectors.test_posture import (
    TestPostureCollector as PostureCollector_direct,
)
from proactive_loop.models import ContextSignal


# ---------------------------------------------------------------------------
# Helpers -- all black-box: build synthetic tmp workspaces, drive the public API.
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = "x = 1\n") -> Path:
    """Create *path* (and parents) with trivial, TODO-free code content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _by_project(signals: list[ContextSignal]) -> dict[str, ContextSignal]:
    """Index test_posture signals by their project key (summary prefix before ':')."""
    out: dict[str, ContextSignal] = {}
    for s in signals:
        key = s.summary.split(":", 1)[0]
        assert key not in out, f"duplicate project signal for {key!r}"
        out[key] = s
    return out


def _projection(signals: list[ContextSignal]) -> list[tuple]:
    """A hashable, comparison-friendly view of the full public signal contract."""
    return [
        (s.source, s.kind, s.summary, s.detail, s.path, s.weight, s.timestamp)
        for s in signals
    ]


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    from proactive_loop.cli import main

    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ===========================================================================
# Behavior 1 -- Untested project detected.
# ===========================================================================


def test_b01_untested_project_detected(tmp_path: Path) -> None:
    _write(tmp_path / "api" / "server.py")

    signals = PostureCollector().collect(tmp_path)

    assert len(signals) == 1, f"expected exactly one signal, got {signals!r}"
    s = signals[0]
    assert s.source == "test_posture"
    assert s.kind == "test_posture"
    assert s.summary == "api: 1 src, 0 test files (untested)"
    # Signal-contract details documented in the acceptance criteria / SPEC:
    assert s.detail == ""
    assert s.timestamp is None


# ===========================================================================
# Behavior 2 -- Tested project not flagged untested.
# ===========================================================================


def test_b02_tested_project_not_flagged_untested(tmp_path: Path) -> None:
    _write(tmp_path / "svc" / "app.py")
    _write(tmp_path / "svc" / "test_app.py")

    by = _by_project(PostureCollector().collect(tmp_path))

    assert "svc" in by
    assert by["svc"].summary == "svc: 1 src, 1 test files"
    assert "(untested)" not in by["svc"].summary


# ===========================================================================
# Behavior 3 -- Untested weight outranks tested weight; both in [0, 1].
# ===========================================================================


def test_b03_untested_weight_outranks_tested(tmp_path: Path) -> None:
    _write(tmp_path / "api" / "server.py")          # untested project
    _write(tmp_path / "svc" / "app.py")             # tested project
    _write(tmp_path / "svc" / "test_app.py")

    by = _by_project(PostureCollector().collect(tmp_path))

    assert by["api"].weight == 0.7
    assert by["svc"].weight == 0.4
    assert by["api"].weight > by["svc"].weight
    for s in by.values():
        assert 0.0 <= s.weight <= 1.0


# ===========================================================================
# Behavior 4 -- All four test-file NAME forms are recognized.
# ===========================================================================


def test_b04_all_four_test_name_forms_recognized(tmp_path: Path) -> None:
    _write(tmp_path / "p_prefix" / "main.py")
    _write(tmp_path / "p_prefix" / "test_main.py")      # (a) test_ prefix
    _write(tmp_path / "p_suffix" / "main.go")
    _write(tmp_path / "p_suffix" / "main_test.go")      # (b) _test stem suffix
    _write(tmp_path / "p_dot_test" / "main.js")
    _write(tmp_path / "p_dot_test" / "widget.test.js")  # (c) .test. infix
    _write(tmp_path / "p_dot_spec" / "main.ts")
    _write(tmp_path / "p_dot_spec" / "widget.spec.ts")  # (d) .spec. infix

    by = _by_project(PostureCollector().collect(tmp_path))

    for proj in ("p_prefix", "p_suffix", "p_dot_test", "p_dot_spec"):
        assert proj in by, f"missing signal for project {proj!r}"
        assert by[proj].summary == f"{proj}: 1 src, 1 test files"
        assert "(untested)" not in by[proj].summary


# ===========================================================================
# Behavior 5 -- A file under a test directory counts as a test.
# (tests / test / __tests__ are treated identically.)
# ===========================================================================


@pytest.mark.parametrize("dirname", ["tests", "test", "__tests__"])
def test_b05_file_under_test_dir_counts_as_test(tmp_path: Path, dirname: str) -> None:
    _write(tmp_path / "pkg" / "mod.py")                      # source
    _write(tmp_path / "pkg" / dirname / "helpers.py")        # plainly named, but under a test dir

    by = _by_project(PostureCollector().collect(tmp_path))

    assert by["pkg"].summary == "pkg: 1 src, 1 test files"


# ===========================================================================
# Behavior 6 -- Non-code files are ignored.
# ===========================================================================


def test_b06_non_code_files_ignored(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "README.md", "# hi\n")
    _write(tmp_path / "docs" / "config.json", "{}\n")
    _write(tmp_path / "docs" / "notes.txt", "notes\n")

    assert PostureCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 7 -- Skipped and hidden directories are excluded.
# ===========================================================================


def test_b07_skipped_and_hidden_dirs_excluded(tmp_path: Path) -> None:
    _write(tmp_path / "node_modules" / "pkg" / "index.js")
    _write(tmp_path / ".hidden" / "secret.py")

    assert PostureCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 8 -- Missing or non-directory root degrades to [], never raises.
# ===========================================================================


def test_b08_missing_root_degrades_to_empty(tmp_path: Path) -> None:
    assert PostureCollector().collect(tmp_path / "does_not_exist") == []


def test_b08_file_root_degrades_to_empty(tmp_path: Path) -> None:
    a_file = _write(tmp_path / "afile.py")
    assert PostureCollector().collect(a_file) == []


# ===========================================================================
# Behavior 9 -- Deterministic, repeatable, project-key-sorted ordering.
# ===========================================================================


def test_b09_sorted_and_repeatable(tmp_path: Path) -> None:
    _write(tmp_path / "zeta" / "z.py")
    _write(tmp_path / "alpha" / "a.py")
    _write(tmp_path / "mid" / "m.py")

    first = PostureCollector().collect(tmp_path)
    prefixes = [s.summary.split(":", 1)[0] for s in first]
    assert prefixes == ["alpha", "mid", "zeta"]

    second = PostureCollector().collect(tmp_path)
    assert _projection(first) == _projection(second)


# ===========================================================================
# Behavior 10 -- Root-level source files are attributed to project ".".
# ===========================================================================


def test_b10_root_level_source_attributed_to_dot(tmp_path: Path) -> None:
    _write(tmp_path / "main.py")

    signals = PostureCollector().collect(tmp_path)

    assert len(signals) == 1
    s = signals[0]
    assert s.summary == ".: 1 src, 0 test files (untested)"
    assert s.path == str(tmp_path)


# ===========================================================================
# Behavior 11 -- Registered in the collector registry without disturbing it.
# ===========================================================================


def test_b11_registered_in_registry_without_disturbing_it() -> None:
    collectors = all_collectors()

    posture = [c for c in collectors if type(c) is PostureCollector]
    assert len(posture) == 1, "exactly one TestPostureCollector instance expected"

    fresh = PostureCollector()
    assert fresh.name == "test_posture"

    # The alias and the direct-submodule import must be the same class object.
    assert PostureCollector is PostureCollector_direct

    # Every collector (the new one included) still satisfies the Collector duck-type.
    for c in collectors:
        assert isinstance(c.name, str) and c.name
        assert callable(getattr(c, "collect", None))

    # The new collector conforms to the Collector protocol seam.
    assert hasattr(fresh, "name") and callable(getattr(fresh, "collect", None))


# ===========================================================================
# Behavior 12 -- path points at the project directory (absolute), never None.
# ===========================================================================


def test_b12_path_points_at_project_dir(tmp_path: Path) -> None:
    _write(tmp_path / "k" / "s.py")       # child project
    _write(tmp_path / "root_src.py")      # root-level project "."

    by = _by_project(PostureCollector().collect(tmp_path))

    assert by["k"].path == str(tmp_path / "k")
    assert by["."].path == str(tmp_path)
    for s in by.values():
        assert s.path is not None


# ===========================================================================
# Behavior 13 -- The new kind flows end-to-end through `pla signals` (integration).
# ===========================================================================


def test_b13_signals_cli_surfaces_test_posture_kind(tmp_path: Path, capsys) -> None:
    # A synthetic workspace with ONE untested project. It has no `.git`, so no
    # git-based kinds leak; the only non-test_posture kind present is the
    # recent-file signal for server.py -- which the `--kind` filter must drop.
    _write(tmp_path / "api" / "server.py")

    # `--provider scripted` WITHOUT a `--scripted-responses` file: if `signals`
    # built an LLMClient it would fault here; exit 0 is the black-box proof that
    # the inspector is LLM-free.
    rc, out, err = _run(
        [
            "signals",
            "--workspace", str(tmp_path),
            "--provider", "scripted",
            "--kind", "test_posture",
            "--json",
        ],
        capsys,
    )

    assert rc == 0, f"signals must exit 0; stderr={err!r}"

    doc = json.loads(out)  # entire stdout parses as one clean JSON object
    assert isinstance(doc, dict)
    assert "signals" in doc
    sigs = doc["signals"]
    assert isinstance(sigs, list)

    kinds = {s["kind"] for s in sigs}
    # at least one test_posture entry AND no entry of any other kind
    assert kinds == {"test_posture"}, f"filter must isolate test_posture; got {kinds!r}"
    assert any(s["kind"] == "test_posture" for s in sigs)
