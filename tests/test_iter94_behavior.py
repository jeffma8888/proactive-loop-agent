"""Black-box behavior tests for iteration 94 (foundry state iter-85) --- the
``pla signals --collector NAME`` upstream collector allowlist: a repeatable,
registry-validated option that restricts WHICH collectors run before the
read-only perception inspector renders them, mirroring the already-shipped
``pla scan --collector`` knob (ROADMAP row #71). Unknown name -> exit 2;
absent -> all collectors; composes as a logical AND with ``--kind`` and
``--min-weight``; needs no provider wiring (``signals`` builds no LLMClient).

ISOLATION CONTRACT (honored): these tests are written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, ``ROADMAP.md`` --- and the test conventions already public under
``tests/`` (``test_iter73_behavior.py``, ``test_iter88_behavior.py``). They
drive ONLY documented public surfaces: the ``pla`` CLI entry
``proactive_loop.cli.main(argv) -> int`` (observable stdout / stderr / exit
codes on the bundled ``examples/fixture_workspace``) and the public registry
accessor ``proactive_loop.collectors.all_collectors`` (used ONLY to derive the
expected argparse ``choices`` so the assertion cannot drift from a hardcoded
literal, exactly as ``test_iter73_behavior.py::test_b04b`` does). **No file
under ``src/`` was read, no engineer or reviewer note was read, and no
``git diff`` was consulted.** Every test is fully offline / deterministic: no
LLM, no network, no API keys; the committed ``examples/fixture_workspace``
drives every case.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.collectors import all_collectors

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"

_EMPTY_MARKER = "(no signals collected)"

# The five signal-emitting collectors of the bundled fixture and the exact
# ``## <kind> (N)`` header each produces. NOTE the sections are grouped by KIND,
# not by collector name: the ``git_activity`` collector emits kind ``git_commit``.
# ``git_commit`` is capped at 15 by the collector and the rest are
# fixture-file-derived, so all five counts are stable across runs. (The bare
# view can also show a sixth ``## working_tree`` header whose count tracks the
# repo's dirty tree -- deliberately NOT asserted; behavior 5 is containment.)
_FIXTURE_HEADERS = (
    "## ci_config (1)",
    "## git_commit (15)",
    "## note (5)",
    "## test_posture (1)",
    "## todo (10)",
)


# ---------------------------------------------------------------------------
# Black-box helpers (public CLI only; no monkeypatch, no network).
# ---------------------------------------------------------------------------


def _signals(*extra, workspace=None):
    """Argv for ``pla signals`` on the bundled fixture (absolute path)."""
    ws = str(workspace if workspace is not None else FIXTURE)
    return ["signals", "--workspace", ws, *extra]


def _run(argv, capsys):
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _headers(out):
    """Ordered list of the kind strings from every ``## <kind> (N)`` line."""
    return re.findall(r"^## (\S+) \(\d+\)", out, flags=re.MULTILINE)


def _signal_sources(out):
    """The source column (first whitespace-delimited token) of every indented
    signal line (a line that is indented and is NOT a ``## `` header)."""
    sources = []
    for line in out.splitlines():
        if line.startswith("## ") or not line.strip():
            continue
        if line.startswith("  "):
            sources.append(line.split()[0])
    return sources


# ===========================================================================
# Behavior 1 --- a single --collector restricts the view to that collector's
# signals only (all other kind sections are gone).
# ===========================================================================


def test_b01_single_collector_shows_only_its_kind(capsys):
    rc, out, err = _run(_signals("--collector", "notes"), capsys)
    assert rc == 0
    # Exactly one kind header, and it is the notes collector's kind (`note`).
    assert _headers(out) == ["note"]
    assert "## note (5)" in out
    # The other four fixture sections are gone.
    for kind in ("ci_config", "git_commit", "test_posture", "todo"):
        assert f"## {kind} (" not in out


# ===========================================================================
# Behavior 2 --- --collector selects by COLLECTOR NAME (the signal `source`),
# NOT by kind. Discriminates a name-filter from a kind-filter: the
# ``git_activity`` collector emits kind ``git_commit``, so source != kind, and a
# kind-based "fix" would be wrong-but-green on a fixture where source == kind.
# ===========================================================================


def test_b02_collector_selects_by_source_not_kind(capsys):
    rc, out, err = _run(_signals("--collector", "git_activity"), capsys)
    assert rc == 0
    # The git_activity collector emits kind `git_commit`; that is the ONLY header.
    assert _headers(out) == ["git_commit"]
    assert "## git_commit (15)" in out
    # Every signal line's source column is the COLLECTOR name, not the kind.
    sources = _signal_sources(out)
    assert sources, "expected at least one git_activity signal line"
    assert set(sources) == {"git_activity"}


# ===========================================================================
# Behavior 3 --- --collector is repeatable and unions the named collectors,
# rendered in ascending kind order.
# ===========================================================================


