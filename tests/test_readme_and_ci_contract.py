"""Drift guards for the README's public claims and the CI contract.

Why this file exists
--------------------
The README's portfolio intro sits ABOVE the ``PORTFOLIO INTRO -- human-owned``
marker, which automated contributors may not rewrite. That makes it the one
place in the repo whose numbers the dev loop cannot fix while it is busy
changing them -- exactly where a stale public claim rots unnoticed on a PUBLIC
repo. (It had already rotted once: the intro advertised a hardcoded
``tests-NNNN-passing`` shields badge that went stale on literally every commit.)

So every quoted claim is bound here to a live source of truth:

* ``"N context collectors"`` -> ``len(all_collectors())``
* ``"N CLI verbs"``          -> the live argparse subparser choices
* the suite-size claim       -> must be a **floor** (``1,800+ tests``), never an
  exact count. An exact count is self-invalidating: adding this very file
  changes it. A floor stays true as the suite grows.
* the test signal            -> must be the live CI badge, not a hardcoded one.
* the CI workflow            -> must still run the three commands the README and
  Makefile promise (``uv sync --locked`` / ``uv run pytest`` / ``make demo``).
* every live ``--long`` option -> must appear in the ``## CLI`` reference
* every live subcommand name   -> must appear in the ``## CLI`` reference

The last two close a structural blind spot in this very file: ``_intro()`` returns
only the text ABOVE the marker, and every guard below it consumed that -- so every
machine-checked README claim lived in the human-owned intro while the reference
section a reader actually FOLLOWS had no oracle at all. That is how a shipped flag
(``--min-weight``) and four REQUIRED arguments (``dispatch/explain --slate``,
``resume/trace --run-dir``) reached a public README that could not be followed.
``cli_section()`` is the counterpart seam for the region BELOW the marker, and the
flag guard is bidirectional: a live flag missing from the docs fails, and a
documented flag that exists on no parser (a ghost) fails too.

The README marker carries a narrow carve-out permitting automated contributors
to correct these NUMBERS (and only the numbers), so this guard forces a fix
instead of deadlocking the loop.

Fully offline: reads two files and imports the package. No network, no
subprocess, no YAML dependency (the workflow is checked as text on purpose --
``pyyaml`` is deliberately not a dependency of this project).
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
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
MARKER = "PORTFOLIO INTRO"
CLI_HEADING = "## CLI"

# argparse injects ``--help`` into every parser; the reference documents the 15
# verbs, not 15 identical help flags, so it is exempt from both directions.
EXEMPT_FLAGS = frozenset({"--help"})

# Long options the reference teaches through a SHORT alias instead. ``--verbose``
# is documented only as ``-v``/``-vv`` (it is a global flag on all 15 subparsers),
# so without this the forward guard would report it as undocumented on every verb
# at once -- a false catastrophe, and a guard that cries wolf gets deleted.
DOCUMENTED_SHORT_FORMS: dict[str, tuple[str, ...]] = {"--verbose": ("-v",)}

# A ``--flag``-shaped token. Stops at the first character that cannot be part of
# an option name, so ``--out PATH`` yields ``--out`` and ``run-<id>`` yields
# nothing.
FLAG_TOKEN = re.compile(r"--[A-Za-z][A-Za-z0-9-]*")

# The COMPLETE census of ``--``-shaped tokens the README publishes that are not
# `pla` options at all, so no parser could ever accept them. This is why the
# reverse guard is scoped to the ``## CLI`` section: both of these live outside
# it. Pinned as an EXACT list rather than added to ``EXEMPT_FLAGS``, so a THIRD
# such token still fails the build instead of being silently forgiven.
#   ``--first-success``  shields.io escapes a literal dash as ``--`` in the
#                        Offline badge, inside the human-owned intro.
#   ``--locked``         the Quickstart installs with ``uv sync --locked``. It is
#                        a `uv` flag, and it is exactly what makes that line
#                        honest: a bare ``uv sync`` may resolve and mutate
#                        ``uv.lock``, which is what CI forbids.
FOREIGN_FLAG_TOKENS = ["--first-success", "--locked"]


def _intro() -> str:
    """Return the human-owned block: everything above the portfolio marker."""
    text = README.read_text(encoding="utf-8")
    assert MARKER in text, (
        f"{README.name} lost its {MARKER!r} marker -- automated contributors no "
        "longer have a boundary telling them which prose is human-owned"
    )
    return text.split(MARKER, 1)[0]


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    """The single ``add_subparsers`` action, so verb and flag guards share one seam."""
    subs = [
        a
        for a in parser._subparsers._group_actions
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(subs) == 1, f"expected exactly one subparser action, got {len(subs)}"
    return subs[0]


def _long_options(parser: argparse.ArgumentParser) -> set[str]:
    """Every ``--long`` option string declared directly on ``parser``."""
    return {
        opt
        for action in parser._actions
        for opt in action.option_strings
        if opt.startswith("--")
    }


def _verb_count() -> int:
    """The number of live ``pla`` subcommands, straight off the parser."""
    return len(_subparser_action(build_parser()).choices)


def cli_section(text: str) -> str:
    """Return the ``## CLI`` reference block: that heading up to the next ``## ``.

    The counterpart of :func:`_intro` for the region automated contributors MAY
    edit. It asserts rather than returning ``""`` when the heading is gone,
    because an empty section is the worst possible failure mode here: the forward
    guard would report all 24 flags (unreadable) while the reverse guard reported
    nothing (silently blind).
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\n") == CLI_HEADING]
    assert len(starts) == 1, (
        f"README.md must contain exactly one {CLI_HEADING!r} heading, found "
        f"{len(starts)} -- the CLI reference guards have no section to check"
    )
    start = starts[0]
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
        len(lines),
    )
    return "".join(lines[start:end])


