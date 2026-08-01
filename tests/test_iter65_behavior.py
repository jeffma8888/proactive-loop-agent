"""Black-box behavior tests for iteration 65.

Feature under test: a 7th ``create_client`` provider branch, ``together``, in
``llm/providers.py``. ``together`` is a CLOUD backend serving Together AI-hosted
open models (Llama/Mixtral/...) on Together's inference stack. Its Python SDK is
a Stainless-generated, OpenAI-SDK-shaped clone, so ``_create_together`` is a
near-verbatim mirror of ``_create_groq`` (iter-49): a lazy ``together.Together()``
(zero-arg, reads ``TOGETHER_API_KEY`` from the environment, no network at
construction), ``sdk.chat.completions.create(...)`` at call time, usage from
``completion.usage.prompt_tokens``/``.completion_tokens``, ``model`` defaulting to
``"meta-llama/Llama-3.3-70B-Instruct-Turbo"``, and its throttle/timeout exception
taxonomy sourced from the ``together`` namespace ONLY (``together.RateLimitError``
-> throttle, ``together.APITimeoutError`` -> timeout) so the branch depends on no
second SDK/transport (e.g. ``httpx``) and construction stays offline-constructible
from a single self-contained stub. Purely additive -- no version bump.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's PM spec "Expected Behaviors" 1-8, ``README.md``,
and ``SPEC.md`` (the public design contract, esp. section 4.2) -- and drive only
the documented public surface: ``create_client(Settings(...))`` and
``VALID_PROVIDERS`` (from ``proactive_loop.llm.providers``), the ``pla`` CLI via
``proactive_loop.cli.main([...])`` (capturing stdout/stderr + exit code), the
public types ``LLMClient`` / ``LLMError`` / ``LLMResponse`` (from
``proactive_loop.llm.client``), and ``proactive_loop.__version__``. NO file under
``src/`` was read for implementation detail, no engineer/reviewer notes were
consulted, and no ``git diff`` was inspected. A missing SDK is forced
deterministically with ``monkeypatch.setitem(sys.modules, "together", None)`` (per
CPython import semantics a ``None`` entry makes both ``import together`` and
``importlib.import_module("together")`` raise ``ImportError`` regardless of whether
the real package is installed); a PRESENT SDK is faked with a self-contained
in-memory stub module. Every test runs fully offline with ZERO real SDKs
installed -- no network, no API keys.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.llm.client import LLMClient, LLMError, LLMResponse
from proactive_loop.llm.providers import VALID_PROVIDERS, create_client

# The optional runtime modules whose absence on the scripted path proves the
# offline guarantee (EB6). ``together`` is the new backend; ``httpx`` is the HTTP
# transport an OpenAI-shaped SDK uses under the hood -- the spec forbids the
# together branch from importing it, so neither may leak onto the default path.
_OFFLINE_GUARD_MODULES = ("together", "httpx")
_TRACEBACK = "Traceback (most recent call last)"

# EB4a -- the documented default model when Settings.model is unset.
_DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

# EB4b leak-guard -- every OTHER live provider's SDK plus the httpx transport. If
# _create_together imported ANY of these at construction, forcing them to None
# would make construction raise; a passing EB4b proves the branch depends solely
# on the top-level ``together`` namespace.
_OTHER_SDK_MODULES = ("httpx", "openai", "groq", "boto3", "anthropic", "ollama")


def _write_script(tmp_path: Path) -> Path:
    """Write a minimal, valid scripted-responses file and return its path."""
    script = [
        {"tag": "synthesize", "text": "hello from script"},
        {"tag": "", "text": "wildcard response"},
    ]
    path = tmp_path / "scripted_responses.json"
    path.write_text(json.dumps(script))
    return path


def _make_together_stub(
    content: str = "canned together reply",
    prompt_tokens: int = 7,
    completion_tokens: int = 11,
) -> types.ModuleType:
    """A self-contained in-memory ``together`` stub (EB4).

    An OpenAI-SDK-shaped clone (per the PM spec): a permissive zero-arg
    ``Together`` client whose ``.chat.completions.create(...)`` returns an object
    exposing ``.choices[0].message.content`` and
    ``.usage.prompt_tokens`` / ``.usage.completion_tokens``, plus the two public
    error types ``RateLimitError`` / ``APITimeoutError`` the adapter resolves at
    construction. Exposes ONLY the ``together`` namespace and imports nothing else,
    so a passing EB4b proves ``_create_together`` touches ONLY that namespace (no
    second SDK/transport, no network). ``stub.calls`` records every completion call
    so a test can prove construction never issues one (lazy construction).
    """
    stub = types.ModuleType("together")

    class _Completions:
        def create(self, **kwargs):
            stub.calls.append(kwargs)
            return types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        message=types.SimpleNamespace(content=content)
                    )
                ],
                usage=types.SimpleNamespace(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                ),
            )

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class Together:
        # Zero required args per the spec (reads TOGETHER_API_KEY from env, opens
        # no connection); tolerant of any args/kwargs the adapter may pass.
        def __init__(self, *args, **kwargs) -> None:
            self.chat = _Chat()

    class RateLimitError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    stub.Together = Together
    stub.RateLimitError = RateLimitError
    stub.APITimeoutError = APITimeoutError
    stub.calls = []
    return stub


# ===========================================================================
# Behavior 1 -- together is a registered provider, appended LAST (index 6),
# and the first six entries are unchanged.
# ===========================================================================


def test_behavior1_together_is_registered_provider_appended_last():
    assert "together" in VALID_PROVIDERS, "'together' must be a registered provider"
    assert VALID_PROVIDERS[6] == "together", (
        f"together must be the SEVENTH provider (index 6); got {VALID_PROVIDERS!r}"
    )
    assert VALID_PROVIDERS[:6] == (
        "scripted",
        "anthropic",
        "openai",
        "bedrock",
        "ollama",
        "groq",
    ), (
        "the first six providers must be unchanged (groq stays last of the "
        f"original set); got {VALID_PROVIDERS!r}"
    )


# ===========================================================================
# Behavior 2 -- missing together SDK -> actionable LLMError at the API level
# (names the package, carries `pip install together`, points at the scripted
# fallback, and is NOT a raw ModuleNotFoundError).
# ===========================================================================


def test_behavior2_missing_together_sdk_raises_actionable_llm_error(monkeypatch):
    # Force `import together` / importlib.import_module("together") to raise.
    monkeypatch.setitem(sys.modules, "together", None)

    with pytest.raises(LLMError) as excinfo:
        create_client(Settings(provider="together"))

    # A missing SDK must surface as an LLMError, NOT a raw ImportError /
    # ModuleNotFoundError (the latter is a subclass of ImportError).
    assert not isinstance(excinfo.value, ImportError), (
        "a missing together SDK must surface as an LLMError, not a raw "
        "ModuleNotFoundError/ImportError"
    )
    message = str(excinfo.value)
    for needle in ("together", "pip install together", "--provider scripted"):
        assert needle in message, (
            f"missing-SDK message must contain {needle!r}; got:\n{message!r}"
        )


# ===========================================================================
# Behavior 3 -- CLI end-to-end missing SDK -> exit 1, single `error:` line,
# no traceback, carries the pip-install fix.
# ===========================================================================


def test_behavior3_cli_missing_together_sdk_exit1_single_error_line_no_traceback(
    tmp_path, capsys, monkeypatch
):
    # A REAL existing --workspace so the pre-existing workspace guard does NOT
    # fire first; the live client is built eagerly (before any collect), so the
    # missing-SDK LLMError raises before any network access.
    monkeypatch.setitem(sys.modules, "together", None)
    capsys.readouterr()  # drain any prior output

    rc = main([
        "scan",
        "--workspace", str(tmp_path),
        "--provider", "together",
        "--state-dir", str(tmp_path),
    ])
    err = capsys.readouterr().err

    assert rc == 1, f"a missing together SDK must exit 1 (foreseeable env fault), got {rc}"
    assert _TRACEBACK not in err, f"stderr must NOT contain a traceback; got:\n{err!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, (
        f"stderr must be a SINGLE error line (no traceback, no extra logs); got:\n{err!r}"
    )
    assert err_lines[0].startswith("error: "), (
        f"the stderr line must begin with 'error: '; got:\n{err_lines[0]!r}"
    )
    assert "together" in err, (
        f"the CLI error line must name the together package; got:\n{err!r}"
    )
    assert "pip install together" in err, (
        f"the CLI error line must carry the one-line fix instruction; got:\n{err!r}"
    )


# ===========================================================================
# Behavior 4a -- present-SDK stub constructs a working client that parses the
# reply: text, usage token mapping, and the default model.
# ===========================================================================


def test_behavior4a_present_together_stub_parses_reply(monkeypatch):
    stub = _make_together_stub(
        content="canned together reply", prompt_tokens=7, completion_tokens=11
    )
    monkeypatch.setitem(sys.modules, "together", stub)

    resp = create_client(Settings(provider="together")).complete(
        system="s", prompt="p", tag="synthesize"
    )

    assert isinstance(resp, LLMResponse), (
        "a present together SDK must yield an LLMResponse from .complete()"
    )
    assert resp.text == "canned together reply", (
        f"together text must read choices[0].message.content; got {resp.text!r}"
    )
    assert resp.usage == {"input_tokens": 7, "output_tokens": 11}, (
        "together usage must map input_tokens<-prompt_tokens and "
        f"output_tokens<-completion_tokens; got {resp.usage!r}"
    )
    assert resp.model == _DEFAULT_MODEL, (
        f"together default model mismatch when Settings.model is unset; got {resp.model!r}"
    )


# ===========================================================================
# Behavior 4b -- construction touches ONLY the together namespace (leak-guard):
# with httpx/openai/groq/boto3/anthropic/ollama all forced absent AND only the
# self-contained together stub present, construction still succeeds -- and issues
# NO completion call (lazy construction).
# ===========================================================================


def test_behavior4b_construction_touches_only_together_namespace(monkeypatch):
    for name in _OTHER_SDK_MODULES:
        monkeypatch.setitem(sys.modules, name, None)  # any import would now raise
    stub = _make_together_stub()
    monkeypatch.setitem(sys.modules, "together", stub)

    client = create_client(Settings(provider="together"))

    assert isinstance(client, LLMClient), (
        "construction must depend on the together namespace ONLY (no second "
        "SDK / no httpx transport)"
    )
    assert stub.calls == [], (
        "construction must be lazy -- no completion call may be issued until "
        f".complete() is invoked; got calls={stub.calls!r}"
    )


# ===========================================================================
# Behavior 5 -- unknown provider still raises ValueError listing every option
# (now including together); a config typo stays distinct from a missing SDK.
# ===========================================================================


def test_behavior5_unknown_provider_value_error_lists_all_options_incl_together():
    with pytest.raises(ValueError) as excinfo:
        create_client(Settings(provider="does-not-exist"))

    # A config typo is a ValueError; a missing SDK is an LLMError -- distinct faults.
    assert not isinstance(excinfo.value, LLMError), (
        "an unknown provider must stay a ValueError, not be reclassified as LLMError"
    )
    message = str(excinfo.value)
    for option in VALID_PROVIDERS:
        assert option in message, (
            f"unknown-provider error must list every valid option; missing {option!r} in:\n{message!r}"
        )
    assert "together" in message, "the unknown-provider error must now list 'together' too"


# ===========================================================================
# Behavior 6 -- scripted default path imports NEITHER together NOR httpx
# (the load-bearing lazy-import-in-branch invariant).
# ===========================================================================


def test_behavior6_scripted_path_imports_no_together_or_httpx(tmp_path):
    # Drop any pre-existing together/httpx entries first, build+use the scripted
    # client, then assert NONE reappeared as a truthy module. If the together
    # import leaked to module scope or onto the default path, it would import here.
    for name in list(sys.modules):
        if name.split(".")[0] in _OFFLINE_GUARD_MODULES:
            del sys.modules[name]

    settings = Settings(provider="scripted", scripted_responses_path=_write_script(tmp_path))
    client = create_client(settings)
    client.complete(system="s", prompt="p", tag="synthesize")

    assert not sys.modules.get("together"), (
        "the scripted path must not import 'together' (offline-first no-leak invariant)"
    )
    leaked = [name for name in _OFFLINE_GUARD_MODULES if sys.modules.get(name)]
    assert leaked == [], f"scripted path must import neither together nor httpx; leaked: {leaked}"


# ===========================================================================
# Behavior 7 -- no version bump (purely additive provider).
# ===========================================================================


def test_behavior7_no_version_bump_additive_provider():
    import proactive_loop

    assert proactive_loop.__version__ == "0.1.1", (
        "adding a provider is purely additive (no existing provider's behavior "
        "changes), exactly like iters 09/11/13/17/21/23/32/49 -- so no version bump"
    )


# ===========================================================================
# Behavior 8 -- scripted default run pipeline is byte-stable end-to-end
# (the `make demo` contract as an in-process proxy: the --provider scripted path
# is untouched). Driven via main() so no `make`/subprocess is needed.
# ===========================================================================


def test_behavior8_scripted_run_pipeline_still_succeeds_and_writes_artifacts(
    tmp_path, capsys, monkeypatch
):
    # Even with the together SDK forced absent, the scripted default path must run
    # the full pipeline unchanged (exit 0, artifacts written).
    monkeypatch.setitem(sys.modules, "together", None)

    repo_root = Path(__file__).resolve().parents[1]
    fixture_ws = repo_root / "examples" / "fixture_workspace"
    scripted = repo_root / "examples" / "scripted_responses.json"
    assert fixture_ws.is_dir(), "the demo fixture workspace must exist"
    assert scripted.is_file(), "the demo scripted-responses file must exist"

    state_dir = tmp_path / "pla_runs"
    capsys.readouterr()  # drain

    rc = main([
        "run",
        "--workspace", str(fixture_ws),
        "--provider", "scripted",
        "--scripted-responses", str(scripted),
        "--state-dir", str(state_dir),
    ])

    assert rc == 0, f"the scripted default run pipeline must exit 0; got {rc}"
    artifacts = list(state_dir.rglob("*.md"))
    assert artifacts, (
        f"the scripted run must produce artifact files under {state_dir}; found none"
    )
