"""Behavior tests for state-dir iteration 110 (ships as commit-seq ``factory iter 117``).

Feature under test: the README's ``## CLI`` section now publishes the CLI
exit-code contract as an ``### Exit codes`` table, and this module is the drift
guard that keeps that table honest against the two sources of truth already in
the repo -- the enumerated bullet list in ``proactive_loop.cli.main.__doc__``
and the integer literals actually returned by ``src/proactive_loop/cli.py``.

WHAT THIS GUARD CLAIMS, AND WHAT IT DELIBERATELY DOES NOT
This guard enumerates the exit-code SET and NOT every code path to each code.
Most exit-``1`` outcomes are produced by ``main()``'s top-level exception
guard rather than by a literal ``return 1``, so a rule demanding one literal
return site per documented code would fail for a correct program. Behavior 5
is therefore a SUBSET relation (every literally returned code must be
documented), never an equality, and nothing here asserts that a particular
error reaches a particular code. The MEANINGS are owned by a different oracle:
``tests/test_cli_integration.py`` executes a BLOCKED dispatch and a sensitive
dispatch and asserts they return ``3`` and ``4``. Behavior 8 checks that oracle
still exists rather than re-implementing it, so the two files cannot both rot
in the same direction.

Why the documented set is DERIVED twice and hardcoded once
The six codes are written down once (``EXPECTED_CODES``) purely as an
assertion ABOUT the two derivations; the comparisons that can actually catch
drift are README-vs-docstring (behavior 4) and returns-vs-README (behavior 5),
neither of which consults the constant. Behavior 6 closes the census: every
integer-constant ``return`` in ``cli.py`` must sit inside a function annotated
``-> int``, so a new code smuggled into an unannotated helper cannot become
invisible to behavior 5 -- the gate must never exempt the one place it should
look.

Isolation: black-box. The seams used are (a) reading ``README.md`` as text --
it is the artifact under test, (b) the public ``proactive_loop.cli.main``
docstring, (c) parsing ``src/proactive_loop/cli.py`` with ``ast``, which spec
behaviors 5 and 6 REQUIRE and which reads only return statements and return
annotations, never logic, and (d) reading ``tests/`` as text. No
implementation source was read while writing this file; no engineer, reviewer
or fix note was opened.

Offline: pure file reads and stdlib parsing. No subprocess, no network, no
temp writes, so the whole module costs milliseconds.

Every reader here is fail-CLOSED and each is fired at a known-bad sample in
``test_readers_fire_on_known_bad_samples``: a heading finder that could not
see a deleted section, a table parser that accepted an empty meaning, or an
``ast`` sweep that walked zero functions would all make these guards pass
vacuously, which is strictly worse than no guard at all.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import NamedTuple

from proactive_loop.cli import main

# --------------------------------------------------------------------------
# Paths. Read through the helpers below (never at import time) so a throwaway
# non-vacuity script can repoint ``README`` at a mutated copy.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
CLI_SOURCE = REPO / "src" / "proactive_loop" / "cli.py"
INTEGRATION_TEST = REPO / "tests" / "test_cli_integration.py"

# The live marker reads "PORTFOLIO INTRO <em dash> human-owned"; match only the
# stable ASCII prefix, the same substring tests/test_readme_and_ci_contract.py
# uses, so a dash-style edit cannot silently disarm behavior 2.
HUMAN_OWNED_MARKER = "PORTFOLIO INTRO"

EXIT_CODES_HEADING_TEXT = "Exit codes"
CLI_HEADING_TEXT = "CLI"

# An assertion ABOUT the derivations, not their source of truth (see docstring).
EXPECTED_CODES = {0, 1, 2, 3, 4, 5}


class Heading(NamedTuple):
    """One real Markdown heading -- fenced code-block comments excluded."""

    level: int
    text: str
    offset: int  # character offset of the '#' in the full text
    lineno: int  # 1-based


class Row(NamedTuple):
    """One data row of a Markdown pipe table."""

    cells: tuple[str, ...]
    lineno: int


# --------------------------------------------------------------------------
# Readers (fence-aware Markdown, pipe tables, docstring bullets, ast census)
# --------------------------------------------------------------------------


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _headings(text: str) -> list[Heading]:
    """Every ATX heading OUTSIDE fenced code blocks.

    Fence awareness is load-bearing, not cosmetic: this README's fenced shell
    and python blocks contain comment lines like ``# every context signal ...``
    which a naive ``^#`` scan reads as level-1 headings.
    """
    out: list[Heading] = []
    offset = 0
    in_fence = False
    for lineno, line in enumerate(text.splitlines(keepends=True), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            match = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
            if match is not None:
                out.append(
                    Heading(
                        level=len(match.group(1)),
                        text=match.group(2),
                        offset=offset,
                        lineno=lineno,
                    )
                )
        offset += len(line)
    return out


def _split_row(line: str) -> tuple[str, ...]:
    """Split one pipe-table line into stripped cells, honoring ``\\|`` escapes."""
    body = line.strip()
    body = body.removeprefix("|").removesuffix("|")
    return tuple(cell.strip() for cell in re.split(r"(?<!\\)\|", body))


def _is_separator_row(cells: tuple[str, ...]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells)


def _table_after(text: str, heading: Heading) -> list[Row]:
    """Data rows of the FIRST pipe table following ``heading``.

    Returns ``[]`` when no table follows before the next heading -- the reader
    reports absence instead of raising, so a caller can assert on it.
    """
    lines = text.splitlines()
    rows: list[Row] = []
    started = False
    for lineno in range(heading.lineno + 1, len(lines) + 1):
        line = lines[lineno - 1]
        stripped = line.strip()
        if stripped.startswith("|"):
            started = True
            cells = _split_row(line)
            if not _is_separator_row(cells):
                rows.append(Row(cells=cells, lineno=lineno))
        elif started:
            break  # table ended
        elif re.match(r"^#{1,6}\s", line):
            break  # next section reached without a table
    # Drop the header row (the first non-separator row) if one is present.
    return rows[1:] if rows else rows


def _exit_code_heading(text: str) -> Heading | None:
    matches = [h for h in _headings(text) if h.text == EXIT_CODES_HEADING_TEXT]
    return matches[0] if len(matches) == 1 else None


def _documented_rows(text: str) -> list[Row]:
    heading = _exit_code_heading(text)
    return [] if heading is None else _table_after(text, heading)


def _documented_codes(text: str) -> list[int]:
    """The first column of the exit-code table, as ints, IN TABLE ORDER.

    A list (not a set) so behavior 3 can detect a duplicated code.
    """
    codes: list[int] = []
    for row in _documented_rows(text):
        cell = row.cells[0].strip().strip("`").strip()
        if re.fullmatch(r"\d+", cell):
            codes.append(int(cell))
    return codes


def _docstring_codes() -> set[int]:
    """Codes enumerated by ``main()``'s own RST bullet list."""
    doc = main.__doc__ or ""
    return {int(m) for m in re.findall(r"^\s*\*\s+``(\d+)``", doc, flags=re.MULTILINE)}


