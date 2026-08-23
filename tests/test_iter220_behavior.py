"""Black-box behavior tests for the DECLARED console-script entry point.

Feature under test (``pm.md`` iteration 241, closing roadmap row #117): ``pyproject.toml``
declares ``[project.scripts] pla = "proactive_loop.cli:main"``, and until this module landed
**nothing in the suite read that string**. The two packaging oracles that already exist both
grade the INSTALLED wrapper as a subprocess (``test_iter114_behavior.py``'s ``pla config
--json`` run, ``test_iter155_behavior.py``'s console-script probe), i.e. whatever the last
``uv sync`` happened to drop into ``.venv``. So renaming or moving ``cli.main`` left the
PUBLISHED declaration stale while every gate stayed green until somebody rebuilt the venv --
and ``pip install`` / ``uv tool install`` is the documented way a stranger gets the ``pla``
command on a public portfolio repo, where a stale console script is simply a broken install.

This module closes that gap by RESOLVING the declaration the way a packaging tool's generated
wrapper does -- parse the TOML, split ``module:attribute``, ``importlib.import_module`` the
module part, ``getattr`` the attribute part -- and asserting the result **is** (identity)
``proactive_loop.cli.main``. It buys no user-facing capability; it is hardening, and the row
it closes says so.

Two design rules the spec imposes, both load-bearing:

* **The resolver takes the declaration as an ARGUMENT** (:func:`_resolve_declaration`), so the
  negative controls can drive it with a synthetic string. A resolver that read the live table
  internally could not be falsified, and an oracle that cannot fail proves nothing.
* **The expected value is never restated as a literal that is then compared to itself.**
  Behaviors 1-6 all run off the value PARSED out of ``pyproject.toml``.
  :data:`DECLARED_ENTRY_POINT` is asserted exactly ONCE, by behavior 7, as the ground fact
  this contract pins -- so a silent drift in the declaration itself is caught too.

ISOLATION CONTRACT (honored): every assertion drives public artifacts only -- the tracked
``pyproject.toml`` as TEXT, and the importable public package ``proactive_loop``. **No file
under ``src/`` was read, no engineer or reviewer notes were read, and no ``git diff`` was
consulted.** Fully offline and build-free: zero subprocesses, zero network (behavior 6 proves
both by making a subprocess or a socket connect RAISE for the duration of a resolution), and
nothing under ``.venv/``, ``build/``, ``dist/`` or ``site-packages`` is read -- which is
exactly the difference between this module and the two subprocess oracles it complements.
Paths are derived from ``__file__``, never from the process CWD and never from a directory
basename, so the module passes from any working directory (behavior 6 chdirs to prove it).
"""

from __future__ import annotations

import importlib
import socket
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest

import proactive_loop.cli

#: Repo root, derived from THIS file. Never ``Path.cwd()``: pytest-xdist workers inherit
#: whatever directory the parent process happened to sit in, and a fresh clone is checked
#: out under an arbitrary name, so both CWD and the directory basename are unusable.
REPO: Final[Path] = Path(__file__).resolve().parents[1]
PYPROJECT: Final[Path] = REPO / "pyproject.toml"

#: The console scripts this project publishes, as a SET rather than a count -- a count in a
#: name or an assertion is the decaying-constant defect this repo has retired repeatedly.
EXPECTED_SCRIPT_NAMES: Final[frozenset[str]] = frozenset({"pla"})

#: The ground fact behavior 7 pins, and the ONLY place in this module where the declaration
#: is spelled as a literal. Every other behavior reads the live value out of the TOML.
DECLARED_ENTRY_POINT: Final[str] = "proactive_loop.cli:main"

#: Directory names that mean "a build artifact or an installed copy". The whole point of this
#: oracle is that it grades the SOURCE declaration, so reading any of these would silently
#: reintroduce the stale-``.venv`` blind spot it exists to close.
FORBIDDEN_PATH_PARTS: Final[tuple[str, ...]] = (".venv", "build", "dist", "site-packages")

