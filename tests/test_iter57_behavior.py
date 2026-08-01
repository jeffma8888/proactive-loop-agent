"""Black-box behavior tests for iteration 57 --- the new ``pla collectors
[--json]`` verb: a read-only, LLM-free, ZERO-INPUT catalog of the L2 perception
surface (every registered context collector + a one-line description of what it
perceives). It is the context-free FRONT DOOR of the transparency arc
(``collectors`` -> ``signals`` -> ``scan`` -> ``explain`` -> ``trace``) and the
L2-perception analogue of the shipped ``pla tools`` / ``pla policy`` catalog
verbs: it carries the same inert-globals envelope (no ``LLMClient``, no
``--workspace``, no filesystem touch, always exit 0). Additive verb (12 -> 13),
no version bump.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration --- the spec's "Expected Behaviors"
(``pm.md``), ``README.md``, and ``SPEC.md`` --- and drive ONLY documented public
surfaces: the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (its
observable stdout / stderr / exit code), the public registry API
``proactive_loop.collectors.all_collectors()``, and the public
``proactive_loop.__version__`` string. **No file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted.** The
fourteen canonical collector names are encoded here as the spec-declared "Tester's
ground facts" (pm.md), NOT imported from any private catalog, so the tests
encode the CONTRACT and would catch an implementation that silently drifts.
Every test is fully offline: zero network, zero API keys, no live provider.
"""

from __future__ import annotations

import json

import pytest

from proactive_loop import __version__
from proactive_loop.cli import main
from proactive_loop.collectors import all_collectors

# --------------------------------------------------------------------------
# Tester's ground facts --- the spec-declared canonical set (pm.md). Encoded
# here as a constant, NOT imported from the implementation's private catalog,
# to keep the tests black-box against the contract.
# --------------------------------------------------------------------------

CANONICAL_COLLECTORS = {
    "ci_config",
    "lockfile_drift",
    "dependencies",
    "git_activity",
    "git_stash",
    "git_state",
    "large_file",
    "merge_conflict",
    "notes",
    "recent_files",
    "secret_file",
    "test_posture",
    "todos",
    "working_tree",
}

# The exactly-two keys of every collector object in the --json array.
COLLECTOR_OBJ_KEYS = {"name", "description"}


# --------------------------------------------------------------------------
# Helpers --- black-box: drive main(), read back exit code + stdout/stderr.
# --------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and capture (exit_code, stdout, stderr)."""
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _collector_leading_tokens(out: str) -> list[str]:
    """The ordered list of collector names appearing as a line's LEADING token.

    A catalog line is one whose FIRST whitespace-delimited token (after
    stripping) equals a canonical collector name. Keying off the first token
    ignores the header/preamble lines and only counts the ``name  description``
    catalog rows, in the order they appear.
    """
    tokens: list[str] = []
    for raw in out.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        first = stripped.split()[0]
        if first in CANONICAL_COLLECTORS:
            tokens.append(first)
    return tokens


def _collectors_json(capsys) -> dict:
    """Run ``pla collectors --json`` and return the parsed object (exit 0)."""
    rc, out, err = _run(["collectors", "--json"], capsys)
    assert rc == 0, f"`pla collectors --json` must exit 0; stderr={err!r}"
    return json.loads(out)


# ==========================================================================
# Behavior 1 --- Verb exists; zero-input human form exits 0 with a non-empty
# catalog (stderr empty). INERT: a bogus --scripted-responses path is never
# opened (still exit 0, same catalog); --provider anthropic builds no client.
# ==========================================================================


def test_b01_bare_collectors_exit0_nonempty_stderr_empty(capsys):
    rc, out, err = _run(["collectors"], capsys)
    assert rc == 0, f"bare `pla collectors` must exit 0 (no config needed); stderr={err!r}"
    assert out.strip(), f"stdout must be a non-empty catalog; got {out!r}"
    assert err == "", f"stderr must be empty for the happy path; got {err!r}"


