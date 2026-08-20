"""Black-box behavior tests for state-dir iteration 195 (ships as ``factory
iter 197``): the per-manifest ABSORBED-FAILURE diagnostic gets its first oracle,
and its single definition site moves onto ``BaseCollector``.

WHAT IS UNDER TEST. Two L2 collectors guard each manifest INSIDE their own walk
(``DependencyCollector``, ``LockfileDriftCollector``), so a single bad manifest
degrades that ONE item instead of the whole collector. ``factory iter 184``
shipped one aggregated ``logging.WARNING`` per scan for that second absorbing
point -- naming the collector, how many manifests it absorbed, and the
lowest-sorting affected workspace-relative path -- as TWO hand-copied method
bodies with ZERO test coverage. This iteration hosts that method once on
``BaseCollector``. Every assertion below is therefore written against the
OBSERVABLE contract (returned signals + emitted ``logging`` records), so it
holds whether the method lives on the base or on each subclass; what it forbids
is the message silently losing its count, its path, its level, its logger, or
its one-record-per-scan aggregation.

Coverage (numbered to match this iteration's ``pm.md`` "Expected Behaviors"):

1. The aggregated record survives the move, for BOTH collectors: with
   per-manifest construction raising for exactly two of three recognised
   manifests, ``collect(root)`` does not raise, returns only the surviving
   signals, and emits EXACTLY ONE ``WARNING`` naming the collector's ``name``,
   the count ``2``, and the lexicographically smallest absorbed relative path.
2. Two-sided / anti-vacuous: on a tree where nothing raises, the same call
   emits ZERO records at ``WARNING`` or above from ANY logger in the
   ``proactive_loop`` namespace. Without this, behavior 1 would also pass for a
   method that warns unconditionally.
3. One aggregated record, never one per manifest, and walk-order independent:
   with FOUR absorbing manifests the record count is still exactly 1, the count
   it reports equals the number absorbed, and the path it names equals a
   ``min()`` this module computes itself -- never a hardcoded filename, so the
   assertion cannot pass by accident on a lucky walk order.
4. The diagnostic is emitted BEFORE the item cap is applied: with the
   collector's item cap constructed as 1, on a tree with two absorbing and two
   healthy manifests, ``collect(root)`` returns exactly 1 signal AND still
   emits exactly one WARNING reporting 2 absorbed.
5. Logger identity, DERIVED not hardcoded: for both collectors the record's
   ``name`` equals ``BaseCollector.__module__`` read at runtime from the
   shipped class, so one module logger governs both absorbing points.
6. Single definition site + untouched dataclass contract: over the ``.py``
   files under ``src/proactive_loop/`` only, ``_log_absorbed`` is defined
   exactly ONCE and that definition sits in ``class BaseCollector``; the
   attribute is IDENTICAL on both subclasses; ``BaseCollector`` still has no
   ``__dataclass_fields__``; and both collectors keep their field tuples and
   stay constructible with no arguments. The surviving docstring must state the
   contract generically (no ``max_manifests`` / ``max_items``, no
   collector-specific reading).

ISOLATION CONTRACT honored: every expectation comes from this iteration's
``pm.md`` "Expected Behaviors" plus the conventions of existing modules under
``tests/`` (``test_iter169_behavior.py`` for the namespace-wide ``caplog``
record filter and the runtime-derived logger name, ``test_iter09_behavior.py``
for the dependency-manifest fixtures, ``test_iter70_behavior.py`` for the
lockfile pairings, ``test_source_comment_bounds.py`` for an ``ast`` census
scoped to ``src/proactive_loop/``). No implementation file was read, no
engineer or reviewer note was opened, and no ``git diff`` was consulted. The
message SHAPE was obtained by RUNNING the shipped collectors and reading the
records they emit, and the signatures monkeypatched here by
``inspect.signature`` on public class attributes.

Offline and deterministic: ``tmp_path`` fixture trees only (never the ambient
repo tree, so no collector can perceive repo state), no network, no subprocess,
no ``git`` invocation, no API key, and no duration asserted anywhere. The
``ast`` census in behavior 6 walks the FILESYSTEM under ``src/proactive_loop/``
rather than ``git ls-files``, so a newly added or still-untracked module cannot
fall outside the domain it is measured in -- the inverse of the census that
reds the build the moment its own new file is staged.
"""

from __future__ import annotations

import ast
import dataclasses
import logging
from pathlib import Path
from typing import Callable

import pytest

from proactive_loop.collectors import DependencyCollector, LockfileDriftCollector
from proactive_loop.collectors.base import BaseCollector
from proactive_loop.models import ContextSignal

# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------

