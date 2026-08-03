"""Black-box behavior tests for commit-seq factory iter 93 (state-dir iter-83).

Feature under test (pm.md / SPEC CHECK-contract fail-safe block): a genuine JSON
boolean ``done`` is REQUIRED to complete an L1 run in ``GoalLoop._parse_check``.
A present-but-non-boolean ``done`` (a quoted ``"false"``/``"no"`` string, an int,
``null``, ...) is a GARBLED verdict routed through the SAME CHECK fail-safe path as
unparseable JSON: read as not-done (``done is False``) and degradation-flagged
(``parsed_ok is False``) with a DISTINCT corrective observation ``_CHECK_BAD_DONE``,
instead of being coerced to ``True`` by ``bool()`` and FALSELY completing an
unfinished autonomous run. Genuine booleans are unchanged: ``true`` completes;
``false`` and an ABSENT ``done`` stay non-degradation honest not-yets. The two
pre-existing garbled branches (unparseable JSON, non-dict JSON) keep the DISTINCT
``_CHECK_PARSE_ERROR`` observation.

ISOLATION CONTRACT (honored): these tests drive ONLY the public test seam --
the ``@staticmethod`` ``GoalLoop._parse_check(raw)`` called directly (no loop /
state / CLI harness needed) -- plus the public registries (``all_collectors()`` /
``ToolRegistry`` / ``VALID_PROVIDERS`` / ``build_parser`` / ``__version__``) for the
no-drift check. The two corrective-observation constants are imported for
exact-match asserts. No file under ``src/`` was read, no engineer/reviewer notes
were read, and no ``git diff`` was consulted; the assertions encode pm.md's
Expected Behaviors, not the implementation.

File naming: the prompt's state-dir iteration is 83, but ``tests/test_iter83_
behavior.py`` already exists (an earlier commit-seq iteration; the +10 state-dir
offset since iter-78). The repo names behavior files after the COMMIT SEQUENCE,
which for this iteration is factory iter 93 (pm.md header + ROADMAP row #93);
``test_iter93_behavior.py`` was confirmed unused before creation.
"""

from __future__ import annotations

from proactive_loop import __version__
from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.executor import (
    GoalLoop,
    _CHECK_BAD_DONE,
    _CHECK_PARSE_ERROR,
)
from proactive_loop.loop.tools import ToolRegistry


# --- Behaviors 1-5: PRESENT-but-non-boolean done -> garbled verdict (the bug) ---


def test_b1_string_false_is_garbled_not_completion():
    """B1 (THE BUG, load-bearing): a quoted string "false" must NOT complete the
    run. Before the fix bool("false") -> True falsely marked the run DONE."""
    done, reason, parsed_ok = GoalLoop._parse_check(
        '{"done": "false", "reason": "not yet"}'
    )
    assert done is False, "a string 'false' must be read as NOT done"
    assert parsed_ok is False, "a present-but-non-boolean done must be a degradation"
    assert reason == _CHECK_BAD_DONE, (
        "a non-boolean done must yield the distinct _CHECK_BAD_DONE observation, "
        f"got {reason!r}"
    )


def test_b2_string_no_is_garbled():
    """B2: a quoted string "no" (no reason key) -> garbled verdict."""
    done, reason, parsed_ok = GoalLoop._parse_check('{"done": "no"}')
    assert done is False
    assert parsed_ok is False
    assert reason == _CHECK_BAD_DONE


def test_b3_int_one_is_garbled_proves_isinstance_bool_not_int():
    """B3 (bool-is-int subtlety, discriminating): int 1 must be REJECTED as a
    non-boolean garbled verdict. In Python bool subclasses int, so this proves the
    guard uses isinstance(x, bool), not isinstance(x, int) (an int check would
    wrongly ACCEPT 1 and complete the run). Before the fix bool(1) -> True."""
    done, reason, parsed_ok = GoalLoop._parse_check('{"done": 1}')
    assert done is False, "int 1 must NOT complete the run (isinstance bool, not int)"
    assert parsed_ok is False
    assert reason == _CHECK_BAD_DONE


def test_b4_int_zero_is_garbled():
    """B4: int 0 is still a non-boolean garbled verdict -> degradation, even though
    its coerced value was already not-done."""
    done, reason, parsed_ok = GoalLoop._parse_check('{"done": 0}')
    assert done is False
    assert parsed_ok is False
    assert reason == _CHECK_BAD_DONE