#: Synthetic declarations for behavior 5. Named constants rather than inline literals so the
#: corpus-wide scans in this suite can see at a glance that they are deliberate bad input.
ABSENT_MODULE_DECLARATION: Final[str] = "proactive_loop.no_such_module:main"
ABSENT_ATTRIBUTE_DECLARATION: Final[str] = "proactive_loop.cli:no_such_attribute"
COLONLESS_DECLARATION: Final[str] = "proactive_loop.cli.main"


class ConsoleScriptError(Exception):
    """A console-script declaration could not be resolved to a real object.

    One exception type for every rejection reason, because the CALLER's question is binary
    ("does the published declaration work?"). The distinct underlying causes are preserved on
    ``__cause__`` instead of in the type, and behavior 5 asserts they really are distinct --
    otherwise a single ``except Exception`` in the resolver could collapse "the module is
    gone" and "the function was renamed" into one indistinguishable failure.
    """


def _read_scripts_table(pyproject: Path) -> dict[str, Any]:
    """Return the ``[project.scripts]`` table parsed out of ``pyproject``.

    Takes the path as an argument so the reader is location-independent and testable; the
    caller supplies :data:`PYPROJECT`, which is anchored on ``__file__``.
    """
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        raise ConsoleScriptError(f"{pyproject} declares no [project] table")
    scripts = project.get("scripts")
    if not isinstance(scripts, dict):
        raise ConsoleScriptError(f"{pyproject} declares no [project.scripts] table")
    return scripts


def _live_declaration() -> str:
    """The declaration string as PUBLISHED today, read fresh from the tracked TOML."""
    scripts = _read_scripts_table(PYPROJECT)
    (name,) = sorted(EXPECTED_SCRIPT_NAMES)
    declaration = scripts[name]
    assert isinstance(declaration, str), (
        f"[project.scripts] {name} must be a string, got {type(declaration).__name__}"
    )
    return declaration


def _split_declaration(declaration: str) -> tuple[str, str]:
    """Split ``module:attribute`` into its two halves, rejecting every malformed shape.

    Every rejection message quotes the offending declaration, because the failure a reader
    will actually meet is "CI went red on a packaging contract" and the declaration is the
    one datum that tells them which file to open.
    """
    if any(character.isspace() for character in declaration):
        raise ConsoleScriptError(
            f"console-script declaration {declaration!r} contains whitespace; a "
            "console-script entry point must be a bare module:attribute string"
        )
    if declaration.count(":") != 1:
        raise ConsoleScriptError(
            f"console-script declaration {declaration!r} must hold exactly one ':' "
            f"separating module from attribute, found {declaration.count(':')}"
        )
    module_part, _, attribute_part = declaration.partition(":")
    if not module_part or not attribute_part:
        raise ConsoleScriptError(
            f"console-script declaration {declaration!r} has an empty module or "
            f"attribute half (module={module_part!r}, attribute={attribute_part!r})"
        )
    return module_part, attribute_part


def _resolve_declaration(declaration: str) -> object:
    """Resolve a console-script declaration to the object it names, by IMPORT.

    This mirrors what a packaging tool's generated wrapper does at runtime, which is the
    whole reason the assertion is worth anything: if this function cannot reach the object,
    neither can the ``pla`` command a stranger just installed.
    """
    module_part, attribute_part = _split_declaration(declaration)
    try:
        module = importlib.import_module(module_part)
    except ImportError as exc:
        raise ConsoleScriptError(
            f"console-script declaration {declaration!r} names module {module_part!r}, "
            f"which does not import: {exc}"
        ) from exc
    try:
        return getattr(module, attribute_part)
    except AttributeError as exc:
        raise ConsoleScriptError(
            f"console-script declaration {declaration!r} names attribute "
            f"{attribute_part!r}, which is absent from module {module_part!r}"
        ) from exc


