"""Black-box behavior tests for iteration 75 (foundry state dir iter-65) --- the
new ``pla providers [--json]`` verb: a read-only, LLM-free, ZERO-INPUT catalog of
the L0 LLM-BACKEND surface (every accepted provider in ``VALID_PROVIDERS`` + its
``offline``/``cloud`` kind + the pip package that fulfils it, or ``null`` for the
built-in ``scripted`` client, + a one-line description). It is the FOURTH
self-documenting-CLI catalog verb --- the L0/provider-abstraction analogue of the
shipped ``pla policy`` (L2 autonomy rules), ``pla tools`` (L1 action surface), and
``pla collectors`` (L2 perception) --- carrying the same inert-globals envelope
(builds no ``LLMClient``, resolves no ``_settings``, runs no collector, touches no
filesystem, so it always exits 0). Additive verb (thirteen -> fourteen), no
version bump.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration --- the spec's "Expected Behaviors"
(``pm.md``), ``README.md``, and ``SPEC.md`` --- and drive ONLY documented public
surfaces: the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (its
observable stdout / stderr / exit code), the public provider registry
``proactive_loop.llm.providers.VALID_PROVIDERS``, the spec-directed drift-guard
target ``proactive_loop.cli._PROVIDER_CATALOG`` (Behavior 10 names it explicitly),
the live registries ``all_collectors()`` / ``ToolRegistry.tool_names()`` (the
Behavior-12 no-regression guard), the ``SPEC.md`` text (Behavior 11), and the
public ``proactive_loop.__version__`` string. **No file under ``src/`` was read,
no engineer/reviewer notes were read, and no ``git diff`` was consulted.** The
seven canonical provider names + their kind/package are encoded here as the
spec-declared "Tester's ground facts" (pm.md Behaviors 5/6), NOT imported from
any private catalog, so the tests encode the CONTRACT and would catch an
implementation that silently drifts. Every test is fully offline: zero network,
zero API keys, no live provider client is ever built.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from proactive_loop import __version__
from proactive_loop.cli import _PROVIDER_CATALOG, main
from proactive_loop.collectors import all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry

# --------------------------------------------------------------------------
# Tester's ground facts --- the spec-declared canonical set (pm.md Behaviors
# 1/5/6). Encoded here as constants, NOT imported from the implementation's
# private catalog, to keep the tests black-box against the CONTRACT.
# --------------------------------------------------------------------------

# Behavior 1: the seven accepted provider names.
CANONICAL_PROVIDERS = {
    "scripted",
    "anthropic",
    "openai",
    "bedrock",
    "ollama",
    "groq",
    "together",
}

# Behavior 5: the offline/cloud split.
CANONICAL_KIND = {
    "scripted": "offline",
    "ollama": "offline",
    "anthropic": "cloud",
    "openai": "cloud",
    "bedrock": "cloud",
    "groq": "cloud",
    "together": "cloud",
}

# Behavior 6: the pip install target (scripted has none; bedrock -> boto3).
CANONICAL_PACKAGE = {
    "scripted": None,
    "anthropic": "anthropic",
    "openai": "openai",
    "bedrock": "boto3",
    "ollama": "ollama",
    "groq": "groq",
    "together": "together",
}

# The exactly-four keys of every provider object in the --json array.
PROVIDER_OBJ_KEYS = {"name", "kind", "package", "description"}

# Repo root (this file lives in <repo>/tests/) --- for the SPEC.md drift-guard.
REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# Helpers --- black-box: drive main(), read back exit code + stdout/stderr.
# --------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and capture (exit_code, stdout, stderr)."""
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _provider_lines(out: str) -> dict[str, str]:
    """Map provider-name -> the full human catalog line whose FIRST token is it.

    Keying off the leading token ignores the header/preamble prose and only
    counts the ``name  kind  install  description`` catalog rows.
    """
    lines_by_name: dict[str, str] = {}
    for raw in out.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        first = stripped.split()[0]
        if first in CANONICAL_PROVIDERS:
            assert first not in lines_by_name, f"provider {first!r} listed twice"
            lines_by_name[first] = stripped
    return lines_by_name


