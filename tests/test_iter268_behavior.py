"""Black-box behavior tests for factory iteration 309 (ROADMAP #289) --- the nine-key
dispatched-run document roster is DEFINED ONCE in the test corpus, the four modules that
used to hand-spell it now IMPORT that one object, and a VALUE-keyed census proves a sixth
copy cannot come back under a sixth name.

WHY this module exists. The surviving oracles (``tests/test_iter158_behavior.py``,
``tests/test_iter163_behavior.py``, ``tests/test_iter173_behavior.py``,
``tests/test_iter203_behavior.py``, ``tests/test_iter267_behavior.py``) each pin what the
published document IS -- every one of them compares a HAND-WRITTEN roster against a key
set obtained by RUNNING the verb. None of them pins how many times the roster is SPELLED.
A future iteration that "fixes" a red key-set test by re-declaring a local literal would
leave all five green while quietly restoring the drift this iteration made
unrepresentable. So this module owns the STRUCTURE of the expectation, and deliberately
owns nothing else:

* it does NOT re-spell the roster. A sixth copy of the very literal being de-duplicated
  would defeat the change it verifies, and comparing an imported constant against itself
  is the import-and-assert-itself tautology ``tests/test_iter243_behavior.py`` warns
  about. The VALUE stays owned by the five live document assertions; every needle here is
  ASSEMBLED AT RUNTIME from the owner's imported object;
* it does NOT re-assert the roadmap char wall or the suite-size floor.
  ``tests/test_iter241_behavior.py`` and ``tests/test_readme_and_ci_contract.py`` already
  own those, and a third spelling would be the same duplication in a new place;
* it does NOT pin the live index-row count. ``tests/test_iter168_behavior.py`` owns that
  floor, and a tighter pin here would block a legitimate future retire-and-mint.

The census is keyed on the roster VALUE, never on a NAME: the corpus reached five copies
under TWO names (three orderings), so a name-keyed guard would let the repo publish
"single-sourced" while copies survived under a different identifier. That is the
self-refuting-artifact shape, and it is what this module is shaped to prevent.

Every census below is TWO-SIDED: each helper is a pure function of source text and is
proved to FIRE on synthetic violating text AND to stay SILENT on synthetic compliant
text, so a green run means the census still bites rather than that it stopped looking.
The retired private names are likewise assembled from fragments and never written out, so
this module cannot exempt itself from its own corpus-wide censuses --- it is inside their
domain, and its own path is unioned into that domain unconditionally.

ISOLATION CONTRACT (honored): every assertion here was written from this iteration's spec
("Expected Behaviors" in ``pm.md``), the repo's own ``tests/`` tree, ``ROADMAP.md``,
``ROADMAP_ARCHIVE.md`` and ``README.md``. **No file under ``src/`` was read, no engineer /
reviewer / fix note was consulted, and no ``git diff`` was inspected.**

Offline and deterministic: no network, no API key, no subprocess beyond ``git ls-files``
(with a glob fallback plus an unconditional union of this file, so the domain can never be
empty and can never silently drop the module doing the measuring).

Python-version note: the CI matrix runs 3.12 and 3.13, and 3.13 strips the common
docstring indent while 3.12 does not, so nothing here asserts on docstring layout.
"""

from __future__ import annotations

import ast
import importlib
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / "tests"
ROADMAP = REPO / "ROADMAP.md"
ROADMAP_ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"
README = REPO / "README.md"
SELF = Path(__file__).resolve()

# --------------------------------------------------------------------------
# The spec's own vocabulary (pm.md), encoded here rather than imported, to keep
# these tests black-box against the contract.
# --------------------------------------------------------------------------
CONST = "DISPATCHED_RUN_KEYS"
OWNER_NAME = "test_iter158_behavior.py"
OWNER_MODULE = "tests.test_iter158_behavior"
DEPENDENT_MODULES = (
    "tests.test_iter163_behavior",
    "tests.test_iter173_behavior",
    "tests.test_iter203_behavior",
    "tests.test_iter267_behavior",
)

#: The private names the five copies used to carry. ASSEMBLED, never spelled: writing
#: either one out would put this module in breach of the census it performs.
_RETIRED_PREFIXES = ("_DISPATCH", "_DOCUMENT")
_RETIRED_TAIL = "_KEYS"

