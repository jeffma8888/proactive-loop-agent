"""Black-box oracle for factory iteration 244 -- the live index sheds its line anchors.

Feature under test: ``ROADMAP.md``'s live index cites evidence as ``path`` (or a
backticked SYMBOL) with NO line number, every remaining file citation resolves to a
git-tracked path, and a new guard bans the reintroduction of a ``:LINE`` locator.
``ROADMAP_ARCHIVE.md`` is deliberately OUT of that domain -- it is a point-in-time
record, so converting its anchors would falsify it.

MODULE NAME (derived from the repo, never from the state dir). ``git ls-files tests``
tops out at ``test_iter223_behavior.py`` (this iteration's guard, already staged) and
``git cat-file -e HEAD:tests/test_iter224_behavior.py`` fails, so 224 is the next free
number. The foundry state dir for this ship is ``iter-244``; naming a module from that
counter is how an already-shipped oracle gets overwritten, so the repo wins.

ISOLATION CONTRACT (honored, no exceptions). Every assertion below is derived from this
iteration's ``pm.md`` "Expected Behaviors" 1-8, from the two documents under test, and
from the conventions of ``tests/test_iter214_behavior.py`` and
``tests/test_iter222_behavior.py``. **No file under ``src/`` was read as source text,
no engineer or reviewer note was opened, and no ``git diff`` was consulted.** Behavior 7
counts one symbol's occurrences in one tracked source file with ``str.count`` -- a
mechanical census that an anchor-resolvability claim is not checkable without, never a
read of the surrounding design.

TWO-SIDED BY CONSTRUCTION. The ban is fired at synthetic pre-fix spellings (must fire)
and at the six real colon-bearing tokens the document legitimately carries (must not),
and its domain is proved by pointing the SAME matcher at the archive, where the anchors
must SURVIVE. Nothing here depends on git HISTORY of a document, because a fresh clone
of the shipping commit sees the converted file at HEAD -- a control drawn from
``git show HEAD:ROADMAP.md`` would silently go vacuous there.

Offline, deterministic, fresh-clone safe: pure text over two tracked documents plus one
``git ls-files`` read that SKIPS with a named reason when the checkout carries no
history. No product import, no network, no clock, no writes, and no assertion on
docstring or help-text INDENTATION, so the 3.12/3.13 CI legs cannot diverge.

Coverage (numbered to match the spec's Expected Behaviors):

1. ``ROADMAP.md`` carries ZERO backticked ``TOKEN:DIGITS`` locators (single line, range
   or list), against a domain asserted non-empty in backticked spans.
2. ZERO unbackticked bare-name locators for ``README`` / ``SPEC`` / ``Makefile`` /
   ``ROADMAP``, and ZERO orphan ``:DIGITS`` continuation tokens.
3. Every backticked extension-bearing token resolves to a TRACKED path, exactly or as a
   unique suffix; the only tolerated misses are a small DECLARED-ABSENT set, asserted
   self-cleaning in the dangerous direction (still cited AND still untracked).
4. Domain scoping: the archive KEEPS its own line anchors, and it records this
   iteration's retired row exactly once.
5. Ban fires on every pre-fix spelling, including a locator followed by a sentence
   period -- a shape a naive decimal exclusion silently excuses.
6. Ban accepts all six real colon-bearing tokens, each asserted still PRESENT.
7. Row #192 drops the code shape ``and top is None`` (which occurs ZERO times in the
   file it was cited from) and the stale ``cli.py:4778`` self-correction, and cites a
   symbol that does occur.
8. The live index table stays well-formed, and the Done-ledger record for this
   iteration lives in exactly ONE of the two documents. The published CHAR BUDGET half
   of this behavior is deliberately NOT restated here: ``test_iter172_behavior.py``
   enforces SINGLE OWNERSHIP of that bound through a ``SIZE_BOUND_ALLOWLIST`` census,
   and a second black-box restatement reds the build by design. Measured, not assumed --
   a duplicate ``10_000 <= size <= 40_000`` assertion in this module made that census
   fail with "Newly bounding: [tests/test_iter224_behavior.py]", so the coverage is left
   with its existing owner instead of widening an allowlist to admit a redundant copy.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Final

import pytest

REPO: Final[Path] = Path(__file__).resolve().parents[1]
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"

#: A locator inside a code span: a path-shaped token, a colon, then a line, a range
#: (``:N-M``) or a list (``:N,M``). The tail excludes a DECIMAL continuation so that a
#: real config threshold (``career:4.5``) is not a line number, while still firing on a
#: locator trailed by a sentence period (``cli.py:780.``).
BACKTICKED_LINE_LOCATOR: Final[re.Pattern[str]] = re.compile(
    r"`[^`\n]*?[A-Za-z0-9_./-]+:\d+(?:[-,]\d+)*(?!\.?\d)[^`\n]*?`"
)
#: The same locator written WITHOUT backticks against a bare document name.
BARE_NAME_LOCATOR: Final[re.Pattern[str]] = re.compile(
    r"\b(?:README|SPEC|Makefile|ROADMAP)(?:\.md|\.toml)?:\d+(?:[-,]\d+)*(?!\.?\d)"
)
#: An orphan continuation token left behind by a converted range, e.g. ``:422``.
ORPHAN_CONTINUATION: Final[re.Pattern[str]] = re.compile(r"`:\d+(?:[-,]\d+)*`")

SOURCE_EXTENSIONS: Final[tuple[str, ...]] = (
    ".py",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".cfg",
    ".lock",
)

#: Cited tokens that name no tracked file, each with the reason it cannot resolve. The
#: set is tolerated ONLY because both directions are asserted below: a key that becomes
#: tracked, or stops being cited, reds the build instead of quietly widening.
DECLARED_ABSENT: Final[dict[str, str]] = {
    "pm.md": "a foundry per-iteration state artifact, outside this repo by design",
    "pm_scout_b.md": "a foundry per-iteration state artifact, outside this repo by design",
    "SPEC_ARCHIVE.md": "only PROPOSED by a queued row, never created",
    "tests/conftest.py": "cited as a NEGATIVE existence claim -- the repo has none",
}

#: Real colon-bearing tokens the live index legitimately carries (spec behavior 6).
ACCEPTED_SAMPLES: Final[tuple[str, ...]] = (
    "PLA_CATEGORY_MIN_SCORE=career:4.5,project:3.0",
    "runs: []",
    "suppressed: N",
    "type: ignore",
    "stage-budget: WARN",
    "test_iter115_behavior.py::test_b8_roadmap_row_owns_the_deferred_flag",
)

#: Pre-fix spellings that must be rejected. The first four are the spec's; the last two
#: are shapes a decimal-exclusion tail can silently excuse.
REJECTED_SAMPLES: Final[tuple[str, ...]] = (
    "`cli.py:780`",
    "`git_stash:85`",
    "`SPEC.md:815-819`",
    "`cli.py:4043-4045`",
    "`cli.py:780.`",
    "`SPEC.md:785,791`",
)


def _roadmap() -> str:
    return ROADMAP.read_text(encoding="utf-8")


def _tracked_paths() -> frozenset[str]:
    if not (REPO / ".git").exists():
        pytest.skip("no git history in this checkout, so path tracking is unmeasurable")
    done = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(line for line in done.stdout.splitlines() if line)


def _cited_file_tokens(text: str) -> set[str]:
    """Extension-bearing tokens inside code spans, minus bare extension fragments."""
    found: set[str] = set()
    for span in re.findall(r"`([^`\n]+)`", text):
        for token in re.findall(r"[A-Za-z0-9_./-]+", span):
            stem = token.rsplit("/", 1)[-1]
            if token.endswith(SOURCE_EXTENSIONS) and not stem.startswith("."):
                found.add(token)
    return found


def _resolve(token: str, tracked: frozenset[str]) -> str | None:
    if token in tracked:
        return token
    suffix_matches = [path for path in tracked if path.endswith("/" + token)]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    return None


# --------------------------------------------------------------------------- 1


def test_b1_the_live_index_cites_no_backticked_line_locator() -> None:
    hits = sorted({m.group(0) for m in BACKTICKED_LINE_LOCATOR.finditer(_roadmap())})
    assert hits == [], (
        f"ROADMAP.md still cites {len(hits)} line-anchored locator(s), which are stale "
        f"on arrival because every iteration edits the files they point into: {hits}"
    )


def test_b1_the_ban_has_a_non_empty_domain_to_look_at() -> None:
    """An empty document would satisfy the ban vacuously."""
    spans = re.findall(r"`([^`\n]+)`", _roadmap())
    assert len(spans) >= 100, f"only {len(spans)} code span(s) in the live index"


def test_b1_the_ban_ships_as_a_tracked_guard_module() -> None:
    """A ban that is not COMMITTED cannot outlive the iteration that introduced it.

    The conversion half of this feature is a one-off edit; the durable half is the
    guard. If the guard module were left untracked, a fresh clone of the shipping
    commit would carry a clean document and no ban at all, and the next iteration
    could reintroduce a line anchor with nothing to stop it.
    """
    tracked = _tracked_paths()
    guard = "tests/test_iter223_behavior.py"
    assert guard in tracked, (
        f"{guard} is not tracked, so the conversion would ship with NO guard against "
        "reintroducing a line anchor"
    )
    source = (REPO / guard).read_text(encoding="utf-8")
    assert "def locator_offences" in source, (
        f"{guard} exposes no text -> verdict ban function, so its absence assertions "
        "cannot be shown to fire on a known-bad sample"
    )


# --------------------------------------------------------------------------- 2


def test_b2_the_live_index_carries_no_bare_name_locator() -> None:
    hits = sorted({m.group(0) for m in BARE_NAME_LOCATOR.finditer(_roadmap())})
    assert hits == [], f"unbackticked document locator(s) survive: {hits}"


def test_b2_the_live_index_carries_no_orphan_continuation_token() -> None:
    hits = sorted({m.group(0) for m in ORPHAN_CONTINUATION.finditer(_roadmap())})
    assert hits == [], f"orphan continuation token(s) survive: {hits}"


# --------------------------------------------------------------------------- 3


def test_b3_every_cited_source_file_resolves_to_a_tracked_path() -> None:
    tracked = _tracked_paths()
    tokens = _cited_file_tokens(_roadmap())
    resolved = {t for t in tokens if _resolve(t, tracked) is not None}
    unresolved = sorted(tokens - resolved - set(DECLARED_ABSENT))
    assert unresolved == [], (
        f"cited file(s) name no tracked path and are not declared absent: {unresolved}"
    )
    assert len(resolved) >= 25, (
        f"only {len(resolved)} cited file(s) resolved, so this census is near-vacuous"
    )


def test_b3_the_declared_absent_set_is_self_cleaning_in_both_directions() -> None:
    tracked = _tracked_paths()
    document = _roadmap()
    for token, reason in DECLARED_ABSENT.items():
        assert _resolve(token, tracked) is None, (
            f"{token!r} is tracked now -- delete its DECLARED_ABSENT entry"
        )
        assert f"`{token}`" in document or f"{token}`" in document, (
            f"{token!r} is no longer cited -- delete its DECLARED_ABSENT entry"
        )
        assert len(reason.split()) >= 5, f"no reason given for {token!r}: {reason!r}"


def test_b3_a_bare_extension_fragment_is_not_a_file_citation() -> None:
    """``.py`` alone names no file, so it must never enter the resolvable population."""
    assert _cited_file_tokens("a `.py` suffix and a `real/mod.py` path") == {
        "real/mod.py"
    }


# --------------------------------------------------------------------------- 4


def test_b4_the_archive_keeps_its_own_line_anchors() -> None:
    """The archive is a point-in-time record; converting it would falsify it.

    This is also the ban's non-vacuity control on REAL tracked content: the same
    matcher that reports zero on the live index must report many here.
    """
    hits = [m.group(0) for m in BACKTICKED_LINE_LOCATOR.finditer(ARCHIVE.read_text(encoding="utf-8"))]
    assert len(hits) >= 100, (
        f"only {len(hits)} line anchor(s) left in the archive -- the ban's domain leaked "
        "onto a point-in-time record"
    )


def test_b4_the_archive_records_this_iterations_retired_row_exactly_once() -> None:
    bullets = [
        line
        for line in ARCHIVE.read_text(encoding="utf-8").splitlines()
        if line.startswith("- **#247 ")
    ]
    assert len(bullets) == 1, f"expected exactly one #247 archive bullet, got {len(bullets)}"
    assert "iter 244" in bullets[0], f"the archive bullet does not name iter 244: {bullets[0][:160]!r}"


# --------------------------------------------------------------------------- 5


def test_b5_the_ban_fires_on_every_pre_fix_spelling() -> None:
    missed = [s for s in REJECTED_SAMPLES if not BACKTICKED_LINE_LOCATOR.search(s)]
    assert missed == [], f"the ban is fail-open on {missed}"


def test_b5_the_bare_name_ban_fires_on_the_unbackticked_spelling() -> None:
    assert BARE_NAME_LOCATOR.search("README:524-556") is not None
    assert ORPHAN_CONTINUATION.search("`:422`") is not None


# --------------------------------------------------------------------------- 6


def test_b6_every_real_colon_bearing_token_is_accepted_and_still_present() -> None:
    document = _roadmap()
    for sample in ACCEPTED_SAMPLES:
        assert BACKTICKED_LINE_LOCATOR.search(f"`{sample}`") is None, (
            f"the ban is over-broad: it rejects the real token {sample!r}"
        )
        assert sample in document, (
            f"{sample!r} is gone, so it no longer proves the ban is not over-broad"
        )


def test_b6_a_decimal_threshold_is_not_a_line_number() -> None:
    assert BACKTICKED_LINE_LOCATOR.search("`career:4.5`") is None
    assert BACKTICKED_LINE_LOCATOR.search("`421.6 -> ~285 ms`") is None


# --------------------------------------------------------------------------- 7


def test_b7_row_192_drops_the_code_shape_that_never_occurred() -> None:
    document = _roadmap()
    assert "and top is None" not in document, (
        "row #192 still asserts a code shape that occurs ZERO times in the file it cites"
    )
    assert "cli.py:4778" not in document, "the stale self-correction anchor survives"
    row = [line for line in document.splitlines() if line.startswith("| 192 ")]
    assert len(row) == 1, f"expected exactly one row #192, got {len(row)}"
    assert "_cmd_run" in row[0], "row #192 names no symbol anchor"


def test_b7_the_symbol_row_192_cites_actually_occurs_in_the_file_it_names() -> None:
    """Mechanical census only: the count of one token in one tracked file."""
    cli = REPO / "src" / "proactive_loop" / "cli.py"
    if not cli.exists():
        pytest.skip("cli.py is absent from this checkout")
    assert cli.read_text(encoding="utf-8").count("_cmd_run") > 0, (
        "row #192 cites `_cmd_run`, which does not occur in cli.py -- a symbol anchor "
        "is only better than a line number if it resolves"
    )


# --------------------------------------------------------------------------- 8


def test_b8_the_live_index_table_stays_well_formed() -> None:
    lines = _roadmap().splitlines()
    pipes = [i for i, line in enumerate(lines) if line.startswith("|")]
    assert pipes, "the live index has no table"
    inside = range(pipes[0], pipes[-1] + 1)
    stray = [(i, lines[i][:60]) for i in inside if not lines[i].startswith("|")]
    assert stray == [], f"non-table line(s) inside the table span: {stray}"
    unterminated = [(i, lines[i][-40:]) for i in inside if not lines[i].rstrip().endswith("|")]
    assert unterminated == [], f"unterminated table row(s): {unterminated}"
    header = lines[pipes[0]].count("|")
    short = [(i, lines[i].count("|")) for i in inside if lines[i].count("|") < header]
    assert short == [], (
        f"table row(s) carry fewer cells than the {header - 1}-column header: {short}"
    )
    assert re.match(r"^\|[\s:|-]+\|$", lines[pipes[0] + 1]) is not None, (
        f"the header separator row is malformed: {lines[pipes[0] + 1][:60]!r}"
    )


def test_b8_this_iterations_ledger_record_lives_in_exactly_one_document() -> None:
    record = "- #247 "
    homes = [
        path.name
        for path in (ROADMAP, ARCHIVE)
        if any(line.startswith(record) for line in path.read_text(encoding="utf-8").splitlines())
    ]
    assert homes == ["ROADMAP.md"], (
        f"the {record.strip()!r} Done-ledger record must live in exactly one document, found {homes}"
    )
