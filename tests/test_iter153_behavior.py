"""Black-box behavior tests for factory iteration 153 (foundry state iter-147) ---
the source-detection walk gets exactly ONE definition in the package.

``_has_source`` (and its ``_SOURCE_EXTS`` extension set) answers one question --
"does this tree contain source code worth building or licensing?" -- and it was
answered TWICE, by two logic-identical copies in ``collectors/ci_config.py`` and
``collectors/license.py``, kept equal by a hand-written comment ASKING a human to
keep them in sync.  Both copies gate whether their collector emits an actionable
L2 gap signal, so drift between them would change emitted signals.  This
iteration hoists the single walk into ``collectors/filesystem.py`` -- the
walk-policy seam both modules already import from -- and deletes the copy, the
duplicate constant, the sync comment, and the imports that only the copy used.

The load-bearing risk of any hoist is a VACUOUS proof: an "unchanged behavior"
test that would pass just as well against two copies, or against no walk at all.
Three things guard against that here.  (1) Behavior 3 asserts object IDENTITY
(``is``), so an equal-but-separate copy FAILS where an equality test would pass.
(2) The pruning invariant is proved TWO-SIDED: behavior 4 shows the same fixture
shape EMITS when the ``.py`` file sits at the root, and behavior 5 shows it goes
silent only because the file moved into ``node_modules/`` or a hidden dir -- so
the empty list in behavior 5 cannot be an artifact of a collector that finds
nothing at all.  (3) Behavior 7 asserts the deliberately-separate third copy
(``test_posture._CANDIDATE_EXTS``) is still its OWN object, so an over-eager
"deduplicate everything" edit that aliases the two questions together FAILS.

ISOLATION CONTRACT (honored): every assertion below is written against THIS
iteration's spec (``pm.md`` "Expected Behaviors" 1-8 plus the Acceptance
Criteria) and drives only public surfaces -- ``CiConfigCollector().collect(root)``
and ``LicenseCollector().collect(root)``, plus module-level introspection of
imported objects and an ``ast`` parse, which is the oracle the spec itself
names for behaviors 1, 2 and 8.  **No file under ``src/`` was read by the author,
no engineer / reviewer / fix note was read, and no ``git diff`` was consulted.**
The runtime facts used to pin the assertions (that ``_SOURCE_EXTS`` is a
``frozenset``, and that both collectors take no constructor arguments) were taken
from the RUNNING product by import and by existing ``tests/`` usage, which is the
"read the product's own help/output by running it" affordance the role grants.

Fully offline and deterministic: no network, no subprocess, no git dependency.
Every writable fixture is built under ``tmp_path``.

FRESH-CLONE SAFETY (deliberate, see the ``_platform`` iter-154 post-release
break): the only reads outside ``tmp_path`` are ``ast`` parses of GIT-TRACKED
files under ``src/proactive_loop/`` -- never a count of, or an assertion about,
gitignored ambient state -- so every oracle here holds in a throwaway clone.

AMBIGUITY NOTES (PM feedback, see ``tester.md``):

* Behavior 2 pins ``_SOURCE_EXTS`` by VALUE equality (``== frozenset({...})``),
  exactly as the spec writes it.  ``set`` and ``frozenset`` compare equal by
  value in Python, so that assertion alone would not notice the container type
  changing; the live object is a ``frozenset`` (measured), and immutability is
  the property that makes a hoisted module-level constant safe to share, so it
  is asserted SEPARATELY rather than assumed.
* Behaviors 1/2/8 are spec'd as an ``ast`` census over "every ``*.py`` under
  ``src/proactive_loop/``".  Nested definitions are excluded deliberately: the
  claim is about module-level DEFINITIONS, and a same-named local inside some
  other function would be a different object with no drift risk.
* The Acceptance Criterion "``filesystem.py``'s module docstring still describes
  the module honestly" is prose with no shape-stable oracle, so it is
  deliberately NOT pinned here -- guessing its wording is how a guard goes red
  on its own author (see the iter-146 lesson).  ``tester.md`` records it as
  reviewed-by-reading-the-report rather than machine-checked.
"""

from __future__ import annotations

import ast
from pathlib import Path

from proactive_loop.collectors import CiConfigCollector, LicenseCollector
from proactive_loop.collectors import ci_config, filesystem
from proactive_loop.collectors import license as license_mod
from proactive_loop.collectors import test_posture

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "proactive_loop"
FILESYSTEM_MOD = "proactive_loop.collectors.filesystem"

# The spec's stated value for the one surviving extension set.
SPEC_SOURCE_EXTS = frozenset({".py", ".ts", ".js", ".go", ".rs"})


