"""Behavior tests for iteration 143: give the README's suite-size floor a real oracle.

The intro's ``**N,N00+ tests**`` claim is one of exactly three numbers the
``PORTFOLIO INTRO -- human-owned`` carve-out obliges automated contributors to keep
correct, and it was the only one of the three with no live source of truth: the guard
it replaces asserted a trailing ``+`` and a positive number, so it passed identically
on a stale ``2,700+`` (understating a 3,357-test suite by 657, 19.6%) and on a
fabricated ``9,000+``. This iteration bumped the published floor to ``3,300+`` in both
intro sentences and replaced that fail-open assertion with a two-sided oracle: the
floor must be TRUE (``live >= published``) and FRESH (``live - published < 500``),
with the live number measured by one real ``--collect-only`` subprocess.

The floor is a LIVE number, so this module owns re-bumping it: ``PUBLISHED_FLOOR``
and ``STALE_FLOOR_TOKEN`` move together every time suite growth pushes the published
claim past the slack budget (2,700+ -> 3,300+ at factory iter 143, 3,300+ -> 3,800+ at
factory iter 158, 3,800+ -> 4,300+ at factory iter 180, when the live suite reached
4,308, 4,300+ -> 4,700+ at factory iter 201, when it reached 4,720, and 4,700+ ->
4,800+ at factory iter 204, when a new behavior module carried it to 4,821, and
4,800+ -> 4,900+ at factory iter 207, when this iteration's behavior module carried
it to 4,905, 4,900+ -> 5,000+ at factory iter 212, when this iteration's behavior
module carried it to 5,027, and 5,000+ -> 5,100+ at factory iter 242, when this
iteration's behavior module carried it to 5,108, and 5,100+ -> 5,200+ at factory iter 245, when
this iteration's behavior module carried it to 5,203, and 5,200+ -> 5,300+ at factory
iter 251, when this iteration's behavior module carried it to 5,316, and 5,300+ -> 5,400+ at
factory iter 255, when this iteration's behavior module carried it to 5,413, and
5,400+ -> 5,500+ at factory iter 260, when this iteration's behavior module carried
it past 5,500, and 5,500+ -> 5,600+ at factory iter 263).

Coverage (numbered to match the iteration spec's Expected Behaviors):

1. The published floor is ``5,800+`` in BOTH intro sentences and the string
   ``5,700`` is gone from ``README.md`` entirely.
2. Nothing else above the marker changed: with the digits of the three permitted
   claims neutralized, the intro is byte-identical to the same slice at ``HEAD``
   (plus, while ``HEAD`` is still the pre-bump revision, the strict form -- putting
   ``STALE_FLOOR_TOKEN`` back reproduces ``HEAD`` byte-for-byte).
3. The sibling carve-out numbers stay live-accurate against independently computed
   oracles: ``17 context collectors`` == ``len(all_collectors())`` and ``15 CLI
   verbs`` == the live parser's subcommand count.
4. A pure, importable module-level helper decides the claim -- proven pure by
   breaking its module's ``subprocess`` handle and its file paths and calling it.
5. The real intro text and the real measured live count produce NO problems.
6. A fabricated (too-high) floor is rejected, and a problem names both numbers.
7. A true-but-stale floor is rejected, naming staleness / the slack budget.
8. An exact count (no ``+``) is still rejected.
9. A missing claim is rejected -- the guard cannot pass vacuously.
10. Slack is one named module constant ``= 500`` and the staleness verdict provably
    derives from it (shrink it -> the fresh claim fails; restore -> it passes).
11. The live count comes from a real collection subprocess and fails LOUDLY: a
    non-zero exit reports the exit code, and an unparseable total reports the exit
    code plus an output tail -- with no fallback, no static default and no skip.
12. The measured live count agrees with the published floor:
    ``live >= PUBLISHED_FLOOR`` and ``live - PUBLISHED_FLOOR < SUITE_SIZE_SLACK``.
13. The ``-o addopts=`` neutralization is pinned as load-bearing against
    ``pyproject.toml``'s live ``-n auto``.
14. The collection subprocess leaves the tree clean -- no ``.pytest_cache``, no
    ``.coverage``, no new entry in ``git status --porcelain``.
15. The guard module's docstring no longer claims "no subprocess" and describes the
    floor-AND-freshness contract.
16. The old fail-open assertion exists nowhere in ``tests/``.
17. The typecheck oracle is still wired (``make typecheck`` -> mypy over ``src/``).

Black-box: everything here drives published artifacts (``README.md``,
``pyproject.toml``, ``Makefile``, ``git``) or the guard module's public helpers with
synthetic inputs. No implementation source was read.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors
from tests import test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
PYPROJECT = REPO / "pyproject.toml"
MAKEFILE = REPO / "Makefile"
MARKER = "PORTFOLIO INTRO"

PUBLISHED_FLOOR = 5800
STALE_FLOOR_TOKEN = "5,700"

# The synthetic live count for the checks that feed the REAL published intro to the
# pure helper, so they need no second ``--collect-only`` subprocess. DERIVED from the
# published floor, never frozen: the intro is judged sound only when the live count
# sits at or just above that floor, so a hardcoded number silently pins the carve-out
# to one revision. Measured at factory iter 158 -- the 3357 frozen in from the
# ``3,300+`` era made the true, fresh ``3,800+`` floor read as FALSE and failed three
# tests across two modules. The offset is bounded on BOTH sides by the guard own
# rules: >= 0 or the claim is FALSE, < ``guard.SUITE_SIZE_SLACK`` (500) or it is
# STALE, and above the tightened budgets the staleness tests monkeypatch in (5 here,
# 10 in the sibling module) or those tests could not flip the verdict.
FRESH_LIVE_COUNT = PUBLISHED_FLOOR + 57

# The three numeric claims the README marker's carve-out permits an automated
# contributor to correct. Everything else above the marker is human-owned prose.
PERMITTED_CLAIMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\*\*[\d,]+\+ (?:passing )?tests\*\*"),
    re.compile(r"\d+ context collectors"),
    re.compile(r"\d+ CLI verbs"),
)


def _intro_of(text: str) -> str:
    """The slice of a README ABOVE the human-owned marker."""
    assert MARKER in text, "README lost its PORTFOLIO INTRO marker"
    return text.split(MARKER, 1)[0]


def _head_readme() -> str:
    proc = subprocess.run(
        ["git", "show", "HEAD:README.md"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"git show HEAD:README.md exited {proc.returncode}: {proc.stderr.strip()}"
    )
    return proc.stdout


def _neutralize_permitted(text: str) -> str:
    """Replace the digits INSIDE the three permitted claims with ``N``.

    Everything outside those three patterns keeps its bytes, so this normalization
    licenses exactly the carve-out and nothing more: reworded prose, a dropped
    bullet, a moved badge or a digit elsewhere all survive into the comparison.
    """
    out = text
    for pattern in PERMITTED_CLAIMS:
        out = pattern.sub(lambda m: re.sub(r"\d", "N", m.group(0)), out)
    return out


def _porcelain() -> set[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"git status exited {proc.returncode}"
    return {line for line in proc.stdout.splitlines() if line.strip()}


def _live_verb_count() -> int:
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return len(action.choices)
    raise AssertionError("the live CLI parser exposes no subcommands")


def _int_in(text: str, pattern: str) -> int:
    match = re.search(pattern, text)
    assert match is not None, f"the README intro no longer states {pattern!r}"
    return int(match.group(1))


def _joined(problems: object) -> str:
    assert isinstance(problems, (list, tuple)), (
        f"the helper must return a list or tuple, got {type(problems)!r}"
    )
    return "\n".join(str(p) for p in problems)


# --------------------------------------------------------------------------- #
# 1. the published floor is bumped in both places
# --------------------------------------------------------------------------- #


def test_readme_intro_publishes_the_bumped_floor_in_both_sentences() -> None:
    intro = _intro_of(README.read_text(encoding="utf-8"))
    assert "**5,800+ tests**" in intro
    assert "**5,800+ passing tests**" in intro


def test_the_stale_floor_token_is_gone_from_the_readme() -> None:
    """``5,400`` occurred exactly twice in ``README.md``, both above the marker."""
    assert STALE_FLOOR_TOKEN not in README.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 2. nothing else above the marker changed
# --------------------------------------------------------------------------- #


def test_the_permitted_claim_patterns_are_not_vacuous() -> None:
    """Guard the normalizer itself: each pattern must still match the live intro.

    Without this, a future rewording turns ``_neutralize_permitted`` into a silent
    no-op and behavior 2 starts passing for the wrong reason.
    """
    intro = _intro_of(README.read_text(encoding="utf-8"))
    head_intro = _intro_of(_head_readme())
    for pattern in PERMITTED_CLAIMS:
        assert pattern.search(intro) is not None, f"{pattern.pattern} matches no live intro text"
        assert pattern.search(head_intro) is not None, f"{pattern.pattern} matches no HEAD intro text"


def test_only_the_carve_out_numbers_moved_above_the_marker() -> None:
    intro = _intro_of(README.read_text(encoding="utf-8"))
    head_intro = _intro_of(_head_readme())
    assert _neutralize_permitted(intro) == _neutralize_permitted(head_intro), (
        "the human-owned README intro changed in something other than the three "
        "permitted numeric claims"
    )


def test_the_bump_is_exactly_two_digit_tokens_while_head_is_pre_bump() -> None:
    """Strict form of behavior 2, self-disarming once the bump is committed.

    Before the commit lands, ``HEAD`` still carries ``STALE_FLOOR_TOKEN``: putting it back must
    reproduce ``HEAD`` byte-for-byte, which proves the diff is the two digit tokens
    and nothing else. After the commit, ``HEAD`` == the worktree and the
    normalized comparison above is the whole contract, so this degenerates rather
    than going red in a fresh clone.
    """
    intro = _intro_of(README.read_text(encoding="utf-8"))
    head_intro = _intro_of(_head_readme())
    if STALE_FLOOR_TOKEN not in head_intro:
        assert intro == head_intro or _neutralize_permitted(intro) == _neutralize_permitted(
            head_intro
        )
        return
    assert intro.replace("5,800", STALE_FLOOR_TOKEN) == head_intro


# --------------------------------------------------------------------------- #
# 3. the sibling carve-out numbers stay live-accurate
# --------------------------------------------------------------------------- #


def test_collector_and_verb_counts_still_match_live_sources() -> None:
    intro = _intro_of(README.read_text(encoding="utf-8"))
    assert _int_in(intro, r"(\d+) context collectors") == len(all_collectors())
    assert _int_in(intro, r"(\d+) CLI verbs") == _live_verb_count()


# --------------------------------------------------------------------------- #
# 4. a pure, importable helper decides the floor claim
# --------------------------------------------------------------------------- #


def test_the_floor_decision_is_a_pure_importable_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    helper = getattr(guard, "suite_size_problems", None)
    assert callable(helper), (
        "tests/test_readme_and_ci_contract.py must expose a module-level "
        "suite_size_problems(intro_text, live_count) helper"
    )

    class Exploding:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"the helper must not touch subprocess.{name}")

    monkeypatch.setattr(guard, "subprocess", Exploding())
    monkeypatch.setattr(guard, "README", tmp_path / "absent-readme.md")
    monkeypatch.setattr(guard, "PYPROJECT", tmp_path / "absent-pyproject.toml")

    # Two-sided: prove the patched seam is LIVE (the impure sibling blows up through
    # it) before concluding anything from the pure helper surviving it.
    with pytest.raises(AssertionError):
        guard.collect_live_test_count()

    intro = _intro_of(README.read_text(encoding="utf-8"))
    assert _joined(helper(intro, FRESH_LIVE_COUNT)) == ""
    assert _joined(helper(intro, 99)) != ""


# --------------------------------------------------------------------------- #
# 6-9. the oracle is two-sided on synthetic inputs
# --------------------------------------------------------------------------- #


def _real_intro() -> str:
    return _intro_of(README.read_text(encoding="utf-8"))


def test_a_fabricated_floor_is_rejected_and_both_numbers_are_named() -> None:
    fabricated = _real_intro().replace("5,800+", "9,000+")
    problems = _joined(guard.suite_size_problems(fabricated, 3357))
    assert problems != "", "a floor ABOVE the live count must be rejected"
    assert "9,000" in problems or "9000" in problems
    assert "3,357" in problems or "3357" in problems


def test_a_true_but_stale_floor_is_rejected() -> None:
    stale = _real_intro().replace("5,800+", "1,000+")
    problems = _joined(guard.suite_size_problems(stale, 3357))
    assert problems != "", "a floor 2,357 below the live count must be rejected"
    lowered = problems.lower()
    assert "stale" in lowered or "slack" in lowered or str(guard.SUITE_SIZE_SLACK) in problems


def test_an_exact_count_is_still_rejected() -> None:
    exact = _real_intro().replace("5,800+", "5,157")
    problems = _joined(guard.suite_size_problems(exact, 3357))
    assert problems != "", "an exact count is self-invalidating and must be rejected"


def test_a_missing_claim_is_rejected_rather_than_passing_vacuously() -> None:
    stripped = PERMITTED_CLAIMS[0].sub("**a large suite**", _real_intro())
    assert guard.SUITE_CLAIM.search(stripped) is None, "the synthetic intro still has a claim"
    problems = _joined(guard.suite_size_problems(stripped, 3357))
    assert problems != "", "no claim at all must be a problem, not a pass"
    assert "claim" in problems.lower()


# --------------------------------------------------------------------------- #
# 10. slack is a single named constant and the verdict derives from it
# --------------------------------------------------------------------------- #


def test_slack_is_one_named_constant_the_verdict_derives_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert guard.SUITE_SIZE_SLACK == 500
    intro = _real_intro()
    assert _joined(guard.suite_size_problems(intro, FRESH_LIVE_COUNT)) == ""
    monkeypatch.setattr(guard, "SUITE_SIZE_SLACK", 5)
    tightened = _joined(guard.suite_size_problems(intro, FRESH_LIVE_COUNT))
    assert tightened != "", "the staleness verdict does not derive from SUITE_SIZE_SLACK"
    monkeypatch.undo()
    assert _joined(guard.suite_size_problems(intro, FRESH_LIVE_COUNT)) == ""


# --------------------------------------------------------------------------- #
# 5 + 11 + 12 + 14. one real collection subprocess, measured once
# --------------------------------------------------------------------------- #


def test_the_live_count_is_measured_and_agrees_with_the_published_floor() -> None:
    before = _porcelain()
    live = guard.collect_live_test_count()
    after = _porcelain()

    assert isinstance(live, int) and live > 0
    assert live >= PUBLISHED_FLOOR, (
        f"the README publishes a floor of {PUBLISHED_FLOOR} but only {live} tests collect"
    )
    assert live - PUBLISHED_FLOOR < guard.SUITE_SIZE_SLACK, (
        f"the published floor is {live - PUBLISHED_FLOOR} tests stale"
    )
    assert _joined(guard.suite_size_problems(_real_intro(), live)) == ""

    violations = guard.collection_tree_violations(before, after)
    assert violations == [], f"the collection subprocess dirtied the tree: {violations}"
    assert not [line for line in violations if ".pytest_cache" in line or ".coverage" in line], (
        f"the collection subprocess left pytest/coverage artifacts behind: {violations}"
    )


def test_a_broken_collection_fails_loudly_with_the_exit_code(tmp_path: Path) -> None:
    """A collection that finds nothing must raise, not fall back to a default."""
    with pytest.raises(AssertionError) as excinfo:
        guard.collect_live_test_count(cwd=tmp_path)
    message = str(excinfo.value)
    assert "collect-only" in message or "collection" in message
    assert re.search(r"exit(ed| code) \d+", message), message


def test_an_unparseable_total_fails_loudly_rather_than_defaulting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second loud-failure branch: exit 0 but no ``NNNN tests collected`` line.

    This is what a lost ``-o addopts=`` looks like -- pytest prints per-file counts
    under ``-n auto`` and no total at all -- so it is the branch a defensive
    fallback would turn back into a fail-open guard.
    """

    class FakeCompleted:
        returncode = 0
        stdout = "tests/test_a.py: 12\ntests/test_b.py: 30\n"
        stderr = ""

    class FakeSubprocess:
        @staticmethod
        def run(*args: object, **kwargs: object) -> FakeCompleted:
            return FakeCompleted()

    monkeypatch.setattr(guard, "subprocess", FakeSubprocess())
    with pytest.raises(AssertionError) as excinfo:
        guard.collect_live_test_count()
    message = str(excinfo.value)
    assert "tests collected" in message
    assert "addopts" in message
    assert "test_b.py: 30" in message, "the failure must include a tail of the output"


