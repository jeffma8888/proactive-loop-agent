"""Black-box behavior tests for iteration 148 (ships as commit-sequence **factory
iter 154**) --- the three ``_dirs_to_scan`` docstrings in the git-family collectors
stop describing their directory walk BY REFERENCE to a sibling ("identical
strategy to ...") and instead state their own flavor plus the reason that flavor
is safe. Two of those claims were FALSE, and the word "identical" was an active
invitation to merge two walks that visit different directory sets (ROADMAP #163 /
#180).

Because prose cannot be regression-tested by prose, this module also pins the
structure the corrected prose now describes: an ``ast`` census of the collectors
package proves there are exactly THREE ``_dirs_to_scan`` helpers, and a
docstring-stripped ``ast.unparse`` comparison proves the two surviving flavors are
different equivalence classes.

RE-KEYED for factory iter 265 (ROADMAP #262): the permissive walk was hoisted onto
``BaseCollector``, so ``git_state`` and ``git_stash`` INHERIT it and the census is
now TWO definitions (``base.py`` plus ``working_tree.py``'s gated override), not
three. The pair's text-equality claim became object IDENTITY -- a strictly stronger
guard, since an inherited attribute cannot drift the way two copies could.
Behaviors 6-7 re-assert that no observable collector behavior changed.

ISOLATION CONTRACT (honored): every assertion here was written strictly from this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
tree, and the product's OBSERVABLE output obtained by RUNNING the public
collectors. **No file under ``src/`` was read by the author, no engineer /
reviewer / fix note was consulted, and no ``git diff`` was inspected.** The class
names, module basenames and helper name are the ones the SPEC names; the source
text they own is never transcribed here --- it is parsed at runtime by ``ast`` and
compared to itself, so this module cannot encode an implementation quirk it never
saw. Fully offline and deterministic: no network, no API key, and every fixture
repo is a directory tree under pytest's ``tmp_path`` (the ``git`` binary is used
only where an existing sibling module already does, and those tests skip when it
is unavailable). Nothing is written inside the product repo.

Python-version note (iter-145 was reverted for this class of bug): CPython 3.13
strips the common leading indent from docstrings at compile time and 3.12 does
not, so every docstring assertion below runs through ``inspect.cleandoc`` and
asserts on TOKENS only --- never on indentation, line breaks or exact wording.
"""

from __future__ import annotations

import ast
import inspect
import shutil
import subprocess
from pathlib import Path

import pytest

import proactive_loop.collectors as collectors_pkg
from proactive_loop.collectors import (
    GitActivityCollector,
    GitStashCollector,
    GitStateCollector,
    WorkingTreeCollector,
)
from proactive_loop.collectors.base import BaseCollector

# The collectors package directory, resolved from the IMPORTED package rather
# than a hardcoded "src/proactive_loop/collectors" path, so the census works in
# an editable checkout and in a fresh clone alike.
COLLECTORS_DIR = Path(collectors_pkg.__file__).resolve().parent

HELPER = "_dirs_to_scan"

# The modules that DEFINE a `_dirs_to_scan` helper: the base class now owns the
# permissive walk, and `working_tree` keeps the one justified gated override.
_EXPECTED_HELPER_MODULES = frozenset({"base.py", "working_tree.py"})

# The single definition site of the permissive walk, and the gated walk that is
# deliberately a different equivalence class from it.
_PERMISSIVE_OWNER = "base.py"
_GATED = "working_tree.py"

# The two collector modules that INHERIT the permissive walk (they no longer
# define it -- that is exactly what Behavior 4 now asserts). Their `__doc__`
# reaches the base docstring by attribute access, so the Behavior 1/2 prose
# claims still apply to them.
_PERMISSIVE_PAIR = ("git_stash.py", "git_state.py")

# The banned self-description: a docstring that defers to a sibling collector.
_PARITY_TOKEN = "identical"

# A known-bad sample -- the literal shape of the claim this iteration deletes.
_KNOWN_BAD_DOCSTRING = """Directories to scan.

    Uses an identical strategy to the other git collectors.
    """

