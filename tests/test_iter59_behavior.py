"""Black-box behavior tests for iteration 59.

Feature under test: the shared ``_SdkAdapter.complete`` retry-taxonomy seam --
the single point where every live provider's SDK throttle/timeout exception is
translated into the retryable ``LLMThrottleError`` / ``LLMTimeoutError`` that the
L0 self-healing layer (``with_retry``, SPEC section 4.4) keys on. Per SPEC
section 4.2, each live backend routes its SDK-specific throttle/timeout error
types through this ONE shared adapter; if the translation silently breaks (a
reordered ``except``, a swapped raise-type, a widened ``except Exception`` that
swallows a non-retryable fault, or losing the "throttle checked before timeout"
ordering), L0 resilience dies for every live provider and the failure surfaces
only against a real rate-limited API in production -- never offline. This module
pins that seam through the public ``ollama`` provider path, which exercises the
SAME shared adapter all five live backends use.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's PM spec "Expected Behaviors" 1-6,
``README.md``, and ``SPEC.md`` (the public design contract, esp. section 4.2) --
and drive ONLY the documented public surface: ``create_client(Settings(...))``
and ``VALID_PROVIDERS`` (from ``proactive_loop.llm.providers``) and the public
error/response types ``LLMResponse`` / ``LLMError`` / ``LLMThrottleError`` /
``LLMTimeoutError`` (from ``proactive_loop.llm.client``). NO file under ``src/``
was read, no engineer/reviewer notes were consulted, and no ``git diff`` was
inspected. The private ``_SdkAdapter`` / ``_CompleteFn`` / ``_attr_or_key``
symbols are NOT imported -- the pin is expressed purely at the public
``create_client`` + ``.complete()`` contract level. A self-contained in-memory
``ollama`` stub (the iter-32 / iter-49 discipline) is injected via
``monkeypatch.setitem(sys.modules, "ollama", stub)`` so construction and
``.complete()`` touch ONLY the ``ollama`` namespace -- ZERO real provider SDK,
no network, no API key -- and the suite runs from a cold ``uv sync`` clone.
"""

from __future__ import annotations

import sys
import types

import pytest

from proactive_loop.config import Settings
from proactive_loop.llm.client import (
    LLMError,
    LLMResponse,
    LLMThrottleError,
    LLMTimeoutError,
)
from proactive_loop.llm.providers import VALID_PROVIDERS, create_client


# ---------------------------------------------------------------------------
# Offline harness: a self-contained in-memory ``ollama`` SDK stub.
#
# Exposes EXACTLY the three attributes the ollama branch references:
#   * ``Client``        -- zero-arg-tolerant ctor; ``.chat`` delegates to a
#                          per-case ``_chat_impl`` and RECORDS every call (so
#                          Behavior 6 can assert forwarding + call-count).
#   * ``ResponseError`` -- Exception subclass wired into ``throttle_excs``.
#   * ``RequestError``  -- Exception subclass wired into ``timeout_excs``.
# It imports nothing else, so passing tests prove the adapter touches only the
# ``ollama`` namespace (no second SDK, no network, no key).
# ---------------------------------------------------------------------------


def _make_ollama_stub() -> types.ModuleType:
    stub = types.ModuleType("ollama")
    stub.calls = []  # list of (args, kwargs) per .chat() invocation

    class ResponseError(Exception):
        pass

    class RequestError(Exception):
        pass

    class Client:
        # Zero required args per the spec; tolerant of anything the adapter
        # passes at construction. ``.chat`` is only reached at ``.complete``.
        def __init__(self, *args, **kwargs) -> None:
            pass

        def chat(self, *args, **kwargs):
            stub.calls.append((args, kwargs))
            return stub._chat_impl(*args, **kwargs)

    def _default_chat_impl(*args, **kwargs):  # pragma: no cover - always overridden
        raise AssertionError("test must set stub._chat_impl before .complete()")

    stub.ResponseError = ResponseError
    stub.RequestError = RequestError
    stub.Client = Client
    stub._chat_impl = _default_chat_impl
    return stub


