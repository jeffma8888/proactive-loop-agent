"""Behavior tests for iteration 141: ONE shared ``_relative(root, path)`` helper.

Iteration 141 hoists the single ``_relative(root, path)`` implementation onto the
shared ``BaseCollector`` and deletes the six verbatim per-collector copies
(``dependencies``, ``large_file``, ``lockfile_drift``, ``secret_file``,
``merge_conflict``, ``syntax_error``), then guards the duplication so a seventh
copy cannot grow back. It is a pure subtraction: no collector's observable output
may change.

Coverage (numbered to match the iteration spec's Expected Behaviors):

1. ``BaseCollector._relative`` exists as a ``staticmethod`` taking exactly two
   positional parameters and returning ``str``.
2. Inside-root inputs come back workspace-relative in POSIX form: forward slashes
   only, no leading ``./``, never a backslash.
3. The ``ValueError`` branch is total: an absolute path OUTSIDE root comes back as
   ``path.as_posix()`` and never raises. That is the reachable production case,
   because callers pass absolute walk results.
4. The helper is INHERITED, not merely present: all six collector classes resolve
   it to the base implementation and agree with it byte-for-byte, accessed both on
   the class and on an instance.
5. Regrowth guard: an AST walk (never a regex) over the whole ``collectors``
   package finds exactly ONE ``def _relative``, in ``base.py``. The guard is
   two-sided -- proven to FIRE on a planted seventh copy and to stay silent on a
   planted module that only MENTIONS the name in a string/comment -- and
   non-vacuous: it fails if no modules were scanned or if ``base.py`` was missed.
6. Observable output is UNCHANGED for all six collectors, pinned as a golden set
   against a real fixture tree. **The spec's Behavior 6 as written is FALSE about
   this codebase and is deliberately NOT asserted** -- see the long note on
   ``TestObservableOutputIsUnchanged`` below. Four of the six collectors publish an
   ABSOLUTE ``ContextSignal.path`` and use the helper's output only inside
   ``summary``; only ``merge_conflict`` and ``syntax_error`` put a relative string
   in ``path``. That split predates this iteration (verified against HEAD), so this
   module pins the ACTUAL per-collector channel and shape instead, which is the
   contract the refactor had to preserve.
7. The hoist injected no dataclass field: exact field names, in order, per
   collector, and no-argument construction still works.
8. Structural typing and the fail-open contract survive: every collector still
   satisfies the ``Collector`` protocol and still returns ``list[ContextSignal]``
   without raising on a nonexistent root.

Offline, deterministic, ``tmp_path`` only -- no subprocess, no network.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import os
from pathlib import Path

import pytest

from proactive_loop import collectors as collectors_pkg
from proactive_loop.collectors.base import BaseCollector, Collector
from proactive_loop.collectors.dependencies import DependencyCollector
from proactive_loop.collectors.large_file import LargeFileCollector
from proactive_loop.collectors.lockfile_drift import LockfileDriftCollector
from proactive_loop.collectors.merge_conflict import MergeConflictCollector
from proactive_loop.collectors.secret_file import SecretFileCollector
from proactive_loop.collectors.syntax_error import SyntaxErrorCollector
from proactive_loop.models import ContextSignal

_HELPER = "_relative"

# The six collectors whose duplicated copy this iteration deletes. Constructed
# with the cheapest trigger that makes each one report a NESTED file (see
# ``_build_fixture``); ``LargeFileCollector`` needs ``min_bytes=1`` so a few-byte
# fixture file qualifies without writing megabytes.
_SUBJECTS: dict[str, type] = {
    "dependency": DependencyCollector,
    "large_file": LargeFileCollector,
    "lockfile_drift": LockfileDriftCollector,
    "secret_file": SecretFileCollector,
    "merge_conflict": MergeConflictCollector,
    "syntax_error": SyntaxErrorCollector,
}
_SUBJECT_PARAMS = [pytest.param(cls, id=key) for key, cls in _SUBJECTS.items()]


def _instance(cls: type) -> object:
    """Construct a subject with the tunable that makes the fixture trip it."""
    if cls is LargeFileCollector:
        return cls(min_bytes=1)  # type: ignore[call-arg]
    return cls()


# ---------------------------------------------------------------------------
# Fixture tree -- one nested file per collector, all tiny
# ---------------------------------------------------------------------------


def _build_fixture(root: Path) -> None:
    nested = root / "pkg" / "sub"
    nested.mkdir(parents=True)
    (nested / "broken.py").write_text("def f(:\n", encoding="utf-8")
    (nested / "conflict.txt").write_text(
        "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> other\n", encoding="utf-8"
    )
    (nested / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
    (nested / "requirements.txt").write_text("pydantic>=2\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "uv.lock").write_text("# lock\n", encoding="utf-8")
    # Explicit mtimes: lockfile drift must not depend on write ORDER.
    os.utime(root / "uv.lock", (1_000_000, 1_000_000))
    os.utime(root / "pyproject.toml", (2_000_000, 2_000_000))


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    _build_fixture(root)
    return root


# ---------------------------------------------------------------------------
# Behavior 1: the helper exists on the shared base with the specified shape
# ---------------------------------------------------------------------------


class TestHelperExistsOnTheSharedBase:
    def test_base_owns_the_helper(self) -> None:
        own = vars(BaseCollector)
        assert _HELPER in own, (
            f"BaseCollector must own the single {_HELPER!r} implementation; it "
            f"declares {sorted(k for k in own if not k.startswith('__'))}"
        )

    def test_helper_is_a_staticmethod(self) -> None:
        assert isinstance(vars(BaseCollector)[_HELPER], staticmethod), (
            "the helper must stay a @staticmethod -- a plain method would change "
            "the 8 existing self._relative(root, ...) call sites' arity"
        )

    def test_helper_takes_exactly_two_positional_parameters(self) -> None:
        params = list(inspect.signature(BaseCollector._relative).parameters.values())
        assert [p.name for p in params] == ["root", "path"], (
            "spec pins the two positional parameter names (root, path); got "
            f"{[p.name for p in params]}"
        )
        for param in params:
            assert param.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ), f"{param.name} is {param.kind}, so self._relative(root, x) breaks"
            assert param.default is inspect.Parameter.empty

    def test_helper_returns_a_string(self, tmp_path: Path) -> None:
        assert isinstance(BaseCollector._relative(tmp_path, tmp_path / "a.py"), str)

    def test_helper_docstring_cites_no_single_spec_behavior_number(self) -> None:
        """Acceptance criterion: the six copies cited FOUR different SPEC numbers
        (5, 4, 12, 6), so the one surviving docstring must name the invariant
        generically rather than pick a winner."""
        doc = inspect.getdoc(BaseCollector._relative) or ""
        assert doc.strip(), "the single surviving implementation needs a docstring"
        offenders = [
            token
            for token in ("SPEC behavior 4", "SPEC behavior 5", "SPEC behavior 6", "SPEC behavior 12")
            if token.lower() in doc.lower()
        ]
        assert offenders == [], (
            "the hoisted docstring must not privilege one collector's SPEC "
            f"citation; found {offenders}"
        )


# ---------------------------------------------------------------------------
# Behavior 2: inside-root inputs come back POSIX-relative
# ---------------------------------------------------------------------------


class TestInsideRootIsRelativePosix:
    def test_nested_path_is_relative_posix(self, tmp_path: Path) -> None:
        root = tmp_path / "ws"
        result = BaseCollector._relative(root, root / "a" / "b" / "c.py")
        assert result == "a/b/c.py"

    def test_result_has_no_backslash_and_no_leading_dot_slash(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "ws"
        result = BaseCollector._relative(root, root / "a" / "b" / "c.py")
        assert "\\" not in result, f"backslash leaked into {result!r}"
        assert not result.startswith("./")
        assert not result.startswith("/")

    def test_direct_child_is_a_bare_name(self, tmp_path: Path) -> None:
        root = tmp_path / "ws"
        assert BaseCollector._relative(root, root / "pyproject.toml") == "pyproject.toml"

    def test_root_itself_is_the_posix_dot(self, tmp_path: Path) -> None:
        """``Path.relative_to`` yields ``.`` for the root itself; pin whatever the
        one implementation does so a future rewrite cannot change it silently."""
        root = tmp_path / "ws"
        assert BaseCollector._relative(root, root) == "."


# ---------------------------------------------------------------------------
# Behavior 3: the ValueError branch is total
# ---------------------------------------------------------------------------


class TestOutsideRootFallsBackWithoutRaising:
    def test_absolute_path_outside_root_returns_its_own_posix_form(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "ws"
        outside = (tmp_path / "elsewhere" / "x.py").resolve()
        result = BaseCollector._relative(root, outside)
        assert result == outside.as_posix()
        assert Path(result).is_absolute()

    def test_sibling_prefix_is_not_treated_as_inside(self, tmp_path: Path) -> None:
        """``ws-2`` shares a string prefix with ``ws`` but is NOT inside it. A
        naive ``str.startswith`` implementation would return a mangled relative
        path here; ``relative_to`` must reject it into the fallback."""
        root = tmp_path / "ws"
        outside = tmp_path / "ws-2" / "x.py"
        assert BaseCollector._relative(root, outside) == outside.as_posix()

    def test_parent_of_root_does_not_raise(self, tmp_path: Path) -> None:
        root = tmp_path / "ws" / "deep"
        assert BaseCollector._relative(root, tmp_path) == tmp_path.as_posix()

    def test_relative_input_outside_root_does_not_raise(self, tmp_path: Path) -> None:
        assert BaseCollector._relative(tmp_path / "ws", Path("other/x.py")) == "other/x.py"


# ---------------------------------------------------------------------------
# Behavior 4: the helper is INHERITED by all six, identical to the base
# ---------------------------------------------------------------------------


class TestAllSixInheritTheSameImplementation:
    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_class_and_instance_agree_with_the_base_inside_root(
        self, cls: type, tmp_path: Path
    ) -> None:
        root = tmp_path / "ws"
        target = root / "a" / "b" / "c.py"
        expected = BaseCollector._relative(root, target)
        assert expected == "a/b/c.py"
        assert cls._relative(root, target) == expected  # type: ignore[attr-defined]
        assert _instance(cls)._relative(root, target) == expected  # type: ignore[attr-defined]

    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_class_and_instance_agree_with_the_base_outside_root(
        self, cls: type, tmp_path: Path
    ) -> None:
        root = tmp_path / "ws"
        outside = (tmp_path / "elsewhere" / "x.py").resolve()
        expected = BaseCollector._relative(root, outside)
        assert expected == outside.as_posix()
        assert cls._relative(root, outside) == expected  # type: ignore[attr-defined]
        assert _instance(cls)._relative(root, outside) == expected  # type: ignore[attr-defined]

    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_subject_subclasses_the_shared_base(self, cls: type) -> None:
        assert issubclass(cls, BaseCollector)

    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_subject_does_not_shadow_the_helper_in_its_own_dict(
        self, cls: type
    ) -> None:
        """The runtime half of the regrowth guard: inheritance, not a copy."""
        assert _HELPER not in vars(cls), (
            f"{cls.__name__} re-declares {_HELPER} in its own class body, so the "
            "hoist did not actually remove the duplication"
        )

    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_resolved_function_object_is_the_one_base_function(
        self, cls: type
    ) -> None:
        assert cls._relative is BaseCollector._relative  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Behavior 5: AST regrowth guard, two-sided and non-vacuous
# ---------------------------------------------------------------------------


def _collector_module_paths() -> list[Path]:
    package_dir = Path(collectors_pkg.__file__).parent
    return sorted(package_dir.glob("*.py"))


def _relative_defs(source: str, label: str) -> list[str]:
    """Return ``label:lineno`` for every ``def _relative`` in ``source``.

    AST-based on purpose: a regex over source text would also match the name in a
    docstring, a comment, or a call site. ``test_guard_ignores_a_mere_mention``
    is the proof that this distinction is real.
    """
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == _HELPER
        ):
            hits.append(f"{label}:{node.lineno}")
    return hits


_PLANTED_COPY = '''
"""Planted module for the two-sided guard proof."""

from pathlib import Path


class PlantedCollector:
    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()
'''

_PLANTED_MENTION_ONLY = '''
"""Planted module that only MENTIONS _relative, never defines it.

