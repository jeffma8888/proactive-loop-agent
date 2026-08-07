"""Behavior tests for state-dir iteration 106 (ships as commit-seq ``factory iter 113``).

Feature under test: the README documents the L1 ACT sandbox's REAL action
surface. A ``### ACT sandbox tool allowlist`` subsection carries one table row
per allowlisted tool, and a BIDIRECTIONAL drift guard binds that table to
``proactive_loop.cli._TOOL_CATALOG`` by NAME and by ACCESS CLASS -- so neither a
new tool, a removed tool, nor a re-classified one can leave the README behind.

Why this file is the oracle
---------------------------
Before this iteration the README described the ACT surface in English words
only: 11 tools in prose against 14 shipped, with 12 of the 14 real names absent
from the file and no document anywhere in the repo disclosing that
``replace_in_file`` mutates an existing file IN PLACE -- under a headline
"safety by construction" claim. Prose cannot be drift-guarded; a table bound to
the catalog can. Every derivation here (section reader, table reader, name and
access comparisons) is written from the spec's Expected Behaviors, not from the
shipped implementation.

Fail-closed by design (behavior 10): the section reader and the table reader
both RAISE when the heading, the header row, or the table itself is missing, so
a future deletion of the section turns the suite RED instead of passing
vacuously over zero rows. Both directions are proven -- the readers accept a
well-formed synthetic table and reject four malformed ones -- and each
comparison helper is fired on a known-bad sample, because a tripwire that
cannot be made to fire is indistinguishable from a broken one.

Isolation: black-box. The only seams used are the on-disk ``README.md`` and the
importable ``proactive_loop.cli._TOOL_CATALOG`` (a module-level literal, so the
import performs no I/O). No ``src/`` module was read while writing this file.

Offline: one file read plus one package import. No network, no subprocess.

Table rows are split on the pipe in PYTHON, never with a regex/grep whose
metacharacter IS the pipe: in the dev shell ``grep '^|' README.md`` is ripgrep
alternation and reports EVERY line as a table row (293 of 293), a fail-open
count that looks exactly like data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.cli import _TOOL_CATALOG

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"

# The marker comment is spelled with an em dash, so match the ASCII-safe prefix.
MARKER = "PORTFOLIO INTRO"
ALLOWLIST_HEADING = "### ACT sandbox tool allowlist"
LAYERS_HEADING = "## The three layers"
QUICKSTART_HEADING = "## Quickstart"

EXPECTED_HEADER = ["tool", "access", "effect"]
# The CLOSED access vocabulary the catalog draws from (spec behavior 5).
ACCESS_VOCABULARY = frozenset({"read-only", "create-update", "move", "delete"})
# An ``effect`` cell shorter than this is a placeholder, not a description.
MIN_EFFECT_CHARS = 10


# --------------------------------------------------------------------------
# Independent derivations (spec definitions, not the shipped implementation)
# --------------------------------------------------------------------------


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def catalog() -> dict[str, tuple[str, str]]:
    """The source of truth: ``name -> (access class, description)``."""
    return dict(_TOOL_CATALOG)


def access_of(name: str) -> str:
    return catalog()[name][0]


def section(
    text: str, heading: str, stops: tuple[str, ...] = ("## ", "### ")
) -> str:
    """``heading`` up to (not including) the next line starting with a ``stops`` prefix.

    Fails loudly instead of returning ``""`` when the heading is missing or
    duplicated: a silently-empty section makes every guard below pass over zero
    rows, which is worse than no guard at all.
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\n") == heading]
    assert len(starts) == 1, (
        f"expected exactly one {heading!r} heading in the document, found "
        f"{len(starts)}; the allowlist guards would have no section to check"
    )
    start = starts[0]
    end = next(
        (
            j
            for j in range(start + 1, len(lines))
            if lines[j].startswith(stops)
        ),
        len(lines),
    )
    return "".join(lines[start:end])


