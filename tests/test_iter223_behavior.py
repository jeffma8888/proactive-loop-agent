"""Repo contract: ``ROADMAP.md`` cites evidence by PATH and SYMBOL, never by LINE NUMBER.

WHY A LINE NUMBER IS A DEFECT AND NOT A CONVENIENCE
``ROADMAP.md`` is a per-iteration required read and this loop's only evidence trail,
on a PUBLIC portfolio repo. ``src/proactive_loop/cli.py`` is over 6,000 lines and
nearly every iteration edits it, so a ``path:LINE`` anchor written today lands on
unrelated code within a few ships -- structural drift, not sloppiness. Measured at
the state of iteration 244, before the conversion this module guards: 25 distinct
locators, 9 of them demonstrably stale, including row #170 citing ``cli.py:780`` for
a flag whose first real occurrence was line 351, and row #192 citing both a line
range and a code shape (``and top is None``) that occurred ZERO times in the file.

The cost is not cosmetic. A cited anchor that lands on unrelated code makes a TRUE
claim read as FABRICATED, and it silently converts "measured" into "asserted": the
next PM to select a queued row inherits a premise it cannot verify. A backticked
SYMBOL has neither failure mode -- it survives every edit that does not rename it,
and its presence in the cited file is mechanically checkable.

WHY THIS IS A BAN AND NOT A RE-NUMBERING
Re-numbering buys one iteration of accuracy and then decays again, so the fix has to
remove the SHAPE. Every converted row already carried a backticked symbol in the same
table cell, so the conversion was a DELETION of a ``:NNN`` suffix, never the invention
of a new anchor.

WHY THE GUARD IS TWO-SIDED IN BOTH DIRECTIONS, AND CARRIES NO EXEMPTION SET
1. Against the DETECTOR being dead. An absence assertion that has never been seen to
   FIRE is indistinguishable from ``assert True``, so :func:`locator_offences` is a
   pure text -> verdict function and is fired at the four REAL pre-fix spellings
   (:data:`REJECTED_SAMPLES`) as synthetic strings. The live file is never the
   instrument used to test the instrument.
2. Against the matcher being OVER-BROAD. A ban wide enough to catch ``cli.py:780``
   can easily also catch ``career:4.5`` in an env-var value or a pytest node id, and
   a contributor's remedy for a false positive is to weaken the guard. So six REAL
   colon-bearing tokens already in the file (:data:`ACCEPTED_SAMPLES`) must be
   accepted BYTE-IDENTICAL, and each is separately asserted to still occur in the
   live file so the control cannot go stale.

There is deliberately NO allowlist on the ban: the pattern excludes all six accepted
samples on SHAPE alone (a digit-run that continues into a decimal point, or a colon
followed by anything but digits, is not a line number). An exemption is the one place
a guard can never look, so the shape does the work instead.

WHY THE PATH CENSUS NEEDS A DECLARED-ABSENT MAP, AND WHY IT IS SELF-CLEANING
The second half of the contract is that a cited FILE actually exists: a token bearing
a recognised source extension must resolve to a path ``git ls-files`` reports as
tracked. Four cited tokens legitimately do not -- two are foundry state artifacts
that live outside the repo, two name documents a QUEUED row PROPOSES. Those sit in
:data:`CITED_BUT_UNTRACKED` with a reason each, and the map is self-cleaning in the
opposite direction: every key must STILL be untracked, so the day one of those files
ships, the stale exemption reds the build instead of quietly widening.

Offline, deterministic, fresh-clone safe: pure text over one GIT-TRACKED file plus
this module's own source, and one ``git ls-files`` read that SKIPS with a named reason
when the checkout carries no history. No product import, no network, no clock, no
writes. ``ROADMAP_ARCHIVE.md`` is deliberately OUT of the domain -- it is a
point-in-time record, so rewriting its anchors would falsify it -- and
:func:`test_b08_the_guards_domain_is_the_live_index_only` proves this module never
reads it.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
ROADMAP: Final[Path] = REPO_ROOT / "ROADMAP.md"
THIS_MODULE: Final[Path] = Path(__file__).resolve()

#: The guarded document, named in every verdict so a failure is actionable without
#: opening this file.
GUARDED_FILENAME: Final[str] = "ROADMAP.md"

#: Extensions that make a cited token a claim about a FILE in this repo. A token
#: without one of these (a collector kind such as ``git_stash``, a test-module stem
#: such as ``test_iter108``) is a symbol, not a path, and is out of the census.
SOURCE_EXTENSIONS: Final[tuple[str, ...]] = (
    ".py",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".cfg",
    ".lock",
)

#: One backticked span. Line-scoped (``[^`\n]``) so an unbalanced backtick cannot
#: swallow the rest of a 3,000-character table row.
_BACKTICKED: Final[re.Pattern[str]] = re.compile(r"`([^`\n]+)`")

#: A ``TOKEN:LINE`` locator, where the suffix is a single line (``:80``), a range
#: (``:815-819``) or a list (``:129,132-134``).
#:
#: Two shape rules keep it from over-matching, and both are exercised by
#: :data:`ACCEPTED_SAMPLES`: the token must END in a name character, and the digit
#: run must NOT continue into a decimal point (``career:4.5`` is a threshold, not a
#: line). The leading lookbehind stops a match from starting mid-token.
_LOCATOR: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_./-]*[A-Za-z0-9_-]):(\d+(?:[-,]\d+)*)(?![.\d])"
)

#: An ORPHAN continuation locator -- a whole backticked span that is nothing but a
#: line reference, used in the live file to bolt a second line onto the previous
#: token (``` `test_iter149:338`/`:422` ```). It carries no path at all, so it is the
#: least recoverable spelling of the defect.
_ORPHAN: Final[re.Pattern[str]] = re.compile(r"^:(\d+(?:[-,]\d+)*)$")

#: The same defect spelled WITHOUT backticks against a bare document name. Restricted
#: to the four documents this repo refers to by bare name, because an unrestricted
#: version of this pattern would match ordinary prose such as a time of day.
_BARE_DOCUMENT: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9_./`-])(?:README|SPEC|Makefile|ROADMAP)(?:\.[a-z]+)?"
    r":(\d+(?:[-,]\d+)*)(?![.\d])"
)

#: A token that CLAIMS to name a file: at least one name character before the dot, so
#: the bare extension fragment in a glob such as ``TESTS_DIR.glob("test_*.py")`` is not
#: read as a file citation.
_CITED_PATH: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z0-9_./-]*[A-Za-z0-9_-]\.(?:py|md|toml|yml|yaml|cfg|lock)\b"
)

#: The four REAL pre-fix spellings, kept as the BAD side of the two-sided control.
#: Each was in ``ROADMAP.md`` at iteration 244 and must now be rejected on sight.
REJECTED_SAMPLES: Final[tuple[str, ...]] = (
    "`cli.py:780`",
    "`git_stash:85`",
    "`SPEC.md:815-819`",
    "README:524-556",
)

#: Six REAL colon-bearing tokens the ban must NOT touch -- the GOOD side of the
#: control, proving the matcher is shape-driven rather than "any colon". A threshold
#: list, three YAML/TOML-ish key-value shapes, a stage-budget trailer and a pytest
#: node id.
ACCEPTED_SAMPLES: Final[tuple[str, ...]] = (
    "`PLA_CATEGORY_MIN_SCORE=career:4.5,project:3.0`",
    "`runs: []`",
    "`suppressed: N`",
    "`type: ignore`",
    "stage-budget: WARN",
    "`test_iter115_behavior.py::test_b8_roadmap_row_owns_the_deferred_flag`",
)

#: Cited tokens that name a file git does NOT track, each with the reason it is
#: legitimate. Self-cleaning: :func:`test_b05_the_declared_absent_map_is_self_cleaning`
#: fails once any of them becomes tracked, so the map cannot rot into a fail-open
#: dumping ground.
CITED_BUT_UNTRACKED: Final[dict[str, str]] = {
    "pm.md": "a foundry per-iteration state artifact, outside this repo by design",
    "pm_scout_b.md": "a foundry per-iteration state artifact, outside this repo by design",
    "SPEC_ARCHIVE.md": "PROPOSED by a queued row (the SPEC.md counterpart of the roadmap archive)",
    "tests/conftest.py": "PROPOSED by queued row #218; the repo deliberately has no conftest yet",
}

#: Anti-vacuity floors. A census that measured nothing passes every absence assertion,
#: which is the failure a green run cannot be told apart from health.
MIN_CITED_PATHS: Final[int] = 20
MIN_BACKTICKED_SPANS: Final[int] = 200


@dataclass(frozen=True)
class LocatorVerdict:
    """The outcome of one locator sweep over a document.

    ``message`` is populated on BOTH branches for the reason the sibling size-budget
    guard gives: a consumer that only prints on failure cannot tell a passing sweep
    from one that forgot to measure.
    """

    ok: bool
    offences: tuple[str, ...]
    message: str


def locator_offences(text: str) -> tuple[str, ...]:
    """Every line-number locator in ``text``, in order of appearance.

    Pure, and takes TEXT rather than a path, so the ban can be fired at synthetic
    strings instead of only at the document it polices. Three spellings are swept:
    a backticked ``TOKEN:LINE``, a whole backticked span that is only ``:LINE``, and
    a bare document name carrying a line suffix outside backticks.
    """
    found: list[str] = []
    for span in _BACKTICKED.finditer(text):
        body = span.group(1)
        if _ORPHAN.match(body):
            found.append(f"`{body}`")
            continue
        found.extend(hit.group(0) for hit in _LOCATOR.finditer(body))
    found.extend(hit.group(0) for hit in _BARE_DOCUMENT.finditer(text))
    return tuple(found)


def check_no_line_locators(text: str, *, name: str = GUARDED_FILENAME) -> LocatorVerdict:
    """Verdict on whether ``text`` is free of line-number evidence anchors."""
    offences = locator_offences(text)
    if offences:
        return LocatorVerdict(
            ok=False,
            offences=offences,
            message=(
                f"{name} carries {len(offences)} line-number locator(s): "
                f"{list(offences)}. A line number in this file is stale on arrival -- "
                f"{name} is rewritten every iteration and cli.py is over 6,000 lines. "
                "Cite the path plus a backticked SYMBOL instead; the symbol survives "
                "every edit that does not rename it."
            ),
        )
    return LocatorVerdict(
        ok=True,
        offences=(),
        message=(
            f"{name} is free of line-number locators across "
            f"{len(_BACKTICKED.findall(text))} backticked span(s)"
        ),
    )


def cited_source_files(text: str) -> tuple[str, ...]:
    """Distinct file-naming tokens cited inside backticked spans, sorted.

    Only backticked spans count: the surrounding prose says things like "the README"
    and "SPEC.md section 2" in sentences, and a citation this repo means as evidence
    is always in code font.
    """
    tokens = {
        hit.group(0)
        for span in _BACKTICKED.finditer(text)
        for hit in _CITED_PATH.finditer(span.group(1))
    }
    return tuple(sorted(tokens))


def resolve_cited_path(token: str, tracked: tuple[str, ...]) -> str | None:
    """The tracked path ``token`` names, or ``None``.

    A citation may be written in full (``examples/check_run.py``) or as the readable
    tail of one (``dir_source.py``), so a UNIQUE suffix match resolves. An AMBIGUOUS
    suffix -- two tracked files sharing that tail -- does NOT: it identifies no single
    file, which is exactly the ambiguity a line number used to paper over.
    """
    if token in tracked:
        return token
    matches = [path for path in tracked if path.endswith("/" + token)]
    return matches[0] if len(matches) == 1 else None


def _read_roadmap() -> str:
    """Text of the guarded document, failing loudly rather than censusing nothing."""
    text = ROADMAP.read_text(encoding="utf-8")
    assert text.strip(), f"{GUARDED_FILENAME} must not be empty (a vacuous census is no census)"
    return text


def _tracked_paths() -> tuple[str, ...]:
    """Every path git tracks, or ``pytest.skip`` naming the missing precondition.

    Skipping is correct rather than failing: a source zip has no history, so the
    census has no ground truth to measure against. The count is asserted non-zero so a
    working ``git`` that returns nothing is a failure, not a silent pass.
    """
    if shutil.which("git") is None:
        pytest.skip("precondition missing: `git` is not on PATH")
    if not (REPO_ROOT / ".git").exists():
        pytest.skip(f"precondition missing: no `.git` entry at the repo root ({REPO_ROOT})")
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(
            f"precondition missing: `git ls-files` exited {proc.returncode} -- "
            "this checkout carries no history"
        )
    paths = tuple(proc.stdout.split())
    assert paths, "`git ls-files` reported no tracked path at all"
    return paths


# ---------------------------------------------------------------------------
# The live document.
# ---------------------------------------------------------------------------
def test_b01_the_live_index_cites_no_line_numbers() -> None:
    verdict = check_no_line_locators(_read_roadmap())

    assert verdict.ok, verdict.message


def test_b01_the_verdict_reports_its_measurement_in_the_green_case_too() -> None:
    verdict = check_no_line_locators(_read_roadmap())

    assert verdict.ok
    assert GUARDED_FILENAME in verdict.message
    assert "backticked span(s)" in verdict.message


# ---------------------------------------------------------------------------
# The ban is two-sided: it must FIRE, and it must not over-fire.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sample", REJECTED_SAMPLES)
def test_b02_the_ban_fires_on_each_real_pre_fix_spelling(sample: str) -> None:
    """BAD side, on SYNTHETIC strings: the live file is never used to test the matcher."""
    verdict = check_no_line_locators(f"| 1 | a row citing {sample} as evidence |")

    assert verdict.ok is False
    assert verdict.offences, f"the ban did not see {sample!r}"
    assert sample.strip("`") in verdict.message


@pytest.mark.parametrize("sample", REJECTED_SAMPLES)
def test_b02_no_real_pre_fix_spelling_survives_in_the_live_index(sample: str) -> None:
    assert sample not in _read_roadmap()


def test_b02_the_ban_sees_an_orphan_continuation_token() -> None:
    """The spelling with no path at all -- ``` `test_iter149`/`:422` ```."""
    verdict = check_no_line_locators("cited as `test_iter149`/`:422` in the census")

    assert verdict.offences == ("`:422`",)


def test_b02_the_ban_sees_a_compound_token_that_carries_a_symbol() -> None:
    """One span holding BOTH a line and a symbol still names the line."""
    verdict = check_no_line_locators("normalization (`cli.py:1232 _relative_signal_path`)")

    assert verdict.offences == ("cli.py:1232",)


@pytest.mark.parametrize("sample", ACCEPTED_SAMPLES)
def test_b03_the_ban_accepts_each_real_colon_bearing_token(sample: str) -> None:
    """GOOD side: proof the matcher is shape-driven, not "any colon"."""
    verdict = check_no_line_locators(f"| 1 | a row mentioning {sample} inline |")

    assert verdict.ok, verdict.message


@pytest.mark.parametrize("sample", ACCEPTED_SAMPLES)
def test_b03_each_accepted_sample_is_still_present_in_the_live_index(sample: str) -> None:
    """A control drawn from the live file must stay drawn from it, byte-identical."""
    assert sample in _read_roadmap(), f"the accepted control {sample!r} is no longer in the file"


def test_b03_a_decimal_threshold_is_not_a_line_number() -> None:
    """The narrowest edge in the accepted set, asserted on its own.

    ``career:4.5`` differs from ``cli.py:780`` only in what FOLLOWS the digit run, so
    this is the single assertion standing between the ban and a false positive on
    every threshold in the file.
    """
    assert locator_offences("`career:4.5,project:3.0`") == ()
    assert locator_offences("`career:4`") == ("career:4",)


# ---------------------------------------------------------------------------
# A cited file must exist.
# ---------------------------------------------------------------------------
def test_b04_every_cited_source_file_resolves_to_a_tracked_path() -> None:
    tracked = _tracked_paths()
    cited = cited_source_files(_read_roadmap())
    unresolved = [
        token
        for token in cited
        if resolve_cited_path(token, tracked) is None and token not in CITED_BUT_UNTRACKED
    ]

    assert unresolved == [], (
        f"{GUARDED_FILENAME} cites {unresolved}, which git does not track. Either the "
        "citation is wrong, or the file is legitimately absent -- in which case add it "
        "to CITED_BUT_UNTRACKED with the reason."
    )


def test_b04_the_census_is_not_vacuous() -> None:
    text = _read_roadmap()

    assert len(cited_source_files(text)) >= MIN_CITED_PATHS
    assert len(_BACKTICKED.findall(text)) >= MIN_BACKTICKED_SPANS


def test_b04_the_resolver_is_two_sided_on_synthetic_input() -> None:
    tracked = ("src/proactive_loop/cli.py", "tests/test_a.py", "docs/test_a.py")

    assert resolve_cited_path("src/proactive_loop/cli.py", tracked) == "src/proactive_loop/cli.py"
    assert resolve_cited_path("cli.py", tracked) == "src/proactive_loop/cli.py"
    assert resolve_cited_path("nowhere.py", tracked) is None
    assert resolve_cited_path("test_a.py", tracked) is None, "an ambiguous tail resolves nothing"


def test_b04_a_bare_extension_fragment_is_not_a_file_citation() -> None:
    """``TESTS_DIR.glob("test_*.py")`` cites a glob, not a path."""
    assert cited_source_files('`TESTS_DIR.glob("test_*.py")`') == ()
    assert cited_source_files("`models.py`") == ("models.py",)


def test_b05_the_declared_absent_map_is_self_cleaning() -> None:
    """Each exemption must still be needed, and must say why it exists."""
    tracked = _tracked_paths()
    for token, reason in CITED_BUT_UNTRACKED.items():
        assert resolve_cited_path(token, tracked) is None, (
            f"{token!r} is tracked now -- delete its CITED_BUT_UNTRACKED entry"
        )
        assert len(reason.split()) >= 5, f"the exemption on {token!r} states no reason: {reason!r}"


def test_b05_every_exemption_is_actually_cited_by_the_document() -> None:
    """A dead exemption is dead text: the token must still appear in the file."""
    cited = set(cited_source_files(_read_roadmap()))

    assert set(CITED_BUT_UNTRACKED) <= cited, (
        f"these exemptions cite nothing any more: {sorted(set(CITED_BUT_UNTRACKED) - cited)}"
    )


# ---------------------------------------------------------------------------
# What this iteration corrected, and the guard's domain.
# ---------------------------------------------------------------------------
def test_b07_row_192_no_longer_asserts_a_code_shape_that_does_not_occur() -> None:
    """The void claim goes; the symbol that DOES occur carries the row.

    ``and top is None`` occurred ZERO times in ``cli.py`` when it was measured, and
    the row's own earlier self-correction to a second line number was stale too.
    """
    text = _read_roadmap()
    row = next(line for line in text.splitlines() if line.startswith("| 192 |"))

    assert "and top is None" not in text
    assert "Line ref drifted" not in text
    assert "`_cmd_run`" in row


def test_b08_the_guards_domain_is_the_live_index_only() -> None:
    """The archive is a point-in-time record: rewriting its anchors would falsify it.

    Proved over this module's OWN source, because a prose promise is not a domain, and
    proved STRUCTURALLY rather than by searching the source text for the archive's
    name: this module's docstring has to NAME the archive in order to explain why it
    is excluded, so an absence-of-the-name check is unsatisfiable by construction --
    it would fail on a correct module and the only way to green it would be to delete
    the explanation. So the two decidable facts are asserted instead: which names are
    read, and which filenames are joined onto the repo root.
    """
    tree = ast.parse(THIS_MODULE.read_text(encoding="utf-8"))
    receivers = {
        node.func.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read_text"
        and isinstance(node.func.value, ast.Name)
    }
    joined = {
        node.right.value
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and isinstance(node.right, ast.Constant)
        and isinstance(node.right.value, str)
    }

    assert receivers == {"ROADMAP", "THIS_MODULE"}, f"unexpected read target(s): {receivers}"
    assert joined == {"ROADMAP.md", ".git"}, f"unexpected document(s) resolved: {joined}"


def test_b08_this_module_imports_no_product_code() -> None:
    tree = ast.parse(THIS_MODULE.read_text(encoding="utf-8"))
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "proactive_loop" not in imported, "a docs guard must not depend on product code"