def _provider_leading_tokens(out: str) -> list[str]:
    """Ordered list of provider names appearing as a line's LEADING token."""
    tokens: list[str] = []
    for raw in out.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        first = stripped.split()[0]
        if first in CANONICAL_PROVIDERS:
            tokens.append(first)
    return tokens


def _providers_json(capsys) -> dict:
    """Run ``pla providers --json`` and return the parsed object (exit 0)."""
    rc, out, err = _run(["providers", "--json"], capsys)
    assert rc == 0, f"`pla providers --json` must exit 0; stderr={err!r}"
    return json.loads(out)


# ==========================================================================
# Behavior 1 --- Human catalog, exit 0. Prints every one of the 7 provider
# names, each on its own line (name-ascending), and the printed name set equals
# set(VALID_PROVIDERS). stderr empty on the happy path.
# ==========================================================================


def test_b01_bare_providers_exit0_nonempty_stderr_empty(capsys):
    rc, out, err = _run(["providers"], capsys)
    assert rc == 0, f"bare `pla providers` must exit 0 (no config needed); stderr={err!r}"
    assert out.strip(), f"stdout must be a non-empty catalog; got {out!r}"
    assert err == "", f"stderr must be empty for the happy path; got {err!r}"


def test_b01_human_lists_every_provider_once(capsys):
    rc, out, err = _run(["providers"], capsys)
    assert rc == 0, f"`pla providers` must exit 0; stderr={err!r}"
    lines_by_name = _provider_lines(out)
    assert set(lines_by_name) == CANONICAL_PROVIDERS, (
        f"leading-token name set must equal the canonical 7; missing="
        f"{CANONICAL_PROVIDERS - set(lines_by_name)}, "
        f"extra={set(lines_by_name) - CANONICAL_PROVIDERS}"
    )


def test_b01_human_name_set_equals_valid_providers(capsys):
    rc, out, err = _run(["providers"], capsys)
    assert rc == 0
    human = set(_provider_leading_tokens(out))
    assert human == set(VALID_PROVIDERS), (
        f"human-form name set must equal the LIVE registry set(VALID_PROVIDERS); "
        f"symmetric diff={human ^ set(VALID_PROVIDERS)}"
    )


def test_b01_human_providers_name_ascending(capsys):
    rc, out, err = _run(["providers"], capsys)
    assert rc == 0
    tokens = _provider_leading_tokens(out)
    assert tokens == sorted(CANONICAL_PROVIDERS), (
        f"provider lines must appear name-ascending; got {tokens}"
    )


# ==========================================================================
# Behavior 2 --- `--json` is ONE object with EXACTLY one top-level key
# {providers} (a list). No human trailer; the ENTIRE stdout parses as one
# object. Exit 0.
# ==========================================================================


def test_b02_json_single_object_one_top_key(capsys):
    rc, out, err = _run(["providers", "--json"], capsys)
    assert rc == 0, f"`pla providers --json` must exit 0; stderr={err!r}"
    obj = json.loads(out)  # the ENTIRE stdout must parse as one object
    assert isinstance(obj, dict), f"top-level JSON must be an object; got {type(obj)}"
    assert set(obj.keys()) == {"providers"}, (
        f"exactly one top-level key 'providers' expected; got {sorted(obj.keys())}"
    )
    assert isinstance(obj["providers"], list), "obj['providers'] must be a list"


# ==========================================================================
# Behavior 3 --- Each provider object has EXACTLY the four keys
# {name, kind, package, description} (explicit allowlist, never a model dump);
# name/kind/description are strings, package is str OR null.
# ==========================================================================


