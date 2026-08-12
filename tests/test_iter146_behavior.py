"""Behavior tests for state-dir iteration 139 (ships as commit-seq ``factory iter 146``).

Feature under test: the LAST deferred strict-mode component
(``disallow_any_generics``) is CLOSED. The key is deleted from ``[tool.mypy]`` so
``strict = true`` stands unqualified, and the 35 bare generic annotations it was
hiding (``cli.py`` 19, ``loop/tools.py`` 15, ``loop/executor.py`` 1) are
parameterized.

Why this file exists when mypy is already the oracle
``make typecheck`` -- and the byte-identical CI step -- proves the shipped tree is
CLEAN under the config. It cannot prove the gate is ARMED, because a tree with
zero bare generics passes whether the flag is on or off: deleting the key and
deleting nothing else would look identical to the whole suite. What a downstream
``mypy --strict`` consumer of the published PEP 561 ``py.typed`` marker actually
relies on is not "this tree happens to be clean today" but "the NEXT bare ``dict``
is caught". Only firing the SHIPPED config on a known-bad module can show that.

Why the fixture is authored in ``tmp_path``
Every ship is re-verified from a throwaway fresh clone, where gitignored and
ambient local state does not exist. So this module asserts on nothing it did not
write itself, except the one tracked file that IS the subject under test
(``pyproject.toml``). No repo source file is read, and no test asserts a count of
anything in the working tree.

Two-sided by construction: the bad shape must be REJECTED and must NAME the
``type-arg`` code (an unactionable failure is a bad gate), and the parameterized
shape must PASS with a ``Success`` summary. A gate that rejects everything is as
useless as one that rejects nothing, and a probe that "passes" because the checker
never ran would make this file vacuous -- hence the crash check inside ``probe``
and the positive ``Success`` assertion in the control.

Isolation: black-box. The seams are (a) parsing the shipped ``pyproject.toml`` with
``tomllib`` -- the config IS the feature -- and (b) running the project's locked
mypy as a subprocess over modules written into ``tmp_path``.

Offline: file reads plus two short ``sys.executable -m mypy`` subprocesses against
the project's own pinned checker. No network, no API keys, no writes outside
``tmp_path``.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"

# The flag whose deferral this iteration closes. Named as a constant because the
# assertion is about its ABSENCE: re-adding it as ``false`` must fail by name.
CLOSED_FLAG = "disallow_any_generics"

# The error code that flag owns. A rejection that does not print it is not
# actionable for the developer who trips it.
TYPE_ARG_CODE = "type-arg"

# A bare generic annotation -- the exact shape the 35 fixed sites had. ``dict``
# alone means ``dict[Any, Any]``, which is what silently escaped the oracle.
BAD_MODULE = "def size(mapping: dict) -> int:\n    return len(mapping)\n"

# The SHIPPED remedy, verbatim in form: only the KEY tightens (``Any`` -> ``str``)
# and the value type stays ``Any``, so no expression became more precise and no
# second wave of strict errors could appear.
GOOD_MODULE = (
    "from typing import Any\n"
    "\n"
    "\n"
    "def size(mapping: dict[str, Any]) -> int:\n"
    "    return len(mapping)\n"
)


def mypy_table() -> dict[str, object]:
    """The ``[tool.mypy]`` table as SHIPPED, or fail loudly.

    Never returns ``{}``: an empty table would make the config assertion below
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


def probe(tmp_path: Path, name: str, body: str) -> subprocess.CompletedProcess[str]:
    """Write ``body`` under ``tmp_path`` and type-check it with the SHIPPED config.

    Uses ``sys.executable -m mypy`` so the checker is the pinned dev-dependency of
    this very interpreter (offline, reproducible), and a throwaway cache dir so a
    probe can never be answered from stale state.
    """
    module = tmp_path / f"{name}.py"
    module.write_text(body, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(PYPROJECT),
            "--cache-dir",
            str(tmp_path / f"cache-{name}"),
            str(module),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    assert "Traceback (most recent call last)" not in result.stderr, (
        f"mypy itself crashed on probe {name!r}; the gate proof is void.\n"
        f"stderr={result.stderr!r}"
    )
    return result


# ==========================================================================
# The ratchet is ARMED -- a bare generic is now an error, not a tolerated shape.
# ==========================================================================


def test_bare_generic_annotation_is_rejected_naming_type_arg(tmp_path: Path) -> None:
    """The distinction the shipped tree cannot make on its own.

    Before this iteration the identical module type-checked as ``Success``, which
    is why the package could advertise ``py.typed`` while handing a consumer
    ``dict[Any, Any]`` at 34 boundaries.
    """
    result = probe(tmp_path, "bare_generic", BAD_MODULE)

    assert result.returncode != 0, (
        f"the shipped config must REJECT a bare generic annotation now that "
        f"{CLOSED_FLAG} is closed; mypy exited 0, so the flag is off and the "
        f"'fully type-hinted' claim is unenforced.\nstdout={result.stdout!r}"
    )
    assert TYPE_ARG_CODE in result.stdout, (
        f"the rejection must name the {TYPE_ARG_CODE} error code so a developer "
        f"who trips it knows what to fix; got stdout={result.stdout!r}"
    )


def test_the_parameterized_form_passes_the_gate_does_not_over_fire(
    tmp_path: Path,
) -> None:
    """The other side: the remedy the 35 sites received must actually satisfy it.

    Also the fail-closed check on this module's machinery -- a ``Success`` summary
    can only come from a checker that really ran.
    """
    result = probe(tmp_path, "parameterized", GOOD_MODULE)

    assert result.returncode == 0, (
        "the SHIPPED remedy (`dict[str, Any]`) must pass the shipped config; a "
        f"gate that rejects the fix is unshippable.\nstdout={result.stdout!r}"
    )
    assert "Success" in result.stdout, (
        f"expected a Success summary, which is also the proof that mypy ran at "
        f"all; got stdout={result.stdout!r}"
    )


# ==========================================================================
# The exemption is GONE from the config, not merely satisfied by the tree.
# ==========================================================================


def test_the_closed_flag_is_absent_from_the_shipped_config() -> None:
    """``strict = true`` supplies the flag, so the key may not reappear.

    Deleted rather than set to ``true`` on purpose: the only thing that line ever
    did was name an exemption, and a redundant restatement invites the next
    editor to flip it instead of fixing what it surfaces.
    """
    table = mypy_table()

    assert CLOSED_FLAG not in table, (
        f"{CLOSED_FLAG} is back in [tool.mypy] as {table.get(CLOSED_FLAG)!r}. "
        f"`strict = true` already implies it, so the key can only weaken the "
        f"oracle or duplicate it -- delete it and parameterize the sites it "
        f"surfaces instead"
    )
    assert table.get("strict") is True, (
        f"the whole oracle rests on `strict = true`; got {table.get('strict')!r}"
    )
