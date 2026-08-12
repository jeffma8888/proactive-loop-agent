"""Black-box behavior tests for iteration 148 (foundry iteration 141).

Feature under test: the OpenAI chat-completions wire is written ONCE. The three
byte-identical per-vendor completion closures in ``llm/providers.py``
(``openai`` / ``groq`` / ``together``) fold into a single module-level factory
that returns the callable the already-shipped SDK-adapter seam consumes. This is
a pure internal refactor: every observable behavior of all seven provider
branches must be unchanged, and the duplication must not be able to grow back.

ISOLATION CONTRACT (honored): these tests were written strictly against this
iteration's PM spec ("Expected Behaviors" 1-8) and the conventions of the
existing black-box modules ``tests/test_iter64_behavior.py`` and
``tests/test_iter65_behavior.py``. No file under ``src/`` was read, no
engineer or reviewer note was opened, and no ``git diff`` was inspected. The
private ``_openai_wire_complete_fn`` / ``_SdkAdapter`` / ``_CompleteFn`` symbols
are NOT imported: every functional pin below is expressed through the public
``create_client(Settings(...)).complete(...)`` surface plus the public
``LLMResponse`` / ``LLMError`` types. Behavior 8 is a STRUCTURAL guard the spec
explicitly mandates ("Regrowth guard, by AST"); it consumes the module's source
mechanically -- counting definitions and hashing bodies -- and asserts nothing
about implementation logic.

Every SDK is a self-contained in-memory stub injected via
``monkeypatch.setitem(sys.modules, "<pkg>", stub)`` (auto-restored per test).
No real SDK is installed, no network is touched, no API key is required.
"""

from __future__ import annotations

import ast
import hashlib
import sys
import types
from pathlib import Path

import pytest

from proactive_loop.config import Settings
from proactive_loop.llm import providers as providers_mod
from proactive_loop.llm.client import (
    LLMResponse,
    LLMThrottleError,
    LLMTimeoutError,
)
from proactive_loop.llm.providers import create_client

# ---------------------------------------------------------------------------
# The three vendors this iteration folds, and the documented facts each one
# must keep: its SDK package, its client class, and its default model.
# ---------------------------------------------------------------------------

_FOLDED: dict[str, tuple[str, str, str]] = {
    "openai": ("openai", "OpenAI", "gpt-4o-mini"),
    "groq": ("groq", "Groq", "llama-3.3-70b-versatile"),
    "together": (
        "together",
        "Together",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ),
}
_FOLDED_PARAMS = [pytest.param(name, id=name) for name in _FOLDED]

# Every optional runtime module the folded branches must NOT need. Used by
# behavior 7: each vendor is tested with every OTHER SDK, plus the httpx HTTP
# transport, forced unimportable.
_ALL_SDK_MODULES = (
    "httpx",
    "openai",
    "groq",
    "together",
    "boto3",
    "botocore",
    "anthropic",
    "ollama",
)

_SENTINEL_USAGE = {"input_tokens": 7, "output_tokens": 11}


def _ns(**kwargs: object) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kwargs)


def _openai_shaped_response(
    content: str | None = "hi",
    *,
    usage: object | None = "default",
) -> types.SimpleNamespace:
    """Build an OpenAI-shaped completion response object.

    ``usage="default"`` means the documented happy-path token counts;
    ``usage=None`` exercises the ``usage is None`` branch.
    """
    resolved = (
        _ns(prompt_tokens=7, completion_tokens=11) if usage == "default" else usage
    )
    return _ns(
        choices=[_ns(message=_ns(content=content))],
        usage=resolved,
    )


def _make_wire_stub(pkg: str, client_attr: str) -> types.ModuleType:
    """An in-memory OpenAI-SDK-shaped stub for ``pkg``.

    Exposes only what the branch resolves at construction time (the two public
    error types and the client class) plus a ``chat.completions.create`` that
    records its kwargs in ``stub.calls`` and returns ``stub._response`` -- or
    raises ``stub._raises`` when set, which is how behavior 6 drives the
    retryable taxonomy.
    """
    stub = types.ModuleType(pkg)

    class RateLimitError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    class _Completions:
        def create(self, **kwargs: object) -> object:
            stub.calls.append(kwargs)  # type: ignore[attr-defined]
            if stub._raises is not None:  # type: ignore[attr-defined]
                raise stub._raises("boom")  # type: ignore[attr-defined]
            return stub._response  # type: ignore[attr-defined]

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _ClientClass:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.chat = _Chat()

    stub.RateLimitError = RateLimitError  # type: ignore[attr-defined]
    stub.APITimeoutError = APITimeoutError  # type: ignore[attr-defined]
    setattr(stub, client_attr, _ClientClass)
    stub.calls = []  # type: ignore[attr-defined]
    stub._response = _openai_shaped_response()  # type: ignore[attr-defined]
    stub._raises = None  # type: ignore[attr-defined]
    return stub


