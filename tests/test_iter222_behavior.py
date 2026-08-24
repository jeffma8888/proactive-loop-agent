"""Black-box oracle for factory iteration 243 -- ONE shared re-entrant depth scope.

Feature under test: the twin hand-copied re-entrant cache scopes
``dir_source.walk_scope`` and ``text_source.scan_scope`` collapse onto a single
``collectors/base._depth_scope(scope, drop)`` context manager. Both public names
survive as thin delegations with their own docstrings, and each module keeps its
OWN cache state -- only the control flow is shared.

MODULE NAME (derived from the repo, never from the state dir). ``git ls-files
tests`` tops out at ``test_iter221_behavior.py`` and ``git cat-file -e
HEAD:tests/test_iter222_behavior.py`` fails, so 222 is the next free number. The
foundry state dir for this ship is ``iter-243``; naming a module from that
counter is how an already-shipped oracle gets overwritten, so the repo wins.

ISOLATION CONTRACT (honored, no exceptions). Every assertion below is derived
from this iteration's ``pm.md`` "Expected Behaviors" 1-6, from the conventions of
``tests/test_iter136_behavior.py`` (the text-scope oracle: autouse cache
isolation, the ``TEXT_CACHE_MAX_BYTES`` monkeypatch idiom) and
``tests/test_iter216_behavior.py`` (the walk-scope oracle: the two-sided source
census, the anti-vacuity domain assertion), and from RUNNING the public
interface to read signatures and stats keys. **No file under ``src/`` was read
as source text by a human, no engineer or reviewer note was opened, and no ``git
diff`` was consulted.** Behavior 1 parses tracked source with ``ast`` to COUNT
definition sites, which is a mechanical census, not design reading.

Offline and deterministic: ``tmp_path`` trees only, no network, no subprocess, no
wall-clock or timing assertion. Nothing asserts on docstring or help-text
INDENTATION -- only on non-emptiness -- so the 3.12/3.13 CI legs cannot diverge
on the compile-time docstring-dedent difference.

Coverage (numbered to match the spec's Expected Behaviors):

1. ``_depth_scope`` exists exactly ONCE at module level across
   ``src/proactive_loop/**/*.py`` and its owner is ``collectors/base.py``. The
   census is proven two-sided against SYNTHETIC module source text (a planted
   second definition makes it report 2; the same synthetic module without the
   duplicate reports 1), never by writing into the real package, and its real
   domain is asserted non-empty. The helper is then driven directly: it takes a
   ``dict[str, int]`` carrying ``"depth"`` plus a zero-argument callable, nests
   by depth, drops on BOTH edges, and re-raises unchanged.
2. Both public names survive: each still returns a context manager, keeps its own
   non-empty docstring and its ``Iterator[None]`` return annotation, and still
   shares work within its own scope (one traversal / one decode for two calls).
3. The two scopes are INDEPENDENT -- entering one never activates the other's
   cache, in both directions.
4. Empty on BOTH edges, per scope, and a body exception propagates unchanged.
5. Re-entrancy is by DEPTH, not by boolean: an inner scope's exit does not switch
   caching off for the outer scan, and the OUTERMOST exit does.
6. The activity counters survive scope exit (entries/bytes do not), and the
   explicit ``clear_*`` seams still zero every counter.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from pathlib import Path

import pytest

from proactive_loop.collectors import base, dir_source, text_source

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "proactive_loop"

# The one name this iteration hoists, and its intended sole owner.
HELPER = "_depth_scope"
OWNER = "collectors/base.py"

# Guards the census against a silently empty domain (an ``rglob`` that matches
# nothing reports "exactly one owner" just as happily as a correct tree does).
MIN_SOURCE_FILES = 20

# The two per-module bodies this hoist deletes were 7 statements each; nothing
# below depends on that number, it is recorded only to name what was removed.
SYNTHETIC_OWNER = '''
from contextlib import contextmanager


@contextmanager
def _depth_scope(scope, drop):
    """Synthetic stand-in used ONLY to prove the census is two-sided."""
    scope["depth"] += 1
    drop()
    try:
        yield
    finally:
        scope["depth"] -= 1
        drop()
'''

SYNTHETIC_DUPLICATE = SYNTHETIC_OWNER + '''

@contextmanager
def _depth_scope(scope, drop):
    """A planted SECOND definition -- the census must report 2 and fail."""
    yield
'''

SYNTHETIC_NESTED_ONLY = '''
def outer():
    def _depth_scope(scope, drop):
        """Nested, not module-level -- must NOT be counted."""
        yield
    return _depth_scope
'''


@pytest.fixture(autouse=True)
def _isolate_both_caches() -> Iterator[None]:
    """No test may inherit or leak either provider's entries or counters."""
    dir_source.clear_walk_cache()
    text_source.clear_text_cache()
    yield
    dir_source.clear_walk_cache()
    text_source.clear_text_cache()


