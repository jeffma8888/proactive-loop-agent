"""Black-box behavior tests for iteration 96 (factory iter 103) --- an
offline-first SOURCE-IMPORT GUARD over ``src/proactive_loop`` (ROADMAP #103).

Feature under test (``pm.md``): the product's #1 quality-bar constraint is
"Offline-first: NO network at runtime or in tests." Before this iteration the
only executable enforcement was a banned-import list scoped to ONE test file
(``test_iter102_behavior.py``, guarding only that file's own imports); NOTHING
guarded the runtime ``src`` tree. This iteration turns that loudest public
promise into a CI-graded oracle: a pure-``ast`` guard that scans every file
under ``src/proactive_loop/`` and fails the build if any imports a network
module (``socket``/``ssl``/``urllib``/``http``/``requests``/``httpx``/
``aiohttp``/``urllib3``). It PASSES today (``src`` has zero network imports;
``subprocess`` is legitimately used by ``cli.py`` and the git collectors and is
NOT banned), so it is a zero-behavior-change, smallest-reversible lock -- the
same kind of unbound-claim close the mypy oracle gave "fully type-hinted".

ISOLATION CONTRACT (honored): these tests are written strictly against THIS
iteration's public contract --- the spec's Expected Behaviors (``pm.md``) --- and
verify observable output only. The guard scans the ``src/proactive_loop`` tree
AS DATA (an established pattern here: the iter102 Makefile/ci.yml drift-guard and
the README contract test do the same), parsing import STATEMENTS via the stdlib
AST; it never interprets the modules' behavior. **No source file was read to
learn its implementation, no engineer/reviewer notes were read, and no
``git diff`` was consulted.** The banned set and expected scan-scope facts are
encoded here as the CONTRACT's ground facts (from ``pm.md``), NOT imported from
any implementation, so a silent regression (a network import creeping into
``src``) would go RED. Every test is fully offline and cap-safe: ``ast.parse`` of
~33 small files plus a handful of synthetic-string parses is milliseconds, with
zero network and --- by construction (import-scan only) --- no subprocess, no
build, and no execution of the scanned modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# Tester's ground facts --- the spec-declared contract constants (pm.md).
# Encoded here (NOT imported from the implementation) so these tests encode the
# CONTRACT and would catch a silent regression.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "proactive_loop"

# EB4: the eight TOP-LEVEL modules the guard MUST treat as network/banned.
BANNED_NETWORK_MODULES = frozenset(
    {"socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp", "urllib3"}
)


# --------------------------------------------------------------------------
# The guard's detection routine, re-implemented here as the black-box oracle:
# identify banned network imports STRUCTURALLY via the AST (Import /
# ImportFrom nodes), keyed on the TOP-LEVEL (first dotted component) module
# name. Mentions inside strings / comments / docstrings are invisible to the
# AST and are never flagged (the AST-vs-grep discriminator). Relative imports
# (`from . import x`, level > 0) are intra-package and never network, so they
# are skipped.
# --------------------------------------------------------------------------


def _network_import_offenders(
    source: str, filename: str = "<synthetic>"
) -> list[tuple[str, str]]:
    """Return ``(filename, top_level_module)`` for every banned network import
    found in ``source``. Empty list == clean."""
    tree = ast.parse(source, filename=filename)
    offenders: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in BANNED_NETWORK_MODULES:
                    offenders.append((filename, top))
        elif isinstance(node, ast.ImportFrom):
            # relative import (level > 0) is intra-package, never network
            if node.level and node.level > 0:
                continue
            if node.module is None:
                continue
            top = node.module.split(".")[0]
            if top in BANNED_NETWORK_MODULES:
                offenders.append((filename, top))
    return offenders


def _all_src_files() -> list[Path]:
    """Every ``*.py`` under ``src/proactive_loop`` (recursive), sorted."""
    return sorted(SRC.rglob("*.py"))


def _scan_real_tree() -> list[tuple[str, str]]:
    """Run the guard over the real ``src/proactive_loop`` tree; return offenders
    as ``(repo-relative path, banned module)`` pairs."""
    offenders: list[tuple[str, str]] = []
    for f in _all_src_files():
        rel = str(f.relative_to(REPO))
        offenders.extend(
            _network_import_offenders(f.read_text(encoding="utf-8"), rel)
        )
    return offenders


# ==========================================================================
# EB1 --- Passes on the current tree (the offline guarantee holds today).
# ==========================================================================


def test_eb1_real_src_tree_has_zero_network_imports():
    offenders = _scan_real_tree()
    assert not offenders, (
        "src/proactive_loop must import NO network module (offline-first quality "
        f"bar: 'NO network at runtime or in tests'); offenders: {offenders}"
    )


# ==========================================================================
# EB2 --- Whole-tree recursive scope.
# ==========================================================================


def test_eb2_scan_is_nonempty_and_covers_at_least_30_files():
    files = _all_src_files()
    assert len(files) >= 30, (
        f"the guard must scan the WHOLE recursive tree; expected >= 30 *.py files "
        f"under {SRC.relative_to(REPO)}, found {len(files)}"
    )


def test_eb2_scan_includes_top_level_modules():
    rel = {str(f.relative_to(SRC)) for f in _all_src_files()}
    for top in ("cli.py", "config.py", "models.py", "scheduler.py", "__init__.py"):
        assert top in rel, (
            f"top-level module {top!r} must be within scan scope (whole-tree "
            f"recursive); scanned files: {sorted(rel)}"
        )


def test_eb2_scan_includes_each_named_subpackage():
    subpkgs = {
        f.relative_to(SRC).parts[0]
        for f in _all_src_files()
        if len(f.relative_to(SRC).parts) > 1
    }
    for sub in ("collectors", "llm", "loop", "scout"):
        assert sub in subpkgs, (
            f"subpackage {sub!r} must be within scan scope; found subpackages "
            f"{sorted(subpkgs)}"
        )


# ==========================================================================
# EB3 --- Import detection covers all syntactic forms (AST, not text grep).
# ==========================================================================

_IMPORT_FORMS = [
    ("import socket", "socket"),
    ("import socket as s", "socket"),
    ("import urllib.request", "urllib"),
    ("from urllib import request", "urllib"),
    ("from http.client import HTTPConnection", "http"),
    ("from ssl import SSLContext", "ssl"),
]


@pytest.mark.parametrize("source, expected_module", _IMPORT_FORMS)
def test_eb3_detects_every_import_form(source: str, expected_module: str):
    offenders = _network_import_offenders(source, "synthetic.py")
    modules = {mod for _, mod in offenders}
    assert expected_module in modules, (
        f"the guard must flag {source!r} as importing the banned top-level "
        f"module {expected_module!r} (AST Import/ImportFrom, keyed on first "
        f"dotted component); got offenders {offenders}"
    )


# ==========================================================================
# EB4 --- Banned set (all eight; message names both file and module).
# ==========================================================================


@pytest.mark.parametrize("mod", sorted(BANNED_NETWORK_MODULES))
def test_eb4_each_banned_module_is_reported_with_file_and_module(mod: str):
    offenders = _network_import_offenders(f"import {mod}\n", "danger.py")
    assert offenders, f"banned network module {mod!r} must be reported as an offender"
    files = {f for f, _ in offenders}
    modules = {m for _, m in offenders}
    assert mod in modules, (
        f"the offender must NAME the offending module {mod!r}; got {offenders}"
    )
    assert "danger.py" in files, (
        f"the offender must NAME the offending file 'danger.py'; got {offenders}"
    )


def test_eb4_banned_set_includes_at_least_the_eight_required():
    required = {
        "socket",
        "ssl",
        "urllib",
        "http",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
    }
    assert required <= BANNED_NETWORK_MODULES, (
        "the guard MUST ban at least these eight network modules; missing: "
        f"{sorted(required - BANNED_NETWORK_MODULES)}"
    )


# ==========================================================================
# EB5 --- subprocess and non-network imports are ALLOWED (not flagged).
# ==========================================================================

_ALLOWED_IMPORTS = [
    "import subprocess",
    "import subprocess as sp",
    "from subprocess import run",
    "import os",
    "import pathlib",
    "from pathlib import Path",
    "import json",
    "import ast",
    "import dataclasses",
    "from dataclasses import dataclass",
    "import pydantic",
    "from pydantic import BaseModel",
]


@pytest.mark.parametrize("source", _ALLOWED_IMPORTS)
def test_eb5_allowed_imports_are_not_flagged(source: str):
    offenders = _network_import_offenders(source, "ok.py")
    assert not offenders, (
        f"the guard bans NETWORK modules only, not external processes or the "
        f"stdlib; {source!r} must NOT be flagged (subprocess is legitimately used "
        f"by cli.py and the git collectors); got {offenders}"
    )


# ==========================================================================
# EB6 --- No false positive on mentions in strings / comments / docstrings.
# (The AST-vs-grep discriminator.)
# ==========================================================================


def test_eb6_no_false_positive_on_string_comment_docstring_mentions():
    source = (
        '"""This module talks about socket and urllib in its docstring."""\n'
        "# uses urllib and http and requests conceptually\n"
        "import os\n"
        "import json\n"
        "\n"
        'url = "http://example.com"\n'
        'note = "we deliberately avoid httpx and aiohttp here"\n'
        "# socket ssl urllib3 requests\n"
        "\n"
        "def f() -> str:\n"
        '    """Return a urllib-flavored string without importing socket."""\n'
        '    return "socket urllib http ssl requests httpx aiohttp urllib3"\n'
    )
    offenders = _network_import_offenders(source, "mentions.py")
    assert not offenders, (
        "banned names mentioned ONLY in strings / comments / docstrings (never "
        "actually imported) must NOT be flagged --- this is the AST-vs-grep "
        f"discriminator a naive source grep would fail; got {offenders}"
    )


def test_eb6_discriminates_real_import_from_string_mention():
    # A file that mentions banned names in prose/strings AND has ONE real banned
    # import: only the genuinely-imported module is reported.
    source = (
        '"""mentions socket and urllib only in prose."""\n'
        'url = "http://example.com/socket/urllib"\n'
        "import requests  # a real banned import\n"
    )
    offenders = _network_import_offenders(source, "mixed.py")
    modules = {m for _, m in offenders}
    assert modules == {"requests"}, (
        "only the actually-imported banned module ('requests') may be reported, "
        f"not the string-mentioned ones ('socket'/'urllib'/'http'); got {offenders}"
    )
