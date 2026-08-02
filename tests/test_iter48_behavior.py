"""Black-box behavior tests for iteration 48 --- the new ``pla tools [--json]``
verb plus the public ``ToolRegistry.tool_names()`` accessor.

Feature under test (SPEC section 4.4/4.5, ``pm.md``): ``tools`` is a read-only,
LLM-free, zero-input catalog of the L1 ACT sandbox tool surface --- every
registered tool + a one-line description + its access class + the sandbox
read/write invariant --- so a reviewer of this public repo can answer "what can
a dispatched goal actually DO to my disk?" WITHOUT running anything. It carries
the same inert-globals envelope as ``policy`` (no ``LLMClient``, no workspace,
no settings, no filesystem touch, always exit 0). ``tool_names()`` is the single
source of truth for the tool-name set, drift-guarded against the ``--json``
catalog. Additive verb (11 -> 12), no version bump.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration --- the spec's "Expected Behaviors"
(``pm.md``), ``README.md``, and ``SPEC.md`` sections 4.4/4.5 --- and drive ONLY
documented public surfaces: the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (its observable stdout / stderr / exit
code), the public API ``proactive_loop.loop.tools.ToolRegistry`` (its
``tool_names()`` accessor and ``execute()`` observation strings), and the public
``proactive_loop.__version__`` string. **No file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted.** The fourteen
canonical tool names, the closed access-class set, and the access mapping are
encoded here as the spec-declared "Tester's constants", NOT imported from the
implementation, so the tests encode the spec and would catch an implementation
that silently drifts. Every test is fully offline: zero network, zero API keys,
no live provider.
"""

from __future__ import annotations

import json

import pytest

from proactive_loop import __version__
from proactive_loop.cli import main
from proactive_loop.loop.tools import ToolRegistry

# --------------------------------------------------------------------------
# Tester's constants --- the spec-declared ground facts (pm.md). Encoded here,
# NOT imported from src, to keep the tests black-box against the contract.
# --------------------------------------------------------------------------

# The fourteen canonical tool names (order-independent; compared as a set).
CANONICAL_TOOLS = {
    "write_file",
    "read_file",
    "list_files",
    "search_files",
    "append_file",
    "find_files",
    "stat_file",
    "head_file",
    "remove_file",
    "move_file",
    "tail_file",
    "diff_files",
    "replace_in_file",
    "read_lines",
}

# The closed access-class set (no other access word may be emitted).
CLOSED_ACCESS = {"read-only", "create-update", "move", "delete"}

# The spec-declared access mapping: tool name -> access class.
ACCESS_BY_TOOL = {
    "write_file": "create-update",
    "append_file": "create-update",
    "replace_in_file": "create-update",
    "read_file": "read-only",
    "list_files": "read-only",
    "search_files": "read-only",
    "find_files": "read-only",
    "stat_file": "read-only",
    "head_file": "read-only",
    "tail_file": "read-only",
    "read_lines": "read-only",
    "diff_files": "read-only",
    "move_file": "move",
    "remove_file": "delete",
}

# The two required top-level JSON keys (explicit allowlist, no more/fewer).
JSON_TOP_KEYS = {"sandbox", "tools"}

# The exactly-three keys of every tool object in the --json array.
TOOL_OBJ_KEYS = {"name", "access", "description"}

UNKNOWN_TOOL_PREFIX = "error: unknown tool"


# --------------------------------------------------------------------------
# Helpers --- black-box: drive main(), read back exit code + stdout/stderr.
# --------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and capture (exit_code, stdout, stderr)."""
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _tool_lines(out: str) -> dict[str, str]:
    """Map each canonical tool name -> the human catalog line that names it.

    A catalog line is one whose FIRST whitespace-delimited token equals a
    canonical tool name (the human form prints ``name  access  description``).
    Keying off the first token avoids false hits from tool names that are
    substrings of others (e.g. ``move`` inside ``remove_file``).
    """
    lines: dict[str, str] = {}
    for raw in out.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        first = stripped.split()[0]
        if first in CANONICAL_TOOLS:
            lines[first] = raw
    return lines


def _access_field(line: str) -> str:
    """The access token (2nd whitespace field) of a ``name access desc`` line."""
    parts = line.split()
    assert len(parts) >= 3, f"catalog line must be 'name access description'; got {line!r}"
    return parts[1]