def _count_module_level_defs(source: str, name: str) -> int:
    """Count module-level ``def``/``async def`` statements called ``name``."""
    return sum(
        1
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
    )


def _census() -> tuple[dict[str, int], int]:
    """Return {relative path: definition count} over tracked source, plus the domain size."""
    files = sorted(SRC.rglob("*.py"))
    sites = {}
    for path in files:
        count = _count_module_level_defs(path.read_text(encoding="utf-8"), HELPER)
        if count:
            sites[path.relative_to(SRC).as_posix()] = count
    return sites, len(files)


def _tree(root: Path) -> Path:
    """A small deterministic workspace: two dirs, three files."""
    (root / "pkg" / "sub").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (root / "pkg" / "sub" / "note.md").write_text("# note\n", encoding="utf-8")
    (root / "top.txt").write_text("hello\n", encoding="utf-8")
    return root


# ===========================================================================
# Behavior 1 --- the shared scope exists exactly once, and it behaves
# ===========================================================================
def test_b01a_depth_scope_is_defined_exactly_once_and_lives_in_collectors_base() -> None:
    sites, domain = _census()
    assert domain >= MIN_SOURCE_FILES, (
        f"census domain looks empty ({domain} file(s) under {SRC}); an empty domain "
        "would report 'exactly one owner' for a tree that has none"
    )
    assert sites == {OWNER: 1}, (
        f"{HELPER} must be defined once, in {OWNER}; census found {sites!r}. Two sites "
        "means the hoist left a copy behind; zero means it never landed"
    )


def test_b01b_census_is_two_sided_against_synthetic_source_text() -> None:
    """The census must FAIL on a planted duplicate, and pass without it."""
    assert _count_module_level_defs(SYNTHETIC_OWNER, HELPER) == 1, (
        "the census must count a single module-level definition as 1"
    )
    assert _count_module_level_defs(SYNTHETIC_DUPLICATE, HELPER) == 2, (
        "a planted SECOND definition must be counted -- otherwise behavior 1 is vacuous "
        "and a leftover copy would pass unnoticed"
    )
    assert _count_module_level_defs(SYNTHETIC_NESTED_ONLY, HELPER) == 0, (
        "a nested def is not a module-level owner and must not be counted"
    )


def test_b01c_owner_module_is_collectors_base_at_runtime() -> None:
    """A second, independent signal for the same fact: the runtime ``__module__``."""
    assert hasattr(base, HELPER), f"collectors.base must expose {HELPER}"
    assert base._depth_scope.__module__ == "proactive_loop.collectors.base", (
        f"unexpected owner module {base._depth_scope.__module__!r}"
    )
    assert (base._depth_scope.__doc__ or "").strip(), (
        "the shared helper owns a cache-correctness invariant, so it must document it"
    )