def _install(monkeypatch: pytest.MonkeyPatch, vendor: str) -> types.ModuleType:
    pkg, client_attr, _ = _FOLDED[vendor]
    stub = _make_wire_stub(pkg, client_attr)
    monkeypatch.setitem(sys.modules, pkg, stub)
    return stub


def _drive(vendor: str, **settings: object) -> LLMResponse:
    client = create_client(Settings(provider=vendor, **settings))  # type: ignore[arg-type]
    return client.complete(system="s", prompt="p", tag="synthesize")


# ===========================================================================
# Behavior 1 -- happy path, all three folded vendors.
# ===========================================================================


@pytest.mark.parametrize("vendor", _FOLDED_PARAMS)
def test_behavior1_happy_path(monkeypatch: pytest.MonkeyPatch, vendor: str) -> None:
    _install(monkeypatch, vendor)

    resp = _drive(vendor)

    assert isinstance(resp, LLMResponse), (
        f"{vendor} must return the public LLMResponse; got {type(resp)!r}"
    )
    assert resp.text == "hi", (
        f"{vendor} text must read choices[0].message.content; got {resp.text!r}"
    )
    assert resp.usage == _SENTINEL_USAGE, (
        f"{vendor} usage must map prompt/completion tokens; got {resp.usage!r}"
    )
    assert resp.model == _FOLDED[vendor][2], (
        f"{vendor} default model mismatch; got {resp.model!r}"
    )


# ===========================================================================
# Behavior 2 -- usage=None yields an EMPTY DICT (not None), all three. This is
# the coverage gap the fold closes: `together` had no such test before.
# ===========================================================================


@pytest.mark.parametrize("vendor", _FOLDED_PARAMS)
def test_behavior2_usage_none_is_empty_dict(
    monkeypatch: pytest.MonkeyPatch, vendor: str
) -> None:
    stub = _install(monkeypatch, vendor)
    stub._response = _openai_shaped_response(usage=None)  # type: ignore[attr-defined]

    resp = _drive(vendor)

    assert resp.usage == {}, (
        f"{vendor}: usage=None must yield an empty dict; got {resp.usage!r}"
    )
    assert resp.usage is not None, f"{vendor}: usage must never be None"
    assert resp.text == "hi", (
        f"{vendor}: text must still parse when usage is absent; got {resp.text!r}"
    )


# ===========================================================================
# Behavior 3 -- content=None yields an EMPTY STRING, all three.
# ===========================================================================


@pytest.mark.parametrize("vendor", _FOLDED_PARAMS)
def test_behavior3_content_none_is_empty_string(
    monkeypatch: pytest.MonkeyPatch, vendor: str
) -> None:
    stub = _install(monkeypatch, vendor)
    stub._response = _openai_shaped_response(content=None)  # type: ignore[attr-defined]

    resp = _drive(vendor)

    assert resp.text == "", (
        f"{vendor}: content=None must yield '' (never None, no raise); "
        f"got {resp.text!r}"
    )
    assert resp.usage == _SENTINEL_USAGE, (
        f"{vendor}: usage must still parse when content is None; got {resp.usage!r}"
    )


# ===========================================================================
# Behavior 4 -- per-vendor model default, and the override reaches BOTH the
# wire kwarg and the returned LLMResponse.
# ===========================================================================


@pytest.mark.parametrize("vendor", _FOLDED_PARAMS)
def test_behavior4_default_model_reaches_the_wire(
    monkeypatch: pytest.MonkeyPatch, vendor: str
) -> None:
    stub = _install(monkeypatch, vendor)

    resp = _drive(vendor)

    expected = _FOLDED[vendor][2]
    assert resp.model == expected, f"{vendor} default model; got {resp.model!r}"
    assert stub.calls[0]["model"] == expected, (  # type: ignore[attr-defined]
        f"{vendor}: the default model must be passed to create(model=...); "
        f"got {stub.calls[0]!r}"  # type: ignore[attr-defined]
    )


