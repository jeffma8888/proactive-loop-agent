"""Black-box behavior tests for factory iteration 268 --- ``create_client`` stops
advertising a data-driven dispatch map its body does not contain, and the seven
``provider ==`` arms gain their FIRST oracle binding them to ``VALID_PROVIDERS``.

MODULE NAME, derived from the repo and never from the state-dir counter. The two
counters differ here: this is state-dir iteration 268, while ``git ls-files tests``
tops out at ``test_iter243_behavior.py``, so the free name is ``iter244``. Proved free
before writing: ``git cat-file -e HEAD:tests/test_iter244_behavior.py`` returned
``fatal: path ... does not exist in 'HEAD'``.

WHAT THIS ITERATION CLAIMS (restated from the spec so this file stands alone):

* ``create_client``'s docstring claimed *"Dispatch is data-driven off a small map so
  adding a provider means adding one branch, not editing a long if/elif chain"*. The
  function holds ZERO mapping nodes and IS a flat run of ``provider == "<name>"``
  arms, so the sentence refuted itself: adding a branch *is* editing the chain it
  claimed to avoid. It is replaced by prose describing the real shape.
* ``VALID_PROVIDERS`` and the arm roster are hand-maintained apart, and a comment
  claims they "can never drift apart" --- a claim no test checked. An 8th name added
  to the tuple without a branch would surface as
  ``unknown provider 'x'; valid options are: ... x``: an error listing the provider it
  just rejected. This module makes that drift a red build.

TWO PROPERTIES, DELIBERATELY NOT COLLAPSED INTO A WORD BAN:

1. The map claim is checked as an IMPLICATION --- ``claims_mapping`` implies
   ``has_mapping``, both computed from ONE parse of the same file. Today
   ``has_mapping`` is False, so the vocabulary must be absent; an iteration that
   builds a real ``name -> factory`` map makes ``has_mapping`` True and earns the
   vocabulary back. A standing ban on the words would forbid the honest future shape,
   which is why ``test_b4c`` pins the guard's SILENCE on exactly that shape.
2. Arm parity is DERIVED ON BOTH SIDES --- expected from the imported
   ``VALID_PROVIDERS``, observed from the module's AST. Neither side is a hardcoded
   roster here, so this module cannot be the thing that goes stale when a provider is
   added legitimately.

Every checker is a PURE function of source text, which is what makes the two-sided
proof cheap: each is fired at a planted mutant assembled under ``tmp_path`` and
required to stay silent on the shipping module. No mutant is ever written into the
repo and no mutant is ever imported --- they are parsed, never executed.

ISOLATION CONTRACT (honored): every assertion was written from this iteration's spec
("Expected Behaviors" in ``pm.md``), the repo's own ``tests/`` tree, ``README.md`` and
``ROADMAP.md``, plus the product's observable behavior obtained by CALLING its public
interface. No engineer / reviewer / fix note was consulted and no ``git diff`` was
inspected. ``src/proactive_loop/llm/providers.py`` is parsed with ``ast`` because it is
the ARTIFACT UNDER TEST --- behaviors 1, 2, 3, 5 and 9 are assertions about that
file's docstring and AST shape --- not read as an implementation to mirror.

Offline and deterministic: no network, no API key, and NO optional provider SDK. The
live legs accept either outcome a fresh clone can produce --- ``scripted`` returns a
client, every other name raises ``LLMError`` from its own branch because the SDK is
absent --- and ``LLMError`` is not a ``ValueError`` subclass, so the distinction needs
no message parsing.

Python-version note: the CI matrix runs 3.12 and 3.13 and 3.13 strips the common
docstring indent while 3.12 does not, so nothing here asserts on docstring LAYOUT ---
only on case-folded substring presence and on AST shape.

SUITE-SIZE NOTE, stated because it shaped this module's SHAPE and nothing else.
``tests/test_iter204_behavior.py`` reds the build the moment the collected count
crosses the next hundred, and ``test_iter237_behavior.py``'s own note records why
that is not this iteration's work: the floor bump is a ~25-site coupled edit across
the README and five test modules and "is its own iteration". HEAD collects 5,683, so
this module's budget was 16 test FUNCTIONS, not 16 assertions. A first draft spent 25
(behavior 7 was a 7-way ``parametrize`` and five behaviors used two functions each);
every assertion of all nine behaviors survives here in 14, by pairing siblings inside
one function --- exactly the convention ``test_iter237`` used for the same reason.
Nothing was dropped to fit: behavior 7 became a loop over ``VALID_PROVIDERS`` that
collects ALL offenders, which names every failing provider where ``parametrize`` would
have reported them one at a time.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.config import Settings
from proactive_loop.llm import LLMError
from proactive_loop.llm.providers import VALID_PROVIDERS, create_client

REPO: Final[Path] = Path(__file__).resolve().parents[1]
MODULE_RELPATH: Final[str] = "src/proactive_loop/llm/providers.py"
MODULE_PATH: Final[Path] = REPO / MODULE_RELPATH
FUNC: Final[str] = "create_client"
REGISTRY_NAME: Final[str] = "VALID_PROVIDERS"

#: The vocabulary that ASSERTS a name-keyed collection of factories. Compared
#: case-insensitively; ``data driven`` is listed beside ``data-driven`` so a
#: re-hyphenation cannot slip the claim back in.
MAP_CLAIM_PHRASES: Final[tuple[str, ...]] = (
    "data-driven",
    "data driven",
    "small map",
    "dispatch table",
    "lookup table",
)

#: Behavior 2: the fail-fast contract must survive the rewrite. Either spelling
#: satisfies it -- the spec pins no sentence verbatim.
FAIL_FAST_TOKENS: Final[tuple[str, ...]] = ("unknown", "valid options")

#: Behavior 2: the replacement must name the real unit of extension.
SHAPE_TOKEN: Final[str] = "branch"

#: Behavior 8: the terminal ``raise`` is the ONLY validation gate, because
#: ``Settings.from_env`` accepts the string unvalidated.
UNKNOWN_MESSAGE: Final[str] = "unknown provider"
BOGUS_PROVIDER: Final[str] = "definitely-not-a-provider"

#: Names used only inside planted mutants. Assembled here so no test body re-spells
#: them and so neither can collide with a real provider name.
PHANTOM_ARM: Final[str] = "phantom-arm-not-in-registry"
ORPHAN_NAME: Final[str] = "orphan-name-without-an-arm"


# ---------------------------------------------------------------------------
# Pure source-text checkers. Every one takes SOURCE, never a path, so a mutant
# is a string and the two-sided proof costs no subprocess.
# ---------------------------------------------------------------------------
def shipped_source() -> str:
    """The shipping module's text, with a fail-open guard on the read itself."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert source.strip(), f"{MODULE_RELPATH} is empty -- every check below is vacuous"
    assert source.isascii(), (
        "the mutant splicers below index by column offset, which is a UTF-8 BYTE "
        "offset in CPython's ast; a non-ASCII module would silently mis-splice"
    )
    return source