# Behavior 6/7 fixture layout: the root and `sub/` are repos, `plain/` is not.
_NON_REPO_CHILD = "plain"
_REPO_CHILD = "sub"

_GIT_COLLECTORS = (
    GitActivityCollector,
    GitStateCollector,
    GitStashCollector,
    WorkingTreeCollector,
)


# ---------------------------------------------------------------------------
# Helpers -- docstring predicate (shared by Behaviors 1 and 5) + ast census
# ---------------------------------------------------------------------------


def _claims_sibling_parity(doc: str | None) -> bool:
    """True when *doc* describes itself by reference to a sibling collector.

    This is the single predicate Behavior 1 asserts against the real docstrings
    and Behavior 5 asserts against a synthetic known-bad sample, so a reader that
    silently matches nothing cannot pass Behavior 1 vacuously.
    """
    if doc is None:
        return False
    return _PARITY_TOKEN in inspect.cleandoc(doc).casefold()


def _cleandoc(doc: str | None) -> str:
    """3.12/3.13-safe docstring normaliser (see the module docstring's note)."""
    return "" if doc is None else inspect.cleandoc(doc)


def _module_files() -> list[Path]:
    """Every ``.py`` module file in the collectors package, sorted."""
    return sorted(p for p in COLLECTORS_DIR.glob("*.py"))


def _helper_census() -> dict[str, list[ast.FunctionDef]]:
    """Map module basename -> every ``_dirs_to_scan`` FunctionDef it defines."""
    found: dict[str, list[ast.FunctionDef]] = {}
    for path in _module_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nodes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == HELPER
        ]
        if nodes:
            found[path.name] = nodes
    return found