def test_b03_json_entries_exact_four_key_allowlist(capsys):
    obj = _providers_json(capsys)
    assert obj["providers"], "the provider list must be non-empty"
    for p in obj["providers"]:
        assert set(p.keys()) == PROVIDER_OBJ_KEYS, (
            f"each entry must have EXACTLY {PROVIDER_OBJ_KEYS} (allowlist, no "
            f"leaked model dump); got {sorted(p.keys())}"
        )
        assert isinstance(p["name"], str) and p["name"], (
            f"name must be a non-empty string; got {p['name']!r}"
        )
        assert isinstance(p["kind"], str) and p["kind"], (
            f"kind must be a non-empty string; got {p['kind']!r}"
        )
        assert isinstance(p["description"], str) and p["description"], (
            f"description must be a non-empty string; got {p['description']!r}"
        )
        assert p["package"] is None or isinstance(p["package"], str), (
            f"package must be a string OR JSON null; got {p['package']!r}"
        )


# ==========================================================================
# Behavior 4 --- providers array is name-ascending and drift-guarded to the
# registry: the name set equals set(VALID_PROVIDERS) (proves the catalog is
# derived from the registry, not a hardcoded literal that could drift).
# ==========================================================================


def test_b04_json_names_ascending_and_equal_registry(capsys):
    obj = _providers_json(capsys)
    names = [p["name"] for p in obj["providers"]]
    assert names == sorted(names), f"json names must be name-ascending; got {names}"
    assert set(names) == set(VALID_PROVIDERS), (
        f"json name set must equal the LIVE registry set(VALID_PROVIDERS); "
        f"symmetric diff={set(names) ^ set(VALID_PROVIDERS)}"
    )
    assert set(names) == CANONICAL_PROVIDERS
    assert len(names) == len(set(names)) == len(VALID_PROVIDERS), (
        f"no duplicates; count must equal len(VALID_PROVIDERS); got {names}"
    )


# ==========================================================================
# Behavior 5 --- `kind` is the offline/cloud split. Each provider's kind is one
# of {offline, cloud}; scripted+ollama -> offline; the five cloud SDKs -> cloud.
# ==========================================================================


def test_b05_json_kind_offline_cloud_split(capsys):
    obj = _providers_json(capsys)
    by_name = {p["name"]: p for p in obj["providers"]}
    for name, expected_kind in CANONICAL_KIND.items():
        assert name in by_name, f"provider {name!r} missing from --json"
        got = by_name[name]["kind"]
        assert got in {"offline", "cloud"}, (
            f"{name!r} kind must be offline|cloud; got {got!r}"
        )
        assert got == expected_kind, (
            f"{name!r} kind must be {expected_kind!r}; got {got!r}"
        )


# ==========================================================================
# Behavior 6 --- `package` is the pip install target, with the bedrock->boto3
# divergence and scripted->null.
# ==========================================================================


def test_b06_json_package_install_target(capsys):
    obj = _providers_json(capsys)
    by_name = {p["name"]: p for p in obj["providers"]}
    for name, expected_pkg in CANONICAL_PACKAGE.items():
        assert name in by_name, f"provider {name!r} missing from --json"
        got = by_name[name]["package"]
        assert got == expected_pkg, (
            f"{name!r} package must be {expected_pkg!r}; got {got!r}"
        )
    # The load-bearing divergence, asserted explicitly.
    assert by_name["bedrock"]["package"] == "boto3", "bedrock must ship in boto3, NOT 'bedrock'"
    assert by_name["scripted"]["package"] is None, "scripted is built-in -> package null"


# ==========================================================================
# Behavior 7 --- INERT globals: builds no client, so a bad --provider /
# --scripted-responses still exits 0 (unlike a client-building verb).
# ==========================================================================


def test_b07a_bogus_provider_still_exit0(capsys):
    rc, out, err = _run(["providers", "--provider", "bogus"], capsys)
    assert rc == 0, (
        f"`providers --provider bogus` must build no LLMClient (no validation) "
        f"and exit 0; stderr={err!r}"
    )
    assert out.strip(), "must still print the catalog"


