"""Foundry iteration 279 -- the ``recent_file`` weight quantum, pinned as measured fact.

Why this module exists
Iteration 279 repairs ``tests/test_iter241_behavior.py``'s ``--baseline`` round trip,
which passed VACUOUSLY in every warm working tree (the tracked
``examples/fixture_workspace`` files are far older than the collector's 14-day
window, so zero signals were subtracted from zero signals) and FAILED in a fresh
clone, where every mtime is the clone instant. That failure reverted iteration 278's
green work at ``preship``. The repair stamps the mtimes of a tmp COPY so both halves
of the round trip read the same weight; this module pins the two facts that repair
depends on, so a later reader cannot re-derive them wrong.

Fact one: a ``recent_file`` weight is a CLOCK READING with a 1e-4 quantum.
``RecentFilesCollector`` weights a file by its age against the window, rounded to
4 decimal places, so one rounding step is 1e-4 * within_days(14.0) * 86_400 == 120.96
seconds of file age. A weight therefore CHANGES BY ITSELF roughly every two minutes.
Fact two: that weight is one of the six keys a ``--baseline`` subtraction compares,
so two captures that straddle one step disagree about EVERY recent file at once --
which is why the round trip may only compare captures inside the sub-60s plateau
where the 4-dp value is exactly 1.0, and why it may not simply sleep or retry.

Five decisions worth the next reader's time
1. **Every age here is stamped onto a file under ``tmp_path``; NOTHING in this module
   reads or writes the mtime of a tracked path.** The tracked fixture's mtimes are
   ambient state -- 49.9 days old in this working tree, 0 seconds old in a fresh
   clone -- so an assertion about them passes here and fails at ``preship``. That is
   the exact bug iteration 279 exists to fix, and it must not be re-introduced by the
   module that documents it.
2. **The probes sit in band INTERIORS, never on a band boundary.** The collector
   reads its own ``time.time()`` a moment after ``os.utime``, so the effective age is
   always slightly LARGER than the stamped age; each probe keeps >= 1.4s of margin on
   the side that matters, and the boundaries themselves (60.48s, 181.44s) are asserted
   only through the band values on either side.
3. **The state dir 279 spec's behavior 7 is WRONG about age 200.0s and this module
   pins the MEASURED value instead.** The spec asserts ``weight == 0.9999`` there; the
   collector returns ``0.9998``, because 200.0 is one full step past that band
   (bands: 1.0 below 60.48s, 0.9999 in [60.48, 181.44), 0.9998 in [181.44, 302.40)).
   Encoding the spec literally would have opened this module RED. Recorded as PM
   feedback in ``tester.md``; the rest of that behavior's reasoning measures true.
4. **``_signal_identity`` is asserted with a POSITIVE CONTROL next to the negative
   one.** "Two signals differing only in weight get different identities" is satisfied
   by a helper that returns something different every call, so the same test also
   proves two identical signals share one identity.
5. **No subprocess, no network, no clock-dependent sleep, no gitignored path.** Ages
   are set explicitly rather than waited for, so the module is deterministic, runs in
   well under a second, and reads identically on the 3.12 and 3.13 matrix legs. No
   assertion depends on docstring indentation.
"""

from __future__ import annotations

import ast
import os
import shutil
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop import cli
from proactive_loop.collectors.filesystem import RecentFilesCollector
from proactive_loop.models import ContextSignal

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: The tracked workspace the gate scans in place and the round trip now COPIES.
#: Read for its CONTENT only -- never for its mtimes, see decision 1.
FIXTURE_WORKSPACE: Final[Path] = REPO_ROOT / "examples" / "fixture_workspace"

#: The window the round trip and the demo both run the collector with.
WITHIN_DAYS: Final[float] = 14.0

#: One 1e-4 rounding step of a ``recent_file`` weight, in seconds of file age.
QUANTUM_SECONDS: Final[float] = 1e-4 * WITHIN_DAYS * 86_400  # == 120.96

#: Ages whose 4-dp weight is exactly 1.0 -- the plateau the round trip lives in.
#: 59.0 is the spec's own upper probe and keeps 1.48s of margin under 60.48.
PLATEAU_AGES: Final[tuple[float, ...]] = (0.0, 30.0, 59.0)

