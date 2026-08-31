"""Black-box behavior tests for foundry iteration 256 --- ``SPEC.md`` names every
shipped CLI long flag, guarded by a registry-derived census.

Feature under test: README nominates ``SPEC.md`` as the design contract ("Start
here to see what the project *promises*"), and it was silent about 9 of the 36
long flags ``build_parser()`` actually exposes --- including the three that ARE
the machine-gate enforcement surface CI runs on every push (``--fail-on-kind``,
``--fail-over``, ``--exclude-path``). This iteration documents all 9 in section
4.5 and adds the census below, which is DERIVED FROM THE LIVE PARSER, so the
roster can never go stale the way a hand-maintained list does.

ISOLATION CONTRACT (honored): every assertion below is written against THIS
iteration's spec (``pm.md`` "Expected Behaviors" 1-7) and drives only public or
spec-authorized surfaces --- the public ``proactive_loop.cli.build_parser()``
registry, the public ``proactive_loop.collectors.all_collectors()`` registry, and
the tracked prose files ``SPEC.md`` / ``README.md``. Behavior 3 reads
``src/proactive_loop/cli.py`` as a MACHINE domain (two substring probes the spec
mandates verbatim, to prove the exemption set is justified rather than asserted);
no implementation logic was read by a human, no engineer or reviewer notes were
read, and no ``git diff`` was consulted.

Fully offline and deterministic: no network, no API key, no subprocess, no
sleeps, no temp state --- the census builds a parser in-process and compares it
against text read from the repo. Every mutation in the two-sided family
(behavior 6) is applied to an in-memory COPY of ``SPEC.md``; the tracked file is
never written.

AMBIGUITY NOTES (PM feedback):
* Behavior 5 specifies the bullet pattern as ``- `pla <verb>`` anchored at the
  start of a line. Measured on the shipped tree, section 4.5's verb bullets are
  INDENTED by two spaces, so that literal anchored pattern matches **0** lines
  while ``line.lstrip()`` matches exactly **17**, set-equal to the 17 live verbs.
  The tests use the ``lstrip()`` reading, which is the only one under which the
  behavior is satisfiable. Recommend the spec say "a line whose stripped form
  begins ``- `pla ``".
* Behavior 5 also says ``--version`` "must occur in 4.5 outside every verb
  bullet block, OR in the global-options prose". That is a requirement to
  APPEAR, not a prohibition on appearing twice, so it is tested as satisfied
  when at least one occurrence lies outside every bullet block. Measured: the
  shipped tree satisfies it in the pre-bullet prose AND additionally names
  ``--version`` inside a bullet block, which the OR permits.
* Behavior 6's placement mutation says "one owning verb's bullet block is
  replaced by a bullet with no flags". Replacing ``signals``' block necessarily
  drops all six flags it owns at once, so the assertion is written per
  (flag, verb) PAIR --- it requires that the specific pair under test is
  reported --- rather than requiring the report to name only one flag.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "SPEC.md"
README_PATH = REPO_ROOT / "README.md"
CLI_SOURCE_PATH = REPO_ROOT / "src" / "proactive_loop" / "cli.py"

#: The only long flag argparse adds on our behalf. Every other flag the live
#: parser exposes is declared by our own ``add_argument`` call and must therefore
#: appear in the design contract. Behavior 3 proves this membership mechanically
#: instead of trusting this comment.
EXEMPT_FLAGS: frozenset[str] = frozenset({"--help"})

#: The 9 flags this iteration adds to ``SPEC.md``.
NEWLY_DOCUMENTED: tuple[str, ...] = (
    "--baseline",
    "--exclude-path",
    "--fail-on-kind",
    "--fail-over",
    "--prune",
    "--status",
    "--summary",
    "--timings",
    "--version",
)

#: The 8 of those 9 that are owned by a verb (``--version`` is top-level only),
#: mapped to every verb that owns them in the live parser. Spelled out as the
#: black-box expectation; behavior 5 also re-derives it from the parser and
#: asserts the two agree, so a drift in either direction reds.
EXPECTED_OWNERS: dict[str, frozenset[str]] = {
    "--baseline": frozenset({"run", "signals"}),
    "--exclude-path": frozenset({"scan", "run", "signals"}),
    "--fail-on-kind": frozenset({"signals"}),
    "--fail-over": frozenset({"signals"}),
    "--summary": frozenset({"signals"}),
    "--timings": frozenset({"signals"}),
    "--prune": frozenset({"runs"}),
    "--status": frozenset({"runs"}),
}

OWNED_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (flag, verb) for flag, verbs in sorted(EXPECTED_OWNERS.items()) for verb in sorted(verbs)
)

EXPECTED_FLAG_COUNT = 36
EXPECTED_VERB_COUNT = 17
EXPECTED_COLLECTOR_COUNT = 17


def _collect_long_flags(parser: argparse.ArgumentParser) -> dict[str, frozenset[str | None]]:
    """Return every ``--`` option string the live CLI exposes, mapped to owners.

    Walks the top-level parser's ``_actions`` and, recursively, every subparser
    in each ``argparse._SubParsersAction.choices``. An owner of ``None`` means
    the top-level parser itself.
    """
    owners: dict[str, set[str | None]] = {}
    stack: list[tuple[argparse.ArgumentParser, str | None]] = [(parser, None)]
    while stack:
        current, verb = stack.pop()
        for action in current._actions:
            for option in action.option_strings:
                if option.startswith("--"):
                    owners.setdefault(option, set()).add(verb)
            if isinstance(action, argparse._SubParsersAction):
                for name, subparser in action.choices.items():
                    stack.append((subparser, name))
    return {flag: frozenset(verbs) for flag, verbs in owners.items()}


def _live_verbs(parser: argparse.ArgumentParser) -> frozenset[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return frozenset(action.choices)
    raise AssertionError("the top-level parser exposes no subparsers")


def census_missing_flags(spec_text: str, flags: frozenset[str]) -> list[str]:
    """Return live flags absent from ``spec_text``, ignoring ``EXEMPT_FLAGS``.

    LIMIT OF THIS CHECK, stated so a future reader does not over-trust it: it
    proves each flag is **named** somewhere in the contract, never that it is
    described correctly, placed sensibly, or still accurate --- a substring probe
    is deliberately the weakest possible oracle, and it is chosen because it is
    derived from the live parser and therefore cannot go stale. The companion
    placement rule in :func:`placement_violations` is narrower still: this
    iteration applies it to the 8 verb-owned flags of behavior 5 only. Measured
    on the shipped tree, running that same rule over EVERY verb-owned flag
    reports 77 (flag, verb) pairs, of which 69 are the 5 shared globals argparse
    replicates onto every subparser (``--help``, ``--provider``,
    ``--scripted-responses``, ``--state-dir``, ``--verbose``) and **8 are
    genuinely verb-specific flags missing from an owning verb's bullet block**
    (``--dir``/diff, ``--dry-run``/dispatch, ``--json``/{dispatch, resume, scan},
    ``--kind``/collectors, ``--out-dir``/watch, ``--snapshot``/scan). Those 8 are
    a real, unclosed residual gap, not a bug in this census.
    """
    return sorted(flag for flag in flags if flag not in EXEMPT_FLAGS and flag not in spec_text)


def section_4_5(spec_text: str) -> list[str]:
    """Return section 4.5's lines: its heading through the next ``#``-``###`` heading."""
    lines = spec_text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("### 4.5")), None)
    assert start is not None, "SPEC.md has no '### 4.5' heading"
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^#{1,3} ", lines[index]):
            end = index
            break
    return lines[start:end]


