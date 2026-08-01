"""Black-box behavior tests for iteration 58 --- the PEP 561 ``py.typed`` inline-
types marker.

The whole library is meticulously type-hinted (SPEC §5), but without a
``py.typed`` marker PEP 561 declares the *package* UNTYPED: a downstream consumer
who ``pip install``s it and runs mypy/pyright gets ZERO benefit from the
annotations. This iteration ships one empty ``src/proactive_loop/py.typed``
marker so the fully-hinted package exports as *typed*, plus a one-line README /
SPEC note. It is INERT PACKAGE DATA: no ``.py`` logic, no CLI verb/flag, no
version bump. The offline, deterministic proxies for "the marker ships in the
wheel" are (a) the importable-package-resource check and (b) the hatchling
wheel-packaging drift-guard --- no wheel build or type-checker is invoked
(that would add tooling/network fragility to an offline suite).

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration --- the spec's Expected Behaviors (``pm.md``),
``README.md``, ``SPEC.md``, and ``pyproject.toml`` --- and drive ONLY documented
public surfaces: importing the ``proactive_loop`` package (its ``__file__`` /
``__version__``), ``importlib.resources.files("proactive_loop")``, the repo-root
config/doc files parsed with stdlib ``tomllib``, and the ``pla`` CLI via
``proactive_loop.cli.main(argv)``. **No file under ``src/`` was read (beyond
importing the package), no engineer/reviewer notes were read, and no ``git
diff`` was consulted.** Every test is fully offline: zero network, zero API
keys, no live provider.
"""

from __future__ import annotations

import importlib.resources
import tomllib
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop import __version__
from proactive_loop.cli import main

# --------------------------------------------------------------------------
# Tester's ground facts --- the spec-declared contract constants (pm.md).
# Encoded here as constants, NOT imported from the implementation, so the
# tests encode the CONTRACT and would catch a silent drift.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
README = REPO / "README.md"
SPEC = REPO / "SPEC.md"

# The pinned, un-bumped version for this additive-data iteration.
EXPECTED_VERSION = "0.1.1"

# The hatchling wheel-packages entry that bundles the whole package dir
# (incl. py.typed) into the built wheel.
WHEEL_PACKAGE = "src/proactive_loop"

# README section headers that MUST survive (Behavior 6: no section removed).
README_SECTIONS = (
    "## The three layers",
    "## Quickstart",
    "## CLI",
    "## Configuration (environment variables)",
    "## How the offline scripted provider works",
    "## License",
)

# SPEC section headers that MUST survive (Behavior 7: additive only).
SPEC_SECTIONS = (
    "## 1. Concept",
    "## 2. Layout",
    "## 3. Foundation contracts",
    "## 4. Module contracts",
    "## 5. Non-negotiables",
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _marker_path() -> Path:
    """The marker path colocated with the package's ``__init__.py``."""
    return Path(proactive_loop.__file__).with_name("py.typed")


def _load_pyproject() -> dict:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)


# ==========================================================================
# Behavior 1 --- Marker exists and is co-located with the package.
# ==========================================================================


def test_b1_marker_is_colocated_regular_file():
    p = _marker_path()
    assert p.is_file(), (
        f"py.typed must exist as a regular file next to __init__.py; "
        f"looked at {p}"
    )
    # It must sit in the same directory as the package __init__.py.
    assert p.parent == Path(proactive_loop.__file__).parent, (
        "py.typed must live in the package directory, alongside __init__.py"
    )
    assert p.name == "py.typed"


# ==========================================================================
# Behavior 2 --- Marker is empty (bare ``typed`` marker; never ``partial``).
# ==========================================================================


def test_b2_marker_is_zero_bytes():
    p = _marker_path()
    assert p.stat().st_size == 0, (
        f"py.typed must be exactly 0 bytes (bare inline-types marker); "
        f"got st_size={p.stat().st_size}"
    )


