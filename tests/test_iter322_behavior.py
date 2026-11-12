"""Behaviour oracle for factory iter 327 (ROADMAP #362): README ``-v``/``-vv`` prose.

The README verbosity paragraph (below the human-owned portfolio marker) must tell
the truth about the shipped emit sites, and this oracle DERIVES those sites from
``src/proactive_loop`` so the prose cannot drift from the code:

1. no ``shows DEBUG`` claim while zero ``.debug(`` call sites ship; ``-v`` -> INFO
   and ``-vv`` -> the DEBUG level are still stated;
2. every module containing the ``"L0 retry %d for %s"`` literal is named by stem
   (derived set must be non-empty);
3. no ``silent`` claim while any ``_LOG.warning(`` site exists -- the default
   prints only WARNING-level degradation lines and attaches no handler;
4. stderr-only / ``pla runs -v --json | jq`` pipe-clean claims remain;
5. the paragraph sits below the ``PORTFOLIO INTRO`` marker.

Reads files only: no network, no git, no mtime. One collected item, because the
README suite-size gauge (``make readme-headroom``) had no spare room this iteration.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
SRC = REPO / "src" / "proactive_loop"

PARAGRAPH_OPENING = "Add `-v` (or `-vv`)"
#: The README marker uses an EM DASH; anchor on the stable prefix only.
MARKER = "PORTFOLIO INTRO"
RETRY_LITERAL = '"L0 retry %d for %s'


def _norm(text: str) -> str:
    """Collapse all whitespace so line wrapping never decides a phrase match."""
    return " ".join(text.split())


def _paragraph(text: str) -> tuple[int, str]:
    start = text.index(PARAGRAPH_OPENING)
    end = text.find("\n\n", start)
    return start, text[start : end if end != -1 else len(text)]


def _src_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if p.is_file())


def test_b1_to_b5_verbosity_paragraph_matches_emit_sites() -> None:
    text = README.read_text(encoding="utf-8")
    assert text.count(PARAGRAPH_OPENING) == 1, "verbosity paragraph must be unique"
    start, raw = _paragraph(text)
    para = _norm(raw)
    sources = {p: p.read_text(encoding="utf-8") for p in _src_files()}
    assert sources, "no source files found under src/proactive_loop"

    # B1: no DEBUG-output claim while no .debug( site ships; levels still stated.
    debug_sites = [p for p, s in sources.items() if re.search(r"\.debug\(", s)]
    if not debug_sites:
        assert "shows DEBUG" not in para, para
    assert re.search(r"`-v`[^.]*\bINFO\b", para), para
    assert re.search(r"`-vv`[^.]*\bDEBUG\b", para), para

    # B2: every module emitting the L0 retry literal is named (anti-vacuity: >= 1).
    emitters = sorted(p for p, s in sources.items() if RETRY_LITERAL in s)
    assert emitters, f"no {RETRY_LITERAL!r} emitter derived from {SRC}"
    missing = [p.relative_to(SRC).as_posix() for p in emitters if p.stem not in para]
    assert not missing, f"README verbosity paragraph omits emitters: {missing}"

    # B3: no "silent" claim while WARNING sites exist; default behaviour stated.
    warning_sites = [p for p, s in sources.items() if "_LOG.warning(" in s]
    assert warning_sites, "expected at least one _LOG.warning( site in src"
    assert not re.search(r"\bsilent\b", para, re.IGNORECASE), para
    assert "WARNING" in para and "no handler" in para, para
    assert re.search(r"default \(no `-v`\)", para), para

    # B4: the true stderr-only and pipe-clean claims remain.
    assert "stderr only" in para, para
    assert "pla runs -v --json | jq" in para, para

    # B5: the paragraph lives below the human-owned portfolio marker.
    assert MARKER in text, "README lost its PORTFOLIO INTRO marker"
    assert text.index(MARKER) < start, "verbosity paragraph moved above the marker"
