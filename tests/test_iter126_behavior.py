"""Black-box behavior tests for factory iteration 126 --- ``pla runs --prune``.

Feature under test: a ``--prune`` flag on the already-shipped ``pla runs`` verb
that reports which ``run-*`` state-dir children WOULD be removed (dry run, the
DEFAULT) and deletes exactly that set only when ``--yes`` is also given. The
selection reuses the listing's existing ``--status`` filter, so prune can never
drift from what ``runs`` shows, and the delete is contained to DIRECT ``run-``
prefixed child DIRECTORIES of the state dir, refusing symlinks rather than
following them.

ISOLATION CONTRACT (honored): every assertion is written strictly against this
iteration's spec (``pm.md`` "Expected Behaviors" 1-11) and the published
``README.md``, and drives ONLY documented public surfaces --- the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (its stdout / stderr / exit code / the
on-disk tree it leaves behind), ``--help``, and the public
``proactive_loop.loop.Checkpoint`` + ``proactive_loop.models`` seam the in-tree
iter-04/69/71/98 suites already use to persist synthetic run dirs offline. **No
file under ``src/`` was read by the author, no engineer or reviewer notes were
read, and no ``git diff`` was consulted.** Expected values are DERIVED from what
each test itself plants on disk (and, for behavior 5, from the listing's own
``--json`` output), never hard-coded against an implementation quirk.

Fully offline and deterministic: zero network, zero API keys, no subprocess, no
sleeps, no LLM client. Every state dir is a fresh ``tmp_path`` (never the repo's
``.pla_runs/``), so no test in this file can delete real repo state --- the
mandatory posture for the product's first destructive code path.

AMBIGUITY NOTES (PM feedback):

* Behavior 6 says an empty selection prints "exactly ``no runs to prune``" in
  "BOTH modes", while behavior 8 says ``--prune --json`` prints "exactly one JSON
  object and no prose". Read literally the two clash for ``--prune --json`` over
  an empty selection. The reading tested here is that behavior 6's "both modes"
  means the two PRUNE modes (dry run vs. ``--yes``), because behavior 8 is
  unconditional about JSON output being machine-parseable -- a JSON consumer that
  had to special-case a prose line for the empty case would be broken by design.
  So: human mode -> the bare prose line; ``--json`` -> one object with empty
  ``selected``. Worth pinning explicitly in a future spec.
* Behavior 3 fixes the first line's wording but not whether stdout ends with a
  trailing newline; the tests compare ``splitlines()`` and separately require the
  stream to end with a newline, which is the conventional shape for this CLI.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.loop import Checkpoint
from proactive_loop.models import CandidateGoal, LoopStep, RunState, RunStatus, StepKind

_CHECKPOINT_NAME = "checkpoint.json"
_EMPTY_LINE = "no runs to prune"
_DRY_HEAD = "would prune {n} run dir(s) (dry run -- re-run with --yes to delete):"
_DID_HEAD = "pruned {n} run dir(s):"
# The exact documented key set of the --prune --json object (behavior 8).
_JSON_KEYS = {"dry_run", "status", "selected", "refused", "deleted"}
# Derived from the live enum, so the parity sweep cannot drift from the CLI's
# own --status choices (iter-98 convention).
_STATUSES = [s.value for s in RunStatus]


# ---------------------------------------------------------------------------
# Helpers --- black-box: plant a tree, drive main(), read back stdout / stderr /
# exit code / the surviving tree.
# ---------------------------------------------------------------------------


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Drive ``main(argv)``; return ``(exit_code, stdout, stderr)``.

    Normal path: ``main`` returns an int. argparse paths raise ``SystemExit``
    (``--help`` -> 0, a usage error -> 2); both are normalized to a code so the
    exit contract is observable (iter-98 convention).
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


def _goal(title: str) -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="capture next steps",
        suggested_first_steps=["draft learning_plan.md"],
    )


def _persist_run(
    run_dir: Path,
    *,
    status: RunStatus = RunStatus.DONE,
    title: str = "Inspect the retriever pipeline",
    extra_files: bool = False,
) -> Path:
    """Persist a real checkpointed run under ``run_dir`` via the public
    ``Checkpoint`` seam (the offline setup path iter-04/69/71/98 use).

    ``extra_files=True`` additionally plants ``meta.json`` and a NESTED
    ``artifacts/sub/file.txt`` so behavior 4's "gone entirely, recursively"
    claim has something non-trivial to remove.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(
        goal=_goal(title),
        status=status,
        steps=[
            LoopStep(index=0, kind=StepKind.PLAN, output="thought: locate module"),
            LoopStep(index=1, kind=StepKind.CHECK, output="reason: complete", done=True),
        ],
        iterations_used=1,
        llm_calls_used=2,
        artifacts_dir=str(run_dir / "artifacts"),
    )
    Checkpoint(run_dir / _CHECKPOINT_NAME).save(state)
    if extra_files:
        (run_dir / "meta.json").write_text(json.dumps({"note": "planted"}))
        nested = run_dir / "artifacts" / "sub"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "file.txt").write_text("payload")
    return run_dir


