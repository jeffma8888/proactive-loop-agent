"""Black-box behavior tests for factory iteration 131 --- the published state-directory layout.

Feature under test: ``README.md`` gains ONE reference section, ``### What the state
directory contains``, below the human-owned ``PORTFOLIO INTRO`` marker and inside the
``## CLI`` section, documenting the on-disk audit trail a dispatched goal leaves ---
``slate.json`` at the top of the state dir, and ``meta.json`` / ``checkpoint.json`` /
``artifacts/`` inside each ``run-<goal_id>`` dir. The section is held in BIDIRECTIONAL
agreement with the four module-level ``*_NAME`` string constants in
``src/proactive_loop/cli.py``: every constant value must be documented as a
backtick-quoted token, and every backticked ``*.json`` token in the section must be one
of those values, so a documented-but-nonexistent filename fails the build.

ISOLATION CONTRACT (honored): written strictly against this iteration's spec (``pm.md``
"Expected Behaviors" 1-7) plus the conventions of the existing modules under ``tests/``
(``test_readme_and_ci_contract.py`` is the precedent for README-contract guards, and
``test_iter130_behavior.py`` for the module layout). **No file under ``src/`` was read
while writing this module, no engineer / reviewer / fix note was opened, no
``state/iter-124/probe_behaviors.py`` was lifted, and no ``git diff`` was consulted.**
``cli.py`` is opened only MECHANICALLY, by ``ast.parse`` inside the guard itself --- which
is what the spec mandates --- never by eye, and no assertion here encodes anything about
``cli.py`` beyond the names and values of its module-level ``*_NAME`` constants.

Fully offline and deterministic: every assertion is a pure string/``ast`` check over two
files already in the tree. No subprocess, no network, no API key, no sleeps, no
durations, and no temp files.

AMBIGUITY NOTES (PM feedback):

* Behavior 1 says the heading must sit "strictly AFTER the line closing the
  ``PORTFOLIO INTRO`` HTML comment". The spec's *Why* block cites that closing line as
  line 31; at the parent commit it is line **30**. The guard therefore DERIVES the index
  (first ``-->`` at or after the sole ``PORTFOLIO INTRO`` line) instead of hardcoding
  either number, so it cannot rot when the intro is re-wrapped.
* Behavior 2 says the value must appear "as a backtick-quoted token equal to either the
  value itself or the value followed by ``/``". Read strictly: the token is the WHOLE
  span between two backticks, so a cell reading ```run-<goal_id>/meta.json``` would NOT
  satisfy it. That is deliberate --- it is what keeps the check keyed on the constant's
  value rather than on a path a refactor can re-spell.
* Behavior 3's regex ``^[A-Za-z0-9_.-]+\\.json$`` is anchored on the whole token, so
  ``slate-<NNN>.json`` (the ``watch --out-dir`` stream, explicitly out of scope) would
  not match even if it were mentioned. Only bare filenames are policed.
* Behavior 5 says the section must state that ``meta.json``, ``checkpoint.json`` and
  ``artifacts/`` live inside the per-run dir. "States it" is asserted the only decidable
  way: each of those three table rows carries the phrase "in the run dir", while the
  ``slate.json`` row carries "top of the state dir" --- exactly one of each per row, so a
  row cannot be mislabelled without failing.
* Behavior 6 asks for the token ``atomic`` case-insensitively. ``atomically`` contains
  it; the guard accepts the substring (the promise is the same word family) but ALSO
  pins the ``every step`` phrasing, which is the load-bearing half of the claim.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
CLI_SOURCE = REPO / "src" / "proactive_loop" / "cli.py"

SECTION_HEADING = "### What the state directory contains"
NEXT_HEADING = "### Exit codes"
ENCLOSING_H2 = "## CLI"

#: The four module-level string constants in ``cli.py`` whose target names end ``_NAME``.
EXPECTED_CONSTANT_NAMES = frozenset(
    {"_META_NAME", "_CHECKPOINT_NAME", "_ARTIFACTS_NAME", "_SLATE_NAME"}
)

#: Behavior 3: which backticked tokens the reverse guard polices.
_JSON_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]+\.json$")

#: A backtick-quoted token is the whole span between two single backticks on one line.
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


# --------------------------------------------------------------------------- helpers


def _readme_lines() -> list[str]:
    return README.read_text(encoding="utf-8").splitlines()


def _sole_index(lines: list[str], heading: str) -> int:
    """Index of ``heading`` as a standalone line; asserts it appears exactly once."""
    hits = [i for i, line in enumerate(lines) if line.strip() == heading]
    assert len(hits) == 1, f"expected exactly one {heading!r} line in README.md, found {hits}"
    return hits[0]


def _marker_close_index(lines: list[str]) -> int:
    """Index of the line closing the human-owned ``PORTFOLIO INTRO`` HTML comment.

    Derived, never hardcoded: the sole ``PORTFOLIO INTRO`` line, then the first ``-->``
    at or after it.
    """
    starts = [i for i, line in enumerate(lines) if "PORTFOLIO INTRO" in line]
    assert len(starts) == 1, f"expected exactly one PORTFOLIO INTRO line, found {starts}"
    for i in range(starts[0], len(lines)):
        if "-->" in lines[i]:
            return i
    raise AssertionError("PORTFOLIO INTRO comment is never closed with '-->' in README.md")


def _section_body(lines: list[str], heading: str) -> str:
    """Text of the section introduced by ``heading``, up to the next ``##``/``###``."""
    start = _sole_index(lines, heading)
    out: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.lstrip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            break
        out.append(line)
    return "\n".join(out)


