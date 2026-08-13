"""Behavior tests for state-dir iteration 146 (ships as ``factory iter 152``).

Feature under test: ``pla --help`` publishes the CLI exit-code contract as an
``exit codes:`` epilog, and the meaning of exit code ``5`` -- which has TWO
producers -- is complete on all THREE public surfaces (the new epilog,
``proactive_loop.cli.main.__doc__``, and the README ``### Exit codes`` table).

WHY THIS MODULE IS RE-WRITTEN RATHER THAN RESTORED
The same product change was reverted at the pre-ship gate of the previous
iteration for a defect in its ORACLE, not in the product: its docstring reader
classified a bullet continuation with ``re.match(r"^\\s{4,}\\S", line)``, and
CPython 3.13 strips a docstring's common leading indent at compile time while
3.12 does not, so the code-5 bullet truncated and the assertion failed on CI's
3.13 leg only.  Every reader here is therefore indentation-AGNOSTIC:
``inspect.cleandoc`` first, then ``^\\s+\\S`` for continuations, never a fixed
width.  ``test_b06_docstring_reader_is_indentation_independent`` pins that
property directly by feeding the reader the 3.12-shaped and 3.13-shaped forms
of one docstring and demanding identical output, so the regression cannot come
back on a single-interpreter run.

WHAT THE EXIT-5 CENSUS CLAIMS (behavior 9)
It is an anti-recurrence ratchet, not a correctness proof: it pins the NUMBER of
literal exit-5 routes in ``cli.py`` so a third route cannot be added without a
human noticing that the code-5 meaning must be updated on all three surfaces
first.  It does not claim those are the only ways the process can exit 5, nor
that a given flag reaches a given site.  Line numbers are deliberately NOT
asserted -- inserting the epilog moved both sites (4268/4296 as measured in this
run) while the count did not.

Isolation: black-box.  The seams are (a) running the public CLI in-process via
``proactive_loop.cli.main`` and capturing stdout, (b) the public ``main``
docstring, (c) ``README.md`` as text -- it is an artifact under test, and (d) an
``ast`` census of ``return``/``raise``/``exit`` nodes in
``src/proactive_loop/cli.py``, which spec behavior 9 REQUIRES and which reads
no logic.  No implementation source, engineer note or reviewer note was read
while writing this file.

Offline and deterministic: in-process calls, pure file reads, stdlib parsing.
No subprocess, no network, no clock, no workspace.

Fail-CLOSED: every reader is fired at a planted known-bad sample in
``test_readers_fire_on_known_bad_samples``, because a parser that silently sees
nothing would make each guard below pass vacuously -- strictly worse than no
guard at all.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import re
from pathlib import Path
from typing import NamedTuple

import pytest

from proactive_loop import __version__
from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
CLI_SOURCE = REPO / "src" / "proactive_loop" / "cli.py"

# argparse renders section titles lowercase with a trailing colon
# ("positional arguments:", "options:"), so the epilog heading matches.
EXIT_CODES_SECTION = "exit codes:"

# An assertion ABOUT the three derivations, never their source of truth.
EXPECTED_CODES = [0, 1, 2, 3, 4, 5]

# Both live producers of exit code 5. `--fail-over` shipped later and every
# public description named only the first, which is the defect being closed.
CODE5_PRODUCERS = ("--fail-on-kind", "--fail-over")

# The epilog is hand-wrapped by a raw formatter, so it owns its own width.
MAX_EPILOG_WIDTH = 80

# Matched against the file's REAL bytes: the spec and role prompt transliterate
# this marker with two hyphens, the file uses an em-dash. A one-sided `in`
# check over the transliterated form would pass vacuously forever.
MARKER_RE = re.compile(r"^.*PORTFOLIO INTRO\s+\S+\s+human-owned.*$", re.MULTILINE)


class Entry(NamedTuple):
    """One ``code -> meaning`` entry of the help epilog."""

    code: int
    lineno: int  # 0-based index within the epilog block
    text: str  # entry line plus its continuation lines, joined by "\n"


# --------------------------------------------------------------------------
# Seams / readers -- each takes its input as a parameter so the non-vacuity
# test can point it at a planted known-bad sample.
# --------------------------------------------------------------------------


def _capture_help(argv: list[str]) -> str:
    """Run the public CLI and return its stdout, asserting a clean exit 0."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
    assert excinfo.value.code == 0, (
        f"pla {' '.join(argv)} must exit 0; got {excinfo.value.code!r}"
    )
    return buf.getvalue()