A regex for ``_relative`` matches this file three times; the AST guard must
report zero, or every honest call site would be flagged as a duplicate.
"""

from pathlib import Path


class PlantedCaller:
    def _collect(self, root: Path) -> list[str]:
        # delegates to the inherited _relative helper on the shared base
        return [self._relative(root, root / "x.py")]
'''


class TestRegrowthGuard:
    def test_exactly_one_definition_in_the_whole_collectors_package(self) -> None:
        modules = _collector_module_paths()
        # Non-vacuity, half 1: an empty or mis-globbed scan must fail loudly.
        assert len(modules) >= 10, (
            "the guard scanned only "
            f"{[p.name for p in modules]} -- a glob that misses the collector "
            "modules would make this test vacuously green"
        )
        names = {p.name for p in modules}
        # Non-vacuity, half 2: the file that is SUPPOSED to hold the definition
        # must be among the scanned modules.
        assert "base.py" in names, f"base.py missing from scanned modules {sorted(names)}"

        found: list[str] = []
        for path in modules:
            found.extend(
                _relative_defs(path.read_text(encoding="utf-8"), path.name)
            )
        assert len(found) == 1, (
            f"{_HELPER} must be defined exactly once under "
            "src/proactive_loop/collectors/, but found "
            f"{len(found)} definitions at {found}. Scope note: this guard covers "
            "only collectors that name a helper -- notes.py, todos.py, "
            "filesystem.py and test_posture.py build a workspace-relative path "
            "INLINE and are invisible to it (roadmap row #165)."
        )
        assert found[0].startswith("base.py:"), (
            f"the single definition must live in base.py; found it at {found[0]}"
        )

    def test_guard_fires_on_a_planted_seventh_copy(self) -> None:
        hits = _relative_defs(_PLANTED_COPY, "planted_copy.py")
        assert len(hits) == 1, hits
        assert hits[0].startswith("planted_copy.py:")

    def test_guard_ignores_a_mere_mention(self) -> None:
        """Proves the guard is AST-based, not a text search: this module names
        ``_relative`` in a docstring, a comment and a call, and defines none."""
        assert _PLANTED_MENTION_ONLY.count(_HELPER) >= 3
        assert _relative_defs(_PLANTED_MENTION_ONLY, "planted_mention.py") == []

    def test_guard_counts_two_copies_as_two(self) -> None:
        source = _PLANTED_COPY + "\n\n" + _PLANTED_COPY.split('"""', 2)[2]
        hits = _relative_defs(source, "planted_double.py")
        assert len(hits) == 2, hits


