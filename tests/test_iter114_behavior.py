"""Behavior tests for state-dir iteration 107 (ships as commit-seq ``factory iter 114``).

Feature under test: ``proactive_loop`` gains a REAL importable public API. The
root package re-exports the 13 core data-contract names behind an explicit
``__all__``, the two top-level modules that back them (``models``, ``config``)
declare their own ``__all__``, and a new ``## Use as a library`` README section
documents that surface.

Why this file is the oracle
The README's human-owned intro promises "fully type-hinted (ships a PEP 561
``py.typed`` marker)", and a ``py.typed`` marker has exactly one audience: a
downstream project that IMPORTS the package. Before this iteration
``dir(proactive_loop)`` had NO public names at all and
``from proactive_loop import ContextSignal`` raised ImportError, so the typed
promise was unreachable without spelunking private module paths. These tests
encode the promise as a contract: an exact export set, identity (not copies) with
the home modules, bidirectional ast-vs-``__all__`` completeness on both backing
modules, an unchanged private-path import style, a CLI-free root import, and a
README section whose documented size is bound to the live ``__all__``.

Why two public names are deliberately NOT promised at the root
``models.__all__`` is ast-complete, so it necessarily contains two helpers that
are not part of the data contract: ``ensure_dir`` (a filesystem side effect --
``mkdir(parents=True, exist_ok=True)``-shaped plumbing, not a type a consumer
annotates against) and ``sanitize_validation_error`` (an error-message scrubber
for pydantic failures -- an internal presentation detail whose output format must
stay free to change). Promising either at the root would freeze plumbing instead
of the persisted JSON schema, so behavior 5 pins the root-vs-modules difference
to EXACTLY those two names: a future public helper cannot silently escape into
the compatibility promise, and a future data model cannot silently stay out of it.

Isolation: black-box. The seams used are (a) importing the public package,
(b) reading ``README.md`` from disk, (c) parsing ``models.py`` / ``config.py``
with ``ast`` -- which the spec's behaviors 3 and 4 REQUIRE as the drift oracle,
and which reads only the module's declared surface, never its logic -- and
(d) driving ``main()`` / a fresh interpreter. No implementation source was read
while writing this file; no engineer or reviewer note was opened.

Offline: file reads, in-process imports, and three short ``sys.executable -c``
subprocesses. No network, no API keys, no state-dir writes.

Every reader here is fail-CLOSED and is fired on a known-bad sample in the same
module (``test_guard_*``): a section reader that silently returns "" or a size
parser that silently finds nothing would make these guards pass vacuously, which
is indistinguishable from a broken tripwire.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from proactive_loop.cli import main

# --------------------------------------------------------------------------
# Tester's ground facts --- transcribed from the spec (pm.md), NOT imported
# from the implementation, so a silent drift in either direction is caught.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
PKG = REPO / "src" / "proactive_loop"
MODELS_PY = PKG / "models.py"
CONFIG_PY = PKG / "config.py"

# Spec: the exported set is EXACTLY these 13 names, and this sorted order is
# also the required ``__all__`` order.
PROMISED: tuple[str, ...] = (
    "AutonomyDecision",
    "CandidateGoal",
    "ContextSignal",
    "DispatchDecision",
    "GoalCategory",
    "GoalSlate",
    "LoopStep",
    "RetryPolicy",
    "RunState",
    "RunStatus",
    "Settings",
    "StepKind",
    "WorkspaceSnapshot",
)

# Spec behavior 2: the home module each promised name must resolve to BY IDENTITY.
FROM_CONFIG: frozenset[str] = frozenset({"RetryPolicy", "Settings"})
FROM_MODELS: frozenset[str] = frozenset(PROMISED) - FROM_CONFIG

# Spec behavior 5: public in a backing module, deliberately NOT promised at root.
ROOT_EXCLUDED: frozenset[str] = frozenset({"ensure_dir", "sanitize_validation_error"})

MARKER = "PORTFOLIO INTRO"  # spelled with an em dash in the file; match the prefix
LIBRARY_HEADING = "## Use as a library"


# --------------------------------------------------------------------------
# Readers (all fail-closed; each is fired on a known-bad sample below)
# --------------------------------------------------------------------------


def ast_public_defs(path: Path) -> frozenset[str]:
    """Public TOP-LEVEL ``class``/``def`` names of ``path``, via ``ast``.

    Raises rather than returning an empty set when the file is missing or has no
    public definitions -- an empty derivation would make the bidirectional
    ``__all__`` comparison pass against an empty universe.
    """
    assert path.is_file(), f"cannot derive the public surface: {path} is missing"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    assert names, f"{path.name} declares no public top-level class/def; nothing to compare"
    return frozenset(names)


def module_all(module_name: str) -> list[str]:
    """``__all__`` of a live module, asserting it exists and is a list of str."""
    mod = importlib.import_module(module_name)
    assert hasattr(mod, "__all__"), f"{module_name} must declare __all__"
    value = mod.__all__
    assert isinstance(value, list), f"{module_name}.__all__ must be a list; got {type(value)}"
    assert all(isinstance(name, str) for name in value), (
        f"{module_name}.__all__ must hold only str; got {value!r}"
    )
    return list(value)


def section_of(text: str, heading: str) -> str:
    """``heading`` up to (not including) the next ``## `` line.

    Fails loudly when the heading is missing or duplicated: a silently-empty
    section would make every README guard below pass over zero characters.
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\n") == heading]
    assert len(starts) == 1, (
        f"expected exactly one {heading!r} heading, found {len(starts)}; "
        "the library-reference guards would have no section to read"
    )
    start = starts[0]
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
        len(lines),
    )
    return "".join(lines[start:end])


