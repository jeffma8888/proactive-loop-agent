"""Black-box verification of factory iteration 257: ``pla run`` refuses an aliased
``--baseline`` / ``--snapshot`` pair as a parse-time usage error.

MODULE NAME, derived from the repo and never from the state-dir counter. The two
counters differ here (state dir ``iter-257``), so the name was derived: the
highest tracked ``tests/test_iterNN_behavior.py`` was ``234``, +1 = ``235``, and
``git cat-file -e HEAD:tests/test_iter235_behavior.py`` FAILED before a byte was
written -- the path is provably free in HEAD.

ISOLATION CONTRACT, honored. Nothing under ``src/`` was read; no engineer,
reviewer or fix note was opened; no ``git diff`` was run. Every assertion drives
``proactive_loop.cli.main`` with an argv list and reads back only the exit code,
captured stdout/stderr, files the CLI itself wrote, the public
``proactive_loop.cli.build_parser()`` registry, and the tracked ``SPEC.md`` prose
that behavior 7 mandates.

WHY THE GUARD EXISTS (the defect it closes). ``--snapshot`` writes the SURVIVING
signals and ``--baseline`` suppresses signals a saved document already recorded.
Point both at one path and the document is rewritten with its own complement, so
identical commands ALTERNATE between "suppressed all" and "suppressed none" at
exit 0 -- silent data loss with no non-zero code to branch on.

OFFLINE AND DETERMINISTIC: provider ``scripted`` with the tracked example script,
no network, no API key, no sleeps. Every workspace-adjacent artifact (state dirs,
baselines, snapshots) lives under ``tmp_path``; the only checkout paths touched
are the two TRACKED example inputs and ``SPEC.md`` (read-only), so a throwaway
fresh clone verifies identically -- nothing here reads gitignored local state.

Coverage, numbered to match this iteration's spec Expected Behaviors:

1. Byte-identical paths are refused: exit 2, EMPTY stdout, exactly one stderr
   error line naming ``--baseline``, ``--snapshot`` and the typed path, no
   traceback.
2. The refusal has zero side effects: the baseline's bytes are unchanged, the
   ``--state-dir`` is not even created (so no ``run-*`` dir and no slate), with a
   NON-VACUITY control proving a permitted run does create both.
3. Aliases that are not byte-identical strings are refused too -- ``./b.json``,
   ``sub/../b.json`` and a symlink -- and the error names BOTH typed spellings.
4. Distinct paths are untouched: exit 0 and a real snapshot document is written.
5. Verbs owning only ONE of the two flags are unaffected (``signals``,
   ``scan``), with the parser proving the one-flag premise.
6. The guarded verb set is DERIVED from the live parser, asserted non-empty, and
   every member refuses.
7. ``SPEC.md``'s ``pla run`` bullet block carries one sentence naming
   ``--baseline``, ``--snapshot`` and exit 2 together.

AMBIGUITY NOTES (PM feedback, deliberate deviations from a literal reading):

* Behavior 6 says the derived set "equals exactly ``{"run"}`` today". A hard
  equality pin would RED the spec's own named next increment: ``scan`` already
  owns ``--snapshot``, so giving it ``--baseline`` (Out of Scope item #1, "the
  next candidate") legitimately grows this set to ``{"run", "scan"}``. Following
  this repo's FUTURE-BRITTLE COUNTS convention, this module asserts a FLOOR
  (non-empty, ``run`` present) and drives EVERY member, and records the
  today-measured value in the failure message instead of pinning it.
* Behavior 5 says each one-flag verb stays "byte-identical to HEAD behavior".
  A true byte-diff against HEAD is not reachable from an in-process black-box
  test (it would need a second checkout), so the tested reading is: exit 0, the
  verb's own observable output still present, and the parser confirming the verb
  owns exactly one of the pair.
* Behavior 7 says "exit 2". The shipped prose may spell it ``exit 2``,
  ``exits 2`` or ``exit code 2``; the assertion accepts all three rather than
  pinning one wording, since the contract is the STATUS, not the phrasing.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser, main

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"
WORKSPACE = REPO / "examples" / "fixture_workspace"
SPEC_PATH = REPO / "SPEC.md"

#: The pair whose aliasing is refused.
BASELINE_FLAG = "--baseline"
SNAPSHOT_FLAG = "--snapshot"

#: Measured on the shipped tree at authoring time. Used only in failure messages
#: and as a membership floor -- never as an equality pin (see ambiguity note 1).
GUARDED_VERBS_TODAY = frozenset({"run"})

_EXIT_TWO = re.compile(r"exit(?:s|ed)?(?:\s+(?:code|status))?\s+2\b", re.IGNORECASE)


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """argv in -> (exit code, stdout, stderr).

    A guard may either RETURN 2 or raise ``SystemExit(2)`` (argparse does the
    latter); the spec authorizes both, so both are tolerated.
    """
    try:
        rc = main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _run_argv(state_dir: Path, *extra: str, dry_run: bool = True) -> list[str]:
    argv = ["run"]
    if dry_run:
        argv.append("--dry-run")
    argv += [
        "--workspace",
        str(WORKSPACE),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(state_dir),
    ]
    return argv + list(extra)


def _verb_argv(verb: str, state_dir: Path, *extra: str) -> list[str]:
    argv = [
        verb,
        "--workspace",
        str(WORKSPACE),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
    ]
    if verb != "signals":
        argv += ["--state-dir", str(state_dir)]
    return argv + list(extra)


def _flags_by_verb(parser: argparse.ArgumentParser) -> dict[str, frozenset[str]]:
    """Map every subparser name to the set of ``--`` options it accepts.

    Same walking convention as ``tests/test_iter234_behavior.py``: the top-level
    parser's ``_actions``, recursing through each
    ``argparse._SubParsersAction.choices``.
    """
    owned: dict[str, set[str]] = {}
    stack: list[tuple[argparse.ArgumentParser, str | None]] = [(parser, None)]
    while stack:
        current, verb = stack.pop()
        for action in current._actions:
            if verb is not None:
                for option in action.option_strings:
                    if option.startswith("--"):
                        owned.setdefault(verb, set()).add(option)
            if isinstance(action, argparse._SubParsersAction):
                for name, subparser in action.choices.items():
                    owned.setdefault(name, set())
                    stack.append((subparser, name))
    return {verb: frozenset(flags) for verb, flags in owned.items()}


def _guarded_verbs() -> frozenset[str]:
    """Verbs whose live option set contains BOTH flags -- derived, never literal."""
    by_verb = _flags_by_verb(build_parser())
    return frozenset(
        verb
        for verb, flags in by_verb.items()
        if BASELINE_FLAG in flags and SNAPSHOT_FLAG in flags
    )


def _error_lines(stderr: str) -> list[str]:
    """The stderr lines that carry the failure, excluding argparse's usage block."""
    return [line for line in stderr.splitlines() if "error:" in line]


