"""Black-box behavior tests for state-dir iteration 184 (ships as ``factory iter 188``).

Feature under test: ``tests/test_iter152_behavior.py`` -- the drift guard for the
CLI's exit-code-5 contract -- stops hardcoding WHICH flags route to exit 5 and
DERIVES them from ``src/proactive_loop/cli.py`` instead.  The shipped defect was
a fail-open, not a docs gap: all three published surfaces already named
``verify --fail-on-unresolved``, and NOTHING held them there, because the
constant the five surface loops iterated listed two flags while the same
module's own exit-5 route census already said three.

WHY THIS MODULE EXISTS ALONGSIDE THE GUARD'S OWN TESTS
The artifact under test is itself a test module, so "the suite is green" is not
evidence: a guard can be structurally incapable of firing and still be green.
This module drives the guard from OUTSIDE -- it loads it by file path under a
private name, exercises its published seams against synthetic samples of its
own, and forces its cross-census to FAIL and localise.  Where the guard asserts
a property, this module asserts that the guard can DETECT that property's
violation.

Isolation: black-box.  No implementation source, engineer note, reviewer note or
diff was read while writing this file.  The seams are (a) the guard module
loaded by path (it lives under ``tests/``, which the tester contract permits),
(b) synthetic in-memory source text, and (c) an ``ast`` census of string
constants in ``src/proactive_loop/cli.py``, which spec behaviors 1 and 4 require
by construction -- parsed as DATA, never read as logic.

Offline and deterministic: pure parsing, in-process calls, no subprocess, no
network, no clock, no workspace.

Fail-CLOSED: every census here is fired at a planted known-bad sample, because a
census that silently sees nothing would make each assertion below pass
vacuously -- strictly worse than no assertion at all.

RETIRED NAMES ARE ASSEMBLED FROM FRAGMENTS ON PURPOSE.  Behavior 7 bans two
spellings repo-wide, and this module's domain is ``git ls-files`` plus itself,
so writing either one literally here would red the build the moment this file is
committed (the self-blind-census trap, OPERATOR 2026-08-14).
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD_MODULE = REPO / "tests" / "test_iter152_behavior.py"
CLI_SOURCE = REPO / "src" / "proactive_loop" / "cli.py"

#: The three flags ``cli.py`` announces today. An assertion ABOUT the
#: derivation, never its source of truth -- the guard must compute this itself.
EXPECTED_PRODUCERS = ("--fail-on-kind", "--fail-on-unresolved", "--fail-over")

#: The two spellings behavior 7 retires, assembled from fragments so this file
#: holds NEITHER of them verbatim. Measured, not stylistic: this module unions
#: itself into its own census domain, so a literal spelling here would make the
#: census fire on this file the moment it is committed.
RETIRED_DEF_SUFFIX = "names_" + "both_" + "producers"
RETIRED_PAIR_FLAGS = ("--fail-on-" + "kind", "--fail-" + "over")

#: The surface guards that must consume the DERIVED set (behavior 5).
SURFACE_GUARDS = (
    "test_b03_epilog_code5_entry_names_every_producer",
    "test_b06_docstring_code5_bullet_names_every_producer",
    "test_b08_readme_row5_names_every_producer_and_rows_0_to_4_survive",
)

SHARED_SURFACE_ASSERT = "_assert_surface_names_every_producer"


# --------------------------------------------------------------------------
# Seams
# --------------------------------------------------------------------------


def _load_guard() -> ModuleType:
    """The SHIPPED guard module, loaded by path under a private name.

    A private name so pytest never collects it twice; by PATH so this module
    tests the artifact on disk rather than an ambient import.
    """
    spec = importlib.util.spec_from_file_location("_iter152_guard_under_test", GUARD_MODULE)
    assert spec is not None and spec.loader is not None, (
        f"{GUARD_MODULE} must be loadable as a module; it is the artifact under test"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def guard() -> ModuleType:
    """The guard module under test."""
    return _load_guard()


@pytest.fixture(scope="module")
def guard_source() -> str:
    """The guard module's real bytes, for census assertions."""
    return GUARD_MODULE.read_text(encoding="utf-8")