def _backtick_tokens(text: str) -> list[str]:
    return _BACKTICK_RE.findall(text)


def _name_constants(source: str) -> dict[str, str]:
    """Module-level ``<NAME>_NAME = "<literal>"`` assignments, found with ``ast``.

    Only module-level assignments of a plain string constant count, and only when the
    target name ends in ``_NAME``. Never a regex over source text (behavior 2).
    """
    found: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id.endswith("_NAME"):
                found[target.id] = value.value
    return found


def _cli_name_constants() -> dict[str, str]:
    return _name_constants(CLI_SOURCE.read_text(encoding="utf-8"))


def _undocumented_json_tokens(section: str, allowed: frozenset[str] | set[str]) -> set[str]:
    """Backticked bare ``*.json`` tokens in ``section`` that are not real filenames.

    This is the reverse-direction guard (behavior 3). It is a pure function of its two
    arguments so behavior 7 can prove it two-sided on synthetic input.
    """
    return {
        token
        for token in _backtick_tokens(section)
        if _JSON_TOKEN_RE.match(token) and token not in allowed
    }


def _constant_drift_message(found: dict[str, str]) -> str:
    """Behavior 4's failure message: name what drifted and what to do about it."""
    unexpected = sorted(set(found) - EXPECTED_CONSTANT_NAMES)
    missing = sorted(EXPECTED_CONSTANT_NAMES - set(found))
    parts = [
        "the module-level *_NAME string constants in src/proactive_loop/cli.py drifted:",
        f"unexpected {unexpected}",
        f"missing {missing}.",
        f"Document it in the README section {SECTION_HEADING!r},",
        "or give the constant a name that does not end in '_NAME'.",
    ]
    return " ".join(parts)


def _table_rows(section: str) -> list[str]:
    """Body rows of the section's markdown table (header and separator dropped)."""
    rows = [line for line in section.splitlines() if line.lstrip().startswith("|")]
    return [row for row in rows[2:]] if len(rows) > 2 else []


def _row_for(section: str, token: str) -> str:
    """The single table row whose first cell documents backticked ``token``."""
    wanted = f"`{token}`"
    hits = [row for row in _table_rows(section) if wanted in row.split("|")[1]]
    assert len(hits) == 1, f"expected exactly one table row whose Path cell holds {wanted}, got {len(hits)}"
    return hits[0]


