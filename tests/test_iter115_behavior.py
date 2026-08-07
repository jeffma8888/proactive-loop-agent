"""Behavior tests for state-dir iteration 108 (ships as commit-seq ``factory iter 115``).

Feature under test: the package's type oracle is RATCHETED from mypy default
mode to ``strict`` minus exactly one explicitly deferred flag
(``disallow_any_generics``), the 3 errors that ratchet surfaces are fixed, and
the ratchet is guarded so it cannot silently regress.

Why this file is the oracle
The README's human-owned intro promises "fully type-hinted (ships a PEP 561
``py.typed`` marker)", and iters 86-88 built ``make typecheck`` plus a CI step as
the permanent machine oracle for that claim. But DEFAULT-mode mypy does not check
the signature or the body of an UNANNOTATED function at all, so that oracle was
structurally blind to the exact defect class the claim is about --- and it did in
fact report "Success" on a completely unannotated parameter. A gate that cannot
see the defect it advertises is a documentation claim wearing a build step's
clothes. These tests therefore pin three separate things: that the ratchet is
SET (config), that it FIRES (a synthetic bad module is rejected), and that the
shipped package is actually CLEAN under it (an independent ``ast`` sweep).

Why the deferral is tested as hard as the ratchet
``disallow_any_generics`` owns 35 of the 38 strict errors, so it is deferred to a
queued roadmap row. A deferral that is not asserted is indistinguishable from an
accident, and a deferral that is not RECORDED is indistinguishable from being
forgotten --- so behavior 3 pins the deferred set to EXACTLY one flag, behavior 5
proves a bare generic really is still accepted (the deferral is real, not a
mis-measurement), and behavior 8 requires the roadmap row that owes the cleanup.

Why the ``ast`` sweep is deliberately STRICTER than mypy
mypy special-cases ``__init__`` and accepts a missing ``-> None`` when at least
one argument is annotated, so mypy will NEVER report that shape. The sweep does.
Behaviors 1 and 6 are therefore expected to disagree on it, and the sweep is the
stricter of the two on purpose: "fully type-hinted" is a promise about the source
a reader sees, not about what a checker happens to excuse.

Isolation: black-box. The seams used are (a) parsing ``pyproject.toml`` with
``tomllib`` --- which the spec's behaviors 2-4 REQUIRE as the config oracle,
(b) RUNNING the locked mypy as a subprocess over modules this file writes into
``tmp_path``, (c) parsing the shipped package with ``ast`` --- which behavior 6
REQUIRES, and which reads only declared signatures, never logic, and (d) driving
the public ``ToolRegistry`` / ``_TOOL_CATALOG`` seams. No implementation source
was read while writing this file; no engineer, reviewer or fix note was opened.

Offline: file reads, in-process imports, and four short ``sys.executable -m mypy``
subprocesses against the project's own locked checker. No network, no API keys,
no writes outside ``tmp_path``.

Every reader here is fail-CLOSED and is fired on a known-bad sample in the same
module (``test_guard_*``): a config reader that silently returns ``{}``, an
``ast`` sweep that silently walks zero functions, or a mypy probe that "passes"
because the checker never ran would each make these guards pass vacuously, which
is strictly worse than having no guard at all.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from proactive_loop.cli import _TOOL_CATALOG
from proactive_loop.loop.tools import ToolRegistry

# --------------------------------------------------------------------------
# Tester's ground facts --- transcribed from the spec (pm.md), NOT imported
# from the implementation, so a silent drift in either direction is caught.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
PKG = REPO / "src" / "proactive_loop"
ROADMAP = REPO / "ROADMAP.md"

# Spec behavior 3: exactly ONE strict component may be switched off, and it is
# named. Anything else off is a silent weakening of the advertised oracle.
DEFERRED_FLAG = "disallow_any_generics"

# The flags ``strict`` turns ON (mypy >= 1.11). Used ONLY to classify a config
# key as "weakening when False" --- the proof that the strict flags are really
# active is behavior 5, which fires the checker on bad input.
STRICT_COMPONENTS = frozenset(
    {
        "check_untyped_defs",
        "disallow_any_generics",
        "disallow_incomplete_defs",
        "disallow_subclassing_any",
        "disallow_untyped_calls",
        "disallow_untyped_decorators",
        "disallow_untyped_defs",
        "extra_checks",
        "no_implicit_reexport",
        "strict_bytes",
        "strict_equality",
        "warn_redundant_casts",
        "warn_return_any",
        "warn_unused_configs",
        "warn_unused_ignores",
    }
)

# Keys whose TRUE value weakens the oracle no matter what ``strict`` says.
WEAKENING_IF_TRUE = frozenset(
    {
        "allow_redefinition",
        "allow_untyped_globals",
        "ignore_errors",
        "ignore_missing_imports",
        "implicit_optional",
        "implicit_reexport",
    }
)

# Keys that are neutral or strengthening, so their presence is fine. Any key in
# ``[tool.mypy]`` outside these three sets fails the classification guard on
# purpose: an unclassified knob is an unreviewed knob.
NEUTRAL_OR_STRENGTHENING = frozenset(
    {
        "cache_dir",
        "disallow_any_decorated",
        "disallow_any_explicit",
        "disallow_any_expr",
        "disallow_any_unimported",
        "enable_error_code",
        "exclude",
        "explicit_package_bases",
        "files",
        "incremental",
        "local_partial_types",
        "mypy_path",
        "namespace_packages",
        "no_implicit_optional",
        "packages",
        "plugins",
        "pretty",
        "python_version",
        "show_column_numbers",
        "show_error_codes",
        "strict",
        "warn_no_return",
        "warn_unreachable",
    }
)

# Spec behavior 4: the stub allowance that becomes load-bearing under strict.
STUB_ALLOWANCE_MODULE_PREFIX = "botocore"

# Spec behavior 5: the error code a missing parameter annotation must produce.
UNTYPED_DEF_CODE = "no-untyped-def"
# The code behind the ``loop/tools.py`` fix --- proving it fires proves
# ``warn_return_any`` is really on, which is what that fix was for.
ANY_RETURN_CODE = "no-any-return"

# Spec behavior 7: the unknown-tool observation contract, unchanged by the
# typing fix on the dispatch line.
UNKNOWN_TOOL_PREFIX = "error: unknown tool"
AVAILABLE_TOOLS_MARKER = "available tools:"

# Spec behavior 8: the roadmap row that owes the deferred cleanup.
DEFERRAL_ROW_NUMBER = "121"


# --------------------------------------------------------------------------
# Independent derivations (spec definitions, not the shipped implementation)
# --------------------------------------------------------------------------


def mypy_table() -> dict[str, object]:
    """The ``[tool.mypy]`` table as SHIPPED, or fail loudly.

    Never returns ``{}``: an empty table would make every config guard below
    pass over zero keys, which is indistinguishable from a deleted oracle.
    """
    with PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    table = data.get("tool", {}).get("mypy")
    assert isinstance(table, dict) and table, (
        "pyproject.toml must ship a non-empty [tool.mypy] table; without it the "
        "'fully type-hinted' claim has no machine oracle at all"
    )
    return table


def mypy_overrides() -> list[dict[str, object]]:
    """The ``[[tool.mypy.overrides]]`` entries as shipped, or fail loudly."""
    table = mypy_table()
    overrides = table.get("overrides")
    assert isinstance(overrides, list) and overrides, (
        "pyproject.toml must ship at least one [[tool.mypy.overrides]] entry "
        f"(the {STUB_ALLOWANCE_MODULE_PREFIX} stub allowance); got {overrides!r}"
    )
    for entry in overrides:
        assert isinstance(entry, dict), f"override entry must be a table: {entry!r}"
    return overrides


def override_modules(entry: dict[str, object]) -> list[str]:
    """The ``module`` patterns of one override entry (str or list form)."""
    raw = entry.get("module")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    return []


def package_sources() -> list[Path]:
    """Every ``.py`` file in the shipped package, or fail loudly."""
    files = sorted(PKG.rglob("*.py"))
    assert len(files) >= 20, (
        f"expected the shipped package to hold at least 20 modules, found "
        f"{len(files)} under {PKG}; the ast sweep would be near-vacuous"
    )
    return files


def annotation_defects(path: Path) -> list[str]:
    """``file:line function`` for every unannotated param / missing return.

    ``self`` / ``cls`` are exempt ONLY as the first positional parameter, so a
    stray later parameter literally named ``self`` is still reported.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defects: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        try:
            label = str(path.relative_to(REPO))
        except ValueError:  # a synthetic probe module under tmp_path
            label = path.name
        where = f"{label}:{node.lineno} {node.name}"
        if node.returns is None:
            defects.append(f"{where} -- missing return annotation")
        spec = node.args
        positional = list(spec.posonlyargs) + list(spec.args)
        params = positional + list(spec.kwonlyargs)
        if spec.vararg is not None:
            params.append(spec.vararg)
        if spec.kwarg is not None:
            params.append(spec.kwarg)
        implicit = (
            positional[0].arg
            if positional and positional[0].arg in {"self", "cls"}
            else None
        )
        for index, arg in enumerate(params):
            if arg.annotation is not None:
                continue
            if index == 0 and implicit is not None:
                continue
            defects.append(f"{where} -- parameter {arg.arg!r} has no annotation")
    return defects


