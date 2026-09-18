"""Black-box behavior tests for factory iteration 310 (ROADMAP #290) -- ``SPEC.md``
section 4.6's ``Makefile`` bullet names EVERY recipe the ``Makefile`` declares, bound
two-sided to the ``Makefile``'s own ``target:`` lines with an EMPTY exempt set.

WHY this module exists. ``SPEC.md`` stated the recipe set TWICE and the two sites
disagreed: the section 2 layout fence's ``Makefile`` comment listed 11 recipes (and is
already guarded EMPTY-or-COMPLETE by ``tests/test_spec_layout_contract.py``), while the
section 4.6 prose bullet -- the site a contributor reads to learn how this repo is built
and verified -- named 4. The 7 it hid are the load-bearing ones: ``typecheck`` (the only
oracle for the README's PEP 561 claim), plus all three local gates ``check``,
``check-matrix`` (the both-legs 3.12/3.13 gate) and ``clone-check`` (the fresh-clone
gate), plus ``cov``, ``readme-headroom`` and ``help`` itself.

Three design decisions worth a reader's time:

1. **Two-sided with an EMPTY exempt set.** A one-sided "every target is documented"
   guard lets the prose keep naming a recipe that has been renamed or deleted; a
   one-sided "every documented recipe exists" guard lets a new recipe ship
   undocumented. Both directions are checked, and no target is exempt -- the failure
   message names the offenders so a future author does not have to re-derive them.

2. **The comparison is a PURE HELPER over TEXT.** ``bullet_problems(bullet_text,
   makefile_text)`` reads no file and patches no attribute, so the both-directions proof
   is a synthetic argument pair, not a temporary edit to a tracked file. A guard that
   can only be exercised against the one currently-correct pair on disk is a guard whose
   detection has never been observed.

3. **The bullet's own label is excluded by construction, not by an exempt list.** The
   anchor token ``Makefile`` is backticked and matches the target-name shape exactly, so
   the soundness census reads only the text AFTER the bullet's first colon. Naming it in
   an exemption set instead would be an exemption that grows.

This module deliberately does NOT re-assert the ROADMAP char wall
(``tests/test_iter241_behavior.py`` owns it), the live index-row floor
(``tests/test_iter168_behavior.py``), or the published suite-size floor
(``tests/test_readme_and_ci_contract.py``). A second spelling of any of those is the
same duplication defect in a new place.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: A ``Makefile`` target declaration -- never a tab-indented recipe body line.
TARGET_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):")

#: A backticked token in Markdown prose.
BACKTICKED_RE = re.compile(r"`([^`]+)`")

#: The shape a ``Makefile`` target name has; anything else in the prose (paths, flags,
#: whole commands such as ``uv sync``) is ignored by construction.
TARGET_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

#: The section 2 layout-fence row for the ``Makefile``, e.g.
#: ``|-- Makefile   # help setup test ...``.
FENCE_ROW_RE = re.compile(r"^[^#`]*\bMakefile\s{2,}#\s*(?P<names>\S.*)$")

BULLET_ANCHOR = "- `Makefile`:"

#: The seven recipes the pre-change bullet hid. Spelled as literals on purpose: an
#: oracle whose needles are all derived can pass by parsing nothing.
PREVIOUSLY_HIDDEN = (
    "help",
    "cov",
    "typecheck",
    "readme-headroom",
    "check",
    "check-matrix",
    "clone-check",
)


def declared_targets(makefile_text: str) -> list[str]:
    """Ordered target names declared by ``makefile_text``, duplicates preserved."""
    return [
        match.group(1)
        for match in (
            TARGET_LINE_RE.match(line) for line in makefile_text.splitlines()
        )
        if match is not None
    ]


def documented_recipes(bullet_text: str) -> list[str]:
    """Target-shaped backticked tokens after the bullet's label, in document order.

    The text before the first colon is dropped so the bullet's own ``Makefile`` label --
    backticked and target-shaped -- cannot be read as a member of the set it labels.
    """
    _, _, body = bullet_text.partition(":")
    return [
        token
        for token in BACKTICKED_RE.findall(body)
        if TARGET_NAME_RE.match(token) is not None
    ]


def bullet_problems(bullet_text: str, makefile_text: str) -> list[str]:
    """Two-sided drift between a documenting bullet and a ``Makefile``'s targets.

    Returns one human-readable problem per direction, or ``[]`` when the bullet names
    exactly the declared target set. Pure: reads nothing, writes nothing.
    """
    declared = declared_targets(makefile_text)
    documented = documented_recipes(bullet_text)
    problems: list[str] = []
    undocumented = [name for name in declared if name not in documented]
    if undocumented:
        problems.append(f"declared but not documented: {undocumented}")
    unknown = [name for name in documented if name not in declared]
    if unknown:
        problems.append(f"documented but not declared: {unknown}")
    return problems


def spec_lines() -> list[str]:
    return (REPO / "SPEC.md").read_text(encoding="utf-8").splitlines()


def makefile_text() -> str:
    return (REPO / "Makefile").read_text(encoding="utf-8")


def bullet_anchor_indices(lines: list[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if line.lstrip().startswith(BULLET_ANCHOR)]


def makefile_bullet_lines() -> list[str]:
    """The unique ``- `Makefile`:`` bullet, first line through its last continuation."""
    lines = spec_lines()
    anchors = bullet_anchor_indices(lines)
    assert len(anchors) == 1, f"expected exactly 1 {BULLET_ANCHOR!r} bullet, got {anchors}"
    start = anchors[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    collected = [lines[start]]
    for line in lines[start + 1 :]:
        stripped = line.strip()
        own_indent = len(line) - len(line.lstrip())
        if not stripped or stripped.startswith("#"):
            break
        if stripped.startswith("- ") and own_indent <= indent:
            break
        collected.append(line)
    return collected


def test_the_makefile_bullet_documents_every_declared_recipe() -> None:
    """Expected Behaviors 1, 2, 3, 4, 6 and 7 of factory iteration 310, in spec order.

    Graded as ONE collected item on purpose. ``make readme-headroom`` on the tree this
    lands on reports ``live=6090 binding_at=6099 binding_headroom=8`` against
    ``tests/test_iter263_behavior.py``'s ``MIN_BINDING_HEADROOM = 6``, so this whole
    module may add at most TWO collected items before a shipped assertion goes red on a
    public build. The repo's own precedent for that squeeze is
    ``tests/test_iter264_behavior.py``, which folds nine behaviors into one item for
    exactly this reason. Each section below carries its own failure message, so a red
    still names the behavior that broke.
    """
    lines = spec_lines()
    makefile = makefile_text()

    # Behavior 1 -- the anchor is total: zero or two bullets is a failure.
    anchors = bullet_anchor_indices(lines)
    assert len(anchors) == 1, (
        f"Behavior 1: SPEC.md must carry exactly one {BULLET_ANCHOR!r} bullet so this "
        f"guard has a single binding site; found {len(anchors)} at 1-based lines "
        f"{[i + 1 for i in anchors]}"
    )

    bullet_lines = makefile_bullet_lines()
    bullet = "\n".join(bullet_lines)
    declared = sorted(set(declared_targets(makefile)))
    documented = documented_recipes(bullet)

    # Behaviors 2 and 3 -- complete AND sound, with an EMPTY exempt set.
    problems = bullet_problems(bullet, makefile)
    assert problems == [], (
        "Behaviors 2+3: SPEC.md's `Makefile` bullet has drifted from the Makefile's own "
        f"`target:` lines -- {problems}"
    )
    assert sorted(set(documented)) == declared, (
        f"Behaviors 2+3: documented={sorted(set(documented))} declared={declared}"
    )
    assert "Makefile" not in documented, (
        "Behavior 3: the bullet's own backticked label leaked into the documented set -- "
        "the soundness census must read only the text after the first colon"
    )

    # Behavior 4 -- anti-vacuity, spelled with literal names so the oracle cannot pass
    # by parsing nothing.
    hidden_missing = [name for name in PREVIOUSLY_HIDDEN if f"`{name}`" not in bullet]
    assert hidden_missing == [], (
        "Behavior 4: these recipes were hidden by the pre-change bullet and must be "
        f"named in it: {hidden_missing}"
    )

    # Behavior 6 -- SPEC.md's TWO recipe sites agree with each other and the Makefile,
    # so editing either site alone reds the build.
    fence_rows = [
        match.group("names")
        for match in (FENCE_ROW_RE.match(line) for line in lines)
        if match is not None
    ]
    assert len(fence_rows) == 1, (
        f"Behavior 6: expected one layout-fence Makefile row, got {fence_rows}"
    )
    fenced = fence_rows[0].split()
    assert all(TARGET_NAME_RE.match(name) for name in fenced), (
        f"Behavior 6: the fence comment holds a non-target-shaped token: {fenced}"
    )
    assert sorted(set(fenced)) == declared == sorted(set(documented)), (
        f"Behavior 6: fence={sorted(set(fenced))} declared={declared} "
        f"bullet={sorted(set(documented))} -- SPEC.md's two recipe sites must agree"
    )

    # Behavior 7 -- documenting eleven recipes must not balloon section 4.6.
    assert len(bullet_lines) <= 12, (
        f"Behavior 7: the bullet grew to {len(bullet_lines)} lines"
    )
    assert len(bullet) <= 900, f"Behavior 7: the bullet grew to {len(bullet)} chars"


def test_the_drift_guard_fires_in_both_directions_on_synthetic_text() -> None:
    """Expected Behavior 5 -- detection is OBSERVED, not assumed.

    A guard exercised only against the one currently-correct pair on disk has never been
    seen to fail, so this item hands the pure helper synthetic TEXT: no file is written
    and no attribute is monkeypatched.
    """
    shipped_bullet = "\n".join(makefile_bullet_lines())
    shipped_makefile = makefile_text()
    assert bullet_problems(shipped_bullet, shipped_makefile) == [], (
        "the shipped pair must be clean before the negatives prove anything"
    )

    # (a) a recipe added to the Makefile and left undocumented.
    grown = f"{shipped_makefile}\nship-it:\n\t@echo shipping\n"
    grown_problems = bullet_problems(shipped_bullet, grown)
    assert grown_problems, "an undocumented new target must be reported"
    assert "ship-it" in " ".join(grown_problems), grown_problems

    # (b) one recipe's backticked name removed from the bullet.
    unbackticked = shipped_bullet.replace("`clone-check`", "clone-check")
    assert unbackticked != shipped_bullet, "fixture needle absent from the bullet"
    thinned_problems = bullet_problems(unbackticked, shipped_makefile)
    assert thinned_problems, "a recipe dropped from the bullet must be reported"
    assert "clone-check" in " ".join(thinned_problems), thinned_problems

    # (c) the soundness direction: prose naming a recipe that does not exist.
    invented = f"{shipped_bullet} and `no-such-recipe` (invented)."
    invented_problems = bullet_problems(invented, shipped_makefile)
    assert invented_problems, "a documented non-existent recipe must be reported"
    assert "no-such-recipe" in " ".join(invented_problems), invented_problems