def _int_constant(node: ast.expr | None) -> int | None:
    """The value of ``return <int literal>``; ``None`` for anything else.

    ``bool`` is excluded explicitly -- it is a subclass of ``int``, so without
    this ``return True`` would be miscounted as exit code 1.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None


def _direct_returns(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """``return`` statements whose NEAREST enclosing function is ``fn``."""
    out: list[ast.Return] = []
    stack: list[ast.AST] = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return):
            out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def _returns_int_annotation(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return isinstance(fn.returns, ast.Name) and fn.returns.id == "int"


class Census(NamedTuple):
    """Result of the ``cli.py`` integer-constant-return census."""

    functions: int
    int_annotated: int
    sites: list[tuple[int, int]]  # (lineno, value) inside an -> int function
    orphans: list[tuple[int, int]]  # (lineno, value) elsewhere

    @property
    def codes(self) -> set[int]:
        return {value for _, value in self.sites}


def _census(source: str) -> Census:
    tree = ast.parse(source)
    functions = 0
    int_annotated = 0
    sites: list[tuple[int, int]] = []
    orphans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        functions += 1
        annotated = _returns_int_annotation(node)
        if annotated:
            int_annotated += 1
        for ret in _direct_returns(node):
            value = _int_constant(ret.value)
            if value is None:
                continue
            (sites if annotated else orphans).append((ret.lineno, value))
    return Census(functions=functions, int_annotated=int_annotated, sites=sites, orphans=orphans)


def _row_for(text: str, code: int) -> Row | None:
    for row in _documented_rows(text):
        cell = row.cells[0].strip().strip("`").strip()
        if re.fullmatch(r"\d+", cell) and int(cell) == code:
            return row
    return None


_YES_IS_USELESS = re.compile(r"(does|will|would)\s+not\s+help|no(t)?\s+help|cannot\s+help")


def _row_3_is_a_dead_end(row: Row | None) -> bool:
    """Row for code 3 must say BLOCKED and that ``--yes`` does not help."""
    if row is None:
        return False
    text = " ".join(row.cells[1:])
    lowered = text.lower()
    return "blocked" in lowered and "--yes" in text and bool(_YES_IS_USELESS.search(lowered))


def _row_4_is_retryable(row: Row | None) -> bool:
    """Row for code 4 must point at approval and a ``--yes`` re-run."""
    if row is None:
        return False
    text = " ".join(row.cells[1:])
    lowered = text.lower()
    return "approv" in lowered and "--yes" in text and not _YES_IS_USELESS.search(lowered)


# --------------------------------------------------------------------------
# Behaviors
# --------------------------------------------------------------------------


def test_behavior1_exit_codes_is_one_level3_heading_inside_the_cli_section() -> None:
    """1. Exactly one ``### Exit codes`` heading, located inside ``## CLI``."""
    text = _readme_text()
    headings = _headings(text)
    assert headings, "heading reader found nothing -- README unreadable or reader broken"
    # Fail-closed: the reader must not mistake fenced comment lines for headings.
    assert not [h for h in headings if h.text.startswith("every context signal")], (
        "fence-awareness regressed: a code-block comment was read as a heading"
    )

    named = [h for h in headings if h.text == EXIT_CODES_HEADING_TEXT]
    assert len(named) == 1, f"expected exactly one 'Exit codes' heading, found {len(named)}"
    assert named[0].level == 3, f"'Exit codes' must be level 3, got level {named[0].level}"

    cli = [h for h in headings if h.level == 2 and h.text == CLI_HEADING_TEXT]
    assert len(cli) == 1, "expected exactly one '## CLI' heading"
    following = [h for h in headings if h.level == 2 and h.offset > cli[0].offset]
    assert following, "'## CLI' must not be the last level-2 section"
    assert cli[0].offset < named[0].offset < following[0].offset, (
        f"'### Exit codes' (offset {named[0].offset}) must sit between '## CLI' "
        f"({cli[0].offset}) and '## {following[0].text}' ({following[0].offset})"
    )