def _sole_error_line(stderr: str) -> str:
    lines = _error_lines(stderr)
    assert len(lines) == 1, f"expected exactly ONE error line, got {len(lines)}: {lines!r}"
    assert "Traceback" not in stderr, f"the refusal must not print a traceback:\n{stderr}"
    return lines[0]


def _seed_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str = "b.json") -> Path:
    """Produce a REAL signals document with the shipped ``--snapshot`` writer.

    Handwriting one would test a fixture rather than the product, and an empty
    ``signals`` array would make every guard assertion below vacuous -- so the
    non-emptiness is asserted here.
    """
    document = tmp_path / name
    rc, _, stderr = _run(_run_argv(tmp_path / "seed-state", SNAPSHOT_FLAG, str(document)), capsys)
    assert rc == 0, f"seeding a baseline must succeed; got {rc}\n{stderr}"
    assert document.is_file(), "the shipped --snapshot writer produced no document"
    payload = json.loads(document.read_text(encoding="utf-8"))
    assert payload["signals"], "the seeded baseline carries no signals; guard tests would be vacuous"
    return document


# --------------------------------------------------------------------------
# Behavior 1 -- byte-identical paths are refused
# --------------------------------------------------------------------------


def test_b1_byte_identical_pair_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline = _seed_baseline(tmp_path, capsys)
    typed = str(baseline)
    rc, stdout, stderr = _run(
        _run_argv(tmp_path / "guarded", BASELINE_FLAG, typed, SNAPSHOT_FLAG, typed), capsys
    )
    assert rc == 2, f"an aliased pair must be a usage error (exit 2); got {rc}\n{stderr}"
    assert stdout == "", f"a refused invocation must print NOTHING on stdout; got {stdout!r}"
    line = _sole_error_line(stderr)
    for token in (BASELINE_FLAG, SNAPSHOT_FLAG, typed):
        assert token in line, f"the error line must name {token!r}; got {line!r}"


