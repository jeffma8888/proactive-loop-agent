"""Black-box behavior tests for iteration 39 --- the new ``pla policy [--json]``
verb: a read-only, LLM-free, zero-input catalog of the STANDING autonomy
contract (the product's headline safety mechanism).

Feature under test (SPEC section 4.5, ``pm.md``): ``policy`` surfaces the gate
PROACTIVELY rather than only reactively through a gated ``scan``/``explain``
(both of which need a synthesized slate). It prints the resolved auto-dispatch
threshold, the sensitive-category set, every ``GoalCategory`` tagged
sensitive vs. auto-eligible, and the four ordered ``policy.gate`` rules
(first match wins). ``--json`` emits ONE object of EXACTLY four allowlisted
keys. It reflects a ``PLA_AUTO_DISPATCH_MIN_SCORE`` env override through the
shared ``_settings(args)`` seam. Additive verb (10 -> 11), no version bump.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract for this iteration --- the spec's "Expected Behaviors"
(``pm.md``), ``README.md``, and ``SPEC.md`` section 4.5 --- and drive ONLY
documented public surfaces: the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (its observable stdout / stderr /
exit code) and the public ``proactive_loop.__version__`` string. **No file
under ``src/`` was read, no engineer/reviewer notes were read, and no
``git diff`` was consulted.** The expected six ``GoalCategory`` ``.value``
strings, the two-member default sensitive set, and the ``4.0`` default
threshold are encoded here as the spec-declared "Tester's constants", not
imported from the implementation. Every test is fully offline: zero network,
zero API keys, no workspace, no scripted-responses file, no live provider.
"""

from __future__ import annotations

import json

import pytest

from proactive_loop import __version__
from proactive_loop.cli import main

# --------------------------------------------------------------------------
# Tester's constants --- the spec-declared ground facts (pm.md "Ground facts").
# Encoded here, NOT imported from src, to keep the tests black-box.
# --------------------------------------------------------------------------

# Exactly the six GoalCategory .value strings, in ascending sort order.
ALL_CATEGORIES = [
    "career",
    "finance_legal",
    "health_admin",
    "learning",
    "maintenance",
    "project",
]

# The default sensitive set, as sorted .value strings.
SENSITIVE_CATEGORIES = ["finance_legal", "health_admin"]

# The Settings.auto_dispatch_min_score default (a JSON number).
DEFAULT_THRESHOLD = 4.0

# The four required top-level JSON keys (explicit allowlist, no more/fewer).
JSON_KEYS = {"auto_dispatch_min_score", "sensitive_categories", "categories", "rules"}


# --------------------------------------------------------------------------
# Helpers --- black-box: drive main(), read back exit code + stdout.
# --------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and capture (exit_code, stdout, stderr)."""
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _category_lines(out: str) -> dict[str, str]:
    """Map each category .value -> the human-form catalog line that lists it.

    A catalog line is a bullet line ``  - <value> ...`` in the ``categories:``
    block. Scoping to bullet lines avoids counting the word "sensitive" that
    also appears in the gate-rules narration.
    """
    lines: dict[str, str] = {}
    for raw in out.splitlines():
        stripped = raw.strip()
        if not stripped.startswith("-"):
            continue
        token = stripped[1:].strip().split()[0] if stripped[1:].strip() else ""
        if token in ALL_CATEGORIES:
            lines[token] = raw
    return lines


# ==========================================================================
# Behavior 1 --- The verb exists, is read-only, and needs no config.
# main(["policy"]) -> exit 0 with non-empty stdout, with NO --workspace, NO
# --scripted-responses, and the default `scripted` provider.
# ==========================================================================


def test_b01_policy_needs_no_config_exit0_nonempty(capsys):
    rc, out, err = _run(["policy"], capsys)
    assert rc == 0, f"bare `pla policy` must exit 0 (no config needed); stderr={err!r}"
    assert out.strip(), f"stdout must be non-empty; got {out!r}"


# ==========================================================================
# Behavior 2 --- No LLMClient is built: a nonexistent --scripted-responses
# path is never opened, so policy still exits 0 (a client-building verb given
# the same path exits 1 via create_client's eager load).
# ==========================================================================


