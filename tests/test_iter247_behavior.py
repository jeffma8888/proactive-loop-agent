"""Foundry iteration 277 -- bare ``make`` prints a help listing instead of installing.

What shipped, and why it needed an oracle
There was no ``.DEFAULT_GOAL`` and ``setup`` was the first rule, so the universal
"what does this repo do?" probe -- typing ``make`` with no target -- ran an
unannounced network install (``uv sync --locked``) on a repo whose headline property
is being offline-first. There was also no ``help`` target at all, so ten developer
entry points, each with real rationale in its own Makefile comment block, were listed
nowhere by the tool itself. This iteration makes the zero-argument path SAFE and
INFORMATIVE, and this module is the ratchet that reds the build when the NEXT
``.PHONY`` target ships without a help line.

Black-box by construction. Every assertion below is decided from TRACKED TEXT ONLY --
``Makefile``, ``README.md``, ``.github/workflows/ci.yml`` and the three test modules
that already pin pieces of this surface. No ``proactive_loop`` import, no subprocess,
no ``make`` execution, no ``tmp_path`` tree, no network, no clock, no gitignored path,
so this passes identically in a throwaway fresh clone and on both matrix legs.
Nothing here asserts on indentation or docstring text, so 3.12 and 3.13 cannot
diverge.

Five decisions worth the next reader's time
1. **The "no install, no fetch, no write" claim is scoped to the ``help`` recipe's own
   tab-indented steps, never to the Makefile TEXT.** The target's WHY comment
   legitimately explains what bare ``make`` used to do and so contains the words
   ``uv sync --locked``; a text-level ``"uv sync" not in MAKEFILE.read_text()`` would
   red on the EXPLANATION of the rule instead of a violation of it.
2. **And even inside a step, the ban is on the COMMAND WORD plus shell metacharacters
   OUTSIDE quotes -- not on substrings.** A help line is an ``echo`` whose quoted
   payload describes other targets, so it may legitimately contain ``uv``, ``make`` or
   ``pytest`` as prose. What actually guarantees the zero-argument path cannot install,
   fetch or write is: every command word is ``echo``, and no step carries an unquoted
   redirect, pipe, chain or command substitution. Both halves are asserted.
3. **The target matcher is HYPHEN-aware on both sides, and that is the whole guard.**
   A plain ``\\b`` boundary passes VACUOUSLY here: ``check-matrix`` contains ``check``
   and ``readme-headroom`` contains ``readme``, so a naive matcher would report the
   ``check`` target documented on the strength of a DIFFERENT target's line. Same rule
   ``tests/test_makefile_readme_contract._invocation`` decision 1 already establishes.
4. **The matcher is proven to FIRE, not merely to be green.** Behavior 5 runs it over
   two synthetic Makefile texts built as plain strings in-test: one omitting exactly
   one target's help line, one documenting ``check-matrix`` while leaving ``check``
   undocumented. A gate proven green but never proven to fail is a fail-open gate.
5. **Behavior 8 ("no graded gate step changes") is asserted against the tuple already
   pinned in ``tests/test_iter110_behavior.py``, NOT against ``git show HEAD:``.** A
   HEAD diff is the letter of "byte-identical at HEAD" but reds every FUTURE iteration
   during its own pre-commit stages, and it would red a legitimate later gate change
   that moved the pin honestly. Importing the pin tracks legitimate change and still
   catches the thing this iteration must not do: let the new target leak into the
   graded gate, or leave a ``make`` invocation without an explicit target so that
   flipping the default goal silently re-points a gate step. The byte-equality of
   ``ci.yml`` against ``HEAD`` was measured in the tester transcript instead; the
   substitution is recorded as PM feedback in ``tester.md``.
"""

from __future__ import annotations

import re

from pathlib import Path

import pytest