def split_row(line: str) -> list[str]:
    """Split ONE Markdown table line into its stripped cells, on the pipe, in Python."""
    stripped = line.strip()
    assert stripped.startswith("|") and stripped.endswith("|"), (
        f"not a well-formed table row (must open and close with a pipe): {line!r}"
    )
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def table_block(section_text: str) -> list[str]:
    """The section's single run of consecutive table lines, or raise."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in section_text.splitlines():
        if line.strip().startswith("|"):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    assert len(blocks) == 1, (
        f"expected exactly one Markdown table in the section, found {len(blocks)}; "
        "the allowlist must be ONE table so every cell reference is unambiguous"
    )
    return blocks[0]


def read_table(section_text: str) -> list[list[str]]:
    """DATA rows of the section's table, or raise (never an empty list).

    Rejects: no table, several tables, a missing/renamed header row, a missing
    separator row, and a table with a header but no data.
    """
    block = table_block(section_text)
    assert len(block) >= 3, (
        "a table needs a header row, a separator row and at least one data row; "
        f"found {len(block)} table line(s)"
    )
    header = split_row(block[0])
    assert header == EXPECTED_HEADER, (
        f"table header row is {header}, expected exactly {EXPECTED_HEADER}"
    )
    separator = split_row(block[1])
    assert len(separator) == len(EXPECTED_HEADER) and all(
        cell and set(cell) <= set("-:") for cell in separator
    ), f"expected a Markdown separator row under the header, got {separator}"
    rows = [split_row(line) for line in block[2:]]
    assert rows, "the allowlist table has a header but no data rows"
    return rows


def row_names(rows: list[list[str]]) -> list[str]:
    """Tool names down the table, backticks stripped, in file order."""
    return [row[0].strip().strip("`") for row in rows]


def name_gaps(
    rows: list[list[str]], cat: dict[str, tuple[str, str]]
) -> tuple[list[str], list[str]]:
    """(catalog tools missing from the table, table rows with no catalog tool)."""
    names = set(row_names(rows))
    return sorted(set(cat) - names), sorted(names - set(cat))


def access_mismatches(
    rows: list[list[str]], cat: dict[str, tuple[str, str]]
) -> list[str]:
    """Sorted ``name: documented != real`` reports for every wrong access cell."""
    bad = []
    for row in rows:
        name = row[0].strip().strip("`")
        documented = row[1].strip().strip("`").strip()
        real = cat.get(name, ("<not in catalog>", ""))[0]
        if documented != real:
            bad.append(f"{name}: documented {documented!r} != catalog {real!r}")
    return sorted(bad)


def synthetic_section(rows: str) -> str:
    """A minimal, well-formed allowlist section wrapping ``rows``."""
    return (
        f"{ALLOWLIST_HEADING}\n\nlead-in prose.\n\n"
        "| tool | access | effect |\n"
        "|------|--------|--------|\n"
        f"{rows}"
        "\n## Quickstart\n"
    )


# --------------------------------------------------------------------------
# Sanity: the guard must not be vacuous
# --------------------------------------------------------------------------


def test_the_derived_surface_is_non_trivial() -> None:
    """A guard over an empty catalog or an empty section passes for the wrong reason."""
    cat = catalog()
    assert len(cat) >= 14, f"suspiciously small tool catalog: {sorted(cat)}"
    classes = {access for access, _desc in cat.values()}
    assert classes <= ACCESS_VOCABULARY, f"unknown access class(es): {classes}"
    assert len(classes) >= 2, "an access column over one class documents nothing"
    assert len(section(readme_text(), ALLOWLIST_HEADING)) > 500, (
        "the allowlist section is too small to be the real reference"
    )


# --------------------------------------------------------------------------
# Behavior 1 -- one allowlist heading, below the marker, above Quickstart
# --------------------------------------------------------------------------


def test_behavior1_one_allowlist_heading_below_marker_inside_the_layers_section() -> None:
    text = readme_text()
    lines = [line.rstrip("\n") for line in text.splitlines()]
    heads = [i for i, line in enumerate(lines) if line == ALLOWLIST_HEADING]
    markers = [i for i, line in enumerate(lines) if MARKER in line]
    layers = [i for i, line in enumerate(lines) if line == LAYERS_HEADING]
    quickstarts = [i for i, line in enumerate(lines) if line == QUICKSTART_HEADING]
    assert len(heads) == 1, (
        f"expected exactly one {ALLOWLIST_HEADING!r} line, found {len(heads)}"
    )
    assert len(markers) == 1 and len(layers) == 1 and len(quickstarts) == 1, (
        f"README landmarks are not unique: marker={markers}, layers={layers}, "
        f"quickstart={quickstarts}"
    )
    assert markers[0] < heads[0] < quickstarts[0], (
        "the allowlist subsection must sit BELOW the human-owned PORTFOLIO INTRO "
        f"marker (line {markers[0]}) and ABOVE {QUICKSTART_HEADING!r} (line "
        f"{quickstarts[0]}); it is at line {heads[0]}"
    )
    assert layers[0] < heads[0], (
        f"the allowlist subsection must live inside {LAYERS_HEADING!r}"
    )
    assert ALLOWLIST_HEADING in section(text, LAYERS_HEADING, stops=("## ",))


# --------------------------------------------------------------------------
# Behavior 2 -- exactly one table, header cells tool | access | effect
# --------------------------------------------------------------------------


def test_behavior2_section_holds_one_table_with_the_documented_header() -> None:
    sec = section(readme_text(), ALLOWLIST_HEADING)
    header = split_row(table_block(sec)[0])
    assert header == EXPECTED_HEADER, (
        f"the allowlist table header is {header}; the guards reference cells by "
        f"position, so it must be exactly {EXPECTED_HEADER}"
    )
    read_table(sec)  # also validates the separator row and non-empty body


# --------------------------------------------------------------------------
# Behavior 3 -- one row per catalog tool: no missing tool, no ghost, no dupe
# --------------------------------------------------------------------------


def test_behavior3_rows_cover_the_catalog_exactly() -> None:
    cat = catalog()
    rows = read_table(section(readme_text(), ALLOWLIST_HEADING))
    assert len(rows) == len(cat), (
        f"the allowlist table has {len(rows)} data rows but the catalog ships "
        f"{len(cat)} tools"
    )
    names = row_names(rows)
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"tool documented twice in the allowlist table: {dupes}"
    missing, ghosts = name_gaps(rows, cat)
    assert not missing and not ghosts, (
        f"allowlist table drift -- tools shipped but UNDOCUMENTED: {missing}; rows "
        f"documenting no live tool: {ghosts}. Fix the table BELOW the marker."
    )


def test_behavior3_the_name_guard_fires_on_a_dropped_and_on_a_ghost_row() -> None:
    """The forward and reverse halves must each be provable on a known-bad sample."""
    cat = catalog()
    rows = read_table(section(readme_text(), ALLOWLIST_HEADING))
    for dropped in sorted(cat):
        pruned = [r for r in rows if r[0].strip().strip("`") != dropped]
        assert name_gaps(pruned, cat) == ([dropped], []), (
            f"the name guard failed to isolate a dropped {dropped} row"
        )
    ghost_row = ["`no_such_tool`", "`delete`", "Does something imaginary."]
    assert name_gaps([*rows, ghost_row], cat) == ([], ["no_such_tool"])


def test_behavior3_the_three_previously_undocumented_tools_are_named() -> None:
    """The concrete defect: diff_files / read_lines / replace_in_file were absent."""
    sec = section(readme_text(), ALLOWLIST_HEADING)
    for name in ("diff_files", "read_lines", "replace_in_file"):
        assert name in catalog(), f"{name} is no longer an allowlisted tool"
        assert f"`{name}`" in sec, (
            f"{name} ships in the ACT allowlist but is named nowhere in the README "
            "allowlist section"
        )


# --------------------------------------------------------------------------
# Behavior 4 -- backticked names, in name-ascending order (== `pla tools`)
# --------------------------------------------------------------------------


def test_behavior4_names_are_backticked_and_sorted() -> None:
    rows = read_table(section(readme_text(), ALLOWLIST_HEADING))
    for row in rows:
        cell = row[0].strip()
        assert cell.startswith("`") and cell.endswith("`") and len(cell) > 2, (
            f"the tool cell must be the name in single backticks, got {cell!r}"
        )
        assert "`" not in cell[1:-1], f"nested backticks in the tool cell: {cell!r}"
    assert row_names(rows) == sorted(catalog()), (
        "the table must run name-ascending, the same order `pla tools` renders, so "
        f"a reader can compare the two by eye; got {row_names(rows)}"
    )


# --------------------------------------------------------------------------
# Behavior 5 -- the access cell equals the catalog's class VERBATIM
# --------------------------------------------------------------------------


def test_behavior5_access_cells_match_the_catalog_verbatim() -> None:
    cat = catalog()
    rows = read_table(section(readme_text(), ALLOWLIST_HEADING))
    assert access_mismatches(rows, cat) == [], (
        f"allowlist access-class drift: {access_mismatches(rows, cat)}"
    )
    for row in rows:
        documented = row[1].strip().strip("`").strip()
        assert documented in ACCESS_VOCABULARY, (
            f"{documented!r} is outside the closed access vocabulary "
            f"{sorted(ACCESS_VOCABULARY)}"
        )


def test_behavior5_the_access_guard_fires_on_a_reclassified_tool() -> None:
    cat = catalog()
    rows = read_table(section(readme_text(), ALLOWLIST_HEADING))
    for i, row in enumerate(rows):
        name = row[0].strip().strip("`")
        wrong = "`delete`" if access_of(name) != "delete" else "`read-only`"
        mutated = [list(r) for r in rows]
        mutated[i][1] = wrong
        reports = access_mismatches(mutated, cat)
        assert len(reports) == 1 and reports[0].startswith(f"{name}: "), (
            f"the access guard failed to isolate a re-classified {name} row: {reports}"
        )


# --------------------------------------------------------------------------
# Behavior 6 -- three cells per row, non-empty single-line effect
# --------------------------------------------------------------------------


def test_behavior6_rows_are_three_well_formed_single_line_cells() -> None:
    sec = section(readme_text(), ALLOWLIST_HEADING)
    block = table_block(sec)
    cat = catalog()
    assert len(block) == 2 + len(cat), (
        f"expected {2 + len(cat)} table lines (header + separator + one per tool), "
        f"found {len(block)}; a cell wrapped onto a second line would break the "
        "three-cell split every guard here relies on"
    )
    for line in block:
        assert "\n" not in line
        stripped = line.strip()
        assert stripped.startswith("|") and stripped.endswith("|"), (
            f"table line does not open and close with a pipe: {line!r}"
        )
    for row in read_table(sec):
        assert len(row) == 3, f"row splits into {len(row)} cells, expected 3: {row}"
        effect = row[2]
        assert len(effect.replace(" ", "")) >= MIN_EFFECT_CHARS, (
            f"the effect cell for {row[0]} is a placeholder, not a description: "
            f"{effect!r}"
        )


# --------------------------------------------------------------------------
# Behavior 7 -- the in-place mutator is disclosed
# --------------------------------------------------------------------------


def test_behavior7_replace_in_file_row_discloses_the_in_place_edit() -> None:
    rows = read_table(section(readme_text(), ALLOWLIST_HEADING))
    effects = {row[0].strip().strip("`"): row[2] for row in rows}
    assert "replace_in_file" in effects, "no `replace_in_file` row to inspect"
    assert "in place" in effects["replace_in_file"], (
        "the only in-place mutator in the ACT allowlist must SAY it edits an "
        "existing file in place -- omitting that under a 'safety by construction' "
        f"headline is the defect this row exists to fix; got {effects['replace_in_file']!r}"
    )


# --------------------------------------------------------------------------
# Behavior 8 -- no access class can vanish from the reader's view
# --------------------------------------------------------------------------


def test_behavior8_every_access_class_appears_in_the_section_text() -> None:
    sec = section(readme_text(), ALLOWLIST_HEADING)
    for access in sorted({a for a, _desc in catalog().values()}):
        assert access in sec, (
            f"the access class {access!r} exists in the catalog but appears nowhere "
            "in the README allowlist section"
        )


# --------------------------------------------------------------------------
# Behavior 9 -- the L1 prose states the REAL tool count
# --------------------------------------------------------------------------


def test_behavior9_layers_section_claims_the_real_tool_count() -> None:
    text = readme_text()
    claim = f"{len(catalog())} path-guarded tools"
    layers = section(text, LAYERS_HEADING, stops=("## ",))
    assert claim in layers, (
        f"the {LAYERS_HEADING!r} section must state {claim!r}; the previous prose "
        "enumerated 11 of the 14 allowlisted tools in English words"
    )
    assert LAYERS_HEADING in text and QUICKSTART_HEADING in text, (
        "both headings must survive: other iterations' tests pin them"
    )
    assert claim not in text.split(MARKER, 1)[0], (
        "the count claim landed ABOVE the human-owned marker; behavior 9 must be "
        "satisfied by the section below it"
    )
    for stale in ("11 path-guarded tools", "12 path-guarded tools", "13 path-guarded tools"):
        assert stale not in text, f"stale tool count still in the README: {stale!r}"


# --------------------------------------------------------------------------
# Behavior 10 -- the readers FAIL CLOSED (proven both ways, synthetically)
# --------------------------------------------------------------------------


def test_behavior10_readers_accept_a_well_formed_synthetic_section() -> None:
    """The negative cases below mean nothing unless the readers accept a good table."""
    good = synthetic_section("| `write_file` | `create-update` | Create or overwrite one file whole. |\n")
    rows = read_table(section(good, ALLOWLIST_HEADING))
    assert rows == [
        ["`write_file`", "`create-update`", "Create or overwrite one file whole."]
    ]


def test_behavior10_section_reader_fails_when_the_heading_is_absent() -> None:
    without = f"# Title\n\n{LAYERS_HEADING}\n\nno allowlist here\n\n{QUICKSTART_HEADING}\n"
    with pytest.raises(AssertionError, match="exactly one"):
        section(without, ALLOWLIST_HEADING)


def test_behavior10_section_reader_rejects_a_duplicated_heading() -> None:
    doubled = f"{ALLOWLIST_HEADING}\na\n\n{ALLOWLIST_HEADING}\nb\n"
    with pytest.raises(AssertionError, match="exactly one"):
        section(doubled, ALLOWLIST_HEADING)


def test_behavior10_table_reader_fails_when_the_header_row_is_absent() -> None:
    """Beheading the REAL table must raise, not silently yield rows or ``[]``."""
    sec = section(readme_text(), ALLOWLIST_HEADING)
    header_line = table_block(sec)[0]
    beheaded = sec.replace(header_line + "\n", "", 1)
    assert header_line not in beheaded
    with pytest.raises(AssertionError, match="header row"):
        read_table(beheaded)


def test_behavior10_table_reader_fails_on_a_missing_or_split_table() -> None:
    no_table = f"{ALLOWLIST_HEADING}\n\njust prose, no table at all.\n\n{QUICKSTART_HEADING}\n"
    with pytest.raises(AssertionError, match="exactly one Markdown table"):
        read_table(section(no_table, ALLOWLIST_HEADING))

    two_tables = synthetic_section(
        "| `write_file` | `create-update` | Create or overwrite one file whole. |\n"
    ).replace(
        "\n## Quickstart\n",
        "\nprose between tables\n\n| tool | access | effect |\n|---|---|---|\n"
        "| `read_file` | `read-only` | Read one file whole. |\n\n## Quickstart\n",
    )
    with pytest.raises(AssertionError, match="exactly one Markdown table"):
        read_table(section(two_tables, ALLOWLIST_HEADING))

    header_only = synthetic_section("")
    with pytest.raises(AssertionError, match="at least one data row|header but no data"):
        read_table(section(header_only, ALLOWLIST_HEADING))


def test_behavior10_row_splitter_rejects_a_line_that_is_not_a_row() -> None:
    with pytest.raises(AssertionError, match="pipe"):
        split_row("this is prose, not a table row")
