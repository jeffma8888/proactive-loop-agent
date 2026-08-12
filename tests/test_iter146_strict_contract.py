"""Behavior tests for state-dir iteration 139 (ships as ``factory iter 146``).

Feature under test: ``[tool.mypy]``'s last deliberately deferred strict
component --- ``disallow_any_generics`` --- is DELETED from the shipped config so
``strict = true`` stands unqualified, the 35 bare-generic annotations that flag
was suppressing are parameterized (value types left as ``Any``), and the
newly-armed ratchet is proven to FIRE rather than merely to be satisfied.

Why this module exists next to ``test_iter146_behavior.py``
This is the TESTER's independent, black-box encoding of the spec's eight
Expected Behaviors, written from the spec alone. It deliberately overlaps the
config/probe assertions (an oracle worth having is worth having twice, from two
readers) and adds the four checks the spec asks for that a tmp_path probe cannot
make: that the SHIPPED package is clean under BOTH invocations (behavior 1),
that the ratchet's arming is ATTRIBUTABLE to the deleted key rather than to a
coincidentally clean tree (behavior 7), that re-weakening the config turns the
inverted deferral guards RED (behavior 4), and that nothing was paid for with a
suppression or a runtime regression (behaviors 5 and 6).

Isolation: black-box. The seams used are (a) parsing ``pyproject.toml`` with
``tomllib`` --- which behaviors 2-3 REQUIRE as the config oracle, (b) running the
project's LOCKED mypy as a subprocess, over the shipped package (read-only) and
over modules this file writes into ``tmp_path``, (c) running the CLI's
module entry point (``python -m proactive_loop.cli``) as a subprocess and parsing its
JSON, (d) counting
suppression comments in ``src/`` as TEXT, never reading logic, and (e) running a
COPY of the iter-115 guard module against a MUTATED config inside ``tmp_path``.
No implementation source was read while writing this file; no engineer, reviewer
or fix note was opened; ``git diff`` was not run.

Offline: file reads, subprocesses against this project's own pinned checker and
its own CLI entry point, and writes confined to ``tmp_path``. No network, no API
keys, no writes anywhere the repo tracks.

Every reader here is fail-CLOSED. A config reader that silently returns ``{}``,
a mypy probe that "passes" because the checker never ran, and a sandbox pytest
run that "fails" because it collected zero tests would each make a guard pass
vacuously --- which is worse than no guard --- so each is pinned by a
``test_guard_*`` case or an in-test collection assertion.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TextIO

import pytest

# --------------------------------------------------------------------------
# Ground facts --- transcribed from the spec (pm.md), NOT imported from the
# implementation, so a silent drift in either direction is caught.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
SRC = REPO / "src" / "proactive_loop"
GUARD_MODULE = REPO / "tests" / "test_iter115_behavior.py"

CLOSED_FLAG = "disallow_any_generics"
TYPE_ARG_CODE = "type-arg"
STUB_ALLOWANCE_MODULE = "botocore.*"
EXPECTED_VERSION_LINE = "pla 0.1.1"

# Spec's "Do not touch" note: the suppression count under src/ is 3 today
# (config.py 2, models.py 1) and behavior 5 says it must not increase.
TYPE_IGNORE_BASELINE = 3

# Behavior 6's regression oracle: these verbs must still emit a JSON object.
JSON_VERBS = ("config", "collectors", "providers", "tools")

BARE_GENERIC_MODULE = """
from __future__ import annotations

from typing import Any


def payload(d: dict) -> Any:
    return d.get("k")
"""

PARAMETERIZED_MODULE = """
from __future__ import annotations

from typing import Any


def payload(d: dict[str, Any]) -> Any:
    return d.get("k")
"""


def mypy_table() -> dict[str, object]:
    """Read the shipped ``[tool.mypy]`` table, fail-CLOSED."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    tool = data.get("tool")
    assert isinstance(tool, dict), f"no [tool] table in {PYPROJECT}"
    table = tool.get("mypy")
    assert isinstance(table, dict) and table, (
        "[tool.mypy] must exist and be non-empty --- an empty read would make "
        f"every assertion below pass vacuously; got {table!r}"
    )
    return table


