"""Black-box behavior tests for iteration 104 --- the new ``pla config [--json]``
verb: a read-only, LLM-free, zero-input inspector that prints the fully-resolved
effective ``Settings`` after ``PLA_*`` env overrides and CLI-global flags are
folded in.

Feature under test (``pm.md`` Expected Behaviors 1-9): ``config`` closes the
observability gap left by the ``collectors``/``signals``/``tools``/``providers``/
``policy`` inspector family --- none of them shows the RESOLVED RUNTIME CONFIG the
agent will actually run with. ``pla config`` prints every ``Settings`` field as a
human catalog, or as ONE JSON object (explicit key allowlist, NOT
``model_dump()``) with ``--json``. It reflects ``PLA_*`` env overrides and the
shared ``--provider``/``--state-dir`` global flags through the ``_settings(args)``
seam (identical to ``policy``), builds no LLM client, and fails fast with a single
one-line ``error:`` on malformed env. Additive verb: parser count 14 -> 15.

ISOLATION CONTRACT (honored): these tests are written strictly against the public
contract for this iteration --- the spec's "Expected Behaviors" (``pm.md``) and
``README.md`` --- and drive ONLY documented public surfaces: the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (its observable stdout / stderr / exit
code) and the public ``build_parser()`` factory (the same seam the README-contract
test uses to count verbs). **No file under ``src/`` was read, no engineer/reviewer
notes were read, and no ``git diff`` was consulted.** The default field values, the
JSON key allowlist, the retry-knob key set, and the expected verb count are encoded
here as spec-declared "Tester's constants", not imported from the implementation.
Every test is fully offline: zero network, zero API keys, no workspace, no live
provider.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser, main
from tests.test_iter125_behavior import clear_pla_env


@pytest.fixture(autouse=True)
def _hermetic_pla_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the derived ``PLA_*`` set before EVERY test in this module.

    This module asserts DOCUMENTED DEFAULTS, so any ``PLA_*`` knob exported in
    the developer shell -- and the README publishes them all as the supported
    configuration surface -- red a clean checkout while looking like broken
    code. The target set is derived from the call sites the runtime reads, so a
    new knob is covered the moment it lands. Function-scoped and autouse, so it
    runs BEFORE each test body: a test that sets its own override still wins.
    """
    clear_pla_env(monkeypatch)

# --------------------------------------------------------------------------
# Tester's constants --- spec-declared ground facts (pm.md). Encoded here,
# NOT imported from src, to keep the tests black-box.
# --------------------------------------------------------------------------

# Behavior 2: the EXACT top-level --json key allowlist (no more, no fewer).
ALLOWLIST_KEYS = {
    "provider",
    "model",
    "scripted_responses_path",
    "workspace_root",
    "state_dir",
    "auto_dispatch_min_score",
    "sensitive_categories",
    "max_iterations",
    "max_llm_calls",
    "retry",
}

# Behavior 3: the nested retry object's five knob keys (exactly these).
RETRY_KEYS = {
    "max_attempts",
    "base_backoff_sec",
    "backoff_factor",
    "max_backoff_sec",
    "jitter_frac",
}

# Behavior 3/5: the default sensitive set, as sorted .value strings.
DEFAULT_SENSITIVE = ["finance_legal", "health_admin"]

# Behavior 1: spec-declared Settings defaults (clean env).
DEFAULT_PROVIDER = "scripted"
DEFAULT_THRESHOLD = 4.0
DEFAULT_MAX_ITERATIONS = 8
DEFAULT_MAX_LLM_CALLS = 24
DEFAULT_RETRY_MAX_ATTEMPTS = 5

# Behavior 9: the live argparse verb count after this additive verb lands.
EXPECTED_VERB_COUNT = 17



# --------------------------------------------------------------------------
# Helpers --- black-box: drive main(), read back exit code + stdout/stderr.
# --------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and capture (exit_code, stdout, stderr)."""
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _human_fields(out: str) -> dict[str, str]:
    """Parse the human catalog into a {label: value} map.

    Each field is rendered as an indented ``label: value`` line; the nested
    retry knobs use the same shape under a ``retry:`` header. We split on the
    FIRST colon so nested paths (e.g. ``/tmp/xyz``) in the value survive.
    """
    fields: dict[str, str] = {}
    for raw in out.splitlines():
        if ":" not in raw:
            continue
        label, _, value = raw.partition(":")
        fields[label.strip()] = value.strip()
    return fields


# ==========================================================================
# Behavior 1 --- `pla config` (clean env) exits 0 and prints a human catalog
# listing EVERY resolved Settings field, with the declared defaults.
# ==========================================================================


