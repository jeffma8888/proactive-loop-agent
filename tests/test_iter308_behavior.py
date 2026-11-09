"""Factory iter 560 (ROADMAP #348): a tracked ``.python-version`` pins the fresh-clone leg.

A fresh clone's README on-ramp (``uv sync`` -> ``uv run pytest``) must resolve to an
interpreter the CI matrix actually grades, not whichever newest interpreter the host
happens to have (iter 559 reverted at preship because uv picked a host cpython-3.14).

Black-box over TRACKED FILES ONLY: this oracle never invokes ``uv`` and never asks which
interpreters the host has installed (that is ambient state, and CI's two legs differ).
The fresh-clone proof (behavior 6) is a manual probe recorded in the tester report.
ONE collected item (``make readme-headroom`` reads binding_headroom=6), paid for by
folding the 2-item ``test_iter126::test_eb6`` parametrize; the spec behaviours live in
private ``_bN_`` helpers.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
PIN_FILE: Final = REPO / ".python-version"
CI_YML: Final = REPO / ".github" / "workflows" / "ci.yml"
PYPROJECT: Final = REPO / "pyproject.toml"
SPEC: Final = REPO / "SPEC.md"
MAKEFILE: Final = REPO / "Makefile"
ROADMAP: Final = REPO / "ROADMAP.md"
SPEC_CEILING_BYTES: Final = 94_700
ROADMAP_CEILING_BYTES: Final = 35_428
MATRIX_RE: Final = re.compile(r"python-version:\s*\[([^\]]*)\]")
TIMEOUT_SEC: Final = 60


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(part) for part in v.split("."))


def _matrix_versions() -> list[str]:
    match = MATRIX_RE.search(CI_YML.read_text(encoding="utf-8"))
    assert match is not None, "ci.yml must carry a python-version matrix list"
    versions = [v.strip().strip("'\"") for v in match.group(1).split(",") if v.strip()]
    assert versions, "the ci.yml python-version matrix must not be empty"
    return versions


def _b1_pin_file_is_tracked_and_exact() -> None:
    listed = subprocess.run(
        ["git", "ls-files", "--", ".python-version"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
        timeout=TIMEOUT_SEC,
    ).stdout.split()
    assert listed == [".python-version"], f"Behavior 1: .python-version must be tracked; got {listed}"
    data = PIN_FILE.read_bytes()
    assert data == b"3.12\n", f"Behavior 1: .python-version bytes must be exactly b'3.12\\n'; got {data!r}"


def _b2_pin_is_a_graded_leg() -> None:
    pinned = PIN_FILE.read_text(encoding="utf-8").strip()
    matrix = _matrix_versions()
    assert pinned in matrix, f"Behavior 2: pinned {pinned!r} is not a CI matrix leg {matrix}"
    lowest = min(matrix, key=_version_key)
    assert pinned == lowest, f"Behavior 2: pinned {pinned!r} must be the LOWEST leg {lowest!r}"
    py = PYPROJECT.read_text(encoding="utf-8")
    assert f'"Programming Language :: Python :: {pinned}"' in py, (
        f"Behavior 2: pyproject.toml must carry the {pinned} classifier"
    )
    req = re.search(r'requires-python\s*=\s*">=\s*([0-9.]+)"', py)
    assert req is not None, "Behavior 2: pyproject.toml must declare requires-python >=X"
    assert req.group(1) == pinned, (
        f"Behavior 2: pin {pinned!r} must equal the requires-python floor {req.group(1)!r}"
    )


def _b3_spec_layout_names_the_pin() -> None:
    raw = SPEC.read_bytes()
    assert len(raw) < SPEC_CEILING_BYTES, (
        f"Behavior 3: SPEC.md is {len(raw)} B, must stay under {SPEC_CEILING_BYTES} B"
    )
    text = raw.decode("utf-8")
    head, sep, rest = text.partition("## 2. Layout")
    assert sep, "Behavior 3: SPEC.md must keep its '## 2. Layout' section"
    fence = re.search(r"```\n(.*?)\n```", rest, re.S)
    assert fence is not None, "Behavior 3: the Layout section must hold a fenced tree"
    lines = fence.group(1).splitlines()
    entry = [i for i, ln in enumerate(lines) if re.match(r"^[├└]── \.python-version(\s|$)", ln)]
    assert len(entry) == 1, f"Behavior 3: Layout fence must name .python-version once; got {entry}"
    neighbours = {lines[j].split()[1] for j in (entry[0] - 1, entry[0] + 1) if 0 <= j < len(lines)}
    assert ".gitignore" in neighbours, (
        f"Behavior 3: .python-version must sit next to .gitignore; neighbours {neighbours}"
    )


def _b5_makefile_comment_is_truthful() -> None:
    mk = MAKEFILE.read_text(encoding="utf-8")
    flat = " ".join(mk.split())
    assert "There is no `.python-version` in this repo" not in flat, (
        "Behavior 5: the stale 'no .python-version' Makefile comment must be rewritten"
    )
    comment = " ".join(
        " ".join(ln.lstrip("#").split()) for ln in mk.splitlines() if ln.lstrip().startswith("#")
    )
    assert re.search(r"`?\.python-version`? pins\s+3\.12", comment), (
        "Behavior 5: a Makefile comment must say .python-version pins 3.12"
    )
    assert "check-matrix" in comment and "3.13" in comment, (
        "Behavior 5: the comment must still route the 3.13 leg to make check-matrix"
    )
    recipe = re.search(r"^check-matrix:.*?(?=^\S)", mk, re.S | re.M)
    assert recipe is not None, "Behavior 4: Makefile must keep its check-matrix target"
    assert "--python" in recipe.group(0), "Behavior 4: check-matrix must still pass --python per leg"


def _b7_roadmap_row_348() -> None:
    raw = ROADMAP.read_bytes()
    assert len(raw) < ROADMAP_CEILING_BYTES, (
        f"Behavior 7: ROADMAP.md is {len(raw)} B, must stay under {ROADMAP_CEILING_BYTES} B"
    )
    lines = raw.decode("utf-8").splitlines()
    rows = [ln for ln in lines if ln.startswith("- #348 ")]
    assert len(rows) == 1, f"Behavior 7: exactly one '- #348' ledger row; got {rows}"
    assert ".python-version" in rows[0] and "3.12" in rows[0], f"Behavior 7: row #348 {rows[0]!r}"
    prev = [ln for ln in lines if ln.startswith("- #347 ")]
    assert len(prev) == 1, "Behavior 7: row #347 must still exist exactly once"
    tag = re.search(r"\(foundry iter \d+\)$", prev[0])
    assert tag is not None, f"Behavior 7: row #347 lost its tag {prev[0]!r}"
    assert re.search(r"\(foundry iter \d+\)$", rows[0]), (
        f"Behavior 7: row #348 must copy #347's '(foundry iter NN)' tag format: {rows[0]!r}"
    )
    assert lines.index(rows[0]) == lines.index(prev[0]) + 1, "Behavior 7: #348 must follow #347"


def test_python_version_pin_is_tracked_graded_documented_and_ledgered() -> None:
    _b1_pin_file_is_tracked_and_exact()
    _b2_pin_is_a_graded_leg()
    _b3_spec_layout_names_the_pin()
    _b5_makefile_comment_is_truthful()
    _b7_roadmap_row_348()
