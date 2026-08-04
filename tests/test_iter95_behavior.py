"""Black-box behavior tests for iteration 86 (ships as commit-seq **factory
iter 95**) --- boundary hardening of the ``ollama`` live-provider response
adapter.

Feature under test (SPEC 4.2, ``_create_ollama``): the ``ollama`` adapter now
COERCES its SDK reply AT THE BOUNDARY. Message ``content`` must resolve to a
``str`` -- a genuine ``str`` passes through, a missing/``None`` content yields
``""`` (unchanged), but a PRESENT non-``str`` content (an int, a list, ...) now
raises a clean ``LLMError`` naming ``ollama`` instead of being stored verbatim
as ``LLMResponse.text`` and detonating later in a downstream consumer. Each
token count must resolve to ``int``-or-absent: a non-``int`` count (a ``str`` /
``float``) is treated as absent, so ``LLMResponse.usage`` stays all-``int``.
The happy path is byte-identical to the prior iter-64 ollama behavior.

ISOLATION CONTRACT (honored): these tests are written STRICTLY from this
iteration's public contract --- the PM spec's numbered "Expected Behaviors"
(1-7), ``README.md``, ``SPEC.md`` (section 4.2), and the test conventions
already public under ``tests/`` (the ollama SDK-stub harness of
``test_iter64_behavior.py`` and the ``_run`` CLI helper of
``test_iter88_behavior.py``). They drive ONLY documented public surfaces: the
``create_client(Settings(provider="ollama")).complete(...)`` seam (from
``proactive_loop.llm.providers``), the public ``LLMResponse`` / ``LLMError``
types (from ``proactive_loop.llm.client``), ``VALID_PROVIDERS``, the ``pla``
CLI via ``proactive_loop.cli.main(argv) -> int`` (observable stdout/exit code),
and ``proactive_loop.__version__``. **No file under ``src/`` was read, no
engineer or reviewer note was consulted, and no ``git diff`` was inspected.**
The private ``_create_ollama`` / ``_attr_or_key`` / ``_SdkAdapter`` symbols are
NOT imported; the pin is expressed purely at the public ``create_client`` +
``.complete()`` surface.

Every test is fully offline/deterministic: the ``ollama`` SDK is an in-memory
``types.ModuleType`` stub injected via
``monkeypatch.setitem(sys.modules, "ollama", stub)`` (auto-restored per test),
exposing exactly the ``ResponseError`` / ``RequestError`` construction-time
exception attributes the adapter resolves AND a ``Client`` whose ``.chat(...)``
returns a settable ``stub._response``. NO real SDK is installed, NO network is
touched, NO API key is required.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from proactive_loop import __version__
from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.llm.client import LLMError, LLMResponse
from proactive_loop.llm.providers import VALID_PROVIDERS, create_client


# ---------------------------------------------------------------------------
# In-memory ollama SDK stub + helpers (mirrors tests/test_iter64_behavior.py).
# ---------------------------------------------------------------------------


def _make_ollama_stub() -> types.ModuleType:
    stub = types.ModuleType("ollama")

    class ResponseError(Exception):
        pass

    class RequestError(Exception):
        pass

    class Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def chat(self, *args, **kwargs):
            stub.calls.append((args, kwargs))
            return stub._response

    stub.ResponseError = ResponseError
    stub.RequestError = RequestError
    stub.Client = Client
    stub.calls = []
    stub._response = None
    return stub


def _ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


def _complete_ollama(monkeypatch, response):
    """Drive the public ollama seam with a single settable response object.

    Returns the ``LLMResponse``. Raises whatever ``.complete()`` raises so the
    error-path behaviors can assert on it.
    """
    stub = _make_ollama_stub()
    monkeypatch.setitem(sys.modules, "ollama", stub)
    stub._response = response
    return create_client(Settings(provider="ollama")).complete(
        system="s", prompt="p", tag="synthesize"
    )


def _run(argv, capsys):
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ===========================================================================
# Behavior 1 -- HAPPY PATH PRESERVED: dict-shaped, both counts int.
# ===========================================================================


def test_b1_happy_dict_with_int_counts(monkeypatch):
    resp = _complete_ollama(
        monkeypatch,
        {"message": {"content": "hi there"}, "prompt_eval_count": 3, "eval_count": 5},
    )
    assert isinstance(resp, LLMResponse)
    assert resp.text == "hi there", (
        f"dict-shaped content must read straight through unchanged; got {resp.text!r}"
    )
    assert resp.usage == {"input_tokens": 3, "output_tokens": 5}, (
        f"int prompt_eval_count/eval_count must map to input/output tokens; got {resp.usage!r}"
    )
    assert resp.model == "llama3.1", f"ollama default model mismatch; got {resp.model!r}"


# ===========================================================================
# Behavior 2 -- HAPPY PATH PRESERVED: object-shaped, no counts -> empty usage.
# ===========================================================================


def test_b2_happy_object_no_counts(monkeypatch):
    resp = _complete_ollama(monkeypatch, _ns(message=_ns(content="hi")))
    assert resp.text == "hi", (
        f"object-shaped content must read straight through unchanged; got {resp.text!r}"
    )
    assert resp.usage == {}, (
        f"with no count fields the usage dict must be empty; got {resp.usage!r}"
    )
    assert resp.model == "llama3.1"


# ===========================================================================
# Behavior 3 -- MISSING / NONE CONTENT -> EMPTY TEXT, NO ERROR.
# ===========================================================================


def test_b3a_missing_content_key_is_empty_text(monkeypatch):
    resp = _complete_ollama(monkeypatch, {"message": {}})
    assert resp.text == "", (
        f"a message with no `content` key must yield the empty string, never raise; "
        f"got {resp.text!r}"
    )


def test_b3b_none_content_is_empty_text(monkeypatch):
    resp = _complete_ollama(monkeypatch, {"message": {"content": None}})
    assert resp.text == "", (
        f"an explicit `content=None` must yield the empty string, never raise; "
        f"got {resp.text!r}"
    )


# ===========================================================================
# Behavior 4 -- NEW: NON-STR CONTENT RAISES A CLEAN PROVIDER ERROR.
#   An int content and a list content must BOTH surface as `LLMError` (the
#   provider-boundary base class) -- NOT a bare TypeError/AttributeError -- and
#   the message must name `ollama`.
# ===========================================================================


def test_b4a_int_content_raises_llmerror(monkeypatch):
    with pytest.raises(LLMError) as excinfo:
        _complete_ollama(monkeypatch, {"message": {"content": 123}})
    assert "ollama" in str(excinfo.value), (
        f"a non-str (int) message content must raise an LLMError naming `ollama`; "
        f"got {str(excinfo.value)!r}"
    )


def test_b4b_list_content_raises_llmerror(monkeypatch):
    with pytest.raises(LLMError) as excinfo:
        _complete_ollama(monkeypatch, {"message": {"content": ["a", "b"]}})
    assert "ollama" in str(excinfo.value), (
        f"a non-str (list) message content must raise an LLMError naming `ollama`; "
        f"got {str(excinfo.value)!r}"
    )


def test_b4c_int_content_error_is_not_bare_builtin(monkeypatch):
    # The whole point of the boundary coercion: a wrong-shape reply must NOT
    # leak out as a raw TypeError/AttributeError from a downstream consumer.
    with pytest.raises(LLMError):
        _complete_ollama(monkeypatch, {"message": {"content": 42}})
    # Prove it is specifically NOT a bare builtin type error by asserting the
    # LLMError branch is what fires (pytest.raises above already narrows it);
    # additionally confirm a TypeError alone would NOT satisfy the contract.
    try:
        _complete_ollama(monkeypatch, {"message": {"content": 42}})
    except LLMError:
        pass
    except (TypeError, AttributeError) as exc:  # pragma: no cover - contract guard
        pytest.fail(
            f"non-str content must surface as LLMError, not a bare {type(exc).__name__}"
        )


# ===========================================================================
# Behavior 5 -- NEW: NON-INT TOKEN COUNTS ARE DROPPED; USAGE STAYS ALL-INT.
#   A str count and a float count are both treated as absent; with BOTH counts
#   non-int, usage is the empty dict.
# ===========================================================================


def test_b5_non_int_counts_dropped_usage_all_int(monkeypatch):
    resp = _complete_ollama(
        monkeypatch,
        {"message": {"content": "ok"}, "prompt_eval_count": "3", "eval_count": 2.5},
    )
    assert resp.text == "ok", f"valid content must be unaffected by bad counts; got {resp.text!r}"
    assert all(isinstance(v, int) for v in resp.usage.values()), (
        f"every usage value must be an int; got {resp.usage!r}"
    )
    assert "3" not in resp.usage.values(), (
        f"the str count '3' must never appear in usage; got {resp.usage!r}"
    )
    assert 2.5 not in resp.usage.values(), (
        f"the float count 2.5 must never appear in usage; got {resp.usage!r}"
    )
    assert resp.usage == {}, (
        f"with BOTH counts non-int the usage dict must be empty; got {resp.usage!r}"
    )


# ===========================================================================
# Behavior 6 -- NEW: MIXED VALID + INVALID COUNT.
#   The valid int is kept; the invalid count is coerced-absent and reads 0 in
#   the both-keys block. Every usage value is an int.
# ===========================================================================


def test_b6_mixed_valid_and_invalid_count(monkeypatch):
    resp = _complete_ollama(
        monkeypatch,
        {"message": {"content": "ok"}, "prompt_eval_count": 4, "eval_count": "bad"},
    )
    assert resp.usage == {"input_tokens": 4, "output_tokens": 0}, (
        f"the valid int count is kept, the invalid one reads 0 in the both-keys block; "
        f"got {resp.usage!r}"
    )
    assert all(isinstance(v, int) for v in resp.usage.values()), (
        f"every usage value must be an int; got {resp.usage!r}"
    )


# ===========================================================================
# Behavior 7 -- NO DRIFT / NO REGRESSION.
#   VALID_PROVIDERS stays the exact 7-tuple; `pla providers --json` emits an
#   array of 7 provider objects; __version__ stays "0.1.1".
# ===========================================================================


def test_b7a_valid_providers_exact_seven_tuple():
    assert VALID_PROVIDERS == (
        "scripted",
        "anthropic",
        "openai",
        "bedrock",
        "ollama",
        "groq",
        "together",
    ), f"provider registry drifted; got {VALID_PROVIDERS!r}"


def test_b7b_providers_json_is_seven_objects(capsys):
    rc, out, err = _run(["providers", "--json"], capsys)
    assert rc == 0, f"`pla providers --json` must exit 0; stderr={err!r}"
    obj = json.loads(out)
    assert isinstance(obj, dict) and "providers" in obj, (
        f"`pla providers --json` must emit an object with a 'providers' key; got {out!r}"
    )
    arr = obj["providers"]
    assert isinstance(arr, list), f"'providers' must be an array; got {type(arr).__name__}"
    assert len(arr) == 7, f"exactly 7 provider objects expected; got {len(arr)}"
    names = {p["name"] for p in arr}
    assert names == set(VALID_PROVIDERS), (
        f"the --json provider names must equal VALID_PROVIDERS; got {sorted(names)}"
    )


def test_b7c_version_unchanged():
    assert __version__ == "0.1.1", (
        "this is a behavior-only boundary-hardening iteration: the package version "
        f"must NOT bump; got {__version__!r}"
    )