# The shipped guard's own helpers. Importing them -- rather than reimplementing the
# matcher -- is the point of behaviors 6 and 7: these are claims about the PINS AND
# PREDICATES THAT SHIPPED, and a private copy would only prove this file works.
from tests.test_iter110_behavior import (
    CI_GATE_STEPS,
    FRESHNESS_PRE_STEP,
)
from tests.test_iter183_behavior import (
    EXPECTED_PHONY_TARGETS as PHONY_PIN_183,
)
from tests.test_iter231_behavior import (
    EXPECTED_PHONY_TARGETS as PHONY_PIN_231,
)
from tests.test_makefile_readme_contract import (
    MARKER,
    MIN_PHONY_TARGETS,
    documents_target,
    phony_targets,
    readme_below_marker,
)

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = REPO / "Makefile"
README = REPO / "README.md"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

# Behavior 1: the exact `.PHONY` set AFTER this iteration -- the nine pre-existing
# entry points, all retained, plus `help`.
EXPECTED_PHONY_TARGETS = frozenset(
    {
        "help",
        "setup",
        "test",
        "cov",
        "typecheck",
        "readme-headroom",
        "demo",
        "clean",
        "check",
        "check-matrix",
    }
)
PREEXISTING_TARGETS = frozenset(EXPECTED_PHONY_TARGETS - {"help"})

# Behavior 2: the default goal, spelled twice over on purpose. Either half alone makes
# bare `make` print help; the pair also survives a `make` that ignores `.DEFAULT_GOAL`.
DEFAULT_GOAL_LINE = ".DEFAULT_GOAL := help"

# A Makefile rule head: `name:` at column 0. `[A-Za-z_]` as the first character
# deliberately excludes the dotted specials (`.PHONY`, `.DEFAULT_GOAL`), which are
# directives rather than rules -- proven non-vacuously in behavior 2c.
RULE_HEAD = re.compile(r"^(?P<name>[A-Za-z_][\w-]*)\s*:")

# Shell metacharacters that would let an `echo` step write, fetch or chain. Checked
# only OUTSIDE quoted spans -- see decision 2.
FORBIDDEN_UNQUOTED = (">", "<", "|", ";", "&", "$(", "`")

# The `help` recipe must never gain a second command word.
ALLOWED_HELP_COMMANDS = frozenset({"echo"})


# ==========================================================================
# Pure text helpers -- every one takes the Makefile TEXT, so the synthetic
# negative controls in behavior 5 need no file and no tmp_path.
# ==========================================================================