#: Cues the owner's contract comment must carry (behavior 6).
SINGLE_DEFINITION_CUE = "single definition"
DO_NOT_LOCALIZE_CUE = "do not"
LOCALIZE_CUE = "localize"

#: Cues each dependent must still carry, so the correction of the stale prose cannot
#: quietly weaken the claim the oracle makes (behavior 7). The corpus states the
#: unchanged-oracle claim in TWO phrasings -- "the oracle is unchanged" and "still
#: compared against ..." -- so the census asks for the SUBSTANCE (either phrasing),
#: never for one editor's wording.
UNCHANGED_ORACLE_CUES = ("oracle is unchanged", "still compared against")
UNCHANGED_ORACLE_CUE = UNCHANGED_ORACLE_CUES[0]
HAND_WRITTEN_CUE = "hand-written"

#: Ledger row this iteration owes ``ROADMAP.md``, and the commit tag it must cite.
LEDGER_ROW = "- #289 "
LEDGER_TAG = "(foundry iter 309)"
ARCHIVE_BULLET = "- **#289 "

#: Non-vacuity floors. A census whose needle is an EMPTY set matches every literal in the
#: tree, which is the fail-open shape this repo keeps rediscovering.
MIN_ROSTER_KEYS = 2
MIN_CENSUS_MODULES = 100
MIN_DEPENDENT_REFERENCES = 3

#: How far above the assignment the contract comment may start (behavior 6).
COMMENT_LOOKBACK_LINES = 6

_MARKER = "PORTFOLIO INTRO"


# --------------------------------------------------------------------------
# Assembled needles -- so this module never contains the text it forbids.
# --------------------------------------------------------------------------
def retired_names() -> tuple[str, ...]:
    """The retired private names, built at runtime from fragments."""
    return tuple(prefix + _RETIRED_TAIL for prefix in _RETIRED_PREFIXES)


def local_spelling_needles() -> tuple[str, ...]:
    """Sentences that claim a roster expectation is spelled out locally.

    The first entry is the exact opener the corpus carried before this iteration
    (``tests/test_iter173_behavior.py``); the other two are the neighbouring phrasings a
    future contributor would reach for. Each is proved to fire on its own planted sample
    below, because three needles is three chances to ship a pattern that matches nothing.
    """
    return (
        "Spelled" + " out because",
        "spelled" + " out locally",
        "hand-spell" + "ed here",
    )


