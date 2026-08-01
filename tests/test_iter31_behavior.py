"""Black-box behavior tests for iteration 31.

Feature under test: the SPEC §4.1 "collectors never raise -> ``[]``" invariant is
made REGISTRY-DRIVEN. Instead of proving the never-raise contract for only the 4
original collectors, this iteration proves it for ALL collectors returned by the
public ``all_collectors()`` registry -- so every collector shipped since (and every
future one) is auto-covered. This suite drives that proof from the documented public
API so a refactor that made any registered collector throw on a hostile root would
turn these tests RED instead of sailing through green.

ISOLATION STATEMENT: these tests were written strictly against the PUBLIC contract --
the iteration spec's Expected Behaviors (``pm.md``), ``README.md``, and ``SPEC.md``
§4.1 -- and exercise ONLY the documented public surface: ``all_collectors()`` and the
collector classes exported from the ``proactive_loop.collectors`` package (SPEC §4.1
"``__init__.py: def all_collectors()``" and the per-collector class list). No file
under ``src/`` was read, no engineer/reviewer notes were consulted, and no ``git diff``
was inspected. This suite deliberately builds its OWN hostile-tree fixture (it does not
import any helper from ``tests/test_collectors.py``) so it is an independent encoding of
the spec, not a mirror of the implementation's tests. Everything runs fully offline:
NO network, NO git repo, NO LLM/provider, NO API keys -- ``tmp_path`` fixtures only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.collectors import all_collectors


# ---------------------------------------------------------------------------
# Registry-driven parametrization
# ---------------------------------------------------------------------------
#
# EB2-EB5 must iterate the ENTIRE all_collectors() list dynamically (never a
# hardcoded subset) so they auto-cover every present and future collector. The
# param id is the collector .name, so a failure names the offending collector
# (e.g. "...[merge_conflict]") instead of an opaque index.
_ALL_COLLECTORS = all_collectors()
_COLLECTOR_PARAMS = [pytest.param(c, id=c.name) for c in _ALL_COLLECTORS]

# The 13 collectors documented in SPEC §4.1 (the public contract). Asserting the
# full name-SET -- not a subset, not a bare count -- catches BOTH a collector
# silently dropped from the registry AND a documented collector missing from it.
_DOCUMENTED_COLLECTOR_NAMES = frozenset(
    {
        "ci_config",
        "recent_files",
        "git_activity",
        "git_state",
        "todos",
        "notes",
        "dependencies",
        "working_tree",
        "test_posture",
        "merge_conflict",
        "large_file",
        "secret_file",
        "git_stash",
    }
)


def _build_hostile_tree(root: Path) -> None:
    """Populate *root* with the EB5 mixed undecodable-content stressor tree.

    Independently constructed from the six ingredients the spec enumerates -- this
    is the realistic 'never-raise' stressor the empty/nonexistent cases never touch,
    forcing every decode/parse path (UTF-8 text, tomllib, json, conflict-marker
    scan) to face bytes it cannot handle.
    """
    # A deeply-nested empty subdirectory chain.
    (root / "a" / "b" / "c" / "d").mkdir(parents=True)
    # A zero-byte file with a scanned extension.
    (root / "empty.md").write_bytes(b"")
    # A scanned SOURCE-extension file whose bytes are NOT valid UTF-8.
    (root / "junk.py").write_bytes(b"\xff\xfe\x00\x01 TODO garbage \x80\x81")
    # An invalid, non-UTF-8 pyproject.toml -- stresses DependencyCollector's TOML parse.
    (root / "pyproject.toml").write_bytes(b"\xff\xfe not toml \x00")
    # An invalid package.json with garbage bytes -- stresses the JSON parse.
    (root / "package.json").write_bytes(b"\x00\x01\x02 no")
    # A committed conflict-marker file -- stresses MergeConflictCollector. The label
    # lines start with the 7-chevron + space OPEN/CLOSE prefixes at column 0.
    (root / "conflict.py").write_text(
        "x = 1\n<<<<<<< HEAD\na = 1\n=======\nb = 2\n>>>>>>> feature\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# EB1 - Registry completeness (replaces the stale 4-type check)
# ---------------------------------------------------------------------------


class TestRegistryCompleteness:
    """EB1: all_collectors() exposes EXACTLY the 13 documented collectors, each a
    unique, non-empty-named instance that satisfies the Collector protocol."""

    def test_name_set_is_exactly_the_thirteen_documented(self) -> None:
        """The set of .name values equals the 13 SPEC §4.1 names -- no more, no less.

        A full-SET check (not a subset, not a count) catches a collector dropped
        from the registry AND a documented collector missing from it.
        """
        names = {c.name for c in all_collectors()}
        assert names == set(_DOCUMENTED_COLLECTOR_NAMES)

    def test_returns_a_nonempty_list(self) -> None:
        collectors = all_collectors()
        assert isinstance(collectors, list)
        assert len(collectors) == len(_DOCUMENTED_COLLECTOR_NAMES)

    def test_names_are_unique_nonempty_strings(self) -> None:
        collectors = all_collectors()
        names = [c.name for c in collectors]
        for name in names:
            assert isinstance(name, str)
            assert name  # non-empty
        # Uniqueness: catches a collector swapped for a duplicate of another
        # (which a bare count check would miss).
        assert len(names) == len(set(names))

    def test_every_instance_is_a_distinct_class(self) -> None:
        """No two registered collectors share a class (a duplicate-swap guard that
        needs no src import)."""
        collectors = all_collectors()
        assert len({type(c) for c in collectors}) == len(collectors)

    @pytest.mark.parametrize("collector", _COLLECTOR_PARAMS)
    def test_satisfies_collector_protocol(self, collector: object) -> None:
        """Each instance has a str .name attribute and a callable .collect."""
        assert hasattr(collector, "name")
        assert isinstance(getattr(collector, "name"), str)
        assert callable(getattr(collector, "collect", None))


# ---------------------------------------------------------------------------
# EB2 - Never-raise on a NONEXISTENT root
# ---------------------------------------------------------------------------


class TestNonexistentRoot:
    @pytest.mark.parametrize("collector", _COLLECTOR_PARAMS)
    def test_returns_exactly_empty_list(
        self, collector, tmp_path: Path
    ) -> None:
        """EB2: a path under tmp_path that does not exist degrades to exactly []."""
        missing = tmp_path / "does_not_exist_at_all"
        assert not missing.exists()
        result = collector.collect(missing)
        assert result == []


# ---------------------------------------------------------------------------
# EB3 - Never-raise on a FILE passed as root
# ---------------------------------------------------------------------------


class TestFileAsRoot:
    @pytest.mark.parametrize("collector", _COLLECTOR_PARAMS)
    def test_returns_a_list(self, collector, tmp_path: Path) -> None:
        """EB3: a regular file where a directory is expected returns a list.

        The contract is 'a list, no exception'; the exact contents are unconstrained.
        """
        f = tmp_path / "not_a_dir.txt"
        f.write_text("just a file, not a directory", encoding="utf-8")
        assert f.is_file()
        result = collector.collect(f)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# EB4 - Never-raise on an EMPTY directory
# ---------------------------------------------------------------------------


class TestEmptyRoot:
    @pytest.mark.parametrize("collector", _COLLECTOR_PARAMS)
    def test_returns_a_list(self, collector, tmp_path: Path) -> None:
        """EB4: a freshly-created empty directory returns a list (must not raise)."""
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        assert empty.is_dir()
        assert not any(empty.iterdir())
        result = collector.collect(empty)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# EB5 - Never-raise on a HOSTILE, undecodable-content tree
# ---------------------------------------------------------------------------


class TestHostileTree:
    @pytest.mark.parametrize("collector", _COLLECTOR_PARAMS)
    def test_returns_a_list(self, collector, tmp_path: Path) -> None:
        """EB5: a mixed tree of undecodable/unparseable content returns a list.

        Exercises the content-scanning and manifest-parsing collectors on non-UTF-8
        bytes, invalid TOML/JSON, a zero-byte file, and committed conflict markers --
        the paths where a naive collector would raise instead of degrading.
        """
        _build_hostile_tree(tmp_path)
        result = collector.collect(tmp_path)
        assert isinstance(result, list)

    def test_hostile_tree_fixture_has_all_six_ingredients(
        self, tmp_path: Path
    ) -> None:
        """Guard the fixture itself so EB5 can never silently under-stress: assert the
        six required ingredients actually landed on disk before collectors run."""
        _build_hostile_tree(tmp_path)
        assert (tmp_path / "a" / "b" / "c" / "d").is_dir()
        assert (tmp_path / "empty.md").is_file()
        assert (tmp_path / "empty.md").stat().st_size == 0
        assert (tmp_path / "junk.py").read_bytes()[:2] == b"\xff\xfe"
        assert (tmp_path / "pyproject.toml").read_bytes()[:2] == b"\xff\xfe"
        assert b"\x00" in (tmp_path / "package.json").read_bytes()
        conflict = (tmp_path / "conflict.py").read_text(encoding="utf-8")
        assert any(line.startswith("<<<<<<< ") for line in conflict.splitlines())
        assert any(line.startswith(">>>>>>> ") for line in conflict.splitlines())
