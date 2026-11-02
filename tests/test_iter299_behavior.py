"""Factory iter 550 (ROADMAP #339): every ``uv run pla`` gate in ``make check`` is in README.

The README graded-gate tour documented 6 of the 8 ``pla`` commands in the Makefile
``check:`` recipe; the ``--baseline`` round trip and the ``--fail-on-kind`` self-scan were
missing. This oracle binds README.md to the recipe, so a new gate cannot ship undocumented.
One collected item (``make readme-headroom`` budget); every assertion lives in the body.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
MARKER: Final = "PORTFOLIO INTRO"
ANCHOR: Final = "**And the build budgets what it cannot forbid.**"
DETERMINISM: Final = "**Both graded gates also prove slate-level determinism.**"
ROW: Final = (
    "- #339 README shows all 8 `make check` pla gates; bound to the recipe (foundry iter 327)"
)
HEADING: Final = "**The build also ratchets the fixture against itself, and scans its own tree.**"


def _check_pla_lines() -> list[str]:
    lines = (REPO / "Makefile").read_text(encoding="utf-8").splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("check:"))
    end = next((i for i in range(at + 1, len(lines)) if not lines[i].startswith("\t")), len(lines))
    return [
        line.strip().removesuffix(" > /dev/null")
        for line in lines[at + 1 : end]
        if line.strip().startswith("uv run pla ")
    ]


def test_every_make_check_pla_gate_is_documented_below_the_marker() -> None:
    gates = _check_pla_lines()
    assert len(gates) == 8, f"make check pla gate count moved: {gates}"
    text = (REPO / "README.md").read_text(encoding="utf-8")
    below = text[text.index(MARKER) :]
    missing = [g for g in gates if f"\n{g}\n" not in below]
    assert not missing, f"make check gates absent from README: {missing}"
    para_at = text.index(HEADING)
    assert text.count(HEADING) == 1 and text.index(MARKER) < para_at < text.index(ANCHOR)
    para = text[para_at : text.index(ANCHOR)]
    for gate in gates:
        if "--baseline" in gate or "--fail-on-kind" in gate:
            assert para.count(f"\n{gate}\n") == 1, f"new paragraph lacks: {gate}"
    for word in ("exits **5**", "-exec touch", "mtime"):
        assert word in para, f"new paragraph lacks the WHY token {word!r}"
    # EB1/EB2: the paragraph is the one immediately before the anchor, and its single
    # bash block holds exactly the two new gates, in recipe order.
    assert para.endswith("\n\n") and "\n**" not in para[len(HEADING) :], para[-200:]
    assert text.index(ANCHOR) < text.index(DETERMINISM)
    assert para.count("```bash\n") == 1, "new paragraph must hold exactly one bash block"
    block = para.split("```bash\n", 1)[1].split("\n```", 1)[0].splitlines()
    new_gates = [g for g in gates if "--baseline" in g or "--fail-on-kind" in g]
    assert len(new_gates) == 2 and block == new_gates, f"bash block {block} != {new_gates}"
    # EB7: the ledger row lands exactly once, immediately after row #338.
    roadmap = (REPO / "ROADMAP.md").read_text(encoding="utf-8").splitlines()
    ledger = [ln for ln in roadmap if ln.startswith("- #")]
    rows = [ln for ln in ledger if ln.startswith("- #339 ")]
    assert rows == [ROW], f"ledger row #339 drifted: {rows}"
    assert ledger[ledger.index(rows[0]) - 1].startswith("- #338 "), "row #339 must follow row #338"
