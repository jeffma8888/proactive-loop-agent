"""Behavior tests for iteration 129: ONE shared fail-open ``collect()`` wrapper.

Iteration 129 relocates the byte-identical never-raises ``collect()`` wrapper out
of all 16 collectors and into a single concrete base class in
``proactive_loop.collectors.base``, then guards the duplication so it cannot grow
back. The fail-open contract itself is unchanged -- every collector still swallows
its own exceptions; only the *implementation site* moves.

Coverage (numbered to match the iteration spec's Expected Behaviors):

1. Fail-open is preserved AND actually exercised: a ``_collect`` that RAISES still
   yields ``[]``. The pre-existing suite only proved never-raise against hostile
   *inputs* (``test_collectors.py::TestGracefulDegradation``), so the wrapper
   itself was unexercised until now.
2. Normal collection is unchanged: every collector returns a ``list`` on a real
   empty directory and raises nothing.
3. The public typing contract is unchanged: ``isinstance(c, Collector)`` holds via
   the INHERITED ``collect`` (the ``@runtime_checkable`` Protocol is structural),
   and every ``name`` is a unique non-empty string.
4. Construction is unchanged -- the dataclass footgun is guarded: every collector
   class still constructs with NO arguments, ``name`` is still the first field,
   every field still carries a default, and the shared base contributes ZERO
   dataclass fields and declares no annotated class attributes.
5. The duplication is gone and cannot grow back: a two-sided AST drift guard over
   every collector module, proven to FAIL on a planted ``collect`` re-declaration
   and on a planted collector whose ``_collect`` was renamed away.
6. The shared base's own behavior is specified: instantiated directly it degrades
   to ``[]`` (its ``_collect`` raises ``NotImplementedError``, which the wrapper
   swallows like any other exception), so a subclass that forgets ``_collect``
   never crashes a scan -- behavior 5(b) is what catches that mistake.

Everything is driven from the public registry ``all_collectors()``: no hardcoded
collector list, no subprocess, no network, ``tmp_path`` only.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from proactive_loop import collectors as collectors_pkg
from proactive_loop.collectors import all_collectors
from proactive_loop.collectors.base import Collector
from proactive_loop.models import ContextSignal

# ---------------------------------------------------------------------------
# Registry-driven parameters (no hardcoded collector list)
# ---------------------------------------------------------------------------

_INSTANCES = all_collectors()
_INSTANCE_PARAMS = [pytest.param(c, id=c.name) for c in _INSTANCES]
_CLASS_PARAMS = [pytest.param(type(c), id=c.name) for c in _INSTANCES]
_CLASS_NAMES = frozenset(type(c).__name__ for c in _INSTANCES)

_BASE_MODULE = "proactive_loop.collectors.base"

# Modules in the collectors package that are not collector implementations.
_NON_COLLECTOR_MODULES = frozenset({"base.py", "__init__.py"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _shared_base() -> type:
    """Return the ONE concrete base class every collector inherits ``collect`` from.

    Discovered structurally (never by name) so the proof does not encode a naming
    choice the spec left open: for each registered collector, walk its MRO for a
    class defined in ``collectors.base`` that declares ``collect`` in its own
    ``__dict__``. Exactly one such class must exist, and it must be the SAME class
    for all collectors -- that is behavior 5(c) checked at runtime.
    """
    bases: set[type] = set()
    for instance in _INSTANCES:
        cls = type(instance)
        candidates = [
            base
            for base in cls.__mro__[1:]
            if base is not object
            and getattr(base, "__module__", "") == _BASE_MODULE
            and "collect" in vars(base)
        ]
        assert len(candidates) == 1, (
            f"{cls.__name__} must inherit collect() from exactly ONE class defined "
            f"in {_BASE_MODULE}; found {[c.__name__ for c in candidates]}"
        )
        bases.add(candidates[0])
    assert len(bases) == 1, (
        "every collector must share ONE base class; found "
        f"{sorted(b.__name__ for b in bases)}"
    )
    return bases.pop()


def _collector_module_paths() -> list[Path]:
    """Return every module file in the collectors package that may declare a collector."""
    package_file = collectors_pkg.__file__
    assert package_file is not None, "collectors package must resolve to a file"
    package_dir = Path(package_file).parent
    return sorted(
        path
        for path in package_dir.glob("*.py")
        if path.name not in _NON_COLLECTOR_MODULES
    )


def _drift_violations(
    source: str, *, class_names: frozenset[str], base_name: str
) -> tuple[list[str], set[str]]:
    """Report fail-open-wrapper drift for the collector classes declared in *source*.

    Returns ``(violations, seen_class_names)``. A collector class must:
    (a) NOT declare ``collect`` -- the wrapper lives only in the shared base;
    (b) declare ``_collect`` -- the hook the shared wrapper delegates to;
    (c) name *base_name* among its bases.

    Pure AST over a source STRING, so the guard can be aimed at a planted
    known-bad sample without ever mutating a shipped file.
    """
    violations: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef) or node.name not in class_names:
            continue
        seen.add(node.name)
        methods = {
            child.name
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if "collect" in methods:
            violations.append(
                f"{node.name} re-declares collect(): the fail-open wrapper must "
                f"exist only once, in {base_name}"
            )
        if "_collect" not in methods:
            violations.append(f"{node.name} does not declare _collect()")
        declared_bases = {
            base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
            for base in node.bases
        }
        if base_name not in declared_bases:
            violations.append(
                f"{node.name} does not inherit from {base_name}; bases are "
                f"{sorted(declared_bases)}"
            )
    return violations, seen


def _planted_source(base_name: str, *, hook: str, redeclare_wrapper: bool) -> str:
    """Build a synthetic collector module source for the drift guard's self-test.

    Never imported or executed -- only ``ast.parse``d by :func:`_drift_violations`.
    """
    wrapper = ""
    if redeclare_wrapper:
        wrapper = (
            "    def collect(self, root):\n"
            "        try:\n"
            "            return self._collect(root)\n"
            "        except Exception:\n"
            "            return []\n\n"
        )
    return (
        "from dataclasses import dataclass\n\n"
        f"from proactive_loop.collectors.base import {base_name}\n\n\n"
        "@dataclass\n"
        f"class PlantedCollector({base_name}):\n"
        '    name: str = "planted"\n\n'
        f"{wrapper}"
        f"    def {hook}(self, root):\n"
        "        return []\n"
    )


_PLANTED_NAMES = frozenset({"PlantedCollector"})


def _raiser(root: Path) -> list[ContextSignal]:
    """Stand in for a collector's ``_collect`` hook and blow up.

    Bound as an INSTANCE attribute, so it shadows the class method WITHOUT
    descriptor binding: it takes ``root`` only and never receives ``self``.
    """
    raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Behavior 1: fail-open is preserved AND actually exercised
# ---------------------------------------------------------------------------


class TestFailOpenWrapperSwallowsARaisingHook:
    """The load-bearing L2 invariant: one raising collector must not abort a scan."""

    @pytest.mark.parametrize("collector", _INSTANCE_PARAMS)
    def test_raising_collect_hook_degrades_to_empty_list(
        self, collector: Collector, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instance = type(collector)()
        monkeypatch.setattr(instance, "_collect", _raiser)
        assert instance.collect(tmp_path) == []

    @pytest.mark.parametrize("collector", _INSTANCE_PARAMS)
    def test_raising_collect_hook_raises_nothing_to_the_caller(
        self, collector: Collector, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instance = type(collector)()
        monkeypatch.setattr(instance, "_collect", _raiser)
        try:
            instance.collect(tmp_path)
        except Exception as exc:  # pragma: no cover -- the invariant's failure mode
            pytest.fail(f"{type(collector).__name__}.collect() raised {exc!r}")


# ---------------------------------------------------------------------------
# Behavior 2: normal collection is unchanged
# ---------------------------------------------------------------------------


class TestNormalCollectionIsUnchanged:
    @pytest.mark.parametrize("collector", _INSTANCE_PARAMS)
    def test_empty_directory_returns_a_list(
        self, collector: Collector, tmp_path: Path
    ) -> None:
        result = collector.collect(tmp_path)
        assert isinstance(result, list)
        assert all(isinstance(signal, ContextSignal) for signal in result)


# ---------------------------------------------------------------------------
# Behavior 3: the public typing contract is unchanged
# ---------------------------------------------------------------------------


class TestPublicTypingContractIsUnchanged:
    @pytest.mark.parametrize("collector", _INSTANCE_PARAMS)
    def test_instance_still_satisfies_the_runtime_checkable_protocol(
        self, collector: Collector
    ) -> None:
        assert isinstance(collector, Collector)

    @pytest.mark.parametrize("collector", _INSTANCE_PARAMS)
    def test_name_is_a_non_empty_string(self, collector: Collector) -> None:
        assert isinstance(collector.name, str)
        assert collector.name.strip()

    def test_names_are_unique_across_the_registry(self) -> None:
        names = [c.name for c in _INSTANCES]
        assert len(set(names)) == len(names), f"duplicate collector name in {names}"


# ---------------------------------------------------------------------------
# Behavior 4: construction is unchanged -- the dataclass footgun is guarded
# ---------------------------------------------------------------------------


class TestConstructionIsUnchanged:
    @pytest.mark.parametrize("cls", _CLASS_PARAMS)
    def test_class_constructs_with_no_arguments(self, cls: type) -> None:
        assert cls().name

    @pytest.mark.parametrize("cls", _CLASS_PARAMS)
    def test_name_is_still_the_first_dataclass_field(self, cls: type) -> None:
        field_names = [f.name for f in dataclasses.fields(cls)]
        assert field_names[0] == "name", f"{cls.__name__} fields are {field_names}"

    @pytest.mark.parametrize("cls", _CLASS_PARAMS)
    def test_every_dataclass_field_still_carries_a_default(self, cls: type) -> None:
        for field in dataclasses.fields(cls):
            has_default = (
                field.default is not dataclasses.MISSING
                or field.default_factory is not dataclasses.MISSING
            )
            assert has_default, (
                f"{cls.__name__}.{field.name} lost its default, so no-argument "
                "construction is about to break across the registry"
            )

    def test_shared_base_contributes_no_dataclass_fields(self) -> None:
        base = _shared_base()
        assert not dataclasses.is_dataclass(base)
        assert getattr(base, "__dataclass_fields__", None) is None

    def test_shared_base_declares_no_annotated_class_attributes(self) -> None:
        base = _shared_base()
        own_annotations = vars(base).get("__annotations__", {})
        assert own_annotations == {}, (
            f"{base.__name__} declares {sorted(own_annotations)}; an annotated "
            "attribute on the base reorders the generated __init__ of every subclass"
        )


# ---------------------------------------------------------------------------
# Behavior 5: the duplication is gone and cannot grow back (two-sided guard)
# ---------------------------------------------------------------------------


class TestWrapperDuplicationDriftGuard:
    def test_no_collector_module_declares_its_own_wrapper(self) -> None:
        base_name = _shared_base().__name__
        violations: list[str] = []
        seen: set[str] = set()
        for path in _collector_module_paths():
            found, names = _drift_violations(
                path.read_text(encoding="utf-8"),
                class_names=_CLASS_NAMES,
                base_name=base_name,
            )
            violations.extend(f"{path.name}: {v}" for v in found)
            seen |= names
        assert violations == []
        # Guards the guard: a class-name filter that matched nothing would make
        # the scan above vacuously green.
        assert seen == set(_CLASS_NAMES), (
            "drift guard did not visit every registered collector; missing "
            f"{sorted(set(_CLASS_NAMES) - seen)}"
        )

    def test_guard_accepts_a_well_formed_planted_collector(self) -> None:
        base_name = _shared_base().__name__
        source = _planted_source(base_name, hook="_collect", redeclare_wrapper=False)
        violations, seen = _drift_violations(
            source, class_names=_PLANTED_NAMES, base_name=base_name
        )
        assert violations == []
        assert seen == set(_PLANTED_NAMES)

    def test_guard_fails_on_a_planted_wrapper_redeclaration(self) -> None:
        base_name = _shared_base().__name__
        source = _planted_source(base_name, hook="_collect", redeclare_wrapper=True)
        violations, _ = _drift_violations(
            source, class_names=_PLANTED_NAMES, base_name=base_name
        )
        assert any("re-declares collect()" in v for v in violations), violations

    def test_guard_fails_on_a_planted_collector_missing_its_hook(self) -> None:
        base_name = _shared_base().__name__
        source = _planted_source(base_name, hook="gather", redeclare_wrapper=False)
        violations, _ = _drift_violations(
            source, class_names=_PLANTED_NAMES, base_name=base_name
        )
        assert any("does not declare _collect()" in v for v in violations), violations


# ---------------------------------------------------------------------------
# Behavior 6: the shared base's own behavior is specified
# ---------------------------------------------------------------------------


class TestSharedBaseOwnBehavior:
    def test_base_is_instantiable_with_no_arguments(self) -> None:
        assert _shared_base()() is not None

    def test_base_collect_degrades_to_empty_list(self, tmp_path: Path) -> None:
        assert _shared_base()().collect(tmp_path) == []

    def test_base_collect_hook_raises_not_implemented(self, tmp_path: Path) -> None:
        base_instance = _shared_base()()
        with pytest.raises(NotImplementedError):
            base_instance._collect(tmp_path)
