"""Black-box behavior tests for iteration 155 (ships as commit-sequence **factory
iter 161**): the README's **L2 perception surface** table --- a drift-guarded
enumeration of the scout's whole perception surface, replacing the hand-written
prose bullet that named only 12 of the 17 collectors and described ``ci_config``
and ``license`` nowhere.

The increment is documentation plus its oracle: the README gains an
``### L2 perception surface`` h3 under ``## The three layers``, ahead of the
existing ``### ACT sandbox tool allowlist`` (whose name+access-class table this
one deliberately mirrors), carrying one row per registry entry with columns
``collector`` / ``kind`` / ``perceives``. The ``kind`` column is the load-bearing
one: name and kind differ for 5 of 17 collectors, and ``kind`` --- not the name
--- is the token ``pla signals --kind`` and ``--fail-on-kind`` accept, so the
table is the only document publishing that mapping. The stale bullet keeps a
one-line pointer at the table by anchor instead of enumerating collectors by
hand (ROADMAP #188).

The guard itself is ``l2_table_failures(text, expected)``: a PURE function over
README **text** plus an expected ``{name: kind}`` mapping, returning a list of
human-readable failure strings. It is proved TWO-SIDED here --- ``[]`` on the
shipped README, and non-empty (naming the offender) on four mutated in-memory
copies: a deleted row, a bogus extra row, an altered ``kind`` cell, and rows
shuffled out of ascending order. Mutations never touch the filesystem, and the
shipped ``README.md`` bytes are asserted byte-identical afterwards.

ISOLATION CONTRACT (honored): every assertion here is written strictly against
THIS iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md`` itself, and the product's own observable output --- and drives ONLY
the documented public surface: the ``pla`` CLI via
``proactive_loop.cli.main(argv)`` (``collectors --json``, captured stdout) and
the public registry accessor ``proactive_loop.collectors.all_collectors()``
(the same import ``tests/test_iter57_helpers.py`` and
``tests/test_iter108_behavior.py`` already use). **No file under ``src/`` was
read, no engineer or reviewer note was consulted, and no ``git diff`` was
inspected** to author these assertions. Every test is fully offline: zero
network, zero API keys, no subprocess, no ``tmp_path`` fixture workspace --- the
whole module is text parsing over one tracked file plus one registry import.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from collections.abc import Mapping
from pathlib import Path

from proactive_loop.collectors import all_collectors
from proactive_loop.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

L2_HEADING = "### L2 perception surface"
ACT_HEADING = "### ACT sandbox tool allowlist"
MARKER = "PORTFOLIO INTRO"
ANCHOR = "l2-perception-surface"
EXPECTED_HEADER = ("collector", "kind", "perceives")

# The two collectors the iteration exists to document: described NOWHERE in the
# README before this change (every prior `license` hit was the MIT badge or the
# licence section). Asserted independently of the registry-equality behavior so
# a registry that lost them could not vacuously satisfy behavior 6.
PREVIOUSLY_UNDESCRIBED = ("ci_config", "license")

# Literals retired from the L2 scout bullet by this iteration.
RETIRED_PROSE = ("dependency manifests", "untested source directories")


# ===========================================================================
# Helpers -- pure text parsing; no I/O beyond reading the tracked README once.
# ===========================================================================
def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and len(s) > 1


def _split_row(line: str) -> tuple[str, ...]:
    """Cells of a Markdown table row, outer pipes dropped, each stripped."""
    s = line.strip()
    return tuple(cell.strip() for cell in s[1:-1].split("|"))


def _unbacktick(cell: str) -> str:
    return cell.strip().strip("`").strip()


def _is_separator_row(cells: tuple[str, ...]) -> bool:
    return all(re.fullmatch(r":?-{2,}:?", c) is not None for c in cells) and bool(cells)


def _heading_lines(text: str) -> list[tuple[int, str]]:
    """(index, stripped) for every ATX heading line of any level."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines()):
        s = line.strip()
        if re.match(r"^#{1,6}\s+\S", s):
            out.append((i, s))
    return out


def _line_index(text: str, needle: str) -> int:
    """0-based index of the first line whose STRIPPED form equals ``needle``."""
    for i, line in enumerate(text.splitlines()):
        if line.strip() == needle:
            return i
    return -1


