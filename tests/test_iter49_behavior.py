"""Black-box behavior tests for iteration 49.

Feature under test: a 6th ``create_client`` provider branch, ``groq``, in
``llm/providers.py``. ``groq`` is a CLOUD backend serving open models on Groq's
inference stack; its SDK is an OpenAI-SDK-shaped clone, so ``_create_groq`` is a
near-verbatim mirror of ``_create_openai`` (lazy ``groq.Groq()`` at construction
with no network, ``sdk.chat.completions.create(...)`` at call time, exception
taxonomy ``groq.RateLimitError`` -> throttle / ``groq.APITimeoutError`` ->
timeout). The change is purely additive (mirrors iters 09/11/13/17/21/23/32): the
optional ``groq`` SDK is imported lazily INSIDE its own branch, reuses the shared
missing-SDK guard for an actionable ``LLMError``, and sources BOTH exception
tuples from the ``groq`` namespace ONLY -- so construction is fully
offline-constructible from a single self-contained stub. No version bump.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's PM spec "Expected Behaviors" 1-9, ``README.md``,
and ``SPEC.md`` (the public design contract, esp. section 4.2) -- and drive only
the documented public surface: ``create_client(Settings(...))`` and
``VALID_PROVIDERS`` (from ``proactive_loop.llm.providers``), the ``pla`` CLI via
``proactive_loop.cli.main([...])`` (capturing stdout/stderr + exit code), the
public types ``LLMClient`` / ``LLMError`` (from ``proactive_loop.llm.client``),
and ``proactive_loop.__version__``. NO file under ``src/`` was read, no
engineer/reviewer notes were consulted, and no ``git diff`` was inspected. A
missing SDK is forced deterministically with ``monkeypatch.setitem(sys.modules,
"groq", None)`` (per CPython import semantics a ``None`` entry makes both
``import groq`` and ``importlib.import_module("groq")`` raise ``ImportError``
regardless of whether the real package is installed); a PRESENT SDK is faked with
a self-contained in-memory stub module. Every test runs fully offline with ZERO
real SDKs installed -- no network, no API keys.
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

# The optional runtime SDKs whose absence on the scripted path proves the offline
# guarantee (EB6). ``groq`` is the new backend; ``httpx`` is the HTTP transport an
# OpenAI-shaped SDK uses under the hood -- the spec forbids the groq branch from
# importing it, so neither may leak onto the default scripted path.
_OFFLINE_GUARD_MODULES = ("groq", "httpx")
_TRACEBACK = "Traceback (most recent call last)"

# EB9 -- sibling live branches whose construction behavior must stay unchanged.
# Maps provider name -> (sys.modules key to force absent, pip-package name the
# actionable LLMError must name). ``bedrock`` is served by the ``boto3`` SDK.
_SIBLING_LIVE_PROVIDERS = [
    ("anthropic", "anthropic", "anthropic"),
    ("openai", "openai", "openai"),
    ("bedrock", "boto3", "boto3"),
    ("ollama", "ollama", "ollama"),
]


def _write_script(tmp_path: Path) -> Path:
    """Write a minimal, valid scripted-responses file and return its path."""
    script = [
        {"tag": "synthesize", "text": "hello from script"},
        {"tag": "", "text": "wildcard response"},
    ]
    path = tmp_path / "scripted_responses.json"
    path.write_text(json.dumps(script))
    return path


def _make_groq_stub() -> types.ModuleType:
    """A self-contained in-memory ``groq`` stub (EB4).

    Exposes EXACTLY the three attributes the groq adapter references at
    construction time -- a permissive ``Groq`` class (zero-arg constructor whose
    ``.chat`` is NEVER touched during construction) and the two OpenAI-shaped
    public error types ``RateLimitError`` / ``APITimeoutError`` -- and imports
    nothing else, so a passing EB4 proves ``_create_groq`` touches ONLY the
    ``groq`` namespace (no second SDK/transport, no network).
    """
    stub = types.ModuleType("groq")

    class Groq:
        # Zero required args per the spec; tolerant of any args/kwargs the
        # adapter may pass at construction.
        def __init__(self, *args, **kwargs) -> None:
            pass

        @property
        def chat(self):  # pragma: no cover - must NOT be touched at construction
            raise AssertionError(
                "stub .chat must NOT be accessed during client construction"
            )

    class RateLimitError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    stub.Groq = Groq
    stub.RateLimitError = RateLimitError
    stub.APITimeoutError = APITimeoutError
    return stub


# ===========================================================================
# Behavior 1 -- groq is a registered provider, appended LAST, order preserved
# ===========================================================================


def test_behavior1_groq_is_registered_provider_appended_last():
    assert "groq" in VALID_PROVIDERS, "'groq' must be a registered provider"
    # The five existing entries are unchanged and groq is appended last.
    assert VALID_PROVIDERS == (
        "scripted",
        "anthropic",
        "openai",
        "bedrock",
        "ollama",
        "groq",
    ), f"VALID_PROVIDERS must be the six-tuple with groq last; got {VALID_PROVIDERS!r}"


# ===========================================================================
# Behavior 2 -- missing groq SDK -> actionable LLMError at the API level
# ===========================================================================


def test_behavior2_missing_groq_sdk_raises_actionable_llm_error(monkeypatch):
    # Force `import groq` / importlib.import_module("groq") to raise ImportError.
    monkeypatch.setitem(sys.modules, "groq", None)

    with pytest.raises(LLMError) as excinfo:
        create_client(Settings(provider="groq"))

    # A missing SDK must surface as an LLMError, NOT a raw ImportError.
    assert not isinstance(excinfo.value, ImportError), (
        "a missing groq SDK must surface as an LLMError, not a raw ImportError"
    )
    message = str(excinfo.value)
    for needle in ("groq", "pip install groq", "--provider scripted"):
        assert needle in message, (
            f"missing-SDK message must contain {needle!r}; got:\n{message!r}"
        )


# ===========================================================================
# Behavior 3 -- CLI end-to-end missing SDK -> exit 1, single `error:` line,
# no traceback, carries the pip-install fix
# ===========================================================================


def test_behavior3_cli_missing_groq_sdk_exit1_single_error_line_no_traceback(
    tmp_path, capsys, monkeypatch
):
    # A REAL existing --workspace so the pre-existing exit-2 workspace guard does
    # NOT fire first; the live client is built eagerly (before any collect), so
    # the missing-SDK LLMError raises before any network access.
    monkeypatch.setitem(sys.modules, "groq", None)
    capsys.readouterr()  # drain any prior output

    rc = main([
        "scan",
        "--workspace", str(tmp_path),
        "--provider", "groq",
        "--state-dir", str(tmp_path),
    ])
    err = capsys.readouterr().err

    assert rc == 1, f"a missing groq SDK must exit 1 (foreseeable env fault), got {rc}"
    assert _TRACEBACK not in err, f"stderr must NOT contain a traceback; got:\n{err!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, (
        f"stderr must be a SINGLE error line (no traceback, no extra logs); got:\n{err!r}"
    )
    assert err_lines[0].startswith("error: "), (
        f"the stderr line must begin with 'error: '; got:\n{err_lines[0]!r}"
    )
    assert "pip install groq" in err, (
        f"the CLI error line must carry the one-line fix instruction; got:\n{err!r}"
    )


# ===========================================================================
# Behavior 4 -- present-SDK stub constructs a working client, touching ONLY the
# groq namespace (no network, no second SDK/transport)
# ===========================================================================


def test_behavior4a_present_groq_stub_constructs_working_client(monkeypatch):
    stub = _make_groq_stub()
    monkeypatch.setitem(sys.modules, "groq", stub)

    client = create_client(Settings(provider="groq"))

    assert isinstance(client, LLMClient), (
        "a present groq SDK must yield a client satisfying the LLMClient protocol"
    )
    assert hasattr(client, "complete") and callable(client.complete), (
        "the constructed client must expose a callable .complete"
    )


def test_behavior4b_construction_touches_only_groq_namespace(monkeypatch):
    # EB4's CRITICAL constraint: with `httpx` forced absent AND only the
    # self-contained `groq` stub present, construction must STILL succeed --
    # proving _create_groq references NO non-groq module at construction time
    # (the offline-purity invariant, exactly as the ollama branch pins for httpx).
    monkeypatch.setitem(sys.modules, "httpx", None)  # any httpx import would now raise
    stub = _make_groq_stub()
    monkeypatch.setitem(sys.modules, "groq", stub)

    client = create_client(Settings(provider="groq"))

    assert isinstance(client, LLMClient), (
        "construction must depend on the groq namespace ONLY (no httpx / second SDK)"
    )


# ===========================================================================
# Behavior 5 -- unknown provider still raises ValueError listing every option
# (now including groq); a config typo stays distinct from a missing SDK
# ===========================================================================


def test_behavior5_unknown_provider_value_error_lists_all_options_incl_groq():
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
    assert "groq" in message, "the unknown-provider error must now list 'groq' too"


# ===========================================================================
# Behavior 6 -- scripted default path imports NEITHER groq NOR httpx
# (the load-bearing lazy-import-in-branch invariant)
# ===========================================================================


def test_behavior6_scripted_path_imports_no_groq_or_httpx(tmp_path):
    # Drop any pre-existing groq/httpx entries first, build+use the scripted
    # client, then assert NONE reappeared. If the groq import leaked to module
    # scope or onto the default path, one of these would import here.
    for name in list(sys.modules):
        if name.split(".")[0] in _OFFLINE_GUARD_MODULES:
            del sys.modules[name]

    settings = Settings(provider="scripted", scripted_responses_path=_write_script(tmp_path))
    client = create_client(settings)
    client.complete(system="s", prompt="p", tag="synthesize")

    leaked = [name for name in _OFFLINE_GUARD_MODULES if name in sys.modules]
    assert leaked == [], f"scripted path must import neither groq nor httpx; leaked: {leaked}"


# ===========================================================================
# Behavior 7 -- no version bump (purely additive provider)
# ===========================================================================


def test_behavior7_no_version_bump_additive_provider():
    import proactive_loop

    assert proactive_loop.__version__ == "0.1.1", (
        "adding a provider is purely additive (no existing provider's behavior "
        "changes), exactly like iters 09/11/13/17/21/23/32 -- so no version bump"
    )


# ===========================================================================
# Behavior 8 -- scripted default run pipeline is byte-stable end-to-end
# (the `make demo` contract as an in-process proxy: --provider scripted path is
# untouched). Driven via main() so no `make`/subprocess is needed.
# ===========================================================================


def test_behavior8_scripted_run_pipeline_still_succeeds_and_writes_artifacts(
    tmp_path, capsys, monkeypatch
):
    # Even with the groq SDK forced absent, the scripted default path must run the
    # full scan->auto-dispatch pipeline unchanged (exit 0, artifacts written).
    monkeypatch.setitem(sys.modules, "groq", None)

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


# ===========================================================================
# Behavior 9 -- adding groq disturbs NO existing provider branch
# (each sibling live branch's missing-SDK construction behavior is unchanged;
# the scripted branch still constructs)
# ===========================================================================


@pytest.mark.parametrize(
    "provider,sdk_module,pip_pkg",
    _SIBLING_LIVE_PROVIDERS,
    ids=[p[0] for p in _SIBLING_LIVE_PROVIDERS],
)
def test_behavior9_sibling_live_branches_unchanged(
    provider, sdk_module, pip_pkg, monkeypatch
):
    # With this sibling's own SDK forced absent, its construction must STILL
    # raise an actionable LLMError (NOT a raw ImportError) that names its pip
    # package -- proving the groq addition did not perturb its branch.
    monkeypatch.setitem(sys.modules, sdk_module, None)

    with pytest.raises(LLMError) as excinfo:
        create_client(Settings(provider=provider))

    assert not isinstance(excinfo.value, ImportError), (
        f"a missing {sdk_module} SDK for provider {provider!r} must surface as an "
        "LLMError, not a raw ImportError"
    )
    message = str(excinfo.value)
    assert pip_pkg in message, (
        f"the {provider!r} missing-SDK error must name its pip package "
        f"{pip_pkg!r}; got:\n{message!r}"
    )


def test_behavior9_scripted_branch_still_constructs(tmp_path):
    # The always-offline scripted branch must still build a working client from a
    # valid scripted-responses file (unchanged by the groq addition).
    settings = Settings(
        provider="scripted", scripted_responses_path=_write_script(tmp_path)
    )
    client = create_client(settings)

    assert isinstance(client, LLMClient), (
        "the scripted branch must still construct an LLMClient after adding groq"
    )
    assert hasattr(client, "complete") and callable(client.complete)
