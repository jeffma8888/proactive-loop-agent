"""Black-box verification of factory iteration 259: the pytest suite escalates
every warning to an error, declared once in ``pyproject.toml``.

MODULE NAME, derived from the repo and never from the state-dir counter. The two
counters differ here (state dir ``iter-259``, offset 22, and the offset is NOT
guaranteed), so the name was derived the mandated way: ``git ls-files tests``
holds 256 files whose highest ``test_iterNN_behavior.py`` is ``236``, +1 = ``237``,
and ``git cat-file -e HEAD:tests/test_iter237_behavior.py`` FAILED before a byte
was written -- measured verbatim: ``fatal: path
'tests/test_iter237_behavior.py' does not exist in 'HEAD'``. The worktree path
was absent too, so nothing was overwritten.

ISOLATION CONTRACT, honored. Nothing under ``src/`` was read; no engineer or
reviewer note, no ``IMPLEMENTATION.patch``, and no ``git diff`` was opened. The
artifact under test here IS tracked configuration text, so every assertion
either parses ``pyproject.toml`` with ``tomllib`` exactly as a pytest consumer
would, or exercises the live filter in-process through the public ``warnings``
module. No test in this module re-runs pytest as a subprocess and none passes
``-W`` on a command line.

WHY THIS ITERATION EXISTS. Before this change ``[tool.pytest.ini_options]`` held
exactly ``testpaths`` and ``addopts``, so a warning raised anywhere in the suite
was printed to a scrollback nobody reads and then forgotten. That is the failure
class that stays invisible until it is a hard break, on a PUBLIC portfolio repo
whose stated bar already includes strict ``mypy``, a locked install and a
two-interpreter CI matrix. ``filterwarnings = ["error"]`` converts the silent
class into a red build at the moment the repo itself bumps its lock or adds an
interpreter -- the two moments a maintainer wants to be told.

DISCRIMINATION, MEASURED BY THIS STAGE RATHER THAN INHERITED. Behaviors 3 and 4
are the two-sided pair: this module was run against its own repo config and then
re-run with the single option neutralised (``-o filterwarnings=``), which is the
narrowest possible control -- one ini key, nothing else in the tree touched. The
recorded arms are in the tester report for this iteration. Behavior 5 is
LABELLED non-discriminating and its own docstring repeats the label, because it
passes in both arms; it is a forward-compatibility pin and must never be read as
evidence the filter landed.

DURABILITY OF THE RATCHET. Behavior 6 is the part that keeps working after this
iteration: it fails the build if anyone appends an ``ignore`` entry to the list,
so tolerating a warning becomes a visible reviewed edit to this oracle instead
of a silent one-line append. Behavior 7 pins the single declaration point -- no
``-W`` in any recipe, no second ini file, and no per-test carve-out smuggled
into an existing module.

SUITE-SIZE NOTE, stated because it shaped this module and a reader deserves to
know. The repo publishes a rounded ``5,500+ tests`` floor in its README, and
``tests/test_iter204_behavior.py`` reds the build the moment the collected count
crosses the next hundred. HEAD collects 5,489, so this module had a budget of 10
new test FUNCTIONS, not of assertions. Every assertion the eight behaviors call
for is present; behavior 7's two halves share one function and behavior 8's two
halves share one function purely to stay inside that budget. The floor bump
itself is a ~25-site coupled edit across the README and four test modules
(``test_iter143``, ``test_iter171``, ``test_iter204``, ``test_iter234``), which is
its own iteration and is reported as such in this iteration's tester notes.

OFFLINE AND DETERMINISTIC: no network, no clock, no sleeps, no duration
asserted. Every fact comes from tracked text or from an in-process ``warnings``
call. Nothing reads gitignored local state, so a throwaway fresh clone verifies
identically (the iteration-154 trap): the only ambient dependency is ``git``
itself in behavior 8, which SKIPS rather than fails when history is unavailable.
"""

from __future__ import annotations

import subprocess
import tomllib
import warnings
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
UV_LOCK = REPO / "uv.lock"

