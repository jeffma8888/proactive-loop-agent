"""Black-box behavior tests for foundry iteration 319 -- ``pla diff --fail-on-change``, the
fourth exit-5 gate: after rendering (human or ``--json``) the verb exits ``5`` with exactly
one ``gate: fail-on-change tripped -- added=A removed=R changed=C`` line on STDERR when the
diff reports at least one added, removed or changed goal, and ``0`` when nothing changed.

WHY THIS ITERATION EXISTS. ``watch --out-dir`` -> ``diff --dir`` is the product's only
"what changed last tick?" answer, and until now a CI step or pre-commit hook could not
branch on it without parsing ``--json``. Exit ``5`` is ALREADY the documented "a gate you
armed tripped on a finding" channel for ``signals --fail-on-kind``, ``signals --fail-over``
and ``verify --fail-on-unresolved``; ``diff`` was the one read-only consumer verb without
it. Same idiom, same code, one more verb -- no new concept, no new JSON key.

WHAT THIS MODULE GRADES. Exactly five collected items, funded net-negative by retiring five
byte-identical duplicate definitions elsewhere in the corpus (the binding-headroom gauge
sat exactly at ``MIN_BINDING_HEADROOM``, so a net-positive item delta would red
``test_iter270::test_b7``). The five items pin the CONTRACT, never the prose: (1) an added
goal trips the gate with byte-identical stdout, (2) an unchanged pair exits 0 silently,
(3) under ``--json`` the whole stdout is still one object equal to the flagless payload
and the gate counts equal the payload's list lengths, (4) the flag composes with
``--dir`` and a score move lands in ``changed``, (5) the flag is opt-in and every
pre-existing exit path (0 / 2 / 1) fires BEFORE the gate, while both help pages name the
new gate against exit 5.

ISOLATION CONTRACT (honored). Written from the spec's Expected Behaviors; the seams used
are the public ``main()`` entry point driven in-process with ``capsys`` and slate JSON
files written under ``tmp_path``. Offline, deterministic, no subprocess, no network;
score = impact * urgency * confidence / effort_weight, so bumping ``impact`` alone moves a
matched goal past ``_DIFF_EPSILON`` into ``changed``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from proactive_loop.cli import main

#: The one STDERR line the gate emits; the three counters appear in this order.
GATE_LINE = "gate: fail-on-change tripped -- added={added} removed={removed} changed={changed}"


def _slate(path: Path, *goals: dict[str, Any]) -> str:
    """Write a minimal valid slate holding *goals* and return its path as a string."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"goals": list(goals)}), encoding="utf-8")
    return str(path)


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """``(exit code, stdout, stderr)`` of one in-process ``pla`` invocation."""
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ===========================================================================
# Behavior 1 -- an added goal trips the gate; stdout is byte-identical to the flagless run.
# ===========================================================================


def test_b1_added_goal_exits_5_with_one_gate_line_and_identical_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = _slate(tmp_path / "A.json", {"title": "Keep the lockfile fresh"})
    new = _slate(
        tmp_path / "B.json",
        {"title": "Keep the lockfile fresh"},
        {"title": "Add a CI badge"},
    )
    base_rc, base_out, base_err = _run(["diff", "--old", old, "--new", new], capsys)
    assert (base_rc, base_err) == (0, ""), (base_rc, base_err)

    rc, out, err = _run(["diff", "--old", old, "--new", new, "--fail-on-change"], capsys)
    assert rc == 5, (rc, out, err)
    assert out == base_out, "the gate must not touch one byte of stdout"
    assert err == GATE_LINE.format(added=1, removed=0, changed=0) + "\n", repr(err)
    assert not err.startswith("error:"), "a changed slate is a finding, not a fault"


# ===========================================================================
# Behavior 2 -- identical goal sets: exit 0, stdout unchanged, stderr empty.
# ===========================================================================


def test_b2_identical_slates_exit_0_with_empty_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    goal = {"title": "Keep the lockfile fresh", "impact": 2.0}
    old = _slate(tmp_path / "A.json", goal)
    new = _slate(tmp_path / "B.json", goal)
    _, base_out, _ = _run(["diff", "--old", old, "--new", new], capsys)

    rc, out, err = _run(["diff", "--old", old, "--new", new, "--fail-on-change"], capsys)
    assert rc == 0, (rc, out, err)
    assert out == base_out, "an unchanged pair still prints the normal rendering"
    assert err == "", f"an armed gate that did not trip must stay silent; got {err!r}"


# ===========================================================================
# Behavior 3 -- --json: stdout is still ONE object equal to the flagless payload; the
# gate counts equal the payload's list lengths.
# ===========================================================================


