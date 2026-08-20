"""Drift guard: a "N generated init signatures" claim in ``src/`` prose is bound to the live registry.

Why this file exists
``src/proactive_loop/collectors/base.py`` stated ONE precondition three times and
the copies disagreed -- two sites said ``16``, the newest said ``17`` -- while the
product's own explicit collector registry held 17 and ``README.md`` published 17
under the watch of ``tests/test_readme_and_ci_contract.py``. The identical fact
INSIDE the library was wrong because nothing watched it. On a PUBLIC portfolio
repo whose pitch is auditability, any reader can re-derive that number in one
command and find the source miscounting itself. Iteration 195's reviewer measured
the contradiction, graded it a NIT and let it ship, which is exactly why the
correction has to arrive with an oracle instead of as another number that decays.

How this differs from its sibling guard
``tests/test_source_comment_bounds.py`` BANS a shape (a cap may not be justified
by a census of this checkout, because that census decays on every commit). Here
the number is not a census of the tree -- it is the size of a CLOSED REGISTRY the
product itself exposes -- so it can be DERIVED instead of banned:
:func:`expected_signature_count` reads ``proactive_loop.collectors.all_collectors()``
and the live census demands every claim site in ``src/`` equal it.

Why the expected value comes from the explicit registry and NOT from the dunder
subclass-enumeration hook
This is a MEASURED landmine, not a style preference. Enumerating ``BaseCollector``
descendants looks equivalent and prints 17 when the package is imported alone,
but ``tests/test_iter169_behavior.py`` DEFINES three ``BaseCollector`` subclasses,
so once the suite has imported that module the ambient descendant count is 20.
Whether this census would see 17 or 20 depends on import order and on which
``pytest-xdist`` worker collected that module, so a guard bound to the hook would
report CORRECT prose as wrong, intermittently. ``all_collectors()`` is a closed
roster and is stable either way.

Why the matcher collapses whitespace before scanning
The claim WRAPS across comment and docstring lines in real source, so a
line-oriented scan can return zero on a genuine defect -- and zero is
indistinguishable from health. Whitespace is collapsed across newlines first;
:func:`test_a_claim_wrapped_mid_phrase_is_still_found` plants a sample split
INSIDE the matched phrase and asserts a line scan of it finds nothing while the
collapsed scan finds exactly one.

Offline, deterministic, fresh-clone safe: pure ``tokenize``/``ast`` reads of files
under ``src/proactive_loop/`` (the FILESYSTEM, not ``git ls-files``, so an
untracked module cannot fall outside the domain it is measured in) plus one
import of the product's own registry. No subprocess, no network, no clock, no
writes anywhere.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

from proactive_loop.collectors import all_collectors
from proactive_loop.collectors.base import BaseCollector

REPO = Path(__file__).resolve().parents[1]
SRC_PKG = REPO / "src" / "proactive_loop"
BASE_MODULE = SRC_PKG / "collectors" / "base.py"

# Anti-vacuity floors for the live census. Every one sits far BELOW what the
# package measured when this guard shipped, so ordinary growth or a refactor
# never trips them while an extractor regression to "" cannot pass. They are the
# floors the spec named, not a copy of a handed-over measurement: pinning a floor
# at a number produced by somebody else's extractor convention fails on arrival.
MIN_CENSUS_FILES = 25
MIN_CENSUS_CHARS = 200_000
MIN_CLAIM_SITES = 2

# How much of the surrounding sentence a finding carries, so a failure message
# points at the phrase to fix instead of only naming the file.
_EXCERPT_PAD = 40

# A decimal integer immediately followed by ``generated``, an optional
# ``dataclass``, a backticked ``__init__`` in single OR double backticks, then
# ``signatures``. The two real sites spell it differently -- one is a comment with
# single backticks and the word ``dataclass``, the other a docstring with double
# backticks and no ``dataclass`` -- so a matcher pinned to one spelling silently
# covers only half the defect.
SIGNATURE_COUNT_CLAIM = re.compile(
    r"(?P<count>\d+)\s+generated\s+(?:dataclass\s+)?`{1,2}__init__`{1,2}\s+signatures",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Claim:
    """One signature-count claim site: the number it asserts, and the phrase."""

    count: int
    excerpt: str


def find_signature_count_claims(text: str) -> tuple[Claim, ...]:
    """Report every signature-count claim in ``text``, one per site.

    Pure and whitespace-insensitive: the input is collapsed to single spaces
    first, because the phrase wraps across lines in real source. Collapsing also
    keeps this module off the 3.12/3.13 trap -- 3.13 strips the common leading
    docstring indent at compile time and 3.12 does not, and no assertion here can
    see indentation.
    """
    flat = re.sub(r"\s+", " ", text)
    return tuple(
        Claim(
            count=int(match.group("count")),
            excerpt=flat[max(0, match.start() - _EXCERPT_PAD) : match.end() + _EXCERPT_PAD],
        )
        for match in SIGNATURE_COUNT_CLAIM.finditer(flat)
    )


def expected_signature_count() -> int:
    """The one true value: the size of the product's explicit collector registry."""
    return len(all_collectors())