def _epilog_block(help_text: str) -> list[str]:
    """Lines from the ``exit codes:`` heading to the end of the help text.

    Returns ``[]`` when the section is absent so a caller can assert on the
    absence rather than catch an exception.
    """
    lines = help_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == EXIT_CODES_SECTION:
            return lines[index:]
    return []


def _entries(help_text: str) -> list[Entry]:
    """Parse the epilog block into ``code -> meaning`` entries.

    An entry starts on a line whose first non-whitespace token is a digit; any
    other non-blank line in the block is a continuation of the entry above.
    """
    block = _epilog_block(help_text)
    entries: list[Entry] = []
    for offset, line in enumerate(block[1:], start=1):
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^(\d+)\s+(\S.*)$", stripped)
        if match is not None:
            entries.append(Entry(code=int(match.group(1)), lineno=offset, text=stripped))
        elif entries:
            last = entries[-1]
            entries[-1] = last._replace(text=f"{last.text}\n{stripped}")
    return entries


def _docstring_bullets(doc: str) -> dict[int, str]:
    """``main.__doc__``'s ``* ``N`` ...`` code bullets, code -> joined text.

    Indentation-AGNOSTIC by construction (behavior 6): the text is normalised
    with ``inspect.cleandoc`` and a continuation is any indented non-bullet
    line (``^\\s+\\S``).  It must NOT use a fixed indent width -- that is the
    defect that reverted the previous iteration on Python 3.13 only.
    """
    bullets: dict[int, str] = {}
    current: int | None = None
    bullet_re = re.compile(r"^\s*\*\s+``(\d+)``\s*(.*)$")
    for line in inspect.cleandoc(doc).splitlines():
        match = bullet_re.match(line)
        if match is not None:
            current = int(match.group(1))
            bullets[current] = match.group(2).strip()
        elif not line.strip():
            current = None
        elif current is not None and re.match(r"^\s+\S", line):
            bullets[current] = f"{bullets[current]} {line.strip()}".strip()
        else:
            current = None
    return bullets


def _readme_exit_code_rows(readme_text: str) -> dict[int, str]:
    """The ``### Exit codes`` pipe table, code -> meaning cell."""
    rows: dict[int, str] = {}
    in_section = False
    for line in readme_text.splitlines():
        if re.match(r"^#{1,6}\s", line):
            in_section = line.strip() == "### Exit codes"
            continue
        if not in_section or not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if len(cells) < 2:
            continue
        code_cell = cells[0].strip("`").strip()
        if re.fullmatch(r"\d+", code_cell):
            rows[int(code_cell)] = cells[1]
    return rows


def _exit5_sites(source_text: str) -> dict[str, list[int]]:
    """Every literal exit-5 route, by kind -> ascending line numbers.

    Counts ``return 5``, ``sys.exit(5)`` and ``raise SystemExit(5)`` so the
    census cannot be sidestepped by swapping one spelling for another.
    """
    tree = ast.parse(source_text)
    sites: dict[str, list[int]] = {"return": [], "exit_call": [], "raise": []}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Constant)
            and type(node.value.value) is int
            and node.value.value == 5
        ):
            sites["return"].append(node.lineno)
        elif isinstance(node, ast.Call) and node.args:
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            first = node.args[0]
            if (
                name in {"exit", "_exit"}
                and isinstance(first, ast.Constant)
                and type(first.value) is int
                and first.value == 5
            ):
                sites["exit_call"].append(node.lineno)
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            name = getattr(node.exc.func, "attr", None) or getattr(
                node.exc.func, "id", None
            )
            args = node.exc.args
            if (
                name == "SystemExit"
                and args
                and isinstance(args[0], ast.Constant)
                and type(args[0].value) is int
                and args[0].value == 5
            ):
                sites["raise"].append(node.lineno)
    return {kind: sorted(linenos) for kind, linenos in sites.items()}


