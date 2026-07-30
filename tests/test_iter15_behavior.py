"""Black-box behavior tests for iteration 15.

Feature under test: ``pla signals --workspace W [--json] [--kind K]`` -- a
read-only, LLM-free perception inspector that prints the raw ``ContextSignal``s
the collectors perceive for a workspace, WITHOUT synthesizing (builds no
``LLMClient``). Human form groups signals under a ``## <kind> (<count>)`` header
per distinct kind (kinds sorted ascending; within a kind ordered by
``(source, summary, path or "")``), one two-space-indented line per signal
(``  <source>  w<weight:.2f>  <summary>`` with ``-> <path>`` appended only when
the signal carries a path), degrading to a single ``(no signals collected)`` line
on an empty selection. ``--json`` emits one object ``{workspace_root, signals[...]}``
where each signal is an explicit dict of EXACTLY the six keys
``source, kind, summary, detail, path, weight`` (no ``timestamp`` -- the iter-08
schema-leak discipline), the flat ``signals`` array ordered by
``(kind, source, summary, path or "")``, degrading to ``[]`` (not the human marker)
when a ``--kind`` matches nothing. ``--kind K`` narrows to one collector-defined
kind (dynamic; not validated against an enum). A missing/non-directory
``--workspace`` fails fast with ``error: workspace not found: <path>`` on stderr +
exit 2 (the verbatim iter-10 guard, before any collection), regardless of
``--json``/``--kind``.

ISOLATION CONTRACT (honored): these tests are written strictly against the public
contract for this iteration -- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` sections 4.5/3 -- and drive ONLY documented public
surfaces: the ``pla`` CLI via ``proactive_loop.cli.main(argv) -> int`` (its
observable stdout/stderr/exit codes), plus -- exactly as this iteration's spec
authorizes ("importing the pure helpers ... and passing a synthetic
WorkspaceSnapshot built directly from proactive_loop.models") -- the two pure
render helpers ``_render_signals`` / ``_signals_json_payload`` and the public
domain models ``WorkspaceSnapshot`` / ``ContextSignal``. **No file under ``src/``
was read, no engineer/reviewer notes were read, and no ``git diff`` was
consulted.** Every test is fully offline: zero network, zero API keys; bad-config
providers are exercised only to prove the verb is LLM-free. Empty-workspace tests
use pytest ``tmp_path`` (outside any git checkout) so collector git-discovery does
not walk up into an enclosing repo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop.cli import main, _render_signals, _signals_json_payload
from proactive_loop.models import ContextSignal, WorkspaceSnapshot

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"

_MSG = "error: workspace not found"
_EMPTY_MARKER = "(no signals collected)"

# The six-key explicit signal schema the JSON view must emit -- and nothing else
# (no `timestamp`, no `collected_at`). Per the iter-08 schema-leak discipline.
_SIGNAL_KEYS = {"source", "kind", "summary", "detail", "path", "weight"}


# ---------------------------------------------------------------------------
# Helpers -- all black-box: build argv, drive main(), read back stdout/stderr.
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _worked_example_snapshot() -> WorkspaceSnapshot:
    """The exact snapshot from the spec's worked examples (behaviors 5 & 8)."""
    return WorkspaceSnapshot(
        root="/w",
        signals=[
            ContextSignal(source="todos", kind="todo", summary="TODO: wire retry", path="a.py", weight=1.0),
            ContextSignal(source="todos", kind="todo", summary="FIXME: leak", path="b.py", weight=2.0),
            ContextSignal(source="notes", kind="note", summary="# Roadmap", path=None, weight=0.5),
        ],
    )


# ===========================================================================
# Behavior 1 -- Verb registered: `--help` lists it; a valid workspace exits 0.
# ===========================================================================