def flag_universe(parser: argparse.ArgumentParser) -> frozenset[str]:
    """Every live ``--long`` option: the root parser UNION every subparser's.

    The union is required, not belt-and-braces: the root parser carries only
    ``--help``/``--version``, while ``--provider``/``--scripted-responses``/
    ``--state-dir`` are attached to each subparser through a shared ``parents=``
    group. Reading the root alone would make the reverse guard call
    ``--provider`` a ghost.
    """
    universe = _long_options(parser)
    for sub in _subparser_action(parser).choices.values():
        universe |= _long_options(sub)
    return frozenset(universe - EXEMPT_FLAGS)


def missing_flags(section_text: str, universe: Iterable[str]) -> list[str]:
    """Sorted live flags absent from ``section_text`` (a documented short form counts)."""
    missing = [
        flag
        for flag in set(universe) - EXEMPT_FLAGS
        if flag not in section_text
        and not any(
            short in section_text for short in DOCUMENTED_SHORT_FORMS.get(flag, ())
        )
    ]
    return sorted(missing)


def ghost_flags(section_text: str, universe: Iterable[str]) -> list[str]:
    """Sorted ``--flag``-shaped tokens in ``section_text`` that no parser accepts."""
    known = set(universe) | EXEMPT_FLAGS
    return sorted({t for t in FLAG_TOKEN.findall(section_text) if t not in known})


def missing_verbs(section_text: str, verbs: Iterable[str]) -> list[str]:
    """Sorted live subcommands not present in ``section_text`` as an inline-code token.

    A tolerant presence test on the backticked NAME, deliberately NOT a
    table-column regex: two of the fifteen rows omit the space between the
    closing backtick and the pipe, so a plausible pattern anchored on
    "pipe, space, backticked word, padding, pipe" drops exactly those two rows
    while still passing -- a guard blind to the rows it stares hardest at.
    Requiring the inline-code form (backtick, verb, backtick) rather than the bare
    word also keeps prose like "a bare run" from satisfying the check by accident.
    """
    return sorted(verb for verb in set(verbs) if f"`{verb}`" not in section_text)


def test_readme_collector_count_matches_the_live_registry() -> None:
    intro = _intro()
    m = re.search(r"([\d,]+) context collectors", intro)
    assert m, "README intro must state 'N context collectors'"
    claimed = int(m.group(1).replace(",", ""))
    live = len(all_collectors())
    assert claimed == live, (
        f"README intro claims {claimed} context collectors but the registry has "
        f"{live}; update the number in the intro (the marker's carve-out allows it)"
    )