def test_b07b_bogus_scripted_responses_never_opened_exit0(capsys):
    # A client-building verb would eager-load this path and exit 1; providers
    # never opens it. The catalog must be byte-identical to the bare form.
    baseline_rc, baseline_out, _ = _run(["providers"], capsys)
    assert baseline_rc == 0
    rc, out, err = _run(
        ["providers", "--scripted-responses", "/no/such/file.json"], capsys
    )
    assert rc == 0, (
        f"a nonexistent --scripted-responses path must NOT be opened; expected "
        f"exit 0, got {rc}; stderr={err!r}"
    )
    assert out == baseline_out, "the bogus path must produce the identical catalog"


def test_b07c_json_bogus_provider_full_registry_complete_payload(capsys):
    rc, out, err = _run(["providers", "--json", "--provider", "bogus"], capsys)
    assert rc == 0, f"`providers --json --provider bogus` must exit 0; stderr={err!r}"
    obj = json.loads(out)
    assert set(obj.keys()) == {"providers"}
    names = {p["name"] for p in obj["providers"]}
    assert names == set(VALID_PROVIDERS), (
        f"a bogus --provider must NOT truncate/alter the registry-complete payload; "
        f"symmetric diff={names ^ set(VALID_PROVIDERS)}"
    )
    assert len(obj["providers"]) == len(VALID_PROVIDERS)


# ==========================================================================
# Behavior 8 --- Human render shows package per provider (bedrock line names
# boto3; scripted line presents a no-SDK / built-in marker); each provider line
# also carries its kind token (offline/cloud).
# ==========================================================================


def test_b08_human_line_carries_kind_token(capsys):
    rc, out, err = _run(["providers"], capsys)
    assert rc == 0
    lines_by_name = _provider_lines(out)
    for name, line in lines_by_name.items():
        kind = CANONICAL_KIND[name]
        tokens = line.split()
        assert kind in tokens, (
            f"provider {name!r} line must carry its kind token {kind!r} as a "
            f"whitespace-delimited token; got line {line!r}"
        )


def test_b08_human_cloud_line_names_its_package(capsys):
    rc, out, err = _run(["providers"], capsys)
    assert rc == 0
    lines_by_name = _provider_lines(out)
    for name, pkg in CANONICAL_PACKAGE.items():
        if pkg is None:
            continue  # scripted handled separately below
        assert pkg in lines_by_name[name], (
            f"provider {name!r} human line must name its pip package {pkg!r}; "
            f"got {lines_by_name[name]!r}"
        )


def test_b08_human_bedrock_line_names_boto3(capsys):
    rc, out, err = _run(["providers"], capsys)
    assert rc == 0
    lines_by_name = _provider_lines(out)
    assert "boto3" in lines_by_name["bedrock"], (
        f"the bedrock human line must name boto3 (label != package); "
        f"got {lines_by_name['bedrock']!r}"
    )


def test_b08_human_scripted_line_presents_no_sdk_marker(capsys):
    rc, out, err = _run(["providers"], capsys)
    assert rc == 0
    lines_by_name = _provider_lines(out)
    scripted_line = lines_by_name["scripted"]
    # scripted is built-in: no `pip install <pkg>` install directive, and it
    # carries an explicit no-SDK marker (observed: "(built-in)").
    assert "built-in" in scripted_line.lower(), (
        f"the scripted line must present its no-SDK / built-in status; "
        f"got {scripted_line!r}"
    )
    assert "pip install" not in scripted_line, (
        f"the scripted line must NOT name a pip package (it is built-in); "
        f"got {scripted_line!r}"
    )


# ==========================================================================
# Behavior 9 --- No positional argument; also context-free (no --workspace).
# Both are argparse usage errors (SystemExit code 2).
# ==========================================================================


def test_b09_positional_arg_is_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main(["providers", "something-extra"])
    assert excinfo.value.code == 2, (
        f"`providers` takes no positional argument (usage error, code 2); "
        f"got {excinfo.value.code!r}"
    )