#: Ages one step down. Interiors of [60.48, 181.44), margins >= 1.5s.
FIRST_STEP_AGES: Final[tuple[float, ...]] = (62.0, 120.0, 170.0)

#: Ages two steps down. Interiors of [181.44, 302.40), margins >= 8.5s.
SECOND_STEP_AGES: Final[tuple[float, ...]] = (190.0, 200.0, 290.0)

#: Older than the window, so the collector must emit nothing at all. This is the
#: state the tracked fixture is in today (49.9 days) and the reason the round trip
#: was vacuous for 37 iterations.
BEYOND_WINDOW_SECONDS: Final[float] = 15.0 * 86_400


# ======================================================================================
# Helpers
# ======================================================================================


def _stamp(path: Path, age_seconds: float) -> None:
    """Set ``path``'s atime and mtime to exactly ``age_seconds`` ago."""
    when = time.time() - age_seconds
    os.utime(path, (when, when))


def _weight_at_age(tmp_path: Path, age_seconds: float) -> float:
    """Collect one ``recent_file`` signal for a file of the given age."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "probe.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _stamp(target, age_seconds)
    signals = [
        signal
        for signal in RecentFilesCollector(within_days=WITHIN_DAYS).collect(tmp_path)
        if signal.kind == "recent_file"
    ]
    assert len(signals) == 1, (
        f"a single file of age {age_seconds}s must yield exactly one `recent_file` "
        f"signal, got {len(signals)}: {[s.summary for s in signals]}"
    )
    return signals[0].weight


def _scannable_relative_paths(root: Path) -> frozenset[str]:
    """Relative POSIX paths of the non-hidden regular files under ``root``."""
    return frozenset(
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
    )


def _recent_file_signals(root: Path) -> list[ContextSignal]:
    return [
        signal
        for signal in RecentFilesCollector(within_days=WITHIN_DAYS).collect(root)
        if signal.kind == "recent_file"
    ]


def _module_docstring() -> str:
    """This module's own docstring, parsed rather than re-read as raw text.

    Reading the raw file would let behavior 7's prose assertion match its OWN search
    literal -- a self-hit that passes with the docstring deleted.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    docstring = ast.get_docstring(tree)
    assert docstring is not None, "this module must keep its explanatory docstring"
    return docstring


@pytest.fixture
def signal_pair() -> tuple[ContextSignal, ContextSignal]:
    """Two signals identical in every field except ``weight``."""
    common = {
        "source": "filesystem",
        "kind": "recent_file",
        "summary": "edited today: agent.py",
        "detail": "projects/ai-experiments/agent.py",
        "path": "projects/ai-experiments/agent.py",
    }
    return (
        ContextSignal(**common, weight=1.0),
        ContextSignal(**common, weight=0.9999),
    )


# ======================================================================================
# Behavior 7 -- the 120.96s weight quantum is a pinned, measured fact
# ======================================================================================


def test_b07a_plateau_ages_report_a_weight_of_exactly_one(tmp_path: Path) -> None:
    """Behavior 7: ages 0.0, 30.0 and 59.0 seconds all weigh exactly 1.0.

    Exactly, not ``pytest.approx``: the round trip compares weights as part of a
    set-membership identity, so a value that is merely close is a residual signal.
    """
    for age in PLATEAU_AGES:
        weight = _weight_at_age(tmp_path / f"plateau_{age}", age)
        assert weight == 1.0, (
            f"age {age}s must sit on the weight plateau and report EXACTLY 1.0 "
            f"(the only band in which a produce half and a consume half are "
            f"comparable by construction), got {weight!r}"
        )


def test_b07b_ages_past_the_first_step_report_exactly_0_9999(tmp_path: Path) -> None:
    """Behavior 7: one quantum of age below the plateau costs exactly 1e-4."""
    for age in FIRST_STEP_AGES:
        weight = _weight_at_age(tmp_path / f"step1_{age}", age)
        assert weight == 0.9999, (
            f"age {age}s lies in [60.48, 181.44) -- one 1e-4 rounding step past the "
            f"plateau -- so the weight must be exactly 0.9999, got {weight!r}"
        )