_FENCE = re.compile(r"^```python[ \t]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)


def python_fences(section_text: str) -> list[str]:
    """Bodies of every ```python fence in ``section_text`` (at least one required)."""
    fences = [match.group(1) for match in _FENCE.finditer(section_text)]
    assert fences, "the library section must carry at least one ```python fence"
    return fences


def strip_fences(section_text: str) -> str:
    """``section_text`` with every fenced block removed, i.e. the PROSE only."""
    return re.sub(r"^```.*?^```[ \t]*$", "", section_text, flags=re.DOTALL | re.MULTILINE)


_SIZE_CLAIM = re.compile(r"(\d+)\s*\*{0,2}\s+names\b")


def documented_surface_size(prose: str) -> int:
    """The single ``N names`` size claim in the section prose.

    Bound to the WORD ``names`` rather than to "any integer in the section", so an
    unrelated number elsewhere in the prose cannot satisfy (or break) the guard.
    Raises on zero or multiple claims -- an unparsed claim must not read as
    agreement.
    """
    found = _SIZE_CLAIM.findall(prose)
    assert len(found) == 1, (
        "the library section prose must state the promised surface size exactly "
        f"once as '<N> names'; found {found!r}"
    )
    return int(found[0])


def _run_py(code: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a FRESH interpreter (no inherited sys.modules). Offline."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=120,
    )


# ==========================================================================
# Behavior 1 --- the root ``__all__`` is exactly the 13 promised names, sorted,
# duplicate-free, and a list of str.
# ==========================================================================


def test_b01_root_all_is_exactly_the_thirteen_promised_names_sorted() -> None:
    names = module_all("proactive_loop")
    assert names == sorted(PROMISED), (
        "proactive_loop.__all__ must be exactly the 13 promised names in sorted "
        f"order;\n  expected {sorted(PROMISED)}\n  got      {names}"
    )
    assert len(set(names)) == 13, f"__all__ must hold 13 distinct names; got {names!r}"
    assert names == sorted(names), f"__all__ must be sorted; got {names!r}"


# ==========================================================================
# Behavior 2 --- every promised name imports from the root AND is the SAME
# OBJECT as its home-module attribute (a re-export, never a copy or alias).
# ==========================================================================


def test_b02_every_promised_name_imports_from_the_root() -> None:
    root = importlib.import_module("proactive_loop")
    for name in PROMISED:
        # The real ``from proactive_loop import <name>`` machinery, not getattr.
        imported = __import__("proactive_loop", fromlist=[name])
        assert hasattr(imported, name), f"`from proactive_loop import {name}` must succeed"
        assert getattr(root, name) is getattr(imported, name)


def test_b02_each_export_is_identical_to_its_home_module_attribute() -> None:
    root = importlib.import_module("proactive_loop")
    models = importlib.import_module("proactive_loop.models")
    config = importlib.import_module("proactive_loop.config")

    for name in sorted(FROM_MODELS):
        assert getattr(root, name) is getattr(models, name), (
            f"proactive_loop.{name} must BE proactive_loop.models.{name} "
            "(re-export, not a copy/alias/re-definition)"
        )
    for name in sorted(FROM_CONFIG):
        assert getattr(root, name) is getattr(config, name), (
            f"proactive_loop.{name} must BE proactive_loop.config.{name}"
        )
    # The split is the spec's, so pin it: no config name may leak in via models.
    assert FROM_MODELS | FROM_CONFIG == frozenset(PROMISED)
    assert len(FROM_CONFIG) == 2 and len(FROM_MODELS) == 11


# ==========================================================================
# Behavior 3 --- ``models.__all__`` is ast-COMPLETE, both directions.
# ==========================================================================


def test_b03_models_all_matches_its_ast_public_surface_both_directions() -> None:
    declared = module_all("proactive_loop.models")
    derived = ast_public_defs(MODELS_PY)
    missing = sorted(derived - set(declared))
    extra = sorted(set(declared) - derived)
    assert not missing, (
        f"models.py declares public class/def {missing} that are absent from "
        "models.__all__ (the surface would silently escape the guard)"
    )
    assert not extra, (
        f"models.__all__ lists {extra} which are not public top-level class/def "
        "names in models.py (a stale or invented export)"
    )
    assert len(set(declared)) == len(declared), f"models.__all__ has duplicates: {declared}"


# ==========================================================================
# Behavior 4 --- ``config.__all__`` is ast-complete and is {RetryPolicy, Settings}.
# ==========================================================================


def test_b04_config_all_matches_its_ast_public_surface_both_directions() -> None:
    declared = module_all("proactive_loop.config")
    derived = ast_public_defs(CONFIG_PY)
    assert set(declared) == derived, (
        "config.__all__ must equal the ast-derived public class/def names of "
        f"config.py;\n  __all__ {sorted(declared)}\n  ast     {sorted(derived)}"
    )
    assert set(declared) == set(FROM_CONFIG), (
        f"spec pins config.__all__ to {sorted(FROM_CONFIG)}; got {sorted(declared)}"
    )


# ==========================================================================
# Behavior 5 --- the root surface is a SUBSET of the two backing modules, and
# the withheld difference is EXACTLY the two internal helpers.
# ==========================================================================


def test_b05_root_surface_is_a_subset_withholding_exactly_two_helpers() -> None:
    root = set(module_all("proactive_loop"))
    backing = set(module_all("proactive_loop.models")) | set(module_all("proactive_loop.config"))
    assert root <= backing, (
        f"the root promises names absent from models/config __all__: {sorted(root - backing)}"
    )
    assert backing - root == set(ROOT_EXCLUDED), (
        "the names public in models/config but withheld from the root promise must "
        f"be EXACTLY {sorted(ROOT_EXCLUDED)}; got {sorted(backing - root)}"
    )
    # Withheld does not mean unreachable: both stay importable from their module.
    models = importlib.import_module("proactive_loop.models")
    for name in sorted(ROOT_EXCLUDED):
        assert hasattr(models, name), f"{name} must remain importable from proactive_loop.models"
        assert not hasattr(importlib.import_module("proactive_loop"), name), (
            f"{name} must NOT be reachable on the root package"
        )


# ==========================================================================
# Behavior 6 --- importing the root stays light: a FRESH interpreter that does
# ``import proactive_loop`` must not have pulled in ``proactive_loop.cli``.
# ==========================================================================


def test_b06_root_import_does_not_drag_in_the_cli(tmp_path: Path) -> None:
    code = (
        "import sys, json;"
        "import proactive_loop as p;"
        "print(json.dumps({"
        "'cli': 'proactive_loop.cli' in sys.modules,"
        "'argparse': 'argparse' in sys.modules,"
        "'all': list(p.__all__),"
        "'main': hasattr(p, 'main'),"
        "}))"
    )
    proc = _run_py(code, cwd=tmp_path)
    assert proc.returncode == 0, (
        f"`import proactive_loop` must succeed in a fresh interpreter from an "
        f"arbitrary cwd; rc={proc.returncode} stderr={proc.stderr!r}"
    )
    payload = json.loads(proc.stdout)
    assert payload["cli"] is False, (
        "importing the root package must NOT import proactive_loop.cli "
        "(the library must not pay for argparse setup)"
    )
    assert payload["main"] is False, "`main` is not part of the promised surface"
    assert payload["all"] == sorted(PROMISED)


# ==========================================================================
# Behavior 7 --- no import cycle, and the pre-existing private-path import
# style still works unchanged.
# ==========================================================================


def test_b07_no_import_cycle_and_private_path_imports_still_work(tmp_path: Path) -> None:
    code = (
        "import proactive_loop;"
        "import proactive_loop.cli;"
        "from proactive_loop.models import CandidateGoal;"
        "from proactive_loop.config import Settings;"
        "from proactive_loop.scout import gate_slate;"
        "print('ok', CandidateGoal.__name__, Settings.__name__, gate_slate.__name__)"
    )
    proc = _run_py(code, cwd=tmp_path)
    assert proc.returncode == 0, (
        "root import followed by cli import must not deadlock or cycle, and the "
        f"private-path style must still work; rc={proc.returncode} stderr={proc.stderr!r}"
    )
    assert proc.stdout.startswith("ok CandidateGoal Settings gate_slate"), (
        f"unexpected stdout from the cycle probe: {proc.stdout!r}"
    )


# ==========================================================================
# Behavior 8 --- the README carries `## Use as a library` BELOW the human-owned
# marker, with at least one python fence.
# ==========================================================================


def test_b08_library_section_sits_below_the_human_owned_marker() -> None:
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()
    marker_lines = [i for i, line in enumerate(lines) if MARKER in line]
    assert len(marker_lines) == 1, f"expected one {MARKER!r} marker line; found {marker_lines}"
    heading_lines = [i for i, line in enumerate(lines) if line.strip() == LIBRARY_HEADING]
    assert len(heading_lines) == 1, (
        f"expected exactly one {LIBRARY_HEADING!r} heading; found {len(heading_lines)}"
    )
    assert heading_lines[0] > marker_lines[0], (
        f"{LIBRARY_HEADING!r} is at line {heading_lines[0] + 1}, at/above the human-owned "
        f"marker at line {marker_lines[0] + 1}; reference sections must live BELOW it"
    )
    fences = python_fences(section_of(text, LIBRARY_HEADING))
    assert any(fence.strip() for fence in fences), "the python fence must not be empty"


# ==========================================================================
# Behavior 9 --- no ghost API in the documented example: every name imported
# `from proactive_loop import ...` is in ``__all__``, and every sub-package
# import shown resolves. Then the fence is EXECUTED as published.
# ==========================================================================


def _fence_root_imports(fence: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(fence)):
        if isinstance(node, ast.ImportFrom) and node.module == "proactive_loop":
            names.extend(alias.name for alias in node.names)
    return names


def _fence_subpackage_imports(fence: str) -> list[tuple[str, tuple[str, ...]]]:
    found: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(ast.parse(fence)):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("proactive_loop.")
        ):
            found.append((node.module, tuple(alias.name for alias in node.names)))
    return found


