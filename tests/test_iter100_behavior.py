"""Black-box behavior tests for iteration 93 (factory iter 100) --- align the
Makefile ``setup:`` recipe to ``uv sync --locked`` for local/CI dependency
reproducibility parity (ROADMAP #100).

Feature under test (``pm.md``): CI (``.github/workflows/ci.yml``) installs with
``uv sync --locked``, which fails the build on ANY ``uv.lock`` drift. The
front-door ``make setup`` command, however, ran bare ``uv sync``, which can
SILENTLY mutate ``uv.lock`` when ``pyproject.toml`` drifts and thereby hand a
contributor an environment unlike the one every push is graded against. This
iteration changes the ``setup:`` recipe to ``uv sync --locked`` so a clean
``make setup`` resolves the EXACT locked dependency set CI grades against,
turning a silent divergence into a loud, fixable error. It is build-tooling
ONLY: no ``src/`` runtime change, no dependency add/remove (``uv.lock`` /
``pyproject.toml`` unchanged, so CI's ``--locked`` step stays green), no new CLI
verb / flag / collector / tool, and no version bump.

ISOLATION CONTRACT (honored): these tests are written strictly against THIS
iteration's public contract --- the spec's Expected Behaviors (``pm.md``) and the
public build artifact ``Makefile`` --- and drive ONLY the documented public
surface (the parsed text of ``Makefile``: its ``.PHONY`` line and the
tab-indented recipe lines of each named target). **No file under ``src/`` was
read, no engineer/reviewer notes were read, and no ``git diff`` was consulted.**
The spec-declared strings (``uv sync --locked``, the six target names) are
encoded here as the CONTRACT's ground facts, NOT imported from any
implementation, so the suite would go RED on a silent drift. Every test is fully
offline: zero network, zero API keys, no live provider --- pure file reads.
"""

from __future__ import annotations

import re
from pathlib import Path

# --------------------------------------------------------------------------
# Tester's ground facts --- the spec-declared contract constants (pm.md).
# Encoded here as constants (NOT imported from the implementation) so these
# tests encode the CONTRACT and would catch a silent drift.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"

# The exact install invocation the setup recipe must use (behavior 1) --- the
# same flag CI's install step already grades against.
LOCKED_INSTALL = "uv sync --locked"

# Every target that must survive this additive edit (behavior 4): each must
# remain declared in .PHONY and keep a non-empty recipe. Matches pm.md's list.
EXPECTED_TARGETS = ("setup", "test", "cov", "typecheck", "demo", "clean")


# --------------------------------------------------------------------------
# Helpers --- mirror the Makefile-reading pattern established in iter97
# (tests/test_iter97_behavior.py: _makefile_lines / _phony_tokens / _make_recipe).
# --------------------------------------------------------------------------


def _makefile_lines() -> list[str]:
    return MAKEFILE.read_text(encoding="utf-8").splitlines()


def _phony_tokens() -> set[str]:
    """The set of target names declared on the Makefile ``.PHONY:`` line(s)."""
    tokens: set[str] = set()
    for ln in _makefile_lines():
        if ln.startswith(".PHONY:"):
            tokens.update(ln.split(":", 1)[1].split())
    return tokens


def _make_recipe(target: str) -> list[str]:
    """The tab-indented recipe lines of a Makefile ``target:`` (each stripped).

    Blank lines inside a recipe are tolerated (skipped); the recipe ends at the
    first non-tab-indented, non-blank line after the target header.
    """
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


# ==========================================================================
# Behavior 1 --- the setup recipe invokes `uv sync --locked`.
# ==========================================================================


def test_b1_setup_recipe_invokes_uv_sync_locked():
    recipe = _make_recipe("setup")
    assert recipe, "Makefile must define a `setup:` target with a non-empty recipe"
    recipe_text = "\n".join(recipe)
    assert LOCKED_INSTALL in recipe_text, (
        f"the `setup:` recipe must invoke {LOCKED_INSTALL!r} so a local install "
        "resolves the EXACT locked dependency set CI grades against; got recipe:\n"
        f"{recipe_text}"
    )


def test_b1_uv_sync_locked_is_on_a_recipe_line_not_a_comment():
    # The substring must appear on an actual recipe (tab-indented, stripped)
    # line, not merely in a WHY comment above the target.
    recipe = _make_recipe("setup")
    hits = [ln for ln in recipe if LOCKED_INSTALL in ln]
    assert hits, (
        f"{LOCKED_INSTALL!r} must appear on a RECIPE line of `setup:`, "
        f"not only in a comment; setup recipe lines: {recipe!r}"
    )


# ==========================================================================
# Behavior 2 --- no bare `uv sync` (without --locked) remains in the recipe.
# ==========================================================================


def test_b2_no_bare_uv_sync_in_setup_recipe():
    recipe = _make_recipe("setup")
    assert recipe, "Makefile must define a `setup:` target with a non-empty recipe"
    offenders = [ln for ln in recipe if "uv sync" in ln and "--locked" not in ln]
    assert not offenders, (
        "no `setup:` recipe line may invoke `uv sync` WITHOUT `--locked` "
        "(a bare `uv sync` can silently mutate uv.lock and diverge from CI); "
        f"offending recipe line(s): {offenders!r}"
    )


# ==========================================================================
# Behavior 3 --- `setup` is still declared in .PHONY.
# ==========================================================================


def test_b3_setup_declared_phony():
    tokens = _phony_tokens()
    assert "setup" in tokens, (
        f"Makefile .PHONY must still declare 'setup'; found tokens {sorted(tokens)}"
    )


# ==========================================================================
# Behavior 4 --- additive-edit guard: every pre-existing target survives
# (declared in .PHONY AND keeps a non-empty recipe).
# ==========================================================================


def test_b4_all_expected_targets_declared_phony():
    tokens = _phony_tokens()
    for target in EXPECTED_TARGETS:
        assert target in tokens, (
            f"pre-existing .PHONY token {target!r} must remain (nothing removed); "
            f"found tokens {sorted(tokens)}"
        )


def test_b4_all_expected_targets_have_nonempty_recipe():
    for target in EXPECTED_TARGETS:
        recipe = _make_recipe(target)
        assert recipe, (
            f"pre-existing Makefile target {target!r} must still be defined with a "
            "non-empty recipe (nothing removed or emptied by this edit)"
        )
