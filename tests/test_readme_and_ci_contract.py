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
* the suite-size claim       -> must be a **floor** (``3,800+ tests``) that is
  both TRUE and FRESH against a real collection. Three ways it can be wrong, and
  all three now fail the build: an exact count (self-invalidating -- adding this
  very file changes it), a floor ABOVE the live total (a false boast), and a
  floor more than ``SUITE_SIZE_SLACK`` BELOW it (true, but rotting -- which is
  how this very claim reached a public README understating the suite by 657
  tests, 19.6%, having also been ~150 stale on the day it was hand-written).
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

Offline, and cheap by design: the guards read two files and import the package,
plus exactly ONE local ``sys.executable -m pytest --collect-only`` subprocess over
this suite -- the only oracle that can prove the suite-size floor. A static ``ast``
count of ``test_*`` functions cannot: measured at ``factory iter 143`` it yields
2,477 across 156 files against a 3,357-test collection, i.e. BELOW the published
floor, because ``parametrize`` expands at collection time. (One further
collect-only run, over an EMPTY temp directory, is the known-bad sample proving
that oracle fails LOUDLY rather than falling back; it collects nothing.) Neither
run touches the network or writes anything (``-p no:cacheprovider``), and there is
still no YAML dependency (the workflow is checked as text on purpose -- ``pyyaml``
is deliberately not a dependency of this project).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
MARKER = "PORTFOLIO INTRO"
CLI_HEADING = "## CLI"
PYPROJECT = REPO / "pyproject.toml"

# How far the published suite-size floor may fall BELOW the live collection before
# the claim counts as STALE and must be re-rounded. The ONE knob: retune it here,
# nowhere else.
#
# 500, deliberately not 1000. Drift measures ~+49 tests per ship, so 500 buys ~10
# iterations before a forced digit bump while capping the worst PERMITTED
# understatement at 499 -- strictly better than the 657-test understatement this
# constant was introduced to end. A slack of 1000 would license a 999-test
# understatement, i.e. a WORSE public artifact than the defect being fixed. A slack
# of 0 is the opposite failure: it would manufacture a red badge on a PUBLIC repo
# every ~2 ships, and a guard that cries wolf gets deleted.
SUITE_SIZE_SLACK = 500

# The intro's bolded suite-size claim: ``**3,800+ tests**`` and
# ``**3,800+ passing tests**``. Group 1 is the digits, group 2 the trailing ``+``.
# Deliberately the SAME pattern the removed fail-open assertion used, so the new
# oracle inherits its proven match set (both intro claims) rather than inventing a
# second pattern that could quietly match one of them.
SUITE_CLAIM = re.compile(r"\*\*([\d,]+)(\+?)[^*]*tests\*\*")

# The arguments after ``sys.executable`` for the one collection subprocess.
#
# ``-o addopts=`` is LOAD-BEARING, not tidiness: ``pyproject.toml`` sets
# ``addopts = "-q -n auto"``, and under an inherited ``-n auto`` this command
# prints per-file counts and NO ``NNNN tests collected`` total line at all. A guard
# that lost the neutralization would therefore parse nothing -- and with any
# defensive fallback it would pass VACUOUSLY, which is the exact failure class this
# whole change exists to remove. ``test_the_collection_command_neutralizes_the_
# inherited_addopts`` pins the coupling.
#
# ``-p no:cacheprovider`` is equally deliberate: the release gate reads
# ``git status --porcelain``, so a nested run must not create ``.pytest_cache``.
COLLECT_ONLY_ARGS: tuple[str, ...] = (
    "-m",
    "pytest",
    "--collect-only",
    "-q",
    "-o",
    "addopts=",
    "-p",
    "no:cacheprovider",
)

# pytest's serial one-line total, e.g. ``3357 tests collected in 0.52s``.
# Multiline-anchored: it is the last line of a ``-q`` collection, never the first.
COLLECTED_TOTAL = re.compile(r"^(\d+) tests collected", re.MULTILINE)