def _tools_json(capsys) -> dict:
    """Run ``pla tools --json`` and return the parsed object (asserting exit 0)."""
    rc, out, err = _run(["tools", "--json"], capsys)
    assert rc == 0, f"`pla tools --json` must exit 0; stderr={err!r}"
    return json.loads(out)


# ==========================================================================
# Behavior 1 --- `pla tools` exits 0 and prints a human catalog naming all 14
# canonical tools (each at least once).
# ==========================================================================


def test_b01_tools_exit0_lists_all_fourteen(capsys):
    rc, out, err = _run(["tools"], capsys)
    assert rc == 0, f"bare `pla tools` must exit 0 (no config needed); stderr={err!r}"
    assert out.strip(), f"stdout must be non-empty; got {out!r}"
    for name in CANONICAL_TOOLS:
        assert name in out, f"human catalog must name tool {name!r}; got:\n{out}"


# ==========================================================================
# Behavior 2 --- Human view associates each tool with its access class on the
# SAME line; only closed-set access tokens are ever emitted.
# ==========================================================================


def test_b02_human_access_class_per_line_closed_set(capsys):
    rc, out, err = _run(["tools"], capsys)
    assert rc == 0, f"`pla tools` must exit 0; stderr={err!r}"
    lines = _tool_lines(out)
    assert set(lines.keys()) == CANONICAL_TOOLS, (
        f"expected exactly one catalog line per canonical tool; found "
        f"{sorted(lines)}"
    )
    for name, line in lines.items():
        access = _access_field(line)
        expected = ACCESS_BY_TOOL[name]
        assert access == expected, (
            f"{name}: access field on its line must be {expected!r}; got {access!r} "
            f"(line: {line!r})"
        )
        assert access in CLOSED_ACCESS, (
            f"{name}: access token {access!r} must be in the closed set {CLOSED_ACCESS}"
        )
    # Spec's concrete pins.
    assert "delete" in lines["remove_file"], "remove_file line must contain 'delete'"
    assert _access_field(lines["remove_file"]) == "delete", (
        "remove_file's access token must be 'delete', never 'read-only'"
    )
    assert _access_field(lines["move_file"]) == "move", "move_file access must be 'move'"
    assert _access_field(lines["write_file"]) == "create-update"
    assert _access_field(lines["append_file"]) == "create-update"
    for ro in ("read_file", "list_files", "search_files", "find_files", "stat_file", "head_file"):
        assert _access_field(lines[ro]) == "read-only", (
            f"{ro} access token must be 'read-only'"
        )
    # No access word outside the closed set is emitted across the catalog.
    emitted = {_access_field(line) for line in lines.values()}
    assert emitted <= CLOSED_ACCESS, (
        f"only closed-set access tokens may be emitted; saw extras {emitted - CLOSED_ACCESS}"
    )


# ==========================================================================
# Behavior 3 --- Human view states the sandbox invariant: artifacts_dir is
# writable, workspace_root is read-only.
# ==========================================================================


def test_b03_human_states_sandbox_invariant(capsys):
    rc, out, err = _run(["tools"], capsys)
    assert rc == 0, f"`pla tools` must exit 0; stderr={err!r}"
    for token in ("artifacts_dir", "workspace_root", "writable", "read-only"):
        assert token in out, (
            f"human catalog must state the sandbox invariant token {token!r}; got:\n{out}"
        )


# ==========================================================================
# Behavior 4 --- `pla tools --json` exits 0 and the ENTIRE stdout is ONE JSON
# object (no human trailer / extra prose).
# ==========================================================================


def test_b04_json_entire_stdout_is_one_object(capsys):
    rc, out, err = _run(["tools", "--json"], capsys)
    assert rc == 0, f"`pla tools --json` must exit 0; stderr={err!r}"
    obj = json.loads(out)  # ENTIRE stdout must parse as one JSON value
    assert isinstance(obj, dict), f"top-level JSON must be an object; got {type(obj)}"


# ==========================================================================
# Behavior 5 --- The --json object has EXACTLY {sandbox, tools}; sandbox names
# both roots as values; tools is an array.
# ==========================================================================


