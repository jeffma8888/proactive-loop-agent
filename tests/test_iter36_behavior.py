"""Black-box behavior tests for iteration 36.

Feature under test: ``ScriptedLLMClient`` now validates the *shape* of a
scripted-responses script eagerly -- at load / construction time -- and fails
with a plain ``ValueError`` (never a raw ``KeyError`` and never a deferred
``AttributeError`` inside ``complete``). The offline scripted provider is the
product's headline seam and the CLI's ``(LLMError, ValueError, OSError)``
boundary maps a ``ValueError`` to one ``error:`` line + exit 1, so a reviewer who
typos the config shape on their first offline run gets a legible message instead
of a Python stacktrace.

ISOLATION: these tests are written strictly against the public API documented in
the spec and ``SPEC.md`` -- ``proactive_loop.llm.client.ScriptedLLMClient``
(``from_file`` / the direct constructor / ``remaining`` / ``complete``) and the
``proactive_loop.cli.main([...])`` CLI boundary driven by the offline scripted
provider. No ``src/`` internals, no engineer/reviewer notes, and no ``git diff``
were consulted. Everything runs fully offline -- zero network, zero API keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.llm.client import (
    LLMResponse,
    ScriptedLLMClient,
    ScriptExhaustedError,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

_TRACEBACK = "Traceback (most recent call last)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, obj: object, name: str = "s.json") -> Path:
    """Write ``obj`` as JSON to a tmp file and return its path."""
    path = tmp_path / name
    path.write_text(json.dumps(obj))
    return path


def _write_raw(tmp_path: Path, text: str, name: str = "s.json") -> Path:
    """Write raw ``text`` (already JSON) to a tmp file and return its path."""
    path = tmp_path / name
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------
# Behavior 1 -- dict WITHOUT a "responses" key => ValueError, not KeyError
# ---------------------------------------------------------------------------


def test_behavior1_dict_without_responses_key_raises_valueerror(tmp_path: Path) -> None:
    path = _write(tmp_path, {"foo": [{"tag": "x"}]})

    with pytest.raises(ValueError) as excinfo:
        ScriptedLLMClient.from_file(path)

    # Must be a *plain* ValueError, never a bare KeyError.
    assert type(excinfo.value) is ValueError, (
        f"expected a plain ValueError (not a subclass / KeyError), "
        f"got {type(excinfo.value).__name__}"
    )
    # The message must name the offending file so the fault is self-service.
    assert str(path) in str(excinfo.value), (
        f"error should contain the file path, got: {str(excinfo.value)!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- dict with a non-list "responses" value => ValueError (unchanged)
# ---------------------------------------------------------------------------


def test_behavior2_dict_with_nonlist_responses_raises_valueerror(tmp_path: Path) -> None:
    path = _write(tmp_path, {"responses": 5})

    with pytest.raises(ValueError) as excinfo:
        ScriptedLLMClient.from_file(path)

    assert type(excinfo.value) is ValueError
    assert str(path) in str(excinfo.value)


# ---------------------------------------------------------------------------
# Behavior 3 -- bare non-list, non-dict top-level value => ValueError (unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bare", [5, "x", True, 3.14])
def test_behavior3_bare_scalar_raises_valueerror(tmp_path: Path, bare: object) -> None:
    path = _write(tmp_path, bare, name=f"bare_{type(bare).__name__}.json")

    with pytest.raises(ValueError) as excinfo:
        ScriptedLLMClient.from_file(path)

    assert type(excinfo.value) is ValueError
    assert str(path) in str(excinfo.value)


# ---------------------------------------------------------------------------
# Behavior 4 -- a non-dict entry => ValueError AT LOAD TIME (not deferred),
#               naming the file and the 0-based index of the FIRST offender.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "first_bad_index"),
    [
        (["x"], 0),
        ({"responses": [1, 2, 3]}, 0),
        ([{"tag": "a", "text": "ok"}, 7], 1),
    ],
)
def test_behavior4_nondict_entry_raises_valueerror_at_load(
    tmp_path: Path, payload: object, first_bad_index: int
) -> None:
    path = _write(tmp_path, payload, name=f"bad_entry_{first_bad_index}.json")

    with pytest.raises(ValueError) as excinfo:
        # MUST raise here (load time). If the shape check were still deferred,
        # from_file would return a client and this line would NOT raise --
        # the crash would only surface later on complete() as AttributeError.
        ScriptedLLMClient.from_file(path)

    message = str(excinfo.value)
    assert type(excinfo.value) is ValueError, (
        f"deferred crash should be a plain load-time ValueError, "
        f"got {type(excinfo.value).__name__}"
    )
    assert str(path) in message, f"error should contain the file path, got: {message!r}"
    # The message must carry the index of the FIRST offending entry. Strip the
    # path first so a digit inside the tmp path can't produce a false match.
    without_path = message.replace(str(path), "")
    assert str(first_bad_index) in without_path, (
        f"error should name the first bad entry index {first_bad_index}, "
        f"got: {message!r}"
    )


def test_behavior4_nondict_entry_does_not_defer_to_complete(tmp_path: Path) -> None:
    """The failure must NOT be a deferred AttributeError inside complete().

    We prove the fix by construction: from_file itself raises, so there is no
    surviving client on which complete() could later blow up. (If a bug ever
    re-introduced the deferral, from_file would succeed and the AttributeError
    would strike here instead.)
    """
    path = _write(tmp_path, {"responses": [1, 2, 3]})

    with pytest.raises(ValueError):
        client = ScriptedLLMClient.from_file(path)
        # Unreachable when the contract holds; present only so a regression
        # (deferral) surfaces as the wrong exception type rather than passing.
        client.complete(system="s", prompt="p", tag="x")


# ---------------------------------------------------------------------------
# Behavior 5 -- the DIRECT constructor enforces the same shared entry check.
# ---------------------------------------------------------------------------


def test_behavior5_direct_constructor_nondict_entry_raises_valueerror() -> None:
    with pytest.raises(ValueError) as excinfo:
        ScriptedLLMClient([{"tag": "a"}, 7])

    assert type(excinfo.value) is ValueError, (
        f"the constructor's shape check must raise a plain ValueError, "
        f"got {type(excinfo.value).__name__}"
    )
    # The shared check reports the first offending index (1 here).
    assert "1" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Behavior 6 -- a valid list-of-dicts loads; remaining() == entry count.
# ---------------------------------------------------------------------------


def test_behavior6_valid_list_of_dicts_loads(tmp_path: Path) -> None:
    entries = [
        {"tag": "synthesize", "text": "hi"},
        {"tag": "", "text": "wildcard"},
    ]
    path = _write(tmp_path, entries)

    client = ScriptedLLMClient.from_file(path)

    assert client.remaining() == len(entries)


# ---------------------------------------------------------------------------
# Behavior 7 -- a valid {"responses": [<dicts>]} loads; remaining() == count.
# ---------------------------------------------------------------------------


def test_behavior7_valid_responses_object_loads(tmp_path: Path) -> None:
    responses = [
        {"tag": "a", "text": "b"},
        {"tag": "c", "text": "d"},
        {"tag": "synthesize", "text": "e"},
    ]
    path = _write(tmp_path, {"responses": responses})

    client = ScriptedLLMClient.from_file(path)

    assert client.remaining() == len(responses)


# ---------------------------------------------------------------------------
# Behavior 8 -- backward compat: empty list and list-of-dicts both construct;
#               complete() behaves exactly as today.
# ---------------------------------------------------------------------------


def test_behavior8_empty_list_constructs_and_exhausts_on_complete() -> None:
    client = ScriptedLLMClient([])  # must NOT raise at construction

    assert client.remaining() == 0
    with pytest.raises(ScriptExhaustedError):
        client.complete(system="s", prompt="p", tag="anything")


def test_behavior8_list_of_dicts_constructs_and_returns_response() -> None:
    client = ScriptedLLMClient([{"tag": "", "text": "x"}])  # wildcard entry

    response = client.complete(system="s", prompt="p", tag="anything")

    assert isinstance(response, LLMResponse)
    assert response.text == "x"


# ---------------------------------------------------------------------------
# Behavior 9 -- END TO END: each malformed file (missing-responses dict and a
#               non-dict-entry file) yields exit 1, a single `error:` line on
#               stderr, NO traceback / KeyError / AttributeError, and no slate.
# ---------------------------------------------------------------------------


def _assert_legible_cli_fault(rc: int, err: str) -> None:
    assert rc == 1, f"a foreseeable config-shape fault must exit 1, got {rc}"
    assert _TRACEBACK not in err, f"stderr must NOT contain a traceback, got: {err!r}"
    assert "KeyError" not in err, f"stderr must NOT leak a KeyError, got: {err!r}"
    assert "AttributeError" not in err, (
        f"stderr must NOT leak an AttributeError, got: {err!r}"
    )
    non_empty = [ln for ln in err.splitlines() if ln.strip()]
    assert len(non_empty) == 1, (
        f"exactly one stderr line expected, got {len(non_empty)}: {err!r}"
    )
    assert non_empty[0].startswith("error:"), (
        f"the single stderr line must begin with 'error:', got: {non_empty[0]!r}"
    )


def test_behavior9_missing_responses_key_cli_is_legible(tmp_path: Path, capsys) -> None:
    bad = _write(tmp_path, {"foo": [{"tag": "x"}]}, name="bad.json")
    state_dir = tmp_path / "state"

    rc = main([
        "scan",
        "--workspace", str(tmp_path),
        "--provider", "scripted",
        "--scripted-responses", str(bad),
        "--state-dir", str(state_dir),
    ])

    _assert_legible_cli_fault(rc, capsys.readouterr().err)
    assert not (state_dir / "slate.json").exists(), "no slate must be written on a load fault"


def test_behavior9_nondict_entry_cli_is_legible(tmp_path: Path, capsys) -> None:
    bad = _write_raw(tmp_path, '["x"]', name="bad_entry.json")
    state_dir = tmp_path / "state"

    rc = main([
        "scan",
        "--workspace", str(tmp_path),
        "--provider", "scripted",
        "--scripted-responses", str(bad),
        "--state-dir", str(state_dir),
    ])

    _assert_legible_cli_fault(rc, capsys.readouterr().err)
    assert not (state_dir / "slate.json").exists(), "no slate must be written on a load fault"


# ---------------------------------------------------------------------------
# Behavior 10 -- END TO END: the valid demo script still works unchanged.
# ---------------------------------------------------------------------------


def test_behavior10_valid_demo_script_still_succeeds(tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"

    rc = main([
        "scan",
        "--workspace", str(FIXTURE),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(state_dir),
    ])

    out = capsys.readouterr().out
    assert rc == 0, "the valid demo scan must still exit 0 (no regression)"
    slate = state_dir / "slate.json"
    assert slate.is_file(), "a valid scan must still write the slate file"

    # The slate must parse and carry the ranked goals the demo script produces.
    data = json.loads(slate.read_text())
    goals = data["goals"] if isinstance(data, dict) and "goals" in data else data
    assert isinstance(goals, list) and len(goals) >= 1, (
        f"the valid demo slate must contain ranked goals, got: {data!r}"
    )
    assert out.strip(), "a successful scan must still render slate output to stdout"