# --------------------------------------------------------------------------
# Behavior 1 -- the section exists on the top-level help, which exits 0
# --------------------------------------------------------------------------


def test_b01_top_level_help_publishes_an_exit_codes_section() -> None:
    out = _capture_help(["--help"])
    stripped = [line.strip() for line in out.splitlines()]
    assert EXIT_CODES_SECTION in stripped, (
        "pla --help must contain a line whose stripped text is exactly "
        "'exit codes:' -- it is the surface a scripting consumer reaches for "
        "first, and the exit codes are this tool's integration contract; "
        f"section-like lines found: {[s for s in stripped if s.endswith(':')]}"
    )


# --------------------------------------------------------------------------
# Behavior 2 -- exactly six entries, 0-5 ascending, plus the PRECONDITION
# that makes the entry parse sound
# --------------------------------------------------------------------------


def test_b02_epilog_lists_exactly_the_six_codes_in_ascending_order() -> None:
    entries = _entries(_capture_help(["--help"]))
    codes = [entry.code for entry in entries]
    assert codes == EXPECTED_CODES, (
        "the exit-codes epilog must introduce exactly the codes 0-5, one per "
        f"entry, ascending, with no duplicate and no seventh code; parsed {codes}"
    )
    for entry in entries:
        head = entry.text.split(None, 1)
        assert len(head) == 2 and head[1].strip(), (
            f"exit code {entry.code} is listed with no meaning: {entry.text!r}"
        )


def test_b02_precondition_continuations_are_indented_and_never_start_a_digit() -> None:
    """Without this the entry parse could silently absorb a wrapped line."""
    help_text = _capture_help(["--help"])
    block = _epilog_block(help_text)
    assert block, "no 'exit codes:' section to parse"
    entry_linenos = {entry.lineno for entry in _entries(help_text)}
    continuations = 0
    for offset, line in enumerate(block[1:], start=1):
        if offset in entry_linenos or not line.strip():
            continue
        continuations += 1
        assert not line.strip()[:1].isdigit(), (
            "a continuation line in the exit-codes epilog begins with a digit, "
            "so a future meaning could be mis-parsed as a seventh code: "
            f"{line!r}"
        )
        assert line[:1].isspace(), (
            f"a continuation line must stay indented under its code: {line!r}"
        )
    assert continuations >= 5, (
        "expected the wrapped meanings to produce continuation lines; the "
        f"precondition is vacuous if there are none (found {continuations})"
    )


# --------------------------------------------------------------------------
# Behavior 3 -- the epilog's code-5 entry names BOTH producers
# --------------------------------------------------------------------------


def test_b03_epilog_code5_entry_names_both_producers() -> None:
    entries = {entry.code: entry.text for entry in _entries(_capture_help(["--help"]))}
    assert 5 in entries, "the epilog does not document exit code 5"
    for flag in CODE5_PRODUCERS:
        assert flag in entries[5], (
            f"the epilog's exit-5 meaning omits {flag!r}: both --fail-on-kind "
            "and --fail-over return 5, and the code is all a script sees; got "
            f"{entries[5]!r}"
        )


# --------------------------------------------------------------------------
# Behavior 4 -- the block owns its width: <= 80 columns, no flag split
# --------------------------------------------------------------------------


def test_b04_epilog_lines_fit_80_columns_and_never_split_a_flag() -> None:
    block = _epilog_block(_capture_help(["--help"]))
    assert block, "no 'exit codes:' section to measure"
    too_wide = [line for line in block if len(line) > MAX_EPILOG_WIDTH]
    assert not too_wide, (
        f"epilog lines must fit {MAX_EPILOG_WIDTH} columns, because a raw "
        "formatter will not re-wrap them on a narrow terminal; over-long: "
        f"{[(len(line), line) for line in too_wide]}"
    )
    for flag in CODE5_PRODUCERS:
        assert any(flag in line for line in block), (
            f"{flag!r} does not appear intact on any single epilog line, so a "
            "reader greping for the flag will not find it"
        )


