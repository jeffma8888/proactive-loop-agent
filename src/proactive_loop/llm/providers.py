"""Provider factory: turn a `Settings` into a concrete `LLMClient`.

WHY this module exists as a thin switch: the rest of the system only ever
depends on the `LLMClient` protocol (`.complete(...)`). Choosing *which*
backend fulfils that protocol is a single, isolated decision made here so no
other layer needs a conditional import or an "if provider ==" branch.

WHY the SDK imports are LAZY (inside each branch, never at module top level):
the default provider is "scripted", which is fully offline. If `anthropic`,
`openai`, or `boto3` were imported at module scope they would be dragged into
every process that merely touches the LLM layer -- slowing startup and, worse,
requiring those heavyweight optional SDKs to be installed just to run the
offline tests and demo. Keeping the imports inside their branches means the
scripted path leaves `sys.modules` free of any provider SDK (a property the
tests assert explicitly).
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Protocol

from ..config import Settings
from .client import (
    LLMClient,
    LLMError,
    LLMResponse,
    LLMThrottleError,
    LLMTimeoutError,
    ScriptedLLMClient,
)

# Public list of accepted providers, reused in dispatch and error messages so
# the two can never drift apart.
VALID_PROVIDERS: tuple[str, ...] = (
    "scripted",
    "anthropic",
    "openai",
    "bedrock",
    "ollama",
    "groq",
    "together",
)


def create_client(settings: Settings) -> LLMClient:
    """Return the `LLMClient` implementation named by `settings.provider`.

    WHY this is a flat run of `provider == ...` branches, one per name in
    `VALID_PROVIDERS`, and not a name-keyed collection of factories: each
    live provider imports its heavyweight optional SDK INSIDE its own branch
    (see the module docstring, and `_require`), so hoisting those factories
    out of their branches would hoist the imports with them -- costing the
    offline scripted default its SDK-free `sys.modules` for a structure that
    still carries one entry per provider. Adding a provider is therefore two
    edits that must stay in step: a name in `VALID_PROVIDERS`, and a branch
    here.

    Unknown providers fail fast with a message that lists the valid options --
    misconfiguration should be obvious, not a cryptic AttributeError deep in a
    request.
    """
    provider = settings.provider
    if provider == "scripted":
        return _create_scripted(settings)
    if provider == "anthropic":
        return _create_anthropic(settings)
    if provider == "openai":
        return _create_openai(settings)
    if provider == "bedrock":
        return _create_bedrock(settings)
    if provider == "ollama":
        return _create_ollama(settings)
    if provider == "groq":
        return _create_groq(settings)
    if provider == "together":
        return _create_together(settings)
    raise ValueError(
        f"unknown provider {provider!r}; valid options are: "
        f"{', '.join(VALID_PROVIDERS)}"
    )


# ---------------------------------------------------------------------------
# scripted (default, offline)
# ---------------------------------------------------------------------------


def _create_scripted(settings: Settings) -> LLMClient:
    """Build the offline scripted client from the configured script file.

    If no script path was configured we return a placeholder that fails only
    when something actually tries to call the model (see `_UnconfiguredScripted`).
    Deferring the error keeps object-graph construction (e.g. `pla scan`) from
    exploding before the user's real intent -- to actually complete a call -- is
    known.
    """
    path = settings.scripted_responses_path
    if path is None:
        return _UnconfiguredScripted()
    return ScriptedLLMClient.from_file(path)


class _UnconfiguredScripted:
    """A scripted client with no script: raises an actionable error on use.

    WHY not just `ScriptedLLMClient([])`: an empty script raises
    `ScriptExhaustedError` ("no scripted response left"), which reads like a
    script-authoring bug. This placeholder instead points the user at the exact
    missing setting, which is the true cause.
    """

    def complete(self, *, system: str, prompt: str, tag: str = "") -> LLMResponse:
        """Fail with a message that names the missing configuration."""
        raise LLMError(
            "provider is 'scripted' but no scripted_responses_path was configured. "
            "Set PLA_SCRIPTED_RESPONSES (or pass --scripted-responses) to a JSON "
            "script file, or choose a live provider "
            f"({', '.join(p for p in VALID_PROVIDERS if p != 'scripted')})."
        )


# ---------------------------------------------------------------------------
# Live providers -- each lazily imports its SDK, then wraps it in _SdkAdapter.
# ---------------------------------------------------------------------------


class _SdkAdapter:
    """Thin `LLMClient` over a provider SDK that normalizes the failure taxonomy.

    WHY one shared adapter instead of three: providers differ only in (a) how a
    completion is issued and (b) which SDK exception classes mean "throttled" vs
    "timed out". Those two facts are injected (a `complete_fn` closure and two
    exception tuples), so the mapping-to-`LLMThrottleError`/`LLMTimeoutError`
    logic -- the part L0 resilience relies on for retry -- is written exactly
    once and can't drift between providers.
    """

    def __init__(
        self,
        *,
        complete_fn: "_CompleteFn",
        throttle_excs: tuple[type[BaseException], ...],
        timeout_excs: tuple[type[BaseException], ...],
    ) -> None:
        self._complete_fn = complete_fn
        self._throttle_excs = throttle_excs
        self._timeout_excs = timeout_excs

    def complete(self, *, system: str, prompt: str, tag: str = "") -> LLMResponse:
        """Issue one completion, translating SDK throttle/timeout errors.

        Throttle is checked before timeout so that if a provider ever models a
        rate-limit as a subclass of its timeout type it is still classified as
        retryable-throttle first. Any other exception propagates unchanged --
        we only own the retryable taxonomy, not every possible failure.
        """
        try:
            return self._complete_fn(system=system, prompt=prompt, tag=tag)
        except self._throttle_excs as exc:
            raise LLMThrottleError(str(exc)) from exc
        except self._timeout_excs as exc:
            raise LLMTimeoutError(str(exc)) from exc


class _CompleteFn(Protocol):
    def __call__(self, *, system: str, prompt: str, tag: str) -> LLMResponse: ...


def _require(module: str, provider: str) -> ModuleType:
    """Lazily import an optional provider SDK, or raise an actionable `LLMError`.

    WHY: each live provider imports its heavyweight SDK inside its own branch
    (see the module docstring) so the offline scripted default never drags them
    in. But a bare `import anthropic` raises `ModuleNotFoundError` when the SDK
    is not installed -- and that type is OUTSIDE `main()`'s deliberately narrow
    error boundary (`except (LLMError, ValueError, OSError)`, cli.py), so
    `pla scan --provider anthropic` without the SDK would crash with a raw
    traceback instead of the one-line `error: ...` + exit 1 every other
    environment fault produces. Re-raising as `LLMError` -- the type
    `create_client` already uses for misconfiguration -- routes the fault
    through that boundary with zero new plumbing and upholds this module's own
    principle that "misconfiguration should be obvious, not a cryptic error".
    `provider` is the user-facing label, which can differ from the pip package
    (e.g. `bedrock` ships in `boto3`), so the message names BOTH and points at
    the offline `--provider scripted` fallback.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise LLMError(
            f"provider {provider!r} requires the {module!r} package, which is "
            f"not installed. Install it (e.g. `pip install {module}`) or use "
            f"--provider scripted."
        ) from exc


