"""Black-box behavior tests for iteration 67 --- rot-proofing the two catalog-shape
counts and the tool access-mapping sentence in the PUBLIC design contract (``SPEC.md``).

Iteration 67 is a SPEC-prose + test-only change (NO ``src/`` runtime edit). Before this
iteration the design contract mis-stated the shapes of its OWN inspector output:
``SPEC.md`` claimed ``pla tools --json`` was an "array of 10" ``{name, access,
description}`` objects and ``pla collectors --json`` an "array of 12" ``{name,
description}`` objects, while the code emits **13** of each; the tools access-mapping
sentence also omitted three real tools (``replace_in_file`` [iter-66, create-update],
``tail_file`` [iter-54, read-only], ``diff_files`` [iter-61, read-only]). This iteration
corrects those three claims AND adds the drift-guard below so the SPEC counts / mapping
can never silently rot away from the live registries again.

ISOLATION CONTRACT (honored): these tests are written from ``SPEC.md`` (the public
contract), ``README.md``, and this iteration's PM spec (``pm.md``) ONLY, and drive the
PUBLIC surface --- the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (asserting
stdout / exit codes) plus the public ``ToolRegistry.tool_names()`` and
``proactive_loop.collectors.all_collectors()`` seams. **No file under ``src/`` was read,
no engineer/reviewer note was read, and no ``git diff`` was consulted.** The expected
count (14) and the canonical tool/collector name sets are encoded here as the
spec-declared ground facts, cross-checked against the live public API. Conventions
(``capsys``, JSON stdout parsing, offline / no-network / no-API-key) mirror
``tests/test_iter66_behavior.py`` (tools) and ``tests/test_iter57_behavior.py``
(collectors).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import proactive_loop
from proactive_loop.cli import main
from proactive_loop.collectors import all_collectors
from proactive_loop.loop.tools import ToolRegistry

# --- spec-declared ground facts (encoded here, NOT imported from any private catalog) ---
EXPECTED_COUNT = 14  # TOOLS count (pla tools --json / SPEC tools shape)
EXPECTED_COLLECTOR_COUNT = 16  # COLLECTORS count; decoupled once a collector was added without a tool

CANONICAL_TOOLS = {
    "write_file",
    "append_file",
    "replace_in_file",
    "read_file",
    "head_file",
    "tail_file",
    "list_files",
    "stat_file",
    "search_files",
    "find_files",
    "diff_files",
    "move_file",
    "remove_file",
    "read_lines",
}

CANONICAL_COLLECTORS = {
    "ci_config",
    "lockfile_drift",
    "dependencies",
    "git_activity",
    "git_stash",
    "git_state",
    "large_file",
    "license",
    "merge_conflict",
    "notes",
    "recent_files",
    "secret_file",
    "syntax_error",
    "test_posture",
    "todos",
    "working_tree",
}

# The tools omitted from SPEC's access mapping before this iteration + their fixed class.
NEWLY_MAPPED = {
    "replace_in_file": "create-update",
    "tail_file": "read-only",
    "diff_files": "read-only",
}
ACCESS_CLASSES = {"read-only", "create-update", "move", "delete"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec_path() -> Path:
    """The public design contract lives at the repo root, one level above tests/."""
    return Path(__file__).resolve().parent.parent / "SPEC.md"


def _spec_norm() -> str:
    """Whitespace-normalized SPEC text (all whitespace runs -> single space)."""
    return re.sub(r"\s+", " ", _spec_path().read_text(encoding="utf-8"))


def _tools_json(capsys) -> dict:
    """Run ``pla tools --json`` and return the parsed object (asserting exit 0)."""
    rc = main(["tools", "--json"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla tools --json` must exit 0"
    return json.loads(out)


def _collectors_json(capsys) -> dict:
    """Run ``pla collectors --json`` and return the parsed object (asserting exit 0)."""
    rc = main(["collectors", "--json"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla collectors --json` must exit 0"
    return json.loads(out)


# ===========================================================================
# Behavior 1 --- `pla tools --json` emits exactly 14 tool objects (unchanged shape)
# ===========================================================================


def test_eb1_tools_json_emits_fourteen_objects(capsys) -> None:
    obj = _tools_json(capsys)
    assert set(obj.keys()) == {"sandbox", "tools"}, obj.keys()

    tools = obj["tools"]
    assert isinstance(tools, list), type(tools)
    assert len(tools) == EXPECTED_COUNT, (
        f"`pla tools --json` must emit {EXPECTED_COUNT} objects; got {len(tools)}"
    )

    # Each object keeps EXACTLY {name, access, description}.
    for t in tools:
        assert set(t.keys()) == {"name", "access", "description"}, t
        assert t["access"] in ACCESS_CLASSES, t

    names = {t["name"] for t in tools}
    assert names == CANONICAL_TOOLS, sorted(names)
    # Cross-check the live public registry agrees.
    assert names == set(ToolRegistry.tool_names()), sorted(
        names ^ set(ToolRegistry.tool_names())
    )

    # Name-ascending order is preserved.
    emitted = [t["name"] for t in tools]
    assert emitted == sorted(emitted), emitted


# ===========================================================================
# Behavior 2 --- `pla collectors --json` emits exactly 15 collector objects (shape)
# ===========================================================================


def test_eb2_collectors_json_emits_fifteen_objects(capsys) -> None:
    obj = _collectors_json(capsys)
    assert set(obj.keys()) == {"collectors"}, obj.keys()

    collectors = obj["collectors"]
    assert isinstance(collectors, list), type(collectors)
    assert len(collectors) == EXPECTED_COLLECTOR_COUNT, (
        f"`pla collectors --json` must emit {EXPECTED_COLLECTOR_COUNT} objects; got {len(collectors)}"
    )

    # Each object keeps EXACTLY {name, kind, description} (the `kind` column
    # shipped later; the assertion stays an exact set, only the allowlist grew).
    for c in collectors:
        assert set(c.keys()) == {"name", "kind", "description"}, c

    names = {c["name"] for c in collectors}
    assert names == CANONICAL_COLLECTORS, sorted(names)
    # Cross-check the live public registry agrees.
    assert names == {c.name for c in all_collectors()}, sorted(
        names ^ {c.name for c in all_collectors()}
    )

    # Name-ascending order is preserved.
    emitted = [c["name"] for c in collectors]
    assert emitted == sorted(emitted), emitted


# ===========================================================================
# Behavior 3 --- SPEC tool-count drift-guard
# ===========================================================================


def test_eb3_spec_tool_count_matches_live_registry(capsys) -> None:
    norm = _spec_norm()
    # Anchor on the distinctive {name, access, description} key tuple.
    matches = re.findall(
        r"array of (\d+) [^{}]*\{name, access, description\}[^{}]*objects", norm
    )
    assert len(matches) == 1, (
        f"SPEC must state the tools catalog shape exactly once; found {len(matches)}: {matches}"
    )
    n = int(matches[0])

    assert n == EXPECTED_COUNT, (
        f"SPEC tools-catalog-shape count is {n}; expected {EXPECTED_COUNT} "
        f"(SPEC prose drifted from the code)"
    )
    assert n == len(ToolRegistry.tool_names()), (
        f"SPEC says {n} tools; live ToolRegistry.tool_names() has "
        f"{len(ToolRegistry.tool_names())} --- SPEC drifted from the registry"
    )
    assert n == len(_tools_json(capsys)["tools"]), (
        f"SPEC says {n} tools; `pla tools --json` emits "
        f"{len(_tools_json(capsys)['tools'])}"
    )


# ===========================================================================
# Behavior 4 --- SPEC collector-count drift-guard
# ===========================================================================


def test_eb4_spec_collector_count_matches_live_registry(capsys) -> None:
    norm = _spec_norm()
    # Anchor on the {name, description} tuple --- it does NOT match the tools
    # {name, access, description} tuple.
    matches = re.findall(
        r"array of (\d+) [^{}]*\{name, description\}[^{}]*objects", norm
    )
    assert len(matches) == 1, (
        f"SPEC must state the collectors catalog shape exactly once; "
        f"found {len(matches)}: {matches}"
    )
    n = int(matches[0])

    assert n == EXPECTED_COLLECTOR_COUNT, (
        f"SPEC collectors-catalog-shape count is {n}; expected {EXPECTED_COLLECTOR_COUNT} "
        f"(SPEC prose drifted from the code)"
    )
    assert n == len(all_collectors()), (
        f"SPEC says {n} collectors; live all_collectors() has "
        f"{len(all_collectors())} --- SPEC drifted from the registry"
    )
    assert n == len(_collectors_json(capsys)["collectors"]), (
        f"SPEC says {n} collectors; `pla collectors --json` emits "
        f"{len(_collectors_json(capsys)['collectors'])}"
    )


# ===========================================================================
# Behavior 5 --- Access-mapping completeness (fix + guard)
# ===========================================================================


def _access_mapping_region() -> str:
    """The tools access-mapping region: from the unique marker up to the FIRST
    subsequent tools-section --json sentence."""
    norm = _spec_norm()
    start_marker = "The access mapping is:"
    end_marker = "emits one object of EXACTLY"
    assert norm.count(start_marker) == 1, (
        f"'The access mapping is:' must occur exactly once; got {norm.count(start_marker)}"
    )
    i = norm.index(start_marker)
    j = norm.index(end_marker, i)
    region = norm[i:j]
    assert region.strip(), "access-mapping region must be non-empty"
    return region


def test_eb5_access_mapping_names_every_tool() -> None:
    region = _access_mapping_region()

    # Every LIVE tool name is backtick-quoted in the mapping region.
    for name in ToolRegistry.tool_names():
        assert f"`{name}`" in region, (
            f"access-mapping sentence must name `{name}`; region was:\n{region}"
        )

    # In particular the three tools absent before this iteration are now present.
    for name in NEWLY_MAPPED:
        assert f"`{name}`" in region, (
            f"`{name}` (added in a prior iteration) must appear in the access mapping"
        )

    # All four access classes (the closed set) are still referenced --- unchanged.
    for klass in ACCESS_CLASSES:
        assert f"`{klass}`" in region, (
            f"access class `{klass}` must remain in the mapping; region:\n{region}"
        )


# ===========================================================================
# Behavior 6 --- No runtime / CLI-output regression (SPEC-prose + test-only change)
# ===========================================================================


def test_eb6_no_version_bump() -> None:
    assert proactive_loop.__version__ == "0.1.1", (
        f"SPEC-prose-only change: __version__ must stay '0.1.1'; "
        f"got {proactive_loop.__version__!r}"
    )


def test_eb6_inspector_output_stable_and_exit_zero(capsys) -> None:
    # Both inspectors still exit 0 and are stable across repeated invocations
    # (they read no SPEC.md and take no input, so they cannot regress on this change).
    rc1 = main(["tools", "--json"])
    out1 = capsys.readouterr().out
    rc2 = main(["tools", "--json"])
    out2 = capsys.readouterr().out
    assert rc1 == rc2 == 0, (rc1, rc2)
    assert out1 == out2, "`pla tools --json` output must be deterministic"

    rc3 = main(["collectors", "--json"])
    out3 = capsys.readouterr().out
    rc4 = main(["collectors", "--json"])
    out4 = capsys.readouterr().out
    assert rc3 == rc4 == 0, (rc3, rc4)
    assert out3 == out4, "`pla collectors --json` output must be deterministic"