# Generous: the measured cost is 0.52s collect / 0.91s wall warm, but a cold
# import of 156 test modules on a loaded machine is slower, and a hang must fail
# with a clear TimeoutExpired rather than wedging the suite.
COLLECT_TIMEOUT = 180

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
# reverse guard is scoped to the ``## CLI`` section: all three of these live
# outside it. Pinned as an EXACT list rather than added to ``EXEMPT_FLAGS``, so a
# FOURTH such token still fails the build instead of being silently forgiven.
#   ``--first-success``  shields.io escapes a literal dash as ``--`` in the
#                        Offline badge, inside the human-owned intro.
#   ``--locked``         the Quickstart installs with ``uv sync --locked``. It is
#                        a `uv` flag, and it is exactly what makes that line
#                        honest: a bare ``uv sync`` may resolve and mutate
#                        ``uv.lock``, which is what CI forbids.
#   ``--no-verify``      the "Pre-commit hook (opt-in)" section names git's own
#                        escape hatch, ``git commit --no-verify``. It is a `git`
#                        flag, and documenting it is what keeps a hook that fails
#                        CLOSED from being a trap: a reader whose environment
#                        cannot resolve the CLI needs a stated way past the gate.
FOREIGN_FLAG_TOKENS = ["--first-success", "--locked", "--no-verify"]


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


def _mentions_flag(section_text: str, flag: str) -> bool:
    """True when ``flag`` occurs as a WHOLE option token in ``section_text``.

    A bare substring test is not enough once one live flag is a PREFIX of
    another: ``--out`` occurs inside ``watch --out-dir``, so a section that
    documents only ``--out-dir`` would silently satisfy ``--out`` and the
    forward guard would stop reporting a genuinely undocumented required flag.
    Requiring the next character to be one that cannot continue an option name
    keeps the match honest -- the same reasoning ``_mentions_short_form`` applies
    to ``-v`` inside ``--version``, now applied to long options too.
    """
    return re.search(rf"{re.escape(flag)}(?![A-Za-z0-9-])", section_text) is not None


def _mentions_short_form(section_text: str, alias: str) -> bool:
    """True when a documented short alias occurs as its own token.

    ``-v`` occurs inside ``--version``, so a plain substring test would let a
    section that never teaches ``-v`` exempt ``--verbose``.
    """
    return re.search(rf"(?<![\w-]){re.escape(alias)}(?![A-Za-z0-9-])", section_text) is not None