def recipe_lines(makefile_text: str, target: str) -> list[str]:
    """The tab-indented recipe lines of ``target:``, each stripped of surrounding space.

    Blank lines inside a recipe are tolerated; the first non-blank line that is not
    tab-indented ends the recipe. Pure ``#`` comment lines are dropped: a comment is
    not a step, and the ``help`` target's WHY block is exactly such a comment.
    """
    lines: list[str] = []
    in_target = False
    for line in makefile_text.splitlines():
        if RULE_HEAD.match(line) and RULE_HEAD.match(line)["name"] == target:
            in_target = True
            continue
        if not in_target:
            continue
        if line.startswith("\t"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(stripped)
        elif line.strip() == "":
            continue
        else:
            break
    return lines


def rules_in_order(makefile_text: str) -> list[str]:
    """Every rule name in file order, dotted directives excluded."""
    return [
        match["name"]
        for match in (RULE_HEAD.match(line) for line in makefile_text.splitlines())
        if match is not None
    ]


def command_word(step: str) -> str:
    """A recipe step's command word, with make's line prefixes dropped.

    ``@`` (silence), ``-`` (ignore errors) and ``+`` (always run) select make's
    ECHO/ERROR policy, not the command -- the same normalization
    ``tests/test_iter110_behavior._normalize`` performs.
    """
    return step.lstrip("@-+ ").strip().split(maxsplit=1)[0] if step.strip() else ""


def outside_quotes(step: str) -> str:
    """``step`` with every single- and double-quoted span removed.

    This is what makes decision 2 sound: an ``echo`` may legitimately print the words
    ``uv sync --locked`` or ``->`` inside its quoted payload, but an unquoted ``>`` is
    a redirect and an unquoted ``$(`` is command substitution.
    """
    return re.sub(r"\"[^\"]*\"|'[^']*'", "", step)


def target_mentions(recipe_text: str, target: str) -> bool:
    """Whether ``recipe_text`` names ``target`` as a whole, hyphen-bounded token.

    ``[\\w-]`` rather than ``\\b`` on both sides, so ``check-matrix`` never documents
    ``check`` and ``readme-headroom`` never documents ``readme``: see decision 3.
    """
    return re.search(rf"(?<![\w-]){re.escape(target)}(?![\w-])", recipe_text) is not None


def undocumented_in_help(makefile_text: str) -> list[str]:
    """The sorted ``.PHONY`` targets the ``help`` recipe never names.

    A pure function of the Makefile TEXT, so behavior 5 can prove it fires on planted
    text without touching the repo. Raises when the ``help`` recipe is empty rather
    than reporting "nothing undocumented": an empty haystack makes every membership
    check pass, which is the fail-open shape this repo keeps rediscovering.
    """
    targets = phony_targets(makefile_text)
    lines = recipe_lines(makefile_text, "help")
    assert lines, (
        "the `help` target has no tab-indented steps, so the help listing is empty "
        "and this check would report every target documented by vacuity"
    )
    recipe_text = "\n".join(lines)
    return sorted(t for t in targets if not target_mentions(recipe_text, t))


# ==========================================================================
# Synthetic negative controls (behavior 5). Plain strings, same SHAPE as the
# live Makefile, so the matcher is proven to FIRE and not merely to be green.
# ==========================================================================

# Omits exactly one target's help line: `cov`.
SYNTHETIC_ONE_OMITTED = (
    ".DEFAULT_GOAL := help\n"
    ".PHONY: help setup test cov\n"
    "\n"
    "# WHY: bare `make` used to run `uv sync --locked`, a network install.\n"
    "help:\n"
    '\t@echo "targets:"\n'
    '\t@echo "  make help     print this listing"\n'
    '\t@echo "  make setup    install the locked dependency set"\n'
    '\t@echo "  make test     run the full suite"\n'
    "\n"
    "setup:\n"
    "\tuv sync --locked\n"
)
SYNTHETIC_ONE_OMITTED_EXPECTS = ["cov"]

# Documents `check-matrix` while leaving `check` undocumented: the exact case a plain
# `\b` boundary passes VACUOUSLY.
SYNTHETIC_HYPHEN_TRAP = (
    ".DEFAULT_GOAL := help\n"
    ".PHONY: help check check-matrix readme-headroom\n"
    "\n"
    "help:\n"
    '\t@echo "  make help              print this listing"\n'
    '\t@echo "  make check-matrix      grade both interpreter legs"\n'
    '\t@echo "  make readme-headroom   report the published-floor headroom"\n'
)
SYNTHETIC_HYPHEN_TRAP_EXPECTS = ["check"]


# ==========================================================================
# Behavior 1 -- `.PHONY` widens to exactly ten targets
# ==========================================================================


def test_b1a_phony_declares_exactly_the_ten_expected_targets() -> None:
    live = phony_targets(MAKEFILE.read_text(encoding="utf-8"))
    assert live == EXPECTED_PHONY_TARGETS, (
        f"the Makefile's .PHONY set is {sorted(live)}, expected "
        f"{sorted(EXPECTED_PHONY_TARGETS)}. A target added here must also gain a "
        "`help` line and a README entry below the human-owned marker, and both "
        "exact-set pins (test_iter183, test_iter231) must move in the SAME commit."
    )


def test_b1b_every_pre_existing_entry_point_is_retained() -> None:
    """Stated separately from b1a so a REGRESSION reads differently from an ADDITION."""
    live = phony_targets(MAKEFILE.read_text(encoding="utf-8"))
    lost = sorted(PREEXISTING_TARGETS - live)
    assert not lost, (
        f"these developer entry points disappeared from .PHONY: {lost}. This "
        "iteration is additive -- `help` joins the nine, none of them is renamed, "
        "reordered or dropped."
    )
    assert "help" in live, "the `help` target is the deliverable and must be declared"


# ==========================================================================
# Behavior 2 -- the default goal is `help`, declared twice over
# ==========================================================================


def test_b2a_default_goal_directive_is_present() -> None:
    lines = [line.strip() for line in MAKEFILE.read_text(encoding="utf-8").splitlines()]
    assert DEFAULT_GOAL_LINE in lines, (
        f"no line reading {DEFAULT_GOAL_LINE!r} in the Makefile, so bare `make` falls "
        "back to the FIRST rule -- which is how the zero-argument path came to run a "
        "network install in the first place"
    )


def test_b2b_help_is_the_first_rule_in_the_file() -> None:
    rules = rules_in_order(MAKEFILE.read_text(encoding="utf-8"))
    assert rules, "no rules parsed from the Makefile -- the parser has lost its subject"
    assert rules[0] == "help", (
        f"the first rule in the Makefile is {rules[0]!r}, not 'help'. Being first is "
        "the belt to `.DEFAULT_GOAL`'s braces: it keeps bare `make` harmless even "
        "under a make that ignores the directive."
    )
    assert len(rules) >= len(EXPECTED_PHONY_TARGETS), (
        f"only {len(rules)} rules parsed ({rules}) -- fewer than the "
        f"{len(EXPECTED_PHONY_TARGETS)} declared .PHONY targets, so the rule-head "
        "parser has gone partially blind and 'help is first' would be near-vacuous"
    )


def test_b2c_the_rule_parser_excludes_dotted_directives() -> None:
    """Non-vacuity for b2b: `.PHONY` / `.DEFAULT_GOAL` must never count as rules."""
    synthetic = ".DEFAULT_GOAL := help\n.PHONY: help setup\n\nhelp:\n\t@echo hi\n\nsetup:\n\tuv sync\n"
    assert rules_in_order(synthetic) == ["help", "setup"], (
        "the rule-head parser must skip dotted directives; if it counted "
        "`.DEFAULT_GOAL` as the first rule, b2b would pass no matter where `help` sat"
    )


# ==========================================================================
# Behavior 3 -- the zero-argument path cannot install, fetch or write
# ==========================================================================


def test_b3a_the_help_recipe_has_steps_and_every_command_word_is_echo() -> None:
    steps = recipe_lines(MAKEFILE.read_text(encoding="utf-8"), "help")
    assert steps, "the `help` recipe has no tab-indented steps -- bare `make` prints nothing"
    offenders = sorted(
        {command_word(step) for step in steps} - ALLOWED_HELP_COMMANDS
    )
    assert not offenders, (
        f"the `help` recipe runs command word(s) {offenders}; only "
        f"{sorted(ALLOWED_HELP_COMMANDS)} is permitted. Bare `make` is the "
        "universal 'what is this?' probe on a public offline-first repo: it must "
        f"print and nothing else. Steps were {steps}."
    )


def test_b3b_no_help_step_can_redirect_fetch_or_chain() -> None:
    """The other half of decision 2: `echo` alone cannot write, but `echo >` can."""
    steps = recipe_lines(MAKEFILE.read_text(encoding="utf-8"), "help")
    assert steps, "the `help` recipe has no steps to inspect"
    for step in steps:
        bare = outside_quotes(step)
        found = sorted({token for token in FORBIDDEN_UNQUOTED if token in bare})
        assert not found, (
            f"help step {step!r} carries unquoted shell metacharacter(s) {found} "
            f"(unquoted remainder {bare!r}). A redirect, pipe, chain or command "
            "substitution would let the zero-argument path write or fetch."
        )
        assert "$(MAKE)" not in step, (
            f"help step {step!r} recurses into make -- the zero-argument path must "
            "not run another target"
        )


def test_b3c_the_unquoted_reducer_is_not_vacuous() -> None:
    """Prove `outside_quotes` keeps a real redirect and drops only quoted prose."""
    assert outside_quotes('@echo "run uv sync --locked -> installs"') == "@echo "
    assert ">" in outside_quotes('@echo "hello" > out.txt')
    assert "$(" in outside_quotes("@echo $(shell date)")


# ==========================================================================
# Behavior 4 -- every `.PHONY` target is documented in the help recipe
# ==========================================================================


def test_b4a_the_help_listing_documents_every_phony_target() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    missing = undocumented_in_help(text)
    assert not missing, (
        f"these .PHONY targets have no line in the `help` listing: {missing}. Bare "
        "`make` is now the tool's own index of its entry points, so a target absent "
        "from it is invisible to every reader who does not read the Makefile."
    )


def test_b4b_the_listing_teaches_each_target_in_make_invocation_form() -> None:
    """Stronger than b4a, and the same rule the README guard enforces.

    A bare token would let a target be "documented" by an unrelated word; the
    ``make <target>`` invocation form is a command a reader can actually copy.
    """
    lines = recipe_lines(MAKEFILE.read_text(encoding="utf-8"), "help")
    recipe_text = "\n".join(lines)
    missing = sorted(
        t for t in EXPECTED_PHONY_TARGETS if not documents_target(recipe_text, t)
    )
    assert not missing, (
        f"the `help` listing never teaches {missing} in runnable `make <target>` "
        f"form. Listing was:\n{recipe_text}"
    )


# ==========================================================================
# Behavior 5 -- the behavior-4 matcher is non-vacuous in BOTH directions
# ==========================================================================


def test_b5a_the_matcher_reports_zero_undocumented_targets_on_the_live_makefile() -> None:
    assert undocumented_in_help(MAKEFILE.read_text(encoding="utf-8")) == []


def test_b5b_the_matcher_names_the_one_target_whose_help_line_was_omitted() -> None:
    assert undocumented_in_help(SYNTHETIC_ONE_OMITTED) == SYNTHETIC_ONE_OMITTED_EXPECTS, (
        "the check must FIRE on a Makefile whose help listing omits exactly one "
        "target. A gate proven green but never proven to fail is a fail-open gate."
    )


def test_b5c_a_longer_hyphenated_target_never_documents_its_own_prefix() -> None:
    assert undocumented_in_help(SYNTHETIC_HYPHEN_TRAP) == SYNTHETIC_HYPHEN_TRAP_EXPECTS, (
        "`check-matrix` must not count as documentation of `check`, and "
        "`readme-headroom` must not count as documentation of `readme`. This is the "
        "exact case a plain \\b word boundary passes vacuously, because `-` is a "
        "non-word character."
    )


def test_b5d_an_empty_help_recipe_raises_instead_of_reporting_all_clear() -> None:
    with pytest.raises(AssertionError, match="no tab-indented steps"):
        undocumented_in_help(".PHONY: help setup\n\nhelp:\n\nsetup:\n\tuv sync\n")


# ==========================================================================
# Behavior 6 -- README documents `make help` BELOW the human-owned marker
# ==========================================================================


def test_b6a_readme_below_the_marker_documents_make_help() -> None:
    below = readme_below_marker(README.read_text(encoding="utf-8"))
    assert documents_target(below, "help"), (
        f"README.md never teaches `make help` below the {MARKER!r} marker. The new "
        "entry point must be documented in the reference half, which is the only "
        "half an automated contributor may edit."
    )


def test_b6b_the_frozen_intro_gained_nothing() -> None:
    readme = README.read_text(encoding="utf-8")
    above, separator, _ = readme.partition(MARKER)
    assert separator, f"README.md lost its {MARKER!r} marker"
    assert not documents_target(above, "help"), (
        "the `make help` entry landed ABOVE the human-owned PORTFOLIO INTRO marker. "
        "That block is frozen prose: only the three carve-out NUMBERS (collector "
        "count, CLI-verb count, test floor) may ever change there, and none of them "
        "moves in this iteration."
    )


def test_b6c_the_permanent_readme_guard_stays_green_against_the_widened_set() -> None:
    """The widened `.PHONY` set must not red `test_makefile_readme_contract`."""
    targets = phony_targets(MAKEFILE.read_text(encoding="utf-8"))
    below = readme_below_marker(README.read_text(encoding="utf-8"))
    assert len(targets) >= MIN_PHONY_TARGETS, (
        f"{len(targets)} targets parsed, below the guard's anti-vacuity floor "
        f"{MIN_PHONY_TARGETS}"
    )
    missing = sorted(t for t in targets if not documents_target(below, t))
    assert not missing, (
        f"adding a target widened the guard's domain without documenting it: {missing}"
    )


# ==========================================================================
# Behavior 7 -- both exact-set `.PHONY` snapshots moved in the same commit
# ==========================================================================


def test_b7_both_exact_set_phony_pins_equal_the_live_ten_target_set() -> None:
    live = phony_targets(MAKEFILE.read_text(encoding="utf-8"))
    for name, pin in (
        ("tests/test_iter183_behavior.EXPECTED_PHONY_TARGETS", PHONY_PIN_183),
        ("tests/test_iter231_behavior.EXPECTED_PHONY_TARGETS", PHONY_PIN_231),
    ):
        assert pin == EXPECTED_PHONY_TARGETS, (
            f"{name} is {sorted(pin)}, expected {sorted(EXPECTED_PHONY_TARGETS)}. "
            "Each is a frozenset compared with `==`, so a widened .PHONY reds that "
            "module unless the pin moves in the SAME commit as the Makefile."
        )
        assert pin == live, f"{name} disagrees with the live Makefile ({sorted(live)})"


# ==========================================================================
# Behavior 8 -- no graded gate step changes
# ==========================================================================


def test_b8a_the_check_recipe_still_runs_exactly_the_pinned_gate_steps() -> None:
    steps = recipe_lines(MAKEFILE.read_text(encoding="utf-8"), "check")
    normalized = {
        re.sub(r"\s+", " ", step.replace("$(MAKE)", "make")).lstrip("@-+ ").strip()
        for step in steps
    }
    normalized = {re.sub(r"\s*>\s*/dev/null(\s+2>&1)?$", "", s).strip() for s in normalized}
    allowed = set(CI_GATE_STEPS) | {FRESHNESS_PRE_STEP}
    extra = sorted(normalized - allowed)
    assert not extra, (
        f"the `check` recipe grew step(s) {extra} that no pin knows about. Adding a "
        "graded gate step is a four-module change (CI_GATE_STEPS, "
        "EXPECTED_CI_RUN_STEPS, the iter-102 copy, the iter-128 byte-equality pin) "
        "and is explicitly out of scope for this iteration."
    )
    lost = sorted(set(CI_GATE_STEPS) - normalized)
    assert not lost, f"the `check` recipe LOST pinned gate step(s) {lost}"


def test_b8b_the_new_target_did_not_leak_into_the_graded_gate() -> None:
    steps = recipe_lines(MAKEFILE.read_text(encoding="utf-8"), "check")
    for step in steps:
        assert not re.search(r"(?<![\w-])help(?![\w-])", step), (
            f"`check` step {step!r} invokes the help listing. `help` is a print-only "
            "developer entry point, not a gate step."
        )
    assert steps, "the `check` recipe is empty -- the local gate has lost its steps"
    assert "--fail-on-kind" in steps[-1] and "signals" in steps[-1], (
        "the armed `pla signals --fail-on-kind ...` self-scan must remain the LAST "
        f"step of `check`; last step is {steps[-1]!r}"
    )


def test_b8c_every_make_invocation_in_the_makefile_names_an_explicit_target() -> None:
    """Why the default-goal flip is safe: no gate ever relies on bare `make`.

    Scoped to EXECUTABLE steps whose command word is not ``echo`` -- a help line that
    prints the word ``make`` is documentation, not an invocation (the same
    documentation-versus-violation distinction as decision 1).
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    for target in sorted(phony_targets(text)):
        for step in recipe_lines(text, target):
            if command_word(step) == "echo":
                continue
            normalized = step.replace("$(MAKE)", "make")
            for match in re.finditer(r"(?<![\w-])make(?![\w-])", normalized):
                tail = normalized[match.end() :]
                assert re.match(r"[ \t]+[A-Za-z_][\w-]*", tail), (
                    f"`{target}` step {step!r} invokes make without an explicit "
                    "target, so flipping the default goal silently re-points it"
                )


def test_b8d_the_ci_workflow_never_invokes_make_without_a_target() -> None:
    for lineno, line in enumerate(CI_WORKFLOW.read_text(encoding="utf-8").splitlines(), 1):
        code = line.split("#", 1)[0]
        for match in re.finditer(r"(?<![\w-])make(?![\w-])", code):
            tail = code[match.end() :]
            assert re.match(r"[ \t]+[A-Za-z_][\w-]*", tail), (
                f"ci.yml:{lineno} invokes make without an explicit target: "
                f"{line.strip()!r}. Every CI step must name its target so the new "
                "default goal cannot change what CI grades."
            )