@pytest.mark.parametrize("vendor", _FOLDED_PARAMS)
def test_behavior4_model_override_reaches_the_wire(
    monkeypatch: pytest.MonkeyPatch, vendor: str
) -> None:
    stub = _install(monkeypatch, vendor)

    resp = _drive(vendor, model="custom-x")

    assert stub.calls[0]["model"] == "custom-x", (  # type: ignore[attr-defined]
        f"{vendor}: Settings.model must be passed verbatim to create(model=...); "
        f"got {stub.calls[0]!r}"  # type: ignore[attr-defined]
    )
    assert resp.model == "custom-x", (
        f"{vendor}: the override must also be echoed on LLMResponse.model; "
        f"got {resp.model!r}"
    )


# ===========================================================================
# Behavior 5 -- the messages payload is unchanged: exactly one call, exactly
# the two roles in order, and no kwarg beyond model/messages.
# ===========================================================================


@pytest.mark.parametrize("vendor", _FOLDED_PARAMS)
def test_behavior5_messages_payload_unchanged(
    monkeypatch: pytest.MonkeyPatch, vendor: str
) -> None:
    stub = _install(monkeypatch, vendor)

    _drive(vendor)

    calls = stub.calls  # type: ignore[attr-defined]
    assert len(calls) == 1, (
        f"{vendor}: exactly one create() call per complete(); got {len(calls)}"
    )
    kwargs = calls[0]
    assert kwargs["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "p"},
    ], f"{vendor}: messages payload changed; got {kwargs.get('messages')!r}"
    assert set(kwargs) == {"model", "messages"}, (
        f"{vendor}: create() must receive only model+messages; "
        f"got {sorted(kwargs)!r}"
    )


# ===========================================================================
# Behavior 6 -- the retryable taxonomy stays PER-VENDOR: each vendor's own
# RateLimitError/APITimeoutError classify, sourced from its own namespace.
# ===========================================================================


@pytest.mark.parametrize("vendor", _FOLDED_PARAMS)
def test_behavior6_rate_limit_maps_to_throttle(
    monkeypatch: pytest.MonkeyPatch, vendor: str
) -> None:
    stub = _install(monkeypatch, vendor)
    stub._raises = stub.RateLimitError  # type: ignore[attr-defined]

    with pytest.raises(LLMThrottleError):
        _drive(vendor)


@pytest.mark.parametrize("vendor", _FOLDED_PARAMS)
def test_behavior6_timeout_maps_to_timeout(
    monkeypatch: pytest.MonkeyPatch, vendor: str
) -> None:
    stub = _install(monkeypatch, vendor)
    stub._raises = stub.APITimeoutError  # type: ignore[attr-defined]

    with pytest.raises(LLMTimeoutError):
        _drive(vendor)


def test_behavior6_taxonomy_is_not_shared_across_vendors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vendor must classify ITS OWN error types only.

    The fold's risk is a single shared exception tuple. If that happened, groq's
    RateLimitError would also be recognised by the openai branch. Here the
    openai branch is driven with an error class that belongs to the groq stub
    and is a stranger to openai's namespace: it must NOT be classified as a
    throttle, it must surface unclassified.
    """
    openai_stub = _install(monkeypatch, "openai")
    groq_stub = _make_wire_stub("groq", "Groq")
    openai_stub._raises = groq_stub.RateLimitError  # type: ignore[attr-defined]

    with pytest.raises(Exception) as excinfo:  # noqa: PT011 - class asserted below
        _drive("openai")

    assert not isinstance(excinfo.value, LLMThrottleError), (
        "a foreign vendor's RateLimitError must NOT be classified as a throttle "
        "-- the exception tuples must stay per-vendor after the fold"
    )


# ===========================================================================
# Behavior 7 -- construction and completion touch ONLY that vendor's
# namespace: every other SDK, and httpx, forced unimportable.
# ===========================================================================


@pytest.mark.parametrize("vendor", _FOLDED_PARAMS)
def test_behavior7_namespace_isolation(
    monkeypatch: pytest.MonkeyPatch, vendor: str
) -> None:
    pkg = _FOLDED[vendor][0]
    blocked = [name for name in _ALL_SDK_MODULES if name != pkg]
    for name in blocked:
        # Per CPython import semantics a None entry in sys.modules makes both
        # `import x` and importlib.import_module("x") raise ImportError.
        monkeypatch.setitem(sys.modules, name, None)

    # Non-vacuity: prove the block is real before relying on it.
    with pytest.raises(ImportError):
        __import__(blocked[0])

    stub = _install(monkeypatch, vendor)

    resp = _drive(vendor)

    assert resp.text == "hi", (
        f"{vendor} must work with only the {pkg!r} namespace present; "
        f"got {resp.text!r}"
    )
    assert len(stub.calls) == 1, (  # type: ignore[attr-defined]
        f"{vendor}: the isolated path must still issue exactly one wire call"
    )


# ===========================================================================
# Behavior 8 -- regrowth guard, by AST (never a regex), two-sided and
# non-vacuous; plus the three UNFOLDED branches still work unchanged.
# ===========================================================================

_PROVIDERS_PATH = Path(providers_mod.__file__)


def _nested_functions(source: str) -> list[tuple[str, int, str]]:
    """Every function defined INSIDE another function: (name, lineno, digest).

    The digest hashes the unparsed BODY only, so it is name-independent: a clone
    renamed to dodge a name-keyed check still collides. AST-based on purpose --
    a text search would also match the name in a docstring or a comment, which
    ``test_behavior8_guard_ignores_a_mere_mention`` proves is a real distinction.
    """
    tree = ast.parse(source)
    out: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if inner is node:
                continue
            if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = "\n".join(ast.unparse(stmt) for stmt in inner.body)
                digest = hashlib.sha256(body.encode()).hexdigest()[:12]
                out.append((inner.name, inner.lineno, digest))
    return out


def _closure_factories(source: str) -> list[str]:
    """Module-level functions that define an inner function and RETURN it."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        inner_names = {
            child.name
            for child in ast.walk(node)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child is not node
        }
        returns_inner = any(
            isinstance(stmt, ast.Return)
            and isinstance(stmt.value, ast.Name)
            and stmt.value.id in inner_names
            for stmt in ast.walk(node)
        )
        if inner_names and returns_inner:
            found.append(node.name)
    return found