def find_function(source: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in the parsed module")


def docstring_of(source: str, name: str) -> str:
    return ast.get_docstring(find_function(source, name)) or ""


def has_mapping(source: str, name: str = FUNC) -> bool:
    """True when ``name``'s body holds at least one dict literal or comprehension.

    This is the OTHER half of the implication: it is what earns the mapping
    vocabulary back, so it must be computed from the same parse as the claim rather
    than assumed to be False forever.
    """
    fn = find_function(source, name)
    return any(
        isinstance(node, (ast.Dict, ast.DictComp))
        for statement in fn.body
        for node in ast.walk(statement)
    )


def claimed_map_phrases(source: str, name: str = FUNC) -> list[str]:
    doc = docstring_of(source, name).lower()
    return [phrase for phrase in MAP_CLAIM_PHRASES if phrase in doc]


def map_claim_violations(source: str, name: str = FUNC) -> list[str]:
    """Violations of ``claims_mapping implies has_mapping``; empty when sound.

    Silent in three of the four quadrants on purpose: no claim (either way) and a
    claim BACKED by a real mapping are all honest. Only "claims a map, has none".
    """
    claimed = claimed_map_phrases(source, name)
    if not claimed or has_mapping(source, name):
        return []
    return [
        f"{name}'s docstring claims a name-keyed mapping ({claimed}) but its body "
        "holds no ast.Dict/ast.DictComp node -- the claim describes a structure the "
        "function does not have, and 'adding one branch' IS editing the chain it "
        "says it avoids"
    ]


def arm_literals(source: str, name: str = FUNC) -> set[str]:
    """The string literals ``L`` for which ``name``'s body compares ``provider == L``."""
    fn = find_function(source, name)
    found: set[str] = set()
    for statement in fn.body:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Compare):
                continue
            if not (isinstance(node.left, ast.Name) and node.left.id == "provider"):
                continue
            if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
                continue
            operand = node.comparators[0]
            if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                found.add(operand.value)
    return found


