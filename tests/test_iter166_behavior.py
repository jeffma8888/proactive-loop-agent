"""Iteration 160 (factory iter 166) -- black-box verification of row #199.

WHAT THIS ITERATION CLAIMS (from the PM spec, restated so this file stands alone)
Five cap justifications under src/proactive_loop/collectors/ justified a memory
cap by a census of this checkout's own tree -- "4096 is ~21x this repo's own 189
scanned files" and four more of that shape -- and every one had decayed into a
false statement (189 -> 228 scanned files, 173 -> 219 py files, 3.17 -> 4.36 MB
of text). A sixth site of the same class was accurate but is rewritten anyway,
because the one site a guard exempts is the one place it can never look. The
replacement standard: a cap may be justified by an ABSOLUTE bound, or by a ratio
against a NAMED CODE CONSTANT, and never by a census of the current tree. A
dated record of a PAST measurement stays legal, because it is history.

HOW THIS FILE VERIFIES IT, INDEPENDENTLY
The four detection patterns and the positive/negative samples below are
transcribed from the SPEC, not from the shipped module, and the census here runs
its OWN tokenize+ast extractor over src/proactive_loop/. So a defect in the
shipped guard cannot hide behind agreement with itself: the spec-side oracle and
the shipped oracle are asserted separately, and both must agree that the tree is
clean. The shipped module is additionally checked for having ADOPTED the
pre-validated pattern set rather than redesigning it.

Two traps this file respects on purpose.
1. DOMAIN. This module CONTAINS the banned shapes, in its pattern literals and
   in every planted sample. Both censuses are scoped to src/proactive_loop/, so
   this file is outside the measured domain by construction; test_b10 asserts
   that scoping is load-bearing rather than incidental.
2. INTERPRETER SKEW. Python 3.13 strips the common leading docstring indent at
   compile time and 3.12 does not, and CI runs both, so nothing here asserts on
   indentation: docstrings come out of ast.get_docstring(clean=True) and all
   extracted prose is collapsed to single spaces before matching.

Behavior 9 of the spec (byte-identical signals output) is discharged by the full
suite, which already pins the collectors' output contracts; the spec says so
explicitly, and this file deliberately spawns no child process.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

from proactive_loop.collectors import large_file, merge_conflict, syntax_error, text_source, todos

from tests import test_source_comment_bounds as shipped

REPO = Path(__file__).resolve().parents[1]
SRC_PKG = REPO / "src" / "proactive_loop"
TESTS_DIR = REPO / "tests"

# Transcribed from the spec's Expected Behaviors table (P1-P4), not from the
# shipped module. Kept as raw strings so the comparison in test_b03 is exact.
SPEC_PATTERN_SOURCES: dict[str, str] = {
    "P1-ratio-against-the-repo": r"\d+(?:\.\d+)?x\s+this\s+repo",
    "P2-the-repos-own-N": r"this\s+repo'?s?\s+own\s+(?:measured\s+)?\d",
    "P3-frozen-file-census": r"\(\s*\d[\d,]*\s+scanned\s+files",
    "P4-parenthesised-repo-census": r"in\s+this\s+repo\s*\(\s*\d",
}

SPEC_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(source, re.IGNORECASE) for name, source in SPEC_PATTERN_SOURCES.items()
}

# Spec behavior 3: one validated sample per pattern, so no pattern is dead code.
SPEC_POSITIVES: dict[str, str] = {
    "P1-ratio-against-the-repo": "4096 is ~21x this repo's own scanned-file count",
    "P2-the-repos-own-N": "roughly this repo's own measured 3.17 MB of scanned text",
    "P3-frozen-file-census": "Measured on this repo (189 scanned files, 3,170 KB of decoded text)",
    "P4-parenthesised-repo-census": "256 is ~8x the densest file in this repo (33 items)",
}

# Spec behavior 4: six REAL in-repo phrases that mention this checkout
# legitimately. If any of these starts matching, the guard has become a machine
# for deleting honest prose.
SPEC_NEGATIVES: tuple[str, ...] = (
    "this repo publishes an offline-first bar enforced by a blunt module-name oracle",
    "measured on this repo, --exclude-path tests left a 75-signal listing at 75 ... took it to 66",
    "measured on this repo before the change: --kind ci_config spent ~378 ms ... cost 3.2x --collector todos",
    "every ordered surface in this repo has to be reproducible",
    "the one thing this repo's output contracts refuse to do",
    "32 MiB is 6.7x the 5 MB per-file cap the three collectors share (LARGE_FILE_MIN_BYTES)",
)

# Spec behavior 6 floors, transcribed from the spec.
SPEC_MIN_FILES = 25
SPEC_MIN_CHARS = 20_000

# Spec behavior 8: every cap VALUE is unchanged by a comment-only iteration.
SPEC_CAP_VALUES: tuple[tuple[str, object, str, int], ...] = (
    ("todos", todos, "TODO_MEMO_MAX_ENTRIES", 4096),
    ("todos", todos, "TODO_MEMO_MAX_ITEMS_PER_FILE", 256),
    ("syntax_error", syntax_error, "PARSE_MEMO_MAX_ENTRIES", 4096),
    ("merge_conflict", merge_conflict, "MERGE_CONFLICT_MEMO_MAX_ENTRIES", 4096),
    ("text_source", text_source, "TEXT_CACHE_MAX_BYTES", 33_554_432),
)

# Spec behavior 7: each of these caps must still carry non-empty justification
# prose naming a bound, and the text_source one must name the code constant.
BOUND_VOCABULARY = re.compile(
    r"(byte|bytes|KB|MB|MiB|GB|cap|bound|entries|items|constant|tuple|LARGE_FILE_MIN_BYTES)",
    re.IGNORECASE,
)


# ==========================================================================
# Spec-side oracle: an independent text -> findings function and extractor.
# Deliberately NOT merging overlapping spans -- merging is the shipped
# module's presentation choice, and an unmerged scan is strictly stricter for
# the zero-findings assertions that matter most here.
# ==========================================================================
def spec_findings(text: str) -> tuple[tuple[str, str], ...]:
    """Report (pattern_name, matched_phrase) for every banned shape in TEXT."""
    flat = re.sub(r"\s+", " ", text)
    hits: list[tuple[int, str, str]] = []
    for name, pattern in SPEC_PATTERNS.items():
        for match in pattern.finditer(flat):
            hits.append((match.start(), name, flat[max(0, match.start() - 30) : match.end() + 30]))
    hits.sort()
    return tuple((name, excerpt) for _, name, excerpt in hits)


def spec_prose(source: str) -> str:
    """Extract comments (tokenize) and docstrings (ast), whitespace-collapsed."""
    parts: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=True)
            if doc:
                parts.append(doc)
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            parts.append(token.string.lstrip("#").strip())
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def package_modules() -> list[Path]:
    return sorted(SRC_PKG.rglob("*.py"))


def justification_for(module_path: Path, constant: str) -> tuple[str, str]:
    """Return (where_it_came_from, prose) justifying CONSTANT in MODULE_PATH.

    Looks, in order, at the contiguous comment block immediately ABOVE the
    assignment, a trailing comment on the assignment line itself, and finally
    any sentence of the module's extracted prose that names the constant.
    """
    lines = module_path.read_text(encoding="utf-8").splitlines()
    assign = re.compile(rf"^{re.escape(constant)}\s*(?::[^=]+)?=")
    index = next((i for i, line in enumerate(lines) if assign.match(line)), None)
    assert index is not None, f"{module_path.name} no longer assigns {constant} at column 0"

    above: list[str] = []
    cursor = index - 1
    while cursor >= 0 and lines[cursor].lstrip().startswith("#"):
        above.append(lines[cursor].lstrip().lstrip("#").strip())
        cursor -= 1
    if above:
        return ("comment block above", re.sub(r"\s+", " ", " ".join(reversed(above))).strip())

    _, _, trailing = lines[index].partition("#")
    if trailing.strip():
        return ("trailing comment", re.sub(r"\s+", " ", trailing).strip())

    prose = spec_prose(module_path.read_text(encoding="utf-8"))
    sentences = [part for part in re.split(r"(?<=[.!?]) ", prose) if constant in part]
    return ("module prose", " ".join(sentences).strip())


# ==========================================================================
# Behavior 1 -- a banned phrase is reported, named, and excerpted.
# ==========================================================================
def test_b01_a_banned_repo_census_phrase_is_reported_with_its_pattern_and_phrase() -> None:
    sample = "4096 is ~21x this repo's own scanned-file count"

    spec_hits = spec_findings(sample)
    assert spec_hits, "the spec-side oracle reported nothing for a known-bad phrase"
    for name, excerpt in spec_hits:
        assert name in SPEC_PATTERN_SOURCES, f"finding names an unknown pattern: {name!r}"
        assert "this repo" in excerpt.lower(), f"excerpt lost the matched phrase: {excerpt!r}"

    shipped_hits = shipped.find_repo_census_claims(sample)
    assert shipped_hits, "the shipped guard reported nothing for a known-bad phrase"
    for finding in shipped_hits:
        assert finding.pattern in shipped.PATTERN_NAMES, finding
        assert "this repo" in finding.excerpt.lower(), finding


# ==========================================================================
# Behavior 2 -- clean text is silent.
# ==========================================================================
def test_b02_text_with_none_of_the_four_shapes_reports_zero_findings() -> None:
    clean = (
        "4096 verdicts, each a None or a small (int, str) tuple, stays well under "
        "1 MB, and the memo is cleared per run so nothing accumulates across ticks."
    )
    assert spec_findings(clean) == (), spec_findings(clean)
    assert shipped.find_repo_census_claims(clean) == (), shipped.find_repo_census_claims(clean)


# ==========================================================================
# Behavior 3 -- every pattern is individually two-sided (no dead pattern).
# ==========================================================================
def test_b03_each_spec_pattern_fires_on_its_own_validated_sample() -> None:
    for name, pattern in SPEC_PATTERNS.items():
        sample = SPEC_POSITIVES[name]
        assert pattern.search(sample), (
            f"{name} matched nothing in its own validated sample {sample!r} -- "
            "a pattern that cannot fire is dead code in a gate"
        )
        assert shipped.find_repo_census_claims(sample), (
            f"the shipped guard is blind to the {name} sample {sample!r}"
        )


def test_b03_the_shipped_guard_adopted_the_pre_validated_pattern_set() -> None:
    assert {pattern.pattern for _, pattern in shipped.PATTERNS} == set(
        SPEC_PATTERN_SOURCES.values()
    ), (
        "the shipped pattern set differs from the four patterns the spec "
        f"pre-validated: shipped={[p.pattern for _, p in shipped.PATTERNS]}"
    )
    assert len(shipped.PATTERN_NAMES) == 4, shipped.PATTERN_NAMES
    assert len(set(shipped.PATTERN_NAMES)) == 4, "two patterns share a name"


# ==========================================================================
# Behavior 4 -- six real, legitimate in-repo mentions survive.
# ==========================================================================
def test_b04_real_legitimate_mentions_of_this_repo_are_not_flagged() -> None:
    for sample in SPEC_NEGATIVES:
        assert spec_findings(sample) == (), (
            f"spec-side oracle false-positives on legitimate prose: {sample!r} -> "
            f"{spec_findings(sample)}"
        )
        assert shipped.find_repo_census_claims(sample) == (), (
            f"shipped guard false-positives on legitimate prose: {sample!r}"
        )


# ==========================================================================
# Behavior 5 -- the live package carries none of the four shapes.
# ==========================================================================
def test_b05_no_module_under_the_package_justifies_a_cap_with_a_repo_census() -> None:
    offenders: list[str] = []
    for path in package_modules():
        for name, excerpt in spec_findings(spec_prose(path.read_text(encoding="utf-8"))):
            offenders.append(f"{path.relative_to(REPO)} [{name}] ...{excerpt}...")
    assert offenders == [], (
        "these comment/docstring sites still justify a cap by a census of this "
        "checkout's own tree, which is false the moment the tree grows: "
        + " | ".join(offenders)
    )


def test_b05_the_census_pipeline_fires_on_a_planted_module(tmp_path) -> None:
    """Two-sided proof: extractor + oracle must catch a planted known-bad module."""
    planted = tmp_path / "planted_collector.py"
    planted.write_text(
        '"""A module whose docstring claims 32 MiB is ~10x this repo\'s own 3.17 MB."""\n'
        "\n"
        "# 4096 is ~24x this repo's own 173 py files, so the memo cannot grow without\n"
        "# bound in practice.\n"
        "CAP = 4096\n",
        encoding="utf-8",
    )
    hits = spec_findings(spec_prose(planted.read_text(encoding="utf-8")))
    assert len(hits) >= 2, f"the pipeline saw only {hits} in a module planted with two defects"
    assert shipped.find_repo_census_claims(
        shipped.prose_of(planted.read_text(encoding="utf-8"))
    ), "the shipped extractor+oracle pair is blind to a planted known-bad module"


