"""Black-box behavior tests for iteration 78 (state dir iter-68).

Feature under test (pm.md / SPEC section 3): wire the
``PLA_SENSITIVE_CATEGORIES`` environment variable into
``proactive_loop.config.Settings.from_env``, making the autonomy gate's
always-approve category set env-overridable -- the one remaining unwired
``Settings`` field -- so ``config.py``'s "everything overridable via ``PLA_``"
contract and ``README.md``'s "Every runtime knob is overridable" prose become
true. Parse contract: split on ``,``, ``.strip().lower()`` each token, drop
empty tokens; >=1 valid token REPLACES ``sensitive_categories`` (no merge);
zero non-empty tokens keeps the default (fail-safe -- the gate can never be
emptied via the environment); an unknown token raises a plain ``ValueError``
(all-or-nothing, no partial set); an explicit keyword override beats the env.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration -- the spec's "Expected Behaviors"
(``pm.md``), ``README.md``, and ``SPEC.md`` section 3 -- and drive ONLY
documented public surfaces: the public API
``proactive_loop.config.Settings.from_env(...)`` and the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (its observable stdout / stderr /
exit code). **No file under ``src/`` was read, no engineer/reviewer notes
were read, and no ``git diff`` was consulted.** The six ``GoalCategory``
``.value`` strings, the two-member default sensitive set, and the canonical
14-name ``PLA_*`` env-var set are encoded here as the spec-declared "Tester's
constants", not derived from the implementation. Every test is fully offline
-- zero network, zero API keys, no live provider -- and uses ``monkeypatch``
to isolate process-environment state (auto-restored after each test).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.models import GoalCategory

# --------------------------------------------------------------------------
# Tester's constants -- spec-declared ground facts, encoded (not imported from
# src) to keep these tests black-box.
# --------------------------------------------------------------------------

ENV_VAR = "PLA_SENSITIVE_CATEGORIES"

# The default sensitive set, as sorted .value strings.
DEFAULT_SENSITIVE = ["finance_legal", "health_admin"]

# All six GoalCategory .value strings, ascending.
ALL_CATEGORY_VALUES = [
    "career",
    "finance_legal",
    "health_admin",
    "learning",
    "maintenance",
    "project",
]

# The canonical PLA_ env-var set AFTER this iteration -- 14 names. Re-encoded
# here as a black-box anti-rot bar: the README Configuration section must
# document exactly these 14 (independent of test_iter55's own drift guard).
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
    "PLA_SENSITIVE_CATEGORIES",
}

_PLA_TOKEN_RE = re.compile(r"\bPLA_[A-Z][A-Z_]*\b")

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"


# --------------------------------------------------------------------------
# Helpers -- black-box only.
# --------------------------------------------------------------------------

# Sentinel: an argument of _OMIT means "do not set the env var at all".
_OMIT = object()


def _cats(settings) -> list[str]:
    """Return settings.sensitive_categories as sorted .value strings."""
    return sorted(c.value for c in settings.sensitive_categories)


def _from_env_cats(monkeypatch, value=_OMIT, **kwargs) -> list[str]:
    """Set (or clear) PLA_SENSITIVE_CATEGORIES, build Settings.from_env(**kwargs),
    return the resulting sensitive-category .value strings, sorted.
    """
    if value is _OMIT:
        monkeypatch.delenv(ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(ENV_VAR, value)
    return _cats(Settings.from_env(**kwargs))


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and capture (exit_code, stdout, stderr)."""
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _config_section(text: str) -> str:
    """Return the README '## Configuration' section (heading to next H2/EOF)."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## Configuration"):
            start = i
            break
    assert start is not None, (
        "README.md must contain a '## Configuration...' section (Behavior 11)"
    )
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def _var_row(section: str) -> str:
    """Return the single Markdown table row line documenting ENV_VAR."""
    rows = [
        ln for ln in section.splitlines()
        if ln.lstrip().startswith("|") and ENV_VAR in ln
    ]
    assert len(rows) == 1, (
        f"the Configuration section must document {ENV_VAR} in exactly one "
        f"table row; found {len(rows)}: {rows!r}"
    )
    return rows[0]


# ==========================================================================
# Behavior 1 -- var absent -> default retained.
# ==========================================================================


def test_b1_absent_retains_default(monkeypatch):
    got = _from_env_cats(monkeypatch)
    assert got == DEFAULT_SENSITIVE, (
        f"with {ENV_VAR} unset, Settings.from_env().sensitive_categories must "
        f"be the default {DEFAULT_SENSITIVE}; got {got}"
    )


def test_b1_absent_equals_bare_settings(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    from_env = _cats(Settings.from_env())
    bare = _cats(Settings())
    assert from_env == bare == DEFAULT_SENSITIVE, (
        "with the var absent, from_env().sensitive_categories must equal a bare "
        f"Settings().sensitive_categories; from_env={from_env} bare={bare}"
    )


# ==========================================================================
# Behavior 2 -- single valid category REPLACES the set (no merge).
# ==========================================================================


def test_b2_single_category_replaces(monkeypatch):
    got = _from_env_cats(monkeypatch, "career")
    assert got == ["career"], (
        f"{ENV_VAR}=career must REPLACE the set with exactly {{career}}; got {got}"
    )


def test_b2_replace_not_merge_default_is_dropped(monkeypatch):
    got = set(_from_env_cats(monkeypatch, "career"))
    # The two default members must NOT be merged in (replace, not union).
    assert "health_admin" not in got and "finance_legal" not in got, (
        f"{ENV_VAR}=career must NOT merge the default two in; got {sorted(got)}"
    )


# ==========================================================================
# Behavior 3 -- multiple comma-separated valid categories -> exactly that set.
# ==========================================================================


def test_b3_multiple_categories(monkeypatch):
    got = _from_env_cats(monkeypatch, "health_admin,finance_legal,career")
    assert got == ["career", "finance_legal", "health_admin"], (
        f"three comma-separated valid categories must yield exactly that set; got {got}"
    )


# ==========================================================================
# Behavior 4 -- whitespace + case tolerance.
# ==========================================================================


def test_b4_whitespace_and_case_tolerant(monkeypatch):
    got = _from_env_cats(monkeypatch, " Health_Admin , CAREER ")
    assert got == ["career", "health_admin"], (
        "each token must be .strip().lower()-matched against the enum values; "
        f"got {got}"
    )


# ==========================================================================
# Behavior 5 -- lenient empty tokens (trailing / doubled commas ignored).
# ==========================================================================


def test_b5_trailing_comma_ignored(monkeypatch):
    got = _from_env_cats(monkeypatch, "career,")
    assert got == ["career"], f"a trailing comma must be ignored; got {got}"


def test_b5_doubled_comma_ignored(monkeypatch):
    got = _from_env_cats(monkeypatch, "career,,project")
    assert got == ["career", "project"], (
        f"a doubled comma must be ignored (empty token dropped); got {got}"
    )


# ==========================================================================
# Behavior 6 -- blank / whitespace-comma-only value -> NO override (fail-safe).
# ==========================================================================


def test_b6_empty_string_keeps_default(monkeypatch):
    got = _from_env_cats(monkeypatch, "")
    assert got == DEFAULT_SENSITIVE, (
        f'{ENV_VAR}="" must be treated as unset (default retained); got {got}'
    )


def test_b6_whitespace_comma_only_keeps_default(monkeypatch):
    got = _from_env_cats(monkeypatch, " , ")
    assert got == DEFAULT_SENSITIVE, (
        f'{ENV_VAR}=" , " (zero non-empty tokens) must keep the default; got {got}'
    )


def test_b6_gate_can_never_be_emptied_via_env(monkeypatch):
    # The load-bearing safety invariant: neither blank form empties the gate.
    for blank in ("", " ", " , ", ",", ",,", "  ,  ,  "):
        got = _from_env_cats(monkeypatch, blank)
        assert got == DEFAULT_SENSITIVE and len(got) >= 1, (
            f"{ENV_VAR}={blank!r} must NEVER empty the always-approve gate; "
            f"got {got}"
        )


# ==========================================================================
# Behavior 7 -- unknown category -> plain ValueError, no partial application.
# ==========================================================================


def test_b7_unknown_raises_plain_valueerror(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "bogus")
    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()
    # A PLAIN ValueError (not a subclass) so it composes with main()'s
    # `except (LLMError, ValueError, OSError)` boundary.
    assert type(excinfo.value) is ValueError, (
        f"an unknown category must raise a PLAIN ValueError, not "
        f"{type(excinfo.value).__name__}"
    )
    msg = str(excinfo.value)
    for needle in (ENV_VAR, "unknown category", "bogus"):
        assert needle in msg, (
            f"the ValueError message must contain {needle!r}; got {msg!r}"
        )


def test_b7_mixed_valid_and_unknown_is_all_or_nothing(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "career,bogus")
    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()
    assert type(excinfo.value) is ValueError
    assert "bogus" in str(excinfo.value), (
        "a mix of valid+unknown must raise naming the offending token; "
        f"got {str(excinfo.value)!r}"
    )
    # No partial application is observable because from_env() raised before
    # returning any Settings -- there is no object to inspect.


# ==========================================================================
# Behavior 8 -- explicit keyword override beats env.
# ==========================================================================


def test_b8_kwarg_override_beats_env(monkeypatch):
    got = _from_env_cats(
        monkeypatch, "career", sensitive_categories={GoalCategory.PROJECT}
    )
    assert got == ["project"], (
        "an explicit sensitive_categories= keyword override must beat the env "
        f"var (flag > env > default precedence); got {got}"
    )


# ==========================================================================
# Behavior 9 -- CLI end-to-end: `pla policy --json` reflects the override.
# ==========================================================================


def test_b9_cli_policy_json_reflects_override(monkeypatch, capsys):
    monkeypatch.setenv(ENV_VAR, "career")
    rc, out, _err = _run(["policy", "--json"], capsys)
    assert rc == 0, f"pla policy --json must exit 0; got {rc}"
    payload = json.loads(out)
    assert payload["sensitive_categories"] == ["career"], (
        "the policy --json sensitive_categories field must reflect the env "
        f"override as ['career']; got {payload.get('sensitive_categories')!r}"
    )


def test_b9_cli_policy_json_default_when_unset(monkeypatch, capsys):
    monkeypatch.delenv(ENV_VAR, raising=False)
    rc, out, _err = _run(["policy", "--json"], capsys)
    assert rc == 0
    payload = json.loads(out)
    assert payload["sensitive_categories"] == DEFAULT_SENSITIVE, (
        "with the var unset, policy --json must show the default sorted set; "
        f"got {payload.get('sensitive_categories')!r}"
    )


def test_b9_cli_policy_json_multi_sorted(monkeypatch, capsys):
    monkeypatch.setenv(ENV_VAR, "career,finance_legal")
    rc, out, _err = _run(["policy", "--json"], capsys)
    assert rc == 0
    payload = json.loads(out)
    assert payload["sensitive_categories"] == ["career", "finance_legal"], (
        "policy --json must emit the override as a sorted list of values; "
        f"got {payload.get('sensitive_categories')!r}"
    )


# ==========================================================================
# Behavior 10 -- CLI error boundary: unknown category -> one `error:` line, exit 1.
# ==========================================================================


def test_b10_cli_unknown_category_one_error_line_exit1(monkeypatch, capsys):
    monkeypatch.setenv(ENV_VAR, "bogus")
    rc, out, err = _run(["policy"], capsys)
    assert rc == 1, (
        f"an unknown category must exit 1 (not 0, not a raw traceback exit 2); got {rc}"
    )
    err_lines = err.strip().splitlines()
    assert len(err_lines) == 1, (
        f"exactly ONE stderr line expected; got {len(err_lines)}: {err_lines!r}"
    )
    line = err_lines[0]
    assert line.startswith("error:"), (
        f"the single stderr line must start with 'error:'; got {line!r}"
    )
    assert ENV_VAR in line, (
        f"the error line must name {ENV_VAR}; got {line!r}"
    )
    assert "Traceback" not in err, (
        "the error boundary must NOT print a raw Python traceback"
    )


def test_b10_cli_mixed_unknown_also_errors(monkeypatch, capsys):
    monkeypatch.setenv(ENV_VAR, "career,bogus")
    rc, _out, err = _run(["policy"], capsys)
    assert rc == 1
    assert err.strip().startswith("error:") and ENV_VAR in err, (
        f"a mixed valid+unknown env value must also hit the error boundary; got {err!r}"
    )


# ==========================================================================
# Behavior 11 -- docs<->code drift guard stays green + documents the new var.
# ==========================================================================


def test_b11_readme_documents_the_var_as_a_table_row():
    section = _config_section(README.read_text(encoding="utf-8"))
    row = _var_row(section)
    # The row must carry a default cell documenting the two-member default set.
    assert "health_admin" in row and "finance_legal" in row, (
        f"the {ENV_VAR} row must document the default health_admin,finance_legal; "
        f"got {row!r}"
    )


def test_b11_readme_row_explains_meaning():
    section = _config_section(README.read_text(encoding="utf-8"))
    row = _var_row(section).lower()
    # The meaning cell must convey the approval/replace semantics, not just name-drop.
    assert "approval" in row or "approve" in row, (
        f"the {ENV_VAR} row must explain that these categories need human "
        f"approval; got {row!r}"
    )
    assert "replace" in row, (
        f"the {ENV_VAR} row must convey REPLACE (not merge) semantics; got {row!r}"
    )


def test_b11_config_section_documents_exactly_fourteen_env_vars():
    # Independent anti-rot bar: the documented PLA_ set equals the canonical 14
    # (this iteration bumps the surface 13 -> 14 by adding PLA_SENSITIVE_CATEGORIES).
    section = _config_section(README.read_text(encoding="utf-8"))
    found = set(_PLA_TOKEN_RE.findall(section))
    missing = CANONICAL_ENV_VARS - found
    extra = found - CANONICAL_ENV_VARS
    assert not missing, f"Configuration section MISSING canonical vars: {sorted(missing)}"
    assert not extra, f"Configuration section has NON-canonical PLA_ tokens: {sorted(extra)}"
    assert found == CANONICAL_ENV_VARS, (
        f"documented set {sorted(found)} != canonical 14 {sorted(CANONICAL_ENV_VARS)}"
    )
    assert ENV_VAR in found, f"{ENV_VAR} must be one of the documented 14"


def test_b11_from_env_actually_reads_the_documented_var(monkeypatch):
    # The bidirectional pin: the newly-documented var is genuinely READ by
    # from_env (a non-default value round-trips), so docs != dead prose.
    got = _from_env_cats(monkeypatch, "project")
    assert got == ["project"], (
        f"{ENV_VAR} is documented AND must be read by from_env; got {got}"
    )
