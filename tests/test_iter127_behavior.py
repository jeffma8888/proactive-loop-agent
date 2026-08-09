"""Black-box behavior tests for factory iteration 127 --- ``pla signals --fail-on-kind``.

Feature under test: a repeatable ``--fail-on-kind KIND`` flag on the shipped
``pla signals`` verb that leaves stdout byte-identical and exits with the new
code ``5`` when the command REPORTS at least one signal of a named kind, so
``pla signals`` can gate a pre-commit hook or a CI step. This is the product's
first ENFORCEMENT mode: sixteen collectors could previously only be read.

ISOLATION CONTRACT (honored): every assertion is written strictly against this
iteration's spec (``pm.md`` "Expected Behaviors" 1-9) and the published
``README.md``, and drives ONLY documented public surfaces --- the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (its stdout / stderr / exit code),
``main.__doc__``, ``--help``, and the public
``proactive_loop.collectors.SIGNAL_KINDS`` registry that the in-tree iter-108
suite already treats as public. **No file under ``src/`` was read by the author,
no engineer or reviewer notes were read, and no ``git diff`` was consulted.**

Expected values are DERIVED wherever a derivation exists --- the per-kind counts
in the stderr gate line are computed from the command's own ``--json`` listing,
and the "kind that cannot match" fixture is chosen as ``SIGNAL_KINDS`` minus the
kinds that listing reports --- so these tests cannot silently encode an
implementation quirk or a fixture that stops being negative when a collector
changes.

Fully offline and deterministic: zero network, zero API keys, no subprocess, no
sleeps, no LLM client, no git invocation. Every workspace is a fresh ``tmp_path``
(never the repo tree), and the only planted "secret" is an EMPTY ``.env`` ---
``SecretFileCollector`` matches on FILE NAME, so no credential-shaped string is
ever written into this public repo.

AMBIGUITY NOTES (PM feedback):

* Behavior 5 requires that "no collection runs" for an unknown kind. Collection
  is not directly observable black-box, so it is tested two ways: stdout is
  empty (no listing was produced), and with a ``--workspace`` that does NOT
  exist the reported error is still argparse's invalid-choice message rather
  than the workspace error --- which is only possible if the rejection happens
  at parse time, before the path is even examined. That is the strongest
  external evidence available; a direct "collector never ran" probe would
  require reading the implementation.
* Behavior 7 says the ``--collector`` rule matches the ``--min-weight`` rule
  (narrowing that hides the finding exits 0) while behavior 8 refuses a
  ``--kind``/``--fail-on-kind`` contradiction at parse time with exit 2. So a
  ``--collector`` that excludes the gated kind is deliberately NOT a usage
  error, because collector-to-kind is a runtime relation rather than one
  argparse can decide. Tested per that reading; worth pinning in a future spec.
"""

from __future__ import annotations

import contextlib
import io
import json
from collections import Counter
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.collectors import SIGNAL_KINDS

_GATE_PREFIX = "gate: fail-on-kind tripped -- "
_GATE_CODE = 5