def test_b03_repeatable_unions_in_ascending_kind_order(capsys):
    rc, out, err = _run(
        _signals("--collector", "notes", "--collector", "todos"), capsys
    )
    assert rc == 0
    # Exactly the two kinds, ascending kind order (note < todo).
    assert _headers(out) == ["note", "todo"]
    assert "## note (5)" in out
    assert "## todo (10)" in out
    for kind in ("ci_config", "git_commit", "test_posture"):
        assert f"## {kind} (" not in out


# ===========================================================================
# Behavior 4 --- an unknown collector name is a PARSE-TIME usage error
# (exit 2), side-effect-free; stderr names the bad choice and the LIVE valid
# collector names (identical validation to ``pla scan --collector bogus``).
# ===========================================================================


def test_b04_unknown_name_is_parse_time_exit2(capsys):
    capsys.readouterr()
    with pytest.raises(SystemExit) as ei:
        main(_signals("--collector", "bogus"))
    assert ei.value.code == 2
    cap = capsys.readouterr()
    assert cap.out == ""  # nothing printed to stdout; no collection ran
    err = cap.err
    assert "bogus" in err
    # Valid names are derived from the LIVE registry, so this cannot drift from
    # a hardcoded literal.
    for name in sorted(c.name for c in all_collectors()):
        assert f"'{name}'" in err, f"{name} missing from choices: {err!r}"


# ===========================================================================
# Behavior 5 --- absent --collector is the all-collectors view. Assert
# CONTAINMENT of the five fixture headers, never "exactly five" (a future
# collector could add a sixth; ``working_tree`` already emits on a dirty tree).
# ===========================================================================


def test_b05_absent_collector_contains_all_five_headers(capsys):
    rc, out, err = _run(_signals(), capsys)
    assert rc == 0
    for header in _FIXTURE_HEADERS:
        assert header in out, f"missing header {header!r} in bare view"


# ===========================================================================
# Behavior 6 --- --collector composes as a logical AND with --kind and
# with --min-weight.
# ===========================================================================


def test_b06a_and_with_matching_kind(capsys):
    rc, out, err = _run(_signals("--collector", "todos", "--kind", "todo"), capsys)
    assert rc == 0
    assert _headers(out) == ["todo"]
    assert "## todo (10)" in out


def test_b06b_and_with_nonmatching_kind_is_empty(capsys):
    # The todos collector emits no `note`-kind signal -> the AND is empty.
    rc, out, err = _run(_signals("--collector", "todos", "--kind", "note"), capsys)
    assert rc == 0
    assert out.strip() == _EMPTY_MARKER
    assert "## " not in out


def test_b06c_and_with_min_weight(capsys):
    # Every git_commit weight is 1.0, so a 1.0 INCLUSIVE floor keeps all 15.
    rc, out, err = _run(
        _signals("--collector", "git_activity", "--min-weight", "1.0"), capsys
    )
    assert rc == 0
    assert _headers(out) == ["git_commit"]
    assert "## git_commit (15)" in out


# ===========================================================================
# Behavior 7 --- the --json view honors --collector.
# ===========================================================================


def test_b07_json_view_honors_collector(capsys):
    rc, out, err = _run(_signals("--collector", "notes", "--json"), capsys)
    assert rc == 0
    payload = json.loads(out)  # EXACTLY one JSON object -> parses cleanly.
    assert isinstance(payload, dict)
    assert payload["workspace_root"] == str(FIXTURE)
    sigs = payload["signals"]
    assert len(sigs) == 5
    assert {s["source"] for s in sigs} == {"notes"}


# ===========================================================================
# Behavior 8 --- signals --collector needs NO provider/LLM configuration
# (the handler builds no LLMClient). Default `scripted` provider with NO
# --scripted-responses succeeds, with no `provider is 'scripted' but ...` error.
# ===========================================================================


def test_b08_needs_no_provider_config(capsys):
    # No --provider and no --scripted-responses -> defaults to `scripted`.
    rc, out, err = _run(_signals("--collector", "notes"), capsys)
    assert rc == 0
    assert "provider is 'scripted'" not in err
    assert "## note (5)" in out


# ===========================================================================
# Behavior 9 --- a VALID collector that yields no signals for the workspace is
# an empty SELECTION, not an error (mirrors --kind-matches-nothing).
# ===========================================================================


def test_b09_valid_collector_with_no_signals_is_empty_not_error(capsys):
    rc, out, err = _run(_signals("--collector", "merge_conflict"), capsys)
    assert rc == 0
    assert out.strip() == _EMPTY_MARKER
    assert "## " not in out


# ===========================================================================
# Behavior 10 --- run and watch STILL reject --collector at parse time (the
# flag is now scan+signals, NOT all verbs). Surviving half of the iter-73
# scan-only contract.
# ===========================================================================


@pytest.mark.parametrize("verb", ["run", "watch"])
def test_b10_run_and_watch_still_reject_collector(verb, capsys):
    capsys.readouterr()
    with pytest.raises(SystemExit) as ei:
        main([verb, "--workspace", str(FIXTURE), "--collector", "todos"])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "--collector" in err, f"{verb} error should name --collector: {err!r}"