_PACKAGE = "proactive_loop"

# The logger every absorbed-manifest record must ride, DERIVED at runtime from
# the shipped base class (behavior 5) -- never a hardcoded dotted string.
_EXPECTED_LOGGER = BaseCollector.__module__

# Distinctive text, so nothing below can pass on an unrelated exception message.
_BOOM = "iter200-induced-manifest-failure"

_PYPROJECT = '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["a", "b"]\n'

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PKG = REPO_ROOT / "src" / "proactive_loop"


def _write(path: Path, content: str) -> Path:
    """Create *path* (and parents) with *content* (utf-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _tree(root: Path, rel_paths: list[str]) -> list[str]:
    """Write one ``pyproject.toml``-shaped manifest per entry in *rel_paths*.

    ``pyproject.toml`` is recognised by BOTH collectors under test (a
    dependency manifest, and the lock-bearing manifest of the
    ``pyproject.toml -> uv.lock`` pairing), so one fixture shape drives both
    and no collector-specific tree is needed. No lockfile is written, which
    keeps the lockfile collector's healthy manifests signal-bearing.
    """
    for rel in rel_paths:
        _write(root / rel, _PYPROJECT)
    return rel_paths


def _product_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Records at WARNING or above emitted from inside the product namespace.

    Filtered on the package PREFIX rather than one exact logger name, so a
    warning from ANY product module counts. That is what makes behavior 2 a
    real anti-vacuity control instead of a check scoped to the single logger
    under test -- and it is also what would catch the diagnostic escaping to
    the root logger.
    """
    return [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and (record.name == _PACKAGE or record.name.startswith(_PACKAGE + "."))
    ]


def _fail_dependencies(
    monkeypatch: pytest.MonkeyPatch, failing: set[str]
) -> None:
    """Make ``DependencyCollector`` raise for exactly the relative paths in *failing*.

    Patches the per-manifest construction seam on the CLASS and delegates to
    the shipped implementation for every other manifest, so the healthy path
    stays byte-for-byte the product's own. ``monkeypatch`` restores it
    unconditionally at teardown.
    """
    original = DependencyCollector._signal_for

    def patched(self: DependencyCollector, path: Path, rel: str, fname: str) -> ContextSignal:
        if rel in failing:
            raise RuntimeError(_BOOM)
        return original(self, path, rel, fname)

    monkeypatch.setattr(DependencyCollector, "_signal_for", patched)


def _fail_lockfile(monkeypatch: pytest.MonkeyPatch, failing: set[str]) -> None:
    """Make ``LockfileDriftCollector`` raise for exactly the relative paths in *failing*."""
    original = LockfileDriftCollector._signal_for

    def patched(
        self: LockfileDriftCollector,
        root: Path,
        manifest: Path,
        candidates: tuple[str, ...],
    ) -> ContextSignal | None:
        rel = manifest.resolve().relative_to(root.resolve()).as_posix()
        if rel in failing:
            raise RuntimeError(_BOOM)
        return original(self, root, manifest, candidates)

    monkeypatch.setattr(LockfileDriftCollector, "_signal_for", patched)


# Both collectors, each with the seam-patcher that induces a per-manifest
# failure and the keyword that constructs its item cap. Parametrizing on this
# table is what makes every behavior below cover BOTH absorbing collectors
# without duplicating a single assertion.
_TARGETS: list[pytest.param] = [
    pytest.param(
        DependencyCollector,
        _fail_dependencies,
        "max_manifests",
        id="dependencies",
    ),
    pytest.param(
        LockfileDriftCollector,
        _fail_lockfile,
        "max_items",
        id="lockfile_drift",
    ),
]