def test_b01_signals_verb_registered_and_valid_ws_exits_zero(capsys):
    # `pla --help` raises SystemExit(0) and lists a `signals` subcommand.
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    help_out = capsys.readouterr().out
    assert "signals" in help_out, f"`signals` must appear in --help; got:\n{help_out}"

    # `signals --workspace W` on an existing directory returns exit 0.
    rc, o, e = _run(["signals", "--workspace", str(FIXTURE)], capsys)
    assert rc == 0, f"signals on a real dir must exit 0; stderr={e!r}"
    assert e == ""


def test_b01_signals_subparser_has_its_own_help(capsys):
    # `pla signals --help` is a valid, self-documenting subcommand (SystemExit 0).
    with pytest.raises(SystemExit) as excinfo:
        main(["signals", "--help"])
    assert excinfo.value.code == 0
    sub_help = capsys.readouterr().out
    # Its documented flags are advertised.
    for flag in ("--workspace", "--json", "--kind"):
        assert flag in sub_help, f"signals --help must advertise {flag}; got:\n{sub_help}"


# ===========================================================================
# Behavior 2 -- LLM-free / offline: bad provider configs are inert (no client).
# ===========================================================================


def test_b02_unknown_provider_is_inert(capsys):
    # An unknown provider (which makes `scan` fail) is inert here: no client is
    # built, so `signals` still exits 0 and never prints a provider error.
    rc, o, e = _run(
        ["signals", "--workspace", str(FIXTURE), "--provider", "no_such_provider"],
        capsys,
    )
    assert rc == 0, f"unknown provider must be inert for signals; stderr={e!r}"
    assert "error:" not in e
    assert "provider" not in e.lower()


def test_b02_scripted_without_responses_file_is_inert(capsys):
    # `--provider scripted` with NO `--scripted-responses` would fault a
    # client-building verb; signals never builds a client, so it still exits 0.
    rc, o, e = _run(
        ["signals", "--workspace", str(FIXTURE), "--provider", "scripted"],
        capsys,
    )
    assert rc == 0, f"scripted-without-responses must be inert for signals; stderr={e!r}"
    assert "error:" not in e
    assert "scripted" not in e.lower()


def test_b02_discriminator_scan_faults_under_same_config(capsys):
    # Discriminator proving the config IS otherwise client-fatal: the SAME
    # unknown-provider config makes `scan` (which builds a client) exit nonzero,
    # whereas `signals` above exited 0 -- i.e. signals genuinely builds no client.
    rc_scan, _o, _e = _run(
        ["scan", "--workspace", str(FIXTURE), "--provider", "no_such_provider"],
        capsys,
    )
    assert rc_scan != 0, "scan must fault under a bad provider (else the b02 discriminator is vacuous)"
    rc_sig, _o2, e2 = _run(
        ["signals", "--workspace", str(FIXTURE), "--provider", "no_such_provider"],
        capsys,
    )
    assert rc_sig == 0 and e2 == ""


# ===========================================================================
# Behavior 3 -- Missing/non-dir workspace -> exit 2 (verbatim guard, fires first).
# ===========================================================================


@pytest.mark.parametrize("extra", [[], ["--json"], ["--kind", "todo"], ["--json", "--kind", "note"]])
def test_b03_missing_workspace_exit2_verbatim(capsys, extra):
    missing = "/no/such/dir"
    rc, o, e = _run(["signals", "--workspace", missing, *extra], capsys)
    assert rc == 2, f"missing workspace must exit 2 (extra={extra}); got {rc}"
    # Exact verbatim message to STDERR, and nothing on stdout, before collection.
    assert e.strip() == f"{_MSG}: {missing}", f"stderr must be the verbatim guard; got {e!r}"
    assert o == "", f"nothing may be written to stdout on the guard; got {o!r}"


@pytest.mark.parametrize("extra", [[], ["--json"], ["--kind", "todo"]])
def test_b03_regular_file_workspace_exit2(tmp_path, capsys, extra):
    a_file = tmp_path / "not_a_dir.txt"
    a_file.write_text("i am a file, not a workspace\n", encoding="utf-8")
    rc, o, e = _run(["signals", "--workspace", str(a_file), *extra], capsys)
    assert rc == 2, f"a file (not a dir) must exit 2 (extra={extra}); got {rc}"
    assert e.strip() == f"{_MSG}: {a_file}"
    assert o == ""


