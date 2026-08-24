"""Black-box behavior tests for state-dir iteration 227 (ships as ``factory iter 201``).

Feature under test: the README ``### Exit codes`` preamble now names the top-level
``pla --help`` epilog as the DURABLE machine-readable exit-code surface, and
demotes ``proactive_loop.cli.main.__doc__`` (and the README table itself) to prose
derivations -- because ``python -OO`` strips docstrings, so the previously-named
surface is EMPTY in exactly the lean scripted invocation most likely to branch on
an exit code.  ``src/`` is unchanged; this iteration corrects the prose that
describes code written 49 factory iterations ago, and adds the durability oracle
that was missing.

MODULE NAME -- DERIVED FROM THE REPO, NEVER FROM A COUNTER.  Three counters
disagree this iteration: the state dir is ``iter-227``, the newest commit is
``factory iter 200`` (so this ships as 201), and the highest tracked
``tests/test_iterNN_behavior.py`` is 203.  Naming a module after either iteration
counter would SILENTLY OVERWRITE a shipped green oracle (the iter-172 / iter-186
destroyed-oracle failures).  So the name is derived: highest tracked module 203 +
1 = 204, and ``git cat-file -e HEAD:tests/test_iter204_behavior.py`` was proved to
exit 128 -- and the working-tree path proved absent -- before a byte was written.

ISOLATION CONTRACT (honored): every assertion is written against this iteration's
spec ("Expected Behaviors" in ``pm.md``), the published ``README.md``, the repo's
own ``tests/`` conventions, and the product's OBSERVABLE output obtained by
RUNNING it.  **No file under ``src/`` was read, no engineer's or reviewer's note
was consulted, and no ``git diff`` was inspected.**

WHY REAL SUBPROCESSES, AND ONLY TWO OF THEM.  Behaviors 4 and 5 are claims about
what survives ``python -OO``, and an in-process run cannot falsify them: this
interpreter is not running at optimization level 2 and cannot retroactively
discard the docstrings it already compiled.  So those two behaviors spend real
``[sys.executable, "-OO", ...]`` subprocesses (measured 0.19s and 0.10s each),
rooted at the repo with ``cwd=REPO``, never a bare ``python``.  Every other
behavior is a text read or an in-process ``main([...])`` capture (the
iter-117 / iter-152 convention).

TWO-SIDED BY CONSTRUCTION.  Behavior 5 is the control that keeps behavior 4 from
being vacuous -- it proves the demoted surface really is empty under ``-OO``,
measured 0 chars against 2193 under a normal interpreter.  Behavior 9 fires both
of this module's readers at planted known-bad samples, because a reader that
silently sees nothing would make every guard above pass while reporting nothing.

Offline and deterministic: no network, no API key, no clock, no provider.  Nothing
is written anywhere -- every subprocess is read-only ``--help`` / ``-c`` and every
other assertion reads a tracked artifact.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

from proactive_loop.cli import main
from tests import test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"

EXIT_HEADING = "### Exit codes"
EXIT_CODES_SECTION = "exit codes:"
EXPECTED_CODES = (0, 1, 2, 3, 4, 5)

# The human-owned intro marker is matched on this LOOSE distinctive prefix on
# purpose: README.md spells the full marker with an EM DASH, so a retyped
# ``PORTFOLIO INTRO -- human-owned`` finds nothing and every ``find()``
# comparison below would pass trivially at -1 (the iter-227 reviewer's own
# fail-open).  Same convention as tests/test_iter143_behavior.py:78.
MARKER = "PORTFOLIO INTRO"

# The sentence the preamble must no longer contain (behavior 2).
RETIRED_CLAIM = "The contract lives in the docstring of"

# Words that would re-promote the docstring to the authoritative surface
# (behavior 3).  Checked case-insensitively over the region only.
PROMOTION_WORDS = ("authoritative", "canonical", "primary")

# Behavior 10: the floor the guard's own derivation rule dictates for the live
# count, i.e. ``live // 100 * 100``.  Not chosen -- computed.
PUBLISHED_FLOOR = 5100


# --------------------------------------------------------------------------- #
# Readers.  Each is fail-closed and each is fired at a planted known-bad
# sample by behavior 9, so it can never make a guard pass by seeing nothing.
# --------------------------------------------------------------------------- #


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _region(text: str, heading: str = EXIT_HEADING) -> str:
    """Text from ``heading`` up to the next ``##``/``###`` heading, inclusive.

    FAIL-CLOSED: raises when ``heading`` is absent instead of returning ``""``.
    An empty return would satisfy every ``not in`` assertion in this module.
    Raised explicitly rather than via ``assert`` so the guard survives ``-OO``,
    which is the very optimization level this module is about.
    """
    start = text.find(heading)
    if start < 0:
        raise AssertionError(f"heading {heading!r} not found -- extractor is vacuous")
    rest = text[start + len(heading) :]
    match = re.search(r"^#{2,3} ", rest, flags=re.MULTILINE)
    end = len(rest) if match is None else match.start()
    return heading + rest[:end]


def _epilog_block(help_text: str) -> list[str]:
    """Lines from the ``exit codes:`` heading to the end of ``help_text``.

    Returns ``[]`` when the heading is absent, so a caller can assert on the
    ABSENCE (behavior 8) rather than catch an exception.  Every caller that
    needs presence asserts the block is non-empty first.
    """
    lines = help_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == EXIT_CODES_SECTION:
            return lines[index:]
    return []


def _epilog_first_tokens(help_text: str) -> list[str]:
    """First whitespace-separated token of each non-blank line UNDER the heading.

    The spec states behavior 4 in exactly these terms ("a line whose first
    whitespace-separated token is that code"), so the reader is deliberately
    dumber than a code/meaning parser: it makes no claim about continuations.
    """
    block = _epilog_block(help_text)
    return [line.split()[0] for line in block[1:] if line.split()]


def _table_codes(region: str) -> list[int]:
    """First-column integers of the pipe table inside ``region``, in order."""
    codes: list[int] = []
    for line in region.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and re.fullmatch(r"\d+", cells[0]):
            codes.append(int(cells[0]))
    return codes


def _table_rows(region: str) -> list[tuple[int, str]]:
    """``(code, meaning)`` data rows of the pipe table inside ``region``."""
    rows: list[tuple[int, str]] = []
    for line in region.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) >= 2 and re.fullmatch(r"\d+", cells[0]):
            rows.append((int(cells[0]), cells[1]))
    return rows


def _docstring_codes(doc: str) -> set[int]:
    """Codes enumerated by ``main.__doc__``, indentation-agnostically.

    Normalised with ``inspect.cleandoc`` because 3.13 strips the common leading
    docstring indent at compile time and 3.12 does not (the iter-152 lesson).
    """
    text = inspect.cleandoc(doc)
    return {int(m) for m in re.findall(r"^\s*\*\s+``(\d+)``", text, flags=re.MULTILINE)}


def _intro(text: str) -> str:
    """The human-owned portfolio intro: everything ABOVE the marker."""
    index = text.find(MARKER)
    if index < 0:
        raise AssertionError("README lost its PORTFOLIO INTRO marker")
    return text[:index]


def _capture_help(argv: list[str]) -> str:
    """Run the public CLI in-process and return stdout, asserting exit 0."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
    assert excinfo.value.code == 0, (
        f"pla {' '.join(argv)} must exit 0; got {excinfo.value.code!r}"
    )
    return buf.getvalue()


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """One read-only interpreter subprocess rooted at the repo."""
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


# --------------------------------------------------------------------------- #
# Behavior 1 -- the preamble names the top-level `pla --help` epilog
# --------------------------------------------------------------------------- #


def test_b01_preamble_names_the_top_level_pla_help_epilog() -> None:
    region = _region(_readme())
    assert "pla --help" in region, (
        "the ### Exit codes preamble must name `pla --help` as the durable "
        f"machine-readable surface; region is:\n{region}"
    )


def test_b01_the_named_surface_is_described_as_surviving_the_optimizer() -> None:
    """The mention is not incidental: the region ties `pla --help` to ``-OO``."""
    region = _region(_readme())
    assert "pla --help" in region and "-OO" in region, region
    lowered = region.lower()
    assert "strip" in lowered or "empt" in lowered, (
        "the region names -OO but never says what it does to a docstring"
    )


# --------------------------------------------------------------------------- #
# Behavior 2 -- the retired claim is gone from the WHOLE README
# --------------------------------------------------------------------------- #


def test_b02_readme_no_longer_claims_the_contract_lives_in_the_docstring() -> None:
    text = _readme()
    assert RETIRED_CLAIM not in text, (
        f"README.md still contains the retired claim {RETIRED_CLAIM!r}"
    )
    # The assertion above is only meaningful because the README is non-empty and
    # really is the file under test -- prove the reader is not looking at "".
    assert EXIT_HEADING in text and len(text) > 10_000, len(text)


# --------------------------------------------------------------------------- #
# Behavior 3 -- the docstring is still named, and named HONESTLY
# --------------------------------------------------------------------------- #


def test_b03_region_still_names_the_docstring_and_names_dash_oo() -> None:
    region = _region(_readme())
    assert "proactive_loop.cli.main" in region, (
        "the region must still tell a reader where the prose derivation lives"
    )
    assert "-OO" in region, "the region must say which optimization level strips it"


def test_b03_region_does_not_re_promote_the_docstring() -> None:
    """No superlative re-crowns the docstring as THE contract surface.

    AMBIGUITY (PM feedback): the spec says the region "does not describe the
    docstring as the primary, authoritative or canonical surface".  A semantic
    reading is not testable offline, so this takes the strictest defensible
    literal reading -- none of those three words occurs anywhere in the region.
    That is stronger than the spec requires (it would also reject "the epilog is
    authoritative", which the spec permits), and it is deliberately the reading
    that cannot pass vacuously.
    """
    lowered = _region(_readme()).lower()
    found = [word for word in PROMOTION_WORDS if word in lowered]
    assert found == [], f"the region re-promotes the docstring with {found}"
    assert "lives in the docstring" not in lowered, lowered


# --------------------------------------------------------------------------- #
# Behavior 4 -- the surface the preamble NAMES survives `python -OO`
# --------------------------------------------------------------------------- #


def test_b04_dash_oo_help_still_publishes_the_whole_exit_code_epilog() -> None:
    proc = _run(["-OO", "-m", "proactive_loop.cli", "--help"])
    assert proc.returncode == 0, (
        f"python -OO -m proactive_loop.cli --help exited {proc.returncode}; "
        f"stderr:\n{proc.stderr}"
    )
    block = _epilog_block(proc.stdout)
    assert block, (
        "no line whose stripped form is 'exit codes:' under -OO; stdout:\n"
        f"{proc.stdout}"
    )
    assert block[0].strip() == EXIT_CODES_SECTION, block[0]
    tokens = _epilog_first_tokens(proc.stdout)
    missing = [code for code in EXPECTED_CODES if str(code) not in tokens]
    assert missing == [], (
        f"codes {missing} have no line of their own under -OO; first tokens were "
        f"{tokens[:12]}"
    )


# --------------------------------------------------------------------------- #
# Behavior 5 -- the demoted surface really IS empty under `-OO` (the control
# that makes behavior 4 a proof rather than a coincidence)
# --------------------------------------------------------------------------- #


_DOC_LEN_PROBE = "import proactive_loop.cli as m; print(len(m.main.__doc__ or ''))"


def test_b05_the_demoted_docstring_is_empty_under_dash_oo() -> None:
    proc = _run(["-OO", "-c", _DOC_LEN_PROBE])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "0", (
        "main.__doc__ is expected to be EMPTY under -OO; the probe printed "
        f"{proc.stdout.strip()!r}"
    )


def test_b05_the_same_probe_under_a_normal_interpreter_is_substantial() -> None:
    """The other side of the control: the docstring exists when not optimized.

    Without this, behavior 5 would also pass if the probe were simply broken.
    """
    proc = _run(["-c", _DOC_LEN_PROBE])
    assert proc.returncode == 0, proc.stderr
    length = int(proc.stdout.strip())
    assert length > 500, (
        f"main.__doc__ is only {length} chars unoptimized -- the -OO result is "
        "not evidence of anything"
    )


# --------------------------------------------------------------------------- #
# Behavior 6 -- the pre-existing three-surface code-SET agreement is preserved,
# and the six table rows were NOT edited
# --------------------------------------------------------------------------- #


def test_b06_all_three_surfaces_still_publish_the_same_code_set() -> None:
    epilog = {int(t) for t in _epilog_first_tokens(_capture_help(["--help"])) if t.isdigit()}
    docstring = _docstring_codes(main.__doc__ or "")
    table = set(_table_codes(_region(_readme())))
    expected = set(EXPECTED_CODES)
    assert epilog == expected, f"epilog codes {sorted(epilog)} != 0-5"
    assert docstring == expected, f"main.__doc__ codes {sorted(docstring)} != 0-5"
    assert table == expected, f"README table codes {sorted(table)} != 0-5"


def test_b06_the_table_still_has_six_rows_with_real_meanings() -> None:
    rows = _table_rows(_region(_readme()))
    assert [code for code, _ in rows] == list(EXPECTED_CODES), rows
    for code, meaning in rows:
        # Deliberately NOT a length floor: row 0's published meaning really is
        # "Success." (8 chars), so a `len(meaning) > 20` threshold is a
        # fail-CLOSED bug in the oracle rather than a defect in the table.
        assert re.search(r"[A-Za-z]", meaning), f"row {code} lost its meaning"
        assert meaning.endswith("."), f"row {code} meaning is truncated: {meaning!r}"


def test_b06_the_table_rows_are_byte_identical_to_head() -> None:
    """This iteration is prose-only: no table row may move.

    NOTE (self-limiting, by design): once the shipping commit lands, ``HEAD``
    carries this same README and the comparison is tautological -- exactly like
    ``tests/test_iter143_behavior.py``'s HEAD-intro guard.  Its value is in the
    pre-commit window, where it is the only mechanical check that the six rows
    survived a preamble rewrite untouched.
    """
    proc = subprocess.run(
        ["git", "show", "HEAD:README.md"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip("HEAD:README.md unavailable")
    head_rows = _table_rows(_region(proc.stdout))
    assert head_rows, "the HEAD reader found no table -- comparison would be vacuous"
    assert _table_rows(_region(_readme())) == head_rows, (
        "the six exit-code table rows are out of scope for this iteration"
    )


# --------------------------------------------------------------------------- #
# Behavior 7 -- placement is unchanged
# --------------------------------------------------------------------------- #


def test_b07_exactly_one_level_three_exit_codes_heading() -> None:
    text = _readme()
    headings = [
        line for line in text.splitlines() if line.strip().startswith("### Exit codes")
    ]
    assert len(headings) == 1, headings
    assert headings[0] == EXIT_HEADING, (
        f"the heading must stay a bare level-3 heading; got {headings[0]!r}"
    )
    assert text.count(EXIT_HEADING) == 1, text.count(EXIT_HEADING)


def test_b07_the_section_still_sits_inside_the_cli_section() -> None:
    text = _readme()
    index = text.find(EXIT_HEADING)
    assert index > 0
    preceding = [
        line
        for line in text[:index].splitlines()
        if re.fullmatch(r"## \S.*", line)
    ]
    assert preceding, "no level-2 heading precedes ### Exit codes"
    assert preceding[-1] == "## CLI", (
        f"### Exit codes moved out of ## CLI, into {preceding[-1]!r}"
    )


def test_b07_the_section_stays_below_the_single_human_owned_marker() -> None:
    text = _readme()
    marker_index = text.find(MARKER)
    heading_index = text.find(EXIT_HEADING)
    # Assert both are FOUND before comparing: `str.find` returns -1, so
    # comparing two misses passes trivially (the iter-227 reviewer's fail-open).
    assert marker_index >= 0, "README lost its PORTFOLIO INTRO marker"
    assert heading_index >= 0, "README lost its ### Exit codes heading"
    assert text.count(MARKER) == 1, f"{text.count(MARKER)} intro markers"
    assert heading_index > marker_index, (
        f"### Exit codes (byte {heading_index}) is ABOVE the human-owned marker "
        f"(byte {marker_index})"
    )


# --------------------------------------------------------------------------- #
# Behavior 8 -- the epilog stays top-level only, and the region does not send a
# reader to a per-verb `--help`
# --------------------------------------------------------------------------- #


def test_b08_subcommand_help_still_carries_no_exit_code_epilog() -> None:
    assert _epilog_block(_capture_help(["signals", "--help"])) == [], (
        "the exit-codes epilog must stay top-level only"
    )
    # Two-sided: the same reader DOES find the block on the top-level help, so
    # the emptiness above is a property of `signals --help`, not of the reader.
    assert _epilog_block(_capture_help(["--help"])), "reader is broken, not the verb"


def test_b08_region_points_only_at_the_top_level_help() -> None:
    region = _region(_readme())
    stray = [
        m.start()
        for m in re.finditer(r"--help", region)
        if not region[max(0, m.start() - 4) : m.start()].endswith("pla ")
    ]
    assert stray == [], (
        "every --help mentioned in the region must be the top-level `pla --help`; "
        f"stray offsets {stray} in:\n{region}"
    )


# --------------------------------------------------------------------------- #
# Behavior 9 -- the new oracle is FAIL-CLOSED: every reader this module defines
# is fired at a planted known-bad sample and must report the defect
# --------------------------------------------------------------------------- #


def test_b09_region_extractor_refuses_a_sample_with_no_heading() -> None:
    with pytest.raises(AssertionError):
        _region("# README\n\nno exit-code section here at all\n")


def test_b09_region_extractor_stops_at_the_next_heading() -> None:
    sample = (
        "### Exit codes\n\nmine: pla --help\n\n### Next section\n\npla other --help\n"
    )
    region = _region(sample)
    assert "pla --help" in region
    assert "pla other --help" not in region, (
        "the extractor bled into the next section -- behavior 8's stray-help "
        "check would be measuring the wrong text"
    )


def test_b09_intro_reader_refuses_a_readme_with_no_marker() -> None:
    with pytest.raises(AssertionError):
        _intro("# README\n\nno human-owned marker here\n")


def test_b09_epilog_reader_reports_a_missing_heading_and_a_missing_code() -> None:
    assert _epilog_block("usage: pla\n\noptions:\n  -h\n") == []
    assert _epilog_first_tokens("usage: pla\n\noptions:\n  -h\n") == []
    # Heading present but a code silently dropped: the reader must NOT invent it.
    planted = "usage: pla\n\nexit codes:\n  0  ok\n  1  fault\n"
    tokens = _epilog_first_tokens(planted)
    assert tokens == ["0", "1"], tokens
    missing = [c for c in EXPECTED_CODES if str(c) not in tokens]
    assert missing == [2, 3, 4, 5], (
        "the epilog reader cannot detect a dropped code, so behavior 4 would "
        f"pass vacuously; it reported {missing}"
    )


def test_b09_table_reader_reports_a_dropped_row() -> None:
    planted = (
        "### Exit codes\n\n| Code | Meaning |\n|------|---------|\n"
        "| 0 | Success. |\n| 1 | Fault. |\n"
    )
    assert _table_codes(planted) == [0, 1]
    assert _table_codes("### Exit codes\n\nno table at all\n") == []


def test_b09_docstring_reader_reports_an_empty_docstring() -> None:
    assert _docstring_codes("") == set()
    assert _docstring_codes("no bullets here") == set()
    assert _docstring_codes("* ``0`` ok\n* ``1`` fault\n") == {0, 1}


# --------------------------------------------------------------------------- #
# Behavior 10 -- the README suite-size floor is corrected in the SAME commit
# --------------------------------------------------------------------------- #


def test_b10_both_intro_claims_publish_the_corrected_floor() -> None:
    intro = _intro(_readme())
    assert "**5,100+ tests**" in intro, intro[-1500:]
    assert "**5,100+ passing tests**" in intro, intro[-1500:]
    assert "5,000" not in intro, "the stale floor token survives in the intro"


def test_b10_the_guard_reports_no_suite_size_problem_for_the_live_count() -> None:
    intro = _intro(_readme())
    live = guard.collect_live_test_count()
    assert isinstance(live, int) and live > 0, live
    assert live // 100 * 100 == PUBLISHED_FLOOR, (
        f"{live} tests collect, so the published floor must be "
        f"{live // 100 * 100}, not {PUBLISHED_FLOOR}"
    )
    assert guard.suite_size_problems(intro, live) == [], (
        guard.suite_size_problems(intro, live)
    )


def test_b10_the_floor_claim_is_still_two_sided() -> None:
    """A floor that cannot be wrong is decoration -- prove the guard bites."""
    intro = _intro(_readme())
    assert guard.suite_size_problems(intro, PUBLISHED_FLOOR - 1) != [], (
        "a live count BELOW the published floor makes the claim false and must "
        "be reported"
    )
    assert guard.suite_size_problems(intro, PUBLISHED_FLOOR + guard.SUITE_SIZE_SLACK) != [], (
        "a live count a full slack above the floor is stale and must be reported"
    )