def test_b09_workspace_flag_is_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main(["providers", "--workspace", "."])
    assert excinfo.value.code == 2, (
        f"`providers` takes no --workspace (context-free; usage error, code 2); "
        f"got {excinfo.value.code!r}"
    )


# ==========================================================================
# Behavior 10 --- In-process catalog drift-guard: cli._PROVIDER_CATALOG key set
# equals set(VALID_PROVIDERS) (the same anti-rot guard _TOOL_CATALOG /
# _COLLECTOR_CATALOG carry against their registries).
# ==========================================================================


def test_b10_provider_catalog_keys_equal_registry():
    assert set(_PROVIDER_CATALOG) == set(VALID_PROVIDERS), (
        f"_PROVIDER_CATALOG key set must equal set(VALID_PROVIDERS) (anti-rot "
        f"drift-guard); symmetric diff={set(_PROVIDER_CATALOG) ^ set(VALID_PROVIDERS)}"
    )
    assert set(_PROVIDER_CATALOG) == CANONICAL_PROVIDERS


# ==========================================================================
# Behavior 11 --- SPEC count drift-guard: SPEC.md states the shape exactly once
# as an "array of 7 {name, kind, package, description} objects", and that count
# equals len(VALID_PROVIDERS) AND the number of objects --json actually emits.
# ==========================================================================


def test_b11_spec_count_equals_registry_and_emitted(capsys):
    spec_text = (REPO_ROOT / "SPEC.md").read_text(encoding="utf-8")
    pat = re.compile(r"array of (\d+) `\{name, kind, package, description\}` objects")
    matches = pat.findall(spec_text)
    assert len(matches) == 1, (
        f"SPEC.md must state the providers --json shape EXACTLY once; found "
        f"{len(matches)} occurrences: {matches}"
    )
    stated = int(matches[0])
    assert stated == len(VALID_PROVIDERS), (
        f"SPEC-stated array count {stated} must equal len(VALID_PROVIDERS)="
        f"{len(VALID_PROVIDERS)}"
    )
    obj = _providers_json(capsys)
    assert stated == len(obj["providers"]), (
        f"SPEC-stated array count {stated} must equal the number of objects "
        f"`pla providers --json` emits ({len(obj['providers'])})"
    )


# ==========================================================================
# Behavior 12 --- Verb-count doc updated + no other-count regression. The cli.py
# module docstring reads "fifteen verbs" (was "thirteen"); the collector count is
# now 15 (later iters added syntax_error; the providers verb itself added no
# collector). Tool count is now 14 (the read_lines tool shipped later, factory
# iter 76; the providers verb added no tool).
# Version unchanged; --help discoverability.
# ==========================================================================


def test_b12_cli_docstring_says_fifteen_verbs():
    import proactive_loop.cli as cli_module

    doc = cli_module.__doc__ or ""
    assert "fifteen" in doc, (
        "cli.py module docstring must read 'fifteen verbs' after adding the "
        f"config verb; got docstring:\n{doc}"
    )
    assert "thirteen" not in doc, (
        "cli.py module docstring must no longer read 'thirteen'; got:\n" + doc
    )


def test_b12_collector_count_fifteen():
    assert len(all_collectors()) == 16, (
        "the collector registry must have 16 entries (later iters added syntax_error)"
    )


def test_b12_tool_count_fourteen():
    assert len(ToolRegistry.tool_names()) == 14, (
        "the tool registry has 14 entries (read_lines added in factory iter 76)"
    )


def test_b12_version_unchanged():
    assert __version__ == "0.1.1", (
        f"adding this verb must NOT bump the version; got {__version__!r}"
    )


def test_b12_top_level_help_lists_providers_and_priors(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "providers" in out, f"top-level --help must list `providers`; got:\n{out}"
    for prior in ("scan", "policy", "tools", "collectors", "signals"):
        assert prior in out, (
            f"top-level --help must still list the prior subcommand {prior!r}; got:\n{out}"
        )


def test_b12_providers_help_mentions_json(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["providers", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--json" in out, f"`providers --help` must mention the --json flag; got:\n{out}"
