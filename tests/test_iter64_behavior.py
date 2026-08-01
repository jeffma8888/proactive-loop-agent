"""Black-box behavior tests for iteration 64.

Feature under test: the five LIVE-provider response/usage parsing adapters --
``anthropic`` / ``openai`` / ``bedrock`` / ``ollama`` / ``groq`` -- exercised
END-TO-END via the public ``create_client(...).complete(...)`` surface with
purely in-memory SDK stubs. Each live branch contains a small SDK-specific
translation closure ("read the reply text out of *this* SDK's response object;
read the prompt/completion token counts out of *its* usage object"). This is
the code most likely to break silently when an SDK ships a new response shape;
if it regresses, a live ``pla run`` returns empty text instead of failing a
test. This module pins the RESPONSE/USAGE seam of every live backend at the
public contract level (SPEC section 4.2).

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's PM spec "Expected Behaviors" 1-12,
``README.md``, and ``SPEC.md`` (esp. section 4.2) -- and drive ONLY the
documented public surface: ``create_client(Settings(provider=...))`` (from
``proactive_loop.llm.providers``) and the public ``LLMResponse`` dataclass
(from ``proactive_loop.llm.client``). NO file under ``src/`` was read, no
engineer/reviewer notes were consulted, and no ``git diff`` was inspected. The
private ``_SdkAdapter`` / ``_attr_or_key`` symbols are NOT imported -- the pin
is expressed purely at ``create_client`` + ``.complete()``.

Every SDK is a self-contained in-memory stub injected via
``monkeypatch.setitem(sys.modules, "<pkg>", stub)`` (auto-restored per test, so
no cross-test leakage and the iter-23 no-leak guard still holds). Each stub
exposes the throttle/timeout exception attributes the adapter resolves AT
CONSTRUCTION (else ``create_client`` raises before ``.complete`` is reached).
NO real SDK is installed, NO network is touched, NO API key is required -- the
suite runs from a cold ``uv sync`` clone.
"""

from __future__ import annotations

import sys
import types

from proactive_loop.config import Settings
from proactive_loop.llm.client import LLMResponse
from proactive_loop.llm.providers import create_client


# ===========================================================================
# In-memory SDK stub builders. Each exposes EXACTLY the attributes its live
# branch references: the construction-time exception types, plus a callable
# client whose response is set per test via ``stub._response``.
# ===========================================================================


def _make_anthropic_stub() -> types.ModuleType:
    stub = types.ModuleType("anthropic")

    class RateLimitError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    class _Messages:
        def create(self, **kwargs):
            stub.calls.append(kwargs)
            return stub._response

    class Anthropic:
        def __init__(self, *args, **kwargs) -> None:
            self.messages = _Messages()

    stub.RateLimitError = RateLimitError
    stub.APITimeoutError = APITimeoutError
    stub.Anthropic = Anthropic
    stub.calls = []
    stub._response = None
    return stub


def _make_openai_like_stub(pkg: str, client_attr: str) -> types.ModuleType:
    """Build an OpenAI-SDK-shaped stub (``openai`` and ``groq`` share it)."""
    stub = types.ModuleType(pkg)

    class RateLimitError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    class _Completions:
        def create(self, **kwargs):
            stub.calls.append(kwargs)
            return stub._response

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _ClientClass:
        def __init__(self, *args, **kwargs) -> None:
            self.chat = _Chat()

    stub.RateLimitError = RateLimitError
    stub.APITimeoutError = APITimeoutError
    setattr(stub, client_attr, _ClientClass)
    stub.calls = []
    stub._response = None
    return stub


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


def _install_boto3(monkeypatch) -> types.ModuleType:
    """Inject a bedrock (``boto3``) stub plus the ``botocore`` timeout-exception
    submodule the branch does ``from botocore.exceptions import ...`` against."""
    boto3 = types.ModuleType("boto3")

    class ThrottlingException(Exception):
        pass

    class _RuntimeClient:
        exceptions = types.SimpleNamespace(ThrottlingException=ThrottlingException)

        def converse(self, **kwargs):
            boto3.calls.append(kwargs)
            return boto3._response

    _instance = _RuntimeClient()

    def client(name, *args, **kwargs):
        boto3.client_names.append(name)
        return _instance

    boto3.client = client
    boto3.calls = []
    boto3.client_names = []
    boto3._response = None

    botocore = types.ModuleType("botocore")
    botocore_exc = types.ModuleType("botocore.exceptions")

    class ConnectTimeoutError(Exception):
        pass

    class ReadTimeoutError(Exception):
        pass

    botocore_exc.ConnectTimeoutError = ConnectTimeoutError
    botocore_exc.ReadTimeoutError = ReadTimeoutError
    botocore.exceptions = botocore_exc  # attribute access + submodule import

    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", botocore_exc)
    return boto3