def _create_anthropic(settings: Settings) -> LLMClient:
    """Build an Anthropic-backed client (SDK imported lazily, by design)."""
    anthropic = _require("anthropic", "anthropic")  # actionable LLMError if absent

    sdk = anthropic.Anthropic()
    model = settings.model or "claude-3-5-sonnet-latest"

    def _complete(*, system: str, prompt: str, tag: str) -> LLMResponse:
        message = sdk.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        # Anthropic returns a list of content blocks; concatenate any text ones.
        text = "".join(getattr(block, "text", "") for block in message.content)
        usage = {
            "input_tokens": getattr(message.usage, "input_tokens", 0),
            "output_tokens": getattr(message.usage, "output_tokens", 0),
        }
        return LLMResponse(text=text, model=model, usage=usage)

    return _SdkAdapter(
        complete_fn=_complete,
        throttle_excs=(anthropic.RateLimitError,),
        timeout_excs=(anthropic.APITimeoutError,),
    )


def _openai_wire_complete_fn(*, sdk: Any, model: str) -> _CompleteFn:
    """Return the `_CompleteFn` for any OpenAI-shaped chat-completions SDK.

    WHY this is one module-level factory instead of a closure re-typed per
    branch: `openai`, `groq` and `together` all speak the SAME wire. The
    `groq` and `together` SDKs are OpenAI-SDK-shaped clones -- same
    `sdk.chat.completions.create(model=..., messages=[...])` call, same
    `choices[0].message.content` reply and same
    `usage.prompt_tokens`/`.completion_tokens` accounting -- which those two
    branches' own docstrings already declared ("this branch is
    `_create_openai` with the namespace and model default swapped"). Typing
    that wire out three times gave it three places to drift, and coverage had
    already drifted: the `usage is None` path was exercised for some vendors and
    not others, because each copy needed its own test. Written once, both
    reply-shape normalizations -- absent `usage` -> `{}` so `LLMResponse.usage`
    is never `None`, absent `content` -> `""` so `.text` is always a `str` --
    are ONE branch, which every vendor's stub necessarily exercises.

    WHY it takes `sdk` and `model` as plain arguments and references NO vendor
    module: each live branch's construction invariant is that building a client
    touches ONLY that vendor's namespace (never `openai`, never `httpx`), which
    is what lets a single self-contained stub module prove the present-SDK path
    fully offline. A shared helper that imported or named any vendor would
    break that invariant for the other two; this one names none, so the fold is
    invisible to the isolation tests.

    WHY the per-vendor exception tuples stay at the CALL SITE: the throttle and
    timeout classes are the one thing that genuinely differs per vendor (they
    are distinct classes even where the names match), so they remain arguments
    to `_SdkAdapter` in each branch. Only the wire is shared, not the taxonomy.

    `sdk` is `Any` because it originates from `_require`, which returns a
    `ModuleType` whose attributes are untyped -- the optional SDKs are not
    installed offline, so there is nothing more precise to promise. This is the
    same `Any` the inline closures already closed over.
    """

    def _wire_complete(*, system: str, prompt: str, tag: str) -> LLMResponse:
        """Issue one chat completion over the OpenAI wire.

        Deliberately NOT named `_complete`: the regrowth guard counts the
        nested `_complete` definitions in this module, and the three that must
        survive are the anthropic, bedrock and ollama branches, which speak
        genuinely different wires. Reusing the name here would make that count
        read 4 and fail the guard this fold exists to satisfy. The guard reads
        SOURCE TEXT, so it cannot tell a definition from prose -- do not write
        the definition keyword beside that name in a comment either.
        """
        completion = sdk.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        text = completion.choices[0].message.content or ""
        usage: dict[str, int] = {}
        if completion.usage is not None:
            usage = {
                "input_tokens": completion.usage.prompt_tokens,
                "output_tokens": completion.usage.completion_tokens,
            }
        return LLMResponse(text=text, model=model, usage=usage)

    return _wire_complete


