"""Behavior tests for factory iteration 251 -- exit code 1 names EVERY producer.

Exit code 1 has two literal routes in ``cli.py``: the top-level operational-fault
boundary in ``main``, and ``_cmd_signals``' fail-CLOSED route for a collector that
owns a kind armed with ``--fail-on-kind`` and degraded mid-scan.  Two of the three
published code-1 surfaces named only the first, so a script branching on the code
would read "a gate refused to certify a result it could not prove" as "the tool
crashed" -- the opposite conclusion.

This module is the oracle for that contract, and it mirrors the proven shape of
``tests/test_iter152_behavior.py`` (the same discipline for exit code 5) with its
OWN local readers, so neither module can drift the other:

* the producer set is DERIVED from ``cli.py`` source text, never written down here;
* every reader takes its input as a PARAMETER, so each guard has a two-sided
  control fed a synthetic known-bad sample;
* the exit-1 route census reports enclosing FUNCTION NAMES and never line numbers
  (line anchors drift and are banned in this repo).

All checks are offline, deterministic and in-memory apart from rendering the
product's own ``--help`` and reading tracked files.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import re
import subprocess
from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
CLI_SOURCE = REPO / "src" / "proactive_loop" / "cli.py"

# argparse renders section titles lowercase with a trailing colon.
EXIT_CODES_SECTION = "exit codes:"

# The epilog is hand-wrapped by a raw formatter, so it owns its own width.
MAX_EPILOG_WIDTH = 80

# An assertion ABOUT the three derivations, never their source of truth.
EXPECTED_CODES = [0, 1, 2, 3, 4, 5]

# Sibling contract text this iteration must not disturb (behavior 9).
SIBLING_ORACLE = "tests/test_iter152_behavior.py"

# Every fail-closed gate announces itself on stderr as
# `error: <flag> gate unproven`, so that literal is the one place the code names
# its own exit-1 producers.  The flag shape is `--` plus lowercase-alphanumeric
# words joined by SINGLE hyphens and never ending in one, so a malformed
# `error: --fail-over- gate unproven` yields no producer rather than a flag name
# no CLI surface could ever match.
UNPROVEN_LITERAL_RE = re.compile(
    r"error:\s+(--[a-z0-9]+(?:-[a-z0-9]+)*)\s+gate unproven\b"
)

# The exit-5 convention is a DIFFERENT literal shape (bare flag, no leading
# `--`), which is why the two producer sets cannot cross-contaminate.
GATE_LITERAL_RE = re.compile(r"gate:\s+([a-z0-9]+(?:-[a-z0-9]+)*)\s+tripped\b")


# --------------------------------------------------------------------------
# Seams / readers -- each takes its input as a parameter so every guard can be
# pointed at a planted known-bad sample.
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
    """Lines from the ``exit codes:`` heading to the end of the help text."""
    lines = help_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == EXIT_CODES_SECTION:
            return lines[index:]
    return []


def _epilog_entries(help_text: str) -> dict[int, str]:
    """Parse the epilog block into ``code -> meaning`` text.

    An entry starts on a line whose first non-whitespace token is a digit; any
    other non-blank line in the block continues the entry above it.
    """
    entries: dict[int, str] = {}
    current: int | None = None
    for line in _epilog_block(help_text)[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^(\d+)\s+(\S.*)$", stripped)
        if match is not None:
            current = int(match.group(1))
            entries[current] = match.group(2).strip()
        elif current is not None:
            entries[current] = f"{entries[current]}\n{stripped}"
    return entries


def _epilog_codes_in_order(help_text: str) -> list[int]:
    """The first-token codes of the epilog block, in rendered order."""
    codes: list[int] = []
    for line in _epilog_block(help_text)[1:]:
        match = re.match(r"^(\d+)\s+\S", line.strip())
        if match is not None:
            codes.append(int(match.group(1)))
    return codes


def _docstring_bullets(doc: str) -> dict[int, str]:
    """``main.__doc__``'s ``* ``N`` ...`` code bullets, code -> joined text.

    Indentation-AGNOSTIC by construction: the text is normalised with
    ``inspect.cleandoc`` (3.13 strips a docstring's common indent and 3.12 does
    not) and a continuation is any indented non-bullet line (``^\\s+\\S``).
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