def test_readme_cli_verb_count_matches_the_live_parser() -> None:
    intro = _intro()
    m = re.search(r"([\d,]+) CLI verbs", intro)
    assert m, "README intro must state 'N CLI verbs'"
    claimed = int(m.group(1).replace(",", ""))
    live = _verb_count()
    assert claimed == live, (
        f"README intro claims {claimed} CLI verbs but the parser exposes {live}; "
        "update the number in the intro (the marker's carve-out allows it)"
    )


def test_readme_states_the_suite_size_as_a_floor_not_an_exact_count() -> None:
    intro = _intro()
    claims = list(re.finditer(r"\*\*([\d,]+)(\+?)[^*]*tests\*\*", intro))
    assert claims, (
        "README intro must make at least one bolded claim about the suite size"
    )
    for m in claims:
        assert m.group(2) == "+", (
            f"README claims an exact test count ({m.group(0)!r}). State a floor "
            "like '**1,800+ tests**' instead: an exact count is stale the moment "
            "the next test lands, and this block is human-owned so the loop that "
            "breaks it cannot fix it."
        )
        floor = int(m.group(1).replace(",", ""))
        assert floor > 0, f"nonsensical test-count floor in {m.group(0)!r}"


def test_readme_test_signal_is_the_live_ci_badge() -> None:
    intro = _intro()
    assert "actions/workflows/ci.yml/badge.svg" in intro, (
        "README must carry the live GitHub Actions CI badge -- it is the only "
        "test signal that cannot go stale"
    )
    assert "img.shields.io/badge/tests-" not in intro, (
        "a hardcoded 'tests-NNNN-passing' shields badge is back in the README; "
        "it misreports the suite size on every commit -- use the CI badge"
    )


def test_ci_workflow_runs_the_commands_the_project_documents() -> None:
    assert WORKFLOW.is_file(), (
        f"missing {WORKFLOW.relative_to(REPO)} -- the CI badge in the README "
        "would render as 'no status' and the repo would advertise a check it "
        "does not run"
    )
    text = WORKFLOW.read_text(encoding="utf-8")
    for command in ("uv sync --locked", "uv run pytest", "make demo"):
        assert command in text, (
            f"CI no longer runs {command!r}; the workflow must keep asserting "
            "both halves of the offline claim (suite green AND demo completes)"
        )
    # The floor of requires-python must actually be exercised, or "3.12+" is
    # an untested claim.
    assert '"3.12"' in text, "CI must test the requires-python floor (3.12)"