def test_b01_human_lists_every_field_with_defaults(capsys):
    rc, out, err = _run(["config"], capsys)
    assert rc == 0, f"bare `pla config` must exit 0 (no config needed); stderr={err!r}"
    assert out.strip(), f"stdout must be non-empty; got {out!r}"

    fields = _human_fields(out)
    # Every top-level Settings field label is present.
    for label in (
        "provider",
        "model",
        "scripted_responses_path",
        "workspace_root",
        "state_dir",
        "auto_dispatch_min_score",
        "sensitive_categories",
        "max_iterations",
        "max_llm_calls",
    ):
        assert label in fields, f"human catalog must list {label!r}; got:\n{out}"
    # Every retry knob label is present (nested under `retry:`).
    for knob in RETRY_KEYS:
        assert knob in fields, f"human catalog must list retry knob {knob!r}; got:\n{out}"

    # Declared defaults surface (labeled, so no fragile bare-substring match).
    assert fields["provider"] == DEFAULT_PROVIDER, (
        f"default provider must be {DEFAULT_PROVIDER!r}; got {fields['provider']!r}"
    )
    assert fields["auto_dispatch_min_score"] == "4.00", (
        f"default threshold must render '4.00'; got {fields['auto_dispatch_min_score']!r}"
    )
    assert fields["max_iterations"] == str(DEFAULT_MAX_ITERATIONS), (
        f"default max_iterations must be {DEFAULT_MAX_ITERATIONS}; "
        f"got {fields['max_iterations']!r}"
    )
    assert fields["max_llm_calls"] == str(DEFAULT_MAX_LLM_CALLS), (
        f"default max_llm_calls must be {DEFAULT_MAX_LLM_CALLS}; "
        f"got {fields['max_llm_calls']!r}"
    )
    assert fields["max_attempts"] == str(DEFAULT_RETRY_MAX_ATTEMPTS), (
        f"default retry.max_attempts must be {DEFAULT_RETRY_MAX_ATTEMPTS}; "
        f"got {fields['max_attempts']!r}"
    )


# ==========================================================================
# Behavior 2 --- `--json` emits EXACTLY the ten-key allowlist object; the
# ENTIRE stdout parses as ONE JSON object (schema-leak discipline; NOT
# model_dump()).
# ==========================================================================


def test_b02_json_exactly_the_ten_key_allowlist(capsys):
    rc, out, err = _run(["config", "--json"], capsys)
    assert rc == 0, f"`pla config --json` must exit 0; stderr={err!r}"
    obj = json.loads(out)  # ENTIRE stdout must parse as one object (no trailer)
    assert isinstance(obj, dict), f"top-level JSON must be an object; got {type(obj)}"
    assert set(obj.keys()) == ALLOWLIST_KEYS, (
        f"keys must be EXACTLY {sorted(ALLOWLIST_KEYS)} (no more, no fewer); "
        f"got {sorted(obj.keys())}"
    )


# ==========================================================================
# Behavior 3 --- JSON field-type contract: sensitive_categories is a sorted
# list of .value strings; retry is a nested object with exactly the five
# knobs; Path fields are strings (or null when unset); threshold is a number.
# ==========================================================================


def test_b03_json_field_types_and_shapes(capsys):
    rc, out, _ = _run(["config", "--json"], capsys)
    assert rc == 0
    obj = json.loads(out)

    # sensitive_categories: sorted list of .value strings, the two defaults.
    assert obj["sensitive_categories"] == DEFAULT_SENSITIVE, (
        f"sensitive_categories must be the sorted default {DEFAULT_SENSITIVE}; "
        f"got {obj['sensitive_categories']!r}"
    )

    # retry: nested object with EXACTLY the five knob keys.
    retry = obj["retry"]
    assert isinstance(retry, dict), f"retry must be a JSON object; got {type(retry)}"
    assert set(retry.keys()) == RETRY_KEYS, (
        f"retry keys must be EXACTLY {sorted(RETRY_KEYS)}; got {sorted(retry.keys())}"
    )
    assert retry["max_attempts"] == DEFAULT_RETRY_MAX_ATTEMPTS

    # Path-typed fields: emitted as strings (workspace_root/state_dir always set).
    assert isinstance(obj["workspace_root"], str), (
        f"workspace_root must be a JSON string; got {obj['workspace_root']!r}"
    )
    assert isinstance(obj["state_dir"], str), (
        f"state_dir must be a JSON string; got {obj['state_dir']!r}"
    )
    # Unset optional fields are null, never an empty string or a repr.
    assert obj["scripted_responses_path"] is None, (
        f"unset scripted_responses_path must be null; got {obj['scripted_responses_path']!r}"
    )
    assert obj["model"] is None, f"unset model must be null; got {obj['model']!r}"

    # threshold: a raw JSON number, not a formatted string.
    assert isinstance(obj["auto_dispatch_min_score"], (int, float)) and not isinstance(
        obj["auto_dispatch_min_score"], bool
    ), (
        f"auto_dispatch_min_score must be a JSON number, not a string; "
        f"got {obj['auto_dispatch_min_score']!r}"
    )
    assert obj["auto_dispatch_min_score"] == DEFAULT_THRESHOLD