def _code1_producers(source_text: str) -> tuple[str, ...]:
    """CLI flags that route to exit 1's fail-closed branch, derived from source.

    Takes the source as a PARAMETER rather than importing the module, so the
    growth and comment-immunity controls can feed it a synthetic sample.

    WHY AN AST WALK AND NOT A TEXT SCAN: ``ast.parse`` discards comments, so
    repo prose cannot inflate the guard, and walking string constants also
    reaches f-string literal parts -- which is how the live gate-unproven
    message is spelled.  Returned SORTED so every consumer is deterministic.
    """
    flags = {
        match.group(1)
        for node in ast.walk(ast.parse(source_text))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for match in UNPROVEN_LITERAL_RE.finditer(node.value)
    }
    return tuple(sorted(flags))


def _code5_producers(source_text: str) -> tuple[str, ...]:
    """The exit-5 producer set, derived the same way (behavior 9 only)."""
    flags = {
        f"--{match.group(1)}"
        for node in ast.walk(ast.parse(source_text))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for match in GATE_LITERAL_RE.finditer(node.value)
    }
    return tuple(sorted(flags))


def _missing_producers(surface_text: str, producers: tuple[str, ...]) -> list[str]:
    """Producers absent from one surface's text, in derived order."""
    return [flag for flag in producers if flag not in surface_text]


def _assert_surface_names_every_producer(
    surface: str, surface_text: str, producers: tuple[str, ...] = ()
) -> None:
    """Fail NAMING the absent flag, so a drifted surface localises the offender.

    A count alone ("2 of 3") tells a contributor that something is undocumented
    but not WHICH gate, and the exit code is the only thing a wrapper script
    sees.
    """
    wanted = producers or CODE1_PRODUCERS
    missing = _missing_producers(surface_text, wanted)
    assert not missing, (
        f"{surface} omits {', '.join(missing)} -- exit code 1 has "
        f"{len(wanted)} gate-unproven producer(s) derived from cli.py "
        f"({', '.join(wanted)}), and the code is all a script sees, so every "
        f"route to it must be named on every published surface; got "
        f"{surface_text!r}"
    )


def _is_literal_one(node: ast.expr | None) -> bool:
    """``True`` for the integer constant 1 only.

    ``type(...) is int`` rather than ``isinstance``: ``True == 1`` in Python, so
    an ``isinstance``-based census also counts every ``return True`` -- which
    over-reports and would red a correct tree.
    """
    return (
        isinstance(node, ast.Constant)
        and type(node.value) is int
        and node.value == 1
    )


def _exit1_routes(source_text: str) -> tuple[str, ...]:
    """Every literal exit-1 route, as sorted enclosing FUNCTION names.

    Counts ``return 1``, ``sys.exit(1)`` / ``os._exit(1)`` and
    ``raise SystemExit(1)``, so the census cannot be sidestepped by swapping one
    spelling for another.  Reports function names and NEVER line numbers: line
    anchors drift on every edit above them.
    """
    tree = ast.parse(source_text)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing(node: ast.AST) -> str:
        cursor = parents.get(node)
        while cursor is not None:
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cursor.name
            cursor = parents.get(cursor)
        return "<module>"

    routes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and _is_literal_one(node.value):
            routes.append(enclosing(node))
        elif isinstance(node, ast.Call) and node.args:
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in {"exit", "_exit"} and _is_literal_one(node.args[0]):
                routes.append(enclosing(node))
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            name = getattr(node.exc.func, "attr", None) or getattr(
                node.exc.func, "id", None
            )
            if name == "SystemExit" and node.exc.args and _is_literal_one(node.exc.args[0]):
                routes.append(enclosing(node))
    return tuple(sorted(routes))


