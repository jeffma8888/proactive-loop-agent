"""Black-box behavior tests for ``pla trend --fail-on-persist N`` (foundry iter 290).

Feature under test: ``trend`` -- the read-only, LLM-free persistence inspector over a
``watch --out-dir`` stream -- gains the armed exit-5 gate its sibling read-only verbs
(``signals --fail-on-kind/--fail-over``, ``verify --fail-on-unresolved``,
``diff --fail-on-change``) already have: exit 5 when at least one goal title appears in
``>= N`` ticks of the stream, with stdout byte-unchanged and one ``gate:`` line on stderr.

WHAT THIS MODULE GRADES (FOUR collected items -- ``make readme-headroom`` read
``binding_headroom=15`` before this module, and the spec caps it at <= 4 items):
(1) EB1-3: the gate trips at N=3 (goals=1) and N=2 (goals=2 -- ticks are a TOTAL count, so a
gapped title still counts), and stays silent at N=4 (exit 0, empty stderr);
(2) EB4: stdout with the flag is byte-identical to stdout without it, for N in {2, 4}, in both
the human and the ``--json`` render, and ``--json`` stays exactly one JSON object;
(3) EB5-6: ``0``/``-1``/``abc`` are argparse usage errors (exit 2, empty stdout), and the
existing missing-dir / empty-dir refusals still win over an armed gate;
(4) EB7: the flag is documented in ``trend --help``, the ``pla --help`` exit-code epilog, the
code-5 bullet of ``main.__doc__``, README ``### Exit codes`` row 5 and SPEC's trend usage line.

Fully offline: ``main()`` runs in-process against ``GoalSlate`` JSON written straight into
``tmp_path`` (the shape ``pla watch --out-dir`` writes). No LLM, no watch, no network, no
sleeps, no mtime dependence, no gitignored state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.cli import main
from proactive_loop.models import CandidateGoal, GoalSlate

REPO: Final[Path] = Path(__file__).resolve().parents[1]
README: Final[Path] = REPO / "README.md"
SPEC: Final[Path] = REPO / "SPEC.md"
FLAG: Final[str] = "--fail-on-persist"

#: tick file -> goal titles. "A" persists in all 3 ticks, "B" in 001 and 003 (a gap), "C" only in 003.
TICKS: Final[dict[str, tuple[str, ...]]] = {
    "slate-001.json": ("A", "B"),
    "slate-002.json": ("A",),
    "slate-003.json": ("A", "B", "C"),
}


def _stream(root: Path) -> Path:
    stream = root / "stream"
    stream.mkdir()
    for name, titles in TICKS.items():
        slate = GoalSlate(goals=[CandidateGoal(title=t) for t in titles])
        (stream / name).write_text(slate.model_dump_json(), encoding="utf-8")
    return stream


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    try:
        rc = main(argv)
    except SystemExit as exc:  # argparse usage errors / --help
        code = exc.code
        rc = code if isinstance(code, int) else (0 if code is None else 1)
    out, err = capsys.readouterr()
    return int(rc), out, err


def test_b1_gate_trips_on_total_ticks_and_stays_silent_above(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stream = str(_stream(tmp_path))
    # EB1: only "A" is in >= 3 ticks.
    rc, out, err = _run(["trend", "--dir", stream, FLAG, "3"], capsys)
    assert rc == 5, (rc, err)
    assert err.splitlines() == ["gate: fail-on-persist tripped -- goals=1 threshold=3"], err
    assert out.strip(), "the report must still print on a tripped gate"
    # EB2: "B" has a gap but 2 total ticks, so it counts alongside "A".
    rc, out, err = _run(["trend", "--dir", stream, FLAG, "2"], capsys)
    assert rc == 5, (rc, err)
    assert err.splitlines() == ["gate: fail-on-persist tripped -- goals=2 threshold=2"], err
    # EB3: no title reaches 4 ticks (there are only 3).
    rc, out, err = _run(["trend", "--dir", stream, FLAG, "4"], capsys)
    assert rc == 0, (rc, err)
    assert err == "", err
    assert out.strip()


def test_b2_stdout_is_byte_identical_with_and_without_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stream = str(_stream(tmp_path))
    for render in ([], ["--json"]):
        rc, base, base_err = _run(["trend", "--dir", stream, *render], capsys)
        assert rc == 0, (render, rc, base_err)
        assert base_err == ""
        for n in ("2", "4"):
            rc, out, _ = _run(["trend", "--dir", stream, *render, FLAG, n], capsys)
            assert rc == (5 if n == "2" else 0), (render, n, rc)
            assert out == base, (render, n)
        if render:
            doc = json.loads(base)  # exactly one JSON document, or this raises
            assert isinstance(doc, dict), type(doc)


def test_b3_bad_values_are_usage_errors_and_refusals_still_win(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stream = str(_stream(tmp_path))
    for bad in ("0", "-1", "abc"):
        rc, out, err = _run(["trend", "--dir", stream, f"{FLAG}={bad}"], capsys)
        assert rc == 2, (bad, rc, err)
        assert out == "", (bad, out)
        assert FLAG in err, (bad, err)
    # EB6: a missing --dir is still the exit-2 refusal, never a gate.
    missing = str(tmp_path / "nope")
    rc, out, err = _run(["trend", "--dir", missing, FLAG, "1"], capsys)
    assert rc == 2, (rc, err)
    assert "error: --dir must be an existing directory" in err, err
    assert "gate:" not in err
    # An empty stream is still exit 2, not 0 and not 5.
    empty = tmp_path / "empty"
    empty.mkdir()
    rc, out, err = _run(["trend", "--dir", str(empty), FLAG, "1"], capsys)
    assert rc == 2, (rc, err)
    assert "gate:" not in err


def test_b4_flag_is_documented_on_every_exit_code_surface(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc, out, _ = _run(["trend", "--help"], capsys)
    assert rc == 0 and FLAG in out, out
    rc, top, _ = _run(["--help"], capsys)
    assert rc == 0
    epilog = top[top.lower().find("exit code") :]
    assert FLAG in epilog, top
    doc = main.__doc__ or ""
    start = doc.find("* ``5``")
    assert start >= 0, "main.__doc__ lost its code-5 bullet"
    end = doc.find("\n\n", start)
    assert FLAG in doc[start : end if end > 0 else None], doc[start:end]
    readme = README.read_text(encoding="utf-8")
    exit_block = readme[readme.index("### Exit codes") :]
    row5 = next(line for line in exit_block.splitlines() if line.startswith("| 5 |"))
    assert f"trend {FLAG}" in row5, row5
    assert "pla trend --dir DIR [--json] [--fail-on-persist N]" in SPEC.read_text(encoding="utf-8")
