"""Black-box behavior tests for iteration 32.

Feature under test: a new ``ollama`` LOCAL-model provider in ``create_client``
(``llm/providers.py``). It is the first OFFLINE runtime backend -- a user with a
locally-hosted model (the ``ollama`` server on ``localhost``) runs the full
plan->act->check loop with NO API key and NO network egress, extending the
product's offline-first thesis (SPEC.md section 5) from the ``scripted`` test
double to real execution. The provider is purely additive (mirrors iter-23): it
lazily imports the optional ``ollama`` SDK inside its own branch, reuses the
iter-23 missing-SDK guard for an actionable ``LLMError``, and sources its
throttle/timeout exception taxonomy from the ``ollama`` namespace ONLY, so
construction is fully offline-constructible from a single self-contained stub.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's PM spec "Expected Behaviors" 1-8, ``README.md``,
and ``SPEC.md`` (the public design contract, esp. 4.2) -- and drive only the
documented public surface: ``create_client(Settings(...))`` and ``VALID_PROVIDERS``
(from ``proactive_loop.llm.providers``), the ``pla`` CLI via
``proactive_loop.cli.main([...])`` (capturing stdout/stderr + exit code), the
public types ``LLMClient`` / ``LLMError`` (from ``proactive_loop.llm.client``),
and ``proactive_loop.__version__``. NO file under ``src/`` was read, no
engineer/reviewer notes were read, and no ``git diff`` was consulted. A missing
SDK is forced deterministically with ``monkeypatch.setitem(sys.modules,
"ollama", None)`` (per CPython import semantics a ``None`` entry makes both
``import ollama`` and ``importlib.import_module("ollama")`` raise ``ImportError``
regardless of whether the real package exists); a PRESENT SDK is faked with a
self-contained in-memory stub module. Every test runs fully offline with ZERO
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

# The optional runtime SDKs whose absence on the scripted path proves the
# offline guarantee (EB6). ``ollama`` is the new backend; ``httpx`` is the HTTP
# lib the ``ollama`` SDK uses under the hood -- the spec forbids the ollama
# branch from importing it, so neither may leak onto the default path.
_OFFLINE_GUARD_MODULES = ("ollama", "httpx")
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


def _make_ollama_stub() -> types.ModuleType:
    """A self-contained in-memory ``ollama`` stub (EB4).

    Exposes EXACTLY the three attributes the ollama adapter references at
    construction time -- a permissive ``Client`` class and the two documented
    public error types ``ResponseError`` / ``RequestError`` -- and imports
    nothing else, so a passing EB4 proves ``_create_ollama`` touches ONLY the
    ``ollama`` namespace (no second SDK, no network).
    """
    stub = types.ModuleType("ollama")

    class Client:
        # Zero-arg per the spec; tolerant of any kwargs the adapter may pass.
        def __init__(self, *args, **kwargs) -> None:
            pass

        def chat(self, *args, **kwargs):  # pragma: no cover - never called at construction
            raise AssertionError("stub .chat must NOT be called during construction")

    class ResponseError(Exception):
        pass

    class RequestError(Exception):
        pass

    stub.Client = Client
    stub.ResponseError = ResponseError
    stub.RequestError = RequestError
    return stub


# ===========================================================================
# Behavior 1 -- ollama is a registered provider, appended last, order preserved
# ===========================================================================


def test_behavior1_ollama_is_registered_provider_appended_last():
    assert "ollama" in VALID_PROVIDERS, "'ollama' must be a registered provider"
    # Exact tuple: the four existing entries unchanged, ollama appended last.
    assert VALID_PROVIDERS == ("scripted", "anthropic", "openai", "bedrock", "ollama"), (
        f"VALID_PROVIDERS must be the exact five-tuple with ollama last; got {VALID_PROVIDERS!r}"
    )


# ===========================================================================
# Behavior 2 -- missing ollama SDK -> actionable LLMError at the API level
# ===========================================================================


def test_behavior2_missing_ollama_sdk_raises_actionable_llm_error(monkeypatch):
    # Force `import ollama` / importlib.import_module("ollama") to raise.
    monkeypatch.setitem(sys.modules, "ollama", None)

    with pytest.raises(LLMError) as excinfo:
        create_client(Settings(provider="ollama"))

    # A missing SDK must surface as an LLMError, NOT a raw ImportError.
    assert not isinstance(excinfo.value, ImportError), (
        "a missing ollama SDK must surface as an LLMError, not a raw ImportError"
    )
    message = str(excinfo.value)
    for needle in ("ollama", "pip install ollama", "--provider scripted"):
        assert needle in message, (
            f"missing-SDK message must contain {needle!r}; got:\n{message!r}"
        )


# ===========================================================================
# Behavior 3 -- CLI end-to-end missing SDK -> exit 1, single `error:` line,
# no traceback, carries the pip-install fix
# ===========================================================================


def test_behavior3_cli_missing_ollama_sdk_exit1_single_error_line_no_traceback(
    tmp_path, capsys, monkeypatch
):
    # A REAL existing --workspace so the pre-existing exit-2 workspace guard does
    # NOT fire first; the live client is built eagerly (before any collect), so
    # the missing-SDK LLMError raises before any network access.
    monkeypatch.setitem(sys.modules, "ollama", None)
    capsys.readouterr()  # drain any prior output

    rc = main([
        "scan",
        "--workspace", str(tmp_path),
        "--provider", "ollama",
        "--state-dir", str(tmp_path),
    ])
    err = capsys.readouterr().err

    assert rc == 1, f"a missing ollama SDK must exit 1 (foreseeable env fault), got {rc}"
    assert _TRACEBACK not in err, f"stderr must NOT contain a traceback; got:\n{err!r}"
    err_lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, (
        f"stderr must be a SINGLE error line (no traceback, no extra logs); got:\n{err!r}"
    )
    assert err_lines[0].startswith("error: "), (
        f"the stderr line must begin with 'error: '; got:\n{err_lines[0]!r}"
    )
    assert "pip install ollama" in err, (
        f"the CLI error line must carry the one-line fix instruction; got:\n{err!r}"
    )


# ===========================================================================
# Behavior 4 -- present-SDK stub constructs a working client (no network)
# ===========================================================================


def test_behavior4_present_ollama_stub_constructs_working_client(monkeypatch):
    stub = _make_ollama_stub()
    monkeypatch.setitem(sys.modules, "ollama", stub)

    client = create_client(Settings(provider="ollama"))

    assert isinstance(client, LLMClient), (
        "a present ollama SDK must yield a client satisfying the LLMClient protocol"
    )
    assert hasattr(client, "complete") and callable(client.complete), (
        "the constructed client must expose a callable .complete"
    )


def test_behavior4_construction_touches_only_ollama_namespace(monkeypatch):
    # Belt-and-suspenders on EB4's CRITICAL constraint: with `httpx` forced
    # absent AND only the self-contained `ollama` stub present, construction must
    # still succeed -- proving _create_ollama references NO non-ollama module.
    monkeypatch.setitem(sys.modules, "httpx", None)  # any httpx import would now raise
    stub = _make_ollama_stub()
    monkeypatch.setitem(sys.modules, "ollama", stub)

    client = create_client(Settings(provider="ollama"))

    assert isinstance(client, LLMClient), (
        "construction must depend on the ollama namespace ONLY (no httpx / second SDK)"
    )


# ===========================================================================
# Behavior 5 -- unknown provider still raises ValueError listing every option
# (now including ollama); a config typo stays distinct from a missing SDK
# ===========================================================================


def test_behavior5_unknown_provider_value_error_lists_all_options_incl_ollama():
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
    assert "ollama" in message, "the unknown-provider error must now list 'ollama' too"


# ===========================================================================
# Behavior 6 -- scripted default path imports NO ollama / httpx
# (the load-bearing offline invariant: the ollama import lives in its branch only)
# ===========================================================================


def test_behavior6_scripted_path_imports_no_ollama_or_httpx(tmp_path):
    # Drop any pre-existing ollama/httpx entries first, build+use the scripted
    # client, then assert NONE reappeared. If the ollama import leaked onto the
    # default path, one of these would import here.
    for name in list(sys.modules):
        if name.split(".")[0] in _OFFLINE_GUARD_MODULES:
            del sys.modules[name]

    settings = Settings(provider="scripted", scripted_responses_path=_write_script(tmp_path))
    client = create_client(settings)
    client.complete(system="s", prompt="p", tag="synthesize")

    leaked = [name for name in _OFFLINE_GUARD_MODULES if name in sys.modules]
    assert leaked == [], f"scripted path must import neither ollama nor httpx; leaked: {leaked}"


# ===========================================================================
# Behavior 7 -- no version bump (purely additive provider, like iter-23)
# ===========================================================================


def test_behavior7_no_version_bump_additive_provider():
    import proactive_loop

    assert proactive_loop.__version__ == "0.1.1", (
        "adding a provider is purely additive (no existing provider's behavior "
        "changes), exactly like iters 09/11/13/17/21/23 -- so no version bump"
    )


# ===========================================================================
# Behavior 8 -- scripted default path remains byte-stable end-to-end
# (make demo uses --provider scripted; the default path is untouched). We drive
# the same scripted `run` pipeline via main() -- an in-process, offline proxy for
# the demo's exit-0 + artifacts contract, needing no `make`/subprocess.
# ===========================================================================


def test_behavior8_scripted_run_pipeline_still_succeeds_and_writes_artifacts(
    tmp_path, capsys, monkeypatch
):
    # Even with the ollama SDK forced absent, the scripted default path must run
    # the full scan->auto-dispatch pipeline unchanged (exit 0, artifacts written).
    monkeypatch.setitem(sys.modules, "ollama", None)

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
    # The auto-dispatched goal writes artifacts under a run dir in the state dir.
    artifacts = list(state_dir.rglob("*.md"))
    assert artifacts, (
        f"the scripted run must produce artifact files under {state_dir}; found none"
    )