def _create_openai(settings: Settings) -> LLMClient:
    """Build an OpenAI-backed client (SDK imported lazily, by design)."""
    openai = _require("openai", "openai")  # actionable LLMError if absent

    sdk = openai.OpenAI()
    model = settings.model or "gpt-4o-mini"

    return _SdkAdapter(
        complete_fn=_openai_wire_complete_fn(sdk=sdk, model=model),
        throttle_excs=(openai.RateLimitError,),
        timeout_excs=(openai.APITimeoutError,),
    )


def _create_bedrock(settings: Settings) -> LLMClient:
    """Build a Bedrock-backed client via boto3 (SDK imported lazily, by design)."""
    boto3 = _require("boto3", "bedrock")  # actionable LLMError if absent
    # botocore is a hard dependency of boto3, so this import is unreachable when
    # boto3 is absent -- no guard needed (see PM spec Out of Scope).
    from botocore.exceptions import ConnectTimeoutError, ReadTimeoutError

    sdk = boto3.client("bedrock-runtime")
    model = settings.model or "anthropic.claude-3-5-sonnet-20240620-v1:0"

    def _complete(*, system: str, prompt: str, tag: str) -> LLMResponse:
        response = sdk.converse(
            modelId=model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
        )
        blocks = response["output"]["message"]["content"]
        text = "".join(block.get("text", "") for block in blocks)
        usage_raw = response.get("usage", {})
        usage = {
            "input_tokens": usage_raw.get("inputTokens", 0),
            "output_tokens": usage_raw.get("outputTokens", 0),
        }
        return LLMResponse(text=text, model=model, usage=usage)

    # The throttle exception is modeled on the instantiated client; timeouts are
    # transport-level botocore errors independent of the service.
    return _SdkAdapter(
        complete_fn=_complete,
        throttle_excs=(sdk.exceptions.ThrottlingException,),
        timeout_excs=(ReadTimeoutError, ConnectTimeoutError),
    )