# ==========================================================================
# Behavior 6 -- the census is anti-vacuous, in both oracles.
# ==========================================================================
def test_b06_the_census_examined_a_real_corpus_not_an_empty_one() -> None:
    modules = package_modules()
    total = sum(len(spec_prose(path.read_text(encoding="utf-8"))) for path in modules)
    assert len(modules) >= SPEC_MIN_FILES, (
        f"census walked only {len(modules)} modules under {SRC_PKG} -- the glob is fail-open"
    )
    assert total >= SPEC_MIN_CHARS, (
        f"census extracted only {total} chars of comment/docstring prose -- an "
        "extractor regression to empty strings would pass a clean verdict"
    )


def test_b06_the_shipped_guard_declares_floors_at_least_as_strict_as_the_spec() -> None:
    assert shipped.MIN_CENSUS_FILES >= SPEC_MIN_FILES, shipped.MIN_CENSUS_FILES
    assert shipped.MIN_CENSUS_CHARS >= SPEC_MIN_CHARS, shipped.MIN_CENSUS_CHARS


# ==========================================================================
# Behavior 7 -- information was preserved, not merely deleted.
# ==========================================================================
def test_b07_text_source_still_justifies_its_cap_against_a_named_code_constant() -> None:
    source, prose = justification_for(SRC_PKG / "collectors" / "text_source.py", "TEXT_CACHE_MAX_BYTES")
    assert prose, f"TEXT_CACHE_MAX_BYTES lost its justification prose ({source})"
    assert "LARGE_FILE_MIN_BYTES" in prose, (
        "the text cache cap must be justified against the named code constant "
        f"LARGE_FILE_MIN_BYTES, not against a tree census; {source} says: {prose!r}"
    )