def test_b5_present_null_is_garbled_discriminating_vs_absent():
    """B5 (discriminating vs absent, B8): a PRESENT null done is a garbled verdict
    -> degradation. Contrast B8 where an ABSENT done stays a non-degradation."""
    done, reason, parsed_ok = GoalLoop._parse_check('{"done": null}')
    assert done is False
    assert parsed_ok is False
    assert reason == _CHECK_BAD_DONE


# --- Behaviors 6-8: genuine boolean / absent done unchanged (load-bearing) ---


def test_b6_genuine_true_still_completes():
    """B6 (MUST still complete, load-bearing): a genuine JSON boolean true completes
    the run with the model's reason and parsed_ok True."""
    done, reason, parsed_ok = GoalLoop._parse_check('{"done": true, "reason": "ok"}')
    assert done is True, "a genuine boolean true must complete the run"
    assert reason == "ok", "the model's reason must be preserved on completion"
    assert parsed_ok is True


def test_b7_genuine_false_stays_non_degradation():
    """B7 (MUST stay NON-degradation, load-bearing): a genuine boolean false is an
    HONEST not-yet -- NOT a degradation. parsed_ok stays True and the reason is the
    model's, distinct from _CHECK_BAD_DONE (SPEC 'never on a well-formed done:false'
    invariant preserved)."""
    done, reason, parsed_ok = GoalLoop._parse_check(
        '{"done": false, "reason": "not yet"}'
    )
    assert done is False
    assert reason == "not yet", "the model's reason must be preserved"
    assert parsed_ok is True, "a well-formed done:false must NOT be a degradation"
    assert reason != _CHECK_BAD_DONE, "an honest not-yet is not a garbled verdict"


def test_b8_absent_done_stays_non_degradation():
    """B8 (NON-degradation, unchanged; discriminating vs present-null B5): an ABSENT
    done defaults to the genuine bool False, which passes the isinstance check, so it
    stays a non-degradation honest not-yet -- no separate '"done" not in data' branch
    was added."""
    done, reason, parsed_ok = GoalLoop._parse_check('{"reason": "working"}')
    assert done is False
    assert reason == "working"
    assert parsed_ok is True, "an absent done must stay a non-degradation not-yet"
    assert reason != _CHECK_BAD_DONE


# --- Behaviors 9-10: pre-existing garbled branches keep the DISTINCT observation ---


def test_b9_unparseable_json_keeps_distinct_parse_error():
    """B9: unparseable JSON keeps the DISTINCT _CHECK_PARSE_ERROR observation, and
    the two garbled-verdict classes have distinct corrective observations."""
    done, reason, parsed_ok = GoalLoop._parse_check("not json at all")
    assert done is False
    assert parsed_ok is False
    assert reason == _CHECK_PARSE_ERROR
    assert _CHECK_BAD_DONE != _CHECK_PARSE_ERROR, (
        "the non-boolean-done and unparseable-JSON verdicts must be distinct "
        "corrective observations"
    )


def test_b10_non_dict_json_unchanged():
    """B10: a JSON array (valid JSON but not a dict) keeps _CHECK_PARSE_ERROR."""
    done, reason, parsed_ok = GoalLoop._parse_check("[1, 2, 3]")
    assert done is False
    assert parsed_ok is False
    assert reason == _CHECK_PARSE_ERROR


# --- Behavior 11: no regression / no drift ---


def test_b11_bad_done_observation_mentions_boolean():
    """B11: the new _CHECK_BAD_DONE corrective observation names the required type
    ('boolean') so the fed-back nudge tells the model the contract."""
    assert "boolean" in _CHECK_BAD_DONE, (
        f"_CHECK_BAD_DONE must mention 'boolean', got {_CHECK_BAD_DONE!r}"
    )


def test_b11_collector_count_unchanged():
    assert len(all_collectors()) == 15, "collector set changed (expected 15)"


def test_b11_tool_count_unchanged():
    assert len(ToolRegistry.tool_names()) == 14, "tool set changed (expected 14)"


def test_b11_provider_count_unchanged():
    assert len(VALID_PROVIDERS) == 7, "provider set changed (expected 7)"


def test_b11_verb_count_unchanged():
    subactions = [
        a for a in build_parser()._subparsers._group_actions if hasattr(a, "choices")
    ]
    assert subactions, "no subparser choices found"
    assert len(subactions[0].choices) == 14, "CLI verb set changed (expected 14)"


def test_b11_version_unchanged():
    assert __version__ == "0.1.1", f"unexpected version bump: {__version__!r}"