def test_b03_guard_exit_is_two_never_one(tmp_path, capsys):
    a_file = tmp_path / "f.txt"
    a_file.write_text("x\n", encoding="utf-8")
    for ws in ("/no/such/dir", str(a_file)):
        rc, _o, _e = _run(["signals", "--workspace", ws], capsys)
        assert rc == 2 and rc != 1, f"{ws!r} must use exit 2, not the reserved exit-1 class"


# ===========================================================================
# Behavior 4 -- Grouped human render: sorted kind headers with counts.
# ===========================================================================


def test_b04_sorted_kind_headers_with_counts(capsys):
    snap = _worked_example_snapshot()  # kinds: todo(2), note(1)
    out = _render_signals(snap)
    lines = out.splitlines()

    header_lines = [ln for ln in lines if ln.startswith("## ")]
    # Exactly one header per distinct kind, each carrying its true count.
    assert header_lines == ["## note (1)", "## todo (2)"], f"headers wrong/out-of-order:\n{out}"

    # The ONLY lines starting with `## ` are those kind headers (no stray `## `).
    assert len(header_lines) == 2

    # Ascending lexicographic order of the kind token.
    kinds_in_order = [ln[len("## "):].split(" (")[0] for ln in header_lines]
    assert kinds_in_order == sorted(kinds_in_order) == ["note", "todo"]


# ===========================================================================
# Behavior 5 -- One line per signal; exact format; path arrow; deterministic order.
# ===========================================================================


def test_b05_exact_worked_example_render(capsys):
    snap = _worked_example_snapshot()
    expected = (
        "## note (1)\n"
        "  notes  w0.50  # Roadmap\n"
        "## todo (2)\n"
        "  todos  w2.00  FIXME: leak -> b.py\n"
        "  todos  w1.00  TODO: wire retry -> a.py"
    )
    assert _render_signals(snap) == expected


def test_b05_line_format_arrow_and_within_kind_order(capsys):
    snap = _worked_example_snapshot()
    lines = _render_signals(snap).splitlines()

    # Every non-header line is a two-space-indented signal line.
    signal_lines = [ln for ln in lines if not ln.startswith("## ")]
    for ln in signal_lines:
        assert ln.startswith("  "), f"signal line must be two-space indented; got {ln!r}"
        assert not ln.startswith("   "), f"exactly two-space indent expected; got {ln!r}"

    # A signal WITH a path ends with ` -> <path>` (verbatim echo).
    assert "  todos  w2.00  FIXME: leak -> b.py" in signal_lines
    # A signal WITHOUT a path carries no ` -> ` arrow.
    note_line = next(ln for ln in signal_lines if "# Roadmap" in ln)
    assert " -> " not in note_line, f"pathless signal must not render an arrow; got {note_line!r}"

    # Within the `todo` section, order is (source, summary, path): FIXME before TODO.
    todo_section = signal_lines[1:]  # after the single `note` line
    assert todo_section == [
        "  todos  w2.00  FIXME: leak -> b.py",
        "  todos  w1.00  TODO: wire retry -> a.py",
    ]


def test_b05_render_is_pure_and_deterministic(capsys):
    snap = _worked_example_snapshot()
    assert _render_signals(snap) == _render_signals(snap), "render must be byte-identical across calls"


def test_b05_weight_is_two_decimal_formatted(capsys):
    # Weight is rendered as w<value:.2f> regardless of the underlying float.
    snap = WorkspaceSnapshot(
        root="/w",
        signals=[ContextSignal(source="s", kind="k", summary="only", path=None, weight=3.0)],
    )
    assert "  s  w3.00  only" in _render_signals(snap)


# ===========================================================================
# Behavior 6 -- `--kind K` filters the human view to one kind.
# ===========================================================================