def test_behavior8_exactly_three_nested_complete_closures_remain() -> None:
    source = _PROVIDERS_PATH.read_text(encoding="utf-8")
    # Non-vacuity: the scan must have found a real, substantial module.
    assert len(source) > 5000, (
        f"the guard read only {len(source)} chars from {_PROVIDERS_PATH} -- "
        "a mislocated file would make this test vacuously green"
    )

    nested = _nested_functions(source)
    completes = [item for item in nested if item[0] == "_complete"]

    assert len(completes) == 3, (
        "exactly 3 nested `def _complete` closures must remain (anthropic, "
        "bedrock, ollama -- the three distinct wires); found "
        f"{len(completes)} at {[(n, ln) for n, ln, _ in completes]}"
    )


def test_behavior8_one_module_level_factory_returns_the_shared_closure() -> None:
    source = _PROVIDERS_PATH.read_text(encoding="utf-8")

    factories = _closure_factories(source)

    assert len(factories) == 1, (
        "the folded OpenAI wire must live in exactly ONE module-level closure "
        f"factory; found {len(factories)}: {factories}"
    )


def test_behavior8_no_two_nested_closures_share_a_body() -> None:
    """Name-independent clone detection: a duplicate under a new name still trips."""
    source = _PROVIDERS_PATH.read_text(encoding="utf-8")

    nested = _nested_functions(source)
    assert len(nested) >= 4, (
        f"expected at least 4 nested closures in {_PROVIDERS_PATH.name}; "
        f"found {len(nested)} -- the scan looks broken"
    )

    seen: dict[str, list[str]] = {}
    for name, lineno, digest in nested:
        seen.setdefault(digest, []).append(f"{name}:{lineno}")
    dupes = {digest: sites for digest, sites in seen.items() if len(sites) > 1}

    assert not dupes, (
        "no two nested closures in providers.py may share a body digest "
        f"(byte-identical duplication); found {dupes}"
    )


_PLANTED_CLONES = '''
"""Planted module: two byte-identical nested closures under DIFFERENT names."""


def make_a(sdk, model):
    def _complete(system, prompt):
        return sdk.run(model=model, system=system, prompt=prompt)

    return _complete


def make_b(sdk, model):
    def _renamed(system, prompt):
        return sdk.run(model=model, system=system, prompt=prompt)

    return _renamed
'''

_PLANTED_MENTION_ONLY = '''
"""Planted module that only MENTIONS `def _complete`, never defines one.

A regex for `def _complete` matches this docstring; the AST guard must report
zero, or prose about the guard would break the guard.
"""


def build(sdk):
    # the shared factory is deliberately NOT named `def _complete`
    return sdk
'''


def test_behavior8_guard_fires_on_planted_renamed_clones() -> None:
    nested = _nested_functions(_PLANTED_CLONES)
    digests = [digest for _, _, digest in nested]

    assert len(nested) == 2, nested
    assert digests[0] == digests[1], (
        "the digest must be name-independent: two identical bodies under "
        f"different names must collide; got {nested}"
    )
    assert len(_closure_factories(_PLANTED_CLONES)) == 2, _closure_factories(
        _PLANTED_CLONES
    )