# ---------------------------------------------------------------------------
# Helpers --- black-box: plant a workspace, drive main(), read back stdout /
# stderr / exit code.
# ---------------------------------------------------------------------------


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Drive ``main(argv)``; return ``(exit_code, stdout, stderr)``.

    Normal path: ``main`` returns an int. argparse paths raise ``SystemExit``
    (``--help`` -> 0, a usage error -> 2); both are normalized to a code so the
    exit contract is observable (iter-98/126 convention).
    """
    out, err = io.StringIO(), io.StringIO()
    code: int
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rv = main(argv)
            code = rv if isinstance(rv, int) else 0
        except SystemExit as exc:  # argparse --help / usage error
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return code, out.getvalue(), err.getvalue()


def _secret_ws(tmp_path: Path) -> Path:
    """A workspace whose reported signals include exactly one ``secret_file``.

    ``SecretFileCollector`` matches on FILE NAME (``.env``), never on contents,
    so an EMPTY ``.env`` is a sufficient and fully deterministic fixture.
    """
    ws = tmp_path / "secret_ws"
    ws.mkdir()
    (ws / ".env").write_text("")
    return ws


def _clean_ws(tmp_path: Path) -> Path:
    """A workspace with NO ``secret_file`` signal, but not an empty directory.

    ``.env.example`` is explicitly EXCLUDED by the collector, so the negative
    case proves the gate keys off the REPORTED SIGNAL and not merely off a
    filename that looks env-ish. Other kinds (no license, no CI, ...) are still
    reported here, so a gate that tripped on "any signal at all" would fail.
    """
    ws = tmp_path / "clean_ws"
    ws.mkdir()
    (ws / ".env.example").write_text("API_KEY=\n")
    (ws / "mod.py").write_text("x = 1\n")  # so OTHER kinds are still reported
    return ws


def _mixed_ws(tmp_path: Path) -> Path:
    """A workspace reporting BOTH ``secret_file`` (1) and ``todo`` (2), for the
    multi-kind ordering and count assertions."""
    ws = tmp_path / "mixed_ws"
    ws.mkdir()
    (ws / ".env").write_text("")
    (ws / "mod.py").write_text("x = 1  # TODO: tidy\ny = 2  # TODO: again\n")
    return ws


def _reported(ws: Path, *narrowing: str) -> Counter[str]:
    """Per-kind counts the command ITSELF reports for ``ws`` under the given
    narrowing flags, read from its ``--json`` listing.

    This is the oracle for behavior 3's counts and behavior 7's "the gate sees
    exactly what the view reports" --- expectations are derived from the
    product's own listing rather than hard-coded.
    """
    code, out, _ = _run(["signals", "--workspace", str(ws), "--json", *narrowing])
    assert code == 0, f"listing probe failed ({code}): {out!r}"
    payload = json.loads(out)
    return Counter(str(s["kind"]) for s in payload["signals"])


def _gate_line(stderr: str) -> str:
    """The single gate line, asserting there is exactly one."""
    lines = [ln for ln in stderr.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly one stderr line, got {lines!r}"
    return lines[0]


def _absent_kind(ws: Path) -> str:
    """A registry kind this workspace does NOT report --- derived, so it stays a
    true negative even if a collector's behavior changes later."""
    present = set(_reported(ws))
    candidates = sorted(set(SIGNAL_KINDS) - present)
    assert candidates, f"no unreported kind available for {ws}"
    return candidates[0]


# ---------------------------------------------------------------------------
# Behavior 1 --- trip: exit 5, stdout byte-identical to the ungated run.
# ---------------------------------------------------------------------------