def test_b01_inert_bogus_scripted_responses_still_exit0_same_catalog(capsys):
    # The verb is inert: it never opens the --scripted-responses file (mirrors
    # policy/tools). A client-building verb would eager-load and exit 1.
    baseline_rc, baseline_out, _ = _run(["collectors"], capsys)
    assert baseline_rc == 0
    rc, out, err = _run(
        ["collectors", "--scripted-responses", "/nonexistent/does_not_exist.json"],
        capsys,
    )
    assert rc == 0, (
        f"a bogus --scripted-responses path must NOT be opened; expected exit 0, "
        f"got {rc}; stderr={err!r}"
    )
    assert out == baseline_out, "the bogus path must produce the identical catalog"


def test_b01_inert_provider_flag_builds_no_client(capsys):
    rc, out, err = _run(["collectors", "--provider", "anthropic"], capsys)
    assert rc == 0, (
        f"`collectors --provider anthropic` must build no LLMClient and exit 0; "
        f"stderr={err!r}"
    )
    assert out.strip(), "must still print the catalog"


# ==========================================================================
# Behavior 2 --- Human form lists every registered collector, one per indented
# line, name-ascending, each with a non-empty description. The leading-token
# name set equals CANONICAL_COLLECTORS (no missing, no extra), in order.
# ==========================================================================


def test_b02_human_lists_each_collector_with_description(capsys):
    rc, out, err = _run(["collectors"], capsys)
    assert rc == 0, f"`pla collectors` must exit 0; stderr={err!r}"
    # Every canonical name appears as a leading token exactly once, each on a
    # line whose remainder is a non-empty description.
    lines_by_name: dict[str, str] = {}
    for raw in out.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        first = stripped.split()[0]
        if first in CANONICAL_COLLECTORS:
            assert first not in lines_by_name, f"collector {first!r} listed twice"
            lines_by_name[first] = stripped
    assert set(lines_by_name) == CANONICAL_COLLECTORS, (
        f"leading-token name set must equal the canonical 13; missing="
        f"{CANONICAL_COLLECTORS - set(lines_by_name)}, "
        f"extra={set(lines_by_name) - CANONICAL_COLLECTORS}"
    )
    for name, line in lines_by_name.items():
        remainder = line[len(name):].strip()
        assert remainder, (
            f"collector {name!r} line must carry a non-empty description; got {line!r}"
        )
        # >=1 non-whitespace description char (redundant w/ .strip() truthiness,
        # kept explicit per the spec's wording).
        assert any(not ch.isspace() for ch in remainder)


def test_b02_human_collectors_ascending(capsys):
    rc, out, err = _run(["collectors"], capsys)
    assert rc == 0
    tokens = _collector_leading_tokens(out)
    assert tokens == sorted(CANONICAL_COLLECTORS), (
        f"collector lines must appear name-ascending; got {tokens}"
    )


# ==========================================================================
# Behavior 3 --- `--json` emits exactly ONE JSON object with exactly one
# top-level key `collectors` (a list). No human trailer, nothing else.
# ==========================================================================


def test_b03_json_single_object_one_top_key(capsys):
    rc, out, err = _run(["collectors", "--json"], capsys)
    assert rc == 0, f"`pla collectors --json` must exit 0; stderr={err!r}"
    obj = json.loads(out)  # the ENTIRE stdout must parse as one object
    assert isinstance(obj, dict), f"top-level JSON must be an object; got {type(obj)}"
    assert set(obj.keys()) == {"collectors"}, (
        f"exactly one top-level key 'collectors' expected; got {sorted(obj.keys())}"
    )
    assert isinstance(obj["collectors"], list), "obj['collectors'] must be a list"


# ==========================================================================
# Behavior 4 --- Each `--json` entry has EXACTLY the two keys {name,
# description}, both non-empty strings (explicit allowlist, never a model dump).
# ==========================================================================


def test_b04_json_entries_exact_two_key_allowlist(capsys):
    obj = _collectors_json(capsys)
    assert obj["collectors"], "the collector list must be non-empty"
    for c in obj["collectors"]:
        assert set(c.keys()) == COLLECTOR_OBJ_KEYS, (
            f"each entry must have EXACTLY {COLLECTOR_OBJ_KEYS} (allowlist, no "
            f"leaked model dump); got {sorted(c.keys())}"
        )
        assert isinstance(c["name"], str) and c["name"], (
            f"name must be a non-empty string; got {c['name']!r}"
        )
        assert isinstance(c["description"], str) and c["description"], (
            f"description must be a non-empty string; got {c['description']!r}"
        )