def prose_of(source: str) -> str:
    """Every comment and docstring in ``source``, joined and space-collapsed.

    Comments come from ``tokenize`` and docstrings from ``ast.get_docstring`` so
    that string literals, identifiers and regex bodies are NEVER read: a module
    that legitimately spells the hunted phrase inside a pattern must not be
    flagged for the thing it exists to detect.
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


# The pre-fix text of the two wrong sites, lifted VERBATIM so the fixtures are
# evidence rather than invention. Note they differ: a single-backtick comment
# carrying the extra word ``dataclass``, and a double-backtick docstring without
# it. A pattern that stops matching either sample is dead code.
PLANTED_POSITIVES: tuple[str, ...] = (
    "to all 16 generated dataclass `__init__` signatures and reorder them), and the",
    "all 16 generated ``__init__`` signatures and reorder them, which surfaces as a",
)

# The same claim split INSIDE the matched phrase -- between ``generated`` and the
# backticked dunder -- which is what a line-oriented scan cannot see.
WRAPPED_CLAIM = (
    "Subclasses contribute a field to all 16 generated\n"
    "``__init__`` signatures and reorder them, which surfaces as a keyword change.\n"
)

# Real in-repo prose that must stay clean, or the guard becomes a machine for
# deleting honest history. The first is the DATED verb-count note this iteration
# reworded: a record of what was true when ``scan --json`` landed, which is
# history rather than a claim about the current tree, and not a signature-count
# claim at all.
REAL_NEGATIVES: tuple[str, ...] = (
    "``--json`` is the machine-readable idiom on 14 of the 16 verbs, as measured "
    "when ``scan --json`` landed",
    "every collector contributes a field to the generated ``__init__`` signatures",
    "17 collectors ship in the default roster",
    "reorder the 16 verbs so ``watch`` sorts last",
    "the generated signatures are keyword-only, so 16 positional args are impossible",
)


# ===========================================================================
# Behavior 4 -- the detector is alive: it fires on each pre-fix site.
# ===========================================================================
def test_each_prefix_site_is_a_planted_positive() -> None:
    for sample in PLANTED_POSITIVES:
        claims = find_signature_count_claims(sample)
        assert len(claims) == 1, (
            f"the matcher no longer fires on the very site it was written for -- it "
            f"is dead code and the census is vacuous: {sample!r} -> {claims}"
        )
        assert claims[0].count == 16, (
            f"the pre-fix sites claimed 16; matcher read {claims[0].count}: {claims[0]}"
        )


def test_the_two_planted_samples_are_spelled_differently() -> None:
    """A matcher pinned to one spelling would silently cover only one site."""
    comment_sample, docstring_sample = PLANTED_POSITIVES
    assert "dataclass" in comment_sample and "``__init__``" not in comment_sample
    assert "dataclass" not in docstring_sample and "``__init__``" in docstring_sample


def test_a_finding_names_its_value_and_quotes_the_phrase() -> None:
    claims = find_signature_count_claims(PLANTED_POSITIVES[0])
    assert claims
    for claim in claims:
        assert claim.count > 0
        assert "signatures" in claim.excerpt, (
            f"a finding must quote the matched phrase, not just name a file: {claim}"
        )


# ===========================================================================
# Behavior 3 -- the matcher is whitespace-normalized ACROSS LINES.
# ===========================================================================
def test_a_claim_wrapped_mid_phrase_is_still_found() -> None:
    line_hits = [
        line for line in WRAPPED_CLAIM.splitlines() if SIGNATURE_COUNT_CLAIM.search(line)
    ]
    assert line_hits == [], (
        "the fixture must be split INSIDE the matched phrase, or it proves nothing "
        f"about cross-line matching: a line scan found {line_hits}"
    )
    claims = find_signature_count_claims(WRAPPED_CLAIM)
    assert len(claims) == 1, (
        f"a claim wrapped mid-phrase must still report exactly one site: {claims}"
    )
    assert claims[0].count == 16


# ===========================================================================
# Behavior 6 -- the guard is not a false-positive machine.
# ===========================================================================
def test_real_legitimate_prose_survives() -> None:
    for sample in REAL_NEGATIVES:
        assert find_signature_count_claims(sample) == (), (
            "this is real, legitimate in-repo prose -- flagging it would turn the "
            f"guard into a machine for deleting honest history: {sample!r}"
        )


def test_the_matcher_needs_all_three_anchors() -> None:
    """Number, ``generated``, the backticked dunder and ``signatures``: all four."""
    near_misses = (
        "all 16 generated `__init__` methods",
        "all 16 `__init__` signatures",
        "all generated `__init__` signatures",
        "all 16 generated signatures",
    )
    for sample in near_misses:
        assert find_signature_count_claims(sample) == (), sample


# ===========================================================================
# Behavior 2 -- the expected value is the closed registry, not ambient state.
# ===========================================================================
def test_expected_count_is_the_explicit_registry() -> None:
    assert expected_signature_count() == len(all_collectors())
    assert expected_signature_count() > 0


def test_expected_count_ignores_ambient_subclass_state() -> None:
    """Defining another ``BaseCollector`` descendant must not move the number."""
    before = expected_signature_count()

    class _CensusProbeCollector(BaseCollector):  # pragma: no cover - never collected
        name = "_census_probe"

    assert _CensusProbeCollector.__name__ not in {type(c).__name__ for c in all_collectors()}
    assert expected_signature_count() == before, (
        "the expected value moved when a subclass was defined, so it is bound to "
        "ambient descendant state and will report correct prose as wrong whenever "
        "another test module happens to be imported first"
    )


def test_this_module_never_enumerates_subclasses() -> None:
    """The dunder descendant hook must not appear in this file at all.

    The needle is built from two halves on purpose, so that asserting its absence
    does not itself introduce the token and make the check impossible to pass.
    """
    needle = "__sub" + "classes__"
    text = Path(__file__).read_text(encoding="utf-8")
    assert needle not in text, (
        "this census must derive its expected value from the closed registry; the "
        "descendant hook is ambient state that other test modules mutate"
    )


# ===========================================================================
# Behaviors 1, 5 and 7 -- the live census over the package.
# ===========================================================================
@dataclass(frozen=True)
class CensusResult:
    """What a census run EXAMINED as well as what it found.

    Both halves are asserted separately on purpose: an extractor that returns
    "" reports zero offenders and looks perfect, which is the fail-open shape
    this repo keeps rediscovering.
    """

    files: int
    chars: int
    sites: int
    offenders: tuple[str, ...]


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return path.name


def census(paths: Iterable[Path], expected: int) -> CensusResult:
    """Compare every signature-count claim under ``paths`` against ``expected``."""
    files = 0
    chars = 0
    sites = 0
    offenders: list[str] = []
    for path in paths:
        files += 1
        prose = prose_of(path.read_text(encoding="utf-8"))
        chars += len(prose)
        for claim in find_signature_count_claims(prose):
            sites += 1
            if claim.count != expected:
                offenders.append(
                    f"{_label(path)} claims {claim.count}, registry holds {expected} "
                    f"...{claim.excerpt}..."
                )
    return CensusResult(files=files, chars=chars, sites=sites, offenders=tuple(offenders))


def test_no_signature_count_claim_in_src_disagrees_with_the_registry() -> None:
    expected = expected_signature_count()
    result = census(_package_modules(), expected)

    assert result.files >= MIN_CENSUS_FILES, (
        f"census walked only {result.files} modules under "
        f"{SRC_PKG.relative_to(REPO)} -- the glob is fail-open, so a zero-offender "
        "result proves nothing"
    )
    assert result.chars >= MIN_CENSUS_CHARS, (
        f"census extracted only {result.chars} chars of comment/docstring prose -- "
        "the extractor is returning near-empty text, so the scan is vacuous"
    )
    assert result.sites >= MIN_CLAIM_SITES, (
        f"census found only {result.sites} signature-count claim site(s) -- the "
        "matcher no longer sees the prose it guards, so a clean result means nothing"
    )
    assert not result.offenders, (
        "these src/ comments miscount the product's own collector registry. The "
        "number must equal len(all_collectors()); a reader of a public portfolio "
        f"repo can re-derive it in one command: {list(result.offenders)}"
    )


def test_the_census_fires_on_a_stale_site_and_names_all_three_facts(tmp_path: Path) -> None:
    """Two-sided at the CENSUS level, not merely at the matcher level.

    A live census that can never report an offender is ``assert True``, so the
    same code path that scans the package is pointed at a planted stale module
    here. The message must name the MODULE, the CLAIMED value and the DERIVED
    value, because a failure naming only a file leaves the reader to re-derive
    the number the guard already knows.
    """
    module = tmp_path / "stale_module.py"
    module.write_text(
        chr(34) * 3
        + "Subclasses contribute a field to all 16 generated ``__init__`` signatures.\n"
        + chr(34) * 3
        + "\n",
        encoding="utf-8",
    )
    result = census([module], expected=17)

    assert result.sites == 1, result
    assert len(result.offenders) == 1, result
    offender = result.offenders[0]
    assert "stale_module.py" in offender, offender
    assert "16" in offender, offender
    assert "17" in offender, offender


def test_the_census_passes_a_site_that_agrees(tmp_path: Path) -> None:
    """The mirror of the test above: agreement must NOT be reported as a defect."""
    module = tmp_path / "fresh_module.py"
    module.write_text(
        chr(34) * 3
        + "Subclasses contribute a field to all 17 generated ``__init__`` signatures.\n"
        + chr(34) * 3
        + "\n",
        encoding="utf-8",
    )
    result = census([module], expected=17)

    assert result.sites == 1, result
    assert result.offenders == (), result


def test_base_py_states_the_count_with_exactly_one_value() -> None:
    claims = find_signature_count_claims(prose_of(BASE_MODULE.read_text(encoding="utf-8")))
    assert len(claims) >= MIN_CLAIM_SITES, (
        f"expected the repeated precondition to be visible in {BASE_MODULE.name}; "
        f"found {len(claims)} site(s)"
    )
    distinct = sorted({claim.count for claim in claims})
    assert len(distinct) == 1, (
        f"{BASE_MODULE.name} states one precondition with {len(distinct)} different "
        f"numbers {distinct} -- the module contradicts itself: {claims}"
    )
    assert distinct[0] == expected_signature_count()


# ===========================================================================
# Behavior 8 -- prose only: the guarded text never reaches product output.
# ===========================================================================
def _cli_stdout(capsys: pytest.CaptureFixture[str], argv: list[str]) -> str:
    from proactive_loop.cli import main

    assert main(argv) == 0, f"pla {' '.join(argv)} exited non-zero"
    return capsys.readouterr().out


def test_guarded_prose_never_reaches_product_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Why this is the right black-box oracle for "no runtime change".

    A comment or docstring edit cannot alter observable behavior unless the text
    is RENDERED somewhere, so the durable assertion is that the guarded shape is
    absent from the surfaces that enumerate the registry. The floor on output
    length is what stops this from passing on an empty capture.
    """
    for argv in (["collectors"], ["collectors", "--json"]):
        out = _cli_stdout(capsys, argv)
        assert len(out) > 500, (
            f"pla {' '.join(argv)} produced only {len(out)} chars, so asserting the "
            "guarded prose is absent from it proves nothing"
        )
        assert find_signature_count_claims(out) == (), (
            f"pla {' '.join(argv)} renders a signature-count claim into user-visible "
            "output, so editing that prose would be a RUNTIME change, not a comment "
            f"change: {find_signature_count_claims(out)}"
        )


def test_the_registry_surface_is_reproducible(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Same input, same bytes -- the offline-deterministic bar, on the roster verb."""
    first = _cli_stdout(capsys, ["collectors", "--json"])
    second = _cli_stdout(capsys, ["collectors", "--json"])
    assert first == second, "pla collectors --json is not reproducible run-to-run"
    assert len(first) > 500, "capture floor: an empty roster would pass vacuously"