def test_b07_every_rewritten_cap_still_carries_prose_naming_a_bound() -> None:
    targets = (
        (SRC_PKG / "collectors" / "todos.py", "TODO_MEMO_MAX_ENTRIES"),
        (SRC_PKG / "collectors" / "todos.py", "TODO_MEMO_MAX_ITEMS_PER_FILE"),
        (SRC_PKG / "collectors" / "syntax_error.py", "PARSE_MEMO_MAX_ENTRIES"),
        (SRC_PKG / "collectors" / "merge_conflict.py", "MERGE_CONFLICT_MEMO_MAX_ENTRIES"),
    )
    for path, constant in targets:
        source, prose = justification_for(path, constant)
        assert prose, f"{path.name}:{constant} has no justification prose at all ({source})"
        assert BOUND_VOCABULARY.search(prose), (
            f"{path.name}:{constant} prose no longer names a bound -- the stale "
            f"ratio was deleted without replacing the information; {source} says: {prose!r}"
        )


# ==========================================================================
# Behavior 8 -- a comment-only iteration moved no cap value.
# ==========================================================================
def test_b08_every_cap_value_is_unchanged() -> None:
    for module_name, module, constant, expected in SPEC_CAP_VALUES:
        actual = getattr(module, constant)
        assert actual == expected, f"{module_name}.{constant} is {actual}, expected {expected}"