# --------------------------------------------------------------------------
# Domain + pure census helpers (each proved two-sided further down).
# --------------------------------------------------------------------------
def tracked_test_paths() -> list[Path]:
    """Every test module in the SHIPPING tree, plus this file unconditionally."""
    paths: set[Path] = {SELF}
    try:
        out = subprocess.run(
            ["git", "ls-files", "tests"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        listed = [line for line in out.stdout.split() if line.endswith(".py")]
    except OSError:  # pragma: no cover - git is present in CI and in a fresh clone
        listed = []
    if not listed:
        listed = [str(p.relative_to(REPO)) for p in sorted(TESTS_DIR.glob("*.py"))]
    for rel in listed:
        candidate = REPO / rel
        if candidate.is_file():
            paths.add(candidate.resolve())
    return sorted(paths)


def roster_literal_lines(source: str, roster: frozenset[str]) -> list[int]:
    """Lines holding a set/list/tuple literal whose strings are a SUPERSET of ``roster``.

    Keyed on the VALUE, so it is blind to the constant's name and cannot be evaded by a
    rename. ``frozenset({...})`` is counted ONCE: only the collection DISPLAY is matched,
    never the enclosing ``Call``, so one definition seen through two nodes stays one site.
    """
    assert len(roster) >= MIN_ROSTER_KEYS, "an empty needle matches every literal"
    lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            continue
        strings = {
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        if roster <= strings:
            lines.add(node.lineno)
    return sorted(lines)


def name_assignment_lines(source: str, name: str) -> list[int]:
    """Lines where ``name`` is assigned anything, at any depth."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                lines.append(node.lineno)
    return lines


def imported_names_from(source: str, module: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.update(alias.name for alias in node.names)
    return names


def text_needle_hits(source: str, needles: tuple[str, ...]) -> list[str]:
    """Which of ``needles`` occur in ``source`` as raw text."""
    return [needle for needle in needles if needle in source]


def prose_census_domain(tracked: list[Path]) -> list[Path]:
    """``tracked`` minus THIS module, which is the one file allowed to name the shapes.

    The banned sentences have to be written out somewhere to be proved to fire, and the
    assertion messages have to describe what they found, so this module WOULD be its own
    first finding. Stating the exclusion explicitly is the whole remedy: the alternative
    is relying on the prose here staying clean, which the next helpful comment breaks.
    The retired-name and roster-literal censuses do NOT take this exclusion -- both
    assemble their needles at runtime, so this module is provably inside their domain.
    """
    return [path for path in tracked if path != SELF]


def owner_roster_literal_strings(source: str, name: str) -> frozenset[str]:
    """The string elements of the collection literal ``name`` is assigned."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            continue
        for inner in ast.walk(node.value):
            if isinstance(inner, (ast.Set, ast.List, ast.Tuple)):
                return frozenset(
                    element.value
                    for element in inner.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                )
    return frozenset()


def comment_block_above(source: str, lineno: int, lookback: int) -> str:
    """The contiguous ``#`` comment lines immediately above 1-based ``lineno``."""
    lines = source.splitlines()
    block: list[str] = []
    index = lineno - 2
    while index >= 0 and len(block) < lookback:
        stripped = lines[index].strip()
        if not stripped.startswith("#"):
            break
        block.append(stripped.lstrip("#").strip())
        index -= 1
    return "\n".join(reversed(block))


def is_frozenset_call_of_a_display(source: str, name: str) -> bool:
    """True when ``name`` is assigned ``frozenset(<set/list/tuple display>)``."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "frozenset"
            and len(value.args) == 1
            and isinstance(value.args[0], (ast.Set, ast.List, ast.Tuple))
        ):
            return True
    return False


def _dependent_path(module: str) -> Path:
    return REPO / (module.replace(".", "/") + ".py")


def _synthetic_literal(roster: frozenset[str], name: str, spelling: str) -> str:
    """Module text that plants a roster literal under ``name``.

    The keys are interpolated from the OWNER's imported object at runtime, so no copy of
    the roster is ever written into this file's source text.
    """
    keys = ", ".join(repr(key) for key in sorted(roster))
    bodies = {
        "set": "{" + keys + "}",
        "frozenset": "frozenset({" + keys + "})",
        "list": "[" + keys + "]",
        "tuple": "(" + keys + ",)",
    }
    return name + " = " + bodies[spelling] + "\n"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def tracked() -> list[Path]:
    paths = tracked_test_paths()
    assert len(paths) > MIN_CENSUS_MODULES, (
        f"census domain collapsed to {len(paths)} module(s)"
    )
    assert SELF in paths, "the census domain excludes the module doing the measuring"
    return paths


@pytest.fixture(scope="module")
def block() -> str:
    """The contract comment immediately above the owner's assignment."""
    source = (TESTS_DIR / OWNER_NAME).read_text(encoding="utf-8")
    lines = name_assignment_lines(source, CONST)
    assert len(lines) == 1, f"{OWNER_NAME} must assign {CONST} once; got {lines}"
    text = comment_block_above(source, lines[0], COMMENT_LOOKBACK_LINES)
    assert text, (
        f"no comment block sits in the {COMMENT_LOOKBACK_LINES} lines above {CONST}; "
        "a future contributor has nothing telling them not to localize it"
    )
    return text


@pytest.fixture(scope="module")
def roster() -> frozenset[str]:
    """The roster, taken from the OWNER at runtime rather than re-spelled."""
    owner = importlib.import_module(OWNER_MODULE)
    value = getattr(owner, CONST)
    assert isinstance(value, frozenset), (
        f"{OWNER_MODULE}.{CONST} must be a frozenset; got {type(value).__name__}"
    )
    assert len(value) >= MIN_ROSTER_KEYS, (
        f"{CONST} holds {len(value)} key(s), too few for a meaningful census needle"
    )
    return value


# ==========================================================================
# Behavior 1: one owner, publicly named; the retired names are gone.
# ==========================================================================
class TestOneOwnerPubliclyNamed:
    def test_b1_exactly_one_tracked_module_assigns_the_roster_name(
        self, tracked: list[Path]
    ) -> None:
        sites = {
            path.name: name_assignment_lines(path.read_text(encoding="utf-8"), CONST)
            for path in tracked
        }
        owners = {name: lines for name, lines in sites.items() if lines}
        assert list(owners) == [OWNER_NAME], (
            f"{CONST} must be assigned in exactly one tracked test module "
            f"({OWNER_NAME}); found {owners}"
        )
        assert len(owners[OWNER_NAME]) == 1, (
            f"{OWNER_NAME} assigns {CONST} more than once: {owners[OWNER_NAME]}"
        )

    def test_b1_the_owner_publishes_a_public_frozenset_of_exactly_the_roster(
        self, roster: frozenset[str]
    ) -> None:
        assert not CONST.startswith("_"), (
            f"the shared roster must be public so dependents can import it; got {CONST}"
        )
        source = (TESTS_DIR / OWNER_NAME).read_text(encoding="utf-8")
        assert is_frozenset_call_of_a_display(source, CONST), (
            f"{OWNER_NAME} must assign {CONST} = frozenset(<display>) so the shared "
            "object is immutable; a mutable set could be edited by one importer"
        )
        spelled = owner_roster_literal_strings(source, CONST)
        assert spelled == roster, (
            f"the literal {OWNER_NAME} spells and the object it exports disagree; "
            f"only-in-source={sorted(spelled - roster)} "
            f"only-in-object={sorted(roster - spelled)}"
        )

    def test_b1_the_retired_private_names_are_absent_corpus_wide(
        self, tracked: list[Path]
    ) -> None:
        needles = retired_names()
        offenders = {
            path.name: hits
            for path in tracked
            if (hits := text_needle_hits(path.read_text(encoding="utf-8"), needles))
        }
        assert offenders == {}, (
            f"a retired private roster name survives in the shipping tree: {offenders}"
        )

    def test_b1_the_retired_name_census_is_two_sided(
        self, roster: frozenset[str]
    ) -> None:
        needles = retired_names()
        assert len(needles) == len(_RETIRED_PREFIXES)
        for needle in needles:
            planted = _synthetic_literal(roster, needle, "frozenset")
            assert text_needle_hits(planted, needles) == [needle], (
                f"the census cannot see a revived {needle}"
            )
        compliant = f"from {OWNER_MODULE} import {CONST}\n"
        assert text_needle_hits(compliant, needles) == []


# ==========================================================================
# Behavior 2: four importers, no local copy.
# ==========================================================================
class TestFourImportersNoLocalCopy:
    def test_b2_each_dependent_imports_the_roster_from_its_owner(self) -> None:
        imported = {
            module: imported_names_from(
                _dependent_path(module).read_text(encoding="utf-8"), OWNER_MODULE
            )
            for module in DEPENDENT_MODULES
        }
        missing = {
            module: sorted(names)
            for module, names in imported.items()
            if CONST not in names
        }
        assert missing == {}, (
            f"every dependent must import {CONST} from {OWNER_MODULE}; these do not, "
            f"listed with the names they DO import: {missing}"
        )

    def test_b2_no_dependent_assigns_the_roster_name_locally(self) -> None:
        offenders = {
            module: lines
            for module in DEPENDENT_MODULES
            if (
                lines := name_assignment_lines(
                    _dependent_path(module).read_text(encoding="utf-8"), CONST
                )
            )
        }
        assert offenders == {}, (
            f"no dependent may re-assign {CONST} locally, which would shadow the "
            f"imported object and restore the drift; still assigned at {offenders}"
        )

    def test_b2_no_dependent_still_spells_the_roster(
        self, roster: frozenset[str]
    ) -> None:
        offenders = {
            module: lines
            for module in DEPENDENT_MODULES
            if (
                lines := roster_literal_lines(
                    _dependent_path(module).read_text(encoding="utf-8"), roster
                )
            )
        }
        assert offenders == {}, (
            f"these dependents still spell the roster as a literal: {offenders}; "
            f"each must import {CONST} from {OWNER_MODULE} instead"
        )


# ==========================================================================
# Behavior 3: identity, not equality -- drift is unrepresentable.
# ==========================================================================
class TestSharedObjectIdentity:
    def test_b3_each_dependent_shares_the_owner_object(self) -> None:
        owner = getattr(importlib.import_module(OWNER_MODULE), CONST)
        copies = [
            module
            for module in DEPENDENT_MODULES
            if getattr(importlib.import_module(module), CONST) is not owner
        ]
        assert copies == [], (
            f"{copies} carry their own {CONST} object, so each can disagree with "
            f"{OWNER_MODULE}; equal copies drift, one shared object cannot"
        )

    def test_b3_all_five_references_are_one_object(self) -> None:
        modules = (OWNER_MODULE, *DEPENDENT_MODULES)
        objects = [getattr(importlib.import_module(name), CONST) for name in modules]
        assert len({id(obj) for obj in objects}) == 1, (
            f"the roster is reachable as {len({id(o) for o in objects})} distinct "
            f"objects across {list(modules)}"
        )


# ==========================================================================
# Behavior 4: the VALUE census over the whole shipping tree reports one site.
# ==========================================================================
class TestValueCensusOverTheShippingTree:
    def test_b4_exactly_one_roster_literal_in_the_shipping_tree(
        self, tracked: list[Path], roster: frozenset[str]
    ) -> None:
        sites = {
            path.name: roster_literal_lines(path.read_text(encoding="utf-8"), roster)
            for path in tracked
        }
        found = {name: lines for name, lines in sites.items() if lines}
        assert list(found) == [OWNER_NAME], (
            "the roster must have exactly one definition site in the test corpus; "
            f"found {found}"
        )
        assert len(found[OWNER_NAME]) == 1, (
            f"{OWNER_NAME} holds {len(found[OWNER_NAME])} roster literals at "
            f"{found[OWNER_NAME]}; the owner must spell it once"
        )

    def test_b4_this_module_never_spells_the_roster_itself(
        self, roster: frozenset[str]
    ) -> None:
        lines = roster_literal_lines(SELF.read_text(encoding="utf-8"), roster)
        assert lines == [], (
            "the census module re-spells the roster it de-duplicates at lines "
            f"{lines} -- the import-and-assert-itself tautology"
        )


# ==========================================================================
# Behavior 5: the census is two-sided, and name-blind.
# ==========================================================================
class TestCensusIsTwoSided:
    def test_b5_census_fires_on_a_second_roster_under_a_different_name(
        self, roster: frozenset[str]
    ) -> None:
        owner_side = _synthetic_literal(roster, CONST, "frozenset")
        planted = owner_side + _synthetic_literal(roster, "_A_SIXTH_NAME", "frozenset")
        lines = roster_literal_lines(planted, roster)
        assert len(lines) == 2, (
            "the census must report BOTH the owner and a renamed copy; a name-keyed "
            f"guard would report one. Got {lines}"
        )

    def test_b5_census_stays_silent_on_compliant_text(
        self, roster: frozenset[str]
    ) -> None:
        compliant = (
            f"from {OWNER_MODULE} import {CONST}\n"
            "def t() -> None:\n"
            f"    assert {CONST}\n"
        )
        assert roster_literal_lines(compliant, roster) == []

    def test_b5_a_frozenset_call_counts_as_one_site_not_two(
        self, roster: frozenset[str]
    ) -> None:
        planted = _synthetic_literal(roster, CONST, "frozenset")
        assert roster_literal_lines(planted, roster) == [1], (
            "frozenset({...}) is ONE definition seen through two AST nodes; counting "
            "raw walk hits reports two and reds against a compliant tree"
        )
        # ... and every OTHER collection spelling a revived copy could hide in is still
        # exactly one site, so the census is blind to shape as well as to name.
        blind = [
            spelling
            for spelling in ("set", "list", "tuple")
            if roster_literal_lines(
                _synthetic_literal(roster, "_A_SIXTH_NAME", spelling), roster
            )
            != [1]
        ]
        assert blind == [], (
            f"a roster copy spelled as any of {blind} is invisible to the census, so "
            "a sixth copy could come back in that shape"
        )

    def test_b5_census_fires_on_a_superset_and_ignores_a_subset(
        self, roster: frozenset[str]
    ) -> None:
        keys = sorted(roster)
        superset = ", ".join(repr(key) for key in [*keys, "a_tenth_key"])
        assert roster_literal_lines("X = {" + superset + "}\n", roster) == [1], (
            "a copy that grows a tenth key must still be found -- that is exactly the "
            "edit this single-sourcing exists to make impossible in five places"
        )
        subset = ", ".join(repr(key) for key in keys[1:])
        assert roster_literal_lines("X = {" + subset + "}\n", roster) == [], (
            "an unrelated shorter key set must not be reported as a roster copy"
        )

    def test_b5_the_census_refuses_an_empty_needle(self) -> None:
        with pytest.raises(AssertionError):
            roster_literal_lines("X = {'a'}\n", frozenset())


# ==========================================================================
# Behavior 6: the owner's comment states the contract.
# ==========================================================================
class TestOwnerContractComment:
    def test_b6_the_comment_states_all_three_halves_of_the_contract(
        self, block: str
    ) -> None:
        lowered = block.lower()
        # (a) it claims to be the one definition ...
        assert SINGLE_DEFINITION_CUE in lowered, (
            f"the contract comment never claims to be the {SINGLE_DEFINITION_CUE}: "
            f"{block!r}"
        )
        # (b) ... names every module that breaks if it is renamed or moved ...
        missing = [
            _dependent_path(module).name
            for module in DEPENDENT_MODULES
            if _dependent_path(module).name not in block
        ]
        assert missing == [], (
            f"the contract comment does not name {missing}, so a reader cannot tell "
            "which modules break if the constant is renamed or moved"
        )
        # (c) ... and forbids localizing it back.
        assert DO_NOT_LOCALIZE_CUE in lowered and LOCALIZE_CUE in lowered, (
            "the contract comment must tell a future contributor not to localize the "
            f"roster back into a dependent: {block!r}"
        )

    def test_b6_the_comment_spells_no_bare_multi_digit_integer(
        self, block: str
    ) -> None:
        offenders = re.findall(r"(?<![\w.,])\d{2,}(?![\w,])", block)
        assert offenders == [], (
            f"the contract comment spells decaying constant(s) {offenders}; a count in "
            "prose has no oracle and is false on the next commit"
        )


# ==========================================================================
# Behavior 7: no stale "spelled out locally" prose survives.
# ==========================================================================
class TestNoStaleLocalSpellingProse:
    def test_b7_no_tracked_module_claims_a_local_spelling(
        self, tracked: list[Path]
    ) -> None:
        needles = local_spelling_needles()
        domain = prose_census_domain(tracked)
        assert len(domain) == len(tracked) - 1, (
            "this module is the only permitted exclusion from the prose census; "
            f"dropped {len(tracked) - len(domain)} module(s)"
        )
        offenders = {
            path.name: hits
            for path in domain
            if (hits := text_needle_hits(path.read_text(encoding="utf-8"), needles))
        }
        assert offenders == {}, (
            "prose claiming a roster expectation is spelled out locally survives, and "
            f"the literal it describes is gone: {offenders}"
        )

    def test_b7_the_local_spelling_census_is_two_sided(self) -> None:
        needles = local_spelling_needles()
        # It FIRES: every needle matches text that really does claim a local spelling,
        # so none of them is assert-True padding.
        for needle in needles:
            sample = f"# {needle} the key set is exact.\n"
            assert text_needle_hits(sample, needles) == [needle], (
                f"needle {needle!r} matches nothing, so it is assert-True padding"
            )
        # It stays SILENT: the correction the four dependents now carry is not a hit,
        # so a green census means compliance rather than a census that stopped looking.
        correction = (
            f"# The roster is IMPORTED above as ``{CONST}``, not re-spelled.\n"
            f"# The {UNCHANGED_ORACLE_CUE} -- still a {HAND_WRITTEN_CUE} expectation.\n"
        )
        assert text_needle_hits(correction, needles) == [], (
            "the census fires on the very correction this iteration shipped, so it "
            "cannot tell a stale claim from a fixed one"
        )

    def test_b7_each_dependent_still_states_its_oracle_is_unchanged(self) -> None:
        silent: dict[str, list[str]] = {}
        for module in DEPENDENT_MODULES:
            lowered = _dependent_path(module).read_text(encoding="utf-8").lower()
            gaps: list[str] = []
            if not any(cue in lowered for cue in UNCHANGED_ORACLE_CUES):
                gaps.append(f"none of {list(UNCHANGED_ORACLE_CUES)}")
            if HAND_WRITTEN_CUE not in lowered:
                gaps.append(f"no {HAND_WRITTEN_CUE!r} claim")
            if gaps:
                silent[module] = gaps
        assert silent == {}, (
            "every dependent must still record that its oracle is UNCHANGED and that "
            "the roster stays a hand-written expectation compared against a LIVE "
            "document -- that is what makes the import safe rather than circular, and "
            f"a reader cannot tell without it; missing: {silent}"
        )


# ==========================================================================
# Behavior 8: every pre-existing assertion still passes unchanged in meaning.
# ==========================================================================
class TestPreExistingOraclesIntact:
    def test_b8_each_dependent_still_compares_a_document_against_the_roster(
        self,
    ) -> None:
        thinned: dict[str, str] = {}
        for module in DEPENDENT_MODULES:
            source = _dependent_path(module).read_text(encoding="utf-8")
            references = source.count(CONST)
            if references < MIN_DEPENDENT_REFERENCES:
                thinned[module] = f"only {references} reference(s)"
            elif not any(
                CONST in line and "assert" in line for line in source.splitlines()
            ):
                thinned[module] = f"imports {CONST} but never asserts on it"
        assert thinned == {}, (
            f"each dependent must keep the import plus the assertion and its failure "
            f"message -- at least {MIN_DEPENDENT_REFERENCES} references to {CONST}, "
            "one of them on an assert line -- so the oracle was thinned rather than "
            f"re-pointed: {thinned}"
        )

    def test_b8_the_owner_still_asserts_against_its_own_roster(self) -> None:
        source = (TESTS_DIR / OWNER_NAME).read_text(encoding="utf-8")
        assert any(
            CONST in line and "assert" in line for line in source.splitlines()
        ), f"{OWNER_NAME} defines {CONST} but no longer asserts against it"


# ==========================================================================
# Behaviors 9 + 10: the published floor stays intact and the iteration records
# itself in exactly one of the two roadmap files.
# ==========================================================================
class TestPublishedFloorAndLedgerRecord:
    def test_b9_the_readme_intro_still_publishes_exactly_one_suite_floor(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert _MARKER in text, "the human-owned portfolio marker is gone from README.md"
        intro = text.split(_MARKER, 1)[0]
        floors = re.findall(r"([\d][\d,]*)\+\s+tests", intro)
        assert len(floors) == 1, (
            f"the intro must publish exactly one suite floor; found {floors}"
        )
        value = int(floors[0].replace(",", ""))
        assert value % 100 == 0, (
            f"the published floor {floors[0]!r} is not a round hundred, so it cannot "
            "be a floor that survives the next commit"
        )

    def test_b10_exactly_one_new_ledger_row_citing_this_iteration_tag(self) -> None:
        rows = [
            line
            for line in ROADMAP.read_text(encoding="utf-8").splitlines()
            if line.startswith(LEDGER_ROW)
        ]
        assert len(rows) == 1, f"expected exactly one {LEDGER_ROW!r} row; got {rows}"
        assert rows[0].rstrip().endswith(LEDGER_TAG), (
            f"the ledger row must cite {LEDGER_TAG}; got {rows[0]!r}"
        )
        assert CONST in rows[0], f"the ledger row does not name {CONST}: {rows[0]!r}"
        assert OWNER_NAME in rows[0], (
            f"the ledger row does not name the owning module {OWNER_NAME}: {rows[0]!r}"
        )
        # A newly minted row lives in exactly ONE of the two roadmap files: recorded in
        # NEITHER or in BOTH is what the ledger-conservation guard reds on.
        archive = ROADMAP_ARCHIVE.read_text(encoding="utf-8")
        in_archive = ARCHIVE_BULLET in archive or LEDGER_ROW in archive
        assert not in_archive, (
            "this iteration's row is in ROADMAP.md AND ROADMAP_ARCHIVE.md; a newly "
            "minted row belongs to exactly one of the two files"
        )

    def test_b10_the_record_did_not_consume_a_live_index_row(self) -> None:
        budget = importlib.import_module("tests.test_roadmap_size_budget")
        rows = budget.parse_index_rows(ROADMAP.read_text(encoding="utf-8"))
        ids = [row[0] for row in rows]
        assert LEDGER_ROW.strip().lstrip("-").strip().lstrip("#") not in ids, (
            "this iteration's record belongs in the Done ledger, not the live index; "
            f"found it among {ids}"
        )
        assert len(ids) == len(set(ids)), f"duplicate live index row id(s) in {ids}"