def _snapshot(root: Path) -> set[str]:
    """Every path under ``root`` (relative, POSIX), so a containment assertion
    can compare WHOLE TREES rather than a handful of top-level ``exists()``
    calls (which would pass even if a nested file had been removed)."""
    if not root.exists():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def _prune_names(stdout: str) -> list[str]:
    """The dir names listed by a human-mode prune report (every line after the
    header, two-space indented)."""
    lines = stdout.splitlines()
    return [ln[2:] for ln in lines[1:]]


def _json_run_ids(state_dir: Path, status: str | None) -> list[str]:
    """The ``run_id`` values the LISTING reports --- the parity oracle for
    behavior 5. Uses only the documented ``runs --json`` array surface."""
    argv = ["runs", "--state-dir", str(state_dir), "--json"]
    if status is not None:
        argv += ["--status", status]
    code, out, err = _run(argv)
    assert code == 0, f"runs --json must exit 0; got {code}; stderr:\n{err}"
    rows = json.loads(out)
    assert isinstance(rows, list), f"runs --json must emit a JSON array; got {type(rows)}"
    return [row["run_id"] for row in rows]


def _prune_json(argv_tail: list[str]) -> dict:
    """``runs --prune --json ...`` -> the single parsed object, asserting the
    ENTIRE stdout parses (behavior 8's "no prose")."""
    code, out, err = _run(["runs", *argv_tail, "--prune", "--json"])
    assert code == 0, f"--prune --json must exit 0; got {code}; stderr:\n{err}"
    obj = json.loads(out)
    assert isinstance(obj, dict), f"--prune --json must emit ONE object; got {type(obj)}"
    return obj


def _mixed_state_dir(tmp_path: Path) -> Path:
    """A state dir holding one run per live ``RunStatus`` plus a degraded
    (no-checkpoint) run dir --- the parity fixture for behavior 5."""
    sd = tmp_path / "state"
    for status in RunStatus:
        _persist_run(sd / f"run-{status.value}", status=status)
    (sd / "run-degraded").mkdir(parents=True, exist_ok=True)  # no checkpoint.json
    return sd


# ===========================================================================
# Behavior 1 --- --prune is accepted on `runs` and on no other verb
# ===========================================================================


def test_eb1_prune_help_on_runs_exits_zero_and_documents_the_flag():
    code, out, err = _run(["runs", "--prune", "--help"])
    assert code == 0, f"runs --prune --help must exit 0; got {code}; stderr:\n{err}"
    assert "--prune" in out, f"runs --help must document --prune; got:\n{out}"
    assert "--yes" in out, f"runs --help must document --yes; got:\n{out}"