# --------------------------------------------------------------------------- #
# 13. the addopts neutralization is pinned as load-bearing
# --------------------------------------------------------------------------- #


def test_the_collection_args_neutralize_the_inherited_parallel_addopts() -> None:
    with PYPROJECT.open("rb") as fh:
        ini = tomllib.load(fh)["tool"]["pytest"]["ini_options"]
    addopts = ini["addopts"]
    assert "-n auto" in addopts, (
        "pyproject no longer inherits -n auto, so behavior 13's live anchor moved"
    )

    args = list(guard.COLLECT_ONLY_ARGS)
    assert "--collect-only" in args
    assert "-p" in args and "no:cacheprovider" in args
    pairs = list(zip(args, args[1:]))
    assert ("-o", "addopts=") in pairs, (
        "the collection command must neutralize the inherited addopts with "
        f"'-o addopts=', got {args}"
    )
    assert args[:2] == ["-m", "pytest"], "the child must be sys.executable -m pytest"
    assert guard.COLLECTED_TOTAL.pattern.startswith("^") and guard.COLLECTED_TOTAL.flags & re.M


# --------------------------------------------------------------------------- #
# 15-17. the docstring, the removed assertion, the typecheck oracle
# --------------------------------------------------------------------------- #


def test_the_guard_docstring_no_longer_claims_it_runs_no_subprocess() -> None:
    doc = " ".join((guard.__doc__ or "").split())
    assert doc, "the guard module lost its docstring"
    assert "no subprocess" not in doc.lower(), (
        "the module docstring still claims 'no subprocess' while the file runs one"
    )
    assert "subprocess" in doc and "collect-only" in doc
    assert "offline" in doc.lower()
    lowered = doc.lower()
    assert "true" in lowered and "fresh" in lowered, (
        "the suite-size bullet must describe the floor-AND-freshness contract"
    )
    assert "SUITE_SIZE_SLACK" in doc


def test_the_fail_open_suite_size_assertion_is_gone_from_the_repo() -> None:
    # Assembled from parts so this scan does not match its own source file.
    dead = "test_readme_states_the_suite_size_as_a" + "_floor_not_an_exact_count"
    hits = [
        path.name
        for path in sorted((REPO / "tests").glob("*.py"))
        if dead in path.read_text(encoding="utf-8")
    ]
    assert hits == [], f"the fail-open assertion still exists in {hits}"
    assert hasattr(guard, "test_readme_suite_size_claim_is_a_true_and_fresh_floor")


def test_the_typecheck_oracle_is_still_wired() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "typecheck:" in makefile
    assert "mypy" in makefile and "src/proactive_loop" in makefile