# --------------------------------------------------------------------------
# Behavior 2 -- the refusal has zero side effects
# --------------------------------------------------------------------------


def test_b2_refusal_leaves_the_baseline_bytes_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _seed_baseline(tmp_path, capsys)
    before = baseline.read_bytes()
    rc, _, _ = _run(
        _run_argv(
            tmp_path / "guarded", BASELINE_FLAG, str(baseline), SNAPSHOT_FLAG, str(baseline)
        ),
        capsys,
    )
    assert rc == 2
    assert baseline.read_bytes() == before, "the refused invocation rewrote the baseline document"


def test_b2_refusal_writes_no_state_no_run_dir_and_no_slate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _seed_baseline(tmp_path, capsys)
    state = tmp_path / "guarded-state"
    rc, _, _ = _run(
        _run_argv(state, BASELINE_FLAG, str(baseline), SNAPSHOT_FLAG, str(baseline)), capsys
    )
    assert rc == 2
    assert not state.exists(), f"the refusal created a state dir: {sorted(p.name for p in state.iterdir())}"
    assert list(state.glob("run-*")) == []
    assert list(state.glob("**/slate.json")) == []


def test_b2_control_a_permitted_run_does_create_a_run_dir_and_slate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """NON-VACUITY for the test above: the artifacts it asserts absent are real.

    Without this control, "no ``run-*`` dir" would hold for a CLI that never
    creates one at all, and behavior 2 would be a statement about nothing.
    """
    state = tmp_path / "live-state"
    rc, _, stderr = _run(_run_argv(state, dry_run=False), capsys)
    assert rc == 0, f"the control run must succeed offline; got {rc}\n{stderr}"
    assert state.is_dir()
    assert list(state.glob("run-*")), "the control produced no run-* dir; behavior 2 would be vacuous"
    assert (state / "slate.json").is_file(), "the control wrote no slate; behavior 2 would be vacuous"


# --------------------------------------------------------------------------
# Behavior 3 -- aliases that are not byte-identical strings
# --------------------------------------------------------------------------


@pytest.mark.parametrize("snapshot_spelling", ["./b.json", "sub/../b.json"])
def test_b3a_relative_respelling_of_the_same_file_is_refused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    snapshot_spelling: str,
) -> None:
    _seed_baseline(tmp_path, capsys)
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path)
    rc, stdout, stderr = _run(
        _run_argv(
            tmp_path / "guarded", BASELINE_FLAG, "b.json", SNAPSHOT_FLAG, snapshot_spelling
        ),
        capsys,
    )
    assert rc == 2, f"{snapshot_spelling!r} resolves to the baseline and must be refused; got {rc}\n{stderr}"
    assert stdout == ""
    line = _sole_error_line(stderr)
    for token in (BASELINE_FLAG, SNAPSHOT_FLAG, "b.json", snapshot_spelling):
        assert token in line, f"the error line must name {token!r} as typed; got {line!r}"


def test_b3b_a_symlink_to_the_baseline_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _seed_baseline(tmp_path, capsys)
    link = tmp_path / "link.json"
    link.symlink_to(baseline)
    rc, stdout, stderr = _run(
        _run_argv(tmp_path / "guarded", BASELINE_FLAG, str(baseline), SNAPSHOT_FLAG, str(link)),
        capsys,
    )
    assert rc == 2, f"a symlink alias must be refused; got {rc}\n{stderr}"
    assert stdout == ""
    line = _sole_error_line(stderr)
    for token in (BASELINE_FLAG, SNAPSHOT_FLAG, str(baseline), str(link)):
        assert token in line, f"the error line must name {token!r} as typed; got {line!r}"
    assert baseline.read_text(encoding="utf-8"), "the refused symlink invocation truncated the target"