def test_behavior2_exit_codes_section_sits_below_the_human_owned_marker() -> None:
    """2. The new section is below the human-owned portfolio-intro marker."""
    text = _readme_text()
    marker = text.find(HUMAN_OWNED_MARKER)
    assert marker != -1, f"human-owned marker {HUMAN_OWNED_MARKER!r} vanished from README"
    heading = _exit_code_heading(text)
    assert heading is not None, "no unique '### Exit codes' heading"
    assert heading.offset > marker, (
        "'### Exit codes' was placed ABOVE the human-owned intro marker"
    )


def test_behavior3_table_documents_six_distinct_codes_with_real_meanings() -> None:
    """3. Six rows, no duplicates, every meaning cell non-empty."""
    text = _readme_text()
    rows = _documented_rows(text)
    assert rows, "no pipe table follows the '### Exit codes' heading"
    codes = _documented_codes(text)
    assert len(codes) == len(rows), (
        f"{len(rows)} table rows but only {len(codes)} parsed as integer codes: "
        f"{[r.cells[0] for r in rows]}"
    )
    assert len(codes) == len(set(codes)), f"duplicate exit code documented: {codes}"
    assert set(codes) == EXPECTED_CODES, f"documented codes {sorted(codes)} != {sorted(EXPECTED_CODES)}"
    for row in rows:
        assert len(row.cells) >= 2, f"row on line {row.lineno} has no meaning column"
        meaning = " ".join(row.cells[1:]).strip().strip("`").strip()
        assert meaning, f"empty meaning for code {row.cells[0]!r} on line {row.lineno}"


