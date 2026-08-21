"""Black-box behavior tests for iteration 97 --- bite 3 (FINAL) of the
"fully type-hinted" mypy oracle (ROADMAP #97).

Feature under test (``pm.md``): mypy is pinned as a LOCKED dev dependency
(``uv.lock`` regenerated in the same commit), and the README's public
"fully type-hinted (ships a PEP 561 ``py.typed`` marker)" claim is bound to a
PERMANENT machine oracle via a ``make typecheck`` target + a CI type step. Bites
1-2 (iters 95-96) made the whole ``src/proactive_loop`` package mypy-clean; this
bite makes the check reproducible and machine-enforced so the public claim can
never silently rot. This is build-tooling + docs ONLY: no ``src/`` runtime
change, no ``SPEC.md`` contract change, no ``__version__`` bump (stays
``0.1.1``), no new CLI verb / tool / collector / provider.

The type oracle itself (``uv run mypy src/proactive_loop`` -> exit 0 /
``Success: no issues found``) is the IN-STAGE AC command run by
engineer/reviewer/tester/final; it is deliberately NOT a pytest test here
(running a type-checker in-suite adds latency + fragility, and the permanent
oracle is the CI step + ``make typecheck``). These pytest behaviors instead
assert that the WIRING EXISTS AS TEXT, mirroring
``tests/test_readme_and_ci_contract.py``.

ISOLATION CONTRACT (honored): these tests are written strictly against THIS
iteration's public contract --- the spec's Expected Behaviors (``pm.md``),
``README.md``, and the public build artifacts (``pyproject.toml``, ``uv.lock``,
``Makefile``, ``.github/workflows/ci.yml``) --- and drive ONLY documented public
surfaces: the parsed TOML of ``pyproject.toml``, the text of ``uv.lock`` /
``Makefile`` / the CI workflow / ``README.md``, and the live
``proactive_loop`` package (its ``__version__``, ``all_collectors()``,
``build_parser()`` choices, ``VALID_PROVIDERS``, ``ToolRegistry.tool_names()``,
and the ``pla --version`` CLI). **No file under ``src/`` was read (beyond
importing the package), no engineer/reviewer notes were read, and no ``git
diff`` was consulted.** The declared strings (``mypy``, ``make typecheck``,
``mypy src/proactive_loop``, the three CI commands, the README claim tokens) are
encoded here as the spec's ground facts, NOT imported from the implementation,
so the suite encodes the CONTRACT and would go RED on a silent drift. Every test
is fully offline: zero network, zero API keys, no live provider.
"""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop import __version__
from proactive_loop.cli import build_parser, main
from proactive_loop.collectors import all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry

# --------------------------------------------------------------------------
# Tester's ground facts --- the spec-declared contract constants (pm.md).
# Encoded here as constants, NOT imported from the implementation, so the tests
# encode the CONTRACT and would catch a silent drift.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
UV_LOCK = REPO / "uv.lock"
MAKEFILE = REPO / "Makefile"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
README = REPO / "README.md"

MARKER = "PORTFOLIO INTRO"  # the human-owned-boundary marker in README.md
EXPECTED_VERSION = "0.1.1"

# The typecheck oracle string --- ALWAYS assert this FULL substring, never the
# bare "src/proactive_loop" token (which also appears in prose/WHY comments).
TYPECHECK_CMD = "mypy src/proactive_loop"

# The three pre-existing CI commands that must remain present (offline claim +
# demo). Same set the pre-existing test_readme_and_ci_contract.py guards.
CI_COMMANDS = ("uv sync --locked", "uv run pytest", "make demo")

# Pre-existing Makefile targets/.PHONY tokens that must survive (additive edit).
PREEXISTING_MAKE_TARGETS = ("setup", "test", "cov", "demo", "clean")

# Pre-existing dev deps that must remain in [dependency-groups].dev.
PREEXISTING_DEV_DEPS = ("pytest", "pytest-cov")

# README section headers that MUST survive (additive-only edit; no section
# removed). Same set as the pre-existing tests/test_iter58_behavior.py.
README_SECTIONS = (
    "## The three layers",
    "## Quickstart",
    "## CLI",
    "## Configuration (environment variables)",
    "## How the offline scripted provider works",
    "## License",
)

# Live-registry expected counts (behavior 6: no drift).
EXPECTED_COLLECTORS = 17
EXPECTED_VERBS = 17
EXPECTED_TOOLS = 14
EXPECTED_PROVIDERS = 7


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _load_pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _req_name(spec: str) -> str:
    """The requirement (distribution) name from a PEP 508 spec string.

    ``"mypy>=1.11"`` -> ``"mypy"``; ``"pytest-cov>=5.0"`` -> ``"pytest-cov"``.
    """
    return re.split(r"[<>=!~;\s\[(]", spec, maxsplit=1)[0].strip()