# Each verb is given its own REQUIRED args, so the only thing argparse can
# complain about is --prune itself (a bare `pla scan --prune` exits 2 for the
# missing --workspace whether or not --prune is accepted --- a fail-open test).
@pytest.mark.parametrize(
    "verb, required",
    [
        ("scan", ["--workspace", "{tmp}"]),
        ("dispatch", ["--slate", "{tmp}/slate.json", "--goal-id", "g1"]),
        ("trace", ["--run-dir", "{tmp}/run-a"]),
    ],
)
def test_eb1_prune_is_a_usage_error_on_other_verbs(tmp_path, verb, required):
    argv = [verb, *[a.format(tmp=tmp_path) for a in required], "--prune"]

    code, out, err = _run(argv)

    assert code == 2, f"{verb} --prune must be an argparse usage error (exit 2); got {code}"
    assert "unrecognized arguments" in err, (
        f"{verb} --prune must be reported as an unrecognized argument; stderr:\n{err}"
    )
    assert "--prune" in err, f"the usage error must name --prune; stderr:\n{err}"


def test_eb1_yes_is_not_leaked_onto_a_read_only_verb(tmp_path):
    """--yes is the confirmation for --prune and for dispatch; it must not have
    appeared on an unrelated read-only verb."""
    code, out, err = _run(["scan", "--workspace", str(tmp_path), "--yes"])

    assert code == 2, f"scan --yes must stay a usage error; got {code}; stderr:\n{err}"
    assert "unrecognized arguments" in err, f"stderr:\n{err}"


# ===========================================================================
# Behavior 2 --- dry run is the DEFAULT: --prune without --yes deletes nothing
# ===========================================================================


def test_eb2_dry_run_is_the_default_and_deletes_nothing(tmp_path):
    sd = tmp_path / "state"
    for name in ("run-a", "run-b", "run-c"):
        _persist_run(sd / name, extra_files=True)
    before = _snapshot(sd)

    code, out, err = _run(["runs", "--state-dir", str(sd), "--prune"])

    assert code == 0, f"dry-run prune must exit 0; got {code}; stderr:\n{err}"
    assert _snapshot(sd) == before, (
        "a dry run must leave the state dir byte-for-byte intact (whole-tree "
        f"compare); stdout:\n{out}"
    )
    for name in ("run-a", "run-b", "run-c"):
        assert (sd / name / _CHECKPOINT_NAME).is_file(), f"{name}/checkpoint.json must survive"
        assert (sd / name / "artifacts" / "sub" / "file.txt").is_file(), (
            f"{name}'s nested artifact must survive a dry run"
        )


# ===========================================================================
# Behavior 3 --- exact dry-run human stdout
# ===========================================================================


def test_eb3_dry_run_human_stdout_is_exactly_the_specified_shape(tmp_path):
    sd = tmp_path / "state"
    # Created OUT of ascending order, so the ordering assertion is real.
    for name in ("run-c", "run-a", "run-b"):
        _persist_run(sd / name)

    code, out, err = _run(["runs", "--state-dir", str(sd), "--prune"])

    assert code == 0, f"dry-run prune must exit 0; got {code}; stderr:\n{err}"
    assert out.splitlines() == [
        _DRY_HEAD.format(n=3),
        "  run-a",
        "  run-b",
        "  run-c",
    ], f"dry-run stdout must match the specified shape exactly; got:\n{out!r}"
    assert out.endswith("\n"), f"stdout must end with a newline; got {out!r}"


def test_eb3_dry_run_header_count_tracks_the_selection_size(tmp_path):
    sd = tmp_path / "state"
    _persist_run(sd / "run-only")

    _, out, _ = _run(["runs", "--state-dir", str(sd), "--prune"])

    assert out.splitlines() == [_DRY_HEAD.format(n=1), "  run-only"], (
        f"N must equal len(SELECTED); got:\n{out!r}"
    )


# ===========================================================================
# Behavior 4 --- --prune --yes removes exactly SELECTED, recursively
# ===========================================================================