# ---------------------------------------------------------------------------
# Behavior 6: observable output is UNCHANGED (golden), spec claim corrected
# ---------------------------------------------------------------------------

# MEASURED per-collector reality, and the reason the spec's Behavior 6 is not
# asserted as written. The spec demanded that EVERY emitted ContextSignal.path be
# relative for all six collectors. Driving the six against the fixture tree shows
# that is false, and equally false at HEAD (same probe, HEAD's src extracted via
# ``git archive``, byte-identical output) -- so it is a wrong claim about the
# PRE-EXISTING design, not a regression this refactor introduced:
#
#   dependency      path=<absolute>   helper output appears in summary
#   large_file      path=<absolute>   helper output appears in summary
#   lockfile_drift  path=<absolute>   helper output appears in summary
#   secret_file     path=<absolute>   helper output appears in summary
#   merge_conflict  path=pkg/sub/conflict.txt   (relative)
#   syntax_error    path=pkg/sub/broken.py      (relative)
#
# Four of six use ``_relative`` ONLY to build the human-readable summary and keep
# an absolute ``path``; ``cli._relative_signal_path`` is what re-roots paths for
# display (iteration 139). So the invariant that actually has to hold after the
# hoist is: the workspace-relative POSIX string each collector publishes is
# unchanged, and each collector's PATH CHANNEL keeps its existing absolute-or-
# relative shape. Both are pinned below.
# Keyed by CLASS, deliberately: the collector's ``name`` attribute and the
# ``ContextSignal.kind`` it emits are NOT the same string (DependencyCollector is
# named "dependencies" but emits kind "dependency"), and keying a golden table by
# the wrong one of those fails as a missing-key error that reads like a product
# bug. ``test_golden_tables_cover_exactly_the_six_subjects`` pins the coverage.
_ABSOLUTE_PATH_COLLECTORS: frozenset[type] = frozenset(
    {
        DependencyCollector,
        LargeFileCollector,
        LockfileDriftCollector,
        SecretFileCollector,
    }
)
_RELATIVE_PATH_COLLECTORS: frozenset[type] = frozenset(
    {MergeConflictCollector, SyntaxErrorCollector}
)