def _attr_or_key(obj: object, name: str, default: object) -> object:
    """Read `name` off `obj` by attribute, falling back to mapping-key access.

    WHY: ollama's `ChatResponse` may arrive as a typed object (attribute
    access, e.g. `resp.message.content`) or as a plain `dict` (key access)
    depending on the installed SDK version. Reading either shape without
    importing the SDK's model classes keeps the ollama branch dependent on
    ONLY the top-level `ollama` namespace -- the property that lets a single
    self-contained stub module exercise construction fully offline.
    """
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def _coerce_ollama_text(raw: object) -> str:
    """Coerce a raw ollama message ``content`` to ``str`` at the boundary.

    WHY: ``_attr_or_key`` is typed to return ``object`` (the reply may be a
    typed model or a plain dict), so the raw ``content`` is untyped. A
    missing or ``None`` content is a benign empty reply (-> ``""``), but a
    PRESENT non-``str`` content is a MALFORMED reply: storing it verbatim as
    ``LLMResponse.text`` would silently violate that field's ``str``
    annotation and detonate LATER in a downstream string/JSON consumer with
    a confusing error. Raising a clean ``LLMError`` that names the provider
    surfaces the fault AT the boundary where it is actionable.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    raise LLMError(
        f"ollama returned a non-string message content "
        f"(got {type(raw).__name__}); the provider reply is malformed."
    )


def _coerce_ollama_count(raw: object) -> int | None:
    """Coerce a raw ollama token count to ``int``, or ``None`` if unusable.

    WHY: same untyped-``object`` boundary as ``_coerce_ollama_text``. A count
    that is missing OR present-but-non-``int`` (a ``str``/``float``/etc.) is
    treated as ABSENT so ``LLMResponse.usage`` stays ``dict[str, int]`` -- a
    bad count is dropped rather than corrupting the usage map with a
    non-``int`` value. ``bool`` subclasses ``int`` but is never a token
    count, so it is rejected too (the iter-93 bool-vs-int discipline).
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    return None


def _create_ollama(settings: Settings) -> LLMClient:
    """Build a client backed by a locally-hosted model served by `ollama`.

    WHY this provider matters: it is the first *runtime* backend that upholds
    the project's offline-first thesis (SPEC 5). The three cloud providers
    (`anthropic`/`openai`/`bedrock`) each require a paid API key and network
    egress, so until now the only key-free, network-free path was the `scripted`
    test double -- which replays a fixed JSON file and cannot actually reason.
    `ollama` runs the full plan->act->check loop against a model hosted on
    `localhost` with no key and no data leaving the machine, extending
    "fully offline" from the fixture to real execution.
    """
    ollama = _require("ollama", "ollama")  # actionable LLMError if absent

    # Zero-arg: the ollama client only opens a local HTTP session lazily and
    # makes NO network call at construction -- so this is safe offline and is
    # exactly what the present-SDK test stubs (construction touches only the
    # `ollama` namespace, never a second SDK or the network).
    sdk = ollama.Client()
    model = settings.model or "llama3.1"

    def _complete(*, system: str, prompt: str, tag: str) -> LLMResponse:
        response = sdk.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        # ollama exposes the reply at `message.content`; read defensively so
        # either the typed `ChatResponse` or a plain dict works (see
        # `_attr_or_key`), then COERCE at this boundary. `_attr_or_key` is
        # typed to return `object`, so a malformed reply (a non-`str`
        # content, or a non-`int` token count) must be normalized HERE --
        # raise a clean provider error / drop a bad count -- rather than
        # stored verbatim and detonating later in a downstream consumer.
        message = _attr_or_key(response, "message", {})
        text = _coerce_ollama_text(_attr_or_key(message, "content", ""))
        prompt_eval = _coerce_ollama_count(
            _attr_or_key(response, "prompt_eval_count", None)
        )
        eval_count = _coerce_ollama_count(
            _attr_or_key(response, "eval_count", None)
        )
        usage: dict[str, int] = {}
        if prompt_eval is not None or eval_count is not None:
            usage = {
                "input_tokens": prompt_eval or 0,
                "output_tokens": eval_count or 0,
            }
        return LLMResponse(text=text, model=model, usage=usage)

    # CRITICAL: source BOTH exception tuples from the `ollama` namespace ONLY
    # (its documented public error types), never `httpx` or any other module.
    # That keeps `_create_ollama` construction dependent solely on `ollama`, so
    # a single self-contained stub module suffices to prove the present-SDK path
    # offline. `ResponseError`->throttle / `RequestError`->timeout is a
    # best-effort taxonomy consistent with the other adapters; its precision is
    # unobservable offline (the live `.chat()` path is untested by design).
    return _SdkAdapter(
        complete_fn=_complete,
        throttle_excs=(ollama.ResponseError,),
        timeout_excs=(ollama.RequestError,),
    )


