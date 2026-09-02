"""Black-box behavior tests for factory iteration 265 (ROADMAP #262) --- the
permissive ``root + direct children`` directory walk becomes ONE staticmethod on
``BaseCollector``, ``GitStateCollector`` / ``GitStashCollector`` delete their
hand-copied bodies and inherit it, and ``WorkingTreeCollector``'s ``sorted()`` +
``.git``-gated + deduplicated walk stays as the single justified override.

WHY this module exists next to ``tests/test_iter154_behavior.py``: that module was
re-keyed by this iteration and now proves the STRUCTURE (an ``ast`` census over the
collectors package plus object identity plus a docstring-token ban). It does not
pin what the surviving walk actually DOES. A hoist that dropped the "no ``sorted()``,
no dedup, one level only" semantics, or that started swallowing a real error, would
leave every structural claim green. So this module pins the SEMANTICS, and it pins
them without depending on the ambient filesystem's enumeration order: the order,
the absence of deduplication and the ``OSError`` fallback are all driven through a
``Path`` subclass whose ``iterdir`` is under the test's control, so the same
assertions hold on any filesystem.

ISOLATION CONTRACT (honored): every assertion here was written from this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
tree, and the product's OBSERVABLE behavior obtained by RUNNING it. **No file under
``src/`` was read, no engineer / reviewer / fix note was consulted, and no ``git
diff`` was inspected.** Nothing here transcribes implementation text: the walk is
called and its return value compared against a listing the test itself produced,
and the docstring claims are checked as TOKENS on the live ``__doc__``.

Offline and deterministic: no network, no API key, no ``git`` binary. Every fixture
is a directory tree under pytest's ``tmp_path``; nothing is written inside the
product repo.

Python-version note (iteration 145 was reverted for this class of bug): CPython
3.13 strips the common leading indent from docstrings at compile time and 3.12 does
not, so every docstring assertion runs through ``inspect.cleandoc`` and asserts on
TOKENS only --- never on indentation, line breaks or exact wording. The ``Path``
subclasses below derive from ``type(Path())`` (the concrete flavour class) rather
than from ``Path`` itself, because subclassing ``Path`` directly is only supported
from 3.13 while the CI matrix also runs 3.12.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import proactive_loop.collectors as collectors_pkg
from proactive_loop.collectors import (
    GitActivityCollector,
    GitStashCollector,
    GitStateCollector,
    WorkingTreeCollector,
)
from proactive_loop.collectors.base import BaseCollector

HELPER = "_dirs_to_scan"

#: The concrete flavour class (``PosixPath`` here). See the module docstring.
_PathBase: type[Path] = type(Path())

#: The banned self-description: a docstring deferring to a sibling collector.
_PARITY_TOKEN = "identical"

#: Behavior 8 fixture names. Deliberately long and unusual so a substring search
#: over collector output cannot be satisfied by an ambient path component.
_REPO_CHILD = "childrepo"
_NON_REPO_CHILD = "plaindir"
_GRANDPARENT = "outerdir"
_GRANDCHILD_REPO = "grandrepo"

#: The two collectors that MIGRATED to the inherited walk.
_MIGRATED = (GitStateCollector, GitStashCollector)


# ---------------------------------------------------------------------------
# Fixtures and doubles
# ---------------------------------------------------------------------------


class _ReversedDoubledPath(_PathBase):  # type: ignore[misc,valid-type]
    """A directory whose ``iterdir`` yields every entry TWICE, reverse-name order.

    This is the whole reason the order and deduplication claims are testable at
    all: a real directory cannot contain a duplicate entry, and its enumeration
    order is the filesystem's business, not the test's. Driving the walk through
    this double makes both claims deterministic on any machine --- the permissive
    walk must echo this order and keep both copies, while the gated override must
    ``sorted()`` it and collapse the copies.
    """

    def iterdir(self) -> Iterator[Path]:
        entries = sorted(super().iterdir(), key=lambda p: p.name, reverse=True)
        return iter(entries + entries)


class _UnreadableDirPath(_PathBase):  # type: ignore[misc,valid-type]
    """A directory whose ``iterdir`` raises ``OSError`` (Behavior 2)."""

    def iterdir(self) -> Iterator[Path]:
        raise OSError(13, "Permission denied")


def _walk_fixture(tmp_path: Path) -> Path:
    """Three child dirs, one file, and one grandchild dir (Behaviors 1 and 2)."""
    root = tmp_path / "walkroot"
    root.mkdir()
    for name in ("bdir", "adir", "cdir"):
        (root / name).mkdir()
    (root / "afile.txt").write_text("not a directory\n", encoding="utf-8")
    (root / "adir" / "grandchild").mkdir()
    return root


def _repo_marker(directory: Path) -> None:
    """Make *directory* look like a git repo, entirely offline.

    A ``.git`` directory holding an in-flight merge marker (what the git-state
    collector reads) and a one-entry stash reflog (what the git-stash collector
    reads). No ``git`` binary is involved, so these tests never skip.
    """
    git = directory / ".git"
    git.mkdir(parents=True, exist_ok=True)
    (git / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
    refs = git / "logs" / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "stash").write_text(
        f"{'0' * 40} {'1' * 40} T <t@t> 1700000000 +0000\t"
        f"On main: wip in {directory.name}\n",
        encoding="utf-8",
    )


def _workspace(tmp_path: Path, plain_child_is_a_repo: bool = False) -> Path:
    """The spec's Behavior-8 fixture, plus a repo one level TOO DEEP.

    ``root`` and ``childrepo/`` are repos; ``plaindir/`` is not (unless the control
    flips it); and ``outerdir/grandrepo/`` is a repo a grandchild deep, which the
    one-level-only rule means no collector may ever surface.
    """
    root = tmp_path / "ws"
    root.mkdir()
    _repo_marker(root)
    _repo_marker(root / _REPO_CHILD)
    plain = root / _NON_REPO_CHILD
    plain.mkdir()
    (plain / "notes.txt").write_text("hello\n", encoding="utf-8")
    if plain_child_is_a_repo:
        _repo_marker(plain)
    (root / _GRANDPARENT).mkdir()
    _repo_marker(root / _GRANDPARENT / _GRANDCHILD_REPO)
    return root


def _gated_fixture(tmp_path: Path) -> Path:
    """Two ``.git`` children and one plain child (Behavior 9)."""
    root = tmp_path / "gated"
    root.mkdir()
    _repo_marker(root)
    _repo_marker(root / "bchild")
    _repo_marker(root / "achild")
    (root / _NON_REPO_CHILD).mkdir()
    return root


def _child_dirs_in_iterdir_order(root: Path) -> list[Path]:
    """Exactly what Behavior 1 says the tail of the walk must be."""
    return [child for child in root.iterdir() if child.is_dir()]


def _names(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


def _rel(value: object, root: Path) -> str:
    """Render *value* root-relative, so the ambient ``tmp_path`` (which the test
    does not control) can neither satisfy nor break a substring assertion."""
    text = "" if value is None else str(value)
    prefix = str(root)
    return text[len(prefix) :] if text.startswith(prefix) else text


def _haystack(signals: list[Any], root: Path) -> str:
    """Every observable string a signal exposes, root-relative."""
    parts: list[str] = []
    for signal in signals:
        parts.append(str(signal.summary))
        parts.append(str(getattr(signal, "detail", "") or ""))
        parts.append(_rel(signal.path, root))
    return " | ".join(parts)


def _shapes(signals: list[Any]) -> list[tuple[str, str, str | None]]:
    return [(s.kind, s.summary, s.path) for s in signals]


def _cleandoc(doc: str | None) -> str:
    """3.12/3.13-safe docstring normaliser (see the module docstring's note)."""
    return "" if doc is None else inspect.cleandoc(doc)


# ---------------------------------------------------------------------------
# Behavior 1 -- root, then every direct child dir, in iterdir order, unsorted
#               and undeduplicated; one level only
# ---------------------------------------------------------------------------


def test_b01_walk_is_root_then_direct_child_dirs_in_live_iterdir_order(
    tmp_path: Path,
) -> None:
    root = _walk_fixture(tmp_path)
    expected = [root, *_child_dirs_in_iterdir_order(root)]
    result = BaseCollector._dirs_to_scan(root)
    assert isinstance(result, list), f"expected a list, got {type(result).__name__}"
    assert len(expected) > 1, "fixture produced no child directories -- vacuous"
    assert result == expected, (
        f"the walk did not return root followed by every direct child directory in "
        f"iterdir order:\n  got      {_names(result)}\n  expected {_names(expected)}"
    )
    assert result[0] == root, f"the walk must start at root, got {result[0]}"


def test_b01_order_is_iterdir_order_and_duplicates_survive(tmp_path: Path) -> None:
    """Reverse-order, doubled ``iterdir`` -> the walk echoes it verbatim.

    Proves all three of "in ``iterdir`` order", "NOT sorted" and "NOT
    deduplicated" from one double, without depending on how the real filesystem
    happens to enumerate.
    """
    root = _ReversedDoubledPath(_walk_fixture(tmp_path))
    dirs_reverse = ["cdir", "bdir", "adir"]
    result = BaseCollector._dirs_to_scan(root)
    assert _names(result) == [root.name, *dirs_reverse, *dirs_reverse], (
        "the walk re-ordered or deduplicated its input: expected root then the "
        f"doubled reverse-name listing {dirs_reverse * 2}, got {_names(result)}"
    )
    tail = _names(result)[1:]
    assert tail != sorted(tail), "the walk sorted its children; it must not"
    assert len(tail) != len(set(tail)), "the walk deduplicated its children; it must not"


def test_b01_files_are_excluded_and_the_directory_control_is_present(
    tmp_path: Path,
) -> None:
    root = _walk_fixture(tmp_path)
    names = _names(BaseCollector._dirs_to_scan(root))
    assert "afile.txt" not in names, f"a plain file entered the walk: {names}"
    assert "adir" in names, (
        f"the positive control (a real child directory) is missing, so the file "
        f"exclusion above proves nothing: {names}"
    )


def test_b01_nesting_is_one_level_only(tmp_path: Path) -> None:
    root = _walk_fixture(tmp_path)
    result = BaseCollector._dirs_to_scan(root)
    names = _names(result)
    assert "grandchild" not in names, (
        f"a grandchild directory was returned; the walk must be one level only: {names}"
    )
    assert "adir" in names, (
        "the grandchild's PARENT is missing from the walk, so the one-level "
        f"assertion is vacuous: {names}"
    )
    assert (root / "adir" / "grandchild").is_dir(), "fixture lost its grandchild dir"


def test_b01_signature_and_staticmethod_shape() -> None:
    static = inspect.getattr_static(BaseCollector, HELPER)
    assert isinstance(static, staticmethod), (
        f"{HELPER} must be a @staticmethod on BaseCollector, got {type(static).__name__}"
    )
    params = list(inspect.signature(BaseCollector._dirs_to_scan).parameters)
    assert params == ["root"], f"expected a single 'root' parameter, got {params}"


# ---------------------------------------------------------------------------
# Behavior 2 -- an unreadable directory degrades to [root], it does not raise
# ---------------------------------------------------------------------------


def test_b02_oserror_from_iterdir_degrades_to_root_only(tmp_path: Path) -> None:
    root = _UnreadableDirPath(_walk_fixture(tmp_path))
    result = BaseCollector._dirs_to_scan(root)
    assert result == [root], (
        f"an unreadable directory must yield exactly [root], got {_names(result)}"
    )


def test_b02_the_oserror_control_would_otherwise_return_children(
    tmp_path: Path,
) -> None:
    """Same fixture WITHOUT the raising double: the walk returns more than root.

    Without this control, Behavior 2 would also pass for a walk that always
    returned ``[root]`` and never listed anything.
    """
    plain = _walk_fixture(tmp_path)
    assert len(BaseCollector._dirs_to_scan(plain)) > 1, (
        "the fixture yields no children even when readable, so the OSError "
        "assertion cannot distinguish a fallback from a walk that never lists"
    )
    with pytest.raises(OSError):
        _UnreadableDirPath(plain).iterdir()


# ---------------------------------------------------------------------------
# Behaviors 3 and 4 -- inheritance by IDENTITY; only two owners, at runtime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("collector", _MIGRATED, ids=lambda c: c.__name__)
def test_b03_migrated_collectors_inherit_the_base_walk_by_identity(
    collector: type[BaseCollector],
) -> None:
    assert collector._dirs_to_scan is BaseCollector._dirs_to_scan, (
        f"{collector.__name__}.{HELPER} is not BaseCollector's object itself -- it "
        "has been shadowed by a fresh definition, so the duplicate is back"
    )


@pytest.mark.parametrize("collector", _MIGRATED, ids=lambda c: c.__name__)
def test_b04_migrated_collectors_own_no_definition_of_their_own(
    collector: type[BaseCollector],
) -> None:
    assert HELPER not in vars(collector), (
        f"{collector.__name__} still defines {HELPER} in its own class namespace; "
        "the permissive walk must be inherited, not copied"
    )


def test_b04_exactly_two_collector_classes_own_the_helper() -> None:
    """A runtime census over the IMPORTED package, complementing the ast census.

    ``tests/test_iter154_behavior.py`` counts ``FunctionDef`` nodes per module
    FILE. This counts owners per CLASS at import time, so it also catches a copy
    that arrives by assignment or by a second class in an already-blessed module.
    """
    classes = [
        obj
        for name in dir(collectors_pkg)
        if isinstance(obj := getattr(collectors_pkg, name), type)
        and issubclass(obj, BaseCollector)
    ]
    assert len(classes) > 3, f"census population is suspiciously small: {classes}"
    owners = {cls.__name__ for cls in classes if HELPER in vars(cls)}
    if HELPER in vars(BaseCollector):
        owners.add(BaseCollector.__name__)
    assert owners == {"BaseCollector", "WorkingTreeCollector"}, (
        f"{HELPER} owners drifted: {sorted(owners)} != "
        "['BaseCollector', 'WorkingTreeCollector']"
    )
    assert HELPER not in vars(GitActivityCollector), (
        f"GitActivityCollector unexpectedly defines {HELPER}; its inline gated "
        "block was explicitly out of scope for this iteration"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- the gated override is a different object AND a different result
# ---------------------------------------------------------------------------


def test_b05_gated_override_is_a_distinct_object_and_a_distinct_result(
    tmp_path: Path,
) -> None:
    assert WorkingTreeCollector._dirs_to_scan is not BaseCollector._dirs_to_scan, (
        "WorkingTreeCollector no longer overrides the walk; its gated flavor "
        "has been folded away, which this iteration explicitly does not do"
    )
    root = _gated_fixture(tmp_path)
    permissive = _names(BaseCollector._dirs_to_scan(root))
    gated = _names(WorkingTreeCollector._dirs_to_scan(root))
    assert permissive != gated, (
        "the two flavors now visit the same directory set, so one of them is "
        f"dead code: {permissive} == {gated}"
    )
    assert _NON_REPO_CHILD in permissive, (
        f"the permissive walk skipped the non-repo child {_NON_REPO_CHILD!r}, so it "
        f"is no longer permissive: {permissive}"
    )
    assert _NON_REPO_CHILD not in gated, (
        f"the gated walk visited the non-repo child {_NON_REPO_CHILD!r}: {gated}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- no surviving docstring defers to a sibling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label, owner",
    [("BaseCollector", BaseCollector), ("WorkingTreeCollector", WorkingTreeCollector)],
)
def test_b06_no_surviving_docstring_claims_sibling_parity(
    label: str, owner: type[BaseCollector]
) -> None:
    doc = _cleandoc(owner._dirs_to_scan.__doc__)
    assert doc, f"{label}.{HELPER} must keep a docstring"
    assert _PARITY_TOKEN not in doc.casefold(), (
        f"{label}.{HELPER}.__doc__ describes its walk by reference to a sibling "
        f"(contains {_PARITY_TOKEN!r}) -- the exact sentence a merge invites: {doc!r}"
    )


def test_b06_the_parity_reader_fires_on_a_known_bad_sample() -> None:
    """Without this, Behavior 6 could pass on a reader that matches nothing."""
    known_bad = "Directories to scan.\n\n    Identical strategy to the sibling.\n    "
    assert _PARITY_TOKEN in _cleandoc(known_bad).casefold()
    assert _PARITY_TOKEN not in _cleandoc("Every direct child; signals get sorted.").casefold()


# ---------------------------------------------------------------------------
# Behavior 7 -- the base docstring carries the facts that make the walk safe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token, why",
    [
        ("sort", "the consuming collector sorts its signals, so walk order is unobservable"),
        ("one level", "nesting is one level only"),
        ("iterdir", "the order is iterdir order"),
        ("dedup", "the result is not deduplicated"),
        ("fold", "why this flavor must not be folded with the gated one"),
    ],
)
def test_b07_base_docstring_states_the_reason_it_is_safe(token: str, why: str) -> None:
    doc = _cleandoc(BaseCollector._dirs_to_scan.__doc__).casefold()
    assert token in doc, (
        f"BaseCollector.{HELPER}.__doc__ never mentions {token!r} -- it must state "
        f"{why}; got {doc!r}"
    )


def test_b07_base_docstring_names_the_collector_that_keeps_the_override() -> None:
    doc = _cleandoc(BaseCollector._dirs_to_scan.__doc__)
    assert "WorkingTree" in doc, (
        "the base docstring does not name the collector that keeps the gated "
        f"override, so a reader cannot find the exception: {doc!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 8 -- observable parity for both migrated collectors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("collector", _MIGRATED, ids=lambda c: c.__name__)
def test_b08_migrated_collector_sees_child_repo_but_not_plain_or_grandchild(
    collector: type[BaseCollector], tmp_path: Path
) -> None:
    root = _workspace(tmp_path)
    signals = collector().collect(root)
    assert signals, (
        f"{collector.__name__}: the fixture produced no signals, so every negative "
        "assertion below is vacuous"
    )
    hay = _haystack(signals, root)
    assert _REPO_CHILD in hay, (
        f"{collector.__name__}: the direct child repo {_REPO_CHILD!r} is missing "
        f"from the output: {hay!r}"
    )
    assert _NON_REPO_CHILD not in hay, (
        f"{collector.__name__}: the non-repo child {_NON_REPO_CHILD!r} contributed "
        f"a signal: {hay!r}"
    )
    assert _GRANDCHILD_REPO not in hay, (
        f"{collector.__name__}: a repo one level TOO DEEP ({_GRANDCHILD_REPO!r}) was "
        f"surfaced; the inherited walk must stay one level only: {hay!r}"
    )


@pytest.mark.parametrize("collector", _MIGRATED, ids=lambda c: c.__name__)
def test_b08_plain_child_control_surfaces_once_it_is_a_repo(
    collector: type[BaseCollector], tmp_path: Path
) -> None:
    """The negative assertion above must be a real detector, not a dead search."""
    root = _workspace(tmp_path, plain_child_is_a_repo=True)
    hay = _haystack(collector().collect(root), root)
    assert _NON_REPO_CHILD in hay, (
        f"{collector.__name__}: a child repo named {_NON_REPO_CHILD!r} did NOT "
        f"surface, so the Behavior-8 negative assertion can never fail: {hay!r}"
    )


@pytest.mark.parametrize("collector", _MIGRATED, ids=lambda c: c.__name__)
def test_b08_two_consecutive_collects_agree(
    collector: type[BaseCollector], tmp_path: Path
) -> None:
    root = _workspace(tmp_path)
    first = collector().collect(root)
    second = collector().collect(root)
    assert first, f"{collector.__name__}: no signals -- determinism check is vacuous"
    assert _shapes(first) == _shapes(second), (
        f"{collector.__name__}: (kind, summary, path) varies between two "
        f"consecutive collect() calls:\n{_shapes(first)}\n{_shapes(second)}"
    )


@pytest.mark.parametrize("collector", _MIGRATED, ids=lambda c: c.__name__)
def test_b08_output_is_sorted_by_summary_which_is_what_makes_it_deterministic(
    collector: type[BaseCollector], tmp_path: Path
) -> None:
    """The mechanism the base docstring cites: an unsorted walk is safe here
    precisely because the consumer sorts its signals before capping them."""
    root = _workspace(tmp_path)
    summaries = [s.summary for s in collector().collect(root)]
    assert len(summaries) > 1, (
        f"{collector.__name__}: fewer than two signals, so sortedness is vacuous"
    )
    assert summaries == sorted(summaries), (
        f"{collector.__name__}: output is not sorted by summary, so the walk's "
        f"arbitrary order becomes observable: {summaries}"
    )


# ---------------------------------------------------------------------------
# Behavior 9 -- the gated walk is unchanged: sorted, .git-gated, deduplicated
# ---------------------------------------------------------------------------


def test_b09_gated_walk_is_sorted_gated_and_deduplicated(tmp_path: Path) -> None:
    """Driven through the reverse-order, doubled ``iterdir`` double, so all three
    properties are pinned deterministically rather than read off the filesystem."""
    root = _ReversedDoubledPath(_gated_fixture(tmp_path))
    result = _names(WorkingTreeCollector._dirs_to_scan(root))
    assert result == [root.name, "achild", "bchild"], (
        "the gated walk must return root then its .git children sorted and "
        f"deduplicated; got {result}"
    )


def test_b09_gated_walk_matches_on_a_real_path_too(tmp_path: Path) -> None:
    root = _gated_fixture(tmp_path)
    result = _names(WorkingTreeCollector._dirs_to_scan(root))
    assert result == [root.name, "achild", "bchild"], (
        f"the gated walk changed shape on a plain Path: {result}"
    )
    assert ".git" not in result, f"the gated walk descended into .git itself: {result}"