#: Pre-existing ``[tool.pytest.ini_options]`` keys and their shipped values, as
#: they stood before this iteration. Hardcoded ON PURPOSE rather than diffed
#: against the HEAD blob: once this iteration's commit lands, HEAD *is* the
#: post-change file, so a HEAD comparison would quietly become tautological.
SHIPPED_ADDOPTS = "-q -n auto"
SHIPPED_TESTPATHS = ["tests"]

#: Files that could each independently declare a pytest ``filterwarnings``. The
#: ini must stay the SINGLE declaration point, so a second one is a drift
#: surface even when it agrees.
RIVAL_INI_FILES = ("pytest.ini", "setup.cfg", "tox.ini", ".pytest.ini")

#: Recipes that grade the suite. None of them may carry a ``-W`` flag.
RECIPES = ("Makefile", ".github/workflows/ci.yml", "hooks/pre-commit")


def _ini_options() -> dict[str, Any]:
    """The live ``[tool.pytest.ini_options]`` table, straight off the artifact."""
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    ini = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert isinstance(ini, dict), "pyproject.toml has no [tool.pytest.ini_options] table"
    return ini


def _filterwarnings() -> list[str]:
    ini = _ini_options()
    assert "filterwarnings" in ini, (
        "[tool.pytest.ini_options] declares no filterwarnings key, so every warning the "
        f"suite raises is printed and forgotten; keys present: {sorted(ini)}"
    )
    value = ini["filterwarnings"]
    return value  # type: ignore[no-any-return]