def test_b3_json_stdout_is_one_object_and_gate_counts_match_the_payload(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = _slate(
        tmp_path / "A.json",
        {"title": "Keep the lockfile fresh"},
        {"title": "Retire the flaky test"},
    )
    new = _slate(tmp_path / "B.json", {"title": "Keep the lockfile fresh"})
    _, base_out, _ = _run(["diff", "--old", old, "--new", new, "--json"], capsys)
    base_payload = json.loads(base_out)

    rc, out, err = _run(
        ["diff", "--old", old, "--new", new, "--json", "--fail-on-change"], capsys
    )
    assert rc == 5, (rc, out, err)
    payload = json.loads(out)  # the ENTIRE stdout parses as exactly one object
    assert payload == base_payload, "the gate adds no key and changes no value"
    assert out == base_out
    added, removed, changed = (len(payload[k]) for k in ("added", "removed", "changed"))
    assert (added, removed, changed) == (0, 1, 0), payload
    assert err == GATE_LINE.format(added=added, removed=removed, changed=changed) + "\n", (
        repr(err)
    )


# ===========================================================================
# Behavior 4 -- --dir: the flag composes with the stream selector; a score move on a
# matched goal lands in `changed`.
# ===========================================================================


def test_b4_dir_stream_with_a_changed_goal_exits_5_with_changed_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stream = tmp_path / "stream"
    _slate(stream / "slate-001.json", {"title": "Keep the lockfile fresh", "impact": 1.0})
    _slate(stream / "slate-002.json", {"title": "Keep the lockfile fresh", "impact": 4.0})

    rc, out, err = _run(["diff", "--dir", str(stream), "--fail-on-change"], capsys)
    assert rc == 5, (rc, out, err)
    assert err == GATE_LINE.format(added=0, removed=0, changed=1) + "\n", repr(err)
    assert out, "the human rendering still precedes the gate line"


# ===========================================================================
# Behavior 5 -- opt-in default and precedence: every pre-existing exit path fires
# BEFORE the gate; both help pages name the gate against exit 5 (behavior 6).
# ===========================================================================


def test_b5_flag_is_opt_in_earlier_exits_win_and_help_names_exit_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = _slate(tmp_path / "A.json", {"title": "Keep the lockfile fresh"})
    new = _slate(tmp_path / "B.json", {"title": "Add a CI badge"})
    # Opt-in: a diff WITH differences and WITHOUT the flag exits 0 and writes no stderr.
    rc, out, err = _run(["diff", "--old", old, "--new", new], capsys)
    assert (rc, err) == (0, ""), (rc, out, err)
    assert "gate:" not in out

    # Usage errors exit 2 BEFORE any gate evaluation, flag or no flag.
    stream = tmp_path / "stream"
    _slate(stream / "slate-001.json", {"title": "x"})
    _slate(stream / "slate-002.json", {"title": "y"})
    rc, out, err = _run(
        ["diff", "--dir", str(stream), "--old", old, "--fail-on-change"], capsys
    )
    assert rc == 2, (rc, out, err)
    assert "gate:" not in err and err.startswith("error:"), repr(err)
    rc, out, err = _run(
        ["diff", "--old", old, "--new", str(tmp_path / "missing.json"), "--fail-on-change"],
        capsys,
    )
    assert rc == 2, (rc, out, err)
    assert "gate:" not in err and "slate file not found" in err, repr(err)

    # A goals-less `{}` slate still exits 1 via the shared loader; the gate never runs.
    goals_less = tmp_path / "gl.json"
    goals_less.write_text("{}", encoding="utf-8")
    rc, out, err = _run(
        ["diff", "--old", str(goals_less), "--new", new, "--fail-on-change"], capsys
    )
    assert rc == 1, (rc, out, err)
    assert "gate:" not in err and err.startswith("error:"), repr(err)

    # Behavior 6: `pla --help` names the gate under exit 5; `pla diff --help` lists it.
    with pytest.raises(SystemExit) as top:
        main(["--help"])
    assert top.value.code == 0
    top_help = capsys.readouterr().out
    assert "diff --fail-on-change" in top_help, top_help
    epilog = top_help[top_help.index("exit codes:"):]
    assert "diff --fail-on-change" in epilog, epilog
    assert all(len(line) <= 78 for line in epilog.splitlines()), (
        "the exit-codes epilog wrap must stay valid at 78 columns"
    )
    with pytest.raises(SystemExit) as verb:
        main(["diff", "--help"])
    assert verb.value.code == 0
    verb_help = capsys.readouterr().out
    assert "--fail-on-change" in verb_help, verb_help
    # The option ENTRY (not the usage synopsis): argparse indents the option line by
    # two spaces and every continuation line deeper, so the entry ends at the first
    # line that is not indented past the option column.
    tail = verb_help[verb_help.index("\n  --fail-on-change") + 1 :].splitlines()
    entry = [tail[0]]
    for line in tail[1:]:
        if not line.startswith("    "):
            break
        entry.append(line)
    entry_text = "\n".join(entry)
    assert "Exit 5" in entry_text, f"the help string must name exit 5:\n{entry_text}"