def test_b07c_age_200s_reports_0_9998_correcting_the_specs_claim(
    tmp_path: Path,
) -> None:
    """Behavior 7, CORRECTED: 200.0s weighs 0.9998, not the spec's 0.9999.

    The spec's arithmetic (a 120.96s quantum) is right and its conclusion about
    200.0s is one band off. Pinning the measured value is the whole point of the
    behavior, so this module pins 0.9998 and says why.
    """
    for age in SECOND_STEP_AGES:
        weight = _weight_at_age(tmp_path / f"step2_{age}", age)
        assert weight == 0.9998, (
            f"age {age}s lies in [181.44, 302.40) -- TWO 1e-4 steps past the "
            f"plateau -- so the weight must be exactly 0.9998, got {weight!r}"
        )


def test_b07d_the_quantum_arithmetic_is_120_96_seconds() -> None:
    """Behavior 7: ``1e-4 * within_days * 86_400 == 120.96`` seconds of age."""
    assert QUANTUM_SECONDS == pytest.approx(120.96), (
        "one 1e-4 rounding step of a `recent_file` weight must be 120.96 seconds "
        f"of file age, got {QUANTUM_SECONDS!r}"
    )
    assert QUANTUM_SECONDS / 2 == pytest.approx(60.48), (
        "half a quantum -- the width of the exactly-1.0 plateau -- must be 60.48s"
    )


def test_b07e_two_ages_one_quantum_apart_differ_by_exactly_one_step(
    tmp_path: Path,
) -> None:
    """Behavior 7: the quantum is MEASURED, not only computed on paper.

    Both probes sit deep inside their bands (100.0s and 220.96s), so this asserts
    the SIZE of the step rather than the position of a boundary.
    """
    younger = _weight_at_age(tmp_path / "younger", 100.0)
    older = _weight_at_age(tmp_path / "older", 100.0 + QUANTUM_SECONDS)
    assert round(younger - older, 6) == 0.0001, (
        f"two ages exactly one 120.96s quantum apart must differ by exactly one "
        f"1e-4 weight step; got {younger!r} - {older!r} = {younger - older!r}"
    )


def test_b07f_the_module_states_the_quantum_derivation_in_prose() -> None:
    """Behavior 7: the oracle explains, in prose, WHY the plateau is mandatory."""
    docstring = _module_docstring()
    for phrase in (
        "1e-4 * within_days(14.0) * 86_400 == 120.96",
        "sub-60s plateau",
        "CLOCK READING",
    ):
        assert phrase in docstring, (
            f"the module docstring must state {phrase!r} so a later reader cannot "
            f"re-derive the quantum wrong; it is the reason the round trip may not "
            f"simply sleep or retry"
        )


def test_b07g_a_copy_older_than_the_window_emits_no_signal(tmp_path: Path) -> None:
    """Behavior 7's root cause: beyond ``within_days`` the collector is SILENT.

    This is the state the tracked fixture is in on this box, and it is why the
    round trip subtracted an empty set from an empty set for 37 iterations.
    """
    scanned = tmp_path / "aged_copy"
    shutil.copytree(FIXTURE_WORKSPACE, scanned)
    expected = _scannable_relative_paths(FIXTURE_WORKSPACE)
    assert expected, "the tracked fixture workspace must contain scannable files"
    for path in sorted(scanned.rglob("*")):
        if path.is_file():
            _stamp(path, BEYOND_WINDOW_SECONDS)
    signals = _recent_file_signals(scanned)
    assert signals == [], (
        "a workspace whose files are all older than the 14-day window must emit "
        f"ZERO `recent_file` signals -- that silence is what made the --baseline "
        f"round trip vacuous -- got {[s.summary for s in signals]}"
    )


