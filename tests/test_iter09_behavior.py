"""Black-box behavior tests for iteration 09.

Feature under test: a new **L2 perception signal**, the ``DependencyCollector``.
It walks a workspace and emits one ``ContextSignal`` (``kind == "dependency"``)
per project manifest it recognizes -- ``pyproject.toml`` / ``requirements.txt``
(Python) and ``package.json`` (Node) -- reporting the ecosystem, the manifest's
relative path, and the declared-dependency count so the scout can perceive the
user's stack. It is stdlib-only, offline, deterministic, and (like every
collector) degrades to ``[]`` rather than raising on any I/O or parse error.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors", ``README.md``,
and ``SPEC.md`` (the ``collectors`` module contract in section 4.1) -- and drive
only the documented public surface: the public collector API
``DependencyCollector().collect(root)``, the ``proactive_loop.collectors``
package imports (``DependencyCollector``, ``all_collectors``), the
``Collector`` protocol from ``proactive_loop.collectors.base``, and the
``ContextSignal`` domain model from ``proactive_loop.models``. No file under
``src/`` was read, no engineer/reviewer notes were read, and no ``git diff`` was
consulted. Field names (``source``/``kind``/``summary``/``path``/``weight``/
``detail``) were confirmed only from the public model schema and the existing
published tests (``tests/test_collectors.py``), never from the implementation.
Every test builds its workspace under a fresh ``tmp_path`` and runs fully
offline -- zero network, zero git, zero API keys.
"""

from __future__ import annotations

import re
from pathlib import Path

from proactive_loop.collectors import DependencyCollector, all_collectors
from proactive_loop.collectors.base import Collector
from proactive_loop.models import ContextSignal

REPO = Path(__file__).resolve().parents[1]
# Runner-location-independent path to the offline demo fixture.
FIXTURE = REPO / "examples" / "fixture_workspace"