def registry_from_source(source: str) -> tuple[str, ...]:
    """``VALID_PROVIDERS`` as literal-eval'd from the module's own text."""
    tree = ast.parse(source)
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id == REGISTRY_NAME:
                assert node.value is not None, f"{REGISTRY_NAME} has no value"
                value = ast.literal_eval(node.value)
                assert isinstance(value, tuple), f"{REGISTRY_NAME} is not a tuple"
                return tuple(str(item) for item in value)
    raise AssertionError(f"{REGISTRY_NAME} not found at module level")


def parity_violations(source: str) -> list[str]:
    """Drift between ``VALID_PROVIDERS`` and the dispatch arms; empty when in step.

    Both sides come from the SAME source text, which is what lets a ``tmp_path``
    mutant move either one independently and be caught by the same checker.
    """
    registry = registry_from_source(source)
    arms = arm_literals(source)
    problems: list[str] = []
    for missing in sorted(set(registry) - arms):
        problems.append(
            f"{REGISTRY_NAME} lists {missing!r} but {FUNC} has no matching arm: the "
            "terminal raise is the only gate, so a user would be told "
            f"'unknown provider {missing!r}' by an error that then lists {missing!r} "
            "among the valid options"
        )
    for extra in sorted(arms - set(registry)):
        problems.append(
            f"{FUNC} dispatches on {extra!r}, which {REGISTRY_NAME} does not list: an "
            "undocumented provider reachable only by guessing"
        )
    return problems


# ---------------------------------------------------------------------------
# Mutant assembly. Every mutant is written under ``tmp_path`` and read back, so
# the checkers are exercised on a real file that is not in the repo.
# ---------------------------------------------------------------------------
def _span(source: str, lineno: int, col: int, end_lineno: int, end_col: int) -> tuple[int, int]:
    lines = source.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: lineno - 1]) + col
    end = sum(len(line) for line in lines[: end_lineno - 1]) + end_col
    return start, end


def with_docstring(source: str, name: str, new_doc: str) -> str:
    """Replace ``name``'s docstring literal, leaving every statement untouched."""
    assert '"""' not in new_doc and "\\" not in new_doc, "mutant docstring must be plain"
    fn = find_function(source, name)
    node = fn.body[0]
    assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant), (
        f"{name} does not open with a docstring"
    )
    assert node.end_lineno is not None and node.end_col_offset is not None
    start, end = _span(
        source, node.lineno, node.col_offset, node.end_lineno, node.end_col_offset
    )
    return f'{source[:start]}"""{new_doc}"""{source[end:]}'


def with_statement_before_the_raise(source: str, name: str, statement: str) -> str:
    """Splice ``statement`` (already newline-terminated lines) above the terminal raise."""
    fn = find_function(source, name)
    tail = fn.body[-1]
    assert isinstance(tail, ast.Raise), f"{name} no longer ends in a raise"
    lines = source.splitlines(keepends=True)
    indent = " " * tail.col_offset
    block = "".join(f"{indent}{line}\n" for line in statement.splitlines())
    lines.insert(tail.lineno - 1, block)
    return "".join(lines)