def test_b01d_helper_takes_a_depth_dict_and_a_zero_argument_drop() -> None:
    scope: dict[str, int] = {"depth": 0}
    depth_at_drop: list[int] = []

    with base._depth_scope(scope, lambda: depth_at_drop.append(scope["depth"])):
        assert scope["depth"] == 1, f"entry must increment the depth; got {scope!r}"
    assert scope["depth"] == 0, f"exit must restore the depth; got {scope!r}"
    assert depth_at_drop == [1, 0], (
        "the invariant is 'empty on BOTH edges': drop must run once after the entry "
        f"increment and once after the exit decrement; observed {depth_at_drop!r}"
    )


def test_b01e_helper_nests_by_depth_and_never_goes_negative() -> None:
    scope: dict[str, int] = {"depth": 0}
    drops: list[int] = []

    def drop() -> None:
        drops.append(scope["depth"])

    with base._depth_scope(scope, drop):
        with base._depth_scope(scope, drop):
            assert scope["depth"] == 2, f"two nested scopes must reach depth 2; got {scope!r}"
        assert scope["depth"] == 1, (
            f"the INNER exit must leave the outer scope active; got {scope!r}"
        )
    assert scope["depth"] == 0, f"the outermost exit must reach depth 0; got {scope!r}"
    assert drops == [1, 2, 1, 0], (
        f"every edge of both scopes must drop; observed depths {drops!r}"
    )


def test_b01f_helper_reraises_the_body_exception_unchanged_and_still_drops() -> None:
    scope: dict[str, int] = {"depth": 0}
    drops: list[int] = []

    with pytest.raises(RuntimeError, match="^boom$"):
        with base._depth_scope(scope, lambda: drops.append(scope["depth"])):
            raise RuntimeError("boom")
    assert scope["depth"] == 0, f"a raising body must still restore the depth; got {scope!r}"
    assert drops == [1, 0], (
        f"a raising body must still drop on the exit edge; observed {drops!r}"
    )


# ===========================================================================
# Behavior 2 --- both public names survive unchanged and still share
# ===========================================================================
@pytest.mark.parametrize(
    ("name", "factory"),
    [("walk_scope", dir_source.walk_scope), ("scan_scope", text_source.scan_scope)],
)
def test_b02a_public_scopes_still_return_a_context_manager_with_their_own_docstring(
    name: str, factory: object
) -> None:
    manager = factory()  # type: ignore[operator]
    try:
        assert hasattr(manager, "__enter__") and hasattr(manager, "__exit__"), (
            f"{name}() must return a context manager; got {manager!r}"
        )
        assert (factory.__doc__ or "").strip(), (  # type: ignore[attr-defined]
            f"{name} must keep its OWN docstring after delegating its control flow"
        )
        annotation = inspect.signature(factory).return_annotation  # type: ignore[arg-type]
        assert annotation == "Iterator[None]", (
            f"{name}'s public return annotation moved to {annotation!r}; the decorated "
            "@contextmanager form must survive the hoist (a bare `return helper(...)` "
            "would force AbstractContextManager[None] instead)"
        )
        assert inspect.signature(factory).parameters == {}, (  # type: ignore[arg-type]
            f"{name} must stay zero-argument"
        )
    finally:
        close = getattr(manager, "close", None)
        if close is not None:
            close()