# Parses the relative manifest path out of a "<Eco>: <relpath> (<n> deps)" summary.
_SUMMARY = re.compile(r"^(?:Python|Node): (?P<rel>.+) \((?P<count>\d+) deps\)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> Path:
    """Create *path* (and parents) with *content* (utf-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _dep_signals(root: Path) -> list[ContextSignal]:
    """Collect and assert every returned signal is a dependency signal."""
    signals = DependencyCollector().collect(root)
    assert isinstance(signals, list)
    for s in signals:
        assert isinstance(s, ContextSignal)
        assert s.kind == "dependency"
        assert s.source == "dependencies"
    return signals


_PYPROJECT_3 = '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["a", "b", "c"]\n'
_PACKAGE_3 = (
    '{"dependencies": {"react": "^18.0.0", "lodash": "^4.17.0"}, '
    '"devDependencies": {"jest": "^29.0.0"}}'
)
_PACKAGE_EMPTY = '{"dependencies": {}, "devDependencies": {}}'


# ---------------------------------------------------------------------------
# Behavior 1 -- Python pyproject.toml detected
# ---------------------------------------------------------------------------


def test_b1_pyproject_toml_detected(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _PYPROJECT_3)
    signals = _dep_signals(tmp_path)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.source == "dependencies"
    assert sig.kind == "dependency"
    assert sig.summary == "Python: pyproject.toml (3 deps)"


# ---------------------------------------------------------------------------
# Behavior 2 -- Node package.json with combined dep count
# ---------------------------------------------------------------------------


def test_b2_package_json_combined_dep_count(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", _PACKAGE_3)
    signals = _dep_signals(tmp_path)
    assert len(signals) == 1
    assert signals[0].kind == "dependency"
    assert signals[0].summary == "Node: package.json (3 deps)"


# ---------------------------------------------------------------------------
# Behavior 3 -- requirements.txt, ignoring comments / blanks / option lines
# ---------------------------------------------------------------------------


def test_b3_requirements_txt_counts_only_dep_lines(tmp_path: Path) -> None:
    content = "\n".join(
        [
            "# a comment",
            "",
            "flask",
            "requests>=2.0",
            "-e .",
            "django  # web framework",
        ]
    )
    _write(tmp_path / "requirements.txt", content)
    signals = _dep_signals(tmp_path)
    assert len(signals) == 1
    # Only flask, requests, django are dependency lines -> 3.
    assert signals[0].summary == "Python: requirements.txt (3 deps)"


# ---------------------------------------------------------------------------
# Behavior 4 -- multiple manifests each emit their own signal
# ---------------------------------------------------------------------------


def test_b4_multiple_manifests_each_emit(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _PYPROJECT_3)
    _write(tmp_path / "package.json", _PACKAGE_3)
    signals = _dep_signals(tmp_path)
    assert len(signals) == 2
    prefixes = sorted(s.summary.split(":", 1)[0] + ":" for s in signals)
    assert prefixes == ["Node:", "Python:"]
    assert any(s.summary.startswith("Python: ") for s in signals)
    assert any(s.summary.startswith("Node: ") for s in signals)


# ---------------------------------------------------------------------------
# Behavior 5 -- nested manifest uses its relative path (forward slashes)
# ---------------------------------------------------------------------------


def test_b5_nested_manifest_relative_forward_slash_path(tmp_path: Path) -> None:
    _write(tmp_path / "frontend" / "package.json", _PACKAGE_EMPTY)
    signals = _dep_signals(tmp_path)
    assert len(signals) == 1
    assert signals[0].summary == "Node: frontend/package.json (0 deps)"
    # Forward slash on every platform (never a backslash).
    assert "\\" not in signals[0].summary


# ---------------------------------------------------------------------------
# Behavior 6 -- no manifests -> empty
# ---------------------------------------------------------------------------


def test_b6_no_manifests_returns_empty(tmp_path: Path) -> None:
    _write(tmp_path / "module.py", "x = 1\n")
    _write(tmp_path / "docs" / "guide.md", "# Guide\n")
    assert DependencyCollector().collect(tmp_path) == []


# ---------------------------------------------------------------------------
# Behavior 7 -- malformed manifest is skipped, never raises, siblings emit
# ---------------------------------------------------------------------------


def test_b7_malformed_toml_skipped_sibling_emits(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", "= = = not toml")
    _write(tmp_path / "package.json", _PACKAGE_3)
    signals = _dep_signals(tmp_path)  # must not raise
    assert len(signals) == 1
    assert signals[0].summary == "Node: package.json (3 deps)"


def test_b7_malformed_json_skipped_sibling_emits(tmp_path: Path) -> None:
    """Symmetric case: broken package.json JSON, valid pyproject.toml survives."""
    _write(tmp_path / "package.json", "{not valid json")
    _write(tmp_path / "pyproject.toml", _PYPROJECT_3)
    signals = _dep_signals(tmp_path)  # must not raise
    assert len(signals) == 1
    assert signals[0].summary == "Python: pyproject.toml (3 deps)"


# ---------------------------------------------------------------------------
# Behavior 8 -- missing / nonexistent root degrades to empty
# ---------------------------------------------------------------------------


def test_b8_nonexistent_root_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "no" / "such" / "dir_xyz"
    assert DependencyCollector().collect(missing) == []
    # And the exact literal from the spec.
    assert DependencyCollector().collect(Path("/no/such/dir_xyz")) == []


# ---------------------------------------------------------------------------
# Behavior 9 -- noise / hidden directories are skipped
# ---------------------------------------------------------------------------


def test_b9_skips_noise_and_hidden_dirs(tmp_path: Path) -> None:
    for noise in ("node_modules", ".venv", "__pycache__", ".git", ".tox", "dist", "build"):
        _write(tmp_path / noise / "package.json", _PACKAGE_3)
    _write(tmp_path / ".hidden_dir" / "package.json", _PACKAGE_3)
    # No visible manifests anywhere -> nothing should be reported.
    assert DependencyCollector().collect(tmp_path) == []


def test_b9_visible_manifest_still_found_amid_noise(tmp_path: Path) -> None:
    """A real manifest alongside skipped dirs is still reported (skip is scoped)."""
    _write(tmp_path / "node_modules" / "package.json", _PACKAGE_3)
    _write(tmp_path / "package.json", _PACKAGE_3)  # visible, at root
    signals = _dep_signals(tmp_path)
    assert len(signals) == 1
    assert signals[0].summary == "Node: package.json (3 deps)"


# ---------------------------------------------------------------------------
# Behavior 10 -- deterministic ordering (sorted by relative manifest path)
# ---------------------------------------------------------------------------


def test_b10_deterministic_ordering(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _PYPROJECT_3)
    _write(tmp_path / "b" / "package.json", _PACKAGE_EMPTY)
    _write(tmp_path / "a" / "requirements.txt", "flask\nrequests\n")
    _write(tmp_path / "frontend" / "package.json", _PACKAGE_EMPTY)

    first = DependencyCollector().collect(tmp_path)
    second = DependencyCollector().collect(tmp_path)

    first_summaries = [s.summary for s in first]
    second_summaries = [s.summary for s in second]
    # Two successive calls return signals in the same order.
    assert first_summaries == second_summaries
    assert len(first_summaries) == 4

    # And that order is sorted by the manifest's relative path.
    rels = []
    for summary in first_summaries:
        m = _SUMMARY.match(summary)
        assert m is not None, f"unexpected summary format: {summary!r}"
        rels.append(m.group("rel"))
    assert rels == sorted(rels), f"signals not sorted by relative path: {rels}"


# ---------------------------------------------------------------------------
# Behavior 11 -- registered in the collector set
# ---------------------------------------------------------------------------


def test_b11_registered_in_all_collectors(tmp_path: Path) -> None:
    collectors = all_collectors()
    matching = [c for c in collectors if getattr(c, "name", None) == "dependencies"]
    assert len(matching) == 1
    assert isinstance(matching[0], DependencyCollector)


def test_b11_importable_from_package() -> None:
    # The import at the top of this module already proves importability;
    # assert the symbol is the class and is instantiable.
    assert isinstance(DependencyCollector(), DependencyCollector)


# ---------------------------------------------------------------------------
# Behavior 12 -- weight invariant
# ---------------------------------------------------------------------------


def test_b12_weight_invariant(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _PYPROJECT_3)
    _write(tmp_path / "package.json", _PACKAGE_3)
    _write(tmp_path / "requirements.txt", "flask\n")
    signals = _dep_signals(tmp_path)
    assert len(signals) == 3
    for s in signals:
        assert 0.0 < s.weight <= 1.0


# ---------------------------------------------------------------------------
# Behavior 13 -- fixture workspace emits nothing (demo regression guard)
# ---------------------------------------------------------------------------


def test_b13_fixture_workspace_emits_nothing() -> None:
    assert FIXTURE.is_dir(), f"fixture workspace missing at {FIXTURE}"
    assert DependencyCollector().collect(FIXTURE) == []


# ---------------------------------------------------------------------------
# Behavior 14 -- Collector protocol + never-raise contract
# ---------------------------------------------------------------------------


def test_b14_conforms_to_collector_protocol() -> None:
    assert isinstance(DependencyCollector(), Collector)


def test_b14_never_raises_on_bad_inputs(tmp_path: Path) -> None:
    # A directory named like a manifest must not crash the walk / parse.
    (tmp_path / "package.json").mkdir()
    _write(tmp_path / "requirements.txt", "flask\n")
    signals = _dep_signals(tmp_path)  # must not raise
    # The real requirements.txt is still reported; the bogus dir contributes none.
    assert any(s.summary == "Python: requirements.txt (1 deps)" for s in signals)
    assert all(not s.summary.startswith("Node:") for s in signals)


# ---------------------------------------------------------------------------
# Signal-shape sanity: detail is a str, path is populated (SPEC notes)
# ---------------------------------------------------------------------------


def test_signal_detail_is_str_and_path_populated(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _PYPROJECT_3)
    sig = _dep_signals(tmp_path)[0]
    assert isinstance(sig.detail, str)
    # path field is populated (spec note: store the manifest's absolute path).
    assert sig.path
    assert "pyproject.toml" in str(sig.path)