def test_ci_checks_out_full_git_history() -> None:
    """CI must NOT use the default depth-1 checkout.

    This repo tests its own git history: ``GitActivityCollector`` shells out to
    ``git log -n15`` and the fixture behavior tests assert the exact header
    ``## git_commit (15)``. Under a shallow clone only one commit is reachable,
    so those tests fail in CI while passing on every developer machine -- which
    is exactly what happened on 2026-08-04 (three failures across four
    consecutive red builds). Pin the requirement so it cannot silently regress.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "fetch-depth: 0" in text, (
        "CI must check out FULL git history (fetch-depth: 0). The default "
        "depth-1 checkout makes GitActivityCollector see 1 commit instead of "
        "15, breaking the fixture tests in CI only."
    )


# --------------------------------------------------------------------------
# The CLI reference (BELOW the marker) bound to the live parser, both ways.
# --------------------------------------------------------------------------


def test_cli_reference_documents_every_live_flag() -> None:
    section = cli_section(README.read_text(encoding="utf-8"))
    absent = missing_flags(section, flag_universe(build_parser()))
    assert absent == [], (
        f"the README '{CLI_HEADING}' reference does not document these live flags: "
        f"{absent}. Document each one in the table row of the verb that owns it, "
        "BELOW the PORTFOLIO INTRO marker (the intro is human-owned). A reader who "
        "follows the reference must be able to run every verb -- four of these "
        "options are REQUIRED arguments, so omitting one makes the documented "
        "command exit 2."
    )


def test_cli_reference_has_no_ghost_flags() -> None:
    section = cli_section(README.read_text(encoding="utf-8"))
    ghosts = ghost_flags(section, flag_universe(build_parser()))
    assert ghosts == [], (
        f"the README '{CLI_HEADING}' reference documents flags no parser accepts: "
        f"{ghosts}. Either the option was renamed/removed in "
        "src/proactive_loop/cli.py (fix the reference, BELOW the marker) or the "
        "reference has a typo. A documented flag that exits 2 is worse than an "
        "undocumented one."
    )


def test_cli_reference_documents_every_live_verb() -> None:
    section = cli_section(README.read_text(encoding="utf-8"))
    verbs = _subparser_action(build_parser()).choices
    absent = missing_verbs(section, verbs)
    assert absent == [], (
        f"the README '{CLI_HEADING}' reference is missing a row for these live "
        f"verbs: {absent}. Add one terse table row per verb, BELOW the PORTFOLIO "
        "INTRO marker. The intro's verb COUNT is already guarded, so without this "
        "a new verb could ship with the count bumped and the reference row omitted."
    )


def test_ghost_flag_guard_is_scoped_to_the_cli_section() -> None:
    """Tokens outside the CLI section are why the reverse guard is section-scoped.

    ``![Offline](.../runtime-offline--first-success)`` uses shields.io's escaped
    dash, which looks exactly like a long option. It is inside the block this file
    may not edit, so a whole-README reverse guard would be permanently red with an
    unfixable remedy. The Quickstart's ``uv sync --locked`` is the second such
    token and a foreign tool's flag for the same reason. Pinning both results
    keeps that decision from being quietly "simplified" later.
    """
    text = README.read_text(encoding="utf-8")
    universe = flag_universe(build_parser())
    assert ghost_flags(text, universe) == FOREIGN_FLAG_TOKENS, (
        f"expected {FOREIGN_FLAG_TOKENS} to be the ONLY parser-less '--' tokens "
        "in the README; if this changed, re-check whether the reverse guard is "
        "still correctly scoped to the CLI section"
    )
    assert ghost_flags(cli_section(text), universe) == []


def test_cli_section_extractor_fails_loudly_when_the_heading_is_absent() -> None:
    """A silently-empty section would make both guards useless in opposite ways."""
    with pytest.raises(AssertionError, match="exactly one"):
        cli_section("# Title\n\nno CLI heading here\n")


def test_missing_flags_reports_exactly_the_one_undocumented_flag() -> None:
    """Known-bad sample: a tripwire that cannot be made to fire proves nothing."""
    universe = flag_universe(build_parser())
    omitted = "--slate"
    assert omitted in universe
    section = f"{CLI_HEADING}\n" + " ".join(sorted(universe - {omitted})) + "\n"
    assert missing_flags(section, universe) == [omitted]


def test_missing_flags_accepts_a_documented_short_form() -> None:
    """``-v``/``-vv`` in the prose satisfies ``--verbose`` (behavior 2)."""
    section = "Add `-v` (or `-vv`) after any subcommand to raise log verbosity.\n"
    assert "--verbose" not in section
    assert missing_flags(section, {"--verbose"}) == []
    # ...and the exemption is keyed to the flag, not a blanket pass:
    assert missing_flags(section, {"--verbose", "--slate"}) == ["--slate"]


def test_missing_flags_never_reports_the_injected_help_flag() -> None:
    assert missing_flags("", {"--help"}) == []
    assert missing_flags("", {"--help", "--top"}) == ["--top"]


def test_ghost_flags_reports_a_flag_that_exists_on_no_parser() -> None:
    """Known-bad sample for the reverse direction."""
    universe = flag_universe(build_parser())
    section = f"{CLI_HEADING}\n| `scan` | takes `--workspace` and `--no-such-flag`. |\n"
    assert ghost_flags(section, universe) == ["--no-such-flag"]


def test_missing_verbs_reports_exactly_the_one_absent_verb() -> None:
    """Known-bad sample: and it must catch the two rows a column regex would drop."""
    verbs = list(_subparser_action(build_parser()).choices)
    for omitted in ("collectors", "providers", "scan"):
        section = f"{CLI_HEADING}\n" + " ".join(
            f"| `{v}`| does something.|" for v in verbs if v != omitted
        )
        assert missing_verbs(section, verbs) == [omitted]
