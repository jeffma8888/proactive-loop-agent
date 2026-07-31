"""Black-box behavior tests for iteration 50.

Feature under test: ``parse_json_block(text)`` -- the single choke point where
free-form model text becomes structured data for BOTH the L2 synthesizer (goal
array) and the L1 goal loop (PLAN/CHECK objects). ``SPEC.md`` §3 names it a
load-bearing foundation contract:

    "``parse_json_block`` tolerates ```json fences, leading/trailing prose, and
    trailing junk after a valid value (e.g. a stray brace) via ``raw_decode``."

Its **fence-fallback** branch -- reached only when the earliest ``{``/``[`` is a
non-JSON brace *in prose* and the real JSON lives inside a later ```` ```json ````
fence -- is the one branch a live model can trip yet no test exercised (missed
across all prior tests). A future "simplify the parser" refactor could silently
break the loop's ability to recover garbled model output while every other test
stayed green. This suite PINS the full decode-branch matrix so such a regression
turns RED. It is a test-only hardening pin (the iter-31 / iter-35 / iter-47
pattern): it proves EXISTING behavior and changes nothing under ``src/``.

ISOLATION STATEMENT: these tests were written strictly against the PUBLIC
contract -- this iteration's Expected Behaviors (``pm.md``), ``README.md``, and
``SPEC.md`` §3 -- and exercise ONLY the documented public function
``parse_json_block``, imported from BOTH documented paths. No file under ``src/``
was read, no engineer/reviewer notes for this iteration were consulted, and no
``git diff`` was inspected. This is an INDEPENDENT, spec-derived encoding of the
contract, not a mirror of the implementation. Every input/output was re-verified
against live source before asserting, and every fence/last-resort case is
guarded to PROVE the primary ``raw_decode`` step is genuinely forced to fail
(the standing iter-47/49 footgun: a case whose earliest brace accidentally
decodes at step 1 would test nothing). Everything runs fully offline: NO network,
NO API keys, NO CLI subprocess, NO filesystem.
"""

from __future__ import annotations

import json

import pytest

# Documented public surface, imported from BOTH paths named in the spec.
from proactive_loop.llm import parse_json_block as parse_json_block_pkg
from proactive_loop.llm.client import parse_json_block


# ---------------------------------------------------------------------------
# Footgun guard (spec Acceptance Criterion): prove an input's earliest brace does
# NOT self-decode, so the fence/last-resort branch is genuinely the one exercised.
# Mirrors SPEC §3's documented primary step (raw_decode from the earliest brace),
# using only the stdlib -- no src/ read.
# ---------------------------------------------------------------------------
_DECODER = json.JSONDecoder()


def _primary_raw_decode_fails(text: str) -> bool:
    """True iff the documented primary step (raw_decode from the earliest
    ``{``/``[``) fails on ``text`` -- i.e. the fence branch must be reached."""
    idxs = [i for i in (text.find("{"), text.find("[")) if i != -1]
    assert idxs, "guard misuse: input has no brace (fence branch unreachable)"
    start = min(idxs)
    try:
        _DECODER.raw_decode(text, start)
    except ValueError:
        return True
    return False


def _no_brace(text: str) -> bool:
    """True iff there is no ``{``/``[`` -- primary AND fence branches are skipped
    and the last-resort whole-string ``json.loads`` is the only path."""
    return "{" not in text and "[" not in text


# ---------------------------------------------------------------------------
# Behavior 0 -- both documented import paths resolve to the same function.
# ---------------------------------------------------------------------------


def test_behavior_0_both_import_paths_are_the_same_function() -> None:
    """``proactive_loop.llm`` re-exports the exact object from
    ``proactive_loop.llm.client`` (the spec names both paths)."""
    assert parse_json_block is parse_json_block_pkg


# ---------------------------------------------------------------------------
# Behavior 1 -- primary decode tolerates trailing junk after a complete value.
# Branch 1: raw_decode from the leading brace consumes the value, ignores rest
# (SPEC §3 stray-brace case).
# ---------------------------------------------------------------------------


def test_behavior_1_primary_decode_ignores_trailing_junk() -> None:
    text = '{"done": true, "reason": "ok"}}} }'
    assert parse_json_block(text) == {"done": True, "reason": "ok"}


# ---------------------------------------------------------------------------
# Behavior 2 -- fence-fallback, clean JSON inside the fence.
# Branch 2, first fence attempt: json.loads(fenced). The earliest `{` is a
# non-JSON brace in the prose, so the primary raw_decode FAILS and the fenced
# block is used. (The previously-untested branch -- core of this iteration.)
# ---------------------------------------------------------------------------


def test_behavior_2_fence_fallback_clean_json_inside_fence() -> None:
    text = "Note: use { to open a block.\n```json\n{\"done\": true, \"reason\": \"ok\"}\n```"
    # Guard: the prose `{` genuinely defeats the primary step, forcing the fence.
    assert _primary_raw_decode_fails(text), "primary must fail for the fence branch to be tested"
    assert parse_json_block(text) == {"done": True, "reason": "ok"}