# Golden workspace-relative POSIX strings each collector reports for the fixture.
_GOLDEN_RELATIVE: dict[type, set[str]] = {
    DependencyCollector: {"pkg/sub/requirements.txt", "pyproject.toml"},
    LargeFileCollector: {
        "pkg/sub/broken.py",
        "pkg/sub/conflict.txt",
        "pkg/sub/requirements.txt",
        "pyproject.toml",
        "uv.lock",
    },
    LockfileDriftCollector: {"pyproject.toml"},
    SecretFileCollector: {"pkg/sub/.env.local"},
    MergeConflictCollector: {"pkg/sub/conflict.txt"},
    SyntaxErrorCollector: {"pkg/sub/broken.py"},
}


def _workspace_relative(root: Path, raw: str) -> str:
    """Normalize a signal's ``path`` to a workspace-relative POSIX string."""
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


class TestObservableOutputIsUnchanged:
    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_reported_set_matches_the_golden_relative_paths(
        self, cls: type, workspace: Path
    ) -> None:
        signals = _instance(cls).collect(workspace)  # type: ignore[attr-defined]
        assert signals, f"{cls.__name__} reported nothing, so this test is vacuous"
        reported = {_workspace_relative(workspace, str(s.path)) for s in signals}
        assert reported == _GOLDEN_RELATIVE[cls], (
            f"{cls.__name__} changed which files it reports: expected "
            f"{sorted(_GOLDEN_RELATIVE[cls])}, got {sorted(reported)}"
        )

    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_relative_form_is_posix_and_never_backslashed(
        self, cls: type, workspace: Path
    ) -> None:
        signals = _instance(cls).collect(workspace)  # type: ignore[attr-defined]
        for signal in signals:
            rel = _workspace_relative(workspace, str(signal.path))
            assert "\\" not in rel, f"backslash in {rel!r} from {cls.__name__}"
            assert not rel.startswith("./")

    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_path_channel_keeps_its_existing_shape(
        self, cls: type, workspace: Path
    ) -> None:
        """Pins the absolute-vs-relative split MEASURED above, in both directions,
        so the refactor cannot have silently re-rooted anything."""
        signals = _instance(cls).collect(workspace)  # type: ignore[attr-defined]
        absolute = [str(s.path) for s in signals if Path(str(s.path)).is_absolute()]
        relative = [str(s.path) for s in signals if not Path(str(s.path)).is_absolute()]
        if cls in _ABSOLUTE_PATH_COLLECTORS:
            assert relative == [], (
                f"{cls.__name__} used to emit only absolute paths; these became "
                f"relative: {relative}"
            )
            assert absolute
        else:
            assert cls in _RELATIVE_PATH_COLLECTORS
            assert absolute == [], (
                f"{cls.__name__} used to emit only relative paths; these became "
                f"absolute: {absolute}"
            )
            assert relative

    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_helper_output_reaches_the_summary(
        self, cls: type, workspace: Path
    ) -> None:
        """Every one of the six publishes the workspace-relative string in the
        human-readable summary -- that is the channel the helper actually feeds
        for four of them, so it is where a broken hoist would show up first."""
        signals = _instance(cls).collect(workspace)  # type: ignore[attr-defined]
        for signal in signals:
            rel = _workspace_relative(workspace, str(signal.path))
            assert rel in signal.summary, (
                f"{cls.__name__} summary {signal.summary!r} lost its "
                f"workspace-relative path {rel!r}"
            )

    def test_golden_tables_cover_exactly_the_six_subjects(self) -> None:
        """Guards the guard: a typo in a golden key would surface as a KeyError
        that reads like a product failure, and a missing subject would silently
        skip a collector entirely."""
        subjects = set(_SUBJECTS.values())
        assert set(_GOLDEN_RELATIVE) == subjects
        assert set(_GOLDEN_FIELDS) == subjects
        assert _ABSOLUTE_PATH_COLLECTORS | _RELATIVE_PATH_COLLECTORS == subjects
        assert not (_ABSOLUTE_PATH_COLLECTORS & _RELATIVE_PATH_COLLECTORS)

    def test_at_least_one_reported_path_is_nested(self, workspace: Path) -> None:
        """Non-vacuity for the whole golden block: a set of bare filenames would
        satisfy every POSIX assertion above without ever exercising a separator."""
        nested: set[str] = set()
        for cls in _SUBJECTS.values():
            for signal in _instance(cls).collect(workspace):  # type: ignore[attr-defined]
                rel = _workspace_relative(workspace, str(signal.path))
                if "/" in rel:
                    nested.add(rel)
        assert "pkg/sub/broken.py" in nested, sorted(nested)