def with_registry(source: str, names: tuple[str, ...]) -> str:
    """Replace the ``VALID_PROVIDERS`` tuple literal, leaving ``create_client`` alone."""
    tree = ast.parse(source)
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id == REGISTRY_NAME:
                value = node.value
                assert value is not None
                assert value.end_lineno is not None and value.end_col_offset is not None
                start, end = _span(
                    source,
                    value.lineno,
                    value.col_offset,
                    value.end_lineno,
                    value.end_col_offset,
                )
                literal = "(" + ", ".join(repr(name) for name in names) + ")"
                return source[:start] + literal + source[end:]
    raise AssertionError(f"{REGISTRY_NAME} not found at module level")


def materialize(tmp_path: Path, source: str, stem: str) -> str:
    """Write a mutant under ``tmp_path`` and read it back, proving it parses."""
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    ast.parse(text)
    return text


# ===========================================================================
# Behavior 1 -- the false claim is gone.
# ===========================================================================
def test_b1_docstring_makes_no_dispatch_map_claim() -> None:
    """The claim is gone from the FILE and from the LOADED function alike.

    The second half matters because behavior 1 could otherwise be satisfied by a
    file the interpreter does not load -- a stale ``.pyc``, a shadowing install, a
    second copy on the path. Both sides go through ``inspect.cleandoc`` because that
    is what ``ast.get_docstring`` applies by default while ``__doc__`` is raw, and
    because 3.13 strips the common docstring indent where 3.12 does not: comparing
    the raw strings would make this leg interpreter-dependent.
    """
    source = shipped_source()
    doc = docstring_of(source, FUNC)
    assert doc.strip(), f"{FUNC} must keep a docstring"
    assert claimed_map_phrases(source) == [], (
        f"{FUNC}'s docstring still claims a dispatch map: {claimed_map_phrases(source)}"
    )
    assert inspect.cleandoc(create_client.__doc__ or "") == inspect.cleandoc(doc), (
        "the loaded function's __doc__ disagrees with the parsed file, so behavior 1 "
        "was checked against a file the interpreter does not use"
    )


# ===========================================================================
# Behavior 2 -- the replacement states the real shape and its reason.
# ===========================================================================
def test_b2_docstring_states_the_real_shape_and_keeps_the_fail_fast_contract() -> None:
    """Both halves of behavior 2, asserted separately inside one function."""
    doc = docstring_of(shipped_source(), FUNC).lower()
    assert any(token in doc for token in FAIL_FAST_TOKENS), (
        f"{FUNC}'s docstring no longer documents the fail-fast contract; expected one "
        f"of {FAIL_FAST_TOKENS}"
    )
    assert SHAPE_TOKEN in doc, (
        f"{FUNC}'s docstring must name the {SHAPE_TOKEN!r} as the unit of extension, "
        "which is what makes the per-branch lazy import legible"
    )


# ===========================================================================
# Behavior 3 -- an implication computed from one parse, not a word ban.
# ===========================================================================
def test_b3_the_shipped_module_has_no_mapping_so_it_may_not_claim_one() -> None:
    source = shipped_source()
    assert has_mapping(source) is False, (
        f"{FUNC} now holds a mapping node; the claim vocabulary is permitted again, "
        "and this test should be re-stated rather than deleted"
    )
    assert claimed_map_phrases(source) == []
    assert map_claim_violations(source) == []


# ===========================================================================
# Behavior 4 -- the checker is proved on THREE arms, not two.
# ===========================================================================
def test_b4a_restoring_the_map_claim_is_caught(tmp_path: Path) -> None:
    """(a) The exact sentence this iteration deleted must go red again."""
    restored = with_docstring(
        shipped_source(),
        FUNC,
        "Dispatch is data-driven off a small map so adding a provider means adding "
        "one branch, not editing a long if/elif chain.",
    )
    mutant = materialize(tmp_path, restored, "providers_claims_a_map")
    assert has_mapping(mutant) is False, "the mutant must not have gained a mapping"
    problems = map_claim_violations(mutant)
    assert len(problems) == 1, f"expected exactly one violation, got {problems}"
    assert FUNC in problems[0]
    assert "data-driven" in problems[0] and "small map" in problems[0], (
        f"the violation must NAME the offending phrases: {problems[0]}"
    )


def test_b4b_the_shipped_module_yields_no_violation(tmp_path: Path) -> None:
    """(b) The control, read back through the same ``tmp_path`` path as the mutants."""
    unchanged = materialize(tmp_path, shipped_source(), "providers_unchanged")
    assert map_claim_violations(unchanged) == []


