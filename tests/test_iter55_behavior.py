"""Black-box behavior tests for iteration 55.

Feature under test: a new ``## Configuration (environment variables)`` section
in ``README.md`` documenting the complete ``PLA_*`` env-var surface (all 13
recognized variables, their CLI-flag equivalents, defaults, and meaning),
backed by a fully-offline docs<->code drift guard that pins the documented set
to what ``Settings.from_env()`` actually reads and to the code's own retry-var
table.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors", ``README.md``,
and ``SPEC.md`` -- and drive only the documented public surface: the
``README.md`` file content and the public API
``proactive_loop.config.Settings.from_env()`` (plus the spec-named
introspective handles ``proactive_loop.config.ENV_PREFIX`` /
``proactive_loop.config._RETRY_ENV_VARS`` for the Behavior-6 cross-check, which
the spec explicitly directs the test to consult). No file under ``src/`` was
read, no engineer/reviewer notes were read, and no ``git diff`` was consulted.
Every test is fully offline -- zero network, zero API keys -- and uses
``monkeypatch`` to isolate process-environment state (auto-restored after each
test).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from proactive_loop import config
from proactive_loop.config import Settings

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"

# The canonical env-var set is the source of truth for the drift guard.
# Hardcoded from this iteration's spec (the test is the drift guard, so the
# canonical list lives HERE, independent of the docs it validates).
CANONICAL_ENV_VARS = {
    "PLA_PROVIDER",
    "PLA_MODEL",
    "PLA_SCRIPTED_RESPONSES",
    "PLA_WORKSPACE_ROOT",
    "PLA_STATE_DIR",
    "PLA_AUTO_DISPATCH_MIN_SCORE",
    "PLA_MAX_ITERATIONS",
    "PLA_MAX_LLM_CALLS",
    "PLA_RETRY_MAX_ATTEMPTS",
    "PLA_RETRY_BASE_BACKOFF_SEC",
    "PLA_RETRY_BACKOFF_FACTOR",
    "PLA_RETRY_MAX_BACKOFF_SEC",
    "PLA_RETRY_JITTER_FRAC",
}

# The spec's own env-var token regex (Behavior 2).
_PLA_TOKEN_RE = re.compile(r"\bPLA_[A-Z][A-Z_]*\b")

# Behavior 5: each of the 13 vars set to a distinct, valid, NON-default value,
# paired with an accessor into the resulting Settings and the expected value.
_ENV_ROUNDTRIP = [
    ("PLA_PROVIDER", "anthropic", lambda s: s.provider, "anthropic"),
    ("PLA_MODEL", "claude-x", lambda s: s.model, "claude-x"),
    ("PLA_SCRIPTED_RESPONSES", "resp.json",
     lambda s: s.scripted_responses_path, Path("resp.json")),
    ("PLA_WORKSPACE_ROOT", "some/dir",
     lambda s: s.workspace_root, Path("some/dir")),
    ("PLA_STATE_DIR", "custom_runs", lambda s: s.state_dir, Path("custom_runs")),
    ("PLA_AUTO_DISPATCH_MIN_SCORE", "6.5",
     lambda s: s.auto_dispatch_min_score, 6.5),
    ("PLA_MAX_ITERATIONS", "3", lambda s: s.max_iterations, 3),
    ("PLA_MAX_LLM_CALLS", "10", lambda s: s.max_llm_calls, 10),
    ("PLA_RETRY_MAX_ATTEMPTS", "7", lambda s: s.retry.max_attempts, 7),
    ("PLA_RETRY_BASE_BACKOFF_SEC", "2.5",
     lambda s: s.retry.base_backoff_sec, 2.5),
    ("PLA_RETRY_BACKOFF_FACTOR", "3.0", lambda s: s.retry.backoff_factor, 3.0),
    ("PLA_RETRY_MAX_BACKOFF_SEC", "90.0",
     lambda s: s.retry.max_backoff_sec, 90.0),
    ("PLA_RETRY_JITTER_FRAC", "0.25", lambda s: s.retry.jitter_frac, 0.25),
]


# ---------------------------------------------------------------------------
# Helpers -- public-artifact readers only (never touches src/)
# ---------------------------------------------------------------------------


def _readme_text() -> str:
    assert README.is_file(), f"README.md must exist at {README}"
    return README.read_text(encoding="utf-8")


def _config_section(text: str) -> str:
    """Return the Configuration section: from the first line starting with
    ``## Configuration`` up to (but not including) the next line starting with
    ``## `` (a sibling H2), or end-of-file.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## Configuration"):
            start = i
            break
    assert start is not None, (
        "README.md must contain a top-level section whose heading starts with "
        "'## Configuration' (Behavior 1)"
    )
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