# ---------------------------------------------------------------------------
# Behavior 3 -- fence-fallback where json.loads(fenced) fails but
# raw_decode(fenced) wins.
# Branch 2, second fence attempt: primary fails on the prose brace; json.loads
# of the fenced content fails on its trailing junk; raw_decode of the fenced
# content recovers the leading object.
# ---------------------------------------------------------------------------


def test_behavior_3_fence_fallback_raw_decode_of_fenced_content() -> None:
    text = "Prose with a bare { brace.\n```\n{\"tool\": \"write_file\"} trailing junk\n```"
    assert _primary_raw_decode_fails(text), "primary must fail for the fence branch to be tested"
    # Independently pin the fenced-content sub-branch shape the spec describes:
    fenced = '{"tool": "write_file"} trailing junk'
    with pytest.raises(ValueError):
        json.loads(fenced)  # first fence attempt fails on the trailing junk
    assert _DECODER.raw_decode(fenced)[0] == {"tool": "write_file"}  # second wins
    # The public function must recover the leading fenced object.
    assert parse_json_block(text) == {"tool": "write_file"}


# ---------------------------------------------------------------------------
# Behavior 4 -- PRIMARY-BEFORE-FENCE precedence.
# Branch 1 wins: an embedded ```python fence living inside a JSON string VALUE
# must NOT be mistaken for the wrapper. The leading `{` decodes the whole object
# at step 1, so the fence branch is never entered.
# ---------------------------------------------------------------------------


def test_behavior_4_primary_before_fence_embedded_fence_in_value() -> None:
    original = {"tool": "write_file", "args": {"content": "# Title\n```python\nprint(1)\n```\n"}}
    # Build with real JSON escaping (a literal newline in a JSON string is invalid).
    text = json.dumps(original)
    # Guard the OPPOSITE of the fence cases: the leading `{` DOES decode at step 1,
    # so the primary branch is the one that wins (fence never used).
    assert not _primary_raw_decode_fails(text), "primary must decode at step 1 for this precedence test"
    assert parse_json_block(text) == original


# ---------------------------------------------------------------------------
# Behavior 5 -- last-resort whole-string json.loads for a top-level scalar.
# Branch 3: no `{`/`[` and no fence, so the primary and fence branches are
# skipped and json.loads(stripped) handles the bare scalar.
# ---------------------------------------------------------------------------


def test_behavior_5_last_resort_scalar_number_string_bool_null() -> None:
    for scalar in ("42", '"hello"', "true", "null"):
        assert _no_brace(scalar), "scalar must have no brace so the last-resort branch is exercised"
    assert parse_json_block("42") == 42
    assert parse_json_block('"hello"') == "hello"
    # Extra spec-listed scalars (bool + null) for completeness of the branch.
    assert parse_json_block("true") is True
    assert parse_json_block("null") is None


# ---------------------------------------------------------------------------
# Behavior 6 -- total failure raises ValueError when nothing parses.
# 6a: no brace/fence -> last-resort json.loads fails -> raise.
# 6b: prose brace defeats primary; BOTH fence attempts fail on non-JSON fence
#     content; last-resort json.loads of the whole string fails -> raise. This
#     input exercises the fence branch's failure path AND the final raise.
# ---------------------------------------------------------------------------


def test_behavior_6a_total_failure_no_json_raises_valueerror() -> None:
    text = "this is not json at all"
    assert _no_brace(text)
    with pytest.raises(ValueError):
        parse_json_block(text)


def test_behavior_6b_fence_branch_all_attempts_fail_raises_valueerror() -> None:
    text = "bare { brace\n```\nnot json here\n```"
    assert _primary_raw_decode_fails(text), "primary must fail so the fence-failure path is reached"
    # Independently pin that BOTH fence attempts fail on the non-JSON fence body.
    fenced = "not json here"
    with pytest.raises(ValueError):
        json.loads(fenced)
    with pytest.raises(ValueError):
        _DECODER.raw_decode(fenced)
    with pytest.raises(ValueError):
        parse_json_block(text)


# ---------------------------------------------------------------------------
# Behavior 7 -- the failure message is bounded to text[:200].
# Pins the truncation bound so the error can never dump an unbounded model blob.
# (Last-resort branch: a repeated non-JSON char has no brace/fence and fails.)
# ---------------------------------------------------------------------------


def test_behavior_7_failure_message_bounded_to_first_200_chars() -> None:
    text = "q" * 500
    assert _no_brace(text)
    with pytest.raises(ValueError) as excinfo:
        parse_json_block(text)
    message = str(excinfo.value)
    # The first 200 chars are present; the 201st repetition is NOT -> text[:200].
    assert ("q" * 200) in message, "message must contain the first 200 chars of the input"
    assert ("q" * 201) not in message, "message must be truncated at text[:200] (no 201st char)"