# ---------------------------------------------------------------------------
# Behavior 7: the hoist injected no dataclass field
# ---------------------------------------------------------------------------

# Exact field names, in order, as they stand before this iteration.
_GOLDEN_FIELDS: dict[type, list[str]] = {
    DependencyCollector: ["name", "max_manifests"],
    LargeFileCollector: ["name", "max_items", "min_bytes"],
    LockfileDriftCollector: ["name", "max_items"],
    SecretFileCollector: ["name", "max_items"],
    MergeConflictCollector: ["name", "max_items", "max_read_bytes"],
    SyntaxErrorCollector: ["name", "max_items", "max_read_bytes"],
}


class TestNoDataclassFieldWasInjected:
    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_field_names_and_order_are_unchanged(self, cls: type) -> None:
        assert [f.name for f in dataclasses.fields(cls)] == _GOLDEN_FIELDS[cls]

    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_class_still_constructs_with_no_arguments(self, cls: type) -> None:
        assert cls().name  # type: ignore[call-arg]

    def test_shared_base_declares_no_annotated_class_attributes(self) -> None:
        """The documented footgun: an annotated attribute on ``BaseCollector``
        would inject a dataclass field into every collector's generated
        ``__init__``. A ``@staticmethod`` must not have done that."""
        own_annotations = vars(BaseCollector).get("__annotations__", {})
        assert own_annotations == {}, (
            f"BaseCollector declares {sorted(own_annotations)}, which reorders the "
            "generated __init__ of all 17 collectors"
        )

    def test_shared_base_is_not_itself_a_dataclass(self) -> None:
        assert not dataclasses.is_dataclass(BaseCollector)


# ---------------------------------------------------------------------------
# Behavior 8: structural typing and the fail-open contract survive
# ---------------------------------------------------------------------------


class TestTypingAndFailOpenSurvive:
    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_instance_satisfies_the_runtime_checkable_protocol(
        self, cls: type
    ) -> None:
        assert isinstance(_instance(cls), Collector)

    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_collect_returns_context_signals(
        self, cls: type, workspace: Path
    ) -> None:
        signals = _instance(cls).collect(workspace)  # type: ignore[attr-defined]
        assert isinstance(signals, list)
        assert all(isinstance(s, ContextSignal) for s in signals)

    @pytest.mark.parametrize("cls", _SUBJECT_PARAMS)
    def test_nonexistent_root_degrades_to_empty_without_raising(
        self, cls: type, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does" / "not" / "exist"
        assert not missing.exists()
        assert _instance(cls).collect(missing) == []  # type: ignore[attr-defined]
