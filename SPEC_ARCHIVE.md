# SPEC archive

Settled contract prose relocated out of [SPEC.md](SPEC.md), verbatim and unedited.

`SPEC.md` remains the entry point and the fixed intent: it keeps every heading, and a section
whose body has moved here keeps a one-paragraph summary plus a link. A contract lands here only
once it has stopped changing, so that the document every iteration must read stays readable --
the same reason `ROADMAP_ARCHIVE.md` exists for the roadmap. Nothing here is a new promise; to
change one of these contracts, move the text back into `SPEC.md` and edit it there.

---

### 4.2 llm/providers.py

```python
def create_client(settings: Settings) -> LLMClient: ...
```

- `VALID_PROVIDERS == ("scripted", "anthropic", "openai", "bedrock", "ollama", "groq", "together")` —
  the single source of accepted provider names, reused verbatim in the
  unknown-provider `ValueError` message and every missing-SDK error path so the
  dispatch and the messages can never drift apart.
- `settings.provider`: `"scripted"` (default) → `ScriptedLLMClient.from_file(settings.scripted_responses_path)`
  (empty client with clear error message if path is None); `"anthropic"` / `"openai"` /
  `"bedrock"` / `"ollama"` / `"groq"` / `"together"` → **lazy import** inside the branch, thin adapter class per
  provider mapping SDK throttle/timeout exceptions to `LLMThrottleError`/`LLMTimeoutError`.
- `"ollama"` is the LOCAL / offline runtime backend: a lazy `ollama.Client()` (no API
  key, no network egress; it talks to a model served on `localhost`), `model` defaults
  to `"llama3.1"`, and its throttle/timeout exception taxonomy is sourced from the
  `ollama` namespace ONLY (`ollama.ResponseError` → throttle, `ollama.RequestError` →
  timeout) so the branch depends on no second SDK and construction stays offline. It
  extends the offline-first thesis (section 5) from the scripted test double to real
  runtime execution. Its reply is COERCED at the provider boundary in `_create_ollama._complete` (see 4.2): the message `content` is coerced to `str` (missing / `None` -> `""`; a PRESENT non-`str` content raises a clean `LLMError` naming `ollama` instead of being stored verbatim as `LLMResponse.text` and detonating later in a downstream string/JSON consumer), and each token count (`prompt_eval_count` / `eval_count`) is kept only if a genuine `int` -- a non-`int` (`str`/`float`/`bool`) is dropped so `usage` stays all-`int`. This is behavior-only hardening on the wrong-shape path (no contract addition). Additive, exactly like iter-23 — a new provider whose absence-guard
  and taxonomy reuse the existing machinery, so **no version bump**.
- `"groq"` is a CLOUD backend serving open models (Llama/Mixtral/…) on Groq's LPU
  inference stack. Its SDK is an OpenAI-SDK-shaped clone, so `_create_groq` is a
  near-verbatim mirror of `_create_openai`: a lazy `groq.Groq()` (zero-arg, no network at
  construction), `model` defaults to `"llama-3.3-70b-versatile"`, the completion uses
  `sdk.chat.completions.create(model=…, messages=[{system},{user}])` with usage from
  `completion.usage.prompt_tokens`/`.completion_tokens`, and its throttle/timeout
  exception taxonomy is sourced from the `groq` namespace ONLY (`groq.RateLimitError` →
  throttle, `groq.APITimeoutError` → timeout) so the branch depends on no second
  SDK/transport (e.g. `httpx`) and construction stays offline-constructible from a single
  stub. Additive, exactly like iters 23/32 — a new provider whose absence-guard and
  taxonomy reuse the existing `_require`/`_SdkAdapter` machinery verbatim, so **no version
  bump**.
- `"together"` is a CLOUD backend serving Together AI-hosted open models (Llama, Mixtral,
  …) on Together's inference stack. Its Python SDK is a Stainless-generated,
  OpenAI-SDK-shaped clone, so `_create_together` is a near-verbatim mirror of
  `_create_groq`: a lazy `together.Together()` (zero-arg, reads `TOGETHER_API_KEY` from the
  environment, no network at construction), `model` defaults to
  `"meta-llama/Llama-3.3-70B-Instruct-Turbo"`, the completion uses
  `sdk.chat.completions.create(model=…, messages=[{system},{user}])` with usage from
  `completion.usage.prompt_tokens`/`.completion_tokens`, and its throttle/timeout
  exception taxonomy is sourced from the `together` namespace ONLY
  (`together.RateLimitError` → throttle, `together.APITimeoutError` → timeout) so the
  branch depends on no second SDK/transport (e.g. `httpx`) and construction stays
  offline-constructible from a single stub. Additive, exactly like iters 23/32/49 — a new
  provider whose absence-guard and taxonomy reuse the existing `_require`/`_SdkAdapter`
  machinery verbatim, so **no version bump**.
- Unknown provider → `ValueError` listing valid options (all seven, incl. `ollama`, `groq`
  and `together`).
- A live provider (`anthropic`/`openai`/`bedrock`/`ollama`/`groq`/`together`) selected while its optional
  SDK is not installed → an actionable `LLMError` naming the pip package (e.g. `pip
  install boto3` for `bedrock`, whose package name differs from the label; `pip install
  ollama` for `ollama`; `pip install groq` for `groq`; `pip install together` for
  `together`) and the `--provider scripted`
  fallback — NOT a raw `ModuleNotFoundError` traceback — so the fault routes through
  `main()`'s narrow `except (LLMError, ValueError, OSError)` boundary as a one-line
  `error: ...` + exit 1 like every other environment fault.
- Tests: `tests/test_providers.py` — scripted path works from file; unknown provider
  raises; **prove no `anthropic`/`openai`/`boto3` import leak** when provider=scripted
  (assert not in `sys.modules` after create).