# ===========================================================================
# Behavior 1 -- the scripts table exists and publishes exactly one command.
# ===========================================================================
def test_b01_pyproject_publishes_exactly_the_expected_console_script_set() -> None:
    """A second undeclared console script, or a renamed one, is a packaging change no
    other gate in this repo can see -- the subprocess oracles look up ``pla`` by name."""
    scripts = _read_scripts_table(PYPROJECT)
    assert set(scripts) == set(EXPECTED_SCRIPT_NAMES), (
        f"{PYPROJECT.name} [project.scripts] must publish exactly "
        f"{sorted(EXPECTED_SCRIPT_NAMES)}, got {sorted(scripts)}"
    )


# ===========================================================================
# Behavior 2 -- the declaration is a well-formed module:attribute string.
# ===========================================================================
def test_b02_the_live_declaration_is_a_well_formed_module_colon_attribute_string() -> None:
    declaration = _live_declaration()
    assert not any(character.isspace() for character in declaration), (
        f"the declaration must hold no whitespace at all, got {declaration!r}"
    )
    assert declaration.count(":") == 1, (
        f"the declaration must hold exactly one ':', got {declaration!r}"
    )
    module_part, attribute_part = _split_declaration(declaration)
    assert module_part, f"empty module half in {declaration!r}"
    assert attribute_part, f"empty attribute half in {declaration!r}"


# ===========================================================================
# Behavior 3 -- the declaration resolves, BY IMPORT, to the very object it names.
# ===========================================================================
def test_b03_the_live_declaration_resolves_to_the_cli_main_object_itself() -> None:
    """Identity, not equality and not a name match: this is the assertion that reds the
    build when ``main`` is renamed or moved, which is the defect row #117 recorded."""
    resolved = _resolve_declaration(_live_declaration())
    assert resolved is proactive_loop.cli.main, (
        f"the published console script resolves to {resolved!r}, not to "
        f"proactive_loop.cli.main ({proactive_loop.cli.main!r}) -- an installed `pla` "
        "would run the wrong object, or fail to start at all"
    )


# ===========================================================================
# Behavior 4 -- what it resolves to is callable.
# ===========================================================================
def test_b04_the_resolved_entry_point_is_callable() -> None:
    resolved = _resolve_declaration(_live_declaration())
    assert callable(resolved), (
        f"a console-script target must be callable; {resolved!r} is not, so the "
        "generated wrapper would raise TypeError on every invocation"
    )


# ===========================================================================
# Behavior 5 -- the resolver is driven by its ARGUMENT: two distinct negative
# controls plus a malformed-shape control, each naming the offender.
# ===========================================================================
def test_b05_a_declaration_whose_module_is_absent_is_rejected() -> None:
    with pytest.raises(ConsoleScriptError) as caught:
        _resolve_declaration(ABSENT_MODULE_DECLARATION)
    assert ABSENT_MODULE_DECLARATION in str(caught.value), (
        f"the rejection must name the offending declaration, got {caught.value!s}"
    )
    assert isinstance(caught.value.__cause__, ImportError), (
        f"the module half must fail through the IMPORT machinery, got "
        f"{type(caught.value.__cause__).__name__}"
    )


def test_b05_a_declaration_whose_attribute_is_absent_is_rejected() -> None:
    with pytest.raises(ConsoleScriptError) as caught:
        _resolve_declaration(ABSENT_ATTRIBUTE_DECLARATION)
    assert ABSENT_ATTRIBUTE_DECLARATION in str(caught.value), (
        f"the rejection must name the offending declaration, got {caught.value!s}"
    )
    assert isinstance(caught.value.__cause__, AttributeError), (
        f"the attribute half must fail through getattr, got "
        f"{type(caught.value.__cause__).__name__}"
    )