def mypy_overrides() -> list[dict[str, object]]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    tool = data.get("tool", {})
    assert isinstance(tool, dict)
    table = tool.get("mypy", {})
    assert isinstance(table, dict)
    overrides = table.get("overrides", [])
    assert isinstance(overrides, list)
    return [entry for entry in overrides if isinstance(entry, dict)]


def run_mypy(
    target: str, cache: Path, *, config: Path = PYPROJECT, strict: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run the project's LOCKED mypy over ``target`` under ``config``.

    ``sys.executable -m mypy`` pins the checker to this interpreter's
    environment (the locked dev dependency), and a throwaway cache dir stops the
    probe from being answered out of stale state.
    """
    argv = [sys.executable, "-m", "mypy", "--config-file", str(config)]
    if strict:
        argv.append("--strict")
    argv += ["--cache-dir", str(cache), target]
    result = subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO))
    assert "Traceback (most recent call last)" not in result.stderr, (
        f"mypy itself crashed on {target!r}; the proof is void.\n"
        f"stderr={result.stderr!r}"
    )
    return result


def probe(
    tmp_path: Path, name: str, body: str, *, config: Path = PYPROJECT
) -> subprocess.CompletedProcess[str]:
    module = tmp_path / f"{name}.py"
    module.write_text(body, encoding="utf-8")
    return run_mypy(str(module), tmp_path / f"cache-{name}", config=config)


def reweakened_config(tmp_path: Path) -> Path:
    """Copy the shipped config and re-add ``disallow_any_generics = false``.

    Inserted after the single line that is exactly ``strict = true`` --- the
    token also appears inside the comment prose, so a naive first-occurrence
    replace would edit a comment and silently prove nothing.
    """
    lines = PYPROJECT.read_text(encoding="utf-8").splitlines()
    hits = [i for i, line in enumerate(lines) if line.strip() == "strict = true"]
    assert len(hits) == 1, (
        f"expected exactly one bare 'strict = true' line, found {len(hits)}"
    )
    lines.insert(hits[0] + 1, f"{CLOSED_FLAG} = false")
    path = tmp_path / "reweakened-pyproject.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mutated = tomllib.loads(path.read_text(encoding="utf-8"))
    assert mutated["tool"]["mypy"][CLOSED_FLAG] is False, (
        "self-check: the mutated config must actually carry the weakened flag"
    )
    return path


def src_files() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    assert len(files) >= 20, (
        f"only found {len(files)} modules under {SRC} --- a near-empty sweep "
        "would make the suppression count pass vacuously"
    )
    return files


def run_pla(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "proactive_loop.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )


# --------------------------------------------------------------------------
# Behavior 2 --- the key is DELETED, nowhere set
# --------------------------------------------------------------------------


def test_b2_the_closed_flag_is_absent_from_the_mypy_table() -> None:
    table = mypy_table()
    assert CLOSED_FLAG not in table, (
        f"[tool.mypy] must carry no {CLOSED_FLAG} key at all --- 'strict = true' "
        f"supplies it; got {table.get(CLOSED_FLAG)!r}"
    )


def test_b2_strict_still_stands_and_is_true() -> None:
    table = mypy_table()
    assert table.get("strict") is True, (
        f"deleting {CLOSED_FLAG} is only a ratchet if strict itself stays on; "
        f"got strict={table.get('strict')!r}"
    )


def test_b2_no_overrides_block_sets_the_closed_flag() -> None:
    for entry in mypy_overrides():
        assert CLOSED_FLAG not in entry, (
            "a per-module override may not re-open the closed deferral; got "
            f"{entry!r}"
        )


def test_b2_the_closed_flag_is_absent_from_the_file_text_as_a_setting() -> None:
    """Belt-and-braces over the raw text: no assignment to the flag anywhere.

    ``tomllib`` sees only the last winning table; a stray assignment in a table
    this reader does not visit would be invisible to it.
    """
    pattern = re.compile(rf"^\s*{re.escape(CLOSED_FLAG)}\s*=", re.MULTILINE)
    hits = pattern.findall(PYPROJECT.read_text(encoding="utf-8"))
    assert hits == [], (
        f"found {len(hits)} assignment(s) to {CLOSED_FLAG} in pyproject.toml; "
        "behavior 2 requires the key to be deleted, not re-set"
    )


# --------------------------------------------------------------------------
# Behavior 3 --- nothing else was switched off to pay for it
# --------------------------------------------------------------------------


def test_b3_the_only_override_is_the_botocore_stub_allowance() -> None:
    overrides = mypy_overrides()
    assert len(overrides) == 1, (
        "behavior 3 allows exactly one [[tool.mypy.overrides]] block (the "
        f"botocore stub allowance); got {len(overrides)}: {overrides!r}"
    )
    entry = overrides[0]
    assert entry.get("module") == STUB_ALLOWANCE_MODULE, (
        f"the sole override must stay scoped to {STUB_ALLOWANCE_MODULE}; got "
        f"{entry.get('module')!r}"
    )
    assert entry.get("ignore_missing_imports") is True, (
        f"the sole override must still grant only the stub allowance; got {entry!r}"
    )
    assert set(entry) == {"module", "ignore_missing_imports"}, (
        "the stub-allowance override must not grow a strictness exemption; got "
        f"keys {sorted(entry)}"
    )


def test_b3_no_key_in_the_mypy_table_is_switched_off() -> None:
    table = mypy_table()
    switched_off = sorted(k for k, v in table.items() if v is False)
    assert switched_off == [], (
        "no strict component may be switched off anywhere in [tool.mypy] --- "
        f"found {switched_off}"
    )


def test_b3_no_error_codes_are_disabled_and_imports_are_followed() -> None:
    table = mypy_table()
    assert not table.get("disable_error_code"), (
        "disabling an error code globally would re-open the gap by another "
        f"route; got {table.get('disable_error_code')!r}"
    )
    assert table.get("follow_imports", "normal") not in {"skip", "silent"}, (
        "follow_imports must not hide whole modules from the oracle; got "
        f"{table.get('follow_imports')!r}"
    )
    assert not table.get("ignore_errors", False), (
        f"ignore_errors must stay off; got {table.get('ignore_errors')!r}"
    )


# --------------------------------------------------------------------------
# Behavior 1 --- the SHIPPED package is clean under both invocations
# --------------------------------------------------------------------------


def test_b1_config_driven_mypy_is_clean_over_the_shipped_package(
    tmp_path: Path,
) -> None:
    result = run_mypy("src/proactive_loop", tmp_path / "cache-config")
    assert result.returncode == 0, (
        "make typecheck must exit 0 under the unqualified strict config.\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "no issues found" in result.stdout, (
        f"expected a clean report; got stdout={result.stdout!r}"
    )
    assert TYPE_ARG_CODE not in result.stdout, (
        f"no {TYPE_ARG_CODE} error may remain; got stdout={result.stdout!r}"
    )


def test_b1_explicit_strict_agrees_with_the_config_driven_run(
    tmp_path: Path,
) -> None:
    """Behavior 1: the two invocations now AGREE, which is the whole point."""
    result = run_mypy("src/proactive_loop", tmp_path / "cache-strict", strict=True)
    assert result.returncode == 0, (
        "mypy --strict must now agree with the config-driven run (0 errors); "
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "no issues found" in result.stdout, (
        f"expected a clean --strict report; got stdout={result.stdout!r}"
    )


# --------------------------------------------------------------------------
# Behavior 7 --- the ratchet is provably ARMED, and attributable
# --------------------------------------------------------------------------


def test_b7_a_bare_generic_annotation_is_rejected_naming_type_arg(
    tmp_path: Path,
) -> None:
    result = probe(tmp_path, "bare", BARE_GENERIC_MODULE)
    assert result.returncode != 0, (
        "a bare 'dict' annotation must now be REJECTED by the shipped config; "
        f"mypy exited 0, so the ratchet is not armed. stdout={result.stdout!r}"
    )
    assert TYPE_ARG_CODE in result.stdout, (
        f"the rejection must name the {TYPE_ARG_CODE} code so the failure is "
        f"actionable; got stdout={result.stdout!r}"
    )


def test_b7_the_parameterized_form_is_accepted_gate_does_not_over_fire(
    tmp_path: Path,
) -> None:
    result = probe(tmp_path, "parameterized", PARAMETERIZED_MODULE)
    assert result.returncode == 0, (
        "dict[str, Any] --- the form the 35 sites were rewritten to --- must "
        f"PASS; got stdout={result.stdout!r}"
    )


def test_b7_the_deleted_key_is_what_arms_the_gate(tmp_path: Path) -> None:
    """Attribution: the SAME bad module passes once the flag is re-weakened.

    Without this, a green tree and a rejecting probe are consistent with the
    gate being armed by something else entirely.
    """
    weakened = reweakened_config(tmp_path)
    result = probe(tmp_path, "bare_weakened", BARE_GENERIC_MODULE, config=weakened)
    assert result.returncode == 0, (
        f"re-adding {CLOSED_FLAG} = false must make the bare generic acceptable "
        "again --- if it does not, this probe is not measuring that flag. "
        f"stdout={result.stdout!r}"
    )


# --------------------------------------------------------------------------
# Behavior 4 --- the iter-115 deferral guards were INVERTED, not deleted,
# and they are still fail-closed against a re-weakening commit.
# --------------------------------------------------------------------------


def deferral_guard_names() -> list[str]:
    """Discover the inverted behavior-3 deferral guards by AST, fail-CLOSED."""
    tree = ast.parse(GUARD_MODULE.read_text(encoding="utf-8"))
    names = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("test_b3")
        and "defer" in node.name
    ]
    assert len(names) >= 2, (
        "behavior 4 requires the two deferral guards in "
        f"{GUARD_MODULE.name} to be INVERTED, not deleted; found {names}"
    )
    return names


def test_b4_the_inverted_deferral_guards_still_exist() -> None:
    names = deferral_guard_names()
    assert any("no_strict_component" in n or "no_" in n for n in names), (
        f"expected an inverted 'nothing is deferred' guard among {names}"
    )


def test_b4_reweakening_the_config_turns_the_deferral_guards_red(
    tmp_path: Path,
) -> None:
    """The fail-closed proof, run in a sandbox so the real repo is untouched.

    A copy of the guard module plus a copy of ``pyproject.toml`` carrying
    ``disallow_any_generics = false`` is assembled under ``tmp_path``; the guards
    resolve their repo root from their own location, so the copy reads the
    MUTATED config. They must go RED.
    """
    sandbox = tmp_path / "sandbox"
    (sandbox / "tests").mkdir(parents=True)
    weakened = reweakened_config(tmp_path)
    (sandbox / "pyproject.toml").write_text(
        weakened.read_text(encoding="utf-8"), encoding="utf-8"
    )
    shutil.copy2(REPO / "tests" / "__init__.py", sandbox / "tests" / "__init__.py")
    shutil.copy2(GUARD_MODULE, sandbox / "tests" / GUARD_MODULE.name)

    selection = " or ".join(deferral_guard_names())
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(sandbox / "tests" / GUARD_MODULE.name),
            "-k",
            selection,
            "-p",
            "no:cacheprovider",
            "-n0",
        ],
        capture_output=True,
        text=True,
        cwd=str(sandbox),
    )
    combined = result.stdout + result.stderr
    assert "no tests ran" not in combined, (
        "the sandbox run collected nothing, so a non-zero exit proves nothing.\n"
        f"selection={selection!r}\n{combined}"
    )
    # Count the short-summary FAILED lines rather than pytest's trailing
    # "N failed" tally: the sandbox inherits `-q` from the copied config's
    # addopts, and a second `-q` suppresses that tally line entirely.
    reported = re.findall(r"^FAILED .*::(\S+)", combined, re.MULTILINE)
    assert len(reported) >= 2, (
        "re-adding the weakened flag must turn BOTH inverted deferral guards "
        f"red; sandbox pytest reported {reported}:\n{combined}"
    )
    assert set(reported) >= set(deferral_guard_names()), (
        f"expected every deferral guard to go red; red={reported}, "
        f"selected={deferral_guard_names()}"
    )
    assert result.returncode != 0, (
        f"sandbox pytest must exit non-zero; got {result.returncode}\n{combined}"
    )


# --------------------------------------------------------------------------
# Behavior 5 --- fixed by annotation, never by suppression
# --------------------------------------------------------------------------


def test_b5_suppression_count_under_src_did_not_increase() -> None:
    pattern = re.compile(r"type:\s*ignore")
    total = 0
    per_file: dict[str, int] = {}
    for path in src_files():
        hits = len(pattern.findall(path.read_text(encoding="utf-8")))
        if hits:
            per_file[path.relative_to(SRC).as_posix()] = hits
        total += hits
    assert total <= TYPE_IGNORE_BASELINE, (
        f"behavior 5: the 35 errors must be fixed by annotation, not suppressed. "
        f"Baseline was {TYPE_IGNORE_BASELINE}; found {total}: {per_file}"
    )


def test_b5_no_type_arg_error_is_suppressed_anywhere_in_src() -> None:
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in src_files()
        if TYPE_ARG_CODE in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"no source file may mention {TYPE_ARG_CODE} (an inline suppression of "
        f"the very code this iteration closes); got {offenders}"
    )


# --------------------------------------------------------------------------
# Behavior 6 --- runtime behavior unchanged, import-safe on the CI matrix
# --------------------------------------------------------------------------


def test_b6_the_cli_still_reports_its_version() -> None:
    result = run_pla("--version")
    assert result.returncode == 0, (
        f"pla --version must exit 0; got {result.returncode}\n{result.stderr}"
    )
    assert EXPECTED_VERSION_LINE in result.stdout, (
        f"expected {EXPECTED_VERSION_LINE!r}; got stdout={result.stdout!r}"
    )


@pytest.mark.parametrize("verb", JSON_VERBS)
def test_b6_the_json_verbs_still_emit_objects(verb: str) -> None:
    result = run_pla(verb, "--json")
    assert result.returncode == 0, (
        f"pla {verb} --json must exit 0; got {result.returncode}\n{result.stderr}"
    )
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict) and payload, (
        f"pla {verb} --json must emit a non-empty JSON object; got {payload!r}"
    )


def test_b6_the_package_imports_cleanly_in_a_fresh_interpreter() -> None:
    """The eagerly-evaluated generic base class must resolve at IMPORT time.

    Annotations are lazy under ``from __future__ import annotations``, so the
    only site that can break at runtime is a base-class expression. Importing
    the CLI module in a fresh interpreter evaluates it.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import proactive_loop.cli as m; print(m.__name__)"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    assert result.returncode == 0, (
        f"importing proactive_loop.cli must not raise; stderr={result.stderr}"
    )
    assert "proactive_loop.cli" in result.stdout