def verb_bullet_blocks(spec_text: str) -> dict[str, str]:
    """Map each ``- `pla <verb>`` bullet in 4.5 to its block text.

    A block runs from one such bullet to the next, or to the end of 4.5. The
    bullets are matched on ``line.lstrip()`` --- see the module docstring's first
    ambiguity note.
    """
    section = section_4_5(spec_text)
    starts = [i for i, line in enumerate(section) if line.lstrip().startswith("- `pla ")]
    blocks: dict[str, str] = {}
    for position, index in enumerate(starts):
        match = re.match(r"- `pla ([a-z][a-z-]*)", section[index].lstrip())
        assert match is not None, f"unparsable verb bullet: {section[index]!r}"
        stop = starts[position + 1] if position + 1 < len(starts) else len(section)
        blocks[match.group(1)] = "\n".join(section[index:stop])
    assert len(blocks) == len(starts), f"duplicate verb bullet in 4.5: {len(starts)} bullets, {len(blocks)} verbs"
    return blocks


def placement_violations(spec_text: str, owners: dict[str, frozenset[str]]) -> list[str]:
    """Return one message per (flag, owning verb) pair whose bullet block omits the flag."""
    blocks = verb_bullet_blocks(spec_text)
    messages: list[str] = []
    for flag, verbs in sorted(owners.items()):
        for verb in sorted(verbs):
            block = blocks.get(verb)
            if block is None:
                messages.append(f"{flag}: section 4.5 has no `pla {verb}` bullet block at all")
            elif flag not in block:
                messages.append(f"{flag} is missing from the `pla {verb}` bullet block in section 4.5")
    return messages