def test_b4c_a_real_mapping_earns_the_vocabulary_back(tmp_path: Path) -> None:
    """(c) The load-bearing arm: SILENCE on the honest future shape.

    Without this the guard would be a standing ban on five phrases, and the very
    refactor that would make the sentence TRUE could never ship.
    """
    claiming = with_docstring(
        shipped_source(),
        FUNC,
        "Dispatch is data-driven off a small map of name to factory.",
    )
    both = with_statement_before_the_raise(
        claiming, FUNC, '_factories = {"scripted": _create_scripted}'
    )
    mutant = materialize(tmp_path, both, "providers_honest_map")
    assert has_mapping(mutant) is True, "the planted dict literal was not detected"
    assert claimed_map_phrases(mutant) != [], "the mutant must still claim a map"
    assert map_claim_violations(mutant) == [], (
        "the guard must stay silent when the claim is BACKED by a real mapping, or it "
        "is a word ban that forbids the honest future shape"
    )


def test_b4d_a_silent_module_with_a_mapping_is_also_honest(tmp_path: Path) -> None:
    """The fourth quadrant: a mapping and no claim is not a violation either."""
    quiet = with_statement_before_the_raise(
        shipped_source(), FUNC, '_factories = {"scripted": _create_scripted}'
    )
    mutant = materialize(tmp_path, quiet, "providers_quiet_map")
    assert has_mapping(mutant) is True
    assert map_claim_violations(mutant) == []


# ===========================================================================
# Behavior 5 -- arm parity holds today, derived on both sides.
# ===========================================================================
def test_b5_arms_equal_the_imported_registry() -> None:
    """Parity today, plus the tie that makes the source-side roster trustworthy.

    Behavior 6 mutates the tuple IN SOURCE, so the parity checker reads both sides
    from text; the final assertion is what makes that faithful to the imported value.
    """
    source = shipped_source()
    arms = arm_literals(source)
    assert arms == set(VALID_PROVIDERS), (
        f"dispatch arms {sorted(arms)} disagree with the imported {REGISTRY_NAME} "
        f"{sorted(VALID_PROVIDERS)}"
    )
    assert len(arms) == len(VALID_PROVIDERS), (
        f"{REGISTRY_NAME} holds a duplicate name: {len(VALID_PROVIDERS)} entries "
        f"collapse to {len(arms)} distinct arms"
    )
    assert registry_from_source(source) == tuple(VALID_PROVIDERS), (
        "the registry parsed from the module's text differs from the imported value"
    )


# ===========================================================================
# Behavior 6 -- parity fires in BOTH directions on planted mutants.
# ===========================================================================
def test_b6a_a_registry_name_without_an_arm_is_caught(tmp_path: Path) -> None:
    grown = with_registry(shipped_source(), tuple(VALID_PROVIDERS) + (ORPHAN_NAME,))
    mutant = materialize(tmp_path, grown, "providers_orphan_name")
    assert registry_from_source(mutant)[-1] == ORPHAN_NAME
    assert arm_literals(mutant) == set(VALID_PROVIDERS), (
        "behavior 6(a) requires create_client to be UNTOUCHED"
    )
    problems = parity_violations(mutant)
    assert len(problems) == 1, f"expected exactly one violation, got {problems}"
    assert ORPHAN_NAME in problems[0], f"the violation must name the missing arm: {problems[0]}"


def test_b6b_an_arm_without_a_registry_name_is_caught(tmp_path: Path) -> None:
    grown = with_statement_before_the_raise(
        shipped_source(),
        FUNC,
        f'if provider == "{PHANTOM_ARM}":\n    return _create_scripted(settings)',
    )
    mutant = materialize(tmp_path, grown, "providers_phantom_arm")
    assert registry_from_source(mutant) == tuple(VALID_PROVIDERS), (
        "behavior 6(b) requires the registry to be UNTOUCHED"
    )
    assert PHANTOM_ARM in arm_literals(mutant)
    problems = parity_violations(mutant)
    assert len(problems) == 1, f"expected exactly one violation, got {problems}"
    assert PHANTOM_ARM in problems[0], f"the violation must name the extra arm: {problems[0]}"