def test_b05_the_two_negative_controls_fail_for_genuinely_distinct_reasons() -> None:
    """A single control cannot grade a two-stage resolver: a resolver that swallowed
    everything into one ``except Exception`` would pass both controls above while being
    unable to tell "the module is gone" from "the function was renamed"."""
    with pytest.raises(ConsoleScriptError) as absent_module:
        _resolve_declaration(ABSENT_MODULE_DECLARATION)
    with pytest.raises(ConsoleScriptError) as absent_attribute:
        _resolve_declaration(ABSENT_ATTRIBUTE_DECLARATION)
    module_cause = type(absent_module.value.__cause__)
    attribute_cause = type(absent_attribute.value.__cause__)
    assert module_cause is not attribute_cause, (
        f"both controls failed with the same cause type {module_cause.__name__}, so this "
        "resolver cannot distinguish a missing module from a missing attribute"
    )
    assert not issubclass(module_cause, attribute_cause), (
        f"{module_cause.__name__} is a subclass of {attribute_cause.__name__} -- the two "
        "controls are not independent"
    )
    assert not issubclass(attribute_cause, module_cause), (
        f"{attribute_cause.__name__} is a subclass of {module_cause.__name__} -- the two "
        "controls are not independent"
    )


def test_b05_a_declaration_with_no_colon_is_rejected_before_any_import() -> None:
    with pytest.raises(ConsoleScriptError) as caught:
        _resolve_declaration(COLONLESS_DECLARATION)
    message = str(caught.value)
    assert COLONLESS_DECLARATION in message, (
        f"the rejection must name the offending declaration, got {message}"
    )
    assert "':'" in message, f"the rejection must say what is missing, got {message}"


def test_b05_a_declaration_carrying_whitespace_is_rejected() -> None:
    """Guards the shape a hand-edit produces: ``pla = "proactive_loop.cli : main"``
    parses as TOML and installs a wrapper that cannot import ``proactive_loop.cli ``."""
    spaced = f"{DECLARED_ENTRY_POINT[:len('proactive_loop.cli')]} : main"
    with pytest.raises(ConsoleScriptError) as caught:
        _resolve_declaration(spaced)
    assert "whitespace" in str(caught.value), (
        f"the rejection must name whitespace as the fault, got {caught.value!s}"
    )


# ===========================================================================
# Behavior 6 -- location-independent, build-free, offline. No subprocess, no
# socket, nothing read out of an installed or built copy.
# ===========================================================================
def test_b06_the_toml_is_located_from_file_not_from_the_process_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the whole chain from an unrelated directory and require byte-identical
    results. A CWD-relative reader passes in-repo and fails in every other caller."""
    from_repo = _live_declaration()
    monkeypatch.chdir(tmp_path)
    assert Path.cwd() == tmp_path.resolve(), "the chdir did not take effect"
    assert _live_declaration() == from_repo, (
        "the declaration read from an unrelated CWD differs from the in-repo read, so "
        "this oracle depends on the process working directory"
    )
    assert _resolve_declaration(_live_declaration()) is proactive_loop.cli.main


def test_b06_the_toml_path_is_absolute_and_holds_no_build_artifact_directory() -> None:
    assert PYPROJECT.is_absolute(), f"{PYPROJECT} must be absolute"
    assert PYPROJECT.is_file(), f"{PYPROJECT} must exist as a file"
    offenders = [part for part in PYPROJECT.parts if part in FORBIDDEN_PATH_PARTS]
    assert offenders == [], (
        f"the oracle reads {PYPROJECT}, which lives under {offenders} -- it must grade "
        "the SOURCE declaration, never an installed or built copy"
    )


def test_b06_resolution_spawns_no_subprocess_and_opens_no_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two-sided in the only way that matters here: the forbidden calls are made to RAISE,
    so a resolution that reached for either would fail loudly instead of passing quietly."""

    def _forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"forbidden call reached: args={args!r} kwargs={kwargs!r}")

    for attribute in ("run", "Popen", "check_output", "check_call", "call"):
        monkeypatch.setattr(subprocess, attribute, _forbidden)
    # Patch ``connect`` rather than the socket class: a network CALL requires it, while
    # replacing the class could disturb the already-connected xdist worker channel.
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)

    declaration = _live_declaration()
    assert _resolve_declaration(declaration) is proactive_loop.cli.main
    with pytest.raises(ConsoleScriptError):
        _resolve_declaration(ABSENT_MODULE_DECLARATION)