def _dev_deps() -> list[str]:
    data = _load_pyproject()
    dev = data.get("dependency-groups", {}).get("dev")
    assert isinstance(dev, list), (
        "pyproject.toml must define a [dependency-groups] dev LIST; "
        f"got {dev!r}"
    )
    return dev


def _makefile_lines() -> list[str]:
    return MAKEFILE.read_text(encoding="utf-8").splitlines()


def _phony_tokens() -> set[str]:
    tokens: set[str] = set()
    for ln in _makefile_lines():
        if ln.startswith(".PHONY:"):
            tokens.update(ln.split(":", 1)[1].split())
    return tokens


def _make_recipe(target: str) -> list[str]:
    """The tab-indented recipe lines of a Makefile ``target:`` (stripped)."""
    recipe: list[str] = []
    in_target = False
    for ln in _makefile_lines():
        if re.match(rf"^{re.escape(target)}\s*:", ln):
            in_target = True
            continue
        if in_target:
            if ln.startswith("\t"):
                recipe.append(ln.strip())
            elif ln.strip() == "":
                continue  # blank lines inside a recipe are tolerated
            else:
                break
    return recipe


def _readme_halves() -> tuple[str, str]:
    """(before_marker, after_marker) split of the README on the human-owned marker."""
    text = README.read_text(encoding="utf-8")
    assert MARKER in text, (
        f"README.md lost its {MARKER!r} marker --- automated contributors no "
        "longer have the human-owned boundary"
    )
    before, after = text.split(MARKER, 1)
    return before, after