def test_eb4_yes_removes_exactly_the_selected_set_recursively(tmp_path):
    sd = tmp_path / "state"
    _persist_run(sd / "run-keep", status=RunStatus.FAILED, extra_files=True)
    _persist_run(sd / "run-kill", status=RunStatus.DONE, extra_files=True)
    (sd / "notes").mkdir()  # a non-run child
    (sd / "notes" / "keep.txt").write_text("keep me")
    (sd / "slate.json").write_text("{}")  # a non-run file
    keep_before = _snapshot(sd / "run-keep")

    code, out, err = _run(
        ["runs", "--state-dir", str(sd), "--prune", "--status", "done", "--yes"]
    )

    assert code == 0, f"--prune --yes must exit 0; got {code}; stderr:\n{err}"
    assert out.splitlines() == [_DID_HEAD.format(n=1), "  run-kill"], (
        f"executed-prune stdout must mirror behavior 3's shape; got:\n{out!r}"
    )
    assert not (sd / "run-kill").exists(), "the selected run dir must be gone entirely"
    # ... and every non-selected entry of the state dir must be untouched.
    assert _snapshot(sd / "run-keep") == keep_before, "an unselected run dir must be intact"
    assert (sd / "notes" / "keep.txt").read_text() == "keep me"
    assert (sd / "slate.json").is_file(), "a non-run file must survive"


def test_eb4_yes_without_status_removes_every_run_dir(tmp_path):
    sd = tmp_path / "state"
    for name in ("run-a", "run-b", "run-c"):
        _persist_run(sd / name, extra_files=True)
    (sd / "slate.json").write_text("{}")

    code, out, err = _run(["runs", "--state-dir", str(sd), "--prune", "--yes"])

    assert code == 0, f"--prune --yes must exit 0; got {code}; stderr:\n{err}"
    assert out.splitlines() == [_DID_HEAD.format(n=3), "  run-a", "  run-b", "  run-c"]
    assert _snapshot(sd) == {"slate.json"}, (
        f"only the non-run entry may remain; tree is {sorted(_snapshot(sd))}"
    )


# ===========================================================================
# Behavior 5 --- selection parity with the listing
# ===========================================================================


@pytest.mark.parametrize("status", _STATUSES)
def test_eb5_selection_matches_the_listing_for_every_status(tmp_path, status):
    sd = _mixed_state_dir(tmp_path)

    _, out, _ = _run(["runs", "--state-dir", str(sd), "--prune", "--status", status])

    listed = _json_run_ids(sd, status)
    if not listed:
        assert out.splitlines() == [_EMPTY_LINE], (
            f"an empty selection must print the empty line; got:\n{out!r}"
        )
    else:
        assert _prune_names(out) == sorted(listed), (
            f"--prune --status {status} must select exactly what the listing shows "
            f"({sorted(listed)}); got {_prune_names(out)}"
        )


def test_eb5_unfiltered_selection_matches_the_unfiltered_listing(tmp_path):
    sd = _mixed_state_dir(tmp_path)

    _, out, _ = _run(["runs", "--state-dir", str(sd), "--prune"])

    listed = _json_run_ids(sd, None)
    assert _prune_names(out) == sorted(listed), (
        f"unfiltered prune must select every listed run ({sorted(listed)}); "
        f"got {_prune_names(out)}"
    )
    assert "run-degraded" in _prune_names(out), (
        "the degraded (no-checkpoint) run is listed unfiltered, so it must be "
        "selected unfiltered too --- inherited listing behavior"
    )


def test_eb5_degraded_run_is_excluded_by_every_status_filter(tmp_path):
    sd = _mixed_state_dir(tmp_path)
    for status in _STATUSES:
        _, out, _ = _run(["runs", "--state-dir", str(sd), "--prune", "--status", status])
        assert "run-degraded" not in _prune_names(out), (
            f"a (no checkpoint) run matches no RunStatus, so --status {status} must "
            f"exclude it; got:\n{out!r}"
        )


# ===========================================================================
# Behavior 6 --- empty selection prints exactly `no runs to prune`, exits 0
# ===========================================================================


@pytest.mark.parametrize("extra", [[], ["--yes"]])
def test_eb6_empty_no_run_dirs(tmp_path, extra):
    sd = tmp_path / "state"
    sd.mkdir()
    (sd / "notes").mkdir()
    (sd / "slate.json").write_text("{}")
    before = _snapshot(sd)

    code, out, err = _run(["runs", "--state-dir", str(sd), "--prune", *extra])

    assert code == 0, f"an empty prune must exit 0; got {code}; stderr:\n{err}"
    assert out.splitlines() == [_EMPTY_LINE], f"expected the empty line; got:\n{out!r}"
    assert _snapshot(sd) == before, "an empty prune must delete nothing"


