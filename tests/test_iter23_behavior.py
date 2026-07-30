"""Black-box behavior tests for iteration 23.

Feature under test: the live provider adapters (``anthropic`` / ``openai`` /
``bedrock``) must raise an *actionable* ``LLMError`` -- naming the missing pip
package and the ``--provider scripted`` fallback -- when their optional SDK is
not installed, INSTEAD of leaking a raw ``ModuleNotFoundError`` traceback. This
closes iter-02's narrow ``main()`` error-boundary (``except (LLMError,
ValueError, OSError)``) for the one foreseeable environment fault it currently
misses: the obvious happy-path misconfiguration of selecting a live provider
whose SDK is absent. See SPEC.md 4.2 (the ``create_client`` contract) and this
iteration's PM "Expected Behaviors" 1-7.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's PM spec "Expected Behaviors", ``README.md``,
and ``SPEC.md`` (the public design contract, esp. 4.2) -- and drive only the
documented public surface: ``create_client(Settings(...))`` (from
``proactive_loop.llm.providers``), the ``pla`` CLI via
``proactive_loop.cli.main([...])`` (capturing stdout/stderr + exit code), and
the public error/protocol types ``LLMError`` / ``LLMClient`` (from
``proactive_loop.llm.client``). NO file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted. A missing
SDK is forced deterministically with ``monkeypatch.setitem(sys.modules, <pkg>,
None)`` (per CPython import semantics a ``None`` entry makes both ``import X``
and ``importlib.import_module("X")`` raise ``ImportError`` regardless of whether
the real package exists), so every test runs fully offline with ZERO real SDKs
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
from proactive_loop.llm.client import LLMClient, LLMError
from proactive_loop.llm.providers import VALID_PROVIDERS, create_client

# The optional SDKs whose absence must NOT crash with a raw traceback, and whose
# non-import on the scripted path proves the offline guarantee (SPEC.md 4.2).
_SDK_MODULES = ("anthropic", "openai", "boto3", "botocore")
_TRACEBACK = "Traceback (most recent call last)"


def _write_script(tmp_path: Path) -> Path:
    """Write a minimal, valid scripted-responses file and return its path."""
    script = [
        {"tag": "synthesize", "text": "hello from script"},
        {"tag": "", "text": "wildcard response"},
    ]
    path = tmp_path / "scripted_responses.json"
    path.write_text(json.dumps(script))
    return path


# ===========================================================================
# Behavior 1 -- anthropic SDK missing -> actionable LLMError (API level)
# ===========================================================================


def test_behavior1_anthropic_missing_raises_actionable_llm_error(monkeypatch):
    # Force `import anthropic` / importlib.import_module("anthropic") to raise.
    monkeypatch.setitem(sys.modules, "anthropic", None)

    with pytest.raises(LLMError) as excinfo:
        create_client(Settings(provider="anthropic"))

    # NOT a bare ImportError/ModuleNotFoundError -- the guard reclassifies it.
    assert not isinstance(excinfo.value, ImportError), (
        "a missing live SDK must surface as an LLMError, not a raw ImportError"
    )
    message = str(excinfo.value)
    for needle in ("anthropic", "pip install anthropic", "--provider scripted"):
        assert needle in message, (
            f"missing-SDK message must contain {needle!r}; got:\n{message!r}"
        )


# ===========================================================================
# Behavior 2 -- openai SDK missing -> actionable LLMError
# ===========================================================================


def test_behavior2_openai_missing_raises_actionable_llm_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)

    with pytest.raises(LLMError) as excinfo:
        create_client(Settings(provider="openai"))

    assert not isinstance(excinfo.value, ImportError)
    message = str(excinfo.value)
    for needle in ("openai", "pip install openai", "--provider scripted"):
        assert needle in message, (
            f"missing-SDK message must contain {needle!r}; got:\n{message!r}"
        )


# ===========================================================================
# Behavior 3 -- bedrock SDK missing -> LLMError naming the PACKAGE (boto3),
# not the provider label (bedrock)
# ===========================================================================


def test_behavior3_bedrock_missing_names_boto3_package(monkeypatch):
    # boto3 is the pip package for the `bedrock` provider label; guarding the
    # PRIMARY import is enough (botocore is a hard dep of boto3, so it is
    # unreachable when boto3 is absent).
    monkeypatch.setitem(sys.modules, "boto3", None)

    with pytest.raises(LLMError) as excinfo:
        create_client(Settings(provider="bedrock"))

    assert not isinstance(excinfo.value, ImportError)
    message = str(excinfo.value)
    # Proves the hint names the pip package `boto3`, which differs from `bedrock`.
    for needle in ("bedrock", "boto3", "pip install boto3", "--provider scripted"):
        assert needle in message, (
            f"bedrock missing-SDK message must contain {needle!r}; got:\n{message!r}"
        )


# ===========================================================================
# Behavior 4 -- CLI end-to-end: missing SDK -> exit 1 + one `error:` line,
# no traceback (routes through iter-02's narrow main() boundary)
# ===========================================================================


def test_behavior4_cli_missing_sdk_exit1_single_error_line_no_traceback(
    tmp_path, capsys, monkeypatch
):
    # A real, existing --workspace so the pre-existing exit-2 workspace guard
    # does NOT fire first; the live client is constructed eagerly, before any
    # collect/synthesize, so the missing-SDK LLMError raises before any network.
    monkeypatch.setitem(sys.modules, "anthropic", None)
    capsys.readouterr()  # drain any prior output

    rc = main([
        "scan",
        "--workspace", str(tmp_path),
        "--provider", "anthropic",
        "--state-dir", str(tmp_path),
    ])
    err = capsys.readouterr().err

    assert rc == 1, f"a missing live SDK must exit 1 (foreseeable fault), got {rc}"
    assert _TRACEBACK not in err, f"stderr must NOT contain a traceback; got:\n{err!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, (
        f"stderr must be a SINGLE error line (no traceback, no extra logs); got:\n{err!r}"
    )
    assert err_lines[0].startswith("error: "), (
        f"the stderr line must begin with 'error: '; got:\n{err_lines[0]!r}"
    )
    assert "pip install anthropic" in err, (
        f"the CLI error line must carry the one-line fix instruction; got:\n{err!r}"
    )


# ===========================================================================
# Behavior 5 -- Regression: scripted path imports NO provider SDK
# (SPEC.md 4.2 offline invariant preserved; the guard lives in live branches only)
# ===========================================================================


def test_behavior5_scripted_path_leaks_no_sdk_import(tmp_path):
    # Drop any pre-existing SDK entries first (mirrors tests/test_providers.py),
    # build+use the scripted client, then assert NONE reappeared. If the new
    # missing-SDK guard leaked into the default path, an SDK would import here.
    for name in list(sys.modules):
        if name.split(".")[0] in _SDK_MODULES:
            del sys.modules[name]

    settings = Settings(provider="scripted", scripted_responses_path=_write_script(tmp_path))
    client = create_client(settings)
    client.complete(system="s", prompt="p", tag="synthesize")

    leaked = [name for name in _SDK_MODULES if name in sys.modules]
    assert leaked == [], f"scripted path must trip no SDK import; leaked: {leaked}"


# ===========================================================================
# Behavior 6 -- Regression: unknown provider still raises ValueError listing
# every VALID_PROVIDERS entry (missing-SDK guard did not reshape this path)
# ===========================================================================


def test_behavior6_unknown_provider_still_value_error_listing_options():
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
    # Documented set is the four canonical providers.
    for option in ("scripted", "anthropic", "openai", "bedrock"):
        assert option in message


# ===========================================================================
# Behavior 7 -- Positive path: a PRESENT SDK is used, construction succeeds
# (proves the import guard imports-and-returns the module, never unconditionally
# raises)
# ===========================================================================


def test_behavior7_present_sdk_construction_succeeds(monkeypatch):
    # Inject an in-memory stub `anthropic` exposing the three attributes the
    # adapter maps: an `Anthropic` client factory and two SDK exception types.
    stub = types.ModuleType("anthropic")

    class _Anthropic:
        # Zero-arg callable per the spec; tolerant of kwargs the adapter may pass.
        def __init__(self, *args, **kwargs) -> None:
            pass

    class RateLimitError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    stub.Anthropic = _Anthropic
    stub.RateLimitError = RateLimitError
    stub.APITimeoutError = APITimeoutError
    monkeypatch.setitem(sys.modules, "anthropic", stub)

    client = create_client(Settings(provider="anthropic"))

    # The guard must import-and-return; the success path is unbroken.
    assert isinstance(client, LLMClient), (
        "a present SDK must yield a client satisfying the LLMClient protocol"
    )
    assert hasattr(client, "complete") and callable(client.complete)


# ===========================================================================
# Backward-compat -- purely additive error-handling; no version bump
# ===========================================================================


def test_no_version_bump_additive_error_handling():
    import proactive_loop

    assert proactive_loop.__version__ == "0.1.1", (
        "the missing-SDK guard is purely additive error-handling on the live "
        "branches -- no public-contract change, so no version bump"
    )