def _install_ollama(monkeypatch) -> types.ModuleType:
    """Inject a fresh ``ollama`` stub and return it (cases stay independent)."""
    stub = _make_ollama_stub()
    monkeypatch.setitem(sys.modules, "ollama", stub)
    return stub


def _ollama_success_response(content: str = "hello"):
    """An ollama-shaped success object exposing the reply at ``.message.content``."""
    return types.SimpleNamespace(message=types.SimpleNamespace(content=content))


def _all_string_values(obj) -> list[str]:
    """Recursively collect every ``str`` VALUE from nested dict/list/tuple."""
    out: list[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_all_string_values(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_all_string_values(v))
    return out


# ===========================================================================
# Behavior 1 -- Throttle translation.
#   .chat raises ollama.ResponseError -> .complete raises LLMThrottleError with
#   the SAME message and __cause__ IS the original exception instance
#   (i.e. `raise LLMThrottleError(str(exc)) from exc`).
# ===========================================================================


def test_behavior1_throttle_translation(monkeypatch):
    stub = _install_ollama(monkeypatch)
    original = stub.ResponseError("rate limited")

    def chat(*args, **kwargs):
        raise original

    stub._chat_impl = chat

    client = create_client(Settings(provider="ollama"))
    with pytest.raises(LLMThrottleError) as excinfo:
        client.complete(system="s", prompt="p", tag="plan")

    err = excinfo.value
    assert str(err) == "rate limited", (
        f"the translated throttle must carry the original message; got {str(err)!r}"
    )
    assert err.__cause__ is original, (
        "the throttle must be chained from the original ResponseError instance "
        "(`raise LLMThrottleError(str(exc)) from exc`); "
        f"got __cause__={err.__cause__!r}"
    )
    # Retryable-taxonomy sanity: throttle is an LLMError but NOT a timeout.
    assert isinstance(err, LLMError)
    assert not isinstance(err, LLMTimeoutError)


# ===========================================================================
# Behavior 2 -- Timeout translation.
#   .chat raises ollama.RequestError -> .complete raises LLMTimeoutError with
#   the SAME message and __cause__ IS the original RequestError instance.
# ===========================================================================


def test_behavior2_timeout_translation(monkeypatch):
    stub = _install_ollama(monkeypatch)
    original = stub.RequestError("timed out")

    def chat(*args, **kwargs):
        raise original

    stub._chat_impl = chat

    client = create_client(Settings(provider="ollama"))
    with pytest.raises(LLMTimeoutError) as excinfo:
        client.complete(system="s", prompt="p", tag="plan")

    err = excinfo.value
    assert str(err) == "timed out", (
        f"the translated timeout must carry the original message; got {str(err)!r}"
    )
    assert err.__cause__ is original, (
        "the timeout must be chained from the original RequestError instance; "
        f"got __cause__={err.__cause__!r}"
    )
    assert isinstance(err, LLMError)
    assert not isinstance(err, LLMThrottleError)


# ===========================================================================
# Behavior 3 -- Throttle classified BEFORE timeout (ordering invariant).
#   An exception subclassing BOTH ResponseError AND RequestError is classified
#   as the retryable THROTTLE, never the timeout -- because throttle is the
#   FIRST `except` checked. A reordered `except` is the exact regression this
#   pins.
# ===========================================================================


def test_behavior3_throttle_checked_before_timeout(monkeypatch):
    stub = _install_ollama(monkeypatch)

    class Both(stub.ResponseError, stub.RequestError):
        pass

    original = Both("ambiguous")

    def chat(*args, **kwargs):
        raise original

    stub._chat_impl = chat

    client = create_client(Settings(provider="ollama"))
    with pytest.raises(LLMThrottleError) as excinfo:
        client.complete(system="s", prompt="p", tag="plan")

    err = excinfo.value
    # The ordering invariant: a type matching BOTH tuples resolves to throttle.
    assert isinstance(err, LLMThrottleError)
    assert not isinstance(err, LLMTimeoutError), (
        "an exception matching both throttle AND timeout must be classified as "
        "the retryable LLMThrottleError (throttle `except` checked first), NOT "
        "LLMTimeoutError -- a reordered `except` would flip this"
    )
    assert err.__cause__ is original


# ===========================================================================
# Behavior 4 -- Non-taxonomy exceptions propagate UNCHANGED.
#   A type in NEITHER tuple (ValueError) is NOT wrapped in the retry taxonomy;
#   it propagates as itself and is NOT an LLMError. The adapter owns only the
#   retryable taxonomy, not every possible failure (no `except Exception` grab).
# ===========================================================================


def test_behavior4_non_taxonomy_exception_propagates_unchanged(monkeypatch):
    stub = _install_ollama(monkeypatch)

    def chat(*args, **kwargs):
        raise ValueError("boom")

    stub._chat_impl = chat

    client = create_client(Settings(provider="ollama"))
    with pytest.raises(ValueError) as excinfo:
        client.complete(system="s", prompt="p", tag="plan")

    err = excinfo.value
    assert str(err) == "boom", f"the ValueError must propagate verbatim; got {str(err)!r}"
    assert not isinstance(err, LLMError), (
        "a non-taxonomy exception must NOT be reclassified as an LLMError "
        "(no widened `except Exception` swallowing non-retryable faults)"
    )
    assert not isinstance(err, (LLMThrottleError, LLMTimeoutError)), (
        "a non-taxonomy exception must NOT be wrapped in the retry taxonomy"
    )


# ===========================================================================
# Behavior 5 -- Successful completion is returned verbatim (not translated).
#   A valid ollama-shaped response (content "hello") -> an LLMResponse whose
#   .text == "hello". A success is never intercepted by the translation.
# ===========================================================================


def test_behavior5_success_returned_verbatim(monkeypatch):
    stub = _install_ollama(monkeypatch)

    def chat(*args, **kwargs):
        return _ollama_success_response("hello")

    stub._chat_impl = chat

    client = create_client(Settings(provider="ollama"))
    resp = client.complete(system="s", prompt="p", tag="plan")

    assert isinstance(resp, LLMResponse), (
        f"a successful call must return an LLMResponse; got {type(resp).__name__}"
    )
    assert resp.text == "hello", (
        f"the response text must pass through untranslated; got {resp.text!r}"
    )


# ===========================================================================
# Behavior 6 -- Inputs are forwarded to the underlying client.
#   On the Behavior-5 success, the stub records .chat was invoked EXACTLY once,
#   and the recorded call carried the `system` string "s" and the `prompt`
#   string "p" (in the messages payload the adapter builds) -- proving the
#   adapter DELEGATES rather than short-circuiting.
# ===========================================================================


def test_behavior6_inputs_forwarded_to_underlying_client(monkeypatch):
    stub = _install_ollama(monkeypatch)

    def chat(*args, **kwargs):
        return _ollama_success_response("hello")

    stub._chat_impl = chat

    client = create_client(Settings(provider="ollama"))
    resp = client.complete(system="s", prompt="p", tag="plan")

    assert resp.text == "hello"  # (the delegated call actually happened)
    assert len(stub.calls) == 1, (
        f"the underlying .chat must be invoked EXACTLY once; got {len(stub.calls)}"
    )

    recorded_args, recorded_kwargs = stub.calls[0]
    forwarded = _all_string_values(list(recorded_args)) + _all_string_values(recorded_kwargs)
    assert "s" in forwarded, (
        "the `system` string 's' must be forwarded into the underlying call "
        f"payload; recorded call = args={recorded_args!r} kwargs={recorded_kwargs!r}"
    )
    assert "p" in forwarded, (
        "the `prompt` string 'p' must be forwarded into the underlying call "
        f"payload; recorded call = args={recorded_args!r} kwargs={recorded_kwargs!r}"
    )


# ===========================================================================
# Guard -- the pin routes through a REAL registered provider (ollama).
# Not one of the six numbered behaviors, but it anchors the fixture: if
# `ollama` were dropped from VALID_PROVIDERS the whole harness would be moot.
# ===========================================================================


def test_ollama_is_a_registered_provider():
    assert "ollama" in VALID_PROVIDERS, (
        "the shared retry-taxonomy seam is pinned through the ollama provider; "
        f"it must remain registered. VALID_PROVIDERS={VALID_PROVIDERS!r}"
    )