def _marker_index(text: str) -> int:
    for i, line in enumerate(text.splitlines()):
        if MARKER in line:
            return i
    return -1


def _section_lines(text: str, heading: str) -> list[str]:
    """Lines strictly between ``heading`` and the next heading of ANY level."""
    lines = text.splitlines()
    start = _line_index(text, heading)
    if start < 0:
        return []
    end = len(lines)
    for i, line in enumerate(lines[start + 1 :], start=start + 1):
        if re.match(r"^#{1,6}\s+\S", line.strip()):
            end = i
            break
    return lines[start + 1 : end]


def _tables_in(lines: list[str]) -> list[list[str]]:
    """Contiguous runs of Markdown table rows, in order of appearance."""
    tables: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _is_table_row(line):
            current.append(line)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _l2_table(text: str) -> list[str]:
    """The single Markdown table inside the L2 section (empty list if absent)."""
    tables = _tables_in(_section_lines(text, L2_HEADING))
    return tables[0] if len(tables) == 1 else []


def _data_rows(table: list[str]) -> list[tuple[str, ...]]:
    """Data rows of a table: header dropped, separator dropped."""
    rows = [_split_row(line) for line in table]
    if not rows:
        return []
    body = rows[1:]
    if body and _is_separator_row(body[0]):
        body = body[1:]
    return body


def _github_slug(heading_text: str) -> str:
    """GitHub's heading-anchor slug: lowercase, drop punctuation, spaces -> '-'."""
    s = re.sub(r"^#{1,6}\s+", "", heading_text.strip()).strip()
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    return re.sub(r"\s+", "-", s).strip("-")


def _l2_scout_bullet(text: str) -> str:
    """The '- **L2 scout** ...' bullet, joined, up to the next top-level bullet."""
    lines = text.splitlines()
    start = -1
    for i, line in enumerate(lines):
        if line.lstrip().startswith("- **L2 scout**"):
            start = i
            break
    if start < 0:
        return ""
    collected = [lines[start]]
    for line in lines[start + 1 :]:
        stripped = line.lstrip()
        if stripped.startswith("- ") or not line.strip():
            break
        collected.append(line)
    return " ".join(part.strip() for part in collected)


def _collectors_catalog() -> dict[str, str]:
    """``{name: kind}`` exactly as ``pla collectors --json`` publishes it.

    Driven through the public CLI entry point (captured stdout), so this is the
    SHIPPED catalog a user sees, not an internal structure.
    """
    buf = io.StringIO()
    code: int | None = 0
    try:
        with contextlib.redirect_stdout(buf):
            code = main(["collectors", "--json"])
    except SystemExit as exc:  # a CLI that exits rather than returning
        code = int(exc.code or 0)
    assert code in (0, None), f"`pla collectors --json` exited {code!r}"
    payload = json.loads(buf.getvalue())
    if isinstance(payload, dict):
        candidates = [v for v in payload.values() if isinstance(v, list)]
        assert len(candidates) == 1, f"cannot locate the collector list in {sorted(payload)}"
        entries = candidates[0]
    else:
        entries = payload
    catalog = {str(e["name"]): str(e["kind"]) for e in entries}
    assert catalog, "`pla collectors --json` published no collectors"
    return catalog