def test_behavior4_documented_codes_match_the_main_docstring_contract() -> None:
    """4. README table == the contract enumerated in ``main.__doc__``."""
    docstring_codes = _docstring_codes()
    assert docstring_codes, (
        "parsed zero codes out of main.__doc__ -- the docstring bullet form changed, "
        "so this comparison would have passed vacuously"
    )
    documented = set(_documented_codes(_readme_text()))
    assert documented == docstring_codes, (
        f"README documents {sorted(documented)} but main.__doc__ enumerates "
        f"{sorted(docstring_codes)}"
    )


def test_behavior5_returned_codes_are_a_nonempty_subset_of_documented_codes() -> None:
    """5. Every literally returned exit code has a README row (subset, not equality)."""
    census = _census(CLI_SOURCE.read_text(encoding="utf-8"))
    assert census.sites, "census found zero integer-constant returns in cli.py -- reader broken"
    documented = set(_documented_codes(_readme_text()))
    undocumented = sorted(census.codes - documented)
    assert not undocumented, (
        f"cli.py returns exit code(s) {undocumented} that the README does not document; "
        f"sites: {[s for s in census.sites if s[1] in set(undocumented)]}"
    )


def test_behavior6_every_int_constant_return_sits_in_an_int_annotated_function() -> None:
    """6. Fail-closed completeness: no integer-constant return escapes the census."""
    census = _census(CLI_SOURCE.read_text(encoding="utf-8"))
    assert census.functions > 1, f"walked only {census.functions} functions in cli.py"
    assert census.int_annotated > 0, "no '-> int' annotated function found in cli.py"
    assert not census.orphans, (
        "integer-constant return(s) outside an '-> int' annotated function -- "
        f"behavior 5 cannot see them: {census.orphans}"
    )


def test_behavior7_rows_for_3_and_4_branch_in_opposite_directions() -> None:
    """7. The one distinction a wrapper script inverts is spelled out."""
    text = _readme_text()
    row3 = _row_for(text, 3)
    row4 = _row_for(text, 4)
    assert row3 is not None, "no row documents exit code 3"
    assert row4 is not None, "no row documents exit code 4"
    assert _row_3_is_a_dead_end(row3), (
        f"code-3 row must say BLOCKED and that --yes does not help; got: {row3.cells[1:]!r}"
    )
    assert _row_4_is_retryable(row4), (
        f"code-4 row must point at approval plus a --yes re-run; got: {row4.cells[1:]!r}"
    )