def test_b07h_the_same_copy_stamped_to_now_emits_one_signal_per_file(
    tmp_path: Path,
) -> None:
    """Behavior 7: stamping the copy to age 0 makes the collector fire on every file.

    Same tree as ``test_b07g``, opposite outcome, decided ONLY by ``os.utime`` --
    which is exactly the property the repaired round-trip fixture relies on.
    """
    scanned = tmp_path / "fresh_copy"
    shutil.copytree(FIXTURE_WORKSPACE, scanned)
    expected = _scannable_relative_paths(FIXTURE_WORKSPACE)
    for path in sorted(scanned.rglob("*")):
        if path.is_file():
            _stamp(path, 0.0)
    signals = _recent_file_signals(scanned)
    assert len(signals) == len(expected), (
        f"a workspace stamped to age 0 must emit one `recent_file` signal per "
        f"scannable file ({len(expected)}: {sorted(expected)}), got "
        f"{len(signals)}: {[s.summary for s in signals]}"
    )
    weights = sorted({signal.weight for signal in signals})
    assert weights == [1.0], (
        f"every signal on a just-stamped tree must weigh exactly 1.0, got {weights}"
    )


# ======================================================================================
# Behavior 8 -- ``weight`` really is inside the compared identity
# ======================================================================================


def test_b08a_weight_is_one_of_the_six_compared_identity_keys() -> None:
    """Behavior 8: ``weight`` is a member of ``cli._SIGNAL_IDENTITY_KEYS``."""
    keys = cli._SIGNAL_IDENTITY_KEYS
    assert "weight" in keys, (
        "a --baseline subtraction compares `weight`, so a clock-derived weight is "
        f"part of a signal's identity; identity keys are {keys!r}"
    )
    assert set(keys) == {"source", "kind", "summary", "detail", "path", "weight"}, (
        f"the published identity is the six wire keys, got {sorted(keys)}"
    )


def test_b08b_signal_identity_differs_when_only_the_weight_differs(
    signal_pair: tuple[ContextSignal, ContextSignal],
) -> None:
    """Behavior 8: one 1e-4 weight step is enough to change a signal's identity."""
    plateau, stepped = signal_pair
    assert cli._signal_identity(plateau) != cli._signal_identity(stepped), (
        "two signals identical except for a single 1e-4 weight step must get "
        "DIFFERENT identities -- that is the mechanism by which a produce/consume "
        "gap of 121 seconds turns every recent file into residual; got "
        f"{cli._signal_identity(plateau)!r} for both"
    )


def test_b08c_identical_signals_share_one_identity(
    signal_pair: tuple[ContextSignal, ContextSignal],
) -> None:
    """Behavior 8, POSITIVE CONTROL: the helper is not merely always-different.

    Without this, ``test_b08b`` would pass against an identity function that
    returned a fresh object every call.
    """
    plateau, _ = signal_pair
    twin = plateau.model_copy()
    assert cli._signal_identity(plateau) == cli._signal_identity(twin), (
        "two equal signals must share one identity, otherwise a --baseline "
        "subtraction could never cancel anything"
    )


def test_b08d_two_captures_that_straddle_a_quantum_disagree(tmp_path: Path) -> None:
    """Behavior 8 x behavior 7: the failure the repaired fixture avoids, reproduced.

    Two collections over the SAME unchanged file, taken at ages one quantum apart,
    produce disjoint identity sets -- so a ``--baseline`` subtraction reports the
    file as new. Taken inside the plateau instead, the sets cancel exactly.
    """
    target = tmp_path / "unchanged.py"
    target.write_text("x = 1\n", encoding="utf-8")

    _stamp(target, 0.0)
    produce = {cli._signal_identity(s) for s in _recent_file_signals(tmp_path)}
    _stamp(target, 0.0)
    consume_plateau = {cli._signal_identity(s) for s in _recent_file_signals(tmp_path)}
    _stamp(target, QUANTUM_SECONDS + 60.0)
    consume_stale = {cli._signal_identity(s) for s in _recent_file_signals(tmp_path)}

    assert produce, "the produce capture must not be empty"
    assert consume_plateau - produce == set(), (
        "two captures taken inside the sub-60s plateau must cancel exactly, "
        f"residual was {consume_plateau - produce!r}"
    )
    assert consume_stale - produce == consume_stale, (
        "a capture one quantum older must share NO identity with the produce "
        "half -- every recent file becomes residual at once, which is the "
        f"all-five-together failure iteration 278 hit; residual was "
        f"{consume_stale - produce!r}"
    )