def test_b08_the_blessed_ratio_against_the_named_constant_is_arithmetically_true() -> None:
    assert large_file.LARGE_FILE_MIN_BYTES == 5_000_000, large_file.LARGE_FILE_MIN_BYTES
    ratio = text_source.TEXT_CACHE_MAX_BYTES / large_file.LARGE_FILE_MIN_BYTES
    assert round(ratio, 1) == 6.7, (
        "the one ratio the rewrite standard blesses is 32 MiB against the 5 MB "
        f"per-file cap; that is {ratio} today, so any prose saying 6.7x is stale"
    )


# ==========================================================================
# The TRAP -- the domain is the whole remedy, so assert it explicitly.
# ==========================================================================
def test_b10_the_guarded_domain_is_the_package_and_excludes_the_tests_that_carry_samples() -> None:
    modules = package_modules()
    assert modules, "the package census found no modules at all"
    for path in modules:
        assert SRC_PKG in path.parents or path.parent == SRC_PKG, path
        assert TESTS_DIR not in path.parents, f"{path} is inside tests/ -- domain leaked"

    # Load-bearing, not incidental: both this file and the shipped guard hold the
    # banned shapes in their fixtures, so a wider domain would red the build on
    # the guard's own evidence.
    for carrier in (Path(__file__), TESTS_DIR / "test_source_comment_bounds.py"):
        raw = carrier.read_text(encoding="utf-8")
        assert spec_findings(re.sub(r"\s+", " ", raw)), (
            f"{carrier.name} no longer contains a banned sample -- if the fixtures "
            "are gone the two-sidedness proofs above are vacuous"
        )