# ===========================================================================
# The census under test (behavior 8) -- a PURE function over (text, expected).
# ===========================================================================
def l2_table_failures(text: str, expected: Mapping[str, str]) -> list[str]:
    """Every way the README's L2 table disagrees with ``expected`` {name: kind}.

    Pure: no file is read or written, so it can be fired at a mutated in-memory
    copy. Returns human-readable strings NAMING the offenders; ``[]`` means the
    table and the registry agree by name, by kind, by well-formedness and by
    order.
    """
    failures: list[str] = []

    if _line_index(text, L2_HEADING) < 0:
        return [f"no {L2_HEADING!r} heading found in the document"]

    tables = _tables_in(_section_lines(text, L2_HEADING))
    if len(tables) != 1:
        return [f"expected exactly 1 Markdown table in the L2 section; found {len(tables)}"]

    table = tables[0]
    header = _split_row(table[0])
    if tuple(_unbacktick(c) for c in header) != EXPECTED_HEADER:
        failures.append(f"header cells are {header!r}; expected {EXPECTED_HEADER!r}")

    rows = _data_rows(table)
    if not rows:
        return failures + ["the L2 table has no data rows"]

    widths = {len(r) for r in rows}
    if widths != {3}:
        failures.append(f"every data row must have exactly 3 cells; got widths {sorted(widths)}")

    names = [_unbacktick(r[0]) for r in rows]

    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        failures.append(f"duplicate collector rows: {duplicates}")

    missing = sorted(set(expected) - set(names))
    if missing:
        failures.append(f"collectors in the registry with no table row: {missing}")
    extra = sorted(set(names) - set(expected))
    if extra:
        failures.append(f"table rows naming no registered collector: {extra}")

    if len(rows) != len(expected):
        failures.append(f"expected {len(expected)} data rows; found {len(rows)}")

    for row in rows:
        if len(row) != 3:
            continue
        name = _unbacktick(row[0])
        kind = _unbacktick(row[1])
        want = expected.get(name)
        if want is not None and kind != want:
            failures.append(f"{name}: table kind {kind!r} != catalog kind {want!r}")
        perceives = row[2].strip()
        if not perceives:
            failures.append(f"{name}: the `perceives` cell is empty")
        elif "|" in perceives:
            failures.append(f"{name}: the `perceives` cell contains a pipe: {perceives!r}")
        elif "\n" in perceives:
            failures.append(f"{name}: the `perceives` cell spans more than one line")

    if names != sorted(names):
        failures.append(
            f"data rows are not in ascending collector order: {names} "
            f"(expected {sorted(names)})"
        )

    return failures


# ===========================================================================
# Behavior 1 -- the table exists BELOW the marker, as a sibling of the L1 table.
# ===========================================================================
def test_b1_l2_heading_exists_exactly_once() -> None:
    lines = [ln.strip() for ln in _readme_text().splitlines()]
    assert lines.count(L2_HEADING) == 1, (
        f"README must contain exactly one {L2_HEADING!r} heading; "
        f"found {lines.count(L2_HEADING)}"
    )


def test_b1_l2_heading_sits_below_the_marker_and_above_the_act_table() -> None:
    text = _readme_text()
    marker = _marker_index(text)
    l2 = _line_index(text, L2_HEADING)
    act = _line_index(text, ACT_HEADING)
    assert marker >= 0, f"README must still carry the {MARKER!r} marker"
    assert act >= 0, f"README must still carry the {ACT_HEADING!r} precedent heading"
    assert marker < l2, (
        f"{L2_HEADING!r} (line {l2 + 1}) must sit BELOW the human-owned marker "
        f"(line {marker + 1}); the intro block is not editable by automation"
    )
    assert l2 < act, (
        f"{L2_HEADING!r} (line {l2 + 1}) must precede {ACT_HEADING!r} "
        f"(line {act + 1}), matching the L2 -> L1 -> L0 order of the bullets"
    )


def test_b1_human_owned_intro_contains_no_table_row() -> None:
    text = _readme_text()
    above = text.splitlines()[: _marker_index(text)]
    offenders = [(i + 1, ln) for i, ln in enumerate(above) if _is_table_row(ln)]
    assert offenders == [], (
        "the region ABOVE the human-owned marker must contain no Markdown table "
        f"row, proving this feature did not touch it; found {offenders}"
    )


# ===========================================================================
# Behavior 2 -- exactly one table, with the mandated header.
# ===========================================================================
def test_b2_exactly_one_table_in_the_section() -> None:
    tables = _tables_in(_section_lines(_readme_text(), L2_HEADING))
    assert len(tables) == 1, (
        "between the L2 heading and the next heading of any level there must be "
        f"exactly one Markdown table; found {len(tables)}"
    )


def test_b2_header_cells_are_collector_kind_perceives() -> None:
    table = _l2_table(_readme_text())
    assert table, "the L2 section must contain a Markdown table"
    header = tuple(_unbacktick(c) for c in _split_row(table[0]))
    assert header == EXPECTED_HEADER, f"header is {header!r}; expected {EXPECTED_HEADER!r}"