# ==========================================================================
# Behavior 4 --- a PLA_MAX_ITERATIONS env override surfaces in BOTH forms
# (proves the resolved-effective contract through Settings.from_env).
# ==========================================================================


def test_b04_env_override_max_iterations_surfaces(monkeypatch, capsys):
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "3")

    rc, out, _ = _run(["config", "--json"], capsys)
    assert rc == 0
    obj = json.loads(out)
    assert obj["max_iterations"] == 3, (
        f"--json must reflect PLA_MAX_ITERATIONS=3; got {obj['max_iterations']!r}"
    )

    rc2, out2, _ = _run(["config"], capsys)
    assert rc2 == 0
    assert _human_fields(out2)["max_iterations"] == "3", (
        f"human form must reflect PLA_MAX_ITERATIONS=3; got:\n{out2}"
    )


# ==========================================================================
# Behavior 5 --- a nested retry-knob env override surfaces.
# ==========================================================================


def test_b05_env_override_retry_max_attempts_surfaces(monkeypatch, capsys):
    monkeypatch.setenv("PLA_RETRY_MAX_ATTEMPTS", "9")
    rc, out, _ = _run(["config", "--json"], capsys)
    assert rc == 0
    obj = json.loads(out)
    assert obj["retry"]["max_attempts"] == 9, (
        f"--json must reflect PLA_RETRY_MAX_ATTEMPTS=9; got {obj['retry']['max_attempts']!r}"
    )


# ==========================================================================
# Behavior 6 --- a CLI-global flag wins via the shared _settings seam, and no
# LLM client is built (a provider that would need an SDK does NOT error).
# ==========================================================================


def test_b06_provider_flag_overrides_no_client_built(capsys):
    rc, out, err = _run(["config", "--provider", "openai", "--json"], capsys)
    assert rc == 0, (
        f"`config --provider openai` must exit 0 (LLM-free, builds no client); "
        f"got exit {rc}, stderr={err!r}"
    )
    obj = json.loads(out)
    assert obj["provider"] == "openai", (
        f"--provider flag must win via the _settings seam; got {obj['provider']!r}"
    )


# ==========================================================================
# Behavior 7 --- the --state-dir global flag surfaces as the resolved
# state_dir string.
# ==========================================================================


def test_b07_state_dir_flag_surfaces(capsys):
    rc, out, _ = _run(["config", "--state-dir", "/tmp/xyz", "--json"], capsys)
    assert rc == 0
    obj = json.loads(out)
    assert obj["state_dir"] == "/tmp/xyz", (
        f"--state-dir must surface as the resolved state_dir; got {obj['state_dir']!r}"
    )


# ==========================================================================
# Behavior 8 --- fail-fast on malformed env: a single one-line `error:` on
# STDERR, exit 1, NO traceback, and NO JSON on stdout.
# ==========================================================================


def test_b08_malformed_env_is_clean_one_line_error(monkeypatch, capsys):
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "abc")
    rc, out, err = _run(["config"], capsys)
    assert rc == 1, f"malformed env must exit 1 (main() boundary); got {rc}"
    assert not out.strip(), (
        f"nothing must be printed on stdout when config fails to resolve; got {out!r}"
    )
    assert err.startswith("error:"), (
        f"stderr must be a single `error:` line; got {err!r}"
    )
    assert "PLA_MAX_ITERATIONS" in err, f"error must name the bad var; got {err!r}"
    assert "integer" in err, f"error must name the expected type; got {err!r}"
    assert "'abc'" in err, f"error must show the offending value via repr(); got {err!r}"
    assert "Traceback" not in err, f"error must NOT dump a Python traceback; got {err!r}"


# ==========================================================================
# Behavior 9 --- `config` is a registered subparser (live verb count is
# EXPECTED_VERB_COUNT) and the README PORTFOLIO-INTRO states that same count.
# ==========================================================================


def test_b09_config_is_registered_and_verb_count_matches_the_readme():
    parser = build_parser()
    subs = [
        a
        for a in parser._subparsers._group_actions
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(subs) == 1, f"expected exactly one subparser action, got {len(subs)}"
    choices = subs[0].choices
    assert "config" in choices, (
        f"`config` must be a registered subparser choice; got {sorted(choices)}"
    )
    assert len(choices) == EXPECTED_VERB_COUNT, (
        f"live verb count must be {EXPECTED_VERB_COUNT} after the additive verb; "
        f"got {len(choices)} ({sorted(choices)})"
    )


def test_b09_readme_intro_states_the_live_cli_verb_count():
    readme = Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert re.search(rf"\b{EXPECTED_VERB_COUNT} CLI verbs\b", text), (
        f"README PORTFOLIO-INTRO must state '{EXPECTED_VERB_COUNT} CLI verbs' -- the "
        "live count (mandated numeric carve-out). The literal is derived from "
        "EXPECTED_VERB_COUNT so this assertion and the count above can never disagree."
    )
