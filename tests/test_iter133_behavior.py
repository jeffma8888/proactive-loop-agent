"""Behavior tests for foundry state iter-126 (ships as commit-seq ``factory iter 133``).

Feature under test: a fence-aware, per-table-grouped **Markdown-table integrity
guard** armed over every ``*.md`` in the repo root -- three defect classes
(``blank_in_table``, ``column_count``, ``absorbed_paragraph``) -- plus the defect
it was built to detect, paid off in ``ROADMAP_ARCHIVE.md``.

Why this file is the oracle
``ROADMAP.md`` is rewritten by an automated PM role on EVERY iteration of a
PUBLIC portfolio repo, and the only thing that has so far stood between a GFM
rendering defect and publication is a human eye at the final gate (iter-125
caught this exact class by hand, one commit before publication). That is luck,
not a control. ``ROADMAP_ARCHIVE.md`` is what luck running out looks like: a
blank line terminated its first table early, so 73 of its 98 archived rows were
publishing as literal ``| 27 | **GitStateCollector** ... |`` pipe text.

Why the guard is spec'd as THREE classes, not one
The pre-existing guard
(``test_iter115_behavior.py::test_b8_roadmap_table_has_no_internal_blank_line``)
sees only the blank-line class. The blank lines and the stray content pipes in
the archive are COUPLED: deleting the blanks re-joins 73 rows into the table, at
which point 8 of them are seen to carry extra unescaped pipes, and GFM SILENTLY
DISCARDS cells past the header count -- the discarded slot holds the whole
``Status`` text. So a blank-line-only fix trades a LOUD public defect for a
SILENT one that neither a diff nor any existing test can see. The
``absorbed_paragraph`` class is the opposite-polarity trap: an over-eager
blank-line deleter would swallow the blank line that legitimately separates a
table from a following paragraph.

Why both a positive AND a negative control are mandatory here
A naive version of this detector (compare each row against the LAST delimiter
row seen anywhere in the file, count pipes inside fenced code blocks) reports
FOUR false findings in ``README.md``. A guard that manufactures a red build on
the public README is worse than no guard, and a guard that discovers no files
passes vacuously. Behaviors 2 and 3 therefore fire the detector on a known-BAD
sample and on a known-GOOD sample written into ``tmp_path``, and behavior 4
carries anti-vacuous assertions (non-empty file set, all 5 tracked root docs
present, >= 10 tables actually parsed).

Why the audited set comes from git and not from a glob (iter-156, row #155)
Globbing the repo root for Markdown audits the WORKING DIRECTORY: measured at
that iteration, 7 root ``*.md`` files sat on disk while git tracked 5, the two
extras hidden only by ``.git/info/exclude`` -- a per-clone, UNCOMMITTED
mechanism. So the public suite was auditing two files that no other clone, no
CI checkout and no reviewer has, and a table inside either one would red the
build on exactly one machine. The floor was one-sided too: it named 3 files, so
tracked public ``SPEC.md`` and ``DIRECTIONS.md`` could leave the audited set
entirely and the guard would still pass green. The domain is therefore git's
tracked ROOT set, asserted EQUAL to a pinned tuple, so drift in either
direction has to be announced in the commit that causes it.

Isolation: black-box. This module reads the tracked root Markdown files (the
artifacts under test), its own synthetic samples in ``tmp_path``, and the TEXT
of a sibling test module for behavior 8 (a test-suite contract, explicitly in
scope: ``tests/`` is readable by the tester role). No implementation source was
read while writing this file, and no engineer, reviewer or fix note was opened.

Offline and deterministic: pure text parsing, no imports from the product, no
network, no clock, no writes outside ``tmp_path``. ONE subprocess, and only to
name the domain: a read-only ``git ls-files "*.md"``, which skips with a stated
reason where there is no index (a tarball export) instead of auditing nothing.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
ROADMAP = REPO_ROOT / "ROADMAP.md"
ARCHIVE = REPO_ROOT / "ROADMAP_ARCHIVE.md"
SIBLING_GUARD = Path(__file__).resolve().parent / "test_iter115_behavior.py"

#: The three -- and only three -- defect classes the guard reports.
CLASSES = ("blank_in_table", "column_count", "absorbed_paragraph")

#: Closed vocabulary of the archive tables' ``Value`` column (cell index 3).
VALUE_VOCAB = frozenset({"High", "Med-High", "Med", "Low-Med", "Low"})

#: Rows whose stray content pipes were escaped; each must KEEP its Status text.
REPAIRED_ROWS = ("27", "37", "49", "51", "52", "58", "60", "71")

#: The ROOT-level Markdown docs this repo TRACKS, i.e. the ones every clone and
#: every CI checkout actually has. Behavior 4 asserts SET EQUALITY against git's
#: own listing, so adding or retiring a public root doc reds the build until it
#: is announced by editing this tuple in the same commit -- the drift discipline
#: the suite already applies to the CI gate steps and the armed baseline kinds.
TRACKED_ROOT_DOCS = (
    "DIRECTIONS.md",
    "README.md",
    "ROADMAP.md",
    "ROADMAP_ARCHIVE.md",
    "SPEC.md",
)

_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_DELIM_CELL_RE = re.compile(r"^:?-+:?$")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")


# ==========================================================================
# The auditor under test (behavior 1). Pure, offline, fence-aware, per-table.
# ==========================================================================


@dataclass(frozen=True)
class Finding:
    """One Markdown-table defect: its class, its 1-based line, and why."""

    kind: str
    line: int
    detail: str


@dataclass(frozen=True)
class Table:
    """One GFM table: header line/cells, body rows, and what ended the body."""

    header_line: int
    header_cells: tuple[str, ...]
    body: tuple[tuple[int, tuple[str, ...]], ...]
    terminator_line: int | None


def fence_flags(lines: list[str]) -> list[bool]:
    """``True`` for every line inside (or delimiting) a fenced code block."""
    flags: list[bool] = []
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            flags.append(True)
            in_fence = not in_fence
        else:
            flags.append(in_fence)
    return flags


def split_cells(row: str) -> tuple[str, ...]:
    """Cells of a pipe row, split on UNESCAPED pipes only.

    Strips exactly one leading and one trailing table pipe, so ``| a | b |``
    is two cells, and a cell holding an escaped ``\\|`` stays one cell.
    """
    text = row.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    return tuple(cell.strip() for cell in _UNESCAPED_PIPE_RE.split(text))


def _is_pipe_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_delimiter_row(line: str) -> bool:
    if not _is_pipe_line(line):
        return False
    cells = split_cells(line)
    return bool(cells) and all(_DELIM_CELL_RE.fullmatch(c) for c in cells)


def find_tables(text: str) -> list[Table]:
    """Every GFM table in ``text``, grouped by its OWN delimiter row."""
    lines = text.splitlines()
    flags = fence_flags(lines)
    tables: list[Table] = []
    index = 1
    while index < len(lines):
        if flags[index] or flags[index - 1]:
            index += 1
            continue
        if not _is_delimiter_row(lines[index]) or not _is_pipe_line(lines[index - 1]):
            index += 1
            continue
        if _is_delimiter_row(lines[index - 1]):
            index += 1
            continue
        header_cells = split_cells(lines[index - 1])
        body: list[tuple[int, tuple[str, ...]]] = []
        cursor = index + 1
        while cursor < len(lines):
            line = lines[cursor]
            if flags[cursor] or not line.strip() or not _is_pipe_line(line):
                break
            body.append((cursor + 1, split_cells(line)))
            cursor += 1
        tables.append(
            Table(
                header_line=index,
                header_cells=header_cells,
                body=tuple(body),
                terminator_line=cursor + 1 if cursor < len(lines) else None,
            )
        )
        index = cursor + 1
    return tables


def audit_markdown(text: str) -> list[Finding]:
    """Findings for the three table-integrity defect classes, line-sorted."""
    lines = text.splitlines()
    flags = fence_flags(lines)
    findings: list[Finding] = []

    for position, line in enumerate(lines):
        if line.strip() or flags[position]:
            continue
        before = next(
            (i for i in range(position - 1, -1, -1) if lines[i].strip()), None
        )
        after = next(
            (i for i in range(position + 1, len(lines)) if lines[i].strip()), None
        )
        if before is None or after is None or flags[before] or flags[after]:
            continue
        if _is_pipe_line(lines[before]) and _is_pipe_line(lines[after]):
            findings.append(
                Finding(
                    "blank_in_table",
                    position + 1,
                    "blank line between two table rows terminates the table early",
                )
            )

    for table in find_tables(text):
        width = len(table.header_cells)
        for line_no, cells in table.body:
            if len(cells) != width:
                findings.append(
                    Finding(
                        "column_count",
                        line_no,
                        f"{len(cells)} cells against a {width}-column header "
                        f"(header at line {table.header_line - 1})",
                    )
                )
        if table.terminator_line is not None:
            term = lines[table.terminator_line - 1]
            if (
                term.strip()
                and not flags[table.terminator_line - 1]
                and not _is_pipe_line(term)
            ):
                findings.append(
                    Finding(
                        "absorbed_paragraph",
                        table.terminator_line,
                        "paragraph directly after a table row is absorbed by it",
                    )
                )

    return sorted(findings, key=lambda f: (f.line, f.kind))


def read(path: Path) -> str:
    """Text of ``path``, failing loudly rather than auditing an empty string."""
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"{path.name} must not be empty (a vacuous audit is no audit)"
    return text


def archive_rows() -> list[tuple[int, tuple[str, ...]]]:
    """Every body row of both ``ROADMAP_ARCHIVE.md`` tables."""
    return [row for table in find_tables(read(ARCHIVE)) for row in table.body]


# ==========================================================================
# Behavior 1 --- the auditor's shape: three classes, 1-based lines, pure.
# ==========================================================================


def test_b1_auditor_reports_only_the_three_spec_classes_with_line_numbers() -> None:
    sample = "\n".join(
        [
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 | 3 |",
            "trailing paragraph",
        ]
    )

    findings = audit_markdown(sample)

    assert findings, "the auditor must report the two planted defects"
    assert {f.kind for f in findings} <= set(CLASSES), (
        "every finding must be tagged with one of exactly three class names "
        f"{CLASSES}; got {sorted({f.kind for f in findings})}"
    )
    assert all(isinstance(f.line, int) and f.line >= 1 for f in findings), (
        f"line numbers must be 1-based ints; got {[f.line for f in findings]}"
    )
    assert [(f.kind, f.line) for f in findings] == [
        ("column_count", 3),
        ("absorbed_paragraph", 4),
    ], f"unexpected findings: {findings}"
    assert audit_markdown(sample) == findings, "the auditor must be pure/deterministic"


def test_b1_cells_split_on_unescaped_pipes_only() -> None:
    assert split_cells("| a | b |") == ("a", "b")
    assert split_cells("| a \\| b | c |") == ("a \\| b", "c"), (
        "an escaped pipe is CONTENT, not a cell boundary"
    )
    assert split_cells("|x|") == ("x",)


def test_b1_fenced_lines_are_never_table_lines() -> None:
    sample = "\n".join(
        [
            "```",
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 | 3 |",
            "```",
        ]
    )

    assert find_tables(sample) == [], "a fenced block must not parse as a table"
    assert audit_markdown(sample) == [], f"fenced pipes must not fire: {audit_markdown(sample)}"


# ==========================================================================
# Behavior 2 --- known-BAD positive control: the detector must fire.
# ==========================================================================


BAD_SAMPLE_LINES = [
    "# Known-bad sample",  # 1
    "",  # 2
    "| A | B |",  # 3  header, 2 columns
    "| --- | --- |",  # 4  delimiter
    "| 1 | 2 |",  # 5  clean body row
    "| 1 | 2 | 3 |",  # 6  DEFECT: column_count (3 vs 2)
    "",  # 7  DEFECT: blank_in_table
    "| 5 | 6 |",  # 8  orphaned by the blank above
    "",  # 9  legitimate separator (next line is a fence)
    "```",  # 10
    "| not | a | table |",  # 11 fenced pipes -> ignored
    "| --- | --- | --- |",  # 12 fenced delimiter -> ignored
    "```",  # 13
    "",  # 14
    "| C | D | E |",  # 15 header, 3 columns (DIFFERENT width, legal)
    "| --- | --- | --- |",  # 16
    "| x | y | z |",  # 17 clean body row
    "absorbed paragraph",  # 18 DEFECT: absorbed_paragraph
]


def test_b2_known_bad_sample_yields_exactly_one_finding_per_class(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "bad.md"
    sample.write_text("\n".join(BAD_SAMPLE_LINES) + "\n", encoding="utf-8")

    findings = audit_markdown(sample.read_text(encoding="utf-8"))

    assert [(f.kind, f.line) for f in findings] == [
        ("column_count", 6),
        ("blank_in_table", 7),
        ("absorbed_paragraph", 18),
    ], f"positive control must fire once per class at 6/7/18; got {findings}"
    assert sorted(f.kind for f in findings) == sorted(CLASSES), (
        "exactly one finding of each of the three classes"
    )
    assert not [f for f in findings if 10 <= f.line <= 13], (
        "the fenced code block must produce no findings"
    )
    assert not [f for f in findings if f.line in (15, 16, 17)], (
        "the second table's DIFFERENT width is legal: width is compared to its "
        f"OWN header, never a previous table's. Got {findings}"
    )


# ==========================================================================
# Behavior 3 --- known-GOOD negative control: no false positives.
# ==========================================================================


GOOD_SAMPLE_LINES = [
    "# Known-good sample",
    "",
    "| A | B |",
    "| --- | --- |",
    "| 1 | 2 |",
    "| a \\| b | 2 |",
    "",
    "A paragraph correctly separated from the table above.",
    "",
    "```text",
    "| pipes | inside | a | fence |",
    "| --- | --- | --- | --- |",
    "| 1 | 2 | 3 | 4 |",
    "```",
    "",
    "| C | D | E |",
    "| :-- | :-: | --: |",
    "| x | y | z |",
    "",
    "Done.",
]


def test_b3_known_good_sample_yields_zero_findings(tmp_path: Path) -> None:
    sample = tmp_path / "good.md"
    sample.write_text("\n".join(GOOD_SAMPLE_LINES) + "\n", encoding="utf-8")

    text = sample.read_text(encoding="utf-8")
    findings = audit_markdown(text)

    assert findings == [], (
        "negative control must be silent: two tables of DIFFERENT widths, an "
        f"escaped pipe, a fenced pipe block, a legal separator. Got {findings}"
    )
    tables = find_tables(text)
    assert len(tables) == 2, f"the good sample holds 2 tables; parsed {len(tables)}"
    assert [len(t.header_cells) for t in tables] == [2, 3]
    assert tables[0].body[1][1] == ("a \\| b", "2"), (
        f"escaped pipe must stay in one cell; got {tables[0].body[1][1]}"
    )


# ==========================================================================
# The audited DOMAIN (behavior 4). Keyed on git's TRACKED set, never on a
# working-directory glob: a glob audits whatever scratch files happen to sit in
# ONE clone, so a table defect in an untracked file reds `uv run pytest` on one
# machine and is unreproducible on every other -- and the reverse hole is worse,
# because a tracked public doc could leave the audited set with nothing said.
# ==========================================================================


def root_markdown_names(listing: str | Iterable[str]) -> list[str]:
    """ROOT-level names of a ``git ls-files "*.md"`` listing, sorted.

    Pure over the LISTING rather than over the repo, because that is the only
    way BOTH sides of the domain rule are provable. git's pathspec ``*`` also
    matches ``/``, so the real listing carries nested fixture documents whose
    content is deliberately arbitrary; and a fresh clone has no untracked file
    at all, so the "an untracked file is never audited" side cannot be shown
    against the ambient tree. A synthetic listing makes both deterministic.

    Blank and whitespace-only lines are dropped. Names are de-duplicated because
    ``ls-files`` prints one line per index stage, so an unmerged path appears up
    to three times and would otherwise be audited three times.
    """
    lines = listing.splitlines() if isinstance(listing, str) else list(listing)
    return sorted({name for line in lines if (name := line.strip()) and "/" not in name})


def tracked_root_markdown(root: Path = REPO_ROOT) -> list[str]:
    """The tracked root Markdown of ``root``, or skip if git cannot say.

    ``root`` is a parameter for one reason: it makes the degrade path reachable
    from a test without deleting ``.git``. A tarball export has no index, and a
    guard that silently audited NOTHING there would be worse than a skip -- it
    would report health while examining zero files.
    """
    try:
        listed = subprocess.run(
            ["git", "ls-files", "*.md"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except OSError as exc:  # no git binary at all
        pytest.skip(f"git is unavailable ({exc}); the tracked set is unknowable here")
    if listed.returncode != 0:
        pytest.skip(f"{root} is not a git checkout; the tracked set is unknowable here")
    return root_markdown_names(listed.stdout)


# ==========================================================================
# Behavior 4 --- the repo-root guard is green, and cannot pass vacuously.
# ==========================================================================


def test_b4_every_root_markdown_file_is_table_clean() -> None:
    names = tracked_root_markdown()
    pinned = set(TRACKED_ROOT_DOCS)

    # Anti-vacuity FIRST: an empty or unrecognisable listing would make the
    # table assertion below pass for the wrong reason.
    assert names, "git listed no root *.md files -- the guard would pass vacuously"
    for required in TRACKED_ROOT_DOCS:
        assert required in names, f"{required} missing from the audited set {names}"
    assert set(names) == pinned, (
        "the audited set must equal the tracked root Markdown set EXACTLY: a "
        "superset audits a file no other clone has, a subset lets a public doc "
        "leave the guard silently. Announce the change here, in this commit. "
        f"tracked-only={sorted(set(names) - pinned)} "
        f"pinned-only={sorted(pinned - set(names))}"
    )

    report = {name: audit_markdown(read(REPO_ROOT / name)) for name in names}
    offenders = {name: found for name, found in report.items() if found}

    assert offenders == {}, (
        "root Markdown must be table-clean. Findings:\n"
        + "\n".join(
            f"  {name}: " + ", ".join(f"{f.kind}@{f.line} ({f.detail})" for f in found)
            for name, found in offenders.items()
        )
    )


def test_b4_guard_actually_parsed_tables_so_it_cannot_pass_by_finding_nothing() -> None:
    counts = {
        path.name: len(find_tables(read(path)))
        for path in (README, ROADMAP, ARCHIVE)
    }

    assert sum(counts.values()) >= 10, (
        "a broken table detector would find zero tables and pass silently; "
        f"expected >= 10 across README/ROADMAP/ARCHIVE, got {counts}"
    )
    assert all(n >= 1 for n in counts.values()), f"a file parsed as table-less: {counts}"


# ==========================================================================
# Behavior 5 --- the archive has no in-table blank lines (and no over-fix).
# ==========================================================================


def test_b5_archive_has_no_blank_line_inside_a_table() -> None:
    findings = [f for f in audit_markdown(read(ARCHIVE)) if f.kind == "blank_in_table"]

    assert findings == [], (
        "ROADMAP_ARCHIVE.md had 30 in-table blank lines (first at line 57), each "
        "terminating the table early so the rows below published as literal pipe "
        f"text. Still present at lines {[f.line for f in findings]}"
    )


def test_b5_blank_line_deletion_did_not_absorb_a_following_paragraph() -> None:
    findings = [
        f for f in audit_markdown(read(ARCHIVE)) if f.kind == "absorbed_paragraph"
    ]

    assert findings == [], (
        "the opposite-polarity bug: a blank line legitimately separating a table "
        "from a following paragraph must be PRESERVED. Absorbed at "
        f"{[f.line for f in findings]}"
    )


# ==========================================================================
# Behavior 6 --- exact archive table shapes: 2 tables, 98 + 28 rows, 7 cells.
# ==========================================================================


def test_b6_archive_table_shapes_are_exact() -> None:
    tables = find_tables(read(ARCHIVE))

    assert len(tables) == 2, f"ROADMAP_ARCHIVE.md must hold exactly 2 tables; got {len(tables)}"
    assert [len(t.header_cells) for t in tables] == [7, 7], (
        f"both archive headers are 7-column; got {[t.header_cells for t in tables]}"
    )
    assert [len(t.body) for t in tables] == [98, 40], (
        "first archive table body is 98 rows and the second 40 (73 of the first "
        "were publishing as raw pipe text before the fix). The second table grew "
        "28 -> 39 in iter-132, which moved the 11 shipped rows #128/#134/#139/#141/"
        "#145/#147/#148/#150/#152/#153/#154 out of the ROADMAP.md index (37,092 -> "
        "21,892 chars) to keep the PM stage clear of the ~600s cap, then 39 -> 40 in "
        "iter-133, which moved shipped row #157 (`a7be482`) out the same way; got "
        f"{[len(t.body) for t in tables]}"
    )

    wrong = [
        (line_no, len(cells))
        for table in tables
        for line_no, cells in table.body
        if len(cells) != 7
    ]
    assert wrong == [], (
        "every one of the 138 archive rows must split into exactly 7 cells on "
        f"UNESCAPED pipes; offenders (line, cells) = {wrong}"
    )


# ==========================================================================
# Behavior 7 --- alignment is proven, and no text was deleted to get it.
# ==========================================================================


def test_b7_every_archive_row_is_semantically_aligned() -> None:
    rows = archive_rows()

    assert len(rows) == 138, f"expected 138 archive body rows; got {len(rows)}"

    bad_value = [(ln, cells[3]) for ln, cells in rows if cells[3] not in VALUE_VOCAB]
    assert bad_value == [], (
        "cell index 3 must be a Value from the closed vocabulary "
        f"{sorted(VALUE_VOCAB)} -- a pipe escaped in the WRONG place keeps the "
        f"cell COUNT right while shifting every column. Offenders: {bad_value}"
    )

    bad_status = [(ln, cells[6][:40]) for ln, cells in rows if not cells[6].startswith("**")]
    assert bad_status == [], (
        "cell index 6 is the Status text and always opens with bold '**'; "
        f"offenders: {bad_status}"
    )


def test_b7_stray_pipes_were_escaped_not_deleted() -> None:
    text = read(ARCHIVE)

    assert text.count("\\|") >= 12, (
        "the 12 stray content pipes on 8 rows must be ESCAPED as '\\|', not "
        f"removed -- the archive is verbatim history. Found {text.count('\\|')}"
    )

    by_number = {cells[0]: cells for _, cells in archive_rows()}
    missing = [n for n in REPAIRED_ROWS if n not in by_number]
    assert missing == [], (
        f"repaired rows must still exist and still parse; missing {missing}"
    )
    for number in REPAIRED_ROWS:
        cells = by_number[number]
        assert cells[6].startswith("**"), (
            f"row #{number} lost the Status text GFM was discarding: {cells[6][:60]!r}"
        )
        assert len(cells[6]) > 20, (
            f"row #{number} Status text looks truncated: {cells[6]!r}"
        )


# ==========================================================================
# Behavior 8 --- no collateral damage to the pre-existing roadmap guard.
# ==========================================================================


def test_b8_existing_iter115_guard_still_points_at_roadmap_only() -> None:
    source = SIBLING_GUARD.read_text(encoding="utf-8")

    binding = re.search(r'^ROADMAP\s*=\s*\w+\s*/\s*"([^"]+)"', source, re.MULTILINE)
    assert binding is not None, (
        "test_iter115_behavior.py must keep a module-level ROADMAP path constant"
    )
    assert binding.group(1) == "ROADMAP.md", (
        "test_iter115_behavior.py's module-level ROADMAP constant must still bind "
        f"ROADMAP.md; it must not be re-pointed at the archive. Got {binding.group(1)!r}"
    )
    assert "ROADMAP_ARCHIVE" not in source, (
        "the pre-existing guard must not be widened to the archive -- this "
        "module owns the archive and defines its own path constants"
    )
    assert "def roadmap_lines(" in source, (
        "the shared roadmap_lines() helper must survive unchanged"
    )


def test_b8_this_module_defines_its_own_path_constants() -> None:
    assert ARCHIVE.name == "ROADMAP_ARCHIVE.md"
    assert ROADMAP.name == "ROADMAP.md"
    assert ARCHIVE.parent == ROADMAP.parent == REPO_ROOT
    assert ARCHIVE.exists() and ROADMAP.exists() and README.exists()