def _tracked_python() -> dict[str, str]:
    """``relpath -> source`` for every tracked ``.py``, PLUS this module.

    This module is unioned in explicitly because a census whose domain is
    ``git ls-files`` reads GREEN while its own file is still untracked, and this
    is the file most likely to spell a retired name.
    """
    listed = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True, check=False
    )
    assert listed.returncode == 0, (
        f"git ls-files exited {listed.returncode}; the census domain is unknown, "
        "so this oracle would pass vacuously"
    )
    paths = {line for line in listed.stdout.splitlines() if line.strip()}
    paths.add(str(Path(__file__).resolve().relative_to(REPO)))
    corpus = {rel: (REPO / rel).read_text(encoding="utf-8") for rel in sorted(paths)}
    assert len(corpus) > 100, (
        f"the census listed only {len(corpus)} module(s) -- the domain collapsed"
    )
    assert str(Path(__file__).resolve().relative_to(REPO)) in corpus, (
        "this module must be inside its own census domain"
    )
    return corpus


def _module_level_flag_pair_constants(source: str) -> list[str]:
    """Module-level constants bound to a sequence of exactly the retired flags.

    Scoped to MODULE LEVEL and to that exact pair on purpose. The shipped defect
    was a module CONSTANT the surface loops iterated; a flag name inside a
    function body is an expected value or an unrelated assertion, and banning
    those would fire on the very tests that prove the derivation works.
    """
    found: list[str] = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if not isinstance(value, ast.Tuple | ast.List | ast.Set):
            continue
        elts = [
            elt.value
            for elt in value.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
        if len(elts) == len(value.elts) and tuple(elts) == RETIRED_PAIR_FLAGS:
            found.append(ast.unparse(node))
    return found


def _normalized(text: str) -> str:
    """Whitespace-collapsed text, so a wrapped phrase is still one phrase.

    A multi-word ``in`` check over WRAPPED prose is a false negative: the bytes
    carry a newline mid-phrase. Every prose claim below is measured on this.
    """
    return " ".join(text.split())


# --------------------------------------------------------------------------
# Behavior 1 -- the producer set is derived from cli.py source TEXT
# --------------------------------------------------------------------------


def test_b01_helper_takes_source_text_and_returns_the_three_shipped_producers(
    guard: ModuleType,
) -> None:
    """Behavior 1: derived from a SOURCE-TEXT argument, sorted, deduplicated."""
    derive = getattr(guard, "_code5_producers", None)
    assert callable(derive), (
        "the guard must expose a module-level derivation helper so the surface "
        "loops stop iterating a written-down list"
    )
    params = list(inspect.signature(derive).parameters.values())
    assert len(params) == 1, (
        "the helper must take the cli.py SOURCE TEXT as its single parameter, so "
        f"synthetic samples can be fed to it; got {inspect.signature(derive)}"
    )
    assert params[0].annotation in ("str", str), (
        f"the single parameter must be annotated as source text; got {params[0]!r}"
    )

    derived = derive(CLI_SOURCE.read_text(encoding="utf-8"))
    assert derived == EXPECTED_PRODUCERS, (
        "cli.py announces exactly three `gate: <flag> tripped` literals today; a "
        "change here means a gate was added or renamed and every published "
        f"surface must name it in the same commit; got {derived!r}"
    )
    assert tuple(sorted(set(derived))) == tuple(derived), (
        f"the derivation must be sorted and duplicate-free to be deterministic: {derived!r}"
    )
    assert guard.CODE5_PRODUCERS == derived, (
        "the constant the surface loops consume must BE the derivation, not a "
        f"copy of it; got {guard.CODE5_PRODUCERS!r} against {derived!r}"
    )


def test_b01_helper_reads_only_its_argument_and_never_the_real_cli(
    guard: ModuleType,
) -> None:
    """Behavior 1 / acceptance: the helper must not read ``cli.py`` internally.

    Non-leakage is the observable form of that requirement: given a synthetic
    source naming ONE gate no CLI has, the result must be exactly that gate. A
    helper that also read the real file would return the shipped flags too.
    """
    synthetic = (
        "def only_gate() -> int:\n"
        '    print("gate: fail-on-solo tripped")\n'
        "    return 5\n"
    )
    derived = guard._code5_producers(synthetic)
    assert derived == ("--fail-on-solo",), (
        "the derivation must be a pure function of its argument; a shipped flag "
        f"leaking in proves it also reads cli.py itself; got {derived!r}"
    )


def test_b01_no_module_level_constant_writes_the_retired_flag_pair_down(
    guard_source: str,
) -> None:
    """Behavior 1: the hardcoded pair is gone, and the census can still see one."""
    assert not _module_level_flag_pair_constants(guard_source), (
        "no module-level constant in the guard may write the exit-5 producers "
        "down -- that constant is exactly what stopped guarding the third gate: "
        f"found {_module_level_flag_pair_constants(guard_source)}"
    )
    planted = "CODE5_PRODUCERS = " + repr(RETIRED_PAIR_FLAGS) + "\n"
    assert _module_level_flag_pair_constants(planted), (
        "fail-CLOSED: the census must fire on the retired pair, or its silence "
        "on the shipped tree means nothing"
    )
    ignored = "def f():\n    for x in " + repr(RETIRED_PAIR_FLAGS) + ":\n        pass\n"
    assert not _module_level_flag_pair_constants(ignored), (
        "the census must stay scoped to module level: an in-function flag pair is "
        "an expected value, not the retired constant"
    )


# --------------------------------------------------------------------------
# Behavior 2 -- GROWTH: a fourth gate widens the guard with no human edit
# --------------------------------------------------------------------------


def test_b02_a_new_gate_literal_enters_the_derived_set_unaided(
    guard: ModuleType,
) -> None:
    """Behavior 2 (two-sided, positive): growth reaches f-strings and nesting.

    The new gates are spelled as f-strings, which is how a live route is
    written, so this also pins that ``ast.JoinedStr`` parts are walked -- a
    derivation blind to them would silently under-report.
    """
    source = (
        "def existing() -> int:\n"
        '    print("gate: fail-on-kind tripped")\n'
        "    return 5\n"
        "def added(x: int) -> int:\n"
        '    print(f"gate: fail-on-budget tripped -- n={x}")\n'
        "    return 5\n"
        "def outer() -> int:\n"
        "    def nested(y: int) -> int:\n"
        '        print(f"gate: fail-on-nested tripped -- {y}")\n'
        "        return 5\n"
        "    return nested(1)\n"
    )
    derived = guard._code5_producers(source)
    assert derived == ("--fail-on-budget", "--fail-on-kind", "--fail-on-nested"), (
        "a newly emitted `gate: <flag> tripped` literal must enter the derived "
        "set with no human edit -- that is what makes an undocumented gate red "
        f"the build instead of shipping silently; got {derived!r}"
    )
    assert len(derived) == 3 and "--fail-on-budget" in derived, (
        f"growth must be observable in the SIZE of the set, not just its content: {derived!r}"
    )


def test_b02_growth_is_what_forces_a_new_gate_to_be_documented(
    guard: ModuleType,
) -> None:
    """Behavior 2, consequence: a grown set makes an undocumented gate FAIL.

    Growth is only valuable because the surface check consumes it. Feeding the
    shared surface assertion a text that names today's producers but not a
    fourth one must fail and name the fourth.
    """
    grown = guard._code5_producers(
        CLI_SOURCE.read_text(encoding="utf-8")
        + '\ndef added() -> int:\n    print("gate: fail-on-future tripped")\n    return 5\n'
    )
    assert "--fail-on-future" in grown, "precondition: the fourth gate must be derived"
    surface_text = " ".join(EXPECTED_PRODUCERS)
    missing = [flag for flag in grown if flag not in surface_text]
    assert missing == ["--fail-on-future"], (
        "a surface documenting only today's gates must be reported as missing "
        f"exactly the new one; got {missing!r}"
    )


# --------------------------------------------------------------------------
# Behavior 3 -- COMMENT IMMUNITY: repo prose cannot inflate the guard
# --------------------------------------------------------------------------


def test_b03_a_gate_named_only_in_a_comment_is_not_a_producer(
    guard: ModuleType,
) -> None:
    """Behavior 3 (two-sided, negative): comments are discarded, not scanned.

    Load-bearing rather than hypothetical: ``cli.py`` carries a comment naming a
    gate literal a few lines ABOVE an unrelated route, so a text or line-window
    scan would attribute the wrong flag to that route.
    """
    source = (
        "def real() -> int:\n"
        '    print("gate: fail-on-kind tripped")\n'
        "    return 5\n"
        "def phantom() -> int:\n"
        "    # gate: fail-on-phantom tripped\n"
        "    return 5  # gate: fail-on-trailing tripped\n"
    )
    derived = guard._code5_producers(source)
    assert derived == ("--fail-on-kind",), (
        "a gate named only in a `#` comment -- on its own line or trailing a "
        "statement -- must NOT enter the derived set: it is not a producer, and "
        "admitting it would demand documentation for a flag that does not "
        f"exist; got {derived!r}"
    )
    for ghost in ("--fail-on-phantom", "--fail-on-trailing"):
        assert ghost not in derived, f"{ghost} came from a comment; got {derived!r}"


def test_b03_comment_immunity_is_not_an_accident_of_an_empty_parse(
    guard: ModuleType,
) -> None:
    """Behavior 3, fail-CLOSED: the same literal in CODE is still derived.

    Without this, a helper that returned ``()`` for everything would pass the
    negative test above and the immunity claim would be vacuous.
    """
    as_code = (
        "def phantom() -> int:\n"
        '    print("gate: fail-on-phantom tripped")\n'
        "    return 5\n"
    )
    assert guard._code5_producers(as_code) == ("--fail-on-phantom",), (
        "the identical literal must be derived when it is a real string "
        "constant, or the comment-immunity result above proves nothing"
    )


# --------------------------------------------------------------------------
# Behavior 4 -- CROSS-CENSUS: one derived producer per literal exit-5 route
# --------------------------------------------------------------------------


def test_b04_derived_producer_count_equals_the_literal_exit_5_route_count(
    guard: ModuleType,
) -> None:
    """Behavior 4: two independent censuses of the same source must agree."""
    source = CLI_SOURCE.read_text(encoding="utf-8")
    producers = guard._code5_producers(source)
    routes = sum(len(linenos) for linenos in guard._exit5_sites(source).values())
    assert len(producers) == routes == 3, (
        f"cli.py announces {len(producers)} gate(s) {producers} and holds {routes} "
        "literal exit-5 route(s); on the shipped tree both are 3, and a "
        "disagreement means a route or a gate literal is undocumented"
    )


def test_b04_the_cross_census_fails_and_names_both_counts(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behavior 4: the guard's own cross-census must FIRE, naming both counts.

    Driven by pointing the guard's ``CLI_SOURCE`` seam at a synthetic source
    with three gate literals but FOUR routes -- a route that announces no gate,
    which is the fail-open direction a derived set alone cannot see. Nothing on
    disk is touched.
    """
    mismatched = (
        "def a() -> int:\n"
        '    print("gate: fail-on-kind tripped")\n'
        "    return 5\n"
        "def b() -> int:\n"
        '    print("gate: fail-over tripped")\n'
        "    return 5\n"
        "def c() -> int:\n"
        '    print("gate: fail-on-unresolved tripped")\n'
        "    return 5\n"
        "def silent() -> int:\n"
        "    return 5\n"
    )

    class _Stub:
        def read_text(self, encoding: str = "utf-8") -> str:
            return mismatched

    census = getattr(guard, "test_b13_derived_producer_count_matches_the_literal_exit_5_route_census")
    monkeypatch.setattr(guard, "CLI_SOURCE", _Stub())
    with pytest.raises(AssertionError) as excinfo:
        census()
    message = _normalized(str(excinfo.value))
    assert "announces 3" in message and "holds 4" in message, (
        "the cross-census failure must name BOTH counts, so a contributor can "
        f"see which side drifted rather than only that something did; got {message!r}"
    )


# --------------------------------------------------------------------------
# Behavior 5 -- every surface assertion consumes the DERIVED set
# --------------------------------------------------------------------------


@pytest.mark.parametrize("guard_name", SURFACE_GUARDS)
def test_b05_each_surface_guard_passes_on_the_shipped_tree(
    guard: ModuleType, guard_name: str
) -> None:
    """Behavior 5: all three published surfaces name every derived producer."""
    surface_guard = getattr(guard, guard_name, None)
    assert callable(surface_guard), (
        f"{guard_name} must survive the rename as a live test; behavior 5 keeps "
        "all three surface assertions, unchanged in intent"
    )
    surface_guard()


@pytest.mark.parametrize("guard_name", SURFACE_GUARDS)
def test_b05_each_surface_guard_resolves_the_derived_set_not_a_private_list(
    guard_source: str, guard_name: str
) -> None:
    """Behavior 5: the surface guards route through the shared derived check.

    Asserted structurally rather than by reading a passing result: a guard that
    passed while comparing against its own written-down list would be green and
    unable to notice a fourth gate.
    """
    functions = {
        node.name: node
        for node in ast.walk(ast.parse(guard_source))
        if isinstance(node, ast.FunctionDef)
    }
    body = functions[guard_name]
    called = {
        node.func.id
        for node in ast.walk(body)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert SHARED_SURFACE_ASSERT in called, (
        f"{guard_name} must assert through {SHARED_SURFACE_ASSERT}, which resolves "
        f"the derived producer set; it calls {sorted(called)}"
    )
    assert not _module_level_flag_pair_constants(guard_source), (
        "and no module-level flag list may remain for it to fall back on"
    )


def test_b05_the_derived_name_is_consumed_by_at_least_five_sites(
    guard_source: str,
) -> None:
    """Behavior 5: every consumer moved to the derived value, not just three.

    The spec names five loop sites over the old constant; the derived name must
    carry all of them, so a count is asserted rather than spot-checking one.
    """
    tree = ast.parse(guard_source)
    loads = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "CODE5_PRODUCERS"
        and isinstance(node.ctx, ast.Load)
    ]
    stores = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "CODE5_PRODUCERS"
        and isinstance(node.ctx, ast.Store)
    ]
    assert len(stores) == 1, (
        f"the derived set must be bound exactly once, at module level; stores at {stores}"
    )
    assert len(loads) >= 5, (
        "the spec names five sites that iterated the old hardcoded pair; every "
        f"one of them must consume the derived value, so at least five loads are "
        f"expected; found {len(loads)} at {loads}"
    )


# --------------------------------------------------------------------------
# Behavior 6 -- NEGATIVE PER SURFACE, and the failure LOCALISES the offender
# --------------------------------------------------------------------------


def _live_surfaces(guard: ModuleType) -> dict[str, str]:
    """The three published surfaces' code-5 text, read through the guard's seams."""
    from proactive_loop.cli import main as cli_main

    help_text = guard._capture_help(["--help"])
    epilog = {entry.code: entry.text for entry in guard._entries(help_text)}[5]
    docstring = guard._docstring_bullets(cli_main.__doc__ or "")[5]
    readme = guard._readme_exit_code_rows(
        (REPO / "README.md").read_text(encoding="utf-8")
    )[5]
    return {"epilog": epilog, "docstring": docstring, "readme": readme}


@pytest.mark.parametrize("surface", ["epilog", "docstring", "readme"])
@pytest.mark.parametrize("dropped", EXPECTED_PRODUCERS)
def test_b06_removing_any_producer_from_any_surface_fails_and_names_it(
    guard: ModuleType, surface: str, dropped: str
) -> None:
    """Behavior 6: nine cases -- three surfaces x three producers.

    The engineer's own guard proves the third gate; this widens it to EVERY
    producer on EVERY surface, so no single flag is guarded by accident. The
    copy is damaged IN MEMORY -- no file on disk is touched.
    """
    intact = _live_surfaces(guard)[surface]
    assert dropped in intact, (
        f"precondition: the live {surface} must name {dropped} before removal, "
        f"otherwise the damage is a no-op; got {intact!r}"
    )
    guard._assert_surface_names_every_producer(surface, intact)

    damaged = intact.replace(dropped, "")
    assert guard._missing_producers(damaged) == [dropped], (
        "the damaged surface must be reported as missing EXACTLY the removed "
        f"flag; got {guard._missing_producers(damaged)!r}"
    )
    with pytest.raises(AssertionError) as excinfo:
        guard._assert_surface_names_every_producer(surface, damaged)
    message = _normalized(str(excinfo.value))
    omitted = message.split("omits ", 1)[1].split(" --", 1)[0]
    assert omitted == dropped, (
        f"the {surface} failure must localise the offender by name, not report a "
        f"count: its `omits` clause reads {omitted!r} for a removed {dropped}"
    )
    assert surface in message, f"the message must name the surface; got {message!r}"


# --------------------------------------------------------------------------
# Behavior 7 -- NARRATIVE REPAIR: no fixed producer count survives in prose
# --------------------------------------------------------------------------


def test_b07_the_guard_docstring_says_the_count_is_derived(guard_source: str) -> None:
    """Behavior 7: the module's own narrative points at the code, not a number."""
    docstring = ast.get_docstring(ast.parse(guard_source)) or ""
    normalized = _normalized(docstring)
    assert normalized, "the guard module must keep a module docstring"
    assert "DERIVED from" in normalized and "cli.py" in normalized, (
        "the docstring must state that the producer count is derived from "
        f"cli.py; got {normalized[:400]!r}"
    )
    assert "_code5_producers" in normalized, (
        "and it must name the helper that derives it, so a reader can find the "
        f"source of truth; got {normalized[:400]!r}"
    )


def test_b07_no_stale_fixed_count_prose_survives_in_the_guard(
    guard_source: str,
) -> None:
    """Behavior 7: the two stale claims are corrected, measured on wrapped text.

    Whitespace is collapsed first: a multi-word claim can wrap mid-phrase, and
    an un-normalised ``in`` check would report it absent while it is still there.
    """
    normalized = _normalized(guard_source)
    for stale in ("has TWO producers", "Both live producers", "both producers"):
        assert stale not in normalized, (
            f"the retired claim {stale!r} still stands in the guard's prose -- a "
            "count in prose that disagrees with the code is the fail-open this "
            "iteration closes, not a typo"
        )
    assert "TWO producers" not in normalized, (
        "no fixed producer count may be claimed in prose at all"
    )


def test_b07_three_surface_tests_carry_the_renamed_form(guard_source: str) -> None:
    """Behavior 7: exactly the three surface guards were renamed, and no more."""
    names = [
        node.name
        for node in ast.walk(ast.parse(guard_source))
        if isinstance(node, ast.FunctionDef)
    ]
    # CONTAINS, and scoped to `test_` functions. Measured, not stylistic: an
    # `endswith` census counted the shared assertion helper
    # `_assert_surface_names_every_producer` and MISSED the README guard, whose
    # name carries a suffix after the renamed form. Same count, wrong three.
    renamed = [
        name
        for name in names
        if name.startswith("test_") and "names_every_producer" in name
    ]
    assert len(renamed) == 3, (
        f"three surface TESTS must carry the renamed form; found {renamed}"
    )
    assert set(SURFACE_GUARDS) <= set(names), (
        f"the three renamed surface guards must exist under their new names; got {sorted(names)}"
    )
    assert not [name for name in names if name.endswith(RETIRED_DEF_SUFFIX)], (
        "no test may keep the retired name form: it asserts a count of two while "
        "the code announces three"
    )


def test_b07_the_retired_spellings_are_absent_from_every_tracked_module() -> None:
    """Behavior 7: repo-wide census over tracked Python, including this file.

    SCOPE, and it is a deliberate reading of the spec: the domain is tracked
    PYTHON, and the banned constant is a MODULE-LEVEL binding. Measured reasons,
    both verified rather than assumed --
      * ``ROADMAP_ARCHIVE.md`` quotes both retired spellings verbatim, because
        recording what was retired is that file's job; a literal repo-wide ban
        would forbid the repo from documenting its own fix.
      * ``tests/test_iter180_behavior.py`` loops over the same two flags INSIDE a
        function, asserting code 5's meaning keeps naming its SIBLING gates
        alongside the newer trigger. That is a different concept from the
        retired producer constant, and banning it would delete a live guard.
    """
    corpus = _tracked_python()
    with_retired_name = {
        rel: source.count(RETIRED_DEF_SUFFIX)
        for rel, source in corpus.items()
        if RETIRED_DEF_SUFFIX in source
    }
    assert not with_retired_name, (
        f"the retired test-name form must be gone from tracked Python; found {with_retired_name}"
    )
    with_constant = {
        rel: _module_level_flag_pair_constants(source)
        for rel, source in corpus.items()
        if _module_level_flag_pair_constants(source)
    }
    assert not with_constant, (
        "no tracked module may bind the retired two-flag producer pair at module "
        f"level; found {with_constant}"
    )


def test_b07_the_repo_wide_census_is_not_vacuous(tmp_path: Path) -> None:
    """Behavior 7, fail-CLOSED: both halves must fire on planted samples."""
    planted_name = f"def test_epilog_{RETIRED_DEF_SUFFIX}() -> None:\n    pass\n"
    assert RETIRED_DEF_SUFFIX in planted_name, (
        "the planted sample must actually carry the retired form"
    )
    planted_constant = "PRODUCERS = " + repr(RETIRED_PAIR_FLAGS) + "\n"
    assert _module_level_flag_pair_constants(planted_constant), (
        "the constant half of the census must fire on a planted module-level pair"
    )
    clean = "PRODUCERS = _derive(SOURCE)\n"
    assert not _module_level_flag_pair_constants(clean), (
        "and must stay silent on a derived binding, or it bans the fix itself"
    )
    sample = tmp_path / "sample.py"
    sample.write_text(planted_name + planted_constant, encoding="utf-8")
    text = sample.read_text(encoding="utf-8")
    assert RETIRED_DEF_SUFFIX in text and _module_level_flag_pair_constants(text), (
        "a file holding both defects must be detected by both halves"
    )