# ---------------------------------------------------------------------------
# Behavior 1 -- the Configuration section exists
# ---------------------------------------------------------------------------


def test_behavior1_configuration_section_exists():
    text = _readme_text()
    lines = text.splitlines()
    headings = [ln for ln in lines if ln.startswith("## Configuration")]
    assert headings, (
        "README.md must contain a top-level '## Configuration...' section "
        "(Behavior 1); found no matching H2 heading line"
    )
    section = _config_section(text)
    # The extracted section must begin at the heading and carry real content.
    assert section.splitlines()[0].startswith("## Configuration"), (
        f"section extraction must begin at the heading; got: "
        f"{section.splitlines()[0]!r}"
    )
    assert len(section.strip().splitlines()) > 3, (
        "the Configuration section must have substantive content, not a bare heading"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- docs<->code drift guard: EXACTLY the 13 canonical names
# ---------------------------------------------------------------------------


def test_behavior2_section_env_vars_equal_canonical_thirteen():
    section = _config_section(_readme_text())
    found = set(_PLA_TOKEN_RE.findall(section))
    extra = found - CANONICAL_ENV_VARS
    missing = CANONICAL_ENV_VARS - found
    assert not extra, (
        "the Configuration section documents PLA_ tokens OUTSIDE the canonical "
        f"13-name set: {sorted(extra)}"
    )
    assert not missing, (
        "the Configuration section is MISSING canonical PLA_ vars: "
        f"{sorted(missing)}"
    )
    assert found == CANONICAL_ENV_VARS, (
        f"section PLA_ token set {sorted(found)} != canonical "
        f"{sorted(CANONICAL_ENV_VARS)}"
    )
    # No bare wildcard token in the documented section.
    assert "PLA_*" not in section, (
        "the Configuration section must NOT contain a bare 'PLA_*' wildcard token"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- documented as a Markdown table with Variable + Default columns
# ---------------------------------------------------------------------------


def test_behavior3_documented_as_table_with_defaults():
    section = _config_section(_readme_text())
    lines = section.splitlines()
    table_lines = [ln for ln in lines if ln.lstrip().startswith("|")]
    assert table_lines, (
        "the Configuration section must render a Markdown table (at least one "
        "line beginning with '|')"
    )
    # Find a header row containing, case-insensitively, both Variable and
    # Default, plus a meaning/description column.
    header = None
    for ln in table_lines:
        low = ln.lower()
        if "variable" in low and "default" in low:
            header = ln
            break
    assert header is not None, (
        "the table header row must contain both 'Variable' and 'Default' "
        f"columns; table lines seen: {table_lines!r}"
    )
    low_header = header.lower()
    assert "meaning" in low_header or "description" in low_header, (
        "the table header must also carry a meaning/description column "
        f"(so vars are explained, not just name-dropped); header: {header!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- documented defaults ARE the model defaults (single source)
# ---------------------------------------------------------------------------


def test_behavior4_defaults_match_bare_settings(monkeypatch):
    for name in CANONICAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    from_env = Settings.from_env()
    bare = Settings()
    assert from_env == bare, (
        "with all 13 PLA_ vars ABSENT, Settings.from_env() must equal a bare "
        f"Settings() (documented defaults are the model defaults); got "
        f"{from_env!r} != {bare!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- every documented var is real and read by from_env()
# ---------------------------------------------------------------------------


def test_behavior5_every_documented_var_is_read(monkeypatch):
    # Sanity: the roundtrip table covers exactly the canonical 13.
    covered = {name for name, *_ in _ENV_ROUNDTRIP}
    assert covered == CANONICAL_ENV_VARS, (
        "the Behavior-5 roundtrip table must cover exactly the canonical 13; "
        f"diff: {covered ^ CANONICAL_ENV_VARS}"
    )
    for name, raw, _accessor, _expected in _ENV_ROUNDTRIP:
        monkeypatch.setenv(name, raw)
    settings = Settings.from_env()
    for name, raw, accessor, expected in _ENV_ROUNDTRIP:
        actual = accessor(settings)
        assert actual == expected, (
            f"{name}={raw!r} must be reflected by Settings.from_env(); "
            f"expected {expected!r}, got {actual!r}"
        )


def test_behavior5_roundtrip_values_are_all_non_default(monkeypatch):
    # The chosen roundtrip values must differ from the defaults, otherwise
    # Behavior 5 could pass vacuously (a var could be un-read yet still "match").
    for name in CANONICAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    defaults = Settings()
    for _name, _raw, accessor, expected in _ENV_ROUNDTRIP:
        assert accessor(defaults) != expected, (
            f"roundtrip expected value {expected!r} coincides with the default "
            f"for accessor {accessor!r}; pick a genuinely non-default value so "
            f"the read is actually exercised"
        )


# ---------------------------------------------------------------------------
# Behavior 6 -- retry-group cross-check against the code's own retry-var table
# ---------------------------------------------------------------------------


def test_behavior6_retry_names_match_code_retry_table():
    documented_retry = {n for n in CANONICAL_ENV_VARS if n.startswith("PLA_RETRY_")}
    code_retry = {
        config.ENV_PREFIX + suffix
        for (suffix, _field, _coerce) in config._RETRY_ENV_VARS
    }
    assert documented_retry == code_retry, (
        "the documented PLA_RETRY_* names must equal the code's own retry-var "
        f"table {{ENV_PREFIX+suffix for _RETRY_ENV_VARS}}; documented="
        f"{sorted(documented_retry)} code={sorted(code_retry)}"
    )
    # And those same five retry names must actually appear in the docs section.
    section = _config_section(_readme_text())
    section_tokens = set(_PLA_TOKEN_RE.findall(section))
    assert code_retry <= section_tokens, (
        "the five code-defined PLA_RETRY_* names must all be documented in the "
        f"Configuration section; missing: {sorted(code_retry - section_tokens)}"
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- explicit override beats env (precedence), and it's documented
# ---------------------------------------------------------------------------


def test_behavior7a_explicit_override_beats_env(monkeypatch):
    monkeypatch.setenv("PLA_MAX_ITERATIONS", "3")
    settings = Settings.from_env(max_iterations=99)
    assert settings.max_iterations == 99, (
        "an explicit Settings.from_env(max_iterations=99) override must beat "
        f"PLA_MAX_ITERATIONS=3; got {settings.max_iterations!r}"
    )


def test_behavior7b_precedence_documented_in_prose():
    section = _config_section(_readme_text()).lower()
    assert "precedence" in section, (
        "the Configuration section must state the flag>env>default precedence "
        "in prose (the word 'precedence' is absent)"
    )
    # Prose must convey that an explicit flag/override wins over the env var.
    assert ("wins over" in section) or ("takes precedence over" in section) or (
        "overrides" in section
    ), (
        "the Configuration section must state that an explicit CLI flag / "
        "override WINS OVER the corresponding PLA_ env var"
    )


def test_behavior7c_cli_flag_equivalents_named():
    section = _config_section(_readme_text())
    for flag in ("--provider", "--scripted-responses", "--state-dir", "--workspace"):
        assert flag in section, (
            f"the Configuration section must name the CLI-flag equivalent "
            f"{flag!r} (the four vars that have direct flags)"
        )