def _ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


# ===========================================================================
# Behavior 1 -- anthropic happy path.
# ===========================================================================


def test_behavior1_anthropic_happy_path(monkeypatch):
    stub = _make_anthropic_stub()
    monkeypatch.setitem(sys.modules, "anthropic", stub)
    stub._response = _ns(
        content=[_ns(text="hi"), _ns(text=" there")],
        usage=_ns(input_tokens=3, output_tokens=5),
    )

    resp = create_client(Settings(provider="anthropic")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert isinstance(resp, LLMResponse)
    assert resp.text == "hi there", f"anthropic text must join content blocks; got {resp.text!r}"
    assert resp.usage == {"input_tokens": 3, "output_tokens": 5}, (
        f"anthropic usage must map input/output tokens; got {resp.usage!r}"
    )
    assert resp.model == "claude-3-5-sonnet-latest", (
        f"anthropic default model mismatch; got {resp.model!r}"
    )


# ===========================================================================
# Behavior 2 -- anthropic block-without-text tolerance.
# ===========================================================================


def test_behavior2_anthropic_block_without_text(monkeypatch):
    stub = _make_anthropic_stub()
    monkeypatch.setitem(sys.modules, "anthropic", stub)
    # 2nd block has NO .text attribute at all.
    stub._response = _ns(
        content=[_ns(text="a"), _ns()],
        usage=_ns(input_tokens=1, output_tokens=1),
    )

    resp = create_client(Settings(provider="anthropic")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert resp.text == "a", (
        "a content block missing `.text` must contribute the empty string (no error); "
        f"got {resp.text!r}"
    )


# ===========================================================================
# Behavior 3 -- openai happy path.
# ===========================================================================


def test_behavior3_openai_happy_path(monkeypatch):
    stub = _make_openai_like_stub("openai", "OpenAI")
    monkeypatch.setitem(sys.modules, "openai", stub)
    stub._response = _ns(
        choices=[_ns(message=_ns(content="hi"))],
        usage=_ns(prompt_tokens=3, completion_tokens=5),
    )

    resp = create_client(Settings(provider="openai")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert resp.text == "hi", f"openai text must read choices[0].message.content; got {resp.text!r}"
    assert resp.usage == {"input_tokens": 3, "output_tokens": 5}, (
        f"openai usage must map prompt/completion tokens; got {resp.usage!r}"
    )
    assert resp.model == "gpt-4o-mini", f"openai default model mismatch; got {resp.model!r}"


# ===========================================================================
# Behavior 4 -- openai usage=None -> empty usage.
# ===========================================================================


def test_behavior4_openai_usage_none(monkeypatch):
    stub = _make_openai_like_stub("openai", "OpenAI")
    monkeypatch.setitem(sys.modules, "openai", stub)
    stub._response = _ns(
        choices=[_ns(message=_ns(content="hi"))],
        usage=None,
    )

    resp = create_client(Settings(provider="openai")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert resp.text == "hi"
    assert resp.usage == {}, f"openai usage=None must yield an empty dict; got {resp.usage!r}"


# ===========================================================================
# Behavior 5 -- openai content=None -> empty text.
# ===========================================================================


def test_behavior5_openai_content_none(monkeypatch):
    stub = _make_openai_like_stub("openai", "OpenAI")
    monkeypatch.setitem(sys.modules, "openai", stub)
    stub._response = _ns(
        choices=[_ns(message=_ns(content=None))],
        usage=_ns(prompt_tokens=1, completion_tokens=1),
    )

    resp = create_client(Settings(provider="openai")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert resp.text == "", (
        f"openai content=None must yield an empty string, never None; got {resp.text!r}"
    )


# ===========================================================================
# Behavior 6 -- bedrock happy path.
# ===========================================================================


def test_behavior6_bedrock_happy_path(monkeypatch):
    boto3 = _install_boto3(monkeypatch)
    boto3._response = {
        "output": {"message": {"content": [{"text": "hi"}]}},
        "usage": {"inputTokens": 3, "outputTokens": 5},
    }

    resp = create_client(Settings(provider="bedrock")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert resp.text == "hi", f"bedrock text must read output.message.content[].text; got {resp.text!r}"
    assert resp.usage == {"input_tokens": 3, "output_tokens": 5}, (
        f"bedrock usage must map inputTokens/outputTokens; got {resp.usage!r}"
    )
    assert resp.model == "anthropic.claude-3-5-sonnet-20240620-v1:0", (
        f"bedrock default model mismatch; got {resp.model!r}"
    )
    assert boto3.client_names == ["bedrock-runtime"], (
        f"bedrock must construct the bedrock-runtime client; got {boto3.client_names!r}"
    )


# ===========================================================================
# Behavior 7 -- bedrock missing usage -> zeroed usage.
# ===========================================================================


def test_behavior7_bedrock_missing_usage(monkeypatch):
    boto3 = _install_boto3(monkeypatch)
    boto3._response = {
        "output": {"message": {"content": [{"text": "hi"}]}},
        # NO "usage" key.
    }

    resp = create_client(Settings(provider="bedrock")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert resp.text == "hi"
    assert resp.usage == {"input_tokens": 0, "output_tokens": 0}, (
        f"bedrock with no usage key must zero the token counts; got {resp.usage!r}"
    )


# ===========================================================================
# Behavior 8 -- ollama dict-shaped response with token counts.
#   Forces both the mapping-key read path AND the usage-populated branch.
# ===========================================================================


def test_behavior8_ollama_dict_with_counts(monkeypatch):
    stub = _make_ollama_stub()
    monkeypatch.setitem(sys.modules, "ollama", stub)
    stub._response = {
        "message": {"content": "hi there"},
        "prompt_eval_count": 3,
        "eval_count": 5,
    }

    resp = create_client(Settings(provider="ollama")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert resp.text == "hi there", (
        f"ollama must read content out of a dict-shaped message; got {resp.text!r}"
    )
    assert resp.usage == {"input_tokens": 3, "output_tokens": 5}, (
        f"ollama usage must map prompt_eval_count/eval_count; got {resp.usage!r}"
    )
    assert resp.model == "llama3.1", f"ollama default model mismatch; got {resp.model!r}"


# ===========================================================================
# Behavior 9 -- ollama object-shaped response, no counts -> empty usage.
# ===========================================================================


def test_behavior9_ollama_object_no_counts(monkeypatch):
    stub = _make_ollama_stub()
    monkeypatch.setitem(sys.modules, "ollama", stub)
    stub._response = _ns(message=_ns(content="hi"))

    resp = create_client(Settings(provider="ollama")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert resp.text == "hi", f"ollama must read content off an object-shaped message; got {resp.text!r}"
    assert resp.usage == {}, (
        f"ollama with no count fields must yield an empty usage dict; got {resp.usage!r}"
    )
    assert resp.model == "llama3.1"


# ===========================================================================
# Behavior 10 -- groq happy path.
# ===========================================================================


def test_behavior10_groq_happy_path(monkeypatch):
    stub = _make_openai_like_stub("groq", "Groq")
    monkeypatch.setitem(sys.modules, "groq", stub)
    stub._response = _ns(
        choices=[_ns(message=_ns(content="hi"))],
        usage=_ns(prompt_tokens=3, completion_tokens=5),
    )

    resp = create_client(Settings(provider="groq")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert resp.text == "hi", f"groq text must read choices[0].message.content; got {resp.text!r}"
    assert resp.usage == {"input_tokens": 3, "output_tokens": 5}, (
        f"groq usage must map prompt/completion tokens; got {resp.usage!r}"
    )
    assert resp.model == "llama-3.3-70b-versatile", (
        f"groq default model mismatch; got {resp.model!r}"
    )


# ===========================================================================
# Behavior 11 -- groq usage=None -> empty usage.
# ===========================================================================


def test_behavior11_groq_usage_none(monkeypatch):
    stub = _make_openai_like_stub("groq", "Groq")
    monkeypatch.setitem(sys.modules, "groq", stub)
    stub._response = _ns(
        choices=[_ns(message=_ns(content="hi"))],
        usage=None,
    )

    resp = create_client(Settings(provider="groq")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert resp.text == "hi"
    assert resp.usage == {}, f"groq usage=None must yield an empty dict; got {resp.usage!r}"


# ===========================================================================
# Behavior 12 -- No public-contract change (purely additive test coverage).
# ===========================================================================


def test_behavior12_version_unchanged():
    import proactive_loop

    assert proactive_loop.__version__ == "0.1.1", (
        "this is a test-only hardening iteration: the package version must NOT bump; "
        f"got {proactive_loop.__version__!r}"
    )