def _head_blob(relpath: str) -> str:
    """The committed text of a tracked file, for a no-drift comparison."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO), "show", f"HEAD:{relpath}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:  # pragma: no cover - git absent
        pytest.skip("git is unavailable, so the HEAD blob cannot be read")
    if proc.returncode != 0:  # pragma: no cover - shallow/odd checkout
        pytest.skip(f"HEAD:{relpath} is unreadable: {proc.stderr.strip()!r}")
    return proc.stdout


# DERIVED, never written down.  Measured on the shipped tree: ('--fail-on-kind',).
CODE1_PRODUCERS = _code1_producers(CLI_SOURCE.read_text(encoding="utf-8"))
CODE5_PRODUCERS = _code5_producers(CLI_SOURCE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Behavior 1 -- the rendered epilog's code-1 text names the producer flag
# --------------------------------------------------------------------------


def test_b01_epilog_code1_entry_names_the_gate_unproven_producer() -> None:
    entries = _epilog_entries(_capture_help(["--help"]))
    assert 1 in entries, "the `exit codes:` epilog does not document exit code 1"
    _assert_surface_names_every_producer(
        "the `exit codes:` epilog of `pla --help`", entries[1]
    )


# --------------------------------------------------------------------------
# Behavior 2 -- main.__doc__'s code-1 bullet names the producer flag
# --------------------------------------------------------------------------


def test_b02_docstring_code1_bullet_names_the_gate_unproven_producer() -> None:
    doc = main.__doc__
    assert doc, "cli.main has no docstring, so its exit-code contract is unpublished"
    bullets = _docstring_bullets(doc)
    assert 1 in bullets, "cli.main's docstring does not document exit code 1"
    _assert_surface_names_every_producer("cli.main's docstring code-1 bullet", bullets[1])


def test_b02_docstring_reader_is_indentation_independent() -> None:
    """3.13 strips a docstring's common indent and 3.12 does not."""
    body = (
        "Header.\n\n"
        "* ``1`` -- fault, or a gate that could not be proven: a collector\n"
        "  armed with ``--fail-on-kind`` degraded, so it fails closed.\n"
        "* ``2`` -- nothing to act on.\n"
    )
    flat = _docstring_bullets(body)
    indented = _docstring_bullets(
        "".join(f"    {line}" if line.strip() else line for line in body.splitlines(True))
    )
    assert flat == indented, (
        "the docstring reader must not depend on the common indent; "
        f"flat={flat!r} indented={indented!r}"
    )
    assert "--fail-on-kind" in flat[1] and "closed" in flat[1]


# --------------------------------------------------------------------------
# Behavior 3 -- all three surfaces say the route fails CLOSED, not that it faulted
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "surface",
    ["epilog", "docstring", "readme"],
)
def test_b03_every_code1_surface_says_the_gate_fails_closed(surface: str) -> None:
    doc = main.__doc__ or ""
    texts = {
        "epilog": _epilog_entries(_capture_help(["--help"])).get(1, ""),
        "docstring": _docstring_bullets(doc).get(1, ""),
        "readme": _readme_exit_code_rows(README.read_text(encoding="utf-8")).get(1, ""),
    }
    text = texts[surface]
    assert text, f"the {surface} publishes no code-1 text"
    assert "closed" in text, (
        f"the {surface}'s code-1 text must say the gate fails `closed`, or the "
        "new clause reads as a crash -- which is the exact misreading this "
        f"contract exists to prevent; got {text!r}"
    )


# --------------------------------------------------------------------------
# Behavior 4 -- the producer set is DERIVED from cli.py, not written down here
# --------------------------------------------------------------------------


def test_b04_producer_set_is_derived_from_cli_source() -> None:
    assert CODE1_PRODUCERS == ("--fail-on-kind",), (
        "exit code 1's gate-unproven producer set, derived from cli.py string "
        f"constants, must be exactly ('--fail-on-kind',); got {CODE1_PRODUCERS!r}"
    )


# --------------------------------------------------------------------------
# Behavior 5 -- that derivation is two-sided on synthetic input
# --------------------------------------------------------------------------


def test_b05_derivation_grows_when_a_second_gate_literal_ships() -> None:
    grown = _code1_producers(
        'a = "error: --fail-on-kind gate unproven -- x"\n'
        'b = f"error: --fail-over gate unproven -- {n}"\n'
    )
    assert grown == ("--fail-on-kind", "--fail-over"), (
        f"a second gate-unproven literal must enter the set, sorted; got {grown!r}"
    )


def test_b05_derivation_ignores_a_gate_named_only_in_a_comment() -> None:
    assert _code1_producers("# error: --fail-over gate unproven -- prose\nx = 1\n") == (), (
        "ast.parse discards comments, so repo prose must not inflate the guard"
    )


def test_b05_derivation_is_empty_without_the_announcement_literal() -> None:
    assert _code1_producers('x = "error: something else entirely"\n') == ()


def test_b05_derivation_rejects_a_malformed_flag() -> None:
    """A trailing hyphen is not a flag any CLI surface could match."""
    assert _code1_producers('x = "error: --fail-over- gate unproven"\n') == ()