def test_b02_nonexistent_script_path_ignored_exit0(tmp_path, capsys):
    bad = tmp_path / "no_such_file.json"  # never created
    assert not bad.exists()
    rc, out, err = _run(["policy", "--scripted-responses", str(bad)], capsys)
    assert rc == 0, (
        f"policy must ignore a nonexistent --scripted-responses (builds no client); "
        f"got exit {rc}, stderr={err!r}"
    )
    assert out.strip(), f"stdout must still be non-empty; got {out!r}"


# ==========================================================================
# Behavior 3 --- --json emits EXACTLY the four-key allowlist object; the
# entire stdout parses as ONE JSON object (iter-08 schema-leak discipline).
# ==========================================================================


def test_b03_json_exactly_four_key_allowlist(capsys):
    rc, out, err = _run(["policy", "--json"], capsys)
    assert rc == 0, f"`pla policy --json` must exit 0; stderr={err!r}"
    obj = json.loads(out)  # ENTIRE stdout must be one JSON object
    assert isinstance(obj, dict), f"top-level JSON must be an object; got {type(obj)}"
    assert set(obj.keys()) == JSON_KEYS, (
        f"keys must be EXACTLY {sorted(JSON_KEYS)} (no more, no fewer); "
        f"got {sorted(obj.keys())}"
    )


# ==========================================================================
# Behavior 4 --- auto_dispatch_min_score echoes the resolved threshold
# (the Settings default 4.0, as a JSON number).
# ==========================================================================


def test_b04_json_threshold_is_default_number(capsys):
    rc, out, _ = _run(["policy", "--json"], capsys)
    assert rc == 0
    obj = json.loads(out)
    assert obj["auto_dispatch_min_score"] == DEFAULT_THRESHOLD
    assert isinstance(obj["auto_dispatch_min_score"], (int, float)), (
        f"threshold must be a JSON number, not a string; "
        f"got {obj['auto_dispatch_min_score']!r}"
    )


# ==========================================================================
# Behavior 5 --- sensitive_categories is the two defaults, as sorted .value
# strings (never enum reprs).
# ==========================================================================


def test_b05_json_sensitive_categories_sorted_values(capsys):
    rc, out, _ = _run(["policy", "--json"], capsys)
    assert rc == 0
    obj = json.loads(out)
    assert obj["sensitive_categories"] == SENSITIVE_CATEGORIES, (
        f"sensitive_categories must be {SENSITIVE_CATEGORIES}; "
        f"got {obj['sensitive_categories']!r}"
    )


# ==========================================================================
# Behavior 6 --- categories enumerates every GoalCategory exactly once,
# sorted, each object EXACTLY {"category","sensitive"}, with correct flags.
# ==========================================================================


def test_b06_json_categories_complete_sorted_flagged(capsys):
    rc, out, _ = _run(["policy", "--json"], capsys)
    assert rc == 0
    obj = json.loads(out)
    cats = obj["categories"]
    assert isinstance(cats, list), f"categories must be a list; got {type(cats)}"
    # Six objects, each with EXACTLY the two keys.
    for entry in cats:
        assert set(entry.keys()) == {"category", "sensitive"}, (
            f"each category object must have EXACTLY {{'category','sensitive'}}; "
            f"got {sorted(entry.keys())}"
        )
    # Every category exactly once, in ascending order.
    assert [e["category"] for e in cats] == ALL_CATEGORIES, (
        f"category values must be {ALL_CATEGORIES} in ascending order (each once); "
        f"got {[e['category'] for e in cats]}"
    )
    # Sensitivity flags: true only for the two sensitive categories.
    flags = {e["category"]: e["sensitive"] for e in cats}
    for cat, is_sensitive in flags.items():
        expected = cat in SENSITIVE_CATEGORIES
        assert is_sensitive is expected, (
            f"{cat}: sensitive must be {expected}; got {is_sensitive!r}"
        )


# ==========================================================================
# Behavior 7 --- rules narrates the four ordered gate branches (pins the
# load-bearing "first match wins" ordering without over-fixing wording).
# ==========================================================================