def run_mypy(target: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    """Run the project's LOCKED mypy over ``target`` under the SHIPPED config.

    Uses ``sys.executable -m mypy`` so the checker is the pinned dev-dependency
    from this very interpreter's environment (offline, reproducible), and a
    throwaway cache dir so the probe cannot be answered from stale state.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(PYPROJECT),
            "--cache-dir",
            str(cache),
            str(target),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )


def probe(tmp_path: Path, name: str, body: str) -> subprocess.CompletedProcess[str]:
    """Write ``body`` as a module under ``tmp_path`` and type-check it."""
    module = tmp_path / f"{name}.py"
    module.write_text(body, encoding="utf-8")
    result = run_mypy(module, tmp_path / f"cache-{name}")
    assert "Traceback (most recent call last)" not in result.stderr, (
        f"mypy itself crashed on probe {name!r}; the gate proof is void.\n"
        f"stderr={result.stderr!r}"
    )
    return result


def roadmap_lines() -> list[str]:
    """Every line of ``ROADMAP.md``, or fail loudly."""
    text = ROADMAP.read_text(encoding="utf-8")
    assert text.strip(), f"{ROADMAP.name} must not be empty"
    return text.splitlines()


def tools(tmp_path: Path) -> ToolRegistry:
    """A sandboxed registry rooted entirely inside ``tmp_path``."""
    return ToolRegistry(
        workspace_root=tmp_path / "workspace",
        artifacts_dir=tmp_path / "artifacts",
    )


# ==========================================================================
# Behavior 2 --- the ratchet is CONFIGURED: tool.mypy.strict is true.
# ==========================================================================


def test_b2_strict_is_enabled_in_shipped_config() -> None:
    table = mypy_table()

    assert table.get("strict") is True, (
        "pyproject.toml [tool.mypy] must set strict = true --- default-mode mypy "
        "does not check unannotated functions at all, so the 'fully type-hinted' "
        f"README claim would be unguarded. Got strict={table.get('strict')!r}"
    )


def test_b2_python_version_is_pinned() -> None:
    """The oracle must grade against the declared floor, not the local venv."""
    table = mypy_table()

    assert table.get("python_version") == "3.12", (
        "the oracle must pin python_version to the project's declared floor "
        f"(3.12) so CI and a local run agree; got {table.get('python_version')!r}"
    )


# ==========================================================================
# Behavior 3 --- EXACTLY one flag is deferred, and it is named.
# ==========================================================================


def test_b3_exactly_one_strict_component_is_deferred() -> None:
    table = mypy_table()

    deferred = {
        key
        for key, value in table.items()
        if key in STRICT_COMPONENTS and value is False
    }

    assert deferred == {DEFERRED_FLAG}, (
        f"exactly one strict component may be deferred, and it must be "
        f"{DEFERRED_FLAG!r} (it owns 35 of the 38 strict errors, queued as "
        f"roadmap row #{DEFERRAL_ROW_NUMBER}); got {sorted(deferred)}"
    )


def test_b3_deferred_flag_is_explicitly_false_not_merely_absent() -> None:
    """An ABSENT flag under ``strict`` is ON; the deferral must be deliberate."""
    table = mypy_table()

    assert table.get(DEFERRED_FLAG) is False, (
        f"{DEFERRED_FLAG} must be spelled out as false so the deferral is a "
        f"reviewed decision rather than an oversight; got "
        f"{table.get(DEFERRED_FLAG)!r}"
    )


def test_b3_no_other_key_weakens_strict() -> None:
    table = mypy_table()

    weakened = sorted(key for key in WEAKENING_IF_TRUE if table.get(key) is True)

    assert weakened == [], (
        "no [tool.mypy] key may re-open what strict closed; these are true: "
        f"{weakened}. Scope a stub allowance to an [[overrides]] block instead "
        "of weakening the global table"
    )


def test_b3_no_error_codes_are_globally_disabled() -> None:
    table = mypy_table()

    assert not table.get("disable_error_code"), (
        "the oracle must not silence error codes globally; got "
        f"disable_error_code={table.get('disable_error_code')!r}"
    )
    assert table.get("follow_imports", "normal") not in {"skip", "silent"}, (
        "follow_imports must not be skip/silent --- that would hide whole "
        f"modules from the oracle; got {table.get('follow_imports')!r}"
    )


def test_b3_every_config_key_is_classified() -> None:
    """An unclassified knob is an unreviewed knob."""
    table = mypy_table()
    known = STRICT_COMPONENTS | WEAKENING_IF_TRUE | NEUTRAL_OR_STRENGTHENING

    unclassified = sorted(
        key for key in table if key != "overrides" and key not in known
    )

    assert unclassified == [], (
        f"[tool.mypy] holds keys this guard has never classified: "
        f"{unclassified}. Add each to STRICT_COMPONENTS, WEAKENING_IF_TRUE or "
        "NEUTRAL_OR_STRENGTHENING in this test so the next reader knows whether "
        "it strengthens or weakens the shipped oracle"
    )


# ==========================================================================
# Behavior 4 --- the existing stub allowance survives the rewrite.
# ==========================================================================


def test_b4_botocore_stub_allowance_is_preserved() -> None:
    matching = [
        entry
        for entry in mypy_overrides()
        if any(
            pattern.startswith(STUB_ALLOWANCE_MODULE_PREFIX)
            for pattern in override_modules(entry)
        )
    ]

    assert matching, (
        f"the {STUB_ALLOWANCE_MODULE_PREFIX}.* override MUST survive: under "
        "strict, dropping it adds an import-not-found error on the optional "
        "bedrock provider's transport SDK, which ships no stubs"
    )
    for entry in matching:
        assert entry.get("ignore_missing_imports") is True, (
            f"the {STUB_ALLOWANCE_MODULE_PREFIX} override exists but no longer "
            f"grants ignore_missing_imports; got {entry!r}"
        )


def test_b4_stub_allowance_is_scoped_never_global() -> None:
    """The allowance must stay narrow: no blanket global missing-stub bypass."""
    table = mypy_table()

    assert table.get("ignore_missing_imports") is not True, (
        "ignore_missing_imports must be scoped to the stubless transport SDK in "
        "an [[overrides]] block, never set globally --- a global bypass silently "
        "disables stub enforcement for the whole tree"
    )
    for entry in mypy_overrides():
        patterns = override_modules(entry)
        assert patterns, f"every override entry must name a module: {entry!r}"
        assert "*" not in patterns, (
            f"an override may not target every module: {entry!r}"
        )


# ==========================================================================
# Behavior 5 --- the guard FIRES (and does not over-fire).
# ==========================================================================


def test_b5_unannotated_parameter_is_rejected(tmp_path: Path) -> None:
    """The whole point of the ratchet: this shape used to pass as 'Success'."""
    result = probe(
        tmp_path,
        "unannotated_param",
        "def hand_off(client) -> int:\n    return 0\n",
    )

    assert result.returncode != 0, (
        "the shipped config must REJECT a function with an unannotated "
        f"parameter; mypy exited 0.\nstdout={result.stdout!r}"
    )
    assert UNTYPED_DEF_CODE in result.stdout, (
        f"the rejection must name the {UNTYPED_DEF_CODE} error code so the "
        f"failure is actionable; got stdout={result.stdout!r}"
    )


def test_b5_missing_return_annotation_is_rejected(tmp_path: Path) -> None:
    result = probe(
        tmp_path,
        "missing_return",
        "def total(value: int):\n    return value\n",
    )

    assert result.returncode != 0, (
        "the shipped config must REJECT a function with no return annotation; "
        f"mypy exited 0.\nstdout={result.stdout!r}"
    )
    assert UNTYPED_DEF_CODE in result.stdout, (
        f"expected {UNTYPED_DEF_CODE} in stdout; got {result.stdout!r}"
    )


def test_b5_returning_any_from_a_typed_function_is_rejected(tmp_path: Path) -> None:
    """``warn_return_any`` is the flag behind the tools.py dispatch fix."""
    result = probe(
        tmp_path,
        "any_return",
        "from typing import Any\n\n\ndef label(raw: Any) -> str:\n    return raw\n",
    )

    assert result.returncode != 0, (
        "the shipped config must REJECT leaking Any out of a -> str function "
        f"(that is exactly the fixed tools.py dispatch shape); stdout="
        f"{result.stdout!r}"
    )
    assert ANY_RETURN_CODE in result.stdout, (
        f"expected {ANY_RETURN_CODE} in stdout; got {result.stdout!r}"
    )


def test_b5_bare_generic_is_still_accepted_the_deferral_is_real(
    tmp_path: Path,
) -> None:
    """The negative half: prove the DEFERRED flag is genuinely deferred.

    Without this, ``disallow_any_generics = false`` could be a no-op typo and
    every other assertion in this module would still pass.
    """
    result = probe(
        tmp_path,
        "bare_generic",
        "def size(mapping: dict) -> int:\n    return len(mapping)\n",
    )

    assert result.returncode == 0, (
        f"{DEFERRED_FLAG} is documented as DEFERRED, so a bare `dict` "
        "annotation must still pass. If this now fails the flag was enabled "
        "without clearing roadmap row #"
        f"{DEFERRAL_ROW_NUMBER}.\nstdout={result.stdout!r}"
    )


def test_b5_clean_module_passes_the_gate_does_not_over_fire(
    tmp_path: Path,
) -> None:
    result = probe(
        tmp_path,
        "clean",
        "def add(left: int, right: int) -> int:\n    return left + right\n",
    )

    assert result.returncode == 0, (
        "a fully annotated module must pass the shipped config; a gate that "
        f"rejects good code is unshippable.\nstdout={result.stdout!r}"
    )
    assert "Success" in result.stdout, (
        f"expected a Success summary; got {result.stdout!r}"
    )


# ==========================================================================
# Behavior 6 --- no unannotated parameter and no missing return annotation
# survives in the shipped package (ast sweep, independent of mypy).
# ==========================================================================


def test_b6_shipped_package_has_no_annotation_defects() -> None:
    defects: list[str] = []
    for path in package_sources():
        defects.extend(annotation_defects(path))

    assert defects == [], (
        "the README promises the package is fully type-hinted, so every "
        "function in it must annotate every parameter and its return type. "
        "This sweep is deliberately stricter than mypy (which excuses a "
        "missing `-> None` on __init__). Offenders:\n" + "\n".join(defects)
    )


def test_b6_sweep_covers_the_whole_package() -> None:
    """A sweep that walked zero functions would pass vacuously."""
    counted = 0
    for path in package_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        counted += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )

    assert counted >= 200, (
        f"expected the sweep to inspect at least 200 functions, saw {counted}; "
        "a near-empty walk makes behavior 6 vacuous"
    )


# ==========================================================================
# Behavior 7 --- the ACT sandbox boundary is behaviorally unchanged.
# ==========================================================================


def test_b7_unknown_tool_still_returns_the_same_observation(
    tmp_path: Path,
) -> None:
    registry = tools(tmp_path)

    observation = registry.execute("format_hard_drive", {})

    assert isinstance(observation, str), (
        f"the dispatch must return a str observation, never raise or return "
        f"None; got {observation!r}"
    )
    assert observation.startswith(UNKNOWN_TOOL_PREFIX), (
        f"an unknown tool must still yield {UNKNOWN_TOOL_PREFIX!r}; got "
        f"{observation!r}"
    )
    assert AVAILABLE_TOOLS_MARKER in observation, (
        f"the refusal must still list the allowlist ({AVAILABLE_TOOLS_MARKER!r} "
        f"marker) so the model can self-correct; got {observation!r}"
    )
    assert registry.artifacts() == [], (
        f"a refused tool must leave no artifact; got {registry.artifacts()!r}"
    )


def test_b7_refusal_lists_every_allowed_tool(tmp_path: Path) -> None:
    registry = tools(tmp_path)

    observation = registry.execute("definitely_not_a_tool", {})

    missing = sorted(name for name in _TOOL_CATALOG if name not in observation)
    assert missing == [], (
        f"the unknown-tool refusal must name every allowed tool; missing "
        f"{missing} from {observation!r}"
    )


def test_b7_every_allowed_tool_still_returns_a_str(tmp_path: Path) -> None:
    """The typing fix annotated the dispatch result as returning ``str``.

    That annotation is only TRUE because every handler behind the allowlist
    returns a ``str``; mypy cannot prove it through ``getattr``, so this is the
    check that keeps the annotation from becoming a lie.
    """
    registry = tools(tmp_path)

    for name in sorted(_TOOL_CATALOG):
        observation = registry.execute(name, {})
        assert isinstance(observation, str), (
            f"tool {name!r} returned {type(observation).__name__}, not str; the "
            "dispatch annotation Callable[..., str] would be a lie"
        )
        assert not observation.startswith(UNKNOWN_TOOL_PREFIX), (
            f"tool {name!r} is in the catalog but the registry refused it as "
            f"unknown: {observation!r}"
        )


def test_b7_allowlist_size_is_unchanged(tmp_path: Path) -> None:
    """A typing-only edit may not add or drop a sandbox capability."""
    assert len(_TOOL_CATALOG) == 14, (
        f"the ACT sandbox allowlist must still hold exactly 14 tools; got "
        f"{len(_TOOL_CATALOG)}: {sorted(_TOOL_CATALOG)}"
    )


# ==========================================================================
# Behavior 8 --- the deferral is RECORDED, not silent.
# ==========================================================================


def test_b8_roadmap_row_owns_the_deferred_flag() -> None:
    rows = [
        line
        for line in roadmap_lines()
        if line.lstrip().startswith(f"| {DEFERRAL_ROW_NUMBER} |")
    ]

    assert len(rows) == 1, (
        f"ROADMAP.md must hold exactly one row #{DEFERRAL_ROW_NUMBER} (the "
        f"queued {DEFERRED_FLAG} cleanup); found {len(rows)}"
    )
    row = rows[0]
    assert DEFERRED_FLAG in row, (
        f"row #{DEFERRAL_ROW_NUMBER} must NAME the deferred flag so the debt is "
        f"searchable; got {row!r}"
    )
    assert "type-arg" in row, (
        f"row #{DEFERRAL_ROW_NUMBER} must name the deferred error code "
        f"(type-arg) so the remaining work is identifiable; got {row!r}"
    )


def test_b8_roadmap_table_has_no_internal_blank_line() -> None:
    """A blank line inside a GFM table demotes every row below it to plain text.

    A "recorded" row that GitHub renders as literal ``| 121 | ...`` text on a
    public portfolio repo is not recorded --- and this failure is invisible in a
    diff (the added line is just an empty one) and invisible to every other
    test in the suite.
    """
    lines = roadmap_lines()
    breaks: list[int] = []
    for index, line in enumerate(lines):
        if line.strip():
            continue
        previous = next(
            (lines[j] for j in range(index - 1, -1, -1) if lines[j].strip()), ""
        )
        following = next(
            (lines[j] for j in range(index + 1, len(lines)) if lines[j].strip()), ""
        )
        if previous.lstrip().startswith("|") and following.lstrip().startswith("|"):
            breaks.append(index + 1)

    assert breaks == [], (
        "ROADMAP.md has a blank line INSIDE a Markdown table at line(s) "
        f"{breaks}; under GFM the table ends there and every row below renders "
        "as literal pipe-delimited text"
    )


# ==========================================================================
# Fail-closed guards --- each reader above is fired on a known-bad sample, so
# a silently-broken reader cannot masquerade as a passing behavior.
# ==========================================================================


def test_guard_annotation_sweep_fires_on_a_known_bad_module(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "bad_module.py"
    bad.write_text(
        "class Holder:\n"
        "    def __init__(self, entries: list[int]):\n"
        "        self.entries = entries\n"
        "\n"
        "\n"
        "def hand_off(client) -> int:\n"
        "    return 0\n",
        encoding="utf-8",
    )

    defects = annotation_defects(bad)

    joined = "\n".join(defects)
    assert len(defects) == 2, f"expected 2 defects, got {defects}"
    assert "missing return annotation" in joined, joined
    assert "'client' has no annotation" in joined, joined
    # `self` must NOT be reported, and an annotated param must not be either.
    assert "'self'" not in joined, joined
    assert "'entries'" not in joined, joined


def test_guard_annotation_sweep_is_silent_on_a_clean_module(
    tmp_path: Path,
) -> None:
    clean = tmp_path / "clean_module.py"
    clean.write_text(
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "class Holder:\n"
        "    def __init__(self, entries: list[int]) -> None:\n"
        "        self.entries = entries\n"
        "\n"
        "    @classmethod\n"
        "    def empty(cls) -> Holder:\n"
        "        return cls([])\n"
        "\n"
        "\n"
        "async def gather(*args: int, **kwargs: str) -> None:\n"
        "    return None\n"
        "\n"
        "\n"
        "def outer(value: int) -> int:\n"
        "    def inner(inner_value: int) -> int:\n"
        "        return inner_value\n"
        "\n"
        "    doubler = lambda item: item * 2  # noqa: E731\n"
        "    return inner(value) + int(doubler(1))\n",
        encoding="utf-8",
    )

    assert annotation_defects(clean) == [], annotation_defects(clean)


def test_guard_table_break_detector_fires_on_a_known_bad_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "ROADMAP.md"
    broken.write_text(
        "# Roadmap\n"
        "\n"
        "| # | title |\n"
        "| --- | --- |\n"
        "| 120 | a |\n"
        "\n"
        "| 121 | b |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys.modules[__name__], "ROADMAP", broken)

    with pytest.raises(AssertionError) as excinfo:
        test_b8_roadmap_table_has_no_internal_blank_line()

    assert "[6]" in str(excinfo.value), str(excinfo.value)


def test_guard_config_reader_fires_when_the_table_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "pyproject.toml"
    empty.write_text('[project]\nname = "x"\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "PYPROJECT", empty)

    with pytest.raises(AssertionError, match="non-empty"):
        mypy_table()


def test_guard_mypy_probe_actually_invokes_the_checker(tmp_path: Path) -> None:
    """If the subprocess never ran, every behavior-5 assertion is theatre."""
    result = probe(tmp_path, "liveness", "x: int = 1\n")

    assert result.returncode == 0, result.stdout
    assert "1 source file" in result.stdout, (
        "mypy must report a ONE-source-file verdict for the probe module --- "
        "otherwise the "
        f"gate proofs above never touched the checker; stdout={result.stdout!r}"
    )
