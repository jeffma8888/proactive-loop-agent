"""Independent black-box oracle for ``pla diff --fail-on-change`` (foundry iteration 319),
written by the tester from the spec's Expected Behaviors alone, alongside the engineer's
``test_iter277_behavior.py``.

WHAT THIS MODULE ADDS. Exactly two collected items, sized against the binding-headroom gauge
(``make readme-headroom`` read ``live=6090 binding_headroom=8`` on the engineer's tree, so two
items land on the permanent 6-item wall without moving it). They grade the corners the spec
names but the sibling module does not exercise: (1) under ``--json`` all three counters can
be non-zero AT ONCE and the gate line spells them in ``added removed changed`` order from the
payload's own list lengths, with the slate paths passed RELATIVE under ``cwd=tmp_path`` so any
resolution of "the path as given" would surface; (2) the flag composes with ``--dir`` in BOTH
directions -- two identical ticks exit ``0`` with an empty stderr and a stdout byte-identical
to the flagless run, a removed goal trips ``removed=1`` -- and the README documents the gate
only BELOW the human-owned portfolio marker, on the ``diff`` verb row and the exit-``5`` row.

ISOLATION CONTRACT (honored). Public ``main()`` driven in-process with ``capsys``; slate JSON
files written under ``tmp_path``; README read as a consumer would. Offline, deterministic,
no subprocess, no network. Score = impact * urgency * confidence / effort_weight, so a
4x ``impact`` bump moves a title-matched goal into ``changed``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest

from proactive_loop.cli import main

REPO: Final[Path] = Path(__file__).resolve().parents[1]

#: The one STDERR line the gate emits; the counters appear in exactly this order.
GATE_LINE: Final[str] = (
    "gate: fail-on-change tripped -- added={added} removed={removed} changed={changed}"
)


def _slate(path: Path, *goals: dict[str, Any]) -> str:
    """Write a minimal valid slate holding *goals*; return the path exactly as given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"goals": list(goals)}), encoding="utf-8")
    return str(path)


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """``(exit code, stdout, stderr)`` of one in-process ``pla`` invocation."""
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ===========================================================================
# Behaviors 1 + 3 -- --json with an added, a removed AND a changed goal in one diff: the
# whole stdout is still the flagless object, the gate line's three counters equal the
# payload's list lengths in `added removed changed` order, relative paths stay as given.
# ===========================================================================


def test_b3b_json_gate_reports_all_three_counters_from_the_payload_with_relative_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    old = _slate(
        Path("A.json"),
        {"title": "Keep the lockfile fresh", "impact": 1.0},
        {"title": "Retire the flaky test"},
    )
    new = _slate(
        Path("B.json"),
        {"title": "Keep the lockfile fresh", "impact": 4.0},
        {"title": "Add a CI badge"},
    )
    assert (old, new) == ("A.json", "B.json"), "argv carries the RELATIVE spelling"

    base_rc, base_out, base_err = _run(["diff", "--old", old, "--new", new, "--json"], capsys)
    assert (base_rc, base_err) == (0, ""), (base_rc, base_err)
    base_payload = json.loads(base_out)

    rc, out, err = _run(["diff", "--old", old, "--new", new, "--json", "--fail-on-change"], capsys)
    assert rc == 5, (rc, out, err)
    assert out == base_out, "the gate must not touch one byte of the JSON stdout"
    payload = json.loads(out)
    assert set(payload) == set(base_payload), "no new key rides along with the gate"
    counts = tuple(len(payload[key]) for key in ("added", "removed", "changed"))
    assert counts == (1, 1, 1), payload
    assert err == GATE_LINE.format(added=1, removed=1, changed=1) + "\n", repr(err)
    assert err.count("\n") == 1 and not err.startswith("error:"), repr(err)


# ===========================================================================
# Behaviors 2 + 4 + docs -- --dir composes in both directions (silent 0 on identical ticks,
# removed=1 trips), and the README documents the gate only BELOW the human-owned marker.
# ===========================================================================


def test_b4b_dir_stream_identical_ticks_exit_0_silently_removed_trips_and_readme_documents_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    goal = {"title": "Keep the lockfile fresh", "impact": 2.0}
    same = tmp_path / "same"
    _slate(same / "slate-001.json", goal)
    _slate(same / "slate-002.json", goal)
    base_rc, base_out, base_err = _run(["diff", "--dir", str(same)], capsys)
    assert (base_rc, base_err) == (0, ""), (base_rc, base_err)
    rc, out, err = _run(["diff", "--dir", str(same), "--fail-on-change"], capsys)
    assert (rc, err) == (0, ""), (rc, out, err)
    assert out == base_out, "an armed gate that did not trip leaves the rendering alone"

    dropped = tmp_path / "dropped"
    _slate(dropped / "slate-001.json", goal, {"title": "Retire the flaky test"})
    _slate(dropped / "slate-002.json", goal)
    rc, out, err = _run(["diff", "--dir", str(dropped), "--fail-on-change"], capsys)
    assert rc == 5, (rc, out, err)
    assert err == GATE_LINE.format(added=0, removed=1, changed=0) + "\n", repr(err)
    assert out and "gate:" not in out, "the gate line lives on stderr, never in the view"

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    marker = readme.index("PORTFOLIO INTRO")
    assert "fail-on-change" not in readme[:marker], "nothing above the human-owned marker moves"
    below = readme[marker:].splitlines()
    verb_row = next(line for line in below if line.startswith("| `diff`"))
    assert "--fail-on-change" in verb_row and "exits 5" in verb_row, verb_row
    exit_row = next(line for line in below if line.startswith("| 5 |"))
    assert "diff --fail-on-change" in exit_row, exit_row
    assert "pla diff --dir .pla_runs/stream --fail-on-change" in exit_row, exit_row
