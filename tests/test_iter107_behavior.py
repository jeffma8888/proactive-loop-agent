"""Behavior tests for state-dir iteration 100 (ships as commit-seq ``factory iter 107``).

Feature under test: the README's ``## CLI`` reference documents every live CLI
long option and every live verb, and a BIDIRECTIONAL drift guard makes that
permanent -- an undocumented live flag fails, and a documented flag that exists
on no parser (a "ghost") fails too.

Why this file is deliberately redundant
---------------------------------------
Every derivation here (the flag universe, the section extractor, and the three
guard helpers) is re-implemented INDEPENDENTLY of the shipped guard, from the
spec's Expected Behaviors rather than from the shipped code. The two
implementations then act as cross-checking oracles over the same ``README.md``:
if the shipped guard is subtly wrong (a too-generous exemption, a regex that
matches nothing, a section extractor that silently returns ``""``), these tests
still fail on the real file. The last test pins the SHIPPED helpers against
these independent results, because the shipped ones are what CI runs.

Black-box: the only seams used are ``proactive_loop.cli.build_parser()``,
``proactive_loop.collectors.all_collectors()``, argparse introspection of the
live parser, and the on-disk ``README.md``. No ``src/`` module was read while
writing it.

Offline: reads one file and imports the package. No network, no subprocess.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
# The marker comment is spelled with an EM DASH ("PORTFOLIO INTRO - human-owned"
# rendered with U+2014), so match on the ASCII-safe prefix the shipped guard
# uses; the full line is asserted separately in behavior 8.
MARKER = "PORTFOLIO INTRO"
CLI_HEADING = "## CLI"

# argparse injects ``--help`` into all 16 parsers; the reference documents the
# verbs, not 15 identical help flags (spec behavior 3).
EXEMPT_FLAGS = frozenset({"--help"})

# Long options the reference teaches through a short alias instead. Without
# this, the real section (which has ``-v``/``-vv`` and never the literal string
# ``--verbose``) would report one false failure covering all 15 verbs at once
# (spec behavior 2).
SHORT_FORMS: dict[str, tuple[str, ...]] = {"--verbose": ("-v",)}

# A ``--flag``-shaped token: stops at the first char that cannot be part of an
# option name, so ``--out PATH`` yields ``--out``.
FLAG_TOKEN = re.compile(r"--[A-Za-z][A-Za-z0-9-]*")

# The COMPLETE census of ``--``-shaped tokens the README publishes that no parser
# could accept, because they are not `pla` options at all. Derived independently
# here (this module never imports the shipped constants) and pinned as an EXACT
# list, never folded into ``EXEMPT_FLAGS``: a FOURTH such token must fail.
#   ``--first-success``  shields.io dash escaping in the Offline badge, inside
#                        the human-owned intro (behavior 6).
#   ``--locked``         the Quickstart's ``uv sync --locked`` -- a `uv` flag,
#                        below the marker, and the thing that makes the install
#                        line true (a bare ``uv sync`` may mutate ``uv.lock``).
#   ``--no-verify``      the "Pre-commit hook (opt-in)" section names git's own
#                        escape hatch, ``git commit --no-verify`` -- a `git`
#                        flag, below the marker, and the documented way past a
#                        hook that fails CLOSED when the CLI cannot be resolved.
FOREIGN_FLAG_TOKENS = ["--first-success", "--locked", "--no-verify"]

# The 7 verb/flag pairs the spec requires on the ROW THAT OWNS THEM (behavior 9);
# 4 of them are REQUIRED arguments, so an omission makes the documented command
# exit 2.
REQUIRED_PAIRS: tuple[tuple[str, str], ...] = (
    ("dispatch", "--slate"),
    ("explain", "--slate"),
    ("resume", "--run-dir"),
    ("trace", "--run-dir"),
    ("run", "--dry-run"),
    ("scan", "--out"),
    ("signals", "--min-weight"),
)

# Phrasings that would misdescribe ``--dry-run`` (behavior 10): it DOES write
# the slate; what it skips is the run dir and the loop iterations.
FALSE_DRY_RUN_PHRASINGS = (
    "no side effect",
    "without writing",
    "writes no slate",
    "writes nothing",
    "touches no disk",
    "no disk",
)


# --------------------------------------------------------------------------
# Independent derivations (spec definitions, not the shipped implementation)
# --------------------------------------------------------------------------


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def sub_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    actions = [
        a
        for a in parser._actions
        if isinstance(a, argparse._SubParsersAction)  # noqa: SLF001
    ]
    assert len(actions) == 1, f"expected one subparsers action, got {len(actions)}"
    return actions[0]


def long_options(parser: argparse.ArgumentParser) -> set[str]:
    return {
        opt
        for action in parser._actions
        for opt in action.option_strings
        if opt.startswith("--")
    }


def flag_universe() -> frozenset[str]:
    """Root parser UNION every subparser, minus ``--help`` (spec's FLAG UNIVERSE)."""
    parser = build_parser()
    universe = long_options(parser)
    for sub in sub_action(parser).choices.values():
        universe |= long_options(sub)
    return frozenset(universe - EXEMPT_FLAGS)


def live_verbs() -> tuple[str, ...]:
    return tuple(sub_action(build_parser()).choices)


def section_of(text: str, heading: str = CLI_HEADING) -> str:
    """The spec's CLI SECTION: ``heading`` up to (not including) the next ``## ``.

    Fails loudly instead of returning ``""`` when the heading is missing or
    duplicated: a silently-empty section makes the forward guard report all 24
    flags (unreadable) while the reverse guard reports nothing (silently blind).
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\n") == heading]
    assert len(starts) == 1, (
        f"expected exactly one {heading!r} heading in the document, found "
        f"{len(starts)}; the CLI reference guards would have no section to check"
    )
    start = starts[0]
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
        len(lines),
    )
    return "".join(lines[start:end])


def _mentions_alias(text: str, alias: str) -> bool:
    """True when ``alias`` appears as its own token.

    A bare substring test is not enough: ``-v`` occurs INSIDE ``--version``, so
    a section that merely mentions ``--version`` would silently satisfy
    ``--verbose``. Requiring a non-word, non-dash character before the alias
    keeps the exemption honest (the real reference writes it as `-v`).
    """
    return re.search(rf"(?<![\w-]){re.escape(alias)}", text) is not None


def _mentions_flag(text: str, flag: str) -> bool:
    """True when ``flag`` appears as a WHOLE option token in ``text``.

    The long-option mirror of ``_mentions_alias``, and load-bearing for the same
    reason: one live flag is now a PREFIX of another (``--out`` inside
    ``--out-dir``), so a plain substring test would let a section documenting
    only the longer one silently satisfy the shorter -- exactly the blindness
    behavior 4 exists to rule out. The lookahead rejects a match that continues
    into a longer option name.
    """
    return re.search(rf"{re.escape(flag)}(?![A-Za-z0-9-])", text) is not None


def undocumented(section_text: str, universe: Iterable[str]) -> list[str]:
    """Sorted universe flags absent from ``section_text`` (short form counts)."""
    return sorted(
        flag
        for flag in set(universe) - EXEMPT_FLAGS
        if not _mentions_flag(section_text, flag)
        and not any(
            _mentions_alias(section_text, alias)
            for alias in SHORT_FORMS.get(flag, ())
        )
    )


def parserless(section_text: str, universe: Iterable[str]) -> list[str]:
    """Sorted ``--flag``-shaped tokens in ``section_text`` that no parser accepts."""
    known = set(universe) | EXEMPT_FLAGS
    return sorted({t for t in FLAG_TOKEN.findall(section_text) if t not in known})


def undocumented_verbs(section_text: str, verbs: Iterable[str]) -> list[str]:
    """Sorted verbs whose inline-code name is absent from ``section_text``."""
    return sorted(verb for verb in set(verbs) if f"`{verb}`" not in section_text)


def verb_rows(section_text: str) -> dict[str, str]:
    """Map each live verb to the table row that owns it (padding-tolerant)."""
    verbs = set(live_verbs())
    rows: dict[str, str] = {}
    for line in section_text.splitlines():
        if not line.startswith("|"):
            continue
        m = re.search(r"`([a-z][a-z-]*)`", line)
        if m and m.group(1) in verbs:
            rows.setdefault(m.group(1), line)
    return rows


def synthetic_section(flags: Iterable[str]) -> str:
    """A minimal CLI section documenting exactly ``flags`` and no verb prose."""
    return f"{CLI_HEADING}\n\n" + " ".join(sorted(flags)) + "\n"


# --------------------------------------------------------------------------
# Sanity: the guard must not be vacuous
# --------------------------------------------------------------------------


def test_the_derived_surface_is_non_trivial() -> None:
    """A guard over an empty universe passes for the wrong reason."""
    universe = flag_universe()
    assert len(universe) >= 20, f"suspiciously small flag universe: {sorted(universe)}"
    assert "--help" not in universe
    assert len(live_verbs()) >= 15
    section = section_of(readme_text())
    assert len(section) > 2_000, "CLI section is too small to be the real reference"


# --------------------------------------------------------------------------
# Behavior 1 -- forward guard: no live flag is undocumented
# --------------------------------------------------------------------------


def test_behavior1_cli_section_documents_every_live_long_option() -> None:
    absent = undocumented(section_of(readme_text()), flag_universe())
    assert absent == [], (
        f"the README {CLI_HEADING!r} reference does not document these live long "
        f"options: {absent}. Document each in the table row of the verb that owns "
        "it, BELOW the PORTFOLIO INTRO marker (the intro is human-owned)."
    )


def test_behavior1_the_five_flags_this_iteration_added_are_present() -> None:
    """The specific defect: 5 flags, 4 of them REQUIRED arguments."""
    section = section_of(readme_text())
    for flag in ("--dry-run", "--min-weight", "--out", "--run-dir", "--slate"):
        assert flag in section, (
            f"{flag} is missing from the README {CLI_HEADING!r} reference; a reader "
            "following the reference cannot run the verb that requires it"
        )


# --------------------------------------------------------------------------
# Behavior 2 -- ``--verbose`` is satisfied by its documented short form
# --------------------------------------------------------------------------


def test_behavior2_short_form_satisfies_verbose() -> None:
    section = "Add `-v` (or `-vv`) after any subcommand to raise log verbosity.\n"
    assert "--verbose" not in section
    assert undocumented(section, {"--verbose"}) == []
    # ...and the exemption is keyed to that flag, not a blanket pass:
    assert undocumented(section, {"--verbose", "--slate"}) == ["--slate"]


def test_behavior2_the_real_section_relies_on_that_exemption() -> None:
    """Not hypothetical: the real reference teaches ``-v``, never ``--verbose``."""
    section = section_of(readme_text())
    assert "--verbose" not in section
    assert "-v" in section
    assert "--verbose" in flag_universe()


# --------------------------------------------------------------------------
# Behavior 3 -- ``--help`` is exempt in both directions
# --------------------------------------------------------------------------


def test_behavior3_help_is_never_reported_missing() -> None:
    assert undocumented("", {"--help"}) == []
    assert undocumented("", {"--help", "--top"}) == ["--top"]


def test_behavior3_help_is_not_a_ghost_when_documented() -> None:
    assert parserless("run `pla scan --help` for usage", flag_universe()) == []


# --------------------------------------------------------------------------
# Behavior 4 -- the forward guard fires on a known-bad sample
# --------------------------------------------------------------------------


def test_behavior4_forward_guard_reports_exactly_the_one_omitted_flag() -> None:
    """A tripwire that cannot be made to fire is indistinguishable from a broken one."""
    universe = flag_universe()
    for omitted in sorted(universe):
        section = synthetic_section(universe - {omitted})
        assert undocumented(section, universe) == [omitted], (
            f"forward guard failed to isolate {omitted} in a section documenting "
            "every other live flag"
        )


def test_behavior4_forward_guard_reports_all_flags_for_an_empty_section() -> None:
    universe = flag_universe()
    assert undocumented("", universe) == sorted(universe)


# --------------------------------------------------------------------------
# Behavior 5 -- reverse guard: no ghost flags in the reference
# --------------------------------------------------------------------------


def test_behavior5_cli_section_has_no_ghost_flags() -> None:
    ghosts = parserless(section_of(readme_text()), flag_universe())
    assert ghosts == [], (
        f"the README {CLI_HEADING!r} reference documents options no parser accepts: "
        f"{ghosts}. Either the option was renamed/removed in the CLI (fix the "
        "reference, BELOW the marker) or the reference has a typo -- a documented "
        "flag that exits 2 is worse than an undocumented one."
    )


def test_behavior5_reverse_guard_reports_a_flag_no_parser_accepts() -> None:
    section = (
        f"{CLI_HEADING}\n| `scan` | takes `--workspace` and `--no-such-flag`. |\n"
    )
    assert parserless(section, flag_universe()) == ["--no-such-flag"]


# --------------------------------------------------------------------------
# Behavior 6 -- the reverse guard MUST be section-scoped, and the badge proves it
# --------------------------------------------------------------------------


def test_behavior6_badge_escape_is_the_only_parserless_token_in_the_readme() -> None:
    """``runtime-offline--first-success`` is shields.io dash escaping, not a flag.

    It lives in the human-owned intro, so a whole-README reverse guard would be
    permanently red with an unfixable remedy. Pinning BOTH results keeps the
    scoping decision from being quietly "simplified" later. The Quickstart's
    ``uv sync --locked`` is the second member of that census: a foreign tool's
    flag, so also unreachable for any `pla` parser, but BELOW the marker.
    """
    text = readme_text()
    universe = flag_universe()
    assert parserless(text, universe) == FOREIGN_FLAG_TOKENS
    assert parserless(section_of(text), universe) == []
    assert "--first-success" in text.split(MARKER, 1)[0], (
        "the badge escape moved out of the human-owned intro; re-check whether "
        "the reverse guard still needs to be section-scoped"
    )
    # The other census member must stay in the editable half, or the remedy for a
    # future failure here changes from "fix the docs" to "cannot be fixed".
    assert "--locked" in text.split(MARKER, 1)[1], (
        "`uv sync --locked` moved above the human-owned marker; automated "
        "contributors may not edit it there"
    )


def test_behavior6_section_extractor_fails_loudly_without_the_heading() -> None:
    with pytest.raises(AssertionError, match="exactly one"):
        section_of("# Title\n\nno CLI heading here\n")


def test_behavior6_section_extractor_rejects_a_duplicated_heading() -> None:
    with pytest.raises(AssertionError, match="exactly one"):
        section_of(f"{CLI_HEADING}\na\n\n{CLI_HEADING}\nb\n")


def test_behavior6_section_stops_at_the_next_h2() -> None:
    text = f"# T\n\n{CLI_HEADING}\ninside\n\n## Configuration\noutside\n"
    section = section_of(text)
    assert "inside" in section
    assert "outside" not in section
    assert section.startswith(CLI_HEADING)


# --------------------------------------------------------------------------
# Behavior 7 -- verb-presence guard (folded scout-B B2)
# --------------------------------------------------------------------------


def test_behavior7_cli_section_documents_every_live_verb() -> None:
    absent = undocumented_verbs(section_of(readme_text()), live_verbs())
    assert absent == [], (
        f"the README {CLI_HEADING!r} reference is missing these live verbs: "
        f"{absent}. Add one terse table row per verb, BELOW the marker."
    )


def test_behavior7_verb_guard_reports_exactly_the_one_absent_verb() -> None:
    verbs = live_verbs()
    for omitted in verbs:
        section = f"{CLI_HEADING}\n" + "".join(
            f"| `{v}`| does something.|\n" for v in verbs if v != omitted
        )
        assert undocumented_verbs(section, verbs) == [omitted]


def test_behavior7_a_column_regex_would_be_blind_to_the_unpadded_rows() -> None:
    """Why the check must be a tolerant presence test, measured on the real file.

    The plausible pattern ``^\\| `verb`\\s+\\|`` matches only the PADDED rows, so
    it silently drops the rows whose closing backtick touches the pipe while
    still reporting success. The tolerant check sees all 15.
    """
    section = section_of(readme_text())
    naive = re.findall(r"^\| `(\w+)`\s+\|", section, re.M)
    tolerant = [v for v in live_verbs() if f"`{v}`" in section]
    assert len(tolerant) == len(live_verbs()) == 15
    assert set(naive) < set(tolerant), (
        "expected the naive column regex to be strictly blinder than the "
        "presence test; if the table's padding was normalized this assertion "
        "may be updated, but the guard must stay a presence test"
    )
    for unpadded in ("collectors", "providers"):
        assert unpadded not in naive
        assert unpadded in tolerant


# --------------------------------------------------------------------------
# Behavior 8 -- the human-owned intro is untouched
# --------------------------------------------------------------------------


def test_behavior8_marker_and_carved_out_numbers_are_intact() -> None:
    text = readme_text()
    assert MARKER in text, f"README lost its {MARKER!r} boundary comment"
    marker_line = next(line for line in text.splitlines() if MARKER in line)
    assert "human-owned" in marker_line, (
        "the portfolio marker no longer says it is human-owned; automated "
        f"contributors lose their boundary. Line: {marker_line!r}"
    )
    intro = text.split(MARKER, 1)[0]

    m = re.search(r"([\d,]+) context collectors", intro)
    assert m and int(m.group(1).replace(",", "")) == len(all_collectors())

    m = re.search(r"([\d,]+) CLI verbs", intro)
    assert m and int(m.group(1).replace(",", "")) == len(live_verbs())

    floors = re.findall(r"\*\*([\d,]+)(\+?)[^*]*tests\*\*", intro)
    assert floors, "intro must claim the suite size"
    for count, plus in floors:
        assert plus == "+", f"intro states an exact test count ({count}), not a floor"


def test_behavior8_no_flag_documentation_leaked_above_the_marker() -> None:
    """This iteration's edits must all be BELOW the human-owned marker."""
    intro = readme_text().split(MARKER, 1)[0]
    for flag in ("--dry-run", "--min-weight", "--out", "--run-dir", "--slate"):
        assert flag not in intro, (
            f"{flag} is documented ABOVE the {MARKER!r} marker; the CLI reference "
            "belongs below it, and the intro is human-owned"
        )
    assert CLI_HEADING not in intro


# --------------------------------------------------------------------------
# Behavior 9 -- each pair is documented on the verb row that owns it
# --------------------------------------------------------------------------


def test_behavior9_every_required_pair_is_on_its_own_verb_row() -> None:
    rows = verb_rows(section_of(readme_text()))
    assert set(rows) == set(live_verbs()), (
        f"the CLI table is missing rows for {sorted(set(live_verbs()) - set(rows))}"
    )
    for verb, flag in REQUIRED_PAIRS:
        assert flag in rows[verb], (
            f"{flag} is documented somewhere in the CLI section but NOT on the "
            f"`{verb}` row, so a reader of that row still cannot run the command"
        )


def test_behavior9_required_arguments_are_marked_required() -> None:
    """The 4 required pairs must SAY so; an optional-looking required arg exits 2."""
    rows = verb_rows(section_of(readme_text()))
    for verb in ("dispatch", "explain", "resume", "trace"):
        assert "required" in rows[verb].lower(), (
            f"the `{verb}` row documents a REQUIRED argument without saying it is "
            "required; omitting it is an exit-2 usage error"
        )


# --------------------------------------------------------------------------
# Behavior 10 -- ``--dry-run`` is documented with its TRUE semantics
# --------------------------------------------------------------------------


def test_behavior10_dry_run_row_says_the_slate_is_still_written() -> None:
    row = verb_rows(section_of(readme_text()))["run"].lower()
    assert "--dry-run" in row
    assert "slate" in row and ("still writ" in row or "writes the slate" in row), (
        "the `run` row must state that --dry-run STILL WRITES the slate; it is a "
        "preview of what would be auto-dispatched, not a no-side-effects run"
    )
    for phrase in FALSE_DRY_RUN_PHRASINGS:
        assert phrase not in row, (
            f"the `run` row describes --dry-run as {phrase!r}, contradicting its "
            "own help text: the slate IS written; only the run dir and the loop "
            "iterations are skipped"
        )


def test_behavior10_readme_clause_matches_the_live_help_text() -> None:
    """The doc claim is bound to the parser's own help string, not to prose."""
    run_parser = sub_action(build_parser()).choices["run"]
    help_text = next(
        a.help or ""
        for a in run_parser._actions
        if "--dry-run" in a.option_strings
    ).lower()
    assert "slate" in help_text
    assert "stop" in help_text or "before" in help_text
    row = verb_rows(section_of(readme_text()))["run"].lower()
    for token in ("run dir", "slate"):
        assert token in row, (
            f"--dry-run's help text mentions {token!r} but the README row does not"
        )


# --------------------------------------------------------------------------
# Cross-check: the SHIPPED guard (what CI runs) agrees with these oracles
# --------------------------------------------------------------------------


def test_shipped_guard_helpers_agree_with_the_independent_derivations() -> None:
    """Pin the helpers CI actually runs against this module's independent results.

    If this import breaks, the drift guard moved; re-point it rather than
    deleting it -- otherwise the README reference silently loses its oracle.
    """
    contract = pytest.importorskip(
        "tests.test_readme_and_ci_contract",
        reason="the shipped README drift guard module must be importable",
    )
    text = readme_text()
    parser = build_parser()
    universe = contract.flag_universe(parser)
    assert set(universe) == set(flag_universe())
    assert contract.cli_section(text) == section_of(text)

    shipped_section = contract.cli_section(text)
    assert contract.missing_flags(shipped_section, universe) == undocumented(
        shipped_section, universe
    )
    assert contract.ghost_flags(shipped_section, universe) == parserless(
        shipped_section, universe
    )
    assert contract.ghost_flags(text, universe) == FOREIGN_FLAG_TOKENS
    verbs = live_verbs()
    assert contract.missing_verbs(shipped_section, verbs) == undocumented_verbs(
        shipped_section, verbs
    )
    # ...and the shipped forward guard fires on a known-bad sample too.
    omitted = "--slate"
    bad = synthetic_section(set(universe) - {omitted})
    assert contract.missing_flags(bad, universe) == [omitted]