def test_b3_the_check_is_not_a_raw_string_comparison(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pins the DISCRIMINATION: differing strings, one refused, one allowed.

    Two invocations whose ``--snapshot`` strings both DIFFER from ``--baseline``
    get opposite verdicts -- so the guard compares resolved filesystem paths and
    is neither a raw string equality (which would allow the alias) nor a blanket
    refusal of any two-flag invocation (which would break behavior 4).
    """
    baseline = _seed_baseline(tmp_path, capsys)
    (tmp_path / "sub").mkdir()
    aliased = tmp_path / "sub" / ".." / "b.json"
    distinct = tmp_path / "sub" / "other.json"
    assert str(aliased) != str(baseline) and str(distinct) != str(baseline)

    rc_aliased, _, _ = _run(
        _run_argv(tmp_path / "s1", BASELINE_FLAG, str(baseline), SNAPSHOT_FLAG, str(aliased)),
        capsys,
    )
    rc_distinct, _, err_distinct = _run(
        _run_argv(tmp_path / "s2", BASELINE_FLAG, str(baseline), SNAPSHOT_FLAG, str(distinct)),
        capsys,
    )
    assert rc_aliased == 2, "the resolved-alias spelling was accepted -- the check is string-based"
    assert rc_distinct == 0, f"a genuinely distinct path was refused; got {rc_distinct}\n{err_distinct}"


# --------------------------------------------------------------------------
# Behavior 4 -- distinct paths are untouched
# --------------------------------------------------------------------------


def test_b4_distinct_paths_still_compose_and_write_a_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _seed_baseline(tmp_path, capsys)
    snapshot = tmp_path / "s.json"
    rc, stdout, stderr = _run(
        _run_argv(tmp_path / "ok-state", BASELINE_FLAG, str(baseline), SNAPSHOT_FLAG, str(snapshot)),
        capsys,
    )
    assert rc == 0, f"the legitimate composition must still work; got {rc}\n{stderr}"
    assert stdout != "", "a permitted run must still render its slate"
    assert snapshot.is_file(), "no snapshot document was written"
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert isinstance(payload["signals"], list), "the snapshot document carries no signals array"


# --------------------------------------------------------------------------
# Behavior 5 -- verbs owning only one of the two flags are unaffected
# --------------------------------------------------------------------------


def test_b5_one_flag_verbs_own_exactly_one_of_the_pair() -> None:
    """The premise behind behavior 5, measured rather than assumed."""
    by_verb = _flags_by_verb(build_parser())
    assert SNAPSHOT_FLAG not in by_verb["signals"], "signals gained --snapshot; behavior 5 needs rewriting"
    assert BASELINE_FLAG in by_verb["signals"]
    assert BASELINE_FLAG not in by_verb["scan"], "scan gained --baseline; behavior 5 needs rewriting"
    assert SNAPSHOT_FLAG in by_verb["scan"]


def test_b5_signals_with_baseline_alone_still_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _seed_baseline(tmp_path, capsys)
    rc, stdout, stderr = _run(
        _verb_argv("signals", tmp_path / "unused", BASELINE_FLAG, str(baseline)), capsys
    )
    assert rc == 0, f"signals --baseline must be unaffected; got {rc}\n{stderr}"
    assert stdout != "", "signals printed nothing -- its own output regressed"


def test_b5_scan_with_snapshot_alone_still_exits_zero_and_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = tmp_path / "scan-snap.json"
    rc, stdout, stderr = _run(
        _verb_argv("scan", tmp_path / "scan-state", SNAPSHOT_FLAG, str(snapshot)), capsys
    )
    assert rc == 0, f"scan --snapshot must be unaffected; got {rc}\n{stderr}"
    assert stdout != "", "scan printed nothing -- its own output regressed"
    assert snapshot.is_file(), "scan --snapshot wrote no document"


# --------------------------------------------------------------------------
# Behavior 6 -- the guarded verb set is derived from the live parser
# --------------------------------------------------------------------------


def test_b6_the_guarded_set_is_derived_and_non_empty() -> None:
    guarded = _guarded_verbs()
    assert guarded, (
        "no live verb owns BOTH --baseline and --snapshot, so behaviors 1-3 are "
        f"vacuous; measured at authoring time: {sorted(GUARDED_VERBS_TODAY)}"
    )
    assert "run" in guarded, f"run must own both flags; live set is {sorted(guarded)}"


def test_b6_every_verb_owning_both_flags_refuses_an_aliased_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Drives the DERIVED set, so a future verb gaining both flags is covered
    with no edit to this module."""
    guarded = _guarded_verbs()
    assert guarded
    baseline = _seed_baseline(tmp_path, capsys)
    for verb in sorted(guarded):
        argv = [
            verb,
            "--workspace",
            str(WORKSPACE),
            "--provider",
            "scripted",
            "--scripted-responses",
            str(SCRIPT),
            "--state-dir",
            str(tmp_path / f"state-{verb}"),
            BASELINE_FLAG,
            str(baseline),
            SNAPSHOT_FLAG,
            str(baseline),
        ]
        rc, stdout, stderr = _run(argv, capsys)
        assert rc == 2, f"{verb} owns both flags but accepted an aliased pair; got {rc}\n{stderr}"
        assert stdout == "", f"{verb} printed on stdout while refusing: {stdout!r}"
        line = _sole_error_line(stderr)
        assert BASELINE_FLAG in line and SNAPSHOT_FLAG in line, f"{verb}: {line!r}"


# --------------------------------------------------------------------------
# Behavior 7 -- SPEC.md documents the refusal
# --------------------------------------------------------------------------


def _run_bullet_block() -> str:
    """Section 4.5's ``- `pla run`` bullet block, same convention as iter 234."""
    lines = SPEC_PATH.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("### 4.5")), None)
    assert start is not None, "SPEC.md has no '### 4.5' heading"
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^#{1,3} ", lines[index]):
            end = index
            break
    section = lines[start:end]
    starts = [i for i, line in enumerate(section) if line.lstrip().startswith("- `pla ")]
    for position, index in enumerate(starts):
        match = re.match(r"- `pla ([a-z][a-z-]*)", section[index].lstrip())
        assert match is not None, f"unparsable verb bullet: {section[index]!r}"
        if match.group(1) == "run":
            stop = starts[position + 1] if position + 1 < len(starts) else len(section)
            return "\n".join(section[index:stop])
    raise AssertionError("section 4.5 has no `pla run` bullet block")


def test_b7_spec_run_block_has_one_sentence_naming_both_flags_and_exit_two() -> None:
    block = " ".join(_run_bullet_block().split())
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", block) if part.strip()]
    matching = [
        sentence
        for sentence in sentences
        if BASELINE_FLAG in sentence and SNAPSHOT_FLAG in sentence and _EXIT_TWO.search(sentence)
    ]
    assert matching, (
        "no single sentence in SPEC.md's `pla run` block names --baseline, "
        f"--snapshot and exit 2 together; block was:\n{block}"
    )


def test_b7_the_documented_refusal_matches_the_live_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ties the prose to the product: the code SPEC.md publishes is the code
    the CLI returns, so this is a docs-vs-code agreement check and not a
    grep for a number."""
    block = " ".join(_run_bullet_block().split())
    assert _EXIT_TWO.search(block), "SPEC.md's run block never mentions exit 2"
    baseline = _seed_baseline(tmp_path, capsys)
    rc, _, _ = _run(
        _run_argv(tmp_path / "doc-state", BASELINE_FLAG, str(baseline), SNAPSHOT_FLAG, str(baseline)),
        capsys,
    )
    assert rc == 2, f"SPEC.md publishes exit 2 but the CLI returned {rc}"