@pytest.fixture(scope="module")
def spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def live_flags() -> dict[str, frozenset[str | None]]:
    return _collect_long_flags(build_parser())


# --------------------------------------------------------------------------
# Behavior 1 -- census collection
# --------------------------------------------------------------------------


def test_b1_census_collects_every_long_flag_from_parser_and_subparsers(
    live_flags: dict[str, frozenset[str | None]],
) -> None:
    assert len(live_flags) == EXPECTED_FLAG_COUNT, (
        f"expected {EXPECTED_FLAG_COUNT} long flags across the top-level parser and all "
        f"{EXPECTED_VERB_COUNT} subparsers, collected {len(live_flags)}: {sorted(live_flags)}"
    )
    assert all(flag.startswith("--") for flag in live_flags)
    uncollected = sorted(flag for flag in NEWLY_DOCUMENTED if flag not in live_flags)
    assert uncollected == [], f"spec names flags the live parser does not expose: {uncollected}"


# --------------------------------------------------------------------------
# Behavior 2 -- census guard passes on the fixed tree
# --------------------------------------------------------------------------


def test_b2_every_live_flag_except_the_exemption_is_named_in_spec(
    spec_text: str, live_flags: dict[str, frozenset[str | None]]
) -> None:
    missing = census_missing_flags(spec_text, frozenset(live_flags))
    assert missing == [], f"live CLI flags absent from the SPEC.md design contract: {missing}"


def test_b2_exemption_set_has_exactly_one_member() -> None:
    assert EXEMPT_FLAGS == frozenset({"--help"})
    assert len(EXEMPT_FLAGS) == 1


# --------------------------------------------------------------------------
# Behavior 3 -- the exemption is mechanically justified, not asserted
# --------------------------------------------------------------------------


def test_b3_version_is_our_own_declared_flag_and_help_is_argparse_s() -> None:
    source = CLI_SOURCE_PATH.read_text(encoding="utf-8")
    assert '"--version"' in source, (
        "--version is exempted nowhere and must be documented like any other flag, but the "
        "literal '\"--version\"' is absent from cli.py -- re-derive the exemption set"
    )
    assert '"--help"' not in source, (
        "--help is exempt ONLY because argparse adds it for us; cli.py now declares it "
        "explicitly, so it is our flag and must be documented"
    )


# --------------------------------------------------------------------------
# Behavior 4 -- all 9 flags are documented
# --------------------------------------------------------------------------


@pytest.mark.parametrize("flag", NEWLY_DOCUMENTED)
def test_b4_each_newly_documented_flag_occurs_in_spec(spec_text: str, flag: str) -> None:
    assert flag in spec_text, f"{flag} is not named anywhere in SPEC.md"


@pytest.mark.parametrize("flag", sorted(EXPECTED_OWNERS))
def test_b4_each_verb_owned_flag_occurs_inside_section_4_5(spec_text: str, flag: str) -> None:
    section = "\n".join(section_4_5(spec_text))
    assert flag in section, f"{flag} is named in SPEC.md but not inside section 4.5's span"


# --------------------------------------------------------------------------
# Behavior 5 -- owner-correct placement
# --------------------------------------------------------------------------


def test_b5_section_4_5_has_exactly_one_bullet_per_live_verb(spec_text: str) -> None:
    blocks = verb_bullet_blocks(spec_text)
    live = _live_verbs(build_parser())
    assert len(live) == EXPECTED_VERB_COUNT
    assert frozenset(blocks) == live, (
        f"4.5's verb bullets are not set-equal to the live verbs; "
        f"only in 4.5: {sorted(frozenset(blocks) - live)}; only in the parser: {sorted(live - frozenset(blocks))}"
    )