def test_b1_gate_trips_with_exit_5(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    code, out, _ = _run(["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file"])
    assert code == _GATE_CODE, f"expected exit 5 on a reported secret_file signal, got {code}; stdout={out!r}"
    assert "secret_file" in out, "the listing must still be printed when the gate trips"


def test_b1_stdout_is_byte_identical_to_ungated_run(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    base_code, base_out, base_err = _run(["signals", "--workspace", str(ws)])
    gate_code, gate_out, _ = _run(["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file"])
    assert base_code == 0, base_out
    assert base_err == "", "the ungated run must write nothing to stderr"
    assert gate_code == _GATE_CODE
    assert gate_out == base_out, "the gate must change exit status and stderr only, never the listing"


# ---------------------------------------------------------------------------
# Behavior 2 --- clean: exit 0, stdout byte-identical, stderr silent.
# ---------------------------------------------------------------------------


def test_b2_clean_workspace_exits_zero_and_is_silent(tmp_path: Path) -> None:
    ws = _clean_ws(tmp_path)
    assert "secret_file" not in _reported(ws), "fixture is not negative: .env.example must be excluded"
    base_code, base_out, _ = _run(["signals", "--workspace", str(ws)])
    code, out, err = _run(["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file"])
    assert base_code == 0
    assert code == 0, f"an unarmed gate must not change the exit status, got {code}"
    assert out == base_out, "stdout must be byte-identical when the gate does not trip"
    assert err == "", f"a gate that does not trip must write nothing to stderr, got {err!r}"


def test_b2_gate_does_not_trip_on_signals_of_other_kinds(tmp_path: Path) -> None:
    """Fail-closed in the other direction: the clean workspace DOES report other
    kinds, so a gate keyed on 'any signal' would wrongly trip here."""
    ws = _clean_ws(tmp_path)
    assert sum(_reported(ws).values()) > 0, "fixture must still report some signals"
    code, _, err = _run(["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file"])
    assert (code, err) == (0, "")


# ---------------------------------------------------------------------------
# Behavior 3 --- exactly one stderr line, deterministic format, ascending kinds.
# ---------------------------------------------------------------------------


def test_b3_single_kind_stderr_line_exact_format(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    expected_count = _reported(ws)["secret_file"]
    assert expected_count == 1, f"fixture drift: expected one secret_file signal, got {expected_count}"
    _, _, err = _run(["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file"])
    assert _gate_line(err) == f"{_GATE_PREFIX}secret_file={expected_count}"


def test_b3_multiple_matched_kinds_are_comma_joined_in_ascending_order(tmp_path: Path) -> None:
    ws = _mixed_ws(tmp_path)
    counts = _reported(ws)
    assert counts["secret_file"] == 1 and counts["todo"] == 2, f"fixture drift: {counts}"
    # Named deliberately in DESCENDING order, so ascending output cannot be an
    # accident of argument order.
    _, _, err = _run(
        ["signals", "--workspace", str(ws), "--fail-on-kind", "todo", "--fail-on-kind", "secret_file"]
    )
    assert _gate_line(err) == f"{_GATE_PREFIX}secret_file=1, todo=2"


def test_b3_gate_line_is_a_finding_not_a_fault(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    _, _, err = _run(["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file"])
    line = _gate_line(err)
    assert not line.startswith("error:"), "a tripped gate is a finding, not a fault"
    assert "Traceback" not in err and "Error" not in err, err


# ---------------------------------------------------------------------------
# Behavior 4 --- repeatable, OR semantics, matched kinds only.
# ---------------------------------------------------------------------------


def test_b4_or_semantics_trip_when_only_one_named_kind_is_present(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    absent = _absent_kind(ws)
    code, _, err = _run(
        ["signals", "--workspace", str(ws), "--fail-on-kind", absent, "--fail-on-kind", "secret_file"]
    )
    assert code == _GATE_CODE, f"OR semantics: one present kind must trip the gate (absent={absent})"
    assert _gate_line(err) == f"{_GATE_PREFIX}secret_file=1"


def test_b4_unmatched_named_kind_never_appears_in_the_line(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    absent = _absent_kind(ws)
    _, _, err = _run(
        ["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file", "--fail-on-kind", absent]
    )
    assert absent not in err, f"kind {absent} has zero reported signals and must not be listed: {err!r}"


def test_b4_all_named_kinds_absent_exits_zero(tmp_path: Path) -> None:
    ws = _clean_ws(tmp_path)
    absent = _absent_kind(ws)
    code, _, err = _run(
        ["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file", "--fail-on-kind", absent]
    )
    assert (code, err) == (0, "")


def test_b4_repeating_the_same_kind_is_idempotent(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    code, _, err = _run(
        [
            "signals",
            "--workspace",
            str(ws),
            "--fail-on-kind",
            "secret_file",
            "--fail-on-kind",
            "secret_file",
        ]
    )
    assert code == _GATE_CODE
    assert _gate_line(err) == f"{_GATE_PREFIX}secret_file=1", "a repeated kind must not be double-counted"


# ---------------------------------------------------------------------------
# Behavior 5 --- unknown kind is a PARSE-time usage error (exit 2).
# ---------------------------------------------------------------------------


def test_b5_unknown_kind_is_rejected_with_exit_2(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    code, out, err = _run(["signals", "--workspace", str(ws), "--fail-on-kind", "nosuchkind"])
    assert code == 2, f"an unknown gate kind must be a usage error, got {code}"
    assert out == "", f"no collection may run, so nothing may be listed; got {out!r}"
    assert "nosuchkind" in err, "the message must name the rejected value"


def test_b5_message_lists_the_accepted_vocabulary_from_the_live_registry(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    _, _, err = _run(["signals", "--workspace", str(ws), "--fail-on-kind", "nosuchkind"])
    missing = [k for k in SIGNAL_KINDS if k not in err]
    assert not missing, f"rejection must list every accepted kind; missing {missing}"


def test_b5_rejection_precedes_the_workspace_check(tmp_path: Path) -> None:
    """Parse-time evidence: with a workspace that does not exist, the invalid
    choice is still what is reported --- the path was never examined."""
    missing_ws = tmp_path / "does_not_exist"
    code, out, err = _run(["signals", "--workspace", str(missing_ws), "--fail-on-kind", "nosuchkind"])
    assert code == 2
    assert out == ""
    assert "nosuchkind" in err, f"expected the parse-time invalid-choice error, got {err!r}"


# ---------------------------------------------------------------------------
# Behavior 6 --- rendering-independent exit status.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rendering", [[], ["--json"], ["--summary"]])
def test_b6_exit_status_is_identical_across_renderings(tmp_path: Path, rendering: list[str]) -> None:
    ws = _secret_ws(tmp_path)
    code, _, err = _run(["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file", *rendering])
    assert code == _GATE_CODE, f"rendering {rendering or ['<default>']} changed the exit status to {code}"
    assert _gate_line(err) == f"{_GATE_PREFIX}secret_file=1"


@pytest.mark.parametrize("rendering", [[], ["--json"], ["--summary"]])
def test_b6_clean_exit_status_is_identical_across_renderings(tmp_path: Path, rendering: list[str]) -> None:
    ws = _clean_ws(tmp_path)
    code, _, err = _run(["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file", *rendering])
    assert (code, err) == (0, "")


def test_b6_json_stdout_stays_exactly_one_object_with_no_gate_prose(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    base_code, base_out, _ = _run(["signals", "--workspace", str(ws), "--json"])
    code, out, err = _run(["signals", "--workspace", str(ws), "--json", "--fail-on-kind", "secret_file"])
    assert base_code == 0 and code == _GATE_CODE
    assert out == base_out, "the gate must add no prose to --json stdout"
    parsed = json.loads(out)  # exactly one object, still machine-parseable
    assert isinstance(parsed, dict)
    assert _gate_line(err).startswith(_GATE_PREFIX), "the gate's only output is the stderr line"


def test_b6_summary_stdout_is_byte_identical(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    _, base_out, _ = _run(["signals", "--workspace", str(ws), "--summary"])
    code, out, _ = _run(["signals", "--workspace", str(ws), "--summary", "--fail-on-kind", "secret_file"])
    assert code == _GATE_CODE
    assert out == base_out


# ---------------------------------------------------------------------------
# Behavior 7 --- the gate sees exactly what the view reports.
# ---------------------------------------------------------------------------


def test_b7_min_weight_that_hides_the_finding_exits_zero(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    narrowed = _reported(ws, "--min-weight", "0.99")
    assert "secret_file" not in narrowed, f"probe drift: 0.85-weight secret still reported: {narrowed}"
    code, _, err = _run(
        ["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file", "--min-weight", "0.99"]
    )
    assert code == 0, "a signal the view does not report cannot trip a gate"
    assert err == ""


def test_b7_min_weight_below_the_finding_still_trips(tmp_path: Path) -> None:
    ws = _secret_ws(tmp_path)
    code, _, _ = _run(
        ["signals", "--workspace", str(ws), "--fail-on-kind", "secret_file", "--min-weight", "0.5"]
    )
    assert code == _GATE_CODE, "narrowing that still reports the signal must still trip"


def test_b7_collector_narrowing_that_hides_the_finding_exits_zero(tmp_path: Path) -> None:
    ws = _mixed_ws(tmp_path)
    narrowed = _reported(ws, "--collector", "todos")
    assert "secret_file" not in narrowed and narrowed["todo"] == 2, f"probe drift: {narrowed}"
    code, _, err = _run(
        ["signals", "--workspace", str(ws), "--collector", "todos", "--fail-on-kind", "secret_file"]
    )
    assert (code, err) == (0, "")


def test_b7_exit_status_agrees_with_the_listing_for_every_reported_kind(tmp_path: Path) -> None:
    """Sweep: every kind the listing reports must trip, and the derived absent
    kind must not --- so the exit status can never disagree with stdout."""
    ws = _mixed_ws(tmp_path)
    counts = _reported(ws)
    for kind, n in sorted(counts.items()):
        code, _, err = _run(["signals", "--workspace", str(ws), "--fail-on-kind", kind])
        assert code == _GATE_CODE, f"reported kind {kind} ({n}) failed to trip the gate"
        assert _gate_line(err) == f"{_GATE_PREFIX}{kind}={n}"
    absent = _absent_kind(ws)
    code, _, err = _run(["signals", "--workspace", str(ws), "--fail-on-kind", absent])
    assert (code, err) == (0, ""), f"unreported kind {absent} must not trip"


# ---------------------------------------------------------------------------
# Behavior 8 --- a gate that could never fire is refused, not silently dead.
# ---------------------------------------------------------------------------


def test_b8_contradictory_kind_and_gate_is_refused_with_exit_2(tmp_path: Path) -> None:
    ws = _mixed_ws(tmp_path)
    code, out, err = _run(
        ["signals", "--workspace", str(ws), "--kind", "todo", "--fail-on-kind", "secret_file"]
    )
    assert code == 2, f"a gate excluded from the view by construction must be refused, got {code}"
    assert out == "", f"the refusal must precede collection, so nothing may be listed; got {out!r}"
    line = _gate_line(err)
    assert line.startswith("error: "), f"expected exactly one 'error: ...' line, got {err!r}"
    assert "secret_file" in line and "todo" in line, "the refusal must name both kinds"


def test_b8_refusal_happens_before_the_workspace_is_examined(tmp_path: Path) -> None:
    missing_ws = tmp_path / "nope"
    code, out, _ = _run(
        ["signals", "--workspace", str(missing_ws), "--kind", "todo", "--fail-on-kind", "secret_file"]
    )
    assert code == 2 and out == ""


def test_b8_agreeing_kind_and_gate_is_accepted(tmp_path: Path) -> None:
    ws = _mixed_ws(tmp_path)
    code, out, err = _run(
        ["signals", "--workspace", str(ws), "--kind", "secret_file", "--fail-on-kind", "secret_file"]
    )
    assert code == _GATE_CODE, "the agreeing combination must behave per behaviors 1-2"
    assert "secret_file" in out
    assert _gate_line(err) == f"{_GATE_PREFIX}secret_file=1"


def test_b8_agreeing_kind_on_a_clean_workspace_exits_zero(tmp_path: Path) -> None:
    ws = _clean_ws(tmp_path)
    code, _, err = _run(
        ["signals", "--workspace", str(ws), "--kind", "secret_file", "--fail-on-kind", "secret_file"]
    )
    assert (code, err) == (0, "")


# ---------------------------------------------------------------------------
# Behavior 9 --- the exit-code contract is extended in the same commit.
# ---------------------------------------------------------------------------

_README = Path(__file__).resolve().parents[1] / "README.md"


def test_b9_readme_exit_code_table_documents_code_5() -> None:
    text = _README.read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if ln.startswith("| 5 ")]
    assert len(rows) == 1, f"expected exactly one exit-code table row for 5, got {rows!r}"
    row = rows[0].lower()
    assert "gate" in row, f"the code-5 row must describe a gate tripping on a finding: {rows[0]!r}"
    assert "fail-on-kind" in row, f"the code-5 row must name the flag that produces it: {rows[0]!r}"


def test_b9_main_docstring_enumerates_code_5() -> None:
    doc = main.__doc__ or ""
    assert doc, "main() must keep its documented exit-code contract in its docstring"
    for code in ("0", "1", "2", "3", "4", "5"):
        assert code in doc, f"main.__doc__ must enumerate exit code {code}"
    assert "5" in doc and "gate" in doc.lower(), f"code 5 must be described as a gate: {doc!r}"


def test_b9_readme_cli_reference_documents_the_flag() -> None:
    text = _README.read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if ln.startswith("| `signals` |")]
    assert len(rows) == 1, f"expected one signals verb-table row, got {len(rows)}"
    assert "--fail-on-kind" in rows[0], "the signals row must document the new flag"
    assert "5" in rows[0], "the signals row must state the exit-5 contract"


def test_b9_help_text_states_the_exit_5_and_byte_identical_contract() -> None:
    code, out, _ = _run(["signals", "--help"])
    assert code == 0
    assert "--fail-on-kind" in out, "the flag must be discoverable from --help"
    assert "5" in out and "identical" in out.lower(), "help must state the exit-5 / stdout contract"


@pytest.mark.parametrize("verb", ["scan", "dispatch", "run"])
def test_b9_no_other_verb_gained_the_gate(tmp_path: Path, verb: str) -> None:
    """Out-of-scope guard: enforcement is on ``signals`` ONLY --- every other verb
    must still REJECT the flag (exit 2) rather than quietly grow an exit-5 path."""
    ws = _secret_ws(tmp_path)
    code, out, err = _run([verb, "--workspace", str(ws), "--fail-on-kind", "secret_file"])
    assert code == 2, f"{verb} must reject --fail-on-kind as an unknown flag, got {code}"
    assert _GATE_PREFIX not in err, f"{verb} must not emit a gate line: {err!r}"
    assert _GATE_PREFIX not in out


def test_b9_read_only_verbs_keep_exit_zero(tmp_path: Path) -> None:
    """The LLM-free inspection verbs still exit 0 with no gate line when no gate
    is armed, so adding the flag did not change the default contract."""
    ws = _secret_ws(tmp_path)
    for argv in (["collectors"], ["signals", "--workspace", str(ws)]):
        code, _, err = _run(argv)
        assert code == 0, f"{argv} must still exit 0, got {code}"
        assert err == "", f"{argv} must stay silent on stderr, got {err!r}"