def test_b05_json_two_key_allowlist_sandbox_and_tools(capsys):
    obj = _tools_json(capsys)
    assert set(obj.keys()) == JSON_TOP_KEYS, (
        f"top-level keys must be EXACTLY {sorted(JSON_TOP_KEYS)} (no more, no fewer); "
        f"got {sorted(obj.keys())}"
    )
    sandbox = obj["sandbox"]
    assert isinstance(sandbox, dict), f"sandbox must be an object; got {type(sandbox)}"
    sandbox_values = {v for v in sandbox.values() if isinstance(v, str)}
    assert "artifacts_dir" in sandbox_values, (
        f"sandbox must identify the writable root as 'artifacts_dir' (a value); "
        f"got values {sandbox_values}"
    )
    assert "workspace_root" in sandbox_values, (
        f"sandbox must identify the read-only root as 'workspace_root' (a value); "
        f"got values {sandbox_values}"
    )
    assert isinstance(obj["tools"], list), f"tools must be a JSON array; got {type(obj['tools'])}"


# ==========================================================================
# Behavior 6 --- Each tools element is {name, access, description} EXACTLY;
# name str, access str in closed set, description non-empty str; array is
# name-ascending and has exactly 14 elements.
# ==========================================================================


def test_b06_json_tools_elements_shape_order_count(capsys):
    obj = _tools_json(capsys)
    tools = obj["tools"]
    assert len(tools) == 14, f"tools array must have exactly 14 elements; got {len(tools)}"
    for t in tools:
        assert set(t.keys()) == TOOL_OBJ_KEYS, (
            f"each tool object must have EXACTLY {sorted(TOOL_OBJ_KEYS)}; got {sorted(t.keys())}"
        )
        assert isinstance(t["name"], str) and t["name"], f"name must be a non-empty str; got {t['name']!r}"
        assert isinstance(t["access"], str), f"access must be a str; got {t['access']!r}"
        assert t["access"] in CLOSED_ACCESS, (
            f"access {t['access']!r} must be in the closed set {CLOSED_ACCESS}"
        )
        assert isinstance(t["description"], str) and t["description"].strip(), (
            f"description must be a non-empty str; got {t['description']!r}"
        )
    names = [t["name"] for t in tools]
    assert names == sorted(names), f"tools must be ordered by name ascending; got {names}"
    assert set(names) == CANONICAL_TOOLS, (
        f"the 14 names must be exactly the canonical set; got {sorted(names)}"
    )


# ==========================================================================
# Behavior 7 --- In --json, each tool's access value matches the spec mapping.
# ==========================================================================


def test_b07_json_access_mapping_correct(capsys):
    obj = _tools_json(capsys)
    got = {t["name"]: t["access"] for t in obj["tools"]}
    assert got == ACCESS_BY_TOOL, (
        f"--json access mapping must match the spec exactly.\nexpected {ACCESS_BY_TOOL}\n"
        f"got      {got}"
    )


# ==========================================================================
# Behavior 8 --- Drift guard: the --json catalog name set EQUALS the live
# registry name set.
# ==========================================================================


def test_b08_json_name_set_equals_registry(capsys):
    obj = _tools_json(capsys)
    catalog_names = {t["name"] for t in obj["tools"]}
    registry_names = set(ToolRegistry.tool_names())
    assert catalog_names == registry_names, (
        f"the `pla tools --json` name set must equal ToolRegistry.tool_names().\n"
        f"catalog-only : {catalog_names - registry_names}\n"
        f"registry-only: {registry_names - catalog_names}"
    )


# ==========================================================================
# Behavior 9 --- `ToolRegistry.tool_names()` is a public accessor returning the
# canonical registered names; every returned name is dispatchable.
# ==========================================================================


def test_b09_tool_names_public_and_all_dispatchable(tmp_path):
    names = ToolRegistry.tool_names()
    # Compared as a set (order unspecified per the spec).
    assert set(names) == CANONICAL_TOOLS, (
        f"tool_names() must return exactly the canonical 14 names; got {names}"
    )
    assert len(names) == 14, f"tool_names() must return 14 names; got {len(names)}"
    workspace = tmp_path / "ws"
    artifacts = tmp_path / "art"
    workspace.mkdir()
    artifacts.mkdir()
    registry = ToolRegistry(workspace_root=workspace, artifacts_dir=artifacts)
    for name in names:
        observation = registry.execute(name, {})
        assert isinstance(observation, str), f"execute({name!r}) must return a str"
        assert not observation.startswith(UNKNOWN_TOOL_PREFIX), (
            f"every name from tool_names() must be dispatchable; {name!r} returned "
            f"an unknown-tool error: {observation!r}"
        )


# ==========================================================================
# Behavior 10 --- A bogus tool name is neither dispatchable nor cataloged.
# ==========================================================================