# ------------------------------------------------------------------ behavior 1


def test_b01_section_exists_exactly_once_below_the_marker_and_above_exit_codes() -> None:
    lines = _readme_lines()
    marker_close = _marker_close_index(lines)
    section = _sole_index(lines, SECTION_HEADING)
    exit_codes = _sole_index(lines, NEXT_HEADING)

    assert marker_close < section, (
        f"{SECTION_HEADING!r} is at line {section + 1}, at or above the human-owned "
        f"PORTFOLIO INTRO marker close at line {marker_close + 1}"
    )
    assert section < exit_codes, (
        f"{SECTION_HEADING!r} (line {section + 1}) must precede {NEXT_HEADING!r} "
        f"(line {exit_codes + 1})"
    )


def test_b01_section_is_inside_the_cli_section() -> None:
    lines = _readme_lines()
    section = _sole_index(lines, SECTION_HEADING)
    h2s = [line.strip() for line in lines[:section] if line.startswith("## ")]
    assert h2s, "no level-2 heading precedes the new section"
    assert h2s[-1] == ENCLOSING_H2, (
        f"the new section must live under {ENCLOSING_H2!r}; the nearest preceding "
        f"level-2 heading is {h2s[-1]!r}"
    )


def test_b01_section_is_a_level_three_heading_with_exact_text() -> None:
    lines = _readme_lines()
    raw = lines[_sole_index(lines, SECTION_HEADING)]
    assert raw == SECTION_HEADING, f"heading line is {raw!r}, expected {SECTION_HEADING!r}"


# ------------------------------------------------------------------ behavior 2


def test_b02_every_cli_name_constant_value_is_a_backticked_token_in_the_section() -> None:
    constants = _cli_name_constants()
    assert constants, "found no module-level *_NAME string constants in cli.py"
    section = _section_body(_readme_lines(), SECTION_HEADING)
    tokens = set(_backtick_tokens(section))

    for name, value in sorted(constants.items()):
        assert value in tokens or f"{value}/" in tokens, (
            f"cli.py's {name} = {value!r} is not documented in {SECTION_HEADING!r}: "
            f"add a backticked `{value}` (or `{value}/`) token to that section"
        )


def test_b02_bare_prose_does_not_satisfy_the_forward_guard() -> None:
    """The token must be backticked: the bare word in prose must not count."""
    constants = _cli_name_constants()
    artifacts = constants["_ARTIFACTS_NAME"]
    prose_only = f"The run writes everything under {artifacts} while the workspace stays read-only."
    tokens = set(_backtick_tokens(prose_only))
    assert artifacts not in tokens and f"{artifacts}/" not in tokens


# ------------------------------------------------------------------ behavior 3


def test_b03_every_documented_json_filename_is_a_real_cli_constant() -> None:
    values = set(_cli_name_constants().values())
    section = _section_body(_readme_lines(), SECTION_HEADING)
    offenders = _undocumented_json_tokens(section, values)
    assert offenders == set(), (
        f"{SECTION_HEADING!r} documents {sorted(offenders)}, which no module-level "
        f"*_NAME constant in cli.py produces (real values: {sorted(values)})"
    )


# ------------------------------------------------------------------ behavior 4


def test_b04_the_set_of_name_constants_is_exactly_the_documented_four() -> None:
    found = _cli_name_constants()
    assert set(found) == set(EXPECTED_CONSTANT_NAMES), _constant_drift_message(found)