def test_b07_json_rules_four_ordered_branches(capsys):
    rc, out, _ = _run(["policy", "--json"], capsys)
    assert rc == 0
    obj = json.loads(out)
    rules = obj["rules"]
    assert isinstance(rules, list) and len(rules) == 4, (
        f"rules must be a list of exactly four strings; got {rules!r}"
    )
    for i, r in enumerate(rules):
        assert isinstance(r, str) and r.strip(), (
            f"rules[{i}] must be a non-empty string; got {r!r}"
        )
    low = [r.lower() for r in rules]
    # Gate order (first match wins): sensitive -> appropriate -> threshold -> approval.
    assert "sensitive" in low[0], f"rules[0] must mention 'sensitive'; got {rules[0]!r}"
    assert "appropriate" in low[1], (
        f"rules[1] must mention 'appropriate'; got {rules[1]!r}"
    )
    assert "threshold" in low[2] and ("auto" in low[2] or "dispatch" in low[2]), (
        f"rules[2] must mention 'threshold' AND ('auto' OR 'dispatch'); got {rules[2]!r}"
    )
    assert "approval" in low[3], f"rules[3] must mention 'approval'; got {rules[3]!r}"


# ==========================================================================
# Behavior 8 --- --json reflects a LIVE env override of the threshold via the
# shared _settings(args) seam (not a hardcoded 4.0).
# ==========================================================================


def test_b08_json_reflects_env_threshold_override(monkeypatch, capsys):
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "6.5")
    rc, out, _ = _run(["policy", "--json"], capsys)
    assert rc == 0
    obj = json.loads(out)
    assert obj["auto_dispatch_min_score"] == 6.5, (
        f"threshold must reflect the PLA_AUTO_DISPATCH_MIN_SCORE=6.5 override; "
        f"got {obj['auto_dispatch_min_score']!r}"
    )


# ==========================================================================
# Behavior 9 --- Human form shows the threshold, every category, the
# sensitivity annotations (only on the two sensitive lines), and the four
# ordered rule concepts.
# ==========================================================================


def test_b09_human_form_full_catalog(capsys):
    rc, out, err = _run(["policy"], capsys)
    assert rc == 0, f"`pla policy` must exit 0; stderr={err!r}"
    # Threshold formatted :.2f
    assert "4.00" in out, f"human form must show the threshold '4.00'; got:\n{out}"
    # Every category value appears.
    for cat in ALL_CATEGORIES:
        assert cat in out, f"human form must list category {cat!r}; got:\n{out}"
    # Sensitivity annotation only on the two sensitive category lines.
    cat_lines = _category_lines(out)
    assert set(cat_lines.keys()) == set(ALL_CATEGORIES), (
        f"expected one catalog line per category; found lines for "
        f"{sorted(cat_lines)}"
    )
    for cat, line in cat_lines.items():
        if cat in SENSITIVE_CATEGORIES:
            assert "sensitive" in line.lower(), (
                f"{cat} line must carry a 'sensitive' annotation; got {line!r}"
            )
        else:
            assert "sensitive" not in line.lower(), (
                f"non-sensitive {cat} line must NOT carry a 'sensitive' annotation; "
                f"got {line!r}"
            )
    # The four ordered rule concepts all appear (case-insensitive).
    low = out.lower()
    for concept in ("sensitive", "appropriate", "threshold", "approval"):
        assert concept in low, (
            f"human form must narrate the {concept!r} gate concept; got:\n{out}"
        )


# ==========================================================================
# Behavior 10 --- Human form reflects the env override: shows '6.50' and NOT
# the default '4.00'.
# ==========================================================================


def test_b10_human_form_reflects_env_override(monkeypatch, capsys):
    monkeypatch.setenv("PLA_AUTO_DISPATCH_MIN_SCORE", "6.5")
    rc, out, err = _run(["policy"], capsys)
    assert rc == 0, f"`pla policy` must exit 0 under env override; stderr={err!r}"
    assert "6.50" in out, f"human form must show the overridden '6.50'; got:\n{out}"
    assert "4.00" not in out, (
        f"human form must NOT still show the default '4.00' under override; got:\n{out}"
    )


# ==========================================================================
# Behavior 11 --- Version unchanged (additive verb, backward compatible).
# (Full-suite green + make demo byte-stability are verified by the tester
# out-of-band; this pins the version invariant in-suite.)
# ==========================================================================


def test_b11_version_unchanged():
    assert __version__ == "0.1.1", (
        f"policy is an additive verb: __version__ must stay '0.1.1'; got {__version__!r}"
    )