def test_b6_the_stdlib_supports_the_subscripted_handler_base_class() -> None:
    """The spec's measured premise, re-measured on the running interpreter."""
    assert sys.version_info >= (3, 12), (
        f"the project requires >=3.12; running {sys.version_info}"
    )
    assert hasattr(logging.StreamHandler, "__class_getitem__"), (
        "logging.StreamHandler must be subscriptable for the eagerly-evaluated "
        f"base class to import on this interpreter ({sys.version})"
    )
    subscripted = logging.StreamHandler[TextIO]
    assert subscripted is not None


# --------------------------------------------------------------------------
# Fail-closed guards on this module's own readers
# --------------------------------------------------------------------------


def test_guard_the_mypy_probe_actually_invokes_the_checker(tmp_path: Path) -> None:
    """A probe that never ran mypy would make every probe above vacuous."""
    result = probe(tmp_path, "syntax_error", "def broken(\n")
    assert result.returncode != 0
    assert "error:" in result.stdout, (
        f"expected a real mypy diagnostic; got stdout={result.stdout!r}"
    )


def test_guard_the_config_reader_fires_when_the_table_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty-pyproject.toml"
    empty.write_text("[project]\nname = 'x'\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "PYPROJECT", empty)
    with pytest.raises(AssertionError, match=r"\[tool\] table"):
        mypy_table()
