"""Drift guard: a cap in ``src/`` may never be justified by a census of THIS repo.

Why this file exists
Five comments under ``src/proactive_loop/collectors/`` justified a memory cap by
comparing it against this checkout's own tree -- ``4096 is ~21x this repo's own
189 scanned files``, ``32 MiB is ~10x this repo's own measured 3.17 MB of scanned
text``, and three more of the same shape. Every one of them was FALSE by the time
it was read: the tree had grown to 228 scanned files and 4.36 MB of text, so the
real ratios were 18.0x and 7.7x. Nothing in the suite could see it, because the
claims lived in prose inside ``src/``.

That is the same decaying-constant class the operator already banned ABOVE the
README's human-owned marker (no exact test count, no hardcoded
``tests-NNNN-passing`` badge) -- except a README number at least has this guard's
sibling, ``test_readme_and_ci_contract.py``, watching it. A number in a source
comment had no oracle at all, on a PUBLIC portfolio repo where any reader can
re-derive the ratio in one command and find the comment wrong.

The rule this module encodes
A cap may be justified by an ABSOLUTE bound (``4096 verdicts, each a None or a
small (int, str) tuple, stays well under 1 MB``) or by a ratio against a NAMED
CODE CONSTANT (``6.7x the 5 MB per-file cap LARGE_FILE_MIN_BYTES``). It may NOT
be justified by a census of this repo's own tree, because that census is a claim
about today that silently decays on every commit. A DATED record of a past
measurement stays legitimate (``profiled at factory iter 130 on a ~190-file
tree``) -- that is history, not a claim about the current tree, which is why the
two ``cli.py`` "measured on this repo before the change" notes are untouched.

Why the guard is two-sided in both directions
1. Against the DETECTOR being dead. Four patterns is four chances to ship a regex
   that matches nothing, and a census that can never fire is ``assert True``. So
   :func:`find_repo_census_claims` is a pure ``text -> findings`` function and
   EVERY pattern is fired individually against a planted sample taken verbatim
   from the pre-rewrite tree (:data:`PLANTED_POSITIVES`). A pattern that stops
   matching its own sample fails the build.
2. Against the SUBJECT being empty. A census over an extractor that returns ``""``
   reports zero findings and looks perfect, which is the fail-open shape this repo
   keeps rediscovering. So the census asserts FLOORS as well: at least
   :data:`MIN_CENSUS_FILES` modules examined and :data:`MIN_CENSUS_CHARS` of
   extracted comment/docstring text.
3. Against FALSE POSITIVES. Six real in-repo phrases that mention this repo
   legitimately (:data:`REAL_NEGATIVES`) must stay clean, or the guard becomes a
   machine for deleting honest prose.

Why the domain is ``src/proactive_loop/**/*.py`` and nothing wider
THIS MODULE CONTAINS THE BANNED SHAPES -- in its pattern literals and in every
planted sample above. Widening the census to ``tests/`` or to the repo root would
red the build on the guard's own fixtures. Stating the domain is the whole remedy,
and because the census walks the FILESYSTEM under ``src/proactive_loop/`` rather
than ``git ls-files``, a new or untracked module cannot fall outside the domain it
is measured in, and the guard is fresh-clone safe.

Why ``tokenize`` plus ``ast`` rather than a raw text scan
A raw scan of the file's bytes would also read string literals and identifiers,
so a collector that legitimately MATCHES the phrase in a regex would be flagged
for the phrase it exists to find. Comments come from ``tokenize`` and docstrings
from ``ast.get_docstring(clean=True)``, which is also what keeps this module off
the 3.12/3.13 indentation trap: ``clean=True`` plus a whitespace collapse means no
assertion here can see the common leading indent that 3.13 strips at compile time
and 3.12 does not.

Offline, deterministic, fresh-clone safe: pure ``tokenize``/``ast`` reads of
git-tracked files under ``src/``. No product import, no subprocess, no network, no
clock, no writes anywhere.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC_PKG = REPO / "src" / "proactive_loop"

# Anti-vacuity floors for the live census. Both sit far BELOW what the package
# measured when this guard shipped (35 modules, ~376,000 chars of extracted
# prose -- a DATED record of one run, not a claim about the current tree), so
# ordinary growth or a refactor never trips them while an extractor regression
# to "" cannot pass.
MIN_CENSUS_FILES = 25
MIN_CENSUS_CHARS = 20_000

# How much of the surrounding sentence a finding carries, so a failure message
# points at the phrase to fix instead of only naming the file.
_EXCERPT_PAD = 30


@dataclass(frozen=True)
class Finding:
    """One banned justification: WHICH shape matched, and the phrase that did."""

    pattern: str
    excerpt: str


# name -> pattern. Each is anchored on a NUMBER next to a phrase about this repo,
# because the number is what decays; a numberless mention of this repo is prose,
# not a measurement, and stays legal.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # "4096 is ~21x this repo's own scanned-file count"
    ("ratio-against-this-repo", re.compile(r"\d+(?:\.\d+)?x\s+this\s+repo", re.IGNORECASE)),
    # "this repo's own 189 scanned files", "this repo's own measured 3.17 MB"
    ("this-repos-own-number", re.compile(r"this\s+repo'?s?\s+own\s+(?:measured\s+)?\d", re.IGNORECASE)),
    # "Measured on this repo (189 scanned files, 3,170 KB of decoded text)"
    ("frozen-file-census", re.compile(r"\(\s*\d[\d,]*\s+scanned\s+files", re.IGNORECASE)),
    # "the densest file in this repo (33 items)"
    ("parenthesised-repo-census", re.compile(r"in\s+this\s+repo\s*\(\s*\d", re.IGNORECASE)),
)

PATTERN_NAMES = tuple(name for name, _ in PATTERNS)

# One planted sample per pattern, each copied VERBATIM from the pre-rewrite tree,
# so the fixtures are evidence rather than invention.
PLANTED_POSITIVES: dict[str, str] = {
    "ratio-against-this-repo": "4096 is ~21x this repo's own scanned-file count",
    "this-repos-own-number": "roughly this repo's own measured 3.17 MB of scanned text",
    "frozen-file-census": "Measured on this repo (189 scanned files, 3,170 KB of decoded text)",
    "parenthesised-repo-census": "256 is ~8x the densest file in this repo (33 items)",
}

# Real in-repo prose that mentions this repo LEGITIMATELY and must survive: five
# numberless or non-census mentions, plus the one ratio that is stated against a
# named code constant, which is the shape the rule explicitly blesses.
REAL_NEGATIVES: tuple[str, ...] = (
    "this repo publishes an offline-first bar enforced by a blunt module-name oracle",
    "measured on this repo, --exclude-path tests left a 75-signal listing at 75 ... took it to 66",
    "measured on this repo before the change: --kind ci_config spent ~378 ms ... cost 3.2x --collector todos",
    "every ordered surface in this repo has to be reproducible",
    "the one thing this repo's output contracts refuse to do",
    "32 MiB is 6.7x the 5 MB per-file cap the three collectors share (LARGE_FILE_MIN_BYTES)",
)


def find_repo_census_claims(text: str) -> tuple[Finding, ...]:
    """Report every banned repo-census justification in ``text``, one per DEFECT.

    Pure and whitespace-insensitive: the input is collapsed to single spaces
    first, because the shapes being hunted are WRAPPED across comment lines in
    real source -- the phrase ``~21x this repo's own 189 scanned files`` occupied
    two comment lines in ``todos.py`` -- and a line-oriented scan would miss
    exactly the sites that matter.

    WHY OVERLAPPING MATCHES MERGE INTO ONE FINDING. Two patterns routinely hit the
    same phrase -- ``~24x this repo's own 173 *.py files`` trips both
    ``ratio-against-this-repo`` and ``this-repos-own-number`` -- so a raw match
    list reports 9 findings for the 6 defects that existed before this iteration.
    That double-reports one comment and makes the count useless as the DEFECT
    count a reader acts on. Overlapping spans are therefore merged and named for
    the first pattern that matched; two DISTINCT phrases in one comment still
    report separately, because their spans do not touch.
    """
    flat = re.sub(r"\s+", " ", text)
    spans: list[tuple[int, int, str]] = []
    for name, pattern in PATTERNS:
        spans.extend((match.start(), match.end(), name) for match in pattern.finditer(flat))
    spans.sort(key=lambda span: (span[0], span[1]))

    merged: list[tuple[int, int, str]] = []
    for span_start, span_end, name in spans:
        if merged and span_start < merged[-1][1]:
            previous = merged[-1]
            merged[-1] = (previous[0], max(previous[1], span_end), previous[2])
            continue
        merged.append((span_start, span_end, name))

    return tuple(
        Finding(
            pattern=name,
            excerpt=flat[max(0, span_start - _EXCERPT_PAD) : span_end + _EXCERPT_PAD],
        )
        for span_start, span_end, name in merged
    )


def test_two_patterns_hitting_one_phrase_report_a_single_defect() -> None:
    """The merge is load-bearing for the defect count, so it is asserted."""
    phrase = "4096 is ~24x this repo's own 173 ``*.py`` files"
    tripped = [name for name, pattern in PATTERNS if pattern.search(phrase)]
    assert len(tripped) == 2, f"fixture must trip exactly two patterns; tripped {tripped}"
    findings = find_repo_census_claims(phrase)
    assert len(findings) == 1, (
        f"one comment defect must report one finding, not {len(findings)}: {findings}"
    )
    assert findings[0].pattern == tripped[0]


def test_two_distinct_phrases_in_one_comment_report_separately() -> None:
    """The merge must never swallow a second, genuinely different defect."""
    both = (
        "4096 is ~21x this repo's own scanned-file count, and separately "
        "Measured on this repo (189 scanned files, 3,170 KB of decoded text)."
    )
    findings = find_repo_census_claims(both)
    assert len(findings) == 2, findings


def prose_of(source: str) -> str:
    """Every comment and docstring in ``source``, joined and space-collapsed.

    Comments come from ``tokenize`` and docstrings from ``ast`` so that string
    literals, identifiers and regex bodies are NEVER read: a collector whose
    pattern legitimately spells a banned phrase must not be flagged for the thing
    it exists to detect.
    """
    parts: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            parts.append(token.string.lstrip("#"))

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=True)
            if doc:
                parts.append(doc)
    return re.sub(r"\s+", " ", " ".join(parts))


def _package_modules() -> list[Path]:
    return sorted(SRC_PKG.rglob("*.py"))


# ===========================================================================
# The detector is alive: every pattern fires on its own planted sample.
# ===========================================================================
def test_every_pattern_fires_on_its_own_planted_sample() -> None:
    for name, sample in PLANTED_POSITIVES.items():
        matched = {finding.pattern for finding in find_repo_census_claims(sample)}
        assert name in matched, (
            f"pattern {name!r} no longer matches the very phrase it was written "
            f"for ({sample!r}) -- it is dead code and the census is vacuous"
        )


def test_every_pattern_has_a_planted_sample() -> None:
    assert set(PLANTED_POSITIVES) == set(PATTERN_NAMES), (
        "a pattern without a planted sample has never been seen to fire; "
        f"patterns={PATTERN_NAMES} samples={sorted(PLANTED_POSITIVES)}"
    )


def test_a_finding_names_its_pattern_and_carries_the_phrase() -> None:
    findings = find_repo_census_claims("4096 is ~21x this repo's own scanned-file count")
    assert findings, "the canonical banned phrase must report at least one finding"
    for finding in findings:
        assert finding.pattern in PATTERN_NAMES, finding
        assert "this repo" in finding.excerpt, (
            f"a finding must quote the matched phrase, not just name a file: {finding}"
        )


# ===========================================================================
# The detector is not a false-positive machine.
# ===========================================================================
def test_clean_text_reports_nothing() -> None:
    clean = (
        "4096 verdicts, each a None or a small (int, str) tuple, stay well under "
        "1 MB; past the cap the oldest entries are evicted."
    )
    assert find_repo_census_claims(clean) == ()


def test_real_legitimate_mentions_of_this_repo_survive() -> None:
    for sample in REAL_NEGATIVES:
        assert find_repo_census_claims(sample) == (), (
            "this is real, legitimate in-repo prose -- flagging it would turn the "
            f"guard into a machine for deleting honest comments: {sample!r}"
        )


# ===========================================================================
# The live census over the package.
# ===========================================================================
def test_no_module_in_the_package_justifies_a_cap_with_a_repo_census() -> None:
    offenders: list[str] = []
    files = 0
    chars = 0
    for path in _package_modules():
        files += 1
        prose = prose_of(path.read_text(encoding="utf-8"))
        chars += len(prose)
        for finding in find_repo_census_claims(prose):
            offenders.append(f"{path.relative_to(REPO)} [{finding.pattern}] ...{finding.excerpt}...")

    assert files >= MIN_CENSUS_FILES, (
        f"census walked only {files} modules under {SRC_PKG.relative_to(REPO)} -- "
        "the glob is fail-open, so a zero-offender result proves nothing"
    )
    assert chars >= MIN_CENSUS_CHARS, (
        f"census extracted only {chars} chars of comment/docstring prose -- the "
        "extractor is returning near-empty text, so the scan is vacuous"
    )
    assert not offenders, (
        "these comments justify a cap by measuring this checkout's own tree, which "
        "decays on every commit. State an ABSOLUTE bound, or a ratio against a "
        f"NAMED CODE CONSTANT, or date the measurement as history: {offenders}"
    )
