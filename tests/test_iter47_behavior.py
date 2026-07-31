"""Black-box behavior tests for iteration 47.

Feature under test: the ``ScriptedLLMClient.complete()`` runtime contract -- the
single offline seam that ``SPEC.md`` §5 names as "what makes the product
offline-testable end to end" and §3 documents as a load-bearing invariant every
higher layer depends on:

    "``ScriptedLLMClient`` matches on ``tag`` (exact match, else entries with tag
    ``""`` match anything), consumes entries in order, supports scripted failures
    via ``{"raise": ...}``, raises ``ScriptExhaustedError`` when empty."

That contract had NO focused test before this iteration -- higher-level suites
exercise ``complete()`` only incidentally with exact-or-empty tags that never
probe the ``""``-wildcard / first-match-wins matching, the exhaustion message, or
the unknown-raise-kind branch. A refactor could silently break those subtleties
while every exact-tag behavior test stayed green. This suite PINS the invariant so
such a regression turns RED. It is a test-only hardening pin (the iter-31 / iter-35
pattern): it proves EXISTING behavior and changes nothing under ``src/``.

ISOLATION STATEMENT: these tests were written strictly against the PUBLIC contract
-- this iteration's Expected Behaviors (``pm.md``), ``README.md``, and ``SPEC.md``
§3/§5 -- and exercise ONLY the documented public surface exported from
``proactive_loop.llm.client``: the ``ScriptedLLMClient(entries)`` constructor,
``.complete(system=, prompt=, tag=)``, ``.remaining()``, the ``.calls`` list, the
``LLMResponse`` dataclass, and the exception types ``LLMError`` /
``LLMThrottleError`` / ``LLMTimeoutError`` / ``ScriptExhaustedError``. No file under
``src/`` was read, no engineer/reviewer notes were consulted, and no ``git diff``
was inspected. This is an INDEPENDENT, spec-derived encoding of the contract, not a
mirror of the implementation. Everything runs fully offline: NO network, NO API
keys, NO CLI subprocess, NO filesystem -- every client is built from an in-memory
``list[dict]`` (never ``from_file``). ``system`` and ``prompt`` are always passed as
non-empty placeholder strings (required kwargs, irrelevant to matching).
"""

from __future__ import annotations

import pytest

from proactive_loop.llm.client import (
    LLMError,
    LLMResponse,
    LLMThrottleError,
    LLMTimeoutError,
    ScriptExhaustedError,
    ScriptedLLMClient,
)

# Non-empty placeholders for the required (matching-irrelevant) kwargs.
_SYS = "system placeholder"
_PROMPT = "prompt placeholder"


# ---------------------------------------------------------------------------
# Behavior 1 -- In-order (FIFO) consumption of same-tag entries.
# ---------------------------------------------------------------------------


def test_behavior_1_fifo_same_tag_consumption() -> None:
    """Two same-tag entries are returned in order, decrementing remaining()."""
    client = ScriptedLLMClient(
        [{"tag": "plan", "text": "A"}, {"tag": "plan", "text": "B"}]
    )
    assert client.remaining() == 2

    first = client.complete(system=_SYS, prompt=_PROMPT, tag="plan")
    assert isinstance(first, LLMResponse)
    assert first.text == "A"
    assert client.remaining() == 1

    second = client.complete(system=_SYS, prompt=_PROMPT, tag="plan")
    assert isinstance(second, LLMResponse)
    assert second.text == "B"
    assert client.remaining() == 0

    # Every requested tag is recorded, in order, one entry per call.
    assert client.calls == ["plan", "plan"]


# ---------------------------------------------------------------------------
# Behavior 2 -- The "" (empty) tag is a wildcard that serves ANY requested tag.
# ---------------------------------------------------------------------------


def test_behavior_2_empty_tag_is_wildcard_for_any_tag() -> None:
    """A lone ``tag: ""`` entry answers whatever tag is requested."""
    client_plan = ScriptedLLMClient([{"tag": "", "text": "W"}])
    assert client_plan.complete(system=_SYS, prompt=_PROMPT, tag="plan").text == "W"

    # A fresh client with the SAME single wildcard entry serves a DIFFERENT tag,
    # proving the match is on the wildcard, not on the tag string "plan".
    client_check = ScriptedLLMClient([{"tag": "", "text": "W"}])
    assert client_check.complete(system=_SYS, prompt=_PROMPT, tag="check").text == "W"


# ---------------------------------------------------------------------------
# Behavior 3 -- First-match-wins across mixed wildcard + exact entries.
# ---------------------------------------------------------------------------


def test_behavior_3_first_match_wins_wildcard_before_exact() -> None:
    """An EARLIER wildcard is consumed before a LATER exact-tag match."""
    client = ScriptedLLMClient(
        [{"tag": "", "text": "WILD"}, {"tag": "plan", "text": "EXACT"}]
    )
    # The wildcard sits first, so it -- not the later exact "plan" -- is served.
    first = client.complete(system=_SYS, prompt=_PROMPT, tag="plan")
    assert first.text == "WILD"
    assert client.remaining() == 1

    # Only the exact-tag entry remains; the next call returns it.
    second = client.complete(system=_SYS, prompt=_PROMPT, tag="plan")
    assert second.text == "EXACT"


# ---------------------------------------------------------------------------
# Behavior 4 -- Scripted throttle failure raises LLMThrottleError, consumes entry.
# ---------------------------------------------------------------------------