# ===========================================================================
# Behavior 7 -- the one literal: the ground fact this contract pins.
# ===========================================================================
def test_b07_the_live_declaration_is_the_string_this_contract_pins() -> None:
    """Asserted exactly once, deliberately. Behaviors 1-6 run off the PARSED value, so
    they would all still pass if the declaration silently drifted to another real object;
    this is the assertion that notices the drift itself."""
    assert _live_declaration() == DECLARED_ENTRY_POINT, (
        f"{PYPROJECT.name} now publishes {_live_declaration()!r} rather than the pinned "
        f"{DECLARED_ENTRY_POINT!r}. If the move is intended, update this constant in the "
        "same commit -- that edit is the record that the published contract changed"
    )


# ===========================================================================
# TESTER ROUND -- the controls behaviors 1, 3, 4 and 6 were missing.
#
# Everything above grades the LIVE declaration, and three of those behaviors had
# no falsifiable side: a resolver that ignored its argument and a reader that
# ignored its path would both pass. Behavior 6 is the sharper case. Its headline
# claim is that this oracle grades the SOURCE declaration rather than an installed
# copy, but FORBIDDEN_PATH_PARTS was applied only to the TOML path -- which is
# anchored on __file__ and so can never sit in one of those directories. The half
# that CAN is the import, and that half was asserted nowhere: it was merely true
# of this environment.
# ===========================================================================

#: A declaration naming a real module and a real but NON-CALLABLE attribute. Drives the
#: falsifiable side of behaviors 3 and 4, so their assertions are claims about the
#: DECLARATION rather than restatements of the resolver's own shape.
NON_CALLABLE_DECLARATION: Final[str] = "proactive_loop.cli:__name__"


def _module_origin(declaration: str) -> Path:
    """Absolute file the declaration's MODULE half was actually loaded from."""
    module_part, _ = _split_declaration(declaration)
    module = importlib.import_module(module_part)
    origin = getattr(module, "__file__", None)
    assert isinstance(origin, str) and origin, (
        f"module {module_part!r} exposes no usable __file__, so this oracle cannot tell "
        "a source checkout from an installed or built copy"
    )
    return Path(origin).resolve()


def _installed_copy_offenders(origin: Path) -> list[str]:
    """Path components of ``origin`` that mean "an installed or built copy", in order."""
    return [part for part in origin.parts if part in FORBIDDEN_PATH_PARTS]


