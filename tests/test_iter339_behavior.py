"""Black-box oracle for foundry iter 604 (factory iter 339): the README names every
cross-scan collector memo (``*_MAX_ENTRIES``), states its runtime cap, says those memos
persist across scans and names both key kinds, so the scan-scoped-cache sentence is no
longer an unqualified (false) claim about long-lived ``pla watch``.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``), ``README.md``,
``ROADMAP.md`` and the conventions under ``tests/``. The census reads only the
module-level ``*_MAX_ENTRIES`` assignment lines the spec names, and each value is read
at runtime through ``getattr`` on the public module -- never hardcoded. No sha pin, no
line-number pin, no wall-clock bound, no network.

The README checks are pure text functions so the 0-item entry can feed them synthetic
drifted READMEs and prove that none of them passes vacuously.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
COLLECTORS = REPO / "src" / "proactive_loop" / "collectors"
CENSUS_RE = re.compile(r"^([A-Z][A-Z0-9_]*_MAX_ENTRIES)\s*(:[^=]*)?=", re.MULTILINE)
KNOWN = {
    "TODO_MEMO_MAX_ENTRIES",
    "MERGE_CONFLICT_MEMO_MAX_ENTRIES",
    "PARSE_MEMO_MAX_ENTRIES",
    "PYC_VOUCH_MEMO_MAX_ENTRIES",
    "BROKEN_LINK_MEMO_MAX_ENTRIES",
}
ROW = "- #389 README names cross-scan memos"


def census() -> dict[str, str]:
    """NAME -> module stem, derived from the collector sources."""
    found: dict[str, str] = {}
    for path in sorted(COLLECTORS.glob("*.py")):
        for m in CENSUS_RE.finditer(path.read_text(encoding="utf-8")):
            found[m.group(1)] = path.stem
    return found


def below_marker(text: str) -> str:
    """README text after the closing ``-->`` of the PORTFOLIO INTRO marker block."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if "PORTFOLIO INTRO" in ln)
    end = next(i for i in range(start, len(lines)) if "-->" in lines[i])
    return "\n".join(lines[end + 1 :])


def above_marker(text: str) -> str:
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if "PORTFOLIO INTRO" in ln)
    end = next(i for i in range(start, len(lines)) if "-->" in lines[i])
    return "\n".join(lines[: end + 1])


def paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def missing_names(text: str, names: set[str]) -> set[str]:
    """Names absent from below the marker as a backticked token, or present above it."""
    below = below_marker(text)
    above = above_marker(text)
    return {n for n in names if f"`{n}`" not in below or n in above}


def value_violations(text: str, values: dict[str, int]) -> set[str]:
    """Names whose runtime value is not stated in a paragraph that names them."""
    paras = paragraphs(below_marker(text))
    bad = set()
    for name, value in values.items():
        hosts = [p for p in paras if f"`{name}`" in p]
        if not hosts or not any(re.search(rf"(?<!\d){value}(?!\d)", p) for p in hosts):
            bad.add(name)
    return bad


def memo_paragraph_ok(text: str, names: set[str]) -> bool:
    paras = [p for p in paragraphs(below_marker(text)) if any(f"`{n}`" in p for n in names)]
    if not paras:
        return False
    joined = "\n".join(paras)
    return (
        "across scans" in joined.lower()
        and "st_mtime_ns" in joined
        and "digest" in joined.lower()
    )


def unqualified_one_scan(text: str) -> list[str]:
    backticked = re.compile(r"`[A-Z][A-Z0-9_]*_MAX_ENTRIES`")
    return [
        p
        for p in paragraphs(text)
        if "live for exactly one scan" in p
        and "across scans" not in p.lower()
        and not backticked.search(p)
    ]


def values_for(found: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, stem in found.items():
        mod = importlib.import_module(f"proactive_loop.collectors.{stem}")
        out[name] = int(getattr(mod, name))
    return out


def test_b1_census_is_derived_and_covers_known_memos() -> None:
    found = census()
    assert found, "census derived no *_MAX_ENTRIES names (regex or path drift)"
    assert len(found) >= 5, sorted(found)
    assert KNOWN <= set(found), sorted(KNOWN - set(found))


def test_b2_every_memo_named_backticked_below_marker() -> None:
    text = README.read_text(encoding="utf-8")
    assert missing_names(text, set(census())) == set()


def test_b3_runtime_value_stated_in_naming_paragraph() -> None:
    text = README.read_text(encoding="utf-8")
    values = values_for(census())
    assert all(v > 0 for v in values.values()), values
    assert value_violations(text, values) == set()


def test_b4_memo_paragraph_says_across_scans_and_both_key_kinds() -> None:
    text = README.read_text(encoding="utf-8")
    assert memo_paragraph_ok(text, set(census()))


def test_b5_no_unqualified_one_scan_claim() -> None:
    text = README.read_text(encoding="utf-8")
    assert unqualified_one_scan(text) == []


def test_b6_intro_heading_present_and_memo_names_absent_above_marker() -> None:
    text = README.read_text(encoding="utf-8")
    above = above_marker(text)
    assert "What this project demonstrates" in above
    assert "MAX_ENTRIES" not in above


def test_b7_syntax_error_row_still_parse_only() -> None:
    text = README.read_text(encoding="utf-8")
    assert "(stdlib compile, parse-only). |" in text


def test_b8_roadmap_carries_row_389() -> None:
    hits = 0
    for name in ("ROADMAP.md", "ROADMAP_ARCHIVE.md"):
        path = REPO / name
        if path.exists():
            hits += sum(
                1
                for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.startswith(ROW)
            )
    assert hits >= 1
    row = next(
        ln
        for ln in (REPO / "ROADMAP.md").read_text(encoding="utf-8").splitlines()
        if ln.startswith(ROW)
    )
    assert len(row) <= 120


def test_b0_checks_never_pass_vacuously() -> None:
    """0-item entry: every pure check reds on a synthetic drifted README."""
    text = README.read_text(encoding="utf-8")
    found = census()
    names = set(found)
    values = values_for(found)
    # a sixth, undocumented memo reds behavior 2
    assert missing_names(text, names | {"NEW_THING_MAX_ENTRIES"}) == {"NEW_THING_MAX_ENTRIES"}
    # dropping one backticked name reds behavior 2
    victim = sorted(names)[0]
    assert victim in missing_names(text.replace(f"`{victim}`", victim), names)
    # a changed cap reds behavior 3
    bumped = {k: v + 1 for k, v in values.items()}
    assert value_violations(text, bumped) == set(bumped)
    # stripping the key-kind words reds behavior 4
    assert not memo_paragraph_ok(text.replace("st_mtime_ns", "stat"), names)
    assert not memo_paragraph_ok(re.sub("(?i)across scans", "per scan", text), names)
    assert not memo_paragraph_ok(re.sub("(?i)digest", "hash", text), names)
    # the pre-change sentence alone reds behavior 5
    drifted = "Intro.\n\nBoth caches live for exactly one scan, so nothing is stale.\n"
    assert len(unqualified_one_scan(drifted)) == 1
    # a README without the marker cannot be silently treated as all-below
    with pytest.raises(StopIteration):
        below_marker("no marker here")