# --------------------------------------------------------------------------
# Behavior 5 -- the block is width-independent (scope: the block only)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("columns", ["40", "80", "200"])
def test_b05_epilog_block_is_byte_identical_across_terminal_widths(
    monkeypatch: pytest.MonkeyPatch, columns: str
) -> None:
    monkeypatch.setenv("COLUMNS", "80")
    baseline = "\n".join(_epilog_block(_capture_help(["--help"])))
    assert baseline, "no 'exit codes:' section rendered at COLUMNS=80"
    monkeypatch.setenv("COLUMNS", columns)
    rendered = "\n".join(_epilog_block(_capture_help(["--help"])))
    assert rendered == baseline, (
        f"the exit-codes block must be byte-identical at COLUMNS={columns} -- a "
        "re-wrapped meaning would break the one-entry-per-line contract that "
        "behavior 2's parse depends on"
    )


# --------------------------------------------------------------------------
# Behavior 6 -- main.__doc__'s code-5 bullet, read indentation-agnostically
# --------------------------------------------------------------------------


def test_b06_docstring_code5_bullet_names_both_producers() -> None:
    doc = main.__doc__ or ""
    assert doc.strip(), "proactive_loop.cli.main lost its docstring"
    bullets = _docstring_bullets(doc)
    assert 5 in bullets, f"main.__doc__ no longer enumerates exit code 5: {bullets!r}"
    for flag in CODE5_PRODUCERS:
        assert flag in bullets[5], (
            f"main.__doc__'s code-5 bullet omits {flag!r}; got {bullets[5]!r}"
        )


def test_b06_docstring_reader_is_indentation_independent() -> None:
    """Pins the exact defect that reverted the previous iteration.

    CPython 3.13 strips a docstring's common leading indent at compile time,
    3.12 does not, so the SAME source yields two different ``__doc__`` strings.
    The reader must return identical bullets for both shapes.
    """
    dedented = (
        "Console entry point.\n"
        "\n"
        "* ``4`` -- needs-approval (re-run with ``--yes``).\n"
        "* ``5`` -- a requested gate tripped on a finding: either\n"
        "  ``--fail-on-kind`` matched a reported signal, or ``--fail-over``\n"
        "  saw more reported signals than its budget allows.\n"
    )
    indented = "".join(
        line if index == 0 else (f"    {line}" if line.strip() else line)
        for index, line in enumerate(dedented.splitlines(keepends=True))
    )
    assert indented != dedented, "the two docstring shapes must actually differ"
    from_dedented = _docstring_bullets(dedented)
    from_indented = _docstring_bullets(indented)
    assert from_dedented == from_indented, (
        "the docstring reader is indentation-sensitive, so it will disagree "
        "between CPython 3.12 and 3.13 as it did in the reverted iteration: "
        f"3.13-shape {from_dedented!r} vs 3.12-shape {from_indented!r}"
    )
    for flag in CODE5_PRODUCERS:
        assert flag in from_indented[5] and flag in from_dedented[5], (
            f"the reader dropped {flag!r} from a continuation line, which is "
            "exactly how the reverted assertion failed on 3.13 only"
        )


# --------------------------------------------------------------------------
# Behavior 7 -- the three surfaces agree on the code SET
# --------------------------------------------------------------------------


def test_b07_all_three_surfaces_publish_the_same_code_set() -> None:
    epilog_codes = {entry.code for entry in _entries(_capture_help(["--help"]))}
    docstring_codes = set(_docstring_bullets(main.__doc__ or ""))
    readme_codes = set(_readme_exit_code_rows(README.read_text(encoding="utf-8")))
    expected = set(EXPECTED_CODES)
    assert epilog_codes == expected, f"epilog codes {sorted(epilog_codes)} != 0-5"
    assert docstring_codes == expected, (
        f"main.__doc__ codes {sorted(docstring_codes)} != 0-5"
    )
    assert readme_codes == expected, f"README table codes {sorted(readme_codes)} != 0-5"