def _verb_count() -> int:
    parser = build_parser()
    subs = [
        a
        for a in parser._subparsers._group_actions
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(subs) == 1, f"expected exactly one subparser action, got {len(subs)}"
    return len(subs[0].choices)


# ==========================================================================
# Behavior 1 --- mypy is a declared dev dependency (pytest/pytest-cov unchanged).
# ==========================================================================


def test_b1_mypy_declared_dev_dependency():
    dev = _dev_deps()
    names = {_req_name(entry) for entry in dev}
    assert "mypy" in names, (
        "[dependency-groups].dev must declare a 'mypy' requirement (e.g. "
        f"'mypy>=1.11'); dev requirement names present: {sorted(names)}"
    )
    # Its spec string must actually start with 'mypy' (^mypy), not just contain it.
    mypy_specs = [e for e in dev if re.match(r"^mypy(\b|[<>=!~\s\[])", e)]
    assert mypy_specs, (
        f"a dev entry must be a spec string matching ^mypy; dev list: {dev!r}"
    )


def test_b1_preexisting_dev_deps_remain():
    names = {_req_name(entry) for entry in _dev_deps()}
    for dep in PREEXISTING_DEV_DEPS:
        assert dep in names, (
            f"pre-existing dev dependency {dep!r} must remain in "
            f"[dependency-groups].dev; names present: {sorted(names)}"
        )


# ==========================================================================
# Behavior 2 --- uv.lock pins mypy (no --locked drift).
# ==========================================================================


def test_b2_uv_lock_pins_mypy():
    assert UV_LOCK.is_file(), "uv.lock must exist (CI runs `uv sync --locked`)"
    text = UV_LOCK.read_text(encoding="utf-8")
    assert 'name = "mypy"' in text, (
        "uv.lock must contain a package stanza `name = \"mypy\"` --- proving the "
        "lockfile was regenerated in the same commit, so CI `uv sync --locked` "
        "does not fail on lockfile drift"
    )


# ==========================================================================
# Behavior 3 --- Makefile exposes a `typecheck` target (mypy on the package).
# ==========================================================================


def test_b3_makefile_typecheck_target_in_phony_and_runs_mypy():
    tokens = _phony_tokens()
    assert "typecheck" in tokens, (
        f"Makefile .PHONY must declare 'typecheck'; found tokens {sorted(tokens)}"
    )
    recipe = _make_recipe("typecheck")
    assert recipe, "Makefile must define a `typecheck:` target with a recipe"
    recipe_text = "\n".join(recipe)
    assert "mypy" in recipe_text, (
        f"`typecheck:` recipe must invoke mypy; got:\n{recipe_text}"
    )
    assert "src/proactive_loop" in recipe_text, (
        f"`typecheck:` recipe must type-check src/proactive_loop; got:\n{recipe_text}"
    )


def test_b3_preexisting_make_targets_and_phony_survive():
    tokens = _phony_tokens()
    for target in PREEXISTING_MAKE_TARGETS:
        assert target in tokens, (
            f"pre-existing .PHONY token {target!r} must remain; got {sorted(tokens)}"
        )
        assert _make_recipe(target), (
            f"pre-existing Makefile target {target!r} must still be defined "
            "with a recipe"
        )


# ==========================================================================
# Behavior 4 --- CI machine-checks the type claim (three commands preserved).
# ==========================================================================


def test_b4_ci_workflow_runs_mypy_type_step():
    assert WORKFLOW.is_file(), (
        f"missing {WORKFLOW.relative_to(REPO)} --- the CI type oracle would not run"
    )
    text = WORKFLOW.read_text(encoding="utf-8")
    # Assert the FULL command substring (never a bare 'src/proactive_loop', which
    # also appears in the step's WHY comment).
    assert TYPECHECK_CMD in text, (
        f"CI workflow must run {TYPECHECK_CMD!r} as a step --- the permanent "
        "oracle for the README's 'fully type-hinted' claim"
    )


def test_b4_ci_workflow_keeps_the_three_preexisting_commands():
    text = WORKFLOW.read_text(encoding="utf-8")
    for command in CI_COMMANDS:
        assert command in text, (
            f"CI no longer runs {command!r}; adding the mypy step must be "
            "additive --- the three pre-existing commands stay present"
        )


# ==========================================================================
# Behavior 5 --- README documents the oracle BELOW the human-owned marker.
# ==========================================================================


def test_b5_readme_documents_make_typecheck_below_marker():
    _before, after = _readme_halves()
    assert "make typecheck" in after, (
        "README must document `make typecheck` in the AUTOMATED (below-marker) "
        "section --- the human-owned intro above the marker must not be rewritten"
    )


def test_b5_readme_intro_above_marker_keeps_the_type_claim():
    before, _after = _readme_halves()
    # NOTE: 'fully type-hinted' can legitimately appear BELOW the marker too
    # (the new reference note echoes the claim), so we assert only that the
    # human-owned intro ABOVE the marker still carries all three claim tokens ---
    # NOT that they are absent below.
    for token in ("fully type-hinted", "PEP 561", "py.typed"):
        assert token in before, (
            f"human-owned README intro (above the {MARKER!r} marker) must still "
            f"contain {token!r} --- the type claim it binds must not be deleted"
        )


def test_b5_readme_sections_preserved():
    text = README.read_text(encoding="utf-8")
    for section in README_SECTIONS:
        assert section in text, (
            f"README edit must be additive --- existing section {section!r} "
            "must not be removed"
        )


# ==========================================================================
# Behavior 6 --- no version bump, no registry drift.
# ==========================================================================


def test_b6_version_unchanged_via_dunder():
    assert __version__ == EXPECTED_VERSION, (
        f"__version__ must stay {EXPECTED_VERSION!r} (build-tooling-only bite, "
        f"no version bump); got {__version__!r}"
    )


def test_b6_version_unchanged_in_pyproject():
    cfg = _load_pyproject()
    assert cfg["project"]["version"] == EXPECTED_VERSION, (
        f"pyproject project.version must stay {EXPECTED_VERSION!r}; "
        f"got {cfg['project']['version']!r}"
    )


def test_b6_cli_version_prints_pla_0_1_1_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0, "`pla --version` must exit 0"
    out = capsys.readouterr().out
    assert "pla 0.1.1" in out, (
        f"`pla --version` must print a line containing 'pla 0.1.1'; got {out!r}"
    )


def test_b6_collector_count_unchanged():
    live = len(all_collectors())
    assert live == EXPECTED_COLLECTORS, (
        f"collector registry must have {EXPECTED_COLLECTORS} entries; got {live}"
    )


def test_b6_cli_verb_count_unchanged():
    live = _verb_count()
    assert live == EXPECTED_VERBS, (
        f"pla must expose {EXPECTED_VERBS} CLI verbs; got {live}"
    )


def test_b6_tool_registry_count_unchanged(tmp_path):
    ws = tmp_path / "workspace"
    art = tmp_path / "artifacts"
    ws.mkdir()
    art.mkdir()
    reg = ToolRegistry(workspace_root=ws, artifacts_dir=art)
    live = len(reg.tool_names())
    assert live == EXPECTED_TOOLS, (
        f"ToolRegistry must expose {EXPECTED_TOOLS} tools; got {live}"
    )


def test_b6_provider_count_unchanged():
    live = len(VALID_PROVIDERS)
    assert live == EXPECTED_PROVIDERS, (
        f"VALID_PROVIDERS must have {EXPECTED_PROVIDERS} entries; got {live}"
    )