def test_b2_marker_has_no_content_and_no_partial():
    data = _marker_path().read_bytes()
    assert data == b"", f"py.typed must be byte-empty; got {data!r}"
    assert b"partial" not in data, (
        "py.typed MUST NOT contain 'partial' (that would declare only "
        "partial/stub typing, not full inline types)"
    )


# ==========================================================================
# Behavior 3 --- Marker is a real, importable package resource (offline proxy
# for wheel inclusion).
# ==========================================================================


def test_b3_marker_is_importable_package_resource():
    res = importlib.resources.files("proactive_loop").joinpath("py.typed")
    assert res.is_file(), (
        "py.typed must be a genuine member of the importable 'proactive_loop' "
        "package (importlib.resources), not a stray file outside it"
    )


# ==========================================================================
# Behavior 4 --- Wheel-packaging config drift-guard.
# ==========================================================================


def test_b4_wheel_packages_includes_package_dir():
    cfg = _load_pyproject()
    packages = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert isinstance(packages, list), (
        "tool.hatch.build.targets.wheel.packages must be a list"
    )
    assert WHEEL_PACKAGE in packages, (
        f"wheel.packages must include {WHEEL_PACKAGE!r} so hatchling bundles "
        f"the whole package dir (incl. py.typed) into the wheel; got {packages!r}"
    )


# ==========================================================================
# Behavior 5 --- No version bump; no new public surface.
# ==========================================================================


def test_b5_version_unchanged_via_dunder():
    assert __version__ == EXPECTED_VERSION, (
        f"__version__ must stay {EXPECTED_VERSION!r} (additive package data, "
        f"no version bump); got {__version__!r}"
    )


def test_b5_version_unchanged_in_pyproject():
    # The __init__ dunder and pyproject are the single-source pair; both pinned.
    cfg = _load_pyproject()
    assert cfg["project"]["version"] == EXPECTED_VERSION, (
        f"pyproject project.version must stay {EXPECTED_VERSION!r}; "
        f"got {cfg['project']['version']!r}"
    )


def test_b5_cli_version_unchanged(capsys):
    # argparse's version action prints "<prog> <version>" then exits 0 --- the
    # pre-existing contract (iter-05/07/28/42). The marker must not perturb it.
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0, "`pla --version` must exit 0"
    out = capsys.readouterr().out
    assert EXPECTED_VERSION in out, (
        f"`pla --version` must print {EXPECTED_VERSION!r}; got {out!r}"
    )
    assert "pla 0.1.1" in out, (
        f"`pla --version` must still print 'pla 0.1.1' (unchanged); got {out!r}"
    )


def test_b5_marker_adds_no_python_submodule():
    # The marker is INERT DATA, not code: it must not become an importable
    # submodule and must not surface as a package attribute.
    import importlib.util

    assert importlib.util.find_spec("proactive_loop.py") is None
    assert not hasattr(proactive_loop, "py"), (
        "py.typed must be package DATA, never a code attribute of the package"
    )


# ==========================================================================
# Behavior 6 --- README documents the typed export (additive only).
# ==========================================================================


def test_b6_readme_mentions_pep561_and_py_typed():
    text = README.read_text(encoding="utf-8")
    assert "PEP 561" in text, (
        "README must contain the case-sensitive substring 'PEP 561'"
    )
    assert "py.typed" in text, (
        "README must contain the substring 'py.typed'"
    )


def test_b6_readme_sections_preserved():
    text = README.read_text(encoding="utf-8")
    for section in README_SECTIONS:
        assert section in text, (
            f"README edit must be additive --- existing section {section!r} "
            f"must not be removed"
        )


# ==========================================================================
# Behavior 7 --- SPEC layout stays honest (additive only).
# ==========================================================================


def test_b7_spec_lists_py_typed():
    text = SPEC.read_text(encoding="utf-8")
    assert "py.typed" in text, (
        "SPEC.md §2 layout must list the 'py.typed' marker"
    )


def test_b7_spec_sections_preserved():
    text = SPEC.read_text(encoding="utf-8")
    for section in SPEC_SECTIONS:
        assert section in text, (
            f"SPEC edit must be additive --- existing section {section!r} "
            f"must not be removed"
        )