# --------------------------------------------------------------------------
# Behavior 6 -- each surface guard fails and NAMES the absent producer
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("surface", "getter"),
    [
        ("the `exit codes:` epilog of `pla --help`", "epilog"),
        ("cli.main's docstring code-1 bullet", "docstring"),
        ("README's `### Exit codes` row 1", "readme"),
    ],
)
def test_b06_each_surface_guard_is_two_sided_and_localises_the_offender(
    surface: str, getter: str
) -> None:
    doc = main.__doc__ or ""
    texts = {
        "epilog": _epilog_entries(_capture_help(["--help"])).get(1, ""),
        "docstring": _docstring_bullets(doc).get(1, ""),
        "readme": _readme_exit_code_rows(README.read_text(encoding="utf-8")).get(1, ""),
    }
    shipped = texts[getter]
    assert shipped, f"{surface} publishes no code-1 text"

    # Positive leg: the shipped text is complete.
    assert _missing_producers(shipped, CODE1_PRODUCERS) == []
    _assert_surface_names_every_producer(surface, shipped)

    # Negative leg: a copy with the producer deleted must fail, and the message
    # must localise BOTH the surface and the flag -- a count alone is not enough.
    damaged = shipped.replace("--fail-on-kind", "--redacted")
    assert damaged != shipped, "the two-sided control did not modify the sample"
    assert _missing_producers(damaged, CODE1_PRODUCERS) == ["--fail-on-kind"]
    with pytest.raises(AssertionError) as excinfo:
        _assert_surface_names_every_producer(surface, damaged)
    message = str(excinfo.value)
    assert surface in message and "--fail-on-kind" in message, (
        "a drifted surface must be localised by name in the failure message; "
        f"got {message!r}"
    )


# --------------------------------------------------------------------------
# Behavior 7 -- the literal exit-1 route census, by enclosing FUNCTION name
# --------------------------------------------------------------------------


def test_b07_cli_has_exactly_two_literal_exit_1_routes_named_by_function() -> None:
    routes = _exit1_routes(CLI_SOURCE.read_text(encoding="utf-8"))
    assert set(routes) == {"main", "_cmd_signals"}, (
        "cli.py's literal exit-1 routes must be exactly {'main', '_cmd_signals'}; "
        f"got {routes!r}. A NEW exit-1 route has to be named on all three "
        "published surfaces (the `exit codes:` epilog, cli.main's docstring and "
        "the README table) before it ships -- the exit code is the only thing a "
        "wrapper script sees, so an unnamed route is an undocumented contract."
    )
    assert len(routes) == 2, f"expected 2 literal exit-1 routes; got {routes!r}"


def test_b07_census_excludes_boolean_true() -> None:
    """``True == 1`` in Python, so an isinstance-based census over-reports."""
    assert _exit1_routes("def p() -> bool:\n    return True\n") == (), (
        "`return True` is not an exit-1 route; the census must exclude bools"
    )


# --------------------------------------------------------------------------
# Behavior 8 -- the census is two-sided, so a pass cannot be an empty domain
# --------------------------------------------------------------------------


def test_b08_census_reports_zero_for_a_source_without_exit_1() -> None:
    assert _exit1_routes("def f() -> int:\n    return 5\n") == ()


def test_b08_census_grows_to_three_and_counts_every_spelling() -> None:
    grown = _exit1_routes(
        "import os, sys\n"
        "def main() -> int:\n    return 1\n"
        "def _cmd_signals() -> int:\n    sys.exit(1)\n"
        "def _third() -> int:\n    raise SystemExit(1)\n"
    )
    assert grown == ("_cmd_signals", "_third", "main"), (
        "the census must count return / sys.exit / raise SystemExit alike, "
        f"sorted by enclosing function; got {grown!r}"
    )
    assert _exit1_routes("import os\ndef f() -> None:\n    os._exit(1)\n") == ("f",)


# --------------------------------------------------------------------------
# Behavior 9 -- nothing about codes 0 and 2-5 changes
# --------------------------------------------------------------------------


def test_b09_epilog_still_publishes_exactly_six_codes_in_ascending_order() -> None:
    codes = _epilog_codes_in_order(_capture_help(["--help"]))
    assert codes == EXPECTED_CODES, (
        f"the epilog must publish exactly {EXPECTED_CODES} in ascending order; "
        f"got {codes!r}"
    )