@pytest.mark.parametrize("extra", [[], ["--yes"]])
def test_eb6_empty_state_dir_missing(tmp_path, extra):
    missing = tmp_path / "nope"

    code, out, err = _run(["runs", "--state-dir", str(missing), "--prune", *extra])

    assert code == 0, f"a missing state dir must exit 0; got {code}; stderr:\n{err}"
    assert out.splitlines() == [_EMPTY_LINE], f"expected the empty line; got:\n{out!r}"
    assert not missing.exists(), "prune must not CREATE the state dir"


@pytest.mark.parametrize("extra", [[], ["--yes"]])
def test_eb6_empty_status_matches_nothing(tmp_path, extra):
    sd = tmp_path / "state"
    _persist_run(sd / "run-a", status=RunStatus.DONE, extra_files=True)
    before = _snapshot(sd)
    unmatched = next(s for s in _STATUSES if s != RunStatus.DONE.value)

    code, out, err = _run(
        ["runs", "--state-dir", str(sd), "--prune", "--status", unmatched, *extra]
    )

    assert code == 0, f"a no-match --status prune must exit 0; got {code}; stderr:\n{err}"
    assert out.splitlines() == [_EMPTY_LINE], f"expected the empty line; got:\n{out!r}"
    assert _snapshot(sd) == before, "a no-match prune must delete nothing"


# ===========================================================================
# Behavior 7 --- containment (the load-bearing safety behavior)
# ===========================================================================


