"""Black-box oracle for foundry iteration 263 (state dir ``iter-263``).

Feature under test: batch 4 of the shared-walk program. ``todos``,
``large_file`` and ``syntax_error`` stop running their own ``os.walk`` of the
workspace and read the shared per-scan dirent listing from
``collectors/dir_source``, taking one scan from 8 physical traversals to 5. The
README enumeration and the ``dir_source`` rationale are corrected in the same
commit, and the enumeration gains a code-derived oracle.

MODULE NAME. ``pm.md`` names ``tests/test_iter239_behavior.py`` and that is what
this is. Derived from the repo, not from the state-dir number: the highest
tracked ``tests/test_iterNN_behavior.py`` at HEAD is 238 and
``git cat-file -e HEAD:tests/test_iter239_behavior.py`` fails, so the path was
proven free before this file was written. The state dir is 263; naming the
module 263 would have been wrong.

ISOLATION CONTRACT (honored, no exceptions). Every assertion below is derived
from this iteration's ``pm.md`` "Expected Behaviors", from the conventions of
existing modules under ``tests/`` (``tests/test_iter187_behavior.py`` for the
provider API, the autouse cache-isolation fixture and the counting-``os.walk``
wrapper; ``tests/test_iter37/77/90_behavior.py`` for the three collectors'
public constructors), and from RUNNING the shipped public interface. **No file
under ``src/`` was read as source text for design, no engineer/reviewer note was
opened, and no ``git diff`` was consulted.** The censuses in behaviors 1, 8, 10
and 11 measure tracked files mechanically (substring counts over bytes), which
is the established idiom in ``test_iter187_behavior.py``.

Offline and deterministic: ``tmp_path`` fixture trees only, no network, no
wall-clock assertion. Every path asserted on is TRACKED by git, so a fresh clone
(the release re-verification) carries it. Nothing asserts on docstring or
help-text indentation, so the 3.12/3.13 matrix legs cannot diverge here.

Coverage (numbered to match the spec's Expected Behaviors):

1. The three modules name no ``os.walk(`` and each names a ``dir_source.walk(``
   call site.
2. Inside ONE ``walk_scope()`` the three converted collectors plus one
   already-converted collector share a single physical listing
   (``misses == 1``, ``hits >= 3``); with no scope every ``walk()`` is a miss.
3. The directory prune is inherited: nothing is emitted from ``node_modules``,
   ``dist``, ``__pycache__``, ``.git`` or a hidden ``.hidden`` directory.
4. The hidden-FILE policy survives: a hidden file that would otherwise qualify
   emits nothing from any of the three.
5. Per-file suffix and size policy survives verbatim.
6. Order and caps are unchanged under a lowered ``max_items``.
7. The library-consumer path (no scope) returns exactly what a scoped run does.
8. Prune symbols follow the batch-3 precedent: no ``_SKIP_DIRS``, no
   ``import os``, ``_is_hidden`` retained.
9. ``test_iter187_behavior.py``'s equality pin names exactly three collector
   modules and states no stale count.
10. The README enumeration is bound to the code, two-sided.
11. The false ``filesystem.py`` rationale is retired from ``dir_source.py``.
12. Nothing else regresses. The ROADMAP budget clause is verified by
    DELEGATION to its single owner: ``tests/test_iter172_behavior.py``
    single-sources that budget and reds when any unsanctioned module asserts a
    size bound on the document, so restating ``len(ROADMAP.md) < 40_000`` here
    is a defect, not coverage. The live document is bounded by
    ``tests/test_roadmap_size_budget.py`` (the owner) and
    ``tests/test_iter214_behavior.py::test_b7`` in this same suite run; the
    typecheck and full-suite clauses are that run itself.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final

import pytest

from proactive_loop.collectors.dir_source import (
    clear_walk_cache,
    walk_cache_stats,
    walk_scope,
)
from proactive_loop.collectors.large_file import LargeFileCollector
from proactive_loop.collectors.secret_file import SecretFileCollector
from proactive_loop.collectors.syntax_error import SyntaxErrorCollector, clear_parse_memo
from proactive_loop.collectors.todos import TodoCollector, clear_todo_memo
from proactive_loop.models import ContextSignal

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
SRC_PKG: Final[Path] = REPO_ROOT / "src" / "proactive_loop"
COLLECTORS_DIR: Final[Path] = SRC_PKG / "collectors"
README: Final[Path] = REPO_ROOT / "README.md"

# The three modules this iteration converts.
CONVERTED_NOW: Final[tuple[str, ...]] = ("todos.py", "large_file.py", "syntax_error.py")

# The two walkers kept by design (spec Out of Scope), plus the provider itself.
STILL_WALKING: Final[frozenset[str]] = frozenset(
    {"dir_source.py", "filesystem.py", "notes.py"}
)


def _source(name: str) -> str:
    return (COLLECTORS_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Behavior 1: the three modules no longer own a traversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", CONVERTED_NOW)
def test_b01_converted_module_names_no_os_walk(module: str) -> None:
    """Spec behavior 1: ``os.walk(`` is gone from each converted module."""
    text = _source(module)
    assert "os.walk(" not in text, (
        f"{module} still owns a traversal; batch 4 must route it through the "
        "shared provider"
    )


@pytest.mark.parametrize("module", CONVERTED_NOW)
def test_b01_converted_module_calls_the_shared_provider(module: str) -> None:
    """Spec behavior 1: each converted module has a ``dir_source.walk(`` site."""
    text = _source(module)
    assert "dir_source.walk(" in text, (
        f"{module} names no dir_source.walk( call site, so it cannot be served "
        "by the shared per-scan listing"
    )


# ---------------------------------------------------------------------------
# Shared fixtures
#
# ``LargeFileCollector`` needs ``min_bytes`` lowered or it is STRUCTURALLY
# SILENT on any fixture (its default is 5 MB), and a silent collector makes
# every "no leak" assertion a tautology. So the fixture seeds 9,000-byte files
# and the factory below passes ``min_bytes=1000``: each arm is checked to have
# EMITTED something before its negative claim is believed.
# ---------------------------------------------------------------------------

BIG: Final[int] = 9_000
MIN_BYTES: Final[int] = 1_000

# The five directories the shared provider prunes (four noise names + one
# hidden), each seeded with a file EVERY one of the three would otherwise report.
PRUNED_DIRS: Final[tuple[str, ...]] = (
    "node_modules",
    "dist",
    "__pycache__",
    ".git",
    ".hidden",
)

# Hidden FILES that would each qualify if the file-level policy were dropped.
HIDDEN_FILES: Final[tuple[str, ...]] = (".todo.py", ".broken.py", ".big.bin")

Projection = tuple[str, str, str, str, str | None, float, Any]


@pytest.fixture(autouse=True)
def _isolate_caches() -> Iterator[None]:
    """No test may inherit or leak provider cache entries, counters or memos."""
    clear_walk_cache()
    clear_todo_memo()
    clear_parse_memo()
    yield
    clear_walk_cache()
    clear_todo_memo()
    clear_parse_memo()


def _write(root: Path, rel: str, content: str = "x = 1\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_bytes(root: Path, rel: str, size: int) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"z" * size)
    return path


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A tmp workspace tripping all three collectors, with every trap seeded.

    Hermetic on purpose: the ambient repo tree is never scanned, because a fresh
    clone (the release re-verification) does not carry gitignored local state.
    """
    root = tmp_path / "ws"
    root.mkdir()
    # Visible positives, one per collector.
    _write(root, "pkg/a.py", "# TODO: alpha\nx = 1\n")
    _write(root, "pkg/b.py", "def (\n")
    _write_bytes(root, "pkg/big.bin", BIG)
    # An already-converted collector's positive, for the shared-listing count.
    _write(root, "pkg/sub/.env.local", "TOKEN=abc\n")
    # Hidden FILES at the root: each would qualify but for the file-level policy.
    _write(root, ".todo.py", "# TODO: hidden\n")
    _write(root, ".broken.py", "def (\n")
    _write_bytes(root, ".big.bin", BIG)
    # Every pruned directory holds a file EACH of the three would report.
    for name in PRUNED_DIRS:
        _write(root, f"{name}/t.py", "# TODO: pruned\n")
        _write(root, f"{name}/bad.py", "def (\n")
        _write_bytes(root, f"{name}/big.bin", BIG)
    return root


def _todo() -> TodoCollector:
    return TodoCollector()


def _large() -> LargeFileCollector:
    return LargeFileCollector(min_bytes=MIN_BYTES)


def _syntax() -> SyntaxErrorCollector:
    return SyntaxErrorCollector()


THREE: Final[tuple[tuple[str, Callable[[], Any]], ...]] = (
    ("todos", _todo),
    ("large_file", _large),
    ("syntax_error", _syntax),
)


def _relpath(root: Path, sig: ContextSignal) -> str | None:
    """Workspace-relative, forward-slashed path, with a ``:lineno`` suffix cut.

    The three collectors do not agree on ``path`` shape -- ``todos`` reports a
    relative ``pkg/a.py:1``, ``syntax_error`` a relative ``pkg/b.py`` and
    ``large_file`` an absolute path -- so a prune assertion has to normalise
    before it can be believed.
    """
    if sig.path is None:
        return None
    raw = str(sig.path)
    match = re.match(r"^(?P<path>.*):(?P<lineno>\d+)$", raw)
    if match is not None:
        raw = match.group("path")
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def _projection(root: Path, signals: list[ContextSignal]) -> list[Projection]:
    """The full public signal contract, with paths made workspace-relative."""
    return [
        (
            sig.source,
            sig.kind,
            sig.summary,
            sig.detail,
            _relpath(root, sig),
            sig.weight,
            sig.timestamp,
        )
        for sig in signals
    ]


# ---------------------------------------------------------------------------
# Behavior 2: three traversals are eliminated, measurably
# ---------------------------------------------------------------------------


def test_b02_one_scope_serves_all_four_collectors_from_one_listing(
    workspace: Path,
) -> None:
    """Spec behavior 2: inside ONE scope the three converted collectors plus one
    already-converted collector cost exactly ONE physical listing."""
    with walk_scope():
        for _name, factory in THREE:
            factory().collect(workspace)
        SecretFileCollector().collect(workspace)
        stats = walk_cache_stats()

    assert stats["misses"] == 1, (
        "four collectors sharing one scoped root must cost exactly ONE physical "
        f"walk; got {stats!r}"
    )
    assert stats["hits"] >= 3, (
        "the three collectors converted by batch 4 must be SERVED from the "
        f"shared listing, so at least 3 hits are required; got {stats!r}"
    )


def test_b02_no_scope_makes_every_walk_a_miss(workspace: Path) -> None:
    """Spec behavior 2: with no scope, ``misses`` rises once per ``walk()``."""
    seen: list[int] = []
    for _name, factory in THREE:
        factory().collect(workspace)
        seen.append(walk_cache_stats()["misses"])
    assert seen == [1, 2, 3], (
        "the documented pass-through must count one miss per walk() call when no "
        f"scope is active; got {seen!r}"
    )
    assert walk_cache_stats()["hits"] == 0, (
        "nothing can be served from a cache that is not open; got "
        f"{walk_cache_stats()!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 3: the directory prune is inherited, not re-implemented
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,factory", THREE, ids=[n for n, _ in THREE])
def test_b03_no_signal_comes_from_a_pruned_directory(
    workspace: Path, name: str, factory: Callable[[], Any]
) -> None:
    """Spec behavior 3: nothing is reported from any of the five pruned dirs."""
    signals = factory().collect(workspace)
    # POSITIVE CONTROL FIRST -- a structurally silent collector would make the
    # leak assertion below a tautology (the vacuous-arm trap).
    assert signals, (
        f"{name} emitted NOTHING on a fixture built to trip it, so the prune "
        "assertion in this test would be vacuous"
    )
    rels = [_relpath(workspace, sig) for sig in signals]
    leaks = [
        rel
        for rel in rels
        if rel is not None and rel.split("/")[0] in PRUNED_DIRS
    ]
    assert leaks == [], (
        f"{name} reported paths inside a pruned directory, so it is no longer "
        f"inheriting the provider's prune: {leaks!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 4: the hidden-FILE policy survives (the provider filters dirs only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,factory", THREE, ids=[n for n, _ in THREE])
def test_b04_hidden_files_are_still_skipped(
    workspace: Path, name: str, factory: Callable[[], Any]
) -> None:
    """Spec behavior 4: a hidden file that would otherwise qualify emits nothing.

    The provider does not filter FILENAMES, so this policy has to survive at the
    call site -- exactly what a conversion is most likely to "tidy" away.
    """
    signals = factory().collect(workspace)
    assert signals, f"{name} emitted nothing, so this test would be vacuous"
    rels = {_relpath(workspace, sig) for sig in signals}
    for hidden in HIDDEN_FILES:
        assert hidden not in rels, (
            f"{name} reported the hidden file {hidden!r}; the per-file hidden "
            f"policy must stay at the call site. Got {sorted(r for r in rels if r)!r}"
        )


# ---------------------------------------------------------------------------
# Behavior 5: per-file suffix and size policy survives verbatim
# ---------------------------------------------------------------------------


def test_b05_todos_suffix_policy_is_unchanged(tmp_path: Path) -> None:
    """Spec behavior 5: ``todos`` matches only its scan extensions, case-insensitively."""
    _write(tmp_path, "in.py", "# TODO: py\n")
    _write(tmp_path, "upper.PY", "# TODO: upper\n")
    _write(tmp_path, "in.md", "- [ ] TODO: md\n")
    _write(tmp_path, "out.csv", "# TODO: csv\n")
    rels = {_relpath(tmp_path, s) for s in _todo().collect(tmp_path)}
    assert rels == {"in.py", "upper.PY", "in.md"}, (
        "todos must keep its scan-extension set, matched case-insensitively, and "
        f"must ignore a .csv file; got {sorted(r for r in rels if r)!r}"
    )


def test_b05_todos_skips_a_file_over_max_read_bytes(tmp_path: Path) -> None:
    """Spec behavior 5: ``todos`` still refuses to read past ``max_read_bytes``."""
    _write(tmp_path, "small.py", "# TODO: small\n")
    oversize = _write(tmp_path, "huge.py", "# TODO: huge\n" + "#" * 400)
    collector = TodoCollector(max_read_bytes=64)
    assert oversize.stat().st_size > collector.max_read_bytes, "fixture must exceed the cap"
    rels = {_relpath(tmp_path, s) for s in collector.collect(tmp_path)}
    assert rels == {"small.py"}, (
        "a file larger than max_read_bytes must be skipped; got "
        f"{sorted(r for r in rels if r)!r}"
    )


def test_b05_syntax_error_suffix_policy_is_unchanged(tmp_path: Path) -> None:
    """Spec behavior 5: ``.py`` only, case-insensitive, ``.pyi`` excluded."""
    _write(tmp_path, "a.py", "def (\n")
    _write(tmp_path, "b.PY", "def (\n")
    _write(tmp_path, "c.pyi", "def (\n")
    _write(tmp_path, "d.txt", "def (\n")
    rels = {_relpath(tmp_path, s) for s in _syntax().collect(tmp_path)}
    assert rels == {"a.py", "b.PY"}, (
        "syntax_error must scan .py case-insensitively while excluding .pyi and "
        f"non-Python suffixes; got {sorted(r for r in rels if r)!r}"
    )


def test_b05_syntax_error_skips_a_file_over_max_read_bytes(tmp_path: Path) -> None:
    """Spec behavior 5: ``syntax_error`` still refuses to read past ``max_read_bytes``."""
    _write(tmp_path, "small.py", "def (\n")
    oversize = _write(tmp_path, "huge.py", "def (\n" + "#" * 400)
    collector = SyntaxErrorCollector(max_read_bytes=64)
    assert oversize.stat().st_size > collector.max_read_bytes, "fixture must exceed the cap"
    rels = {_relpath(tmp_path, s) for s in collector.collect(tmp_path)}
    assert rels == {"small.py"}, (
        "a .py file larger than max_read_bytes must be skipped; got "
        f"{sorted(r for r in rels if r)!r}"
    )


def test_b05_large_file_applies_no_suffix_restriction(tmp_path: Path) -> None:
    """Spec behavior 5: ``large_file`` is suffix-blind and ``min_bytes`` is inclusive."""
    _write_bytes(tmp_path, "exact.bin", MIN_BYTES)
    _write_bytes(tmp_path, "under.bin", MIN_BYTES - 1)
    _write_bytes(tmp_path, "noext", MIN_BYTES)
    _write_bytes(tmp_path, "code.py", MIN_BYTES)
    rels = {_relpath(tmp_path, s) for s in _large().collect(tmp_path)}
    assert rels == {"exact.bin", "noext", "code.py"}, (
        "large_file must flag any suffix (and none), must flag a file of exactly "
        f"min_bytes, and must not flag min_bytes-1; got {sorted(r for r in rels if r)!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 6: order and caps are the documented sort keys, unchanged
# ---------------------------------------------------------------------------


def test_b06_todos_order_is_relpath_then_lineno(tmp_path: Path) -> None:
    """Spec behavior 6: ascending ``(relpath, lineno)``, truncated AFTER sorting."""
    _write(tmp_path, "z.py", "# TODO: z1\n")
    _write(tmp_path, "a.py", "x = 1\n# TODO: a2\n# TODO: a3\n")
    full = [str(s.path) for s in _todo().collect(tmp_path)]
    assert full == ["a.py:2", "a.py:3", "z.py:1"], full
    clear_todo_memo()
    capped = [str(s.path) for s in TodoCollector(max_items=2).collect(tmp_path)]
    assert capped == ["a.py:2", "a.py:3"], (
        "the cap must keep the FIRST rows of the sorted order, so traversal order "
        f"cannot decide which signals survive; got {capped!r}"
    )


def test_b06_syntax_error_order_is_relpath(tmp_path: Path) -> None:
    """Spec behavior 6: ascending ``relpath``, truncated AFTER sorting."""
    for name in ("m.py", "a.py", "z.py"):
        _write(tmp_path, name, "def (\n")
    full = [_relpath(tmp_path, s) for s in _syntax().collect(tmp_path)]
    assert full == ["a.py", "m.py", "z.py"], full
    clear_parse_memo()
    capped = [_relpath(tmp_path, s) for s in SyntaxErrorCollector(max_items=2).collect(tmp_path)]
    assert capped == ["a.py", "m.py"], capped


def test_b06_large_file_order_is_size_desc_then_relpath(tmp_path: Path) -> None:
    """Spec behavior 6: descending size, ties broken by ascending forward-slashed relpath."""
    _write_bytes(tmp_path, "big.bin", 3_000)
    _write_bytes(tmp_path, "tieB.bin", 2_000)
    _write_bytes(tmp_path, "tieA.bin", 2_000)
    _write_bytes(tmp_path, "sub/tie.bin", 2_000)
    full = [_relpath(tmp_path, s) for s in _large().collect(tmp_path)]
    assert full == ["big.bin", "sub/tie.bin", "tieA.bin", "tieB.bin"], (
        "large_file must sort by descending size then ascending forward-slashed "
        f"relpath; got {full!r}"
    )
    capped = [
        _relpath(tmp_path, s)
        for s in LargeFileCollector(min_bytes=MIN_BYTES, max_items=2).collect(tmp_path)
    ]
    assert capped == ["big.bin", "sub/tie.bin"], capped


# ---------------------------------------------------------------------------
# Behavior 7: the library-consumer path is unaffected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,factory", THREE, ids=[n for n, _ in THREE])
def test_b07_scoped_and_unscoped_output_is_identical(
    workspace: Path, name: str, factory: Callable[[], Any]
) -> None:
    """Spec behavior 7: ``collect(root)`` with NO scope equals the scoped result.

    Full public projection (source/kind/summary/detail/path/weight/timestamp),
    order included -- the served order differs from ``os.walk``'s platform order,
    so this is where an order leak would show up.
    """
    unscoped = _projection(workspace, factory().collect(workspace))
    clear_walk_cache()
    clear_todo_memo()
    clear_parse_memo()
    with walk_scope():
        scoped = _projection(workspace, factory().collect(workspace))
    assert unscoped, f"{name} emitted nothing, so this comparison would be vacuous"
    assert scoped == unscoped, (
        f"{name} must be indistinguishable inside and outside a scope; "
        f"scoped={scoped!r} unscoped={unscoped!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 8: prune symbols follow the batch-3 precedent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", CONVERTED_NOW)
def test_b08_skip_dirs_is_not_named(module: str) -> None:
    """Spec behavior 8: the DIRECTORY rule is inherited, so ``_SKIP_DIRS`` is gone."""
    text = _source(module)
    assert text.count("_SKIP_DIRS") == 0, (
        f"{module} must not name _SKIP_DIRS any more (import or prose); found "
        f"{text.count('_SKIP_DIRS')} occurrence(s)"
    )


@pytest.mark.parametrize("module", CONVERTED_NOW)
def test_b08_is_hidden_is_retained(module: str) -> None:
    """Spec behavior 8: file-level policy stays at the call site, per batch 3."""
    text = _source(module)
    assert text.count("_is_hidden") >= 1, (
        f"{module} must KEEP _is_hidden -- the provider filters directories only, "
        "so dropping it would start reporting hidden files (behavior 4)"
    )


@pytest.mark.parametrize("module", CONVERTED_NOW)
def test_b08_import_os_is_removed(module: str) -> None:
    """Spec behavior 8: ``os.walk`` was the only ``os`` use, so the import goes."""
    text = _source(module)
    assert "import os" not in text, (
        f"{module} still imports os; os.walk was its only os.* reference, so the "
        "import must be removed rather than left dangling"
    )


# ---------------------------------------------------------------------------
# Behavior 9 / 10: the census helpers, derived from the code
#
# The domain is ``COLLECTORS_DIR.glob("*.py")``, the idiom already used by
# ``tests/test_iter187_behavior.py``. Every file it yields is TRACKED, so a
# fresh clone (the release re-verification) measures the same set; nothing here
# depends on gitignored local state.
# ---------------------------------------------------------------------------

ITER187: Final[Path] = REPO_ROOT / "tests" / "test_iter187_behavior.py"

# The ROADMAP char budget is deliberately NOT restated here -- see behavior 12.
ROADMAP_BUDGET_OWNER: Final[Path] = REPO_ROOT / "tests" / "test_roadmap_size_budget.py"
ROADMAP_HEADROOM_PIN: Final[Path] = REPO_ROOT / "tests" / "test_iter214_behavior.py"

_NUMBER_WORDS: Final[dict[str, int]] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
}

_ENUM_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<count>[A-Za-z]+) collector modules are served by the shared walk today"
    r"\s*--\s*(?P<names>[^.]+)\."
)
_REMAINDER_RE: Final[re.Pattern[str]] = re.compile(
    r"Exactly (?P<count>[A-Za-z]+) keep a traversal of their own"
    r"(?P<names>.*?)(?:\n|$)",
    re.DOTALL,
)


def _collector_modules() -> list[str]:
    modules = sorted(p.name for p in COLLECTORS_DIR.glob("*.py"))
    assert len(modules) >= 15, (
        f"census domain regression -- expected the collectors package; got {modules!r}"
    )
    return modules


def _stems(names: list[str]) -> set[str]:
    return {name[: -len(".py")] for name in names}


def _walk_callers() -> set[str]:
    """Collector module stems holding a ``dir_source.walk(`` call site."""
    return _stems(
        [
            name
            for name in _collector_modules()
            if "dir_source.walk(" in (COLLECTORS_DIR / name).read_text(encoding="utf-8")
        ]
    )


def _os_walkers() -> set[str]:
    """Collector module names still holding an ``os.walk(`` call site."""
    return {
        name
        for name in _collector_modules()
        if "os.walk(" in (COLLECTORS_DIR / name).read_text(encoding="utf-8")
    }


# ---------------------------------------------------------------------------
# Behavior 9: the existing equality pin is updated in THIS commit
# ---------------------------------------------------------------------------


def test_b09_exactly_three_collector_modules_still_own_a_walk() -> None:
    """Spec behavior 9: the walkers are the provider plus the two kept by design."""
    assert _os_walkers() == set(STILL_WALKING), (
        "after batch 4 exactly three collector modules may own an os.walk: the "
        "provider itself, filesystem (its _has_source peek early-returns) and "
        f"notes (a genuinely different prune). Got {sorted(_os_walkers())!r}"
    )


def test_b09_iter187_pin_is_renamed_and_states_no_stale_count() -> None:
    """Spec behavior 9: neither the pin's NAME nor its assertion says "six"."""
    text = ITER187.read_text(encoding="utf-8")
    assert "def test_exactly_three_collector_modules_still_walk(" in text, (
        "test_iter187_behavior.py must rename its equality pin to state THREE "
        "walkers; a name saying six is a stale count in this same commit"
    )
    stale = [
        line
        for line in text.splitlines()
        if line.lstrip().startswith("def ") and "six" in line
    ]
    assert stale == [], f"a test name still states the stale count six: {stale!r}"


def test_b09_iter187_converted_tuple_excludes_the_batch_4_modules() -> None:
    """Spec acceptance: the three new modules must NOT join ``CONVERTED``.

    That tuple's companion test requires ZERO mentions of ``_is_hidden``, which
    these three legitimately still need (behavior 8), so adding them would red
    the suite for a correct implementation.
    """
    text = ITER187.read_text(encoding="utf-8")
    match = re.search(r"^CONVERTED\s*=\s*\((?P<body>[^)]*)\)", text, re.MULTILINE)
    assert match is not None, "test_iter187_behavior.py must still define CONVERTED"
    listed = set(re.findall(r"\"([A-Za-z0-9_]+\.py)\"", match.group("body")))
    overlap = listed & set(CONVERTED_NOW)
    assert overlap == set(), (
        "the batch-4 modules keep _is_hidden, so joining iter187's CONVERTED "
        f"tuple would red its prune-symbol census: {sorted(overlap)!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 10: the README enumeration is corrected and BOUND to the code
# ---------------------------------------------------------------------------


def test_b10_readme_names_exactly_the_shared_walk_callers() -> None:
    """Spec behavior 10: two-sided -- reds on an unnamed conversion AND on an
    invented name."""
    match = _ENUM_RE.search(README.read_text(encoding="utf-8"))
    assert match is not None, (
        "README must keep a sentence of the form '<N> collector modules are "
        "served by the shared walk today -- ...'"
    )
    named = set(re.findall(r"`([a-z_]+)`", match.group("names")))
    expected = _walk_callers()
    assert named == expected, (
        "the README enumeration must name exactly the collector modules that call "
        f"dir_source.walk(. Unnamed conversions: {sorted(expected - named)!r}; "
        f"invented names: {sorted(named - expected)!r}"
    )


def test_b10_readme_count_word_matches_the_enumeration() -> None:
    """Spec behavior 10: the leading number word cannot drift from the set."""
    match = _ENUM_RE.search(README.read_text(encoding="utf-8"))
    assert match is not None
    word = match.group("count").lower()
    assert word in _NUMBER_WORDS, f"unrecognised count word {word!r}"
    expected = _walk_callers()
    assert _NUMBER_WORDS[word] == len(expected), (
        f"README says {word!r} ({_NUMBER_WORDS[word]}) collector modules are "
        f"served, but {len(expected)} call dir_source.walk(: {sorted(expected)!r}"
    )


def test_b10_readme_remainder_clause_names_the_two_kept_walkers() -> None:
    """Spec behavior 10: the second clause states the TRUE remainder."""
    match = _REMAINDER_RE.search(README.read_text(encoding="utf-8"))
    assert match is not None, (
        "README must keep a clause of the form 'Exactly <N> keep a traversal of "
        "their own'"
    )
    # The provider itself is not a "remaining walker"; it IS the shared walk.
    remainder = _stems(sorted(_os_walkers() - {"dir_source.py"}))
    word = match.group("count").lower()
    assert word in _NUMBER_WORDS, f"unrecognised count word {word!r}"
    assert _NUMBER_WORDS[word] == len(remainder), (
        f"README says {word!r} collectors keep their own traversal, but the code "
        f"has {len(remainder)}: {sorted(remainder)!r}"
    )
    named = set(re.findall(r"`([a-z_]+)`", match.group("names")))
    assert remainder <= named, (
        "the remainder clause must NAME every collector that still walks for "
        f"itself; missing {sorted(remainder - named)!r}"
    )
    invented = (named & _stems(_collector_modules())) - remainder
    assert invented == set(), (
        "the remainder clause names a collector module that does NOT own an "
        f"os.walk: {sorted(invented)!r}"
    )


def test_b10_readme_edit_is_below_the_human_owned_marker() -> None:
    """Spec acceptance: the portfolio intro is never restructured."""
    text = README.read_text(encoding="utf-8")
    # Spelled as an escape so this module stays ASCII (the ``test_iter181`` idiom):
    # the README marker uses an EM DASH, not the ``--`` the spec prose renders it as.
    marker = "PORTFOLIO INTRO \u2014 human-owned"
    assert marker in text, "the human-owned marker must survive verbatim"
    intro, _, below = text.partition(marker)
    assert "collector modules are served by the shared walk today" not in intro, (
        "the shared-walk enumeration must live BELOW the human-owned marker"
    )
    assert "collector modules are served by the shared walk today" in below


# ---------------------------------------------------------------------------
# Behavior 11: the false rationale is retired from dir_source.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", ("prunes ADDITIONALLY", "genuinely differs"))
def test_b11_the_false_rationale_is_gone_from_dir_source(phrase: str) -> None:
    """Spec behavior 11: neither phrase survives in ``collectors/dir_source.py``.

    WHY the domain is ONE FILE and not the package: an earlier draft banned both
    phrases anywhere under ``src/proactive_loop/``, on the premise that each
    occurred only in ``dir_source.py``. It did not. ``llm/providers.py`` used
    ``genuinely differs`` as ordinary English about per-vendor exception tuples,
    so the package-wide domain made an unrelated module edit one word for no
    reason and would have kept catching innocent prose forever. The false
    rationale that this test exists to retire was written in ``dir_source.py``,
    so ``dir_source.py`` is the correct and only scope.
    """
    path = COLLECTORS_DIR / "dir_source.py"
    assert phrase not in path.read_text(encoding="utf-8"), (
        f"the retired rationale {phrase!r} still appears in "
        f"{path.relative_to(REPO_ROOT)}"
    )


def test_b11_dir_source_records_the_real_reason_filesystem_is_not_a_caller() -> None:
    """Spec behavior 11: the recency test is a per-FILE ``st_mtime`` comparison."""
    text = _source("dir_source.py")
    assert "st_mtime" in text, (
        "dir_source.py must record that filesystem.py's recency test is a "
        "per-FILE st_mtime comparison, not a directory prune"
    )
    assert "per-FILE" in text or "per-file" in text, (
        "dir_source.py must say the recency test is applied per FILE, after the "
        "triple arrives, so it can never remove a directory"
    )


# ---------------------------------------------------------------------------
# Behavior 12: nothing else regresses -- the ROADMAP budget in particular
# ---------------------------------------------------------------------------


def test_b12_the_roadmap_budget_is_enforced_by_its_single_owner() -> None:
    """Spec behavior 12's ROADMAP clause, verified by DELEGATION on purpose.

    An earlier draft of this module asserted ``len(ROADMAP.md)`` against 40,000
    and a 4,000 floor directly. That is a SECOND opinion on a single-sourced
    number, and ``tests/test_iter172_behavior.py`` exists to forbid exactly it:
    its allowlist admits one module besides the owner, with a written reason. The
    duplicate reddened that census the moment this file became tracked -- which a
    full-suite run could not see while the file was still untracked, because the
    census domain is ``git ls-files``.

    So this test does not restate the budget. It asserts the two guards that DO
    bound the live document are present, and both run in this same suite:
    ``tests/test_roadmap_size_budget.py`` owns the sanctioned constants and
    ``tests/test_iter214_behavior.py`` pins the headroom floor whose breach cost
    iteration 247 a reviewer-approved iteration.
    """
    assert ROADMAP_BUDGET_OWNER.is_file(), (
        "the ROADMAP budget owner module is missing, so nothing bounds the "
        f"document: {ROADMAP_BUDGET_OWNER}"
    )
    owner_text = ROADMAP_BUDGET_OWNER.read_text(encoding="utf-8")
    for constant in ("ROADMAP_CHAR_LIMIT", "ROADMAP_CHAR_FLOOR"):
        assert constant in owner_text, (
            f"the budget owner no longer names {constant!r}; the sanctioned "
            "numbers moved and behavior 12 is no longer delegated to anything"
        )
    assert ROADMAP_HEADROOM_PIN.is_file(), (
        f"the headroom pin module is missing: {ROADMAP_HEADROOM_PIN}"
    )
    pin_text = ROADMAP_HEADROOM_PIN.read_text(encoding="utf-8")
    assert "MIN_HEADROOM" in pin_text, (
        "tests/test_iter214_behavior.py no longer names MIN_HEADROOM, so the "
        "headroom floor this iteration had to budget for is unguarded"
    )