def test_b10_bogus_tool_not_dispatchable_not_cataloged(tmp_path, capsys):
    workspace = tmp_path / "ws"
    artifacts = tmp_path / "art"
    workspace.mkdir()
    artifacts.mkdir()
    registry = ToolRegistry(workspace_root=workspace, artifacts_dir=artifacts)
    observation = registry.execute("__no_such_tool__", {})
    assert observation.startswith(UNKNOWN_TOOL_PREFIX), (
        f"a bogus tool must return an unknown-tool error; got {observation!r}"
    )
    assert "__no_such_tool__" not in ToolRegistry.tool_names(), (
        "a bogus tool must not appear in tool_names()"
    )
    obj = _tools_json(capsys)
    catalog_names = {t["name"] for t in obj["tools"]}
    assert "__no_such_tool__" not in catalog_names, (
        "a bogus tool must not appear in the `pla tools --json` catalog"
    )


# ==========================================================================
# Behavior 11 --- Inert globals (the policy envelope): --provider and a
# nonexistent --scripted-responses are accepted but never load-bearing; the
# output is IDENTICAL to the bare invocation.
# ==========================================================================


def test_b11_human_inert_provider_and_bad_script_same_catalog(tmp_path, capsys):
    bad = tmp_path / "no_such_file.json"  # never created
    assert not bad.exists()
    rc_plain, out_plain, _ = _run(["tools"], capsys)
    rc_inert, out_inert, err_inert = _run(
        ["tools", "--provider", "anthropic", "--scripted-responses", str(bad)], capsys
    )
    assert rc_plain == 0 and rc_inert == 0, (
        f"`pla tools` must exit 0 with inert provider/script; got plain={rc_plain}, "
        f"inert={rc_inert}, stderr={err_inert!r}"
    )
    assert out_inert == out_plain, (
        "inert --provider/--scripted-responses must not change the human catalog"
    )


def test_b11_json_inert_provider_same_object(capsys):
    rc_plain, out_plain, _ = _run(["tools", "--json"], capsys)
    rc_inert, out_inert, err = _run(["tools", "--json", "--provider", "openai"], capsys)
    assert rc_plain == 0 and rc_inert == 0, (
        f"`pla tools --json` must exit 0 with inert provider; got plain={rc_plain}, "
        f"inert={rc_inert}, stderr={err!r}"
    )
    assert json.loads(out_inert) == json.loads(out_plain), (
        "inert --provider must not change the --json object"
    )


# ==========================================================================
# Behavior 12 --- Unknown flag / stray positional is an argparse usage error
# (SystemExit code 2); `pla tools` accepts no positional argument.
# ==========================================================================


def test_b12_unknown_flag_is_usage_error_exit2():
    with pytest.raises(SystemExit) as excinfo:
        main(["tools", "--bogus-flag"])
    assert excinfo.value.code == 2, (
        f"an unknown flag must be an argparse usage error (SystemExit code 2); "
        f"got code {excinfo.value.code!r}"
    )


def test_b12_positional_arg_is_usage_error_exit2():
    with pytest.raises(SystemExit) as excinfo:
        main(["tools", "extra"])
    assert excinfo.value.code == 2, (
        f"`pla tools` accepts no positional argument (SystemExit code 2); "
        f"got code {excinfo.value.code!r}"
    )


# ==========================================================================
# Behavior 13 --- Backward compatibility: additive verb, no version bump; the
# unknown-tool error message still lists the available tools.
# ==========================================================================


def test_b13_version_unchanged():
    assert __version__ == "0.1.1", (
        f"tools is an additive verb: __version__ must stay '0.1.1'; got {__version__!r}"
    )


def test_b13_unknown_tool_message_still_lists_available(tmp_path):
    workspace = tmp_path / "ws"
    artifacts = tmp_path / "art"
    workspace.mkdir()
    artifacts.mkdir()
    registry = ToolRegistry(workspace_root=workspace, artifacts_dir=artifacts)
    observation = registry.execute("__nope__", {})
    assert observation.startswith(UNKNOWN_TOOL_PREFIX), (
        f"unknown-tool error message must be unchanged; got {observation!r}"
    )
    assert "available tools:" in observation, (
        f"unknown-tool error must still list available tools; got {observation!r}"
    )
    # The listed tools must be (a superset covering) the canonical set --- the
    # message is built from the same single source of truth.
    for name in CANONICAL_TOOLS:
        assert name in observation, (
            f"unknown-tool error must list {name!r}; got {observation!r}"
        )