# ==========================================================================
# Behavior 5 --- `--json` collector names equal the canonical 13, ascending.
# ==========================================================================


def test_b05_json_names_equal_sorted_canonical(capsys):
    obj = _collectors_json(capsys)
    names = [c["name"] for c in obj["collectors"]]
    assert names == sorted(CANONICAL_COLLECTORS), (
        f"json names must equal sorted canonical 14 (no dups/extras, ascending); "
        f"got {names}"
    )
    assert len(names) == 14


# ==========================================================================
# Behavior 6 --- Drift-guard: the emitted name set equals the LIVE registry,
# for BOTH forms. This is the load-bearing anti-rot coupling.
# ==========================================================================


def test_b06_json_names_equal_live_registry(capsys):
    obj = _collectors_json(capsys)
    emitted = {c["name"] for c in obj["collectors"]}
    live = {c.name for c in all_collectors()}
    assert emitted == live, (
        f"emitted --json names must equal the LIVE registry; symmetric diff="
        f"{emitted ^ live}"
    )
    assert emitted == CANONICAL_COLLECTORS


def test_b06_human_names_equal_live_registry(capsys):
    rc, out, err = _run(["collectors"], capsys)
    assert rc == 0
    human = set(_collector_leading_tokens(out))
    live = {c.name for c in all_collectors()}
    assert human == live == CANONICAL_COLLECTORS, (
        f"human-form name set must equal the live registry and the canonical 13; "
        f"human={sorted(human)}, live={sorted(live)}"
    )


# ==========================================================================
# Behavior 7 --- Human and `--json` forms describe the SAME collector set.
# ==========================================================================


def test_b07_human_and_json_same_set(capsys):
    rc, out, err = _run(["collectors"], capsys)
    assert rc == 0
    human = set(_collector_leading_tokens(out))
    obj = _collectors_json(capsys)
    json_names = {c["name"] for c in obj["collectors"]}
    assert human == json_names == CANONICAL_COLLECTORS, (
        f"human and --json forms must describe the identical canonical set; "
        f"human={sorted(human)}, json={sorted(json_names)}"
    )


# ==========================================================================
# Behavior 8 --- Context-free: no --workspace, no positional argument. Both are
# argparse usage errors (SystemExit code 2), unlike `signals`.
# ==========================================================================


def test_b08_workspace_flag_is_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main(["collectors", "--workspace", "."])
    assert excinfo.value.code == 2, (
        f"`collectors` takes no --workspace (usage error, code 2); "
        f"got {excinfo.value.code!r}"
    )


def test_b08_positional_arg_is_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main(["collectors", "some_positional"])
    assert excinfo.value.code == 2, (
        f"`collectors` takes no positional argument (usage error, code 2); "
        f"got {excinfo.value.code!r}"
    )


# ==========================================================================
# Behavior 9 --- --help discoverability. Top-level help lists `collectors` and
# still lists the prior subcommands; `collectors --help` mentions --json.
# ==========================================================================


def test_b09_top_level_help_lists_collectors_and_priors(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "collectors" in out, f"top-level --help must list `collectors`; got:\n{out}"
    for prior in ("scan", "policy", "tools", "signals"):
        assert prior in out, (
            f"top-level --help must still list the prior subcommand {prior!r}; got:\n{out}"
        )


def test_b09_collectors_help_mentions_json(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["collectors", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--json" in out, (
        f"`collectors --help` must mention the --json flag; got:\n{out}"
    )


# ==========================================================================
# Behavior 10 --- Additive: version unchanged; existing behavior intact; no
# collector added to the registry.
# ==========================================================================


def test_b10_version_unchanged():
    assert __version__ == "0.1.1", (
        f"adding this verb must NOT bump the version; got {__version__!r}"
    )


def test_b10_registry_unchanged_fourteen_collectors():
    assert len(all_collectors()) == 14, "the collector registry must still have 14 entries"
    assert {c.name for c in all_collectors()} == CANONICAL_COLLECTORS, (
        "the collector registry name set must be unchanged (verb adds no collector)"
    )