def test_b06_kind_filter_helper_one_header(capsys):
    snap = _worked_example_snapshot()
    out = _render_signals(snap, kind="todo")
    header_lines = [ln for ln in out.splitlines() if ln.startswith("## ")]
    assert header_lines == ["## todo (2)"], f"exactly one todo header expected; got:\n{out}"
    assert "note" not in out  # the note signal/header is filtered out entirely


def test_b06_kind_filter_cli_one_header(capsys):
    # End-to-end over the bundled fixture (which carries both `todo` and `note`).
    rc, o, e = _run(["signals", "--workspace", str(FIXTURE), "--kind", "todo"], capsys)
    assert rc == 0
    header_lines = [ln for ln in o.splitlines() if ln.startswith("## ")]
    assert len(header_lines) == 1, f"exactly one header under --kind todo; got:\n{o}"
    assert header_lines[0].startswith("## todo ("), f"the single header must be todo; got {header_lines[0]!r}"


# ===========================================================================
# Behavior 7 -- Empty selection -> `(no signals collected)` (human).
# ===========================================================================


def test_b07_empty_snapshot_marker(capsys):
    snap = WorkspaceSnapshot(root="/empty", signals=[])
    assert _render_signals(snap) == _EMPTY_MARKER


def test_b07_kind_no_match_marker_even_when_others_exist(capsys):
    snap = _worked_example_snapshot()  # has todo + note, but not `dependency`
    assert _render_signals(snap, kind="dependency") == _EMPTY_MARKER


def test_b07_cli_empty_dir_prints_marker(tmp_path, capsys):
    # tmp_path is outside any git checkout, so all collectors degrade to [].
    rc, o, e = _run(["signals", "--workspace", str(tmp_path)], capsys)
    assert rc == 0
    assert o.strip() == _EMPTY_MARKER, f"empty workspace must print the degrade marker; got {o!r}"
    # It is a single line (no stray headers or blank lines).
    assert [ln for ln in o.splitlines() if ln.strip()] == [_EMPTY_MARKER]
    assert e == ""


# ===========================================================================
# Behavior 8 -- `--json` schema (exact 6 keys, no timestamp) + determinism.
# ===========================================================================


def test_b08_json_payload_exact_worked_example(capsys):
    snap = _worked_example_snapshot()
    expected = {
        "workspace_root": "/w",
        "signals": [
            {"source": "notes", "kind": "note", "summary": "# Roadmap", "detail": "", "path": None, "weight": 0.5},
            {"source": "todos", "kind": "todo", "summary": "FIXME: leak", "detail": "", "path": "b.py", "weight": 2.0},
            {"source": "todos", "kind": "todo", "summary": "TODO: wire retry", "detail": "", "path": "a.py", "weight": 1.0},
        ],
    }
    assert _signals_json_payload(snap) == expected


def test_b08_json_payload_schema_and_order(capsys):
    snap = _worked_example_snapshot()
    payload = _signals_json_payload(snap)

    # Exactly the two top-level keys.
    assert set(payload.keys()) == {"workspace_root", "signals"}
    assert payload["workspace_root"] == snap.root
    assert isinstance(payload["signals"], list)

    for sig in payload["signals"]:
        # EXACTLY the six keys -- no timestamp, no collected_at, no extras.
        assert set(sig.keys()) == _SIGNAL_KEYS, f"signal schema leak/miss: {set(sig.keys())}"
        assert "timestamp" not in sig
        assert "collected_at" not in sig

    # Flat list ordered by (kind, source, summary, path or "").
    order_key = [(s["kind"], s["source"], s["summary"], s["path"] or "") for s in payload["signals"]]
    assert order_key == sorted(order_key)

    # A pathless signal serializes `path` as JSON null (None).
    note = next(s for s in payload["signals"] if s["kind"] == "note")
    assert note["path"] is None


def test_b08_json_payload_is_json_serializable_without_timestamp(capsys):
    # Round-trip through json to prove no datetime/extra leaks the serializer.
    snap = _worked_example_snapshot()
    text = json.dumps(_signals_json_payload(snap))
    assert "timestamp" not in text
    round = json.loads(text)
    assert round == _signals_json_payload(snap)


