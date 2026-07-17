"""Tests for the provider factory (llm/providers.py).

Coverage:
- scripted provider builds a working client from a real temp script file;
- unknown provider raises ValueError listing the valid options;
- CRITICAL: choosing the scripted provider leaks NO provider SDK
  (anthropic / openai / boto3) into sys.modules -- the offline guarantee;
- scripted provider with no configured path returns a client that fails only on
  use, with a message that names the missing setting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from proactive_loop.config import Settings
from proactive_loop.llm.client import LLMClient, LLMError, LLMResponse
from proactive_loop.llm.providers import VALID_PROVIDERS, create_client

# The optional SDKs whose absence proves the scripted path stays offline.
_SDK_MODULES = ("anthropic", "openai", "boto3", "botocore")


def _write_script(tmp_path: Path) -> Path:
    """Write a minimal, valid scripted-responses file and return its path."""
    script = [
        {"tag": "synthesize", "text": "hello from script"},
        {"tag": "", "text": "wildcard response"},
    ]
    path = tmp_path / "scripted_responses.json"
    path.write_text(json.dumps(script))
    return path


def test_scripted_client_from_real_file(tmp_path: Path) -> None:
    """A configured scripted provider returns a client that replays the file."""
    path = _write_script(tmp_path)
    settings = Settings(provider="scripted", scripted_responses_path=path)

    client = create_client(settings)

    assert isinstance(client, LLMClient)  # satisfies the runtime-checkable protocol
    response = client.complete(system="s", prompt="p", tag="synthesize")
    assert isinstance(response, LLMResponse)
    assert response.text == "hello from script"


def test_unknown_provider_raises_value_error_listing_options() -> None:
    """An unrecognized provider fails fast and tells the user what is valid."""
    settings = Settings(provider="does-not-exist")

    with pytest.raises(ValueError) as excinfo:
        create_client(settings)

    message = str(excinfo.value)
    # Every valid option must be named so the error is self-service.
    for option in VALID_PROVIDERS:
        assert option in message


def test_scripted_provider_leaks_no_sdk_import(tmp_path: Path) -> None:
    """The scripted path must never import anthropic / openai / boto3.

    This is the load-bearing offline guarantee: we drop any pre-existing SDK
    entries from sys.modules first, build the scripted client, then assert none
    reappeared. If a future edit hoists an SDK import to module top level, this
    fails.
    """
    for name in list(sys.modules):
        if name.split(".")[0] in _SDK_MODULES:
            del sys.modules[name]

    path = _write_script(tmp_path)
    settings = Settings(provider="scripted", scripted_responses_path=path)

    client = create_client(settings)
    client.complete(system="s", prompt="p", tag="synthesize")

    leaked = [name for name in _SDK_MODULES if name in sys.modules]
    assert leaked == [], f"scripted path leaked SDK imports: {leaked}"


def test_scripted_provider_without_path_fails_on_use_with_clear_message() -> None:
    """No script path => construction succeeds, but the first call explains why.

    Deferring the error to first use (rather than at build time) keeps object
    construction cheap; the message must point at the exact missing setting.
    """
    settings = Settings(provider="scripted", scripted_responses_path=None)

    client = create_client(settings)  # must not raise here

    with pytest.raises(LLMError) as excinfo:
        client.complete(system="s", prompt="p", tag="synthesize")

    message = str(excinfo.value)
    assert "scripted_responses_path" in message
    assert "PLA_SCRIPTED_RESPONSES" in message


def test_scripted_is_the_default_provider(tmp_path: Path) -> None:
    """Settings() defaults to scripted, so create_client works with no provider set."""
    path = _write_script(tmp_path)
    settings = Settings(scripted_responses_path=path)

    assert settings.provider == "scripted"
    client = create_client(settings)
    assert client.complete(system="s", prompt="p", tag="synthesize").text == "hello from script"