# --------------------------------------------------------------------------
# Behavior 8 -- README: row 5 names both producers, every edit is BELOW the
# human-owned marker, and the intro block keeps its carve-out numbers
# --------------------------------------------------------------------------


def test_b08_readme_row5_names_both_producers_and_rows_0_to_4_survive() -> None:
    rows = _readme_exit_code_rows(README.read_text(encoding="utf-8"))
    for code in EXPECTED_CODES:
        assert code in rows and rows[code].strip(), (
            f"the README '### Exit codes' table lost a meaning for code {code}"
        )
    for flag in CODE5_PRODUCERS:
        assert flag in rows[5], (
            f"the README exit-5 row omits {flag!r}; got {rows[5]!r}"
        )
    for code in (0, 1, 2, 3, 4):
        assert "--fail-over" not in rows[code], (
            f"row {code} was edited to mention --fail-over; this iteration "
            "documents exit 5 only"
        )


def test_b08_exit_codes_table_lives_below_the_human_owned_marker() -> None:
    text = README.read_text(encoding="utf-8")
    markers = MARKER_RE.findall(text)
    assert len(markers) == 1, (
        "the human-owned portfolio-intro marker must appear exactly once "
        f"(matched {len(markers)}: {markers!r}) -- a guard that cannot find it "
        "passes vacuously and stops protecting the block"
    )
    marker_at = text.index(markers[0])
    heading_at = text.index("### Exit codes")
    assert heading_at > marker_at, (
        "the '### Exit codes' section must sit BELOW the human-owned intro "
        "marker; automated contributors may not restructure the intro"
    )
    intro = text[:marker_at]
    assert "exit code" not in intro.lower(), (
        "the human-owned portfolio intro must not have gained exit-code prose"
    )


def test_b08_portfolio_intro_keeps_its_three_carve_out_numbers() -> None:
    """Shape, not value: the three numbers are REQUIRED to move as the repo grows."""
    text = README.read_text(encoding="utf-8")
    intro = text[: text.index(MARKER_RE.findall(text)[0])]
    for label, pattern in (
        ("collector count", r"\b\d+\s+context\s+collectors\b"),
        ("CLI verb count", r"\b\d+\s+(?:CLI\s+)?verbs\b"),
        ("tests floor", r"\b\d,\d00\+\s+tests\b"),
    ):
        assert re.search(pattern, intro, re.IGNORECASE), (
            f"the portfolio intro lost its {label} claim (pattern {pattern!r}); "
            "the intro is human-owned apart from these three numbers, so a "
            "missing one means the block was restructured"
        )


# --------------------------------------------------------------------------
# Behavior 9 -- the exit-5 census ratchet (count, never line numbers)
# --------------------------------------------------------------------------


def test_b09_cli_has_exactly_two_literal_exit_5_routes() -> None:
    sites = _exit5_sites(CLI_SOURCE.read_text(encoding="utf-8"))
    total = sum(len(linenos) for linenos in sites.values())
    assert total == 2, (
        "src/proactive_loop/cli.py must hold exactly 2 literal exit-5 routes "
        f"(found {total}: {sites}). RELEASE CONDITION: a third route to exit 5 "
        "may only be added once its meaning is named on ALL THREE published "
        "surfaces -- the 'exit codes:' epilog on `pla --help`, the code-5 "
        "bullet of proactive_loop.cli.main.__doc__, and the README "
        "'### Exit codes' row 5 -- and this census is raised in the same "
        "commit. Exit 5 is the channel CI branches on; an undocumented route "
        "to it is an undocumented contract."
    )
    assert len(sites["return"]) == 2, (
        f"expected both routes to be literal `return 5` statements; got {sites}"
    )


# --------------------------------------------------------------------------
# Behavior 10 -- the epilog is TOP-LEVEL only
# --------------------------------------------------------------------------


def test_b10_subcommand_help_does_not_inherit_the_epilog() -> None:
    out = _capture_help(["signals", "--help"])
    assert EXIT_CODES_SECTION not in [line.strip() for line in out.splitlines()], (
        "the exit-codes epilog must not leak onto subcommand help: repeating "
        "the whole contract under every verb is noise, and `pla --help` is the "
        "single place it is published"
    )
    assert "--fail-on-kind" in out, (
        "sanity: `pla signals --help` should still document its own gate flag, "
        "otherwise this test is asserting against the wrong parser"
    )