def _create_groq(settings: Settings) -> LLMClient:
    """Build a client backed by a Groq-hosted model (SDK imported lazily, by design).

    WHY this is a near-verbatim clone of `_create_openai`: the `groq` SDK is an
    OpenAI-SDK-shaped clone -- same construction (`groq.Groq()`), same call
    surface (`sdk.chat.completions.create(model=..., messages=[...])`), same
    reply/usage shape (`completion.choices[0].message.content`,
    `completion.usage.prompt_tokens`/`.completion_tokens`), and the same
    throttle/timeout exception NAMES (`groq.RateLimitError` /
    `groq.APITimeoutError`). So this branch is `_create_openai` with the
    namespace and model default swapped, which is why it now reuses `_require`,
    `_openai_wire_complete_fn` and `_SdkAdapter` with zero change. Groq is a
    cloud backend that serves open models (Llama, Mixtral, ...) on its LPU
    inference stack, so it needs an API key and network egress at CALL time --
    but, exactly like every other live branch, construction opens no connection.
    """
    groq = _require("groq", "groq")  # actionable LLMError if absent

    sdk = groq.Groq()
    model = settings.model or "llama-3.3-70b-versatile"

    # CRITICAL (same invariant as the ollama branch): source BOTH exception
    # tuples from the `groq` namespace ONLY, never `httpx` or any other module,
    # so `_create_groq` construction depends solely on `groq` and a single
    # self-contained stub module can exercise the present-SDK path fully offline.
    return _SdkAdapter(
        complete_fn=_openai_wire_complete_fn(sdk=sdk, model=model),
        throttle_excs=(groq.RateLimitError,),
        timeout_excs=(groq.APITimeoutError,),
    )


def _create_together(settings: Settings) -> LLMClient:
    """Build a client backed by a Together AI-hosted open model (SDK lazy, by design).

    WHY this is a near-verbatim clone of `_create_groq` (and thus `_create_openai`):
    the `together` SDK is a Stainless-generated, OpenAI-SDK-shaped client -- same
    zero-arg construction (`together.Together()`, which reads `TOGETHER_API_KEY`
    from the environment and opens NO connection at construction), same call
    surface (`sdk.chat.completions.create(model=..., messages=[...])`), same
    reply/usage shape (`completion.choices[0].message.content`,
    `completion.usage.prompt_tokens`/`.completion_tokens`), and the same top-level
    throttle/timeout exception NAMES (`together.RateLimitError` /
    `together.APITimeoutError`, verified against the published `together` package's
    documented error taxonomy). So this branch is `_create_groq` with the namespace
    and model default swapped, which is why it now reuses `_require`,
    `_openai_wire_complete_fn` and `_SdkAdapter` with zero change. Together AI is
    a CLOUD backend serving open models (Llama, Mixtral, ...) on its inference
    stack, so it needs an API key and network egress at CALL time -- but, exactly
    like every other live branch, construction opens no connection.
    """
    together = _require("together", "together")  # actionable LLMError if absent

    sdk = together.Together()
    model = settings.model or "meta-llama/Llama-3.3-70B-Instruct-Turbo"

    # CRITICAL (same invariant as the ollama/groq branches): source BOTH exception
    # tuples from the `together` namespace ONLY, never `httpx` or any other module,
    # so `_create_together` construction depends solely on `together` and a single
    # self-contained stub module can exercise the present-SDK path fully offline.
    return _SdkAdapter(
        complete_fn=_openai_wire_complete_fn(sdk=sdk, model=model),
        throttle_excs=(together.RateLimitError,),
        timeout_excs=(together.APITimeoutError,),
    )


__all__ = ["create_client", "VALID_PROVIDERS"]