def test_b09_code5_entry_still_names_all_three_producers_on_all_surfaces() -> None:
    assert len(CODE5_PRODUCERS) == 3, (
        f"exit code 5's derived producer set must still be 3; got {CODE5_PRODUCERS!r}"
    )
    doc = main.__doc__ or ""
    surfaces = {
        "the `exit codes:` epilog of `pla --help`": _epilog_entries(
            _capture_help(["--help"])
        ).get(5, ""),
        "cli.main's docstring code-5 bullet": _docstring_bullets(doc).get(5, ""),
        "README's `### Exit codes` row 5": _readme_exit_code_rows(
            README.read_text(encoding="utf-8")
        ).get(5, ""),
    }
    for surface, text in surfaces.items():
        assert text, f"{surface} publishes no code-5 text"
        missing = _missing_producers(text, CODE5_PRODUCERS)
        assert not missing, f"{surface} lost exit-5 producer(s) {missing!r}"


def test_b09_readme_rows_for_codes_0_and_2_to_5_are_unchanged() -> None:
    worktree = _readme_exit_code_rows(README.read_text(encoding="utf-8"))
    committed = _readme_exit_code_rows(_head_blob("README.md"))
    assert committed, "HEAD's README publishes no exit-code table to compare against"
    for code in (0, 2, 3, 4, 5):
        assert worktree.get(code) == committed.get(code), (
            f"README exit-code row {code} changed -- this iteration edits contract "
            "TEXT for code 1 only, and the README's code-1 row was already correct, "
            "so no README row may move"
        )


def test_b09_sibling_exit5_oracle_is_not_edited() -> None:
    committed = _head_blob(SIBLING_ORACLE)
    assert committed, f"HEAD:{SIBLING_ORACLE} is empty"
    assert (REPO / SIBLING_ORACLE).read_text(encoding="utf-8") == committed, (
        f"{SIBLING_ORACLE} must ship unchanged: this module carries its own local "
        "readers precisely so the exit-5 oracle never has to be touched"
    )


# --------------------------------------------------------------------------
# Behavior 10 -- the grown epilog stays width-independent and inside 80 columns
# --------------------------------------------------------------------------


def test_b10_epilog_lines_fit_80_columns_and_never_split_a_flag() -> None:
    block = _epilog_block(_capture_help(["--help"]))
    assert block, "no `exit codes:` section to measure"
    too_wide = [line for line in block if len(line) > MAX_EPILOG_WIDTH]
    assert not too_wide, (
        f"epilog lines must fit {MAX_EPILOG_WIDTH} columns, because a raw "
        "formatter will not re-wrap them on a narrow terminal; over-long: "
        f"{[(len(line), line) for line in too_wide]}"
    )
    for flag in (*CODE1_PRODUCERS, *CODE5_PRODUCERS):
        assert any(flag in line for line in block), (
            f"{flag!r} does not appear intact on any single epilog line, so the "
            "wrap split it and a reader searching for the flag will not find it"
        )


def test_b10_epilog_continuations_stay_indented_and_never_start_a_digit() -> None:
    help_text = _capture_help(["--help"])
    block = _epilog_block(help_text)
    assert block, "no `exit codes:` section to parse"
    entry_texts = _epilog_entries(help_text)
    assert entry_texts, "the epilog parsed to zero entries"
    continuations = 0
    for line in block[1:]:
        stripped = line.strip()
        if not stripped or re.match(r"^\d+\s+\S", stripped):
            continue
        continuations += 1
        assert not stripped[:1].isdigit(), (
            "a continuation line in the exit-codes epilog begins with a digit, "
            f"so a future meaning could be mis-parsed as a seventh code: {line!r}"
        )
        assert line[:1].isspace(), (
            f"a continuation line must stay indented under its code: {line!r}"
        )
    assert continuations >= 5, (
        "expected the wrapped meanings to produce continuation lines; the "
        f"precondition is vacuous if there are none (found {continuations})"
    )


@pytest.mark.parametrize("columns", ["40", "200"])
def test_b10_epilog_block_is_byte_identical_across_terminal_widths(
    monkeypatch: pytest.MonkeyPatch, columns: str
) -> None:
    monkeypatch.setenv("COLUMNS", "80")
    baseline = "\n".join(_epilog_block(_capture_help(["--help"])))
    assert baseline, "no `exit codes:` section rendered at COLUMNS=80"
    monkeypatch.setenv("COLUMNS", columns)
    rendered = "\n".join(_epilog_block(_capture_help(["--help"])))
    assert rendered == baseline, (
        f"the exit-codes block must be byte-identical at COLUMNS={columns} -- a "
        "re-wrapped meaning would break the one-entry-per-line contract the "
        "code-1 parse depends on"
    )