def _write_synthetic_pyproject(directory: Path, body: str) -> Path:
    """Write a throwaway ``pyproject.toml`` under ``directory`` and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "pyproject.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_b06_the_declaration_resolves_out_of_the_tracked_source_tree() -> None:
    """Behavior 6's headline property, ASSERTED rather than assumed.

    If this package were installed non-editably, ``import proactive_loop.cli`` would
    resolve inside ``site-packages`` and this module would grade a BUILT COPY while every
    assertion above still passed -- which is exactly the stale-``.venv`` blind spot row
    #117 exists to close, reintroduced inside the oracle that closes it.

    If this ever reds, the environment holds a non-editable copy: re-run the documented
    setup (``uv sync``, which both CI and the fresh-clone release check run, and which
    installs this project in editable mode). Do not weaken the assertion -- grading the
    checkout is the whole difference between this module and the two subprocess oracles.
    """
    planted = Path("/somewhere/.venv/lib/python3.12/site-packages/proactive_loop/cli.py")
    assert _installed_copy_offenders(planted) == [".venv", "site-packages"], (
        "the installed-copy detector does not fire on a planted site-packages path, so "
        "the assertions below are vacuous and would pass against a built copy"
    )
    assert not planted.is_relative_to(REPO / "src"), (
        f"the planted installed-copy path {planted} reads as inside the source tree, so "
        "the source-tree assertion below cannot fail"
    )

    origin = _module_origin(_live_declaration())
    offenders = _installed_copy_offenders(origin)
    assert offenders == [], (
        f"the declaration's module half resolved to {origin}, which sits under "
        f"{offenders} -- this oracle would be grading an installed or built copy rather "
        "than the source declaration it exists to pin"
    )
    source_root = REPO / "src"
    assert origin.is_relative_to(source_root), (
        f"the declaration's module half resolved to {origin}, which is outside the "
        f"tracked source tree {source_root} -- see this test's docstring for the remedy"
    )


def test_b03_b04_control_a_declaration_naming_a_non_callable_attribute_resolves_to_it() -> None:
    """The falsifiable side of behaviors 3 and 4.

    Both assert a property of the LIVE value, so a resolver that ignored its argument and
    returned ``cli.main`` unconditionally would satisfy both. This control drives the same
    resolver with a declaration naming a real attribute that is neither ``main`` nor
    callable, and requires that object -- not ``main`` -- to come back.
    """
    resolved = _resolve_declaration(NON_CALLABLE_DECLARATION)
    assert resolved is not proactive_loop.cli.main, (
        f"{NON_CALLABLE_DECLARATION!r} resolved to proactive_loop.cli.main, so the "
        "resolver is not driven by the attribute half of its argument and behavior 3's "
        "identity assertion cannot fail"
    )
    assert resolved == proactive_loop.cli.__name__, (
        f"{NON_CALLABLE_DECLARATION!r} must resolve to the attribute it names, got "
        f"{resolved!r}"
    )
    assert not callable(resolved), (
        f"{NON_CALLABLE_DECLARATION!r} was chosen because it names a non-callable "
        f"attribute; it resolved to {resolved!r}, so behavior 4 has no failing side"
    )


def test_b01_the_scripts_table_reader_is_driven_by_the_path_it_is_given(
    tmp_path: Path,
) -> None:
    """Positive control for the reader.

    Behavior 6's location independence rests on the reader taking a PATH argument. If it
    secretly read the live file, every synthetic fixture in this section would silently
    grade ``pyproject.toml`` instead, and the negative controls below would prove nothing.
    """
    synthetic = _write_synthetic_pyproject(
        tmp_path / "elsewhere",
        '[project]\nname = "not-this-project"\n\n[project.scripts]\n'
        'other-command = "some.module:entry"\n',
    )
    assert _read_scripts_table(synthetic) == {"other-command": "some.module:entry"}, (
        "the reader did not return the synthetic table it was handed, so it is not "
        "driven by its path argument"
    )
    assert set(_read_scripts_table(PYPROJECT)) == set(EXPECTED_SCRIPT_NAMES), (
        "reading a synthetic file left the live read changed, so the reader carries state"
    )


def test_b01_a_malformed_scripts_declaration_is_rejected_with_a_distinguishable_message(
    tmp_path: Path,
) -> None:
    """Three reader rejections, each naming the offending FILE, and each distinguishable.

    A reader that collapsed "no ``[project]`` at all" into "no ``[project.scripts]``"
    would leave a maintainer guessing which half of the packaging metadata they broke.
    """
    no_project = _write_synthetic_pyproject(
        tmp_path / "no-project", '[build-system]\nrequires = ["hatchling"]\n'
    )
    no_scripts = _write_synthetic_pyproject(
        tmp_path / "no-scripts", '[project]\nname = "x"\nversion = "0.0.0"\n'
    )
    scripts_not_a_table = _write_synthetic_pyproject(
        tmp_path / "scripts-not-a-table",
        '[project]\nname = "x"\nversion = "0.0.0"\nscripts = "oops"\n',
    )

    messages: dict[Path, str] = {}
    for path in (no_project, no_scripts, scripts_not_a_table):
        with pytest.raises(ConsoleScriptError) as caught:
            _read_scripts_table(path)
        message = str(caught.value)
        assert str(path) in message, (
            f"the rejection for {path} must name the offending file, got {message}"
        )
        messages[path] = message

    assert "[project]" in messages[no_project], (
        f"the missing-[project] rejection must say which table is absent, got "
        f"{messages[no_project]}"
    )
    for path in (no_scripts, scripts_not_a_table):
        assert "[project.scripts]" in messages[path], (
            f"the rejection for {path} must name [project.scripts], got {messages[path]}"
        )
    assert "[project.scripts]" not in messages[no_project], (
        "a file with no [project] table at all was reported as a missing "
        "[project.scripts] table, so the two faults are indistinguishable: "
        f"{messages[no_project]}"
    )