def test_behavior8_the_forward_semantics_oracle_still_exists() -> None:
    """8. The meanings of 3 and 4 stay owned by the integration test, not by this file.

    A presence check, deliberately NOT a re-implementation: if that oracle were
    deleted, the doc guard here would keep passing while nothing executed a
    BLOCKED or sensitive dispatch again.
    """
    source = INTEGRATION_TEST.read_text(encoding="utf-8")
    assert re.search(r"_dispatch\(\s*blocked\.id\s*,\s*yes=True\s*\)\s*==\s*3", source), (
        "tests/test_cli_integration.py no longer asserts a BLOCKED dispatch returns 3"
    )
    assert re.search(r"_dispatch\(\s*sensitive\.id\s*,\s*yes=False\s*\)\s*==\s*4", source), (
        "tests/test_cli_integration.py no longer asserts an unapproved sensitive dispatch returns 4"
    )
    # This module must not duplicate that execution: it may READ main.__doc__ but
    # must never CALL a command. Checked structurally so a regex written in prose
    # here cannot be mistaken for a call.
    own_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(own_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "main" not in called, (
        "this module started executing the CLI -- keep the meanings in one oracle"
    )


def test_behavior9_module_docstring_disclaims_path_coverage() -> None:
    """9. The guard states in its own docstring what it does NOT cover."""
    # Whitespace-normalized: a docstring re-wrap must not disarm this check.
    doc = " ".join((__doc__ or "").split())
    assert "exit-code SET and NOT every code path" in doc, (
        "module docstring must state that the guard covers the code SET, not every code path"
    )
    assert "exception guard" in doc, (
        "module docstring must explain WHY (exit 1 flows through main()'s exception guard)"
    )


def test_readers_fire_on_known_bad_samples() -> None:
    """Non-vacuity: each reader rejects a mutated README, in this process."""
    text = _readme_text()
    heading = _exit_code_heading(text)
    assert heading is not None
    rows = _documented_rows(text)
    assert len(rows) == len(EXPECTED_CODES)

    # (a) whole section deleted -> heading reader reports absence.
    next_h2 = next(h for h in _headings(text) if h.level == 2 and h.offset > heading.offset)
    without_section = text[: heading.offset] + text[next_h2.offset :]
    assert _exit_code_heading(without_section) is None
    assert _documented_codes(without_section) == []
    assert _row_for(without_section, 3) is None

    # (b) rows 3 and 4 deleted -> set mismatch vs the docstring contract.
    lines = text.splitlines(keepends=True)
    keep = [ln for ln in lines if ln not in (lines[rows[3].lineno - 1], lines[rows[4].lineno - 1])]
    without_34 = "".join(keep)
    # The surviving set is DERIVED from the two rows actually removed rather than
    # hardcoded, so appending a code keeps this sample honest instead of stale.
    dropped = {int(rows[i].cells[0].strip().strip("`").strip()) for i in (3, 4)}
    assert dropped == {3, 4}, f"rows 3/4 are no longer codes 3/4: {sorted(dropped)}"
    assert set(_documented_codes(without_34)) == EXPECTED_CODES - dropped
    assert set(_documented_codes(without_34)) != _docstring_codes()

    # (c) an empty meaning cell -> behavior 3's non-empty check must reject it.
    blanked = text.replace(lines[rows[0].lineno - 1], "| 0 |  |\n")
    blank_rows = _documented_rows(blanked)
    assert blank_rows and not " ".join(blank_rows[0].cells[1:]).strip()

    # (d) a duplicated code -> duplicate detection must see it.
    duped = text.replace(lines[rows[4].lineno - 1], lines[rows[4].lineno - 1] * 2)
    duped_codes = _documented_codes(duped)
    assert len(duped_codes) != len(set(duped_codes))

    # (e) the 3-vs-4 rows swapped in meaning -> behavior 7 must reject both.
    inverted = text.replace(
        lines[rows[3].lineno - 1],
        "| 3 | BLOCKED -- once a human has approved it, re-run with `--yes`. |\n",
    )
    assert not _row_3_is_a_dead_end(_row_for(inverted, 3))
    scrubbed = text.replace(lines[rows[4].lineno - 1], "| 4 | NEEDS_APPROVAL -- stops. |\n")
    assert not _row_4_is_retryable(_row_for(scrubbed, 4))

    # (f) an undocumented literal return -> behavior 5's subset check must fail.
    census = _census("def _handler() -> int:\n    return 7\n")
    assert census.codes == {7}
    assert census.codes - EXPECTED_CODES == {7}

    # (g) a literal return in an unannotated helper -> behavior 6 must see an orphan.
    orphaned = _census("def _helper():\n    return 9\n")
    assert orphaned.orphans == [(2, 9)] and not orphaned.sites

    # (h) bool is not an exit code.
    assert _census("def _f() -> int:\n    return True\n").sites == []