def test_b6c_the_shipped_module_produces_neither_violation(tmp_path: Path) -> None:
    unchanged = materialize(tmp_path, shipped_source(), "providers_parity_control")
    assert parity_violations(unchanged) == []


# ===========================================================================
# Behavior 7 -- the live consequence, with no optional SDK installed.
# ===========================================================================
def test_b7_every_listed_provider_reaches_its_own_branch() -> None:
    """No name in ``VALID_PROVIDERS`` may fall through to the terminal ``raise``.

    Either outcome a fresh clone can produce is accepted: ``scripted`` returns a
    client, and every other name raises ``LLMError`` from inside its own branch
    because the optional SDK is absent -- which is itself proof the branch was
    entered. The first two assertions pin the PREMISE behind that ``except`` split
    (``LLMError`` is not a ``ValueError``), so no error message is ever parsed.

    Written as a loop rather than a ``parametrize`` on purpose: the roster is driven
    by ``VALID_PROVIDERS``, so every name is still covered, and collecting ALL
    offenders before failing names each one instead of only the first. The corpus's
    own convention -- see ``test_iter237_behavior.py``'s suite-size note -- is that a
    behavior module has a budget of test FUNCTIONS, not of assertions.
    """
    assert not issubclass(LLMError, ValueError)
    assert ValueError not in LLMError.__mro__

    fell_through: list[str] = []
    for provider in VALID_PROVIDERS:
        settings = Settings.from_env(provider=provider)
        try:
            client = create_client(settings)
        except ValueError as exc:
            fell_through.append(f"{provider!r}: {exc}")
            continue
        except LLMError:
            continue
        assert client is not None, f"{provider!r} returned no client"
    assert fell_through == [], (
        f"{len(fell_through)} name(s) listed in {REGISTRY_NAME} fell through to the "
        f"terminal raise: {fell_through}"
    )


# ===========================================================================
# Behavior 8 -- the negative leg: the terminal raise is the only gate.
# ===========================================================================
def test_b8_an_unlisted_provider_fails_fast_with_a_valueerror() -> None:
    settings = Settings.from_env(provider=BOGUS_PROVIDER)
    assert settings.provider == BOGUS_PROVIDER, (
        "Settings.from_env validated the provider; behavior 8's premise -- that "
        f"{FUNC} is the ONLY gate -- no longer holds and this test must be re-stated"
    )
    with pytest.raises(ValueError) as caught:
        create_client(settings)
    message = str(caught.value)
    assert UNKNOWN_MESSAGE in message.lower(), message
    assert BOGUS_PROVIDER in message, f"the error must name the rejected provider: {message}"
    for name in VALID_PROVIDERS:
        assert name in message, f"the error must list {name!r} among the valid options"


# ===========================================================================
# Behavior 9 -- a docstring-only change: the executable shape is pinned.
# ===========================================================================
def test_b9_create_client_is_still_a_flat_run_of_arms_ending_in_a_raise() -> None:
    """Docstring-only, expressed durably.

    A before/after ``ast.dump`` comparison cannot ship (after the commit there is no
    "before"), so the property is pinned as a shape instead: one arm per listed
    provider, a terminal ``raise``, and no mapping node.
    """
    fn = find_function(shipped_source(), FUNC)
    arms = [node for node in fn.body if isinstance(node, ast.If)]
    assert len(arms) == len(VALID_PROVIDERS), (
        f"expected one top-level arm per listed provider ({len(VALID_PROVIDERS)}); "
        f"found {len(arms)}"
    )
    assert isinstance(fn.body[-1], ast.Raise), f"{FUNC} must still end in a raise"
    assert has_mapping(shipped_source()) is False

    # The lazy-import property the docstring's reason rests on: ``create_client``
    # itself holds no ``import``, so the optional SDKs are reached only through the
    # per-provider helpers, which is what keeps the offline scripted default's
    # ``sys.modules`` free of them.
    imports = [
        node
        for statement in fn.body
        for node in ast.walk(statement)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert imports == [], f"{FUNC} holds {len(imports)} import statement(s) in its body"