def _strip_docstrings(node: ast.AST) -> None:
    """Delete the docstring statement from every def/class in *node*, in place."""
    for sub in ast.walk(node):
        if not isinstance(
            sub, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(sub, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            sub.body = body[1:]


def _body_source(func: ast.FunctionDef) -> str:
    """``ast.unparse`` of *func*'s body with ALL docstrings stripped."""
    clone = ast.parse(ast.unparse(func))
    stripped = clone.body[0]
    assert isinstance(stripped, ast.FunctionDef)
    _strip_docstrings(stripped)
    return "\n".join(ast.unparse(stmt) for stmt in stripped.body)


def _helper_docs() -> dict[str, str | None]:
    """Live ``__doc__`` values keyed by module basename, via ATTRIBUTE access.

    Attribute access, not the file census, is what makes the prose claims survive
    the hoist: ``git_stash.py`` and ``git_state.py`` no longer define the helper,
    so what they resolve to IS ``base.py``'s docstring -- which is the point. The
    keys are kept distinct so a future re-divergence (either collector taking back
    its own override) is still covered by Behaviors 1 and 2.
    """
    return {
        "base.py": BaseCollector._dirs_to_scan.__doc__,
        "git_stash.py": GitStashCollector._dirs_to_scan.__doc__,
        "git_state.py": GitStateCollector._dirs_to_scan.__doc__,
        "working_tree.py": WorkingTreeCollector._dirs_to_scan.__doc__,
    }


# ---------------------------------------------------------------------------
# Behavior 1 -- the false claim is DELETED, not relocated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", sorted(_EXPECTED_HELPER_MODULES))
def test_b01_no_helper_docstring_claims_sibling_parity(module_name: str) -> None:
    doc = _helper_docs()[module_name]
    assert doc, f"{module_name}: {HELPER} must keep a docstring"
    assert not _claims_sibling_parity(doc), (
        f"{module_name}: {HELPER}.__doc__ still describes its walk by reference to a "
        f"sibling (contains {_PARITY_TOKEN!r}): {_cleandoc(doc)!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- each surviving docstring names its OWN flavor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", sorted(_PERMISSIVE_PAIR))
def test_b02_permissive_pair_docstrings_cite_their_own_sort(module_name: str) -> None:
    doc = _cleandoc(_helper_docs()[module_name])
    assert "sort" in doc.casefold(), (
        f"{module_name}: {HELPER}.__doc__ must say the collector sorts its signals "
        f"(the fact that makes an unsorted walk safe); got {doc!r}"
    )


def test_b02_working_tree_docstring_states_its_git_gate() -> None:
    doc = _cleandoc(_helper_docs()[_GATED])
    assert ".git" in doc, (
        f"{_GATED}: {HELPER}.__doc__ must state its own gate (children holding "
        f".git); got {doc!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- the census is exhaustive and NON-VACUOUS
# ---------------------------------------------------------------------------


def test_b03_census_population_is_non_empty() -> None:
    files = _module_files()
    assert files, f"no .py modules found under {COLLECTORS_DIR} -- census is vacuous"
    assert len(files) > 1, f"suspiciously small collectors package: {[p.name for p in files]}"


def test_b03_exactly_two_dirs_to_scan_helpers() -> None:
    census = _helper_census()
    total = sum(len(v) for v in census.values())
    assert total == 2, f"expected exactly 2 {HELPER} FunctionDefs, found {total}: {census.keys()}"
    assert set(census) == set(_EXPECTED_HELPER_MODULES), (
        f"{HELPER} owners drifted: {sorted(census)} != {sorted(_EXPECTED_HELPER_MODULES)}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- TWO equivalence classes, with the negative control
# ---------------------------------------------------------------------------


def test_b04_permissive_pair_inherits_the_base_walk_by_identity() -> None:
    """The migrated collectors share the permissive walk as an OBJECT, not as text.

    This replaces the text-equality guard the previous revision carried. That guard
    could only notice two hand-copied bodies AFTER they drifted apart; an inherited
    attribute cannot drift at all, so the claim is strictly stronger. The census
    half is what makes it a deduplication test rather than an aliasing test: it
    proves the copies are GONE, not merely equal.
    """
    census = _helper_census()
    for name in _PERMISSIVE_PAIR:
        assert name not in census, (
            f"{name} still DEFINES {HELPER}: the permissive walk must be INHERITED "
            f"from {_PERMISSIVE_OWNER}, not copied ({len(census.get(name, []))} def(s))"
        )
    assert _PERMISSIVE_OWNER in census, (
        f"{_PERMISSIVE_OWNER} does not define {HELPER}, so the identity assertions "
        "below would hold vacuously over an attribute nobody owns"
    )
    assert _body_source(census[_PERMISSIVE_OWNER][0]), (
        f"{_PERMISSIVE_OWNER}'s unparsed {HELPER} body is empty"
    )
    base_walk = BaseCollector._dirs_to_scan
    for collector in (GitStashCollector, GitStateCollector):
        assert collector._dirs_to_scan is base_walk, (
            f"{collector.__name__}.{HELPER} is not the {_PERMISSIVE_OWNER} object "
            "itself -- it has been shadowed by a fresh definition somewhere"
        )


def test_b04_gated_walk_is_a_different_equivalence_class() -> None:
    census = _helper_census()
    gated = _body_source(census[_GATED][0])
    permissive = _body_source(census[_PERMISSIVE_OWNER][0])
    assert gated, f"{_GATED}: unparsed body is empty -- assertion would be vacuous"
    assert permissive, f"{_PERMISSIVE_OWNER}: unparsed body is empty -- vacuous"
    assert gated != permissive, (
        f"{_GATED}'s gated walk is now byte-identical to {_PERMISSIVE_OWNER}'s "
        "permissive walk -- the two-flavor claim is no longer true, so the override "
        "should be deleted rather than kept as a silent duplicate"
    )
    assert WorkingTreeCollector._dirs_to_scan is not BaseCollector._dirs_to_scan, (
        f"{_GATED} no longer overrides {HELPER}; its gated walk has been lost"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- the docstring reader fires on a KNOWN-BAD sample
# ---------------------------------------------------------------------------


def test_b05_predicate_fires_on_known_bad_docstring() -> None:
    assert _claims_sibling_parity(_KNOWN_BAD_DOCSTRING), (
        "the Behavior-1 predicate does not fire on the exact claim this iteration "
        "deletes -- Behavior 1 would pass vacuously"
    )


def test_b05_predicate_is_quiet_on_a_clean_docstring() -> None:
    assert not _claims_sibling_parity(
        "Every direct child directory; the collector sorts its signals by summary."
    )
    assert not _claims_sibling_parity(None)


# ---------------------------------------------------------------------------
# Behaviors 6-7 -- fixture + offline git seams
#
# The fixture is the one the spec names: a root holding ``.git``, one child
# ``sub/`` holding ``.git``, and one child ``plain/`` holding none.
#
# TRAP measured in this stage (do not "simplify" this away): ``<collector
# module>.subprocess`` IS the one global ``subprocess`` module object, so
# ``setattr(module.subprocess, "run", ...)`` patches it for EVERY importer at
# once -- stubbing two collectors that way in a single test makes the second stub
# silently answer the first collector's query (measured: git_activity returned 0
# signals because working_tree's status double answered its ``git log``). These
# tests therefore install a per-module PROXY, so each collector sees only its own
# double and every other ``subprocess`` attribute still resolves to the real
# module. ``monkeypatch`` restores it.
# ---------------------------------------------------------------------------

_SEP = "\x1f"  # git log --format field separator used by the git_activity wire


class _SubprocessProxy:
    """Module-local stand-in for ``subprocess`` with only ``run`` replaced."""

    def __init__(self, real, run) -> None:
        self._real = real
        self.run = run

    def __getattr__(self, name: str):
        return getattr(self._real, name)


def _fake_git_log(*args, **kwargs):
    """Answer ``git -C <dir> log ...`` for ANY directory.

    Answering unconditionally is what makes Behavior 6 DISCRIMINATING for the
    gated walks: if a collector ever scanned the non-repo child, this double
    would hand it a commit and the ``plain`` assertion would go red.
    """
    import types

    cmd = [str(x) for x in args[0]]
    target = Path(cmd[cmd.index("-C") + 1])
    line = _SEP.join(
        ["abc1234", "2024-01-01 00:00:00 +0000", f"Work in {target.name}", "A"]
    )
    return types.SimpleNamespace(returncode=0, stdout=line + "\n")


def _fake_git_status(*args, **kwargs):
    """Answer ``git -C <dir> status --porcelain --branch`` for ANY directory."""
    import types

    cmd = [str(x) for x in args[0]]
    target = Path(cmd[cmd.index("-C") + 1])
    out = f"## main...origin/main [ahead 2]\n M {target.name}_edit.py\n"
    return types.SimpleNamespace(returncode=0, stdout=out)


def _stub(monkeypatch, module, run) -> None:
    monkeypatch.setattr(module, "subprocess", _SubprocessProxy(module.subprocess, run))


def _make_repo_marker(directory: Path) -> None:
    """Make *directory* look like a git repo, offline: a ``.git`` dir holding an
    in-flight merge marker and a one-entry stash reflog."""
    git = directory / ".git"
    git.mkdir(parents=True, exist_ok=True)
    (git / "MERGE_HEAD").write_text("0123456789abcdef\n", encoding="utf-8")
    refs = git / "logs" / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "stash").write_text(
        f"{'0' * 40} {'1' * 40} T <t@t> 1700000000 +0000\t"
        f"On main: wip in {directory.name}\n",
        encoding="utf-8",
    )


def _workspace(tmp_path: Path) -> Path:
    """The spec's fixture: root repo, one child repo, one non-repo child."""
    root = tmp_path / "ws"
    root.mkdir()
    _make_repo_marker(root)
    _make_repo_marker(root / _REPO_CHILD)
    plain = root / _NON_REPO_CHILD
    plain.mkdir()
    (plain / "notes.txt").write_text("hello\n", encoding="utf-8")
    return root


def _rel(value: object, root: Path) -> str:
    """Render *value* relative to *root* so the ambient tmp path (which the test
    does not control) can never satisfy or break a substring assertion."""
    text = "" if value is None else str(value)
    prefix = str(root)
    return text[len(prefix) :] if text.startswith(prefix) else text


def _haystack(signals: list, root: Path) -> str:
    """Every observable string a signal exposes, root-relative."""
    parts: list[str] = []
    for s in signals:
        parts.append(str(s.summary))
        parts.append(str(getattr(s, "detail", "") or ""))
        parts.append(_rel(s.path, root))
    return " | ".join(parts)


def _shapes(signals: list) -> list[tuple[str, str, str | None]]:
    return [(s.kind, s.summary, s.path) for s in signals]


def _collect_all(monkeypatch, root: Path) -> dict[str, list]:
    """Collect from all four git-family collectors over the SAME fixture.

    Each stubbed collector is driven in its own ``monkeypatch`` scope via the
    per-module proxy, so the two doubles cannot answer each other's query.
    """
    import proactive_loop.collectors.git_activity as git_activity
    import proactive_loop.collectors.working_tree as working_tree

    out: dict[str, list] = {
        "git_stash": GitStashCollector().collect(root),
        "git_state": GitStateCollector().collect(root),
    }
    _stub(monkeypatch, git_activity, _fake_git_log)
    out["git_activity"] = GitActivityCollector().collect(root)
    _stub(monkeypatch, working_tree, _fake_git_status)
    out["working_tree"] = WorkingTreeCollector().collect(root)
    return out


# ---------------------------------------------------------------------------
# Behavior 6 -- a non-repo child directory contributes NO signals
# ---------------------------------------------------------------------------


def test_b06_non_repo_child_contributes_no_signals(monkeypatch, tmp_path) -> None:
    root = _workspace(tmp_path)
    collected = _collect_all(monkeypatch, root)
    for name, signals in collected.items():
        # Positive control in the SAME fixture: the real child repo IS seen, so a
        # collector that silently returned nothing cannot pass the negative half.
        assert signals, f"{name}: fixture produced no signals -- negative half is vacuous"
        hay = _haystack(signals, root)
        assert _REPO_CHILD in hay, (
            f"{name}: the real child repo {_REPO_CHILD!r} is missing from the output, "
            f"so the {_NON_REPO_CHILD!r} assertion proves nothing: {hay!r}"
        )
        assert _NON_REPO_CHILD not in hay, (
            f"{name}: the non-repo child {_NON_REPO_CHILD!r} contributed a signal: {hay!r}"
        )


# ---------------------------------------------------------------------------
# Behavior 7 -- determinism is unchanged
# ---------------------------------------------------------------------------


def test_b07_two_consecutive_collects_agree(monkeypatch, tmp_path) -> None:
    root = _workspace(tmp_path)
    first = _collect_all(monkeypatch, root)
    second = _collect_all(monkeypatch, root)
    for name in first:
        a, b = first[name], second[name]
        assert a, f"{name}: no signals -- determinism assertion would be vacuous"
        assert len(a) == len(b), f"{name}: signal count varies between runs: {len(a)} vs {len(b)}"
        assert _shapes(a) == _shapes(b), (
            f"{name}: (kind, summary, path) order/content varies between two "
            f"consecutive collect() calls:\n{_shapes(a)}\n{_shapes(b)}"
        )


# ---------------------------------------------------------------------------
# Behavior 6, CONTROL -- the "plain" reader can actually go red
#
# Behavior 5 gives the docstring predicate a known-bad sample; this is the same
# discipline for Behavior 6. If the child named `plain` IS a repo, every collector
# must surface it -- which proves the negative half above is a real detector and
# not a substring search that can never match.
# ---------------------------------------------------------------------------


def test_b06_control_reader_fires_when_the_child_is_a_repo(monkeypatch, tmp_path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    _make_repo_marker(root)
    _make_repo_marker(root / _REPO_CHILD)
    _make_repo_marker(root / _NON_REPO_CHILD)  # same name, but now a real repo
    collected = _collect_all(monkeypatch, root)
    for name, signals in collected.items():
        hay = _haystack(signals, root)
        assert _NON_REPO_CHILD in hay, (
            f"{name}: a child repo named {_NON_REPO_CHILD!r} did NOT surface, so the "
            f"Behavior-6 negative assertion can never fail: {hay!r}"
        )