def test_behavior_4_scripted_throttle_raises_and_consumes() -> None:
    """``{"raise": "throttle"}`` raises LLMThrottleError (an LLMError) and the
    raising entry is consumed, so an L0 retry advances the script."""
    client = ScriptedLLMClient([{"tag": "plan", "raise": "throttle"}])
    with pytest.raises(LLMThrottleError) as excinfo:
        client.complete(system=_SYS, prompt=_PROMPT, tag="plan")
    # LLMThrottleError is a retryable LLMError.
    assert isinstance(excinfo.value, LLMError)
    # The entry was consumed BEFORE the raise.
    assert client.remaining() == 0


# ---------------------------------------------------------------------------
# Behavior 5 -- Scripted timeout failure raises LLMTimeoutError.
# ---------------------------------------------------------------------------


def test_behavior_5_scripted_timeout_raises() -> None:
    """``{"raise": "timeout"}`` raises LLMTimeoutError (an LLMError)."""
    client = ScriptedLLMClient([{"tag": "plan", "raise": "timeout"}])
    with pytest.raises(LLMTimeoutError) as excinfo:
        client.complete(system=_SYS, prompt=_PROMPT, tag="plan")
    assert isinstance(excinfo.value, LLMError)


# ---------------------------------------------------------------------------
# Behavior 6 -- Unknown raise kind -> plain ValueError (NOT an LLMError), consumes.
# ---------------------------------------------------------------------------


def test_behavior_6_unknown_raise_kind_is_plain_valueerror() -> None:
    """An unrecognized ``raise`` kind must surface as a plain ``ValueError`` that
    is NOT an ``LLMError`` -- so it is never silently treated as a retryable
    throttle/timeout -- and the entry is still consumed."""
    client = ScriptedLLMClient([{"tag": "plan", "raise": "boom"}])
    with pytest.raises(ValueError) as excinfo:
        client.complete(system=_SYS, prompt=_PROMPT, tag="plan")
    # Pin that it is NOT retryable: a bad script must fail loud, not loop.
    assert not isinstance(excinfo.value, LLMError), (
        "an unknown raise kind must be a plain ValueError, never an LLMError "
        f"(would be silently retried); got {type(excinfo.value).__name__}"
    )
    assert client.remaining() == 0


# ---------------------------------------------------------------------------
# Behavior 7 -- Exhaustion on an empty script; tag is recorded even on raise.
# ---------------------------------------------------------------------------


def test_behavior_7_exhaustion_empty_script_names_tag_and_count() -> None:
    """An empty script raises ScriptExhaustedError (an LLMError) whose message
    names the requested tag and the remaining count; the tag is still appended to
    ``calls`` even though the call raised.

    Message assertions are SUBSTRING-ONLY (tag text + count), per the spec's
    iter-08 tolerant discipline -- a future wording tweak must not rot this test.
    """
    client = ScriptedLLMClient([])
    with pytest.raises(ScriptExhaustedError) as excinfo:
        client.complete(system=_SYS, prompt=_PROMPT, tag="plan")
    assert isinstance(excinfo.value, LLMError)

    message = str(excinfo.value)
    assert "plan" in message, f"exhaustion message must name the tag, got: {message!r}"
    assert "0" in message, f"exhaustion message must name the count, got: {message!r}"

    # The tag is recorded on the raising call too.
    assert client.calls == ["plan"]


# ---------------------------------------------------------------------------
# Behavior 8 -- Exhaustion on a non-matching exact tag leaves the entry in place.
# ---------------------------------------------------------------------------


def test_behavior_8_exhaustion_nonmatching_tag_does_not_consume() -> None:
    """When no entry matches the requested tag, ScriptExhaustedError is raised and
    the non-matching entry is LEFT IN PLACE (remaining() unchanged).

    Message assertions are SUBSTRING-ONLY (tag text + count), per the spec.
    """
    client = ScriptedLLMClient([{"tag": "check", "text": "C"}])
    with pytest.raises(ScriptExhaustedError) as excinfo:
        client.complete(system=_SYS, prompt=_PROMPT, tag="plan")

    message = str(excinfo.value)
    assert "plan" in message, f"exhaustion message must name the tag, got: {message!r}"
    assert "1" in message, (
        f"exhaustion message must name the remaining count 1, got: {message!r}"
    )

    # The non-matching "check" entry was not consumed.
    assert client.remaining() == 1


# ---------------------------------------------------------------------------
# Behavior 9 -- Missing "text" defaults to "", response identifies as "scripted".
# ---------------------------------------------------------------------------


def test_behavior_9_missing_text_defaults_empty_model_scripted() -> None:
    """An entry with no ``text`` key yields an empty-string response text, and the
    response's model is the scripted double's name."""
    client = ScriptedLLMClient([{"tag": "plan"}])
    resp = client.complete(system=_SYS, prompt=_PROMPT, tag="plan")
    assert isinstance(resp, LLMResponse)
    assert resp.text == ""
    assert resp.model == "scripted"


# ---------------------------------------------------------------------------
# Behavior 10 -- A non-string "text" value is coerced to its str() form.
# ---------------------------------------------------------------------------


def test_behavior_10_non_string_text_is_coerced_to_str() -> None:
    """A non-string ``text`` (here an int) is returned as its ``str()`` form, never
    as a raw non-string -- downstream JSON parsing always sees text."""
    client = ScriptedLLMClient([{"tag": "plan", "text": 123}])
    resp = client.complete(system=_SYS, prompt=_PROMPT, tag="plan")
    assert isinstance(resp.text, str)
    assert resp.text == "123"