# ===========================================================================
# Behavior 9 -- `--json` stdout is one clean JSON object (no trailer).
# ===========================================================================


def test_b09_json_stdout_is_one_object_no_trailer(capsys):
    rc, o, e = _run(["signals", "--workspace", str(FIXTURE), "--json"], capsys)
    assert rc == 0
    # The ENTIRE stdout parses as one JSON object (pipes cleanly into jq).
    doc = json.loads(o)
    assert isinstance(doc, dict)
    assert set(doc.keys()) == {"workspace_root", "signals"}
    # No human rendering leaked in.
    assert "## " not in o
    assert _EMPTY_MARKER not in o
    # Every signal's weight is a JSON number (not the human `w0.50` string form).
    for sig in doc["signals"]:
        assert isinstance(sig["weight"], (int, float)), f"weight must be a JSON number; got {sig['weight']!r}"
    assert "w0." not in o and "w1." not in o  # no `w<value>` human weight tokens
    assert e == ""


def test_b09_weight_number_vs_human_string_contrast(capsys):
    # The same weight renders as a JSON number in --json but `w<value:.2f>` in human.
    snap = _worked_example_snapshot()
    payload = _signals_json_payload(snap)
    note = next(s for s in payload["signals"] if s["kind"] == "note")
    assert note["weight"] == 0.5 and isinstance(note["weight"], float)
    assert "w0.50" in _render_signals(snap)


# ===========================================================================
# Behavior 10 -- `--json --kind K` filters the JSON array (degrades to []).
# ===========================================================================


def test_b10_json_kind_filter_helper(capsys):
    snap = _worked_example_snapshot()
    only_note = _signals_json_payload(snap, kind="note")["signals"]
    assert only_note and all(s["kind"] == "note" for s in only_note)

    # A --kind matching nothing degrades to [] (NOT the human marker), root kept.
    empty = _signals_json_payload(snap, kind="no_such_kind")
    assert empty["signals"] == []
    assert empty["workspace_root"] == snap.root


def test_b10_json_kind_no_match_cli_empty_array(capsys):
    rc, o, e = _run(
        ["signals", "--workspace", str(FIXTURE), "--json", "--kind", "no_such_kind_xyz"],
        capsys,
    )
    assert rc == 0
    doc = json.loads(o)  # whole stdout still parses as one JSON object
    assert set(doc.keys()) == {"workspace_root", "signals"}
    assert doc["signals"] == []
    # JSON degrades to an empty array, never the human `(no signals collected)`.
    assert _EMPTY_MARKER not in o
    assert e == ""


def test_b10_json_kind_match_cli_filters_array(capsys):
    rc, o, e = _run(["signals", "--workspace", str(FIXTURE), "--json", "--kind", "note"], capsys)
    assert rc == 0
    doc = json.loads(o)
    assert doc["signals"], "the fixture has `note` signals"
    assert all(s["kind"] == "note" for s in doc["signals"])


# ===========================================================================
# Behavior 11 -- Bundled-fixture smoke (time- and environment-independent).
# ===========================================================================


def test_b11_fixture_smoke_todo_and_note_headers(capsys):
    # Resolve the fixture relative to the repo root (runner-location independent).
    fixture = Path(__file__).resolve().parents[1] / "examples" / "fixture_workspace"
    rc, o, e = _run(["signals", "--workspace", str(fixture)], capsys)
    assert rc == 0, f"fixture smoke must exit 0; stderr={e!r}"
    # ONLY these two environment-stable facts are asserted (the fixture's source
    # carries TODO/FIXME comments and a notes/journal.md).
    assert "## todo (" in o, f"fixture must yield a todo header; got:\n{o}"
    assert "## note (" in o, f"fixture must yield a note header; got:\n{o}"
    # Deliberately NOT asserting on ## git_commit / ## working_tree / ## recent_file:
    # git discovery walks UP into the enclosing repo (present in a checkout, absent
    # in a tarball export) and recent_file is date-sensitive -- none are portable.