# --------------------------------------------------------------------------
# Behavior 11 -- no regression on the surrounding help surface
# --------------------------------------------------------------------------


def test_b11_version_and_top_level_description_still_work() -> None:
    version_out = _capture_help(["--version"])
    assert __version__ in version_out, (
        f"`pla --version` must print {__version__!r}; got {version_out!r}"
    )
    help_out = _capture_help(["--help"])
    assert "synthesize a ranked goal slate" in help_out, (
        "the top-level description sentence was lost when the epilog was added"
    )


# --------------------------------------------------------------------------
# Non-vacuity: every reader must FIRE on a planted known-bad sample
# --------------------------------------------------------------------------


def test_readers_fire_on_known_bad_samples() -> None:
    # (a) epilog reader: absent section, and a section missing code 3
    assert _epilog_block("usage: pla\n\noptions:\n  -h\n") == [], (
        "_epilog_block must report an absent section as empty"
    )
    missing_three = (
        "usage: pla\n\nexit codes:\n"
        "  0  success.\n  1  fault.\n  2  nothing to do.\n"
        "  4  needs approval.\n  5  gate tripped.\n"
    )
    assert [entry.code for entry in _entries(missing_three)] == [0, 1, 2, 4, 5], (
        "_entries must see a MISSING code, otherwise behavior 2 is vacuous"
    )
    absorbed = (
        "usage: pla\n\nexit codes:\n"
        "  5  gate tripped on a finding, either --fail-on-kind\n"
        "     or --fail-over.\n"
    )
    parsed = _entries(absorbed)
    assert len(parsed) == 1 and "--fail-over" in parsed[0].text, (
        "_entries must JOIN continuation lines, or behavior 3 would miss a "
        f"producer named on the wrapped line; got {parsed!r}"
    )

    # (b) docstring reader: a code-5 bullet that names only one producer
    one_producer = (
        "Console entry point.\n"
        "\n"
        "* ``5`` -- a gate tripped: ``--fail-on-kind`` matched a signal.\n"
    )
    bullets = _docstring_bullets(one_producer)
    assert bullets.keys() == {5} and "--fail-over" not in bullets[5], (
        "_docstring_bullets must detect a missing producer, else behavior 6 "
        f"passes vacuously; got {bullets!r}"
    )
    assert _docstring_bullets("No bullets here.\n") == {}, (
        "_docstring_bullets must return {} when there are no code bullets"
    )

    # (c) README reader: a stripped flag name, and a table outside the section
    bad_table = (
        "### Exit codes\n\n| Code | Meaning |\n|------|---------|\n"
        "| 0 | Success. |\n| 5 | A gate tripped on a finding. |\n"
    )
    rows = _readme_exit_code_rows(bad_table)
    assert rows.keys() == {0, 5} and "--fail-on-kind" not in rows[5], (
        f"_readme_exit_code_rows must detect a stripped flag name; got {rows!r}"
    )
    other_section = (
        "### Something else\n\n| Code | Meaning |\n|------|---------|\n| 5 | x |\n"
    )
    assert _readme_exit_code_rows(other_section) == {}, (
        "_readme_exit_code_rows must ignore pipe tables outside '### Exit codes'"
    )

    # (d) ast census: a third route, and an alternate exit spelling
    third_route = (
        "import sys\n"
        "def a() -> int:\n    return 5\n"
        "def b() -> int:\n    return 5\n"
        "def c() -> None:\n    sys.exit(5)\n"
        "def d() -> None:\n    raise SystemExit(5)\n"
    )
    sites = _exit5_sites(third_route)
    assert sum(len(v) for v in sites.values()) == 4, (
        f"_exit5_sites must count every literal exit-5 spelling; got {sites!r}"
    )
    assert _exit5_sites("def a() -> int:\n    return 4\n") == {
        "return": [],
        "exit_call": [],
        "raise": [],
    }, "_exit5_sites must not match a different constant"