def test_behavior8_guard_ignores_a_mere_mention() -> None:
    assert "def _complete" in _PLANTED_MENTION_ONLY
    assert _nested_functions(_PLANTED_MENTION_ONLY) == []
    assert _closure_factories(_PLANTED_MENTION_ONLY) == []


# --- the three UNFOLDED branches must be untouched -------------------------


def test_behavior8_anthropic_branch_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = types.ModuleType("anthropic")

    class RateLimitError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    class _Messages:
        def create(self, **kwargs: object) -> object:
            stub.calls.append(kwargs)  # type: ignore[attr-defined]
            return stub._response  # type: ignore[attr-defined]

    class Anthropic:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.messages = _Messages()

    stub.RateLimitError = RateLimitError  # type: ignore[attr-defined]
    stub.APITimeoutError = APITimeoutError  # type: ignore[attr-defined]
    stub.Anthropic = Anthropic  # type: ignore[attr-defined]
    stub.calls = []  # type: ignore[attr-defined]
    stub._response = _ns(  # type: ignore[attr-defined]
        content=[_ns(text="hi"), _ns(text=" there")],
        usage=_ns(input_tokens=3, output_tokens=5),
    )
    monkeypatch.setitem(sys.modules, "anthropic", stub)

    resp = _drive("anthropic")

    assert resp.text == "hi there", f"anthropic joins blocks; got {resp.text!r}"
    assert resp.usage == {"input_tokens": 3, "output_tokens": 5}
    assert resp.model == "claude-3-5-sonnet-latest"


def test_behavior8_bedrock_branch_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boto3 = types.ModuleType("boto3")

    class ThrottlingException(Exception):
        pass

    class _RuntimeClient:
        exceptions = types.SimpleNamespace(ThrottlingException=ThrottlingException)

        def converse(self, **kwargs: object) -> object:
            boto3.calls.append(kwargs)  # type: ignore[attr-defined]
            return boto3._response  # type: ignore[attr-defined]

    instance = _RuntimeClient()

    def client(name: str, *args: object, **kwargs: object) -> object:
        boto3.client_names.append(name)  # type: ignore[attr-defined]
        return instance

    boto3.client = client  # type: ignore[attr-defined]
    boto3.calls = []  # type: ignore[attr-defined]
    boto3.client_names = []  # type: ignore[attr-defined]
    boto3._response = {  # type: ignore[attr-defined]
        "output": {"message": {"content": [{"text": "hi"}]}},
        "usage": {"inputTokens": 3, "outputTokens": 5},
    }

    botocore = types.ModuleType("botocore")
    botocore_exc = types.ModuleType("botocore.exceptions")

    class ConnectTimeoutError(Exception):
        pass

    class ReadTimeoutError(Exception):
        pass

    botocore_exc.ConnectTimeoutError = ConnectTimeoutError  # type: ignore[attr-defined]
    botocore_exc.ReadTimeoutError = ReadTimeoutError  # type: ignore[attr-defined]
    botocore.exceptions = botocore_exc  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", botocore_exc)

    resp = _drive("bedrock")

    assert resp.text == "hi", f"bedrock text; got {resp.text!r}"
    assert resp.usage == {"input_tokens": 3, "output_tokens": 5}
    assert resp.model == "anthropic.claude-3-5-sonnet-20240620-v1:0"
    assert boto3.client_names == ["bedrock-runtime"]  # type: ignore[attr-defined]


def test_behavior8_ollama_branch_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = types.ModuleType("ollama")

    class ResponseError(Exception):
        pass

    class RequestError(Exception):
        pass

    class Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def chat(self, *args: object, **kwargs: object) -> object:
            stub.calls.append((args, kwargs))  # type: ignore[attr-defined]
            return stub._response  # type: ignore[attr-defined]

    stub.ResponseError = ResponseError  # type: ignore[attr-defined]
    stub.RequestError = RequestError  # type: ignore[attr-defined]
    stub.Client = Client  # type: ignore[attr-defined]
    stub.calls = []  # type: ignore[attr-defined]
    stub._response = {  # type: ignore[attr-defined]
        "message": {"content": "hi there"},
        "prompt_eval_count": 3,
        "eval_count": 5,
    }
    monkeypatch.setitem(sys.modules, "ollama", stub)

    resp = _drive("ollama")

    assert resp.text == "hi there", f"ollama text; got {resp.text!r}"
    assert resp.usage == {"input_tokens": 3, "output_tokens": 5}
    assert resp.model == "llama3.1"