# --------------------------------------------------------------------------
# helpers -- module-level census over the shipped package
# --------------------------------------------------------------------------
def _src_files() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    assert files, f"census found no *.py under {SRC} -- the oracle would be vacuous"
    return files


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _module_level_functions(path: Path) -> list[str]:
    return [
        node.name
        for node in _parse(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _module_level_bindings(path: Path) -> list[str]:
    names: list[str] = []
    for node in _parse(path).body:
        if isinstance(node, ast.Assign):
            names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def _defining_files(kind: str, name: str) -> list[Path]:
    """Every file under src/ whose MODULE LEVEL defines ``name``."""
    lookup = _module_level_functions if kind == "func" else _module_level_bindings
    return [p for p in _src_files() if name in lookup(p)]


def _plain_imports(path: Path) -> set[str]:
    """Top-level module names from ``import X`` / ``import X.Y`` statements."""
    out: set[str] = set()
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            out.update(alias.name.split(".")[0] for alias in node.names)
    return out


def _from_imports(path: Path) -> dict[str, set[str]]:
    """Map absolute-resolved module -> imported names, for every ``from`` import."""
    pkg_parts = path.relative_to(SRC.parent).with_suffix("").parts[:-1]
    out: dict[str, set[str]] = {}
    for node in ast.walk(_parse(path)):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:  # relative -- resolve against this file's package
            base = list(pkg_parts[: len(pkg_parts) - (node.level - 1)])
        else:
            base = []
        target = ".".join([*base, *([node.module] if node.module else [])])
        out.setdefault(target, set()).update(a.name for a in node.names)
    return out


# --------------------------------------------------------------------------
# fixtures -- the workspaces the spec describes
# --------------------------------------------------------------------------
def _workspace(root: Path, *rel_paths: str) -> Path:
    """Create each relative path as a small file, making parents as needed."""
    for rel in rel_paths:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n" if target.suffix == ".py" else "hello\n", encoding="utf-8")
    return root


def _one(signals: list[object]) -> object:
    assert len(signals) == 1, f"expected exactly one signal, got {len(signals)}: {signals!r}"
    return signals[0]


# --------------------------------------------------------------------------
# behavior 1 -- exactly one definition of the walk
# --------------------------------------------------------------------------
def test_b01_has_source_is_defined_exactly_once_in_filesystem() -> None:
    owners = _defining_files("func", "_has_source")
    assert [p.name for p in owners] == ["filesystem.py"], (
        "_has_source must be defined exactly once, in collectors/filesystem.py; "
        f"found {[str(p.relative_to(REPO)) for p in owners]}"
    )
    assert owners[0] == SRC / "collectors" / "filesystem.py"


# --------------------------------------------------------------------------
# behavior 2 -- exactly one definition of the extension set
# --------------------------------------------------------------------------
def test_b02_source_exts_is_defined_exactly_once_in_filesystem() -> None:
    owners = _defining_files("bind", "_SOURCE_EXTS")
    assert [p.name for p in owners] == ["filesystem.py"], (
        "_SOURCE_EXTS must be bound exactly once, in collectors/filesystem.py; "
        f"found {[str(p.relative_to(REPO)) for p in owners]}"
    )
    assert owners[0] == SRC / "collectors" / "filesystem.py"


def test_b02_source_exts_has_the_spec_value_and_is_immutable() -> None:
    assert filesystem._SOURCE_EXTS == SPEC_SOURCE_EXTS
    # A shared module-level constant is only safe to hoist if a caller cannot
    # mutate it; == alone cannot see the container type (set == frozenset).
    assert isinstance(filesystem._SOURCE_EXTS, frozenset)


# --------------------------------------------------------------------------
# behavior 3 -- both former owners resolve to the hoisted object BY IDENTITY
# --------------------------------------------------------------------------
def test_b03_both_former_owners_resolve_to_the_hoisted_walk_by_identity() -> None:
    assert ci_config._has_source is filesystem._has_source
    assert license_mod._has_source is filesystem._has_source
    # ...and the one object really is defined by the seam module, not re-bound.
    assert filesystem._has_source.__module__ == FILESYSTEM_MOD


def test_b03_neither_former_owner_keeps_its_own_extension_set() -> None:
    assert "_SOURCE_EXTS" not in vars(ci_config)
    assert "_SOURCE_EXTS" not in vars(license_mod)


# --------------------------------------------------------------------------
# behavior 4 -- positive side, both collectors (the control for behavior 5)
# --------------------------------------------------------------------------
def test_b04_source_at_root_makes_both_gaps_actionable(tmp_path: Path) -> None:
    root = _workspace(tmp_path, "README.md", "app.py")

    ci = _one(CiConfigCollector().collect(root))
    assert ci.kind == "ci_config"
    assert ci.summary == "no CI configured"
    assert ci.weight == 0.8

    lic = _one(LicenseCollector().collect(root))
    assert lic.kind == "license"
    assert lic.summary == "no license file"
    assert lic.weight == 0.7


# --------------------------------------------------------------------------
# behavior 5 -- negative side: the pruning invariant, both collectors
# --------------------------------------------------------------------------
def test_b05_source_only_inside_node_modules_is_not_source(tmp_path: Path) -> None:
    root = _workspace(tmp_path, "README.md", "node_modules/app.py")
    assert CiConfigCollector().collect(root) == []
    assert LicenseCollector().collect(root) == []


def test_b05_source_only_inside_a_hidden_dir_is_not_source(tmp_path: Path) -> None:
    root = _workspace(tmp_path, "README.md", ".hidden/app.py")
    assert CiConfigCollector().collect(root) == []
    assert LicenseCollector().collect(root) == []


# --------------------------------------------------------------------------
# behavior 6 -- a docs-only tree is not source
# --------------------------------------------------------------------------
def test_b06_docs_only_tree_is_not_source(tmp_path: Path) -> None:
    root = _workspace(tmp_path, "README.md", "notes.txt", "data.json")
    assert CiConfigCollector().collect(root) == []
    assert LicenseCollector().collect(root) == []


# --------------------------------------------------------------------------
# behavior 7 -- the deliberately excluded third copy stays independent
# --------------------------------------------------------------------------
def test_b07_test_posture_candidate_exts_stays_its_own_binding() -> None:
    owners = _defining_files("bind", "_CANDIDATE_EXTS")
    assert [p.name for p in owners] == ["test_posture.py"], (
        "_CANDIDATE_EXTS must remain test_posture's own module-level binding; "
        f"found {[str(p.relative_to(REPO)) for p in owners]}"
    )
    # Equal today, but a DIFFERENT question ("could this file hold a test").
    # Aliasing them would couple two oracles that must stay separable.
    assert test_posture._CANDIDATE_EXTS is not filesystem._SOURCE_EXTS


# --------------------------------------------------------------------------
# behavior 8 -- no dead import is left behind
# --------------------------------------------------------------------------
def test_b08_former_owners_import_only_the_walk_and_keep_path(tmp_path: Path) -> None:
    for mod_name in ("ci_config", "license"):
        path = SRC / "collectors" / f"{mod_name}.py"
        plain = _plain_imports(path)
        froms = _from_imports(path)
        imported_names = {n for names in froms.values() for n in names}

        assert "os" not in plain, f"{mod_name}.py still imports os"
        assert "os" not in froms, f"{mod_name}.py still does a from-os import"
        for dead in ("_SKIP_DIRS", "_is_hidden"):
            assert dead not in imported_names, f"{mod_name}.py still imports {dead}"

        assert "_has_source" in froms.get(FILESYSTEM_MOD, set()), (
            f"{mod_name}.py must import _has_source from {FILESYSTEM_MOD}; "
            f"its from-imports are {froms}"
        )
        # Acceptance Criterion: `from pathlib import Path` STAYS -- Path is still
        # used by other annotations in both modules.
        assert "Path" in froms.get("pathlib", set()), f"{mod_name}.py lost its Path import"


def test_b08_no_dead_os_name_survives_in_either_namespace() -> None:
    assert "os" not in vars(ci_config)
    assert "os" not in vars(license_mod)


# --------------------------------------------------------------------------
# Acceptance Criteria that are checkable by SHAPE (never by guessed prose)
# --------------------------------------------------------------------------
def test_ac_hand_sync_instruction_is_deleted_not_relocated() -> None:
    """The sync comment existed only because the constant was duplicated.

    Pinned by SHAPE, not by wording: neither former owner may mention
    ``_SOURCE_EXTS`` anywhere in its bytes any more -- it no longer defines it
    (behavior 2) and no longer imports it (behavior 8), so a surviving mention
    is either a relocated hand-sync instruction or a stale reference.
    """
    for mod_name in ("ci_config", "license"):
        text = (SRC / "collectors" / f"{mod_name}.py").read_text(encoding="utf-8")
        assert "_SOURCE_EXTS" not in text, (
            f"{mod_name}.py still mentions _SOURCE_EXTS; the hand-sync note must be "
            "deleted, not relocated"
        )


def test_ac_surviving_constant_names_the_deliberately_separate_third_copy() -> None:
    """The 'why not folded in' note must be PROSE, never a new import edge."""
    path = SRC / "collectors" / "filesystem.py"
    text = path.read_text(encoding="utf-8")
    assert "_CANDIDATE_EXTS" in text or "test_posture" in text, (
        "filesystem.py must carry a short note naming why test_posture's "
        "_CANDIDATE_EXTS is deliberately not folded into _SOURCE_EXTS"
    )
    # A note is documentation; importing test_posture would be a real (and
    # circular-risk) dependency between two collectors.
    assert "test_posture" not in {n for ns in _from_imports(path).values() for n in ns}
    assert "proactive_loop.collectors.test_posture" not in _from_imports(path)