def _containment_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A state dir holding one genuinely prunable run plus every shape that must
    be refused, and an OUTSIDE dir that a ``run-*`` symlink points at."""
    sd = tmp_path / "state"
    _persist_run(sd / "run-kill", extra_files=True)
    (sd / "notes").mkdir()  # child dir, not run-prefixed
    (sd / "notes" / "keep.txt").write_text("keep")
    (sd / "run-file.txt").write_text("a regular FILE named run-*")
    nested = sd / "other" / "run-x"  # a run-* one level deeper
    nested.mkdir(parents=True)
    (nested / "deep.txt").write_text("deep")
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "do_not_delete.txt").write_text("precious")
    (sd / "run-link").symlink_to(outside, target_is_directory=True)
    return sd, outside


def test_eb7_containment_yes_never_escapes_the_direct_run_children(tmp_path):
    sd, outside = _containment_tree(tmp_path)

    code, out, err = _run(["runs", "--state-dir", str(sd), "--prune", "--yes"])

    assert code == 0, f"--prune --yes must exit 0; got {code}; stderr:\n{err}"
    # The one legitimate run dir IS removed (so the test proves containment, not inertia).
    assert not (sd / "run-kill").exists(), "the real run dir must be pruned"
    # Nothing else is.
    assert (sd / "notes" / "keep.txt").read_text() == "keep", "a non-run child dir must survive"
    assert (sd / "run-file.txt").is_file(), "a regular FILE named run-* must survive"
    assert (sd / "other" / "run-x" / "deep.txt").read_text() == "deep", (
        "a run-* nested one level deeper must survive"
    )
    assert (sd / "run-link").is_symlink(), "the run-* symlink itself must survive"
    assert (outside / "do_not_delete.txt").read_text() == "precious", (
        "the symlink's TARGET tree must survive --- the delete must never escape"
    )


def test_eb7_symlink_is_excluded_from_selection_and_refused_on_stderr(tmp_path):
    sd, _ = _containment_tree(tmp_path)

    code, out, err = _run(["runs", "--state-dir", str(sd), "--prune"])

    assert code == 0, f"a refusal must not change the exit code; got {code}"
    assert "run-link" not in _prune_names(out), (
        f"a run-* symlink must be excluded from SELECTED; got:\n{out!r}"
    )
    assert _prune_names(out) == ["run-kill"], f"only the real run dir is selected; got:\n{out!r}"
    assert err.splitlines() == ["refused: run-link is a symlink, not a run dir"], (
        f"the refusal must be exactly one stderr line; got:\n{err!r}"
    )


def test_eb7_nested_run_dir_survives_even_in_dry_run_report(tmp_path):
    sd, _ = _containment_tree(tmp_path)

    _, out, _ = _run(["runs", "--state-dir", str(sd), "--prune"])

    assert "run-x" not in out, (
        f"a run-* nested below the state dir must never be reported; got:\n{out!r}"
    )
    assert "run-file.txt" not in out, f"a regular file named run-* must not be reported;\n{out!r}"
    assert "notes" not in out, f"a non-run child dir must not be reported;\n{out!r}"


def test_eb7_symlinked_state_dir_still_prunes_only_its_run_children(tmp_path):
    """A SYMLINKED ``--state-dir`` is a legitimate setup (a state dir parked on
    another volume); the containment rule is about the state dir's CHILDREN, so
    this must still work and still not escape."""
    real = tmp_path / "real_state"
    _persist_run(real / "run-a", extra_files=True)
    (real / "keep.txt").write_text("keep")
    link = tmp_path / "link_state"
    link.symlink_to(real, target_is_directory=True)

    code, out, err = _run(["runs", "--state-dir", str(link), "--prune", "--yes"])

    assert code == 0, f"a symlinked state dir must still exit 0; got {code}; stderr:\n{err}"
    assert not (real / "run-a").exists(), "the run dir under the symlinked state dir is pruned"
    assert (real / "keep.txt").read_text() == "keep", "non-run entries still survive"


# ===========================================================================
# Behavior 8 --- --prune --json emits exactly one object with five keys
# ===========================================================================


def test_eb8_json_dry_run_object_shape(tmp_path):
    sd, _ = _containment_tree(tmp_path)
    before = _snapshot(sd)

    obj = _prune_json(["--state-dir", str(sd)])

    assert set(obj) == _JSON_KEYS, f"exactly the five documented keys; got {sorted(obj)}"
    assert obj["dry_run"] is True, f"dry_run must be true without --yes; got {obj['dry_run']!r}"
    assert obj["status"] is None, f"status must be null when --status is omitted; got {obj['status']!r}"
    assert obj["selected"] == ["run-kill"], f"selected must be the sorted names; got {obj['selected']}"
    assert obj["refused"] == ["run-link"], f"refused must be the sorted names; got {obj['refused']}"
    assert obj["deleted"] == 0, f"deleted must be 0 in a dry run; got {obj['deleted']!r}"
    assert _snapshot(sd) == before, "a --json dry run must still delete nothing"


def test_eb8_json_executed_object_shape(tmp_path):
    sd = tmp_path / "state"
    for name in ("run-b", "run-a"):
        _persist_run(sd / name, extra_files=True)

    obj = _prune_json(["--state-dir", str(sd), "--yes"])

    assert set(obj) == _JSON_KEYS, f"exactly the five documented keys; got {sorted(obj)}"
    assert obj["dry_run"] is False, f"dry_run must be false with --yes; got {obj['dry_run']!r}"
    assert obj["selected"] == ["run-a", "run-b"], f"selected must be sorted; got {obj['selected']}"
    assert obj["refused"] == [], f"refused must be an empty list here; got {obj['refused']}"
    assert obj["deleted"] == len(obj["selected"]), (
        f"deleted must equal len(selected) after --yes; got {obj['deleted']!r}"
    )
    assert isinstance(obj["deleted"], int) and not isinstance(obj["deleted"], bool), (
        f"deleted must be an integer; got {type(obj['deleted'])}"
    )
    assert _snapshot(sd) == set(), f"every run dir must be gone; tree is {sorted(_snapshot(sd))}"


def test_eb8_json_echoes_the_status_string(tmp_path):
    sd = _mixed_state_dir(tmp_path)

    obj = _prune_json(["--state-dir", str(sd), "--status", "done"])

    assert obj["status"] == "done", f"status must echo the --status string; got {obj['status']!r}"
    assert obj["selected"] == sorted(_json_run_ids(sd, "done")), (
        "the JSON selection must equal the listing's selection"
    )


def test_eb8_json_empty_selection_is_still_one_object(tmp_path):
    """AMBIGUITY (see module docstring): behavior 8 is unconditional about JSON
    being machine-parseable, so an empty selection must NOT degrade to prose."""
    sd = tmp_path / "state"
    sd.mkdir()

    obj = _prune_json(["--state-dir", str(sd)])

    assert set(obj) == _JSON_KEYS, f"exactly the five documented keys; got {sorted(obj)}"
    assert obj["selected"] == [] and obj["refused"] == [] and obj["deleted"] == 0


# ===========================================================================
# Behavior 9 --- no-`--prune` regression: byte-identical, never destructive
# ===========================================================================


@pytest.mark.parametrize("tail", [[], ["--json"], ["--status", "done"]])
def test_eb9_yes_without_prune_is_byte_identical_to_the_plain_listing(tmp_path, tail):
    sd = _mixed_state_dir(tmp_path)
    before = _snapshot(sd)

    base_code, base_out, base_err = _run(["runs", "--state-dir", str(sd), *tail])
    yes_code, yes_out, yes_err = _run(["runs", "--state-dir", str(sd), *tail, "--yes"])

    assert (yes_code, yes_out, yes_err) == (base_code, base_out, base_err), (
        "`runs --yes` without --prune must be inert and byte-identical to `runs`\n"
        f"base rc={base_code} stdout={base_out!r} stderr={base_err!r}\n"
        f"--yes rc={yes_code} stdout={yes_out!r} stderr={yes_err!r}"
    )
    assert _snapshot(sd) == before, "no invocation omitting --prune may delete anything"


def test_eb9_no_listing_invocation_removes_a_run_dir(tmp_path):
    sd = _mixed_state_dir(tmp_path)
    before = _snapshot(sd)

    for tail in ([], ["--json"], ["--status", "done"], ["--status", "failed", "--json"], ["--yes"]):
        code, _, err = _run(["runs", "--state-dir", str(sd), *tail])
        assert code == 0, f"runs {tail} must exit 0; got {code}; stderr:\n{err}"

    assert _snapshot(sd) == before, "the listing must remain strictly read-only"


# ===========================================================================
# Behavior 10 --- an invalid --status stays a usage error, even with --prune
# ===========================================================================


@pytest.mark.parametrize("tail", [["--prune"], ["--prune", "--yes"], ["--prune", "--json"]])
def test_eb10_invalid_status_is_still_exit_two(tmp_path, tail):
    sd = tmp_path / "state"
    _persist_run(sd / "run-a", extra_files=True)
    before = _snapshot(sd)

    code, out, err = _run(["runs", "--state-dir", str(sd), "--status", "bogus", *tail])

    assert code == 2, f"an invalid --status choice must exit 2 with {tail}; got {code}"
    assert _snapshot(sd) == before, "a usage error must happen before anything is deleted"


# ===========================================================================
# Behavior 11 --- the README `## CLI` runs row documents --prune
# ===========================================================================


_README = Path(__file__).resolve().parents[1] / "README.md"


def _cli_section(text: str) -> str:
    start = text.index("\n## CLI")
    rest = text.index("\n## ", start + 1)
    return text[start:rest]


def test_eb11_readme_cli_runs_row_documents_prune():
    text = _README.read_text(encoding="utf-8")
    section = _cli_section(text)
    rows = [ln for ln in section.splitlines() if ln.startswith("| `runs`")]
    assert len(rows) == 1, f"expected exactly one `runs` row in ## CLI; got {rows}"
    row = rows[0]
    assert "--prune" in row, f"the runs row must document --prune; got:\n{row}"
    assert "--yes" in row, f"the runs row must document the --yes confirmation; got:\n{row}"
    assert "dry run" in row.lower(), (
        f"the runs row must state that dry run is the default; got:\n{row}"
    )