def test_b2_section_opens_with_framing_prose_before_the_table() -> None:
    """Mirrors the ACT precedent, which frames its table and names its guard."""
    section = _section_lines(_readme_text(), L2_HEADING)
    before = [ln for ln in section[: next(i for i, ln in enumerate(section) if _is_table_row(ln))]]
    prose = " ".join(ln.strip() for ln in before).strip()
    assert len(prose) > 80, (
        "the L2 section must open with a short framing paragraph before its "
        f"table, as {ACT_HEADING!r} does; got {prose!r}"
    )


# ===========================================================================
# Behavior 3 -- the row set EQUALS the registry, in both directions.
# ===========================================================================
def test_b3_row_count_equals_the_registry_size() -> None:
    rows = _data_rows(_l2_table(_readme_text()))
    registry = all_collectors()
    assert len(rows) == len(registry) == 17, (
        f"expected {len(registry)} data rows (== len(all_collectors())); found {len(rows)}"
    )


def test_b3_first_column_set_equals_the_registry_names() -> None:
    rows = _data_rows(_l2_table(_readme_text()))
    names = {_unbacktick(r[0]) for r in rows}
    registry = {c.name for c in all_collectors()}
    assert names == registry, (
        f"registered collectors with no table row: {sorted(registry - names)}; "
        f"table rows naming no registered collector: {sorted(names - registry)}"
    )


# ===========================================================================
# Behavior 4 -- the kind column matches the SHIPPED catalog.
# ===========================================================================
def test_b4_kind_column_matches_pla_collectors_json() -> None:
    catalog = _collectors_catalog()
    rows = _data_rows(_l2_table(_readme_text()))
    mismatches = [
        (_unbacktick(r[0]), _unbacktick(r[1]), catalog.get(_unbacktick(r[0])))
        for r in rows
        if _unbacktick(r[1]) != catalog.get(_unbacktick(r[0]))
    ]
    assert mismatches == [], f"(collector, table kind, catalog kind) mismatches: {mismatches}"


def test_b4_the_five_name_kind_divergences_are_pinned() -> None:
    """Anti-vacuity: the column would be decoration if name always == kind."""
    catalog = _collectors_catalog()
    diverging = {n: k for n, k in catalog.items() if n != k}
    assert len(diverging) == 5, f"expected 5 name != kind collectors; got {diverging}"
    rows = {_unbacktick(r[0]): _unbacktick(r[1]) for r in _data_rows(_l2_table(_readme_text()))}
    for name, kind in diverging.items():
        assert rows.get(name) == kind, (
            f"{name}'s row must publish kind {kind!r} (the token `--kind` accepts), "
            f"not {rows.get(name)!r}"
        )


# ===========================================================================
# Behavior 5 -- cells well-formed, rows ordered.
# ===========================================================================
def test_b5_perceives_cells_are_nonempty_single_line_and_pipe_free() -> None:
    rows = _data_rows(_l2_table(_readme_text()))
    for row in rows:
        name = _unbacktick(row[0])
        assert len(row) == 3, f"{name}: expected 3 cells, got {len(row)}: {row!r}"
        cell = row[2].strip()
        assert cell, f"{name}: the `perceives` cell must not be empty"
        assert "|" not in cell, f"{name}: the `perceives` cell must not contain a pipe"
        assert "\n" not in cell, f"{name}: the `perceives` cell must be a single line"


def test_b5_rows_are_ordered_by_collector_name_ascending() -> None:
    names = [_unbacktick(r[0]) for r in _data_rows(_l2_table(_readme_text()))]
    assert names == sorted(names), f"rows are not ascending by collector: {names}"


# ===========================================================================
# Behavior 6 -- the two previously-undescribed collectors are present.
# ===========================================================================
def test_b6_ci_config_and_license_now_have_rows() -> None:
    names = {_unbacktick(r[0]) for r in _data_rows(_l2_table(_readme_text()))}
    for collector in PREVIOUSLY_UNDESCRIBED:
        assert collector in names, (
            f"{collector!r} is the specific documentation gap this iteration "
            f"exists to close; it must head a row of the L2 table. Rows: {sorted(names)}"
        )