# ---------------------------------------------------------------------------
# Behavior 1 -- the aggregated record survives the move, for BOTH collectors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("cls", "induce", "cap_kw"), _TARGETS)
def test_b1_aggregated_record_names_collector_count_and_min_path(
    cls: type,
    induce: Callable[[pytest.MonkeyPatch, set[str]], None],
    cap_kw: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rels = _tree(tmp_path, ["beta/pyproject.toml", "alpha/pyproject.toml", "gamma/pyproject.toml"])
    absorbed = {"beta/pyproject.toml", "alpha/pyproject.toml"}
    survivor = sorted(set(rels) - absorbed)
    induce(monkeypatch, absorbed)

    collector = cls()
    with caplog.at_level(logging.DEBUG, logger=_PACKAGE):
        try:
            signals = collector.collect(tmp_path)
        except Exception as exc:  # pragma: no cover -- the fail-open invariant
            pytest.fail(f"collect() must never raise; it raised {exc!r}")

    # (b) only the manifests that succeeded come back.
    assert [s.summary for s in signals] and len(signals) == len(survivor)
    for rel in survivor:
        assert any(rel in s.summary for s in signals), (
            f"surviving manifest {rel!r} missing from {[s.summary for s in signals]!r}"
        )
    for rel in absorbed:
        assert not any(rel in s.summary for s in signals), (
            f"absorbed manifest {rel!r} must not yield a signal"
        )

    # (c) exactly one WARNING, naming name + count + lowest-sorting path.
    records = _product_warnings(caplog)
    assert len(records) == 1, f"expected exactly one product WARNING; got {[r.getMessage() for r in records]!r}"
    message = records[0].getMessage()
    assert records[0].levelno == logging.WARNING
    assert collector.name in message, message
    assert str(len(absorbed)) in message, message
    assert min(absorbed) in message, message


# ---------------------------------------------------------------------------
# Behavior 2 -- two-sided / anti-vacuous: silence when nothing is absorbed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("cls", "induce", "cap_kw"), _TARGETS)
def test_b2_healthy_tree_emits_zero_product_warnings(
    cls: type,
    induce: Callable[[pytest.MonkeyPatch, set[str]], None],
    cap_kw: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _tree(tmp_path, ["beta/pyproject.toml", "alpha/pyproject.toml", "gamma/pyproject.toml"])

    with caplog.at_level(logging.DEBUG, logger=_PACKAGE):
        signals = cls().collect(tmp_path)

    assert len(signals) == 3, f"every healthy manifest should yield a signal; got {signals!r}"
    assert _product_warnings(caplog) == [], (
        "a scan that absorbed nothing must emit no WARNING: "
        f"{[r.getMessage() for r in _product_warnings(caplog)]!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- logger identity, derived from the shipped class at runtime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("cls", "induce", "cap_kw"), _TARGETS)
def test_b5_record_rides_the_base_module_logger(
    cls: type,
    induce: Callable[[pytest.MonkeyPatch, set[str]], None],
    cap_kw: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _tree(tmp_path, ["alpha/pyproject.toml", "beta/pyproject.toml"])
    induce(monkeypatch, {"alpha/pyproject.toml"})

    with caplog.at_level(logging.DEBUG, logger=_PACKAGE):
        cls().collect(tmp_path)

    records = _product_warnings(caplog)
    assert len(records) == 1
    assert records[0].name == _EXPECTED_LOGGER, (
        f"absorbed-manifest record rode {records[0].name!r}; expected "
        f"BaseCollector.__module__ == {_EXPECTED_LOGGER!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- ONE aggregated record for many absorbed manifests, and the
# path it names is a min() this module computes, not a hardcoded filename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("cls", "induce", "cap_kw"), _TARGETS)
def test_b3_one_record_for_four_absorbed_with_computed_min_path(
    cls: type,
    induce: Callable[[pytest.MonkeyPatch, set[str]], None],
    cap_kw: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Directory names are deliberately NOT in walk order and NOT in creation
    # order, and the lowest-sorting one is created LAST, so an implementation
    # that reported "the first failure seen" would name a different path.
    absorbed = {
        "zulu/pyproject.toml",
        "mike/pyproject.toml",
        "delta/nested/pyproject.toml",
        "alpha/pyproject.toml",
    }
    rels = _tree(tmp_path, sorted(absorbed, reverse=True) + ["zzz-healthy/pyproject.toml"])
    induce(monkeypatch, absorbed)

    with caplog.at_level(logging.DEBUG, logger=_PACKAGE):
        signals = cls().collect(tmp_path)

    assert len(signals) == len(rels) - len(absorbed) == 1

    records = _product_warnings(caplog)
    assert len(records) == 1, (
        "the guard must aggregate to ONE record per scan, never one per manifest: "
        f"{[r.getMessage() for r in records]!r}"
    )
    message = records[0].getMessage()
    # The count it reports equals the number absorbed ...
    assert f" {len(absorbed)} " in message, message
    # ... and the path it names is the min() computed here, which for this
    # fixture is neither the first written nor the first walked.
    expected_min = min(absorbed)
    assert expected_min == "alpha/pyproject.toml"  # fixture sanity, not a product claim
    assert expected_min in message, message
    for other in absorbed - {expected_min}:
        assert other not in message, (
            f"only the lowest-sorting absorbed path belongs in the record; found {other!r}"
        )


# ---------------------------------------------------------------------------
# Behavior 4 -- the diagnostic is emitted BEFORE the item cap truncates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("cls", "induce", "cap_kw"), _TARGETS)
def test_b4_record_survives_the_item_cap(
    cls: type,
    induce: Callable[[pytest.MonkeyPatch, set[str]], None],
    cap_kw: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    absorbed = {"alpha/pyproject.toml", "bravo/pyproject.toml"}
    _tree(tmp_path, sorted(absorbed) + ["charlie/pyproject.toml", "delta/pyproject.toml"])
    induce(monkeypatch, absorbed)

    collector = cls(**{cap_kw: 1})
    with caplog.at_level(logging.DEBUG, logger=_PACKAGE):
        signals = collector.collect(tmp_path)

    assert len(signals) == 1, (
        f"{cap_kw}=1 must cap the RETURNED signals at one; got {[s.summary for s in signals]!r}"
    )
    records = _product_warnings(caplog)
    assert len(records) == 1, (
        "the absorbed-manifest diagnostic must survive the item cap: "
        f"{[r.getMessage() for r in records]!r}"
    )
    assert f" {len(absorbed)} " in records[0].getMessage(), records[0].getMessage()


# ---------------------------------------------------------------------------
# Behavior 6 -- ONE definition site, and the dataclass contract is untouched
# ---------------------------------------------------------------------------


def _src_definition_sites(name: str) -> list[tuple[str, str, int]]:
    """Every ``def <name>`` under ``src/proactive_loop/``, with its owning class.

    Domain is the FILESYSTEM under the package dir -- never ``tests/`` (this
    module itself names the symbol repeatedly) and never the ambient repo root.
    Walking the filesystem rather than ``git ls-files`` means a module that is
    new or still untracked cannot fall outside the domain it is measured in.
    """
    sites: list[tuple[str, str, int]] = []
    for path in sorted(SRC_PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for child in node.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == name
                ):
                    sites.append(
                        (path.relative_to(SRC_PKG).as_posix(), node.name, child.lineno)
                    )
    return sites


def test_b6_single_definition_site_on_the_base_class() -> None:
    sites = _src_definition_sites("_log_absorbed")
    assert len(sites) == 1, (
        "_log_absorbed must be defined exactly once under src/proactive_loop/; "
        f"found {sites!r}"
    )
    module, owner, _lineno = sites[0]
    assert owner == "BaseCollector", f"the surviving definition sits in {owner!r}"
    assert module == "collectors/base.py", f"the surviving definition lives in {module!r}"

    # Sanity: the census can see a definition it should see. Without this, a
    # broken walk would report "exactly one" for the wrong reason.
    assert len(_src_definition_sites("_relative")) == 1
    collect_owners = {
        owner for mod, owner, _ in _src_definition_sites("collect") if mod == "collectors/base.py"
    }
    assert "BaseCollector" in collect_owners, collect_owners


@pytest.mark.parametrize(
    "cls", [pytest.param(DependencyCollector, id="dependencies"), pytest.param(LockfileDriftCollector, id="lockfile_drift")]
)
def test_b6_attribute_is_inherited_identically(cls: type) -> None:
    assert cls._log_absorbed is BaseCollector._log_absorbed, (
        f"{cls.__name__} must inherit the single hosted method, not shadow it"
    )


def test_b6_dataclass_contract_unchanged() -> None:
    # The base stays a plain class: an annotated class attribute there would be
    # absorbed into every subclass's generated __init__ signature.
    assert not hasattr(BaseCollector, "__dataclass_fields__"), (
        "BaseCollector must remain a non-dataclass; the hosted member is a plain method"
    )
    assert callable(BaseCollector.__dict__["_log_absorbed"])
    assert not isinstance(BaseCollector.__dict__["_log_absorbed"], (staticmethod, classmethod))
    assert "_log_absorbed" not in getattr(BaseCollector, "__annotations__", {})

    assert tuple(f.name for f in dataclasses.fields(DependencyCollector)) == (
        "name",
        "max_manifests",
    )
    assert tuple(f.name for f in dataclasses.fields(LockfileDriftCollector)) == (
        "name",
        "max_items",
    )
    # Both stay constructible with NO arguments (the registry builds them so).
    assert DependencyCollector().name == "dependencies"
    assert LockfileDriftCollector().name == "lockfile_drift"


def test_b6_surviving_docstring_states_the_contract_generically() -> None:
    doc = BaseCollector._log_absorbed.__doc__
    assert doc is not None and doc.strip(), "the hosted method must keep its WHY"
    # Neither copy's collector-specific field name nor reading may survive on a
    # method that now documents the contract for every subclass.
    for banned in ("max_manifests", "max_items", "no dependency signals", "no drift"):
        assert banned not in doc, (
            f"the single surviving docstring must be generic; it names {banned!r}"
        )