def test_b5_expected_owner_map_matches_the_live_parser(
    live_flags: dict[str, frozenset[str | None]],
) -> None:
    for flag, expected in sorted(EXPECTED_OWNERS.items()):
        actual = frozenset(verb for verb in live_flags[flag] if verb is not None)
        assert actual == expected, f"{flag} ownership drifted: live={sorted(actual)}, expected={sorted(expected)}"


def test_b5_no_placement_violations_on_the_shipped_tree(spec_text: str) -> None:
    violations = placement_violations(spec_text, EXPECTED_OWNERS)
    assert violations == [], "flags missing from an owning verb's bullet block:\n" + "\n".join(violations)


def test_b5_version_is_placement_exempt_and_named_outside_every_bullet_block(spec_text: str) -> None:
    section = section_4_5(spec_text)
    starts = [i for i, line in enumerate(section) if line.lstrip().startswith("- `pla ")]
    outside = "\n".join(section[: starts[0]])
    global_prose = "\n".join(line for line in section if "--version" in line and not line.lstrip().startswith("- `pla "))
    assert "--version" in outside or "--version" in global_prose, (
        "--version is a global flag, so 4.5 must name it outside every verb bullet block "
        "or in the global-options prose; it is named in neither"
    )
    assert "--version" not in EXPECTED_OWNERS, "--version is top-level only and is exempt from the placement rule"


# --------------------------------------------------------------------------
# Behavior 6 -- both guards are two-sided
# --------------------------------------------------------------------------


def test_b6_no_documented_flag_is_a_substring_of_another_live_flag(
    live_flags: dict[str, frozenset[str | None]],
) -> None:
    """Precondition for the deletion mutations below: deleting one flag string
    must not damage another flag's spelling, or the two-sided family would be
    testing the wrong thing."""
    collisions = [
        (flag, other) for flag in NEWLY_DOCUMENTED for other in live_flags if other != flag and flag in other
    ]
    assert collisions == [], f"flag spellings overlap, so deletion mutations are unsound: {collisions}"


@pytest.mark.parametrize("flag", NEWLY_DOCUMENTED)
def test_b6_census_fails_when_one_flag_is_deleted_from_the_contract(
    spec_text: str, live_flags: dict[str, frozenset[str | None]], flag: str
) -> None:
    mutated = spec_text.replace(flag, "")
    assert flag not in mutated
    missing = census_missing_flags(mutated, frozenset(live_flags))
    assert flag in missing, f"census did not report {flag} missing after every occurrence was deleted"
    with pytest.raises(AssertionError) as caught:
        assert missing == [], f"live CLI flags absent from the SPEC.md design contract: {missing}"
    assert flag in str(caught.value)


@pytest.mark.parametrize(("flag", "verb"), OWNED_PAIRS)
def test_b6_placement_fails_when_an_owning_verbs_block_loses_its_flags(
    spec_text: str, flag: str, verb: str
) -> None:
    blocks = verb_bullet_blocks(spec_text)
    stub = f"  - `pla {verb}` --- stub bullet naming no flags."
    mutated = spec_text.replace(blocks[verb], stub)
    assert mutated != spec_text, f"the `pla {verb}` block was not substituted"
    assert frozenset(verb_bullet_blocks(mutated)) == frozenset(blocks), "the mutation changed the verb roster"
    violations = placement_violations(mutated, EXPECTED_OWNERS)
    named = [message for message in violations if flag in message and verb in message]
    assert named, (
        f"placement check did not report ({flag}, {verb}) after that block was stubbed; "
        f"reported instead: {violations}"
    )


# --------------------------------------------------------------------------
# Behavior 7 -- no collateral drift
# --------------------------------------------------------------------------


def test_b7_collector_and_verb_counts_are_unchanged() -> None:
    assert len(all_collectors()) == EXPECTED_COLLECTOR_COUNT
    assert len(_live_verbs(build_parser())) == EXPECTED_VERB_COUNT


def test_b7_readme_carved_out_numbers_still_agree_with_the_live_registries() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    assert f"{EXPECTED_COLLECTOR_COUNT} context collectors" in readme
    assert f"{EXPECTED_VERB_COUNT} CLI verbs" in readme
    assert "5,400+" in readme, "the README tests floor is no longer '5,400+'; behavior 7 expects it unchanged"


def test_b7_spec_stays_under_the_byte_budget() -> None:
    size = len(SPEC_PATH.read_bytes())
    assert size < 99_500, f"SPEC.md is {size} bytes, over this iteration's 99,500-byte budget"