def missing_flags(section_text: str, universe: Iterable[str]) -> list[str]:
    """Sorted live flags absent from ``section_text`` (a documented short form counts)."""
    missing = [
        flag
        for flag in set(universe) - EXEMPT_FLAGS
        if not _mentions_flag(section_text, flag)
        and not any(
            _mentions_short_form(section_text, short)
            for short in DOCUMENTED_SHORT_FORMS.get(flag, ())
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


def _published_floor_for(live_count: int) -> int:
    """The floor to publish for ``live_count``: rounded DOWN to the nearest 100.

    Rounding DOWN is what keeps the published claim a true floor, and the
    ``N,N00+`` shape is the operator's: never an exact count, which is stale on
    the next commit. Every failure message names this value, so a forced bump is
    a copy-paste rather than a judgement call.
    """
    return (live_count // 100) * 100


def suite_size_problems(intro_text: str, live_count: int) -> list[str]:
    """Human-readable problems with the intro's suite-size claim; empty when sound.

    PURE -- no file read, no subprocess -- so the guard can be proven two-sided
    from synthetic strings. That matters here more than usual: the assertion this
    replaces checked only for a trailing ``+`` and a positive number, so it passed
    identically on the stale ``2,700+`` it was supposed to catch and on a
    fabricated ``9,000+``. Of the three numbers the README carve-out obliges
    automated contributors to keep correct, the loudest was the only one whose
    guard could not fail.

    Checks, in the order a reader cares about them:

    1. NO claim at all -> a problem. Without this the guard passes vacuously on an
       intro whose claim was reworded away.
    2. An EXACT count (no ``+``) -> a problem. Preserved from the old assertion:
       the freshness rule must not be bought by trading away the floor rule.
    3. ``live < floor`` -> a problem. The claim is FALSE, not merely stale; this is
       the direction the old guard was blind to.
    4. ``live - floor >= SUITE_SIZE_SLACK`` -> a problem. True but rotted.

    ``SUITE_SIZE_SLACK`` is read as a module global at call time on purpose, so a
    test can monkeypatch it and prove the staleness verdict really derives from
    the named constant instead of a number inlined here.
    """
    claims = list(SUITE_CLAIM.finditer(intro_text))
    suggested = _published_floor_for(live_count)
    if not claims:
        return [
            "the README intro makes no bolded claim about the suite size -- expected "
            f"something like '**{suggested:,}+ tests**'. With no claim to check, this "
            "guard would pass vacuously while the public README says nothing about a "
            "suite that is one of the project's headline claims."
        ]

    problems: list[str] = []
    for match in claims:
        claim = match.group(0)
        floor = int(match.group(1).replace(",", ""))
        if match.group(2) != "+":
            problems.append(
                f"the intro states an exact test count in {claim!r}. State a floor "
                f"like '**{suggested:,}+ tests**' instead: an exact count is stale "
                "the moment the next test lands, and this block is human-owned, so "
                "the loop that breaks it cannot fix it."
            )
            continue
        if floor <= 0:
            problems.append(
                f"nonsensical test-count floor in {claim!r}; publish "
                f"'**{suggested:,}+ tests**'"
            )
            continue
        if live_count < floor:
            problems.append(
                f"the intro claims {claim!r} but a live collection finds only "
                f"{live_count:,} tests: the published floor ({floor}) is ABOVE the "
                f"live count ({live_count}), so the claim is FALSE, not merely "
                f"stale. Publish '**{suggested:,}+ tests**' -- the live count "
                "rounded DOWN to the nearest 100. The README marker's carve-out "
                "permits editing this number."
            )
        elif live_count - floor >= SUITE_SIZE_SLACK:
            problems.append(
                f"the intro's floor {claim!r} is stale: it understates the live "
                f"suite by {live_count - floor:,} tests (live {live_count:,}, i.e. "
                f"{live_count}), which is at or past the slack budget "
                f"SUITE_SIZE_SLACK = {SUITE_SIZE_SLACK}. Replace it with "
                f"'**{suggested:,}+ tests**' -- the live count rounded DOWN to the "
                "nearest 100, so it stays a true floor. The README marker's "
                "carve-out permits editing this number."
            )
    return problems


def collect_env() -> dict[str, str]:
    """Environment for the collection child: no inherited pytest config, no coverage.

    Both removals are load-bearing, and neither is covered by ``-o addopts=``:

    * ``PYTEST_ADDOPTS`` is a SEPARATE channel from the ini ``addopts`` that
      ``-o`` overrides, so an ambient one (a developer shell, a CI step) would
      re-inject flags -- including ``-n auto`` -- and delete the total line the
      parse depends on. The xdist worker variables are dropped for the same
      reason: the child must not believe it is a worker of the outer run.
    * ``COV_CORE_*`` is how pytest-cov starts coverage inside CHILD processes. Left
      in place, a collection run under ``make cov`` would write
      ``.coverage.<host>.<pid>`` files into the repo root -- the tree the release
      gate reads with ``git status --porcelain``, and the same shared artifact
      iteration 52's oracles assert on.
    """
    env = dict(os.environ)
    for key in (
        "PYTEST_ADDOPTS",
        "PYTEST_CURRENT_TEST",
        "PYTEST_XDIST_WORKER",
        "PYTEST_XDIST_WORKER_COUNT",
    ):
        env.pop(key, None)
    for key in [k for k in env if k.startswith("COV_CORE")]:
        env.pop(key, None)
    return env


def collect_live_test_count(
    cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> int:
    """The live number of collected tests, from ONE real ``--collect-only`` run.

    A real collection is the only sound oracle for the published floor: static
    counting undercounts badly because ``parametrize`` expands at collection time
    (2,477 ``test_*`` functions across 156 files against a 3,357-test collection,
    measured at ``factory iter 143``), and an undercount can never prove
    ``live >= published``.

    FAILS LOUDLY, with no fallback path. A non-zero exit or an unparseable total
    raises with the exit code and a tail of the output; there is deliberately no
    default, no cached constant and no ``skip``, because every one of those would
    turn a broken oracle back into the fail-open guard this replaced.
    """
    proc = subprocess.run(
        [sys.executable, *COLLECT_ONLY_ARGS],
        cwd=str(REPO if cwd is None else cwd),
        capture_output=True,
        text=True,
        timeout=COLLECT_TIMEOUT,
        env=dict(collect_env() if env is None else env),
    )
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-20:])
    assert proc.returncode == 0, (
        f"pytest --collect-only exited {proc.returncode} (expected 0), so the live "
        "suite size is unknown and the README's floor cannot be verified. Fix the "
        f"collection error rather than the claim. Output tail:\n{tail}"
    )
    match = COLLECTED_TOTAL.search(proc.stdout)
    assert match is not None, (
        "could not parse a '<N> tests collected' total from the collection output "
        f"(exit code {proc.returncode}). The most likely cause is a lost "
        f"'-o addopts=' -- under the inherited '-n auto' pytest prints per-file "
        f"counts and no total at all. Output tail:\n{tail}"
    )
    return int(match.group(1))


def pytest_ini_options() -> dict[str, Any]:
    """The live ``[tool.pytest.ini_options]`` table, straight off ``pyproject.toml``."""
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    ini = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert isinstance(ini, dict), (
        "pyproject.toml has no [tool.pytest.ini_options] table"
    )
    return ini


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


def test_readme_suite_size_claim_is_a_true_and_fresh_floor() -> None:
    """The third carve-out number, bound to a real collection at last.

    This replaces an assertion that checked only for a trailing ``+`` and a
    positive number, and therefore passed on the stale ``2,700+`` (657 tests,
    19.6% under) exactly as happily as it would on a fabricated ``9,000+``.
    """
    problems = suite_size_problems(_intro(), collect_live_test_count())
    assert problems == [], (
        "the README intro's suite-size claim no longer matches the live suite:\n  - "
        + "\n  - ".join(problems)
    )


def test_suite_size_guard_rejects_a_fabricated_floor() -> None:
    """Known-bad sample, the direction the old guard could not see."""
    problems = suite_size_problems("**9,000+ tests** and more prose", 3357)
    assert problems, "a floor above the live count must be rejected as FALSE"
    assert any("9,000" in p and "3357" in p for p in problems), problems


def test_suite_size_guard_rejects_a_true_but_stale_floor() -> None:
    """``1,000+`` is TRUE for a 3,357-test suite -- and passed the old assertion."""
    problems = suite_size_problems("**1,000+ tests**", 3357)
    assert problems, "a floor 2,357 below the live count must be rejected as stale"
    joined = " ".join(problems).lower()
    assert "stale" in joined and "slack" in joined, problems
    assert "3,300+" in " ".join(problems), (
        "the failure must name the exact replacement floor, or a forced bump "
        f"becomes a judgement call: {problems}"
    )


def test_suite_size_guard_still_rejects_an_exact_count() -> None:
    """The freshness rule must not be bought by trading away the floor rule."""
    problems = suite_size_problems("**3,357 tests**", 3357)
    assert problems, "an exact count must still be rejected"
    assert any("exact" in p for p in problems), problems


def test_suite_size_guard_rejects_a_missing_claim() -> None:
    """An intro with the claim reworded away must not pass vacuously."""
    assert suite_size_problems("# Title\n\nno bolded suite claim here\n", 3357)


def test_suite_size_slack_is_the_single_staleness_knob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verdict must derive from the named constant, not an inlined number."""
    assert SUITE_SIZE_SLACK == 500
    intro = _intro()
    # A synthetic live count keeps this test pure (no second subprocess), but it must
    # be DERIVED from what the intro actually publishes rather than frozen: the claim
    # is sound only when the live count sits at or just above the published floor, so
    # a hardcoded number pins the carve-out to one revision of the README. Measured at
    # factory iter 158 -- a 3357 frozen in from the ``3,300+`` era made the true,
    # fresh ``3,800+`` floor read as FALSE here. The +57 keeps the value TRUE
    # (>= the floor) and FRESH (well inside SUITE_SIZE_SLACK) while staying above the
    # tightened budget below, which must still flip the verdict.
    claim = SUITE_CLAIM.search(intro)
    assert claim is not None, "the intro lost its bolded suite-size claim"
    live = int(claim.group(1).replace(",", "")) + 57
    assert suite_size_problems(intro, live) == []
    monkeypatch.setattr(
        "tests.test_readme_and_ci_contract.SUITE_SIZE_SLACK", 10, raising=True
    )
    assert suite_size_problems(intro, live), (
        "shrinking SUITE_SIZE_SLACK did not change the verdict, so the staleness "
        "budget is hardcoded somewhere inside the helper instead of read from the "
        "named constant"
    )
    monkeypatch.undo()
    assert suite_size_problems(intro, live) == []


def test_the_collection_command_neutralizes_the_inherited_addopts() -> None:
    """Pin the coupling between the live ``addopts`` and ``-o addopts=``.

    Without the neutralization the same command inherits ``-n auto``, prints
    per-file counts and NO ``NNNN tests collected`` line at all -- measured, not
    theorised. So a guard that lost the pair would parse nothing, and any
    defensive fallback would then read as green: the fail-open shape this
    iteration removes, reintroduced by an unrelated config edit.
    """
    addopts = pytest_ini_options().get("addopts", "")
    assert isinstance(addopts, str) and "-n auto" in addopts, (
        "pyproject.toml no longer sets '-n auto' in addopts. If parallelism moved, "
        "re-derive whether the collection subprocess still needs '-o addopts=' "
        f"before deleting it; addopts is currently {addopts!r}"
    )
    pairs = list(zip(COLLECT_ONLY_ARGS, COLLECT_ONLY_ARGS[1:]))
    assert ("-o", "addopts=") in pairs, (
        f"the collection command lost its '-o addopts=' pair: {COLLECT_ONLY_ARGS}"
    )
    assert ("-p", "no:cacheprovider") in pairs, (
        "the collection command lost '-p no:cacheprovider', so a nested run can "
        f"write .pytest_cache into the tree the release gate reads: {COLLECT_ONLY_ARGS}"
    )


def test_collect_live_test_count_fails_loudly_on_a_broken_collection(
    tmp_path: Path,
) -> None:
    """The fail-loud path, proven on a known-bad sample.

    An empty directory collects nothing, so pytest exits 5. The guard must raise
    with that exit code and an output tail -- never fall back to a default, a
    static count or a skip, all of which would restore a fail-open guard.
    """
    with pytest.raises(AssertionError) as excinfo:
        collect_live_test_count(cwd=tmp_path)
    message = str(excinfo.value)
    assert "exited 5" in message, message
    assert "collect" in message.lower(), message


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
    token and a foreign tool's flag for the same reason, and the pre-commit
    section's ``git commit --no-verify`` is the third. Pinning the exact list
    keeps that decision from being quietly "simplified" later: a FOURTH such
    token must fail the build and be justified here, not silently forgiven.
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