# ===========================================================================
# Behavior 7 -- the stale enumeration is gone, replaced by a resolving anchor.
# ===========================================================================
def test_b7_l2_scout_bullet_no_longer_hand_enumerates_collectors() -> None:
    bullet = _l2_scout_bullet(_readme_text())
    assert bullet, "README must still carry the '- **L2 scout**' bullet"
    for retired in RETIRED_PROSE:
        assert retired not in bullet, (
            f"the L2 scout bullet must no longer hand-enumerate the perception "
            f"surface; it still contains {retired!r}: {bullet!r}"
        )


def test_b7_l2_scout_bullet_links_to_the_table_anchor() -> None:
    bullet = _l2_scout_bullet(_readme_text())
    targets = re.findall(r"\]\(([^)]+)\)", bullet)
    assert f"#{ANCHOR}" in targets, (
        f"the L2 scout bullet must point at the table via a '#{ANCHOR}' link "
        f"instead of listing collectors; found link targets {targets}"
    )


def test_b7_the_anchor_resolves_to_exactly_one_heading() -> None:
    slugs = [_github_slug(h) for _i, h in _heading_lines(_readme_text())]
    assert slugs.count(ANCHOR) == 1, (
        f"exactly one README heading must slugify to {ANCHOR!r} (a dangling "
        f"anchor is a broken link on the public page); matches: {slugs.count(ANCHOR)}"
    )


# ===========================================================================
# Behavior 8 -- the census is pure, two-sided, and writes nothing.
# ===========================================================================
def test_b8_census_is_clean_on_the_shipped_readme() -> None:
    assert l2_table_failures(_readme_text(), _collectors_catalog()) == []


def _mutations(text: str) -> dict[str, str]:
    """Four in-memory known-bad copies, keyed by the defect they inject."""
    table = _l2_table(text)
    assert len(table) >= 4, "need a header, a separator and data rows to mutate"
    header, separator, *data = table
    out: dict[str, str] = {}

    # (a) one data row deleted
    out["deleted_row"] = text.replace(data[0] + "\n", "", 1)

    # (b) a bogus row added (appended, so ASCENDING order is preserved and the
    #     set-equality check -- not the order check -- must be what fires)
    bogus = "| `zzz_not_a_collector` | `zzz_not_a_collector` | Bogus row. |"
    out["bogus_row"] = text.replace(data[-1], data[-1] + "\n" + bogus, 1)

    # (c) one row's kind cell altered
    cells = _split_row(data[0])
    altered = f"| {cells[0]} | `zzz_wrong_kind` | {cells[2]} |"
    out["altered_kind"] = text.replace(data[0], altered, 1)

    # (d) rows shuffled out of ascending order (same set, same kinds)
    out["shuffled_rows"] = text.replace(
        "\n".join(table), "\n".join([header, separator, *reversed(data)]), 1
    )
    return out


def test_b8_census_fires_on_each_of_four_mutations_naming_the_offender() -> None:
    text = _readme_text()
    catalog = _collectors_catalog()
    expected_needles = {
        "deleted_row": "no table row",
        "bogus_row": "zzz_not_a_collector",
        "altered_kind": "zzz_wrong_kind",
        "shuffled_rows": "ascending",
    }
    for defect, mutated in _mutations(text).items():
        assert mutated != text, f"mutation {defect!r} did not change the document"
        failures = l2_table_failures(mutated, catalog)
        assert failures, f"the census MISSED the injected defect {defect!r} (fail-open)"
        needle = expected_needles[defect]
        assert any(needle in f for f in failures), (
            f"the census fired on {defect!r} but did not name the offender "
            f"({needle!r}); failures were {failures}"
        )


def test_b8_census_never_writes_to_the_readme() -> None:
    before = README.read_bytes()
    catalog = _collectors_catalog()
    for mutated in _mutations(before.decode("utf-8")).values():
        l2_table_failures(mutated, catalog)
    assert README.read_bytes() == before, (
        "README.md changed on disk while the census ran; the guard must be a "
        "pure function over text, never a file writer"
    )