def test_b09_documented_example_names_no_ghost_api() -> None:
    section = section_of(README.read_text(encoding="utf-8"), LIBRARY_HEADING)
    promised = set(module_all("proactive_loop"))
    root_imports: list[str] = []
    subpackage_imports: list[tuple[str, tuple[str, ...]]] = []
    for fence in python_fences(section):
        root_imports.extend(_fence_root_imports(fence))
        subpackage_imports.extend(_fence_subpackage_imports(fence))

    assert root_imports, (
        "the documented example must actually import from the root package "
        "(otherwise it documents nothing about the promised surface)"
    )
    ghosts = sorted(name for name in root_imports if name not in promised)
    assert not ghosts, (
        f"the README example imports {ghosts} from proactive_loop, which are not in "
        f"__all__ ({sorted(promised)}) -- documented ghost API"
    )
    for module_name, names in subpackage_imports:
        mod = importlib.import_module(module_name)  # must resolve at runtime
        for name in names:
            assert hasattr(mod, name), (
                f"the README example imports {name!r} from {module_name}, which does not exist"
            )


def test_b09_documented_example_runs_as_published(tmp_path: Path) -> None:
    section = section_of(README.read_text(encoding="utf-8"), LIBRARY_HEADING)
    fence = python_fences(section)[0]
    script = tmp_path / "readme_example.py"
    script.write_text(fence, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=120,
    )
    assert proc.returncode == 0, (
        "the published README example must run as-is (offline, no network); "
        f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert proc.stdout.strip(), "the example prints, so its stdout must not be empty"


# ==========================================================================
# Behavior 10 --- the documented surface SIZE is bound to the live ``__all__``.
# ==========================================================================


def test_b10_documented_surface_size_equals_live_all() -> None:
    section = section_of(README.read_text(encoding="utf-8"), LIBRARY_HEADING)
    documented = documented_surface_size(strip_fences(section))
    live = len(module_all("proactive_loop"))
    assert documented == live, (
        f"the README section claims {documented} promised names but "
        f"proactive_loop.__all__ holds {live}; add the export to the docs (or the "
        "doc-claim to __all__) in the same commit"
    )
    assert documented == 13, f"spec pins the promised surface at 13 names; README says {documented}"


# ==========================================================================
# Behavior 11 --- no CLI regression: `pla config --json` still exits 0 with
# parseable JSON (end-to-end proof the package imports under the script path).
# ==========================================================================


def test_b11_cli_config_json_still_exits_zero_with_parseable_json(capsys) -> None:
    rc = main(["config", "--json"])
    cap = capsys.readouterr()
    assert rc == 0, f"`pla config --json` must still exit 0; stderr={cap.err!r}"
    payload = json.loads(cap.out)
    assert isinstance(payload, dict) and payload, (
        f"`pla config --json` must emit one non-empty JSON object; got {cap.out!r}"
    )


def test_b11_console_script_path_still_emits_parseable_json() -> None:
    """The same proof through the REAL `pla` console script, not just `main()`.

    Behavior 11 asks for an end-to-end check that the package still imports "under
    the console-script path", and an in-process ``main()`` call cannot see a broken
    entry point: it imports ``proactive_loop.cli`` directly, bypassing the installed
    wrapper that resolves ``pla`` -> ``proactive_loop.cli:main``. The wrapper is
    declared in ``pyproject.toml`` and installed by ``uv sync``, so its absence is a
    real packaging failure and is reported as one rather than skipped.
    """
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, (
        "the `pla` console script must be installed (declared in pyproject and "
        f"installed by `uv sync`); searched {[str(c) for c in candidates]}"
    )
    proc = subprocess.run(
        [str(script), "config", "--json"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"`pla config --json` must exit 0 via the console script; "
        f"rc={proc.returncode} stderr={proc.stderr!r}"
    )
    payload = json.loads(proc.stdout)
    assert isinstance(payload, dict) and payload, (
        f"the console script must emit one non-empty JSON object; got {proc.stdout!r}"
    )


# ==========================================================================
# Guard self-tests --- every reader above must FIRE on a known-bad sample.
# A tripwire that cannot be made to fire is indistinguishable from a broken one.
# ==========================================================================


def test_guard_section_reader_rejects_missing_and_duplicate_headings() -> None:
    good = f"# t\n\n{LIBRARY_HEADING}\nbody\n\n## Next\nother\n"
    assert "body" in section_of(good, LIBRARY_HEADING)
    assert "other" not in section_of(good, LIBRARY_HEADING)
    with pytest.raises(AssertionError):
        section_of("# t\n\n## Something else\n", LIBRARY_HEADING)
    with pytest.raises(AssertionError):
        section_of(f"{LIBRARY_HEADING}\na\n{LIBRARY_HEADING}\nb\n", LIBRARY_HEADING)


def test_guard_fence_reader_rejects_a_section_with_no_python_fence() -> None:
    assert python_fences("## H\n\n```python\nx = 1\n```\n") == ["x = 1\n"]
    with pytest.raises(AssertionError):
        python_fences("## H\n\nprose only\n")
    with pytest.raises(AssertionError):
        python_fences("## H\n\n```\nnot tagged python\n```\n")


def test_guard_size_parser_rejects_zero_and_multiple_claims() -> None:
    assert documented_surface_size("exactly **13 names**, enumerated") == 13
    assert documented_surface_size("that surface is 7 names") == 7
    with pytest.raises(AssertionError):
        documented_surface_size("thirteen names, spelled out")
    with pytest.raises(AssertionError):
        documented_surface_size("13 names here and 4 names there")
    # A number NOT attached to the word `names` must not satisfy the claim.
    with pytest.raises(AssertionError):
        documented_surface_size("Python 3.12 and a py.typed marker")


def test_guard_ast_reader_sees_public_defs_only_and_rejects_an_empty_module(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "CONST = 1\n"
        "class Public:\n    pass\n"
        "class _Private:\n    pass\n"
        "def helper():\n    return 1\n"
        "def _hidden():\n    return 2\n"
        "async def awaited():\n    return 3\n"
        "if True:\n    class Nested:\n        pass\n",
        encoding="utf-8",
    )
    assert ast_public_defs(sample) == frozenset({"Public", "helper", "awaited"})
    empty = tmp_path / "empty.py"
    empty.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        ast_public_defs(empty)
    with pytest.raises(AssertionError):
        ast_public_defs(tmp_path / "does_not_exist.py")


def test_guard_module_all_reader_rejects_a_bad_or_missing_all(monkeypatch) -> None:
    """The ``__all__`` reader must reject absent, non-list and non-str-item values.

    Fired against synthetic modules injected into ``sys.modules`` rather than a
    stdlib victim: the first candidate tried here (``json.decoder``) turned out to
    DECLARE ``__all__``, so the "known-bad" sample was not bad and the self-test
    proved nothing. Constructing the bad sample removes that guesswork.
    """
    missing = types.ModuleType("pla_fake_missing_all")
    tuple_all = types.ModuleType("pla_fake_tuple_all")
    tuple_all.__all__ = ("Settings",)  # type: ignore[attr-defined]
    int_items = types.ModuleType("pla_fake_int_items")
    int_items.__all__ = [1]  # type: ignore[attr-defined]
    good = types.ModuleType("pla_fake_good")
    good.__all__ = ["Settings"]  # type: ignore[attr-defined]
    for mod in (missing, tuple_all, int_items, good):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)

    assert module_all("pla_fake_good") == ["Settings"]
    for bad in ("pla_fake_missing_all", "pla_fake_tuple_all", "pla_fake_int_items"):
        with pytest.raises(AssertionError):
            module_all(bad)