def test_b04_drift_message_names_the_constant_and_says_what_to_do() -> None:
    """The failure message must be actionable, so prove it on synthetic drift."""
    drifted = {"_META_NAME": "meta.json", "_SLATE_NAME": "slate.json", "_TRACE_NAME": "trace.json"}
    message = _constant_drift_message(drifted)

    assert "_TRACE_NAME" in message, "the unexpected constant must be named"
    assert "_CHECKPOINT_NAME" in message and "_ARTIFACTS_NAME" in message, (
        "the missing constants must be named"
    )
    assert SECTION_HEADING in message, "the message must point at the README section"
    assert "does not end in '_NAME'" in message, "the message must offer the rename escape hatch"

    clean = _constant_drift_message({name: "x.json" for name in EXPECTED_CONSTANT_NAMES})
    assert "unexpected []" in clean and "missing []" in clean


# ------------------------------------------------------------------ behavior 5


def test_b05_section_names_the_state_dir_default_and_the_run_dir_prefix() -> None:
    section = _section_body(_readme_lines(), SECTION_HEADING)
    assert ".pla_runs" in section, "the section must name the default state dir `.pla_runs`"
    assert "run-" in section, "the section must show the literal `run-` per-run dir prefix"


def test_b05_slate_is_at_the_top_and_the_other_three_are_in_the_run_dir() -> None:
    section = _section_body(_readme_lines(), SECTION_HEADING)
    constants = _cli_name_constants()

    slate_row = _row_for(section, constants["_SLATE_NAME"])
    assert "top of the state dir" in slate_row, (
        f"the {constants['_SLATE_NAME']} row must place it at the top of the state dir: {slate_row!r}"
    )
    assert "in the run dir" not in slate_row

    for name in ("_META_NAME", "_CHECKPOINT_NAME"):
        row = _row_for(section, constants[name])
        assert "in the run dir" in row, f"the {constants[name]} row must place it in the run dir"
        assert "top of the state dir" not in row

    artifacts_row = _row_for(section, f"{constants['_ARTIFACTS_NAME']}/")
    assert "in the run dir" in artifacts_row
    assert "top of the state dir" not in artifacts_row

    assert section.count("in the run dir") == 3, (
        "exactly the three per-run artifacts may be labelled 'in the run dir'"
    )
    assert section.count("top of the state dir") == 1, (
        "exactly one path may be labelled 'top of the state dir'"
    )


# ------------------------------------------------------------------ behavior 6


def test_b06_section_states_the_durability_promise_checkably() -> None:
    section = _section_body(_readme_lines(), SECTION_HEADING)
    lowered = section.lower()

    assert "atomic" in lowered, "the section must describe the checkpoint write as atomic"
    assert "every step" in lowered, "the section must say the checkpoint is written after every step"
    assert "meta.json" in set(_backtick_tokens(section)), (
        "the section must document `meta.json` as a backticked token"
    )


# ------------------------------------------------------------------ behavior 7


def test_b07_reverse_guard_fires_on_a_documented_but_nonexistent_filename() -> None:
    allowed = set(_cli_name_constants().values())
    synthetic_bad = (
        "| Path | Contents |\n"
        "|------|----------|\n"
        "| `checkpoints.json` -- in the run dir | a filename this product never writes |\n"
    )
    assert _undocumented_json_tokens(synthetic_bad, allowed) == {"checkpoints.json"}


def test_b07_reverse_guard_passes_on_a_section_naming_only_real_values() -> None:
    constants = _cli_name_constants()
    allowed = set(constants.values())
    synthetic_good = "\n".join(
        f"| `{constants[name]}` | real | " for name in sorted(EXPECTED_CONSTANT_NAMES)
    )
    assert _undocumented_json_tokens(synthetic_good, allowed) == set()


def test_b07_reverse_guard_ignores_non_json_and_suffixed_tokens() -> None:
    """Only bare ``*.json`` tokens are policed --- see the behavior-3 ambiguity note."""
    allowed = set(_cli_name_constants().values())
    noise = "`--run-dir` `.pla_runs` `run-<goal_id>` `slate-<NNN>.json` `ranked()`"
    assert _undocumented_json_tokens(noise, allowed) == set()