def _git(*args: str) -> str | None:
    """Run a read-only git command; return stdout, or ``None`` if git/history is absent."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


# ---------------------------------------------------------------------------
# Behavior 1 -- the key is DECLARED, and its value is exactly ["error"].
# ---------------------------------------------------------------------------


def test_b1_pyproject_declares_filterwarnings_error() -> None:
    """``[tool.pytest.ini_options].filterwarnings`` is a list of str == ["error"]."""
    value = _filterwarnings()
    assert isinstance(value, list), (
        f"filterwarnings must be a list of strings (pytest ini type linelist), got {type(value).__name__}: {value!r}"
    )
    assert all(isinstance(entry, str) for entry in value), (
        f"every filterwarnings entry must be a string, got {[type(e).__name__ for e in value]}"
    )
    assert value == ["error"], f"filterwarnings must be exactly ['error'], got {value!r}"


# ---------------------------------------------------------------------------
# Behavior 2 -- the change is ADDITIVE: no pre-existing key removed or edited.
# ---------------------------------------------------------------------------


def test_b2_the_change_is_additive_and_edits_no_pre_existing_key() -> None:
    """``addopts`` and ``testpaths`` survive byte-for-byte alongside the new key.

    ``addopts`` is pinned by three already-shipped modules, so an edit there is a
    multi-module break; ``testpaths`` had NO oracle at all before this test, which
    is exactly why a silent edit to it was possible.
    """
    ini = _ini_options()

    assert ini.get("addopts") == SHIPPED_ADDOPTS, (
        f"[tool.pytest.ini_options].addopts must still be exactly {SHIPPED_ADDOPTS!r} "
        f"(xdist parallelism + quiet output), got {ini.get('addopts')!r}"
    )
    assert ini.get("testpaths") == SHIPPED_TESTPATHS, (
        f"[tool.pytest.ini_options].testpaths must still be exactly {SHIPPED_TESTPATHS!r}, "
        f"got {ini.get('testpaths')!r}"
    )

    required = {"testpaths", "addopts", "filterwarnings"}
    missing = sorted(required - set(ini))
    assert not missing, f"[tool.pytest.ini_options] lost pre-existing key(s): {missing}"


# ---------------------------------------------------------------------------
# Behavior 3 -- the filter is LIVE, not merely declared (DISCRIMINATING).
# ---------------------------------------------------------------------------


def test_b3_a_deprecation_warning_raises_inside_an_unmarked_test() -> None:
    """A DeprecationWarning raised in a test carrying no mark becomes an exception.

    TWO-SIDED: with the ini key neutralised (``-o filterwarnings=``) this test
    FAILS, because ``warnings.warn`` merely records the warning and returns. It is
    the primary evidence that the declaration is in force rather than decorative.
    """
    with pytest.raises(DeprecationWarning) as excinfo:
        warnings.warn("iter259 live-filter probe: deprecation", DeprecationWarning, stacklevel=2)
    assert "iter259 live-filter probe: deprecation" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Behavior 4 -- the escalation is category-agnostic (DISCRIMINATING).
# ---------------------------------------------------------------------------


def test_b4_a_userwarning_raises_too_so_the_action_is_category_agnostic() -> None:
    """A bare ``error`` action carries no category, so UserWarning raises as well.

    TWO-SIDED alongside behavior 3: it also FAILS with the ini key neutralised.
    A filter written ``error::DeprecationWarning`` would pass behavior 3 and fail
    this one, so the pair distinguishes the shipped bare action from a narrower
    category-scoped one.
    """
    with pytest.raises(UserWarning) as excinfo:
        warnings.warn("iter259 live-filter probe: user", UserWarning, stacklevel=2)
    assert "iter259 live-filter probe: user" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Behavior 5 -- the per-test escape hatch still works (NON-DISCRIMINATING PIN).
# ---------------------------------------------------------------------------


@pytest.mark.filterwarnings("default")
def test_b5_a_test_that_must_observe_a_warning_still_can() -> None:
    """A test may still RECORD a warning instead of being broken by the ratchet.

    HONEST LABEL, PASSES IN BOTH ARMS: this test passes with the ini key present
    AND with it absent, so it is NOT evidence that the filter landed -- behaviors
    3 and 4 are the discriminating pair. Its value is forward-compatibility: it
    proves a future test that legitimately needs to inspect a warning has a
    per-test hatch and is never forced to weaken the ini declaration.
    """
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        warnings.warn("iter259 escape-hatch probe", DeprecationWarning, stacklevel=2)

    assert len(recorded) == 1, f"expected exactly one recorded warning, got {len(recorded)}"
    assert recorded[0].category is DeprecationWarning, (
        f"recorded warning category must be DeprecationWarning, got {recorded[0].category!r}"
    )
    assert "iter259 escape-hatch probe" in str(recorded[0].message)


def test_b5b_the_load_bearing_half_of_the_hatch_is_simplefilter_not_the_mark() -> None:
    """The hatch works from ``simplefilter`` alone -- this test carries NO mark.

    Measured rather than assumed, and it matters for anyone who copies the recipe
    in behavior 5: that test stacks TWO independent mechanisms (the mark AND
    ``simplefilter("always")``), so on its own it cannot say which one defeated the
    ``error`` action. This test isolates one of them -- no ``filterwarnings`` mark
    anywhere on it -- and shows an in-body ``simplefilter("always")`` inside
    ``catch_warnings`` is sufficient. Behaviors 3 and 4 are the proof that WITHOUT
    such an in-body reset the same call raises, so the two together bracket the
    mechanism.
    """
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        warnings.warn("iter259 hatch mechanism probe", UserWarning, stacklevel=2)

    assert [w.category for w in recorded] == [UserWarning], (
        f"an in-body simplefilter('always') must record rather than raise; got {[w.category for w in recorded]}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- the ratchet: NO carve-out today, and none may be added silently.
# ---------------------------------------------------------------------------


def test_b6_the_declaration_carries_no_ignore_carve_out() -> None:
    """Exactly one entry, and it is ``error`` -- an appended ignore reds the build.

    This is the durable half of the iteration. Tolerating a warning is sometimes
    right, but it must be a visible reviewed edit to THIS oracle rather than a
    one-line append nobody sees.
    """
    value = _filterwarnings()

    assert len(value) == 1, (
        f"filterwarnings must hold exactly one entry today; a carve-out was appended: {value!r}"
    )

    offenders = [
        entry
        for entry in value
        if entry.split(":", 1)[0].strip().lower() in {"ignore", "default", "always", "module", "once"}
    ]
    assert not offenders, (
        f"filterwarnings must not weaken the ratchet with a non-error action: {offenders!r}"
    )
    assert "ignore" not in " ".join(value).lower(), (
        f"filterwarnings must contain no ignore carve-out: {value!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- the ini is the SINGLE declaration point, and no existing test
# was given a per-test carve-out to make the suite pass.
# ---------------------------------------------------------------------------


def test_b7a_the_ini_is_the_single_declaration_point() -> None:
    """No recipe passes ``-W``, and no rival ini file declares the filter either.

    A second declaration point is a drift surface even when it agrees with the
    ini today, because the two can disagree later and only one of them is under
    this oracle. Both halves are asserted here rather than in two functions --
    see the SUITE-SIZE note in the module docstring for why the granularity is
    what it is.
    """
    for rel in RECIPES:
        path = REPO / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "pytest" not in line:
                continue
            tokens = line.split()
            hits = [t for t in tokens if t == "-W" or t.startswith("-W")]
            assert not hits, (
                f"{rel}:{lineno} grades pytest with a warning flag {hits!r}; the ini "
                f"[tool.pytest.ini_options].filterwarnings is the single declaration point: {line.strip()!r}"
            )


    for rel in RIVAL_INI_FILES:
        path = REPO / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert "filterwarnings" not in text, (
            f"{rel} declares filterwarnings as well; pyproject.toml must be the single "
            "declaration point or the two can silently disagree"
        )


def test_b7c_this_module_is_the_only_one_carrying_a_filterwarnings_mark() -> None:
    """No EXISTING test module was handed a per-test carve-out.

    The suite was already warning-clean on both graded legs, so the honest way to
    ship this ratchet is with zero suppressions. Measured at the time of writing:
    ZERO tracked test modules used ``@pytest.mark.filterwarnings``. Behavior 5 in
    THIS module is the first and, by this assertion, the only one -- so a future
    suppression sprinkled through the suite to keep a red build green becomes a
    visible failure here instead of a quiet spread.
    """
    listing = _git("ls-files", "tests")
    if listing is None:
        pytest.skip("git history unavailable; the shipping tree cannot be enumerated")

    me = Path(__file__).name
    carriers: list[str] = []
    for rel in listing.split():
        if not rel.endswith(".py"):
            continue
        path = REPO / rel
        if not path.exists() or path.name == me:
            continue
        if "mark.filterwarnings" in path.read_text(encoding="utf-8"):
            carriers.append(rel)

    assert not carriers, (
        "these tracked test modules carry a per-test filterwarnings carve-out, which is how a "
        f"warning ratchet quietly stops ratcheting: {carriers}"
    )


# ---------------------------------------------------------------------------
# Behavior 8 -- no dependency change, so no lock drift. CI runs `uv sync
# --locked`, so a regenerated lock would itself be the failure.
# ---------------------------------------------------------------------------


def test_b8_no_dependency_change_and_therefore_no_lock_drift() -> None:
    """The ratchet adds nothing installable, and ``uv.lock`` reflects that.

    CI installs with ``uv sync --locked``, so a lock regenerated for no declared
    reason is drift that reds a public build. Stated as an implication rather than
    a flat byte-identity so a LEGITIMATE later dependency bump -- which must
    regenerate the lock in the same commit -- is not sabotaged by this oracle.
    """
    with PYPROJECT.open("rb") as fh:
        declared = tomllib.load(fh)
    deps = declared["project"]["dependencies"]
    assert deps == ["pydantic>=2.7"], (
        f"a pytest ini key must not change the runtime dependency set, got {deps!r}"
    )

    head_lock = _git("show", "HEAD:uv.lock")
    head_pyproject = _git("show", "HEAD:pyproject.toml")
    if head_lock is None or head_pyproject is None:
        pytest.skip("git history unavailable; cannot compare against the HEAD blob")

    lock_changed = UV_LOCK.read_text(encoding="utf-8") != head_lock
    if not lock_changed:
        return

    head_data = tomllib.loads(head_pyproject)
    live_data = declared

    def _declared(data: dict[str, Any]) -> tuple[Any, Any]:
        return (
            data.get("project", {}).get("dependencies"),
            data.get("dependency-groups"),
        )

    assert _declared(head_data) != _declared(live_data), (
        "uv.lock differs from its HEAD blob while pyproject.toml declares the same "
        "dependencies and dev groups -- CI runs `uv sync --locked`, so that is lock drift"
    )