def test_b02b_two_walks_inside_one_walk_scope_traverse_once(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    with dir_source.walk_scope():
        first = dir_source.walk(root)
        second = dir_source.walk(root)
        stats = dir_source.walk_cache_stats()
    assert first == second, "a cached traversal must return the same listing"
    assert (stats["misses"], stats["hits"]) == (1, 1), (
        f"two walks in one scope must be one traversal plus one hit; got {stats!r}"
    )


def test_b02c_two_reads_inside_one_scan_scope_decode_once(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    target = root / "pkg" / "mod.py"
    with text_source.scan_scope():
        first = text_source.read_text(target, strict=True)
        second = text_source.read_text(target, strict=True)
        stats = text_source.text_cache_stats()
    assert first == second == "x = 1\n"
    assert (stats["misses"], stats["hits"]) == (1, 1), (
        f"two reads of one path in one scope must decode once; got {stats!r}"
    )


# ===========================================================================
# Behavior 3 --- the two scopes are INDEPENDENT (shared control flow, not state)
# ===========================================================================
def test_b03a_scan_scope_alone_does_not_activate_the_walk_cache(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    with text_source.scan_scope():
        dir_source.walk(root)
        dir_source.walk(root)
        stats = dir_source.walk_cache_stats()
    assert (stats["hits"], stats["misses"]) == (0, 2), (
        f"scan_scope must never arm the walk cache; got {stats!r}"
    )
    assert stats["entries"] == 0, f"nothing may be retained outside a walk scope; {stats!r}"


def test_b03b_walk_scope_alone_does_not_activate_the_text_cache(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    target = root / "pkg" / "sub" / "note.md"
    with dir_source.walk_scope():
        text_source.read_text(target, strict=True)
        text_source.read_text(target, strict=True)
        stats = text_source.text_cache_stats()
    assert (stats["hits"], stats["misses"]) == (0, 2), (
        f"walk_scope must never arm the text cache; got {stats!r}"
    )
    assert stats["entries"] == 0, f"nothing may be retained outside a scan scope; {stats!r}"


# ===========================================================================
# Behavior 4 --- empty on BOTH edges, and the exception propagates untouched
# ===========================================================================
def test_b04a_walk_scope_is_empty_on_entry_and_after_exit(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    with dir_source.walk_scope():
        assert dir_source.walk_cache_stats()["entries"] == 0, "a scope must start empty"
        dir_source.walk(root)
        assert dir_source.walk_cache_stats()["entries"] == 1, (
            f"the traversal should be retained inside the scope; {dir_source.walk_cache_stats()!r}"
        )
    assert dir_source.walk_cache_stats()["entries"] == 0, "the scope must empty on exit"
    with dir_source.walk_scope():
        assert dir_source.walk_cache_stats()["entries"] == 0, (
            "a SECOND scope must never serve a previous scan's entries"
        )


def test_b04b_scan_scope_is_empty_on_entry_and_after_exit(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    target = root / "top.txt"
    with text_source.scan_scope():
        assert text_source.text_cache_stats()["entries"] == 0, "a scope must start empty"
        text_source.read_text(target, strict=True)
        assert text_source.text_cache_stats()["entries"] == 1
    assert text_source.text_cache_stats()["entries"] == 0, "the scope must empty on exit"
    with text_source.scan_scope():
        assert text_source.text_cache_stats()["entries"] == 0, (
            "a SECOND scope must never serve a previous scan's entries"
        )


def test_b04c_walk_scope_body_exception_propagates_unchanged_and_still_empties(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path)
    with pytest.raises(RuntimeError, match="^boom$"):
        with dir_source.walk_scope():
            dir_source.walk(root)
            assert dir_source.walk_cache_stats()["entries"] == 1
            raise RuntimeError("boom")
    stats = dir_source.walk_cache_stats()
    assert stats["entries"] == 0, (
        f"a raising body must not leave a populated cache behind; got {stats!r}"
    )


def test_b04d_scan_scope_body_exception_propagates_unchanged_and_still_empties(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path)
    with pytest.raises(RuntimeError, match="^boom$"):
        with text_source.scan_scope():
            text_source.read_text(root / "top.txt", strict=True)
            assert text_source.text_cache_stats()["entries"] == 1
            raise RuntimeError("boom")
    stats = text_source.text_cache_stats()
    assert stats["entries"] == 0, (
        f"a raising body must not leave a populated cache behind; got {stats!r}"
    )
    assert stats["bytes"] == 0, f"the retained byte total must go with the entries; {stats!r}"


# ===========================================================================
# Behavior 5 --- re-entrancy by DEPTH, not by boolean
# ===========================================================================
def test_b05a_inner_walk_scope_exit_does_not_switch_the_outer_scan_off(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    with dir_source.walk_scope():
        with dir_source.walk_scope():
            dir_source.walk(root)
        before = dir_source.walk_cache_stats()
        dir_source.walk(root)
        dir_source.walk(root)
        after = dir_source.walk_cache_stats()
    assert after["hits"] - before["hits"] == 1, (
        "after an INNER scope exits, the outer scan must still share one traversal "
        f"between two walks; hits went {before['hits']} -> {after['hits']}"
    )
    assert after["misses"] - before["misses"] == 1, (
        "the inner exit drops entries, so exactly one of the two further walks must "
        f"re-traverse; misses went {before['misses']} -> {after['misses']}"
    )


def test_b05b_inner_scan_scope_exit_does_not_switch_the_outer_scan_off(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    target = root / "pkg" / "mod.py"
    with text_source.scan_scope():
        with text_source.scan_scope():
            text_source.read_text(target, strict=True)
        before = text_source.text_cache_stats()
        text_source.read_text(target, strict=True)
        text_source.read_text(target, strict=True)
        after = text_source.text_cache_stats()
    assert after["hits"] - before["hits"] == 1, (
        "after an INNER scope exits, the outer scan must still decode once for two "
        f"reads; hits went {before['hits']} -> {after['hits']}"
    )
    assert after["misses"] - before["misses"] == 1, (
        f"exactly one re-decode is expected; misses went "
        f"{before['misses']} -> {after['misses']}"
    )


def test_b05c_after_the_outermost_scope_exits_caching_is_off_again(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    target = root / "pkg" / "mod.py"
    with dir_source.walk_scope():
        with dir_source.walk_scope():
            dir_source.walk(root)
    with text_source.scan_scope():
        with text_source.scan_scope():
            text_source.read_text(target, strict=True)

    walk_before = dir_source.walk_cache_stats()
    dir_source.walk(root)
    walk_after = dir_source.walk_cache_stats()
    assert walk_after["misses"] - walk_before["misses"] == 1, (
        "a walk after the OUTERMOST exit must miss -- a depth counter that never "
        f"reached 0 would keep caching on; {walk_before!r} -> {walk_after!r}"
    )
    assert walk_after["hits"] == walk_before["hits"]
    assert walk_after["entries"] == 0, f"no entry may be retained; {walk_after!r}"

    text_before = text_source.text_cache_stats()
    text_source.read_text(target, strict=True)
    text_after = text_source.text_cache_stats()
    assert text_after["misses"] - text_before["misses"] == 1, (
        f"a read after the OUTERMOST exit must miss; {text_before!r} -> {text_after!r}"
    )
    assert text_after["hits"] == text_before["hits"]
    assert text_after["entries"] == 0, f"no entry may be retained; {text_after!r}"


# ===========================================================================
# Behavior 6 --- the activity counters survive scope exit; clear_* zeroes them
# ===========================================================================
def test_b06a_walk_counters_survive_the_exit_while_entries_do_not(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    with dir_source.walk_scope():
        dir_source.walk(root)
        dir_source.walk(root)
    stats = dir_source.walk_cache_stats()
    assert stats["hits"] >= 1 and stats["misses"] >= 1, (
        f"the drop clears retained ENTRIES only, never the activity counters; {stats!r}"
    )
    assert stats["entries"] == 0, f"entries must be cleared; {stats!r}"
    dir_source.clear_walk_cache()
    assert dir_source.walk_cache_stats() == {"hits": 0, "misses": 0, "entries": 0, "dirs": 0}, (
        f"clear_walk_cache() must zero every counter; got {dir_source.walk_cache_stats()!r}"
    )


def test_b06b_text_counters_survive_the_exit_while_bytes_do_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tree(tmp_path)
    target = root / "pkg" / "mod.py"
    monkeypatch.setattr(text_source, "TEXT_CACHE_MAX_BYTES", 3)
    with text_source.scan_scope():
        text_source.read_text(target, strict=True)
        text_source.read_text(target, strict=True)
        inside = text_source.text_cache_stats()
    stats = text_source.text_cache_stats()
    assert inside["declined"] >= 1, (
        "the fixture is meant to exceed a 3-byte budget so `declined` is genuinely "
        f"non-zero before the exit; got {inside!r}"
    )
    assert stats["hits"] == inside["hits"] and stats["misses"] == inside["misses"], (
        f"hits/misses must survive the exit; {inside!r} -> {stats!r}"
    )
    assert stats["declined"] == inside["declined"] >= 1, (
        f"`declined` must survive the exit too; {inside!r} -> {stats!r}"
    )
    assert stats["bytes"] == 0, f"the retained byte total must be cleared; {stats!r}"
    assert stats["entries"] == 0, f"entries must be cleared; {stats!r}"
    text_source.clear_text_cache()
    assert text_source.text_cache_stats() == {
        "hits": 0,
        "misses": 0,
        "entries": 0,
        "bytes": 0,
        "declined": 0,
    }, f"clear_text_cache() must zero every counter; got {text_source.text_cache_stats()!r}"


# ===========================================================================
# Behavior 4/5 (abandonment edge) --- the invariant must survive a scope that
# is never exited normally.
#
# The spec's "Why" names three ways a scan can end early -- "a raising
# collector, a ``KeyboardInterrupt`` mid-scan or an early ``return``" -- and
# requires the cache to be empty on BOTH edges regardless. A ``with`` statement
# always calls ``__exit__``, so it cannot reach the last of those: the case
# where the manager's generator is ABANDONED and closed instead. Delegating one
# ``@contextmanager`` to another puts TWO generator frames on that unwind path,
# so this edge is the one the hoist could plausibly change. Nothing else in the
# suite drives it (no other test file mentions ``gen.close`` or ``__enter__``).
# ===========================================================================
def test_b04e_helper_drops_on_both_edges_when_its_generator_is_abandoned() -> None:
    """Closing the generator instead of exiting must still run the exit edge."""
    scope: dict[str, int] = {"depth": 0}
    drops: list[int] = []

    manager = base._depth_scope(scope, lambda: drops.append(scope["depth"]))
    manager.__enter__()
    assert scope["depth"] == 1, f"entry must increment the depth; got {scope!r}"
    manager.gen.close()  # type: ignore[attr-defined]
    assert scope["depth"] == 0, (
        f"an ABANDONED scope must still restore the depth; got {scope!r}"
    )
    assert drops == [1, 0], (
        f"both edges must drop even when the generator is closed; observed {drops!r}"
    )


def test_b04f_walk_scope_empties_when_its_generator_is_abandoned(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    manager = dir_source.walk_scope()
    manager.__enter__()
    dir_source.walk(root)
    assert dir_source.walk_cache_stats()["entries"] == 1, (
        "the fixture must actually populate the cache, or the assertion below is vacuous"
    )
    manager.gen.close()  # type: ignore[attr-defined]
    assert dir_source.walk_cache_stats()["entries"] == 0, (
        "an abandoned walk scope must not leave a populated cache behind; "
        f"got {dir_source.walk_cache_stats()!r}"
    )
    before = dir_source.walk_cache_stats()
    dir_source.walk(root)
    after = dir_source.walk_cache_stats()
    assert after["misses"] - before["misses"] == 1, (
        "caching must be OFF again after the abandoned scope -- a depth counter left "
        f"above 0 would keep it armed; {before!r} -> {after!r}"
    )


def test_b04g_scan_scope_empties_when_its_generator_is_abandoned(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    target = root / "pkg" / "mod.py"
    manager = text_source.scan_scope()
    manager.__enter__()
    text_source.read_text(target, strict=True)
    assert text_source.text_cache_stats()["entries"] == 1, (
        "the fixture must actually populate the cache, or the assertion below is vacuous"
    )
    manager.gen.close()  # type: ignore[attr-defined]
    stats = text_source.text_cache_stats()
    assert stats["entries"] == 0, (
        f"an abandoned scan scope must not leave entries behind; got {stats!r}"
    )
    assert stats["bytes"] == 0, f"the retained byte total must go with them; {stats!r}"
    before = text_source.text_cache_stats()
    text_source.read_text(target, strict=True)
    after = text_source.text_cache_stats()
    assert after["misses"] - before["misses"] == 1, (
        f"caching must be OFF again after the abandoned scope; {before!r} -> {after!r}"
    )


@pytest.mark.parametrize(
    ("name", "factory", "stats", "populate"),
    [
        (
            "walk_scope",
            dir_source.walk_scope,
            dir_source.walk_cache_stats,
            lambda root: dir_source.walk(root),
        ),
        (
            "scan_scope",
            text_source.scan_scope,
            text_source.text_cache_stats,
            lambda root: text_source.read_text(root / "pkg" / "mod.py", strict=True),
        ),
    ],
)
def test_b05d_explicit_enter_exit_pair_balances_for_each_public_scope(
    name: str,
    factory: object,
    stats: object,
    populate: object,
    tmp_path: Path,
) -> None:
    """A ``with`` statement hides both edges behind one construct; drive them apart.

    Two nested MANUAL pairs must behave exactly like nested ``with`` blocks: the
    inner ``__exit__`` drops the entries but leaves the OUTER scope armed, and only
    the outermost ``__exit__`` disarms it. Every assertion is preceded by the
    precondition that makes it non-vacuous (an ``entries == 0`` claim proves nothing
    about a cache that was never populated).
    """
    root = _tree(tmp_path)
    outer = factory()  # type: ignore[operator]
    inner = factory()  # type: ignore[operator]

    outer.__enter__()
    inner.__enter__()
    populate(root)  # type: ignore[operator]
    assert stats()["entries"] == 1, (  # type: ignore[operator]
        f"{name}: the fixture must populate the cache inside the inner pair, or the "
        f"drop assertion below is vacuous; got {stats()!r}"  # type: ignore[operator]
    )

    assert inner.__exit__(None, None, None) in (None, False), (
        f"{name}'s __exit__ must not claim to suppress an exception"
    )
    assert stats()["entries"] == 0, (  # type: ignore[operator]
        f"{name}: the inner exit must drop the entries; got {stats()!r}"  # type: ignore[operator]
    )

    before = stats()  # type: ignore[operator]
    populate(root)  # type: ignore[operator]
    populate(root)  # type: ignore[operator]
    after = stats()  # type: ignore[operator]
    assert after["hits"] - before["hits"] == 1, (
        f"{name}: the OUTER pair must still be armed after the inner __exit__ -- a "
        f"boolean flag would have switched caching off; {before!r} -> {after!r}"
    )

    assert outer.__exit__(None, None, None) in (None, False)
    assert stats()["entries"] == 0, (  # type: ignore[operator]
        f"{name}: the outermost exit must leave the cache empty; got {stats()!r}"  # type: ignore[operator]
    )
    disarmed_before = stats()  # type: ignore[operator]
    populate(root)  # type: ignore[operator]
    disarmed_after = stats()  # type: ignore[operator]
    assert disarmed_after["misses"] - disarmed_before["misses"] == 1, (
        f"{name}: caching must be OFF after the outermost manual exit; "
        f"{disarmed_before!r} -> {disarmed_after!r}"
    )


# ===========================================================================
# Acceptance criterion --- each surviving wrapper's docstring must NAME the
# shared owner, so a reader of either module is pointed at the single place the
# control flow now lives. (Public observable: ``__doc__``. Compared after
# ``inspect.cleandoc`` so the 3.12/3.13 docstring-dedent difference is
# irrelevant, and no indentation or line count is asserted.)
# ===========================================================================
@pytest.mark.parametrize(
    ("name", "factory"),
    [("walk_scope", dir_source.walk_scope), ("scan_scope", text_source.scan_scope)],
)
def test_b02d_each_wrapper_docstring_names_the_shared_owner(
    name: str, factory: object
) -> None:
    doc = inspect.cleandoc(factory.__doc__ or "")  # type: ignore[attr-defined]
    assert doc, f"{name} must keep its own docstring"
    assert HELPER in doc, (
        f"{name}'s docstring must name {HELPER} so the reader is sent to the single "
        f"owner of the control flow; got {doc!r}"
    )
