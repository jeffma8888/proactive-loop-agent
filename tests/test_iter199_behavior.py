"""Black-box oracle for factory iteration 196 (state dir ``iter-194``).

Feature under test: ``examples/check_run.py`` -- the committed consumer that
``make demo`` (and therefore ``make check`` and CI) grades the published
``run --json`` document with -- now READS BACK the run's own persisted
``<run_dir>/checkpoint.json`` and fails when it is missing, unreadable,
unparseable, or disagrees with the document on ``run_id`` or ``status``. Its
success line additionally reports ``run_dir=``, the value ``resume --run-dir``
and ``trace --run-dir`` accept.

Why it matters, in the spec's own words: ``README.md`` has long published that
``dispatched`` carries "``run_id``/``status`` matching that run dir's
``checkpoint.json``", while the document is built in memory from ``RunState``
and never read back -- so the two values agreed by construction and by nobody.

MODULE NAME -- DERIVED FROM THE REPO, NEVER FROM THE STATE-DIR NUMBER. This repo
names behavior modules by the FACTORY iteration number, which runs ahead of the
state-dir counter (state dir ``iter-194`` ships as ``factory iter 196``). The
highest tracked ``test_iterNN_behavior.py`` is 198, so this file is 199, and the
path was proven free two-sided before a byte was written:
``git cat-file -e HEAD:tests/test_iter199_behavior.py`` exits 128 (free) while
the same probe for 198 exits 0 (taken). Writing the state-dir number here would
overwrite a shipped oracle -- the iter-172/iter-186 destroyed-oracle failure.

ISOLATION CONTRACT (honored, no exceptions). Every assertion is derived from this
iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own ``tests/``
conventions, the ``Makefile`` gate definition the feature rides inside, the
human-readable ``README.md``, and the product's OBSERVABLE output obtained by
RUNNING it. **No file under ``src/`` was read, the ``examples/check_run.py``
SOURCE was never opened, no ``engineer.md`` / ``reviewer.md`` / ``fix_review.md``
was read, and no ``git diff`` was inspected.** Fully offline and deterministic:
the bundled scripted provider only, no network, no API key.

WHY THE CONSUMER IS A SUBPROCESS AND NOT AN IMPORT (the convention
``test_iter198_behavior`` established and this module keeps). ``examples/`` is
not a package, so importing a named function out of that script means READING it,
which the isolation contract forbids. The graded gate does not import it either
-- the ``demo`` recipe runs the script and ``make`` reads its EXIT CODE -- so
this module drives it exactly as the recipe does, through ``sys.executable``
(which IS the project venv's interpreter under ``uv run pytest``), with the
document on stdin.

EVERY FIXTURE IS OWNED, NEVER AMBIENT. ``.pla_runs/`` is gitignored
(``.gitignore``) and absent from a fresh clone, so no assertion here reads it;
each behavior copies the one real run into its OWN ``tmp_path`` and runs the
consumer with ``cwd=tmp_path``, so the document's RELATIVE ``run_dir`` resolves
inside that private tree. This also gives the run-dir-not-present path a
``tmp_path``-owned oracle of its own: ``test_iter174_behavior.py`` proves that
path only because a hardcoded ``/tmp`` path happens not to exist on the host,
which is an ambient precondition this module does not inherit.

NO NESTED BUILD TOOLS. ``tests/test_iter110_behavior.py`` forbids the suite from
shelling out to a gate step, so the one real run is driven IN-PROCESS through
``proactive_loop.cli.main([...])`` -- the idiom ~99 existing call sites use --
with the demo recipe's own argument set and its RELATIVE ``--state-dir``, which
is what makes the published ``run_dir`` relative and the join reproducible.

NO INDENTATION ASSERTIONS. CI is a 3.12 + 3.13 matrix and 3.13 strips the common
leading docstring indent at compile time, so nothing here asserts on docstring,
comment or help-text indentation.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.cli import main
from proactive_loop.models import RunStatus

REPO: Final = Path(__file__).resolve().parents[1]
README: Final = REPO / "README.md"
CONSUMER: Final = REPO / "examples" / "check_run.py"
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"

# The demo recipe's own relative state dir, which is what makes `run_dir`
# relative and therefore resolvable against an arbitrary cwd.
STATE_DIR_NAME: Final = ".pla_runs"
CHECKPOINT_NAME: Final = "checkpoint.json"
CONSUMER_STEP: Final = f"uv run python examples/check_run.py < {STATE_DIR_NAME}/run.json"

DONE: Final = RunStatus.DONE.value
NON_SUCCESS: Final = tuple(sorted(m.value for m in RunStatus if m.value != DONE))

# Spec behavior 1: the two tokens the success line must carry.
OK_PREFIX: Final = "ok: "
RUN_ID_TOKEN: Final = "run_id="
RUN_DIR_TOKEN: Final = "run_dir="
# The marker that means "the persisted copy was actually reconciled". Any other
# `checkpoint=` value is a NON-verification and must never read as a success.
VERIFIED: Final = "checkpoint=verified"

HUMAN_OWNED_MARKER: Final = "PORTFOLIO INTRO"
# A minted run id is 12 hex chars and fresh per run, so publishing a literal one
# in the README makes the sample line stale on the very next run.
HEX12: Final = re.compile(r"\b[0-9a-f]{12}\b")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _consume(payload: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the COMMITTED consumer exactly as the ``demo`` recipe does -- script,
    stdin, exit code -- but rooted at ``cwd`` so the document's relative
    ``run_dir`` resolves inside an owned tree."""
    return subprocess.run(
        [sys.executable, str(CONSUMER)],
        input=payload,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _sole_line(stream: str, label: str) -> str:
    lines = stream.splitlines()
    assert len(lines) == 1, f"{label}: expected exactly one line, got {lines!r}"
    return lines[0]


def _messages(proc: subprocess.CompletedProcess[str]) -> str:
    """Everything the consumer said, on either stream.

    The spec fixes the EXIT CODE and requires the message to NAME certain values;
    it does not fix which stream carries a failure, so a message assertion that
    pinned one stream would be testing an unspecified detail.
    """
    return proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# The single real run, shared by every behavior. Performed ONCE: the tester
# stage is measured near the 600s cap and a tester timeout reverts the
# engineer's work too.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, dict, Path]:
    """``(raw_document, parsed_document, root)`` from ONE real performance of the
    demo recipe's argument set, with the recipe's RELATIVE ``--state-dir``."""
    root = tmp_path_factory.mktemp("iter199-run")
    (root / STATE_DIR_NAME).mkdir()
    argv = [
        "run",
        "--workspace",
        str(FIXTURE),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        STATE_DIR_NAME,
        "--snapshot",
        f"{STATE_DIR_NAME}/snapshot.json",
        "--json",
    ]
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.chdir(root):
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = main(argv)
    raw = stdout.getvalue()
    assert rc == 0, (
        "the demo's own argument set must exit 0 before its document can be "
        f"graded; rc={rc}\nstdout:{raw!r}\nstderr:{stderr.getvalue()!r}"
    )
    document = json.loads(raw)
    assert isinstance(document, dict), type(document).__name__
    return raw, document, root


def _dispatched(document: dict) -> dict:
    dispatched = document.get("dispatched")
    assert isinstance(dispatched, dict), (
        f"the document must carry a dispatched run; top-level keys are {sorted(document)}"
    )
    return dispatched


def _stage(tmp_path: Path, real_run: tuple[str, dict, Path]) -> tuple[str, Path]:
    """Copy the real run directory into ``tmp_path`` at the document's OWN
    relative ``run_dir``, and return ``(payload, checkpoint_path)``.

    Every behavior gets its own copy, so one behavior's tampering can never be
    another behavior's precondition.
    """
    raw, document, root = real_run
    rel = _dispatched(document)["run_dir"]
    assert isinstance(rel, str) and rel, repr(rel)
    assert not Path(rel).is_absolute(), (
        "the demo's relative --state-dir must publish a RELATIVE run_dir, or the "
        f"cwd-rooted fixtures below prove nothing; got {rel!r}"
    )
    dst = tmp_path / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / rel, dst)
    return raw, dst / CHECKPOINT_NAME


# ---------------------------------------------------------------------------
# Behavior 1 -- a matching checkpoint is accepted, and the success line names
# BOTH identifiers
# ---------------------------------------------------------------------------


def test_b1_matching_checkpoint_is_accepted_and_names_run_id_and_run_dir(
    tmp_path: Path, real_run: tuple[str, dict, Path]
) -> None:
    """Spec behavior 1. Exit 0, exactly one stdout line starting ``ok: ``,
    carrying ``run_id=<the document's run_id>`` and ``run_dir=<the document's
    run_dir>`` -- the value ``resume --run-dir`` accepts."""
    payload, checkpoint = _stage(tmp_path, real_run)
    _, document, _ = real_run
    dispatched = _dispatched(document)
    assert dispatched["status"] == DONE, (
        f"the real run must reach {DONE!r} or none of these fixtures is a "
        f"success document; got {dispatched['status']!r}"
    )
    assert checkpoint.is_file(), f"the staged fixture must hold {checkpoint}"

    proc = _consume(payload, tmp_path)
    assert proc.returncode == 0, (
        "a document whose run succeeded AND whose persisted checkpoint agrees "
        f"must exit 0; rc={proc.returncode}\nstdout:{proc.stdout!r}\n"
        f"stderr:{proc.stderr!r}"
    )
    line = _sole_line(proc.stdout, "stdout")
    assert line.startswith(OK_PREFIX), line
    assert f"{RUN_ID_TOKEN}{dispatched['run_id']}" in line, (
        f"the summary must name the document's own run_id "
        f"{dispatched['run_id']!r}: {line!r}"
    )
    assert f"{RUN_DIR_TOKEN}{dispatched['run_dir']}" in line, (
        "the summary must name the run_dir `resume --run-dir` accepts "
        f"({dispatched['run_dir']!r}): {line!r}"
    )
    assert VERIFIED in line, (
        f"an accepted document must report the join as verified: {line!r}"
    )


def test_b1b_the_two_identifiers_are_genuinely_different_values(
    real_run: tuple[str, dict, Path],
) -> None:
    """Anti-vacuity for behavior 1. Reporting ``run_dir=`` is only worth a token
    if it is NOT the value already printed as ``run_id`` -- the whole defect is
    that ``run_id`` names no path and is not what ``resume --run-dir`` takes."""
    _, document, _ = real_run
    dispatched = _dispatched(document)
    run_id, run_dir = str(dispatched["run_id"]), str(dispatched["run_dir"])
    assert run_id not in run_dir, (
        "the run id must not be a substring of the run dir, else the new token "
        f"is redundant: run_id={run_id!r} run_dir={run_dir!r}"
    )
    assert run_dir.startswith(f"{STATE_DIR_NAME}/run-"), run_dir


# ---------------------------------------------------------------------------
# Behavior 2 -- a run dir holding NO checkpoint is a failure that names the path
# ---------------------------------------------------------------------------


def test_b2_run_dir_holding_no_checkpoint_exits_1_and_names_the_path(
    tmp_path: Path, real_run: tuple[str, dict, Path]
) -> None:
    """Spec behavior 2: the run dir EXISTS and holds no ``checkpoint.json``."""
    payload, checkpoint = _stage(tmp_path, real_run)
    checkpoint.unlink()
    assert checkpoint.parent.is_dir(), "the run dir itself must remain, per behavior 2"

    proc = _consume(payload, tmp_path)
    assert proc.returncode == 1, (
        "a run dir holding no checkpoint means the run did not verifiably "
        f"succeed -- exit 1, never a fresh code; rc={proc.returncode}\n"
        f"stdout:{proc.stdout!r}\nstderr:{proc.stderr!r}"
    )
    _, document, _ = real_run
    expected = f"{_dispatched(document)['run_dir']}/{CHECKPOINT_NAME}"
    assert expected in _messages(proc), (
        f"the message must name the checkpoint path it looked for ({expected!r}); "
        f"got stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert proc.stdout == "" or not proc.stdout.startswith(OK_PREFIX), (
        f"a rejected document must not print an ok line: {proc.stdout!r}"
    )


def test_b2b_an_absent_run_dir_is_skipped_but_never_reported_as_verified(
    tmp_path: Path, real_run: tuple[str, dict, Path]
) -> None:
    """The run-dir-not-present path, given a ``tmp_path``-OWNED oracle.

    A document can legitimately be graded on a host that never held the run
    (``test_iter174_behavior.py`` publishes exactly such a document), so an
    absent run dir is not a failure. The load-bearing half is that the skip must
    ANNOUNCE itself: if a not-checked join printed ``checkpoint=verified`` the
    gate would be fail-open, and the durability claim would again be true by
    construction. Nothing is staged here, so ``run_dir`` does not exist under
    ``cwd`` -- an owned precondition, not the ambient absence of a ``/tmp`` path.
    """
    raw, document, _ = real_run
    rel = _dispatched(document)["run_dir"]
    assert not (tmp_path / rel).exists(), "precondition: the run dir must be absent"

    proc = _consume(raw, tmp_path)
    assert proc.returncode == 0, (
        "a document graded where its run dir does not exist must stay acceptable "
        f"(test_iter174 publishes one); rc={proc.returncode}\n"
        f"stdout:{proc.stdout!r}\nstderr:{proc.stderr!r}"
    )
    line = _sole_line(proc.stdout, "stdout")
    assert line.startswith(OK_PREFIX), line
    assert VERIFIED not in line, (
        "a join that was NOT performed must never read as verified -- that is a "
        f"fail-open durability gate: {line!r}"
    )
    assert "checkpoint=" in line, (
        f"the summary must still report the checkpoint's disposition: {line!r}"
    )


def test_b2c_a_present_non_directory_run_dir_is_never_reported_as_verified(
    tmp_path: Path, real_run: tuple[str, dict, Path]
) -> None:
    """AMBIGUITY, tested at its most defensible reading and reported as PM
    feedback rather than legislated here.

    ``pm.md`` enumerates a run dir that HOLDS no checkpoint (behavior 2) and,
    through the shipped ``test_iter174`` document, a run dir that is not present.
    It says nothing about a ``run_dir`` that exists but is an ordinary FILE --
    a genuinely broken run dir that is nonetheless on this host. MEASURED today:
    that case takes the not-present path and exits 0. This test therefore asserts
    only the invariant that holds under EITHER policy -- the join must not claim
    to have been verified -- and deliberately does not pin an exit code the spec
    never chose.
    """
    payload, checkpoint = _stage(tmp_path, real_run)
    run_dir = checkpoint.parent
    shutil.rmtree(run_dir)
    run_dir.write_text("not a directory\n", encoding="utf-8")
    assert run_dir.is_file(), "precondition: run_dir must exist and not be a directory"

    proc = _consume(payload, tmp_path)
    if proc.returncode == 0:
        line = _sole_line(proc.stdout, "stdout")
        assert VERIFIED not in line, (
            "a run_dir that is not a directory cannot have had its checkpoint "
            f"reconciled, so the summary must not claim it: {line!r}"
        )
    else:
        assert proc.returncode == 1, (
            "a broken run dir must reuse exit 1 (the run did not verifiably "
            f"succeed), never a fresh code; rc={proc.returncode}"
        )


# ---------------------------------------------------------------------------
# Behavior 3 -- unparseable checkpoint bytes, with a two-sided control
# ---------------------------------------------------------------------------


def test_b3_unparseable_checkpoint_exits_1_without_a_traceback(
    tmp_path: Path, real_run: tuple[str, dict, Path]
) -> None:
    """Spec behavior 3, two-sided in ONE test as ``pm.md`` requires: the planted
    bad bytes must FAIL and the very same fixture with the real bytes must PASS,
    otherwise the assertion cannot tell a working guard from a script that always
    fails. A crash is not a diagnosis, so stderr must carry no traceback."""
    payload, checkpoint = _stage(tmp_path, real_run)
    good = checkpoint.read_bytes()

    checkpoint.write_bytes(b'{"run_id": "trunc')
    bad = _consume(payload, tmp_path)
    assert bad.returncode == 1, (
        "checkpoint bytes that are not valid JSON mean the run did not verifiably "
        f"succeed -- exit 1; rc={bad.returncode}\nstdout:{bad.stdout!r}\n"
        f"stderr:{bad.stderr!r}"
    )
    assert "not valid JSON" in _messages(bad), (
        "the message must say the checkpoint is not valid JSON; got "
        f"stdout={bad.stdout!r} stderr={bad.stderr!r}"
    )
    assert "Traceback (most recent call last)" not in bad.stderr, (
        f"an unreadable checkpoint must be diagnosed, not crashed on: {bad.stderr!r}"
    )

    checkpoint.write_bytes(good)
    control = _consume(payload, tmp_path)
    assert control.returncode == 0, (
        "CONTROL: the identical fixture with the real checkpoint bytes must be "
        f"accepted, or the failure above proves nothing; rc={control.returncode}\n"
        f"stdout:{control.stdout!r}\nstderr:{control.stderr!r}"
    )
    assert VERIFIED in _sole_line(control.stdout, "stdout")


def test_b3b_an_empty_checkpoint_file_is_also_rejected(
    tmp_path: Path, real_run: tuple[str, dict, Path]
) -> None:
    """Spec Why-section, verbatim: "a demo that persisted a truncated, EMPTY or
    contradictory checkpoint passes every graded step today". Zero bytes is the
    single likeliest persistence failure (an interrupted write) and it is not
    valid JSON, so it must take behavior 3's path."""
    payload, checkpoint = _stage(tmp_path, real_run)
    checkpoint.write_bytes(b"")
    proc = _consume(payload, tmp_path)
    assert proc.returncode == 1, (
        f"an EMPTY checkpoint must be rejected; rc={proc.returncode}\n"
        f"stdout:{proc.stdout!r}\nstderr:{proc.stderr!r}"
    )
    assert proc.stdout == "" or not proc.stdout.startswith(OK_PREFIX), proc.stdout


# ---------------------------------------------------------------------------
# Behavior 4 -- disagreement on run_id or on status, reporting BOTH values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["run_id", "status"])
def test_b4_a_disagreeing_checkpoint_exits_1_and_reports_both_values(
    tmp_path: Path, real_run: tuple[str, dict, Path], field: str
) -> None:
    """Spec behavior 4, for each of the two fields ``README.md`` publishes as
    matching. The message must report BOTH values -- naming only one leaves a
    reader unable to tell which copy is wrong."""
    payload, checkpoint = _stage(tmp_path, real_run)
    _, document, _ = real_run
    document_value = str(_dispatched(document)[field])

    persisted = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert str(persisted[field]) == document_value, (
        "PREMISE: the real persisted checkpoint must AGREE with the document on "
        f"{field} before disagreement can be planted; document={document_value!r} "
        f"checkpoint={persisted[field]!r}"
    )
    tampered_value = NON_SUCCESS[0] if field == "status" else "deadbeefcafe"
    assert tampered_value != document_value, tampered_value
    persisted[field] = tampered_value
    checkpoint.write_text(json.dumps(persisted), encoding="utf-8")

    proc = _consume(payload, tmp_path)
    assert proc.returncode == 1, (
        f"a checkpoint disagreeing on {field} means the run did not verifiably "
        f"succeed -- exit 1; rc={proc.returncode}\nstdout:{proc.stdout!r}\n"
        f"stderr:{proc.stderr!r}"
    )
    said = _messages(proc)
    for label, value in (("document", document_value), ("checkpoint", tampered_value)):
        assert value in said, (
            f"the message must report the {label}'s {field} ({value!r}) so a "
            f"reader can tell which copy is wrong; got {said!r}"
        )
    assert proc.stdout == "" or not proc.stdout.startswith(OK_PREFIX), proc.stdout


def test_b4b_the_join_is_not_vacuous_the_document_and_checkpoint_really_agree(
    tmp_path: Path, real_run: tuple[str, dict, Path]
) -> None:
    """The premise the whole iteration rests on, asserted rather than assumed:
    the persisted checkpoint independently carries the two fields
    ``README.md`` claims it matches. If the file lacked them, every comparison
    above would be comparing something against nothing."""
    _, checkpoint = _stage(tmp_path, real_run)
    persisted = json.loads(checkpoint.read_text(encoding="utf-8"))
    _, document, _ = real_run
    dispatched = _dispatched(document)
    for field in ("run_id", "status"):
        assert field in persisted, (
            f"the persisted checkpoint must carry {field!r} for the documented "
            f"join to exist at all; its keys are {sorted(persisted)}"
        )
        assert str(persisted[field]) == str(dispatched[field]), (
            f"README publishes that the document's {field} matches the run dir's "
            f"checkpoint: document={dispatched[field]!r} "
            f"checkpoint={persisted[field]!r}"
        )
    assert persisted["status"] == DONE, persisted["status"]


# ---------------------------------------------------------------------------
# Behavior 5 -- the real persisted checkpoint of a real demo-shaped run passes,
# and it reaches both graded gates without a new gate step
# ---------------------------------------------------------------------------


def test_b5_the_real_demo_shaped_run_passes_the_new_cross_check(
    real_run: tuple[str, dict, Path],
) -> None:
    """Spec behavior 5, driven the way ``test_iter110_behavior`` requires (no
    nested ``make``): the demo's own argument set with its RELATIVE
    ``--state-dir``, graded from that run's own root, so the checkpoint read
    back is the one the run actually persisted. The success line must name a
    ``run_dir`` under ``.pla_runs/run-`` and report the join as verified."""
    raw, _, root = real_run
    proc = _consume(raw, root)
    assert proc.returncode == 0, (
        "the real run's own document must be accepted against its own persisted "
        f"checkpoint; rc={proc.returncode}\nstdout:{proc.stdout!r}\n"
        f"stderr:{proc.stderr!r}"
    )
    line = _sole_line(proc.stdout, "stdout")
    assert line.startswith(OK_PREFIX), line
    assert f"{RUN_DIR_TOKEN}{STATE_DIR_NAME}/run-" in line, (
        f"the summary must name the demo-shaped run dir: {line!r}"
    )
    assert VERIFIED in line, line
    assert proc.stderr == "", (
        f"an accepted document must be silent on stderr: {proc.stderr!r}"
    )


def test_b5b_the_cross_check_reaches_both_gates_without_a_new_gate_step() -> None:
    """Spec acceptance criteria: the grading rides inside the existing ``demo``
    recipe, which ``make check`` composes and CI invokes, so the four pinned
    gate-contract sites stay byte-identical. Read through the SHIPPED recipe
    parser, so this cannot pass by disagreeing with the guards it is about."""
    from tests.test_iter110_behavior import CI_GATE_STEPS
    from tests.test_iter198_behavior import _recipe

    demo = _recipe("demo")
    assert demo[-1] == CONSUMER_STEP, (
        f"the consumer must still be the LAST step of the demo recipe: {demo!r}"
    )
    assert len(demo) == 5, (
        f"the demo recipe's length is pinned so a new gate step cannot be smuggled "
        f"in as a demo step unnoticed -- iteration 199 changed the consumer, not "
        f"the recipe, and factory iter 204 took it to five by publishing and "
        f"grading the autonomy audit; got {len(demo)}: {demo!r}"
    )
    assert CONSUMER_STEP not in tuple(CI_GATE_STEPS), (
        "the consumer must reach CI through `make demo`, never as its own graded "
        f"step; CI_GATE_STEPS is {list(CI_GATE_STEPS)!r}"
    )
    assert any("demo" in step for step in _recipe("check")), (
        f"`make check` must still compose the demo target: {_recipe('check')!r}"
    )


# ---------------------------------------------------------------------------
# The published contract -- documented below the human-owned marker, and with
# no volatile literal
# ---------------------------------------------------------------------------


def test_b6_readme_documents_the_new_token_below_the_marker_without_a_volatile_id() -> None:
    """Spec acceptance criteria. The sample success line gains ``run_dir=`` and a
    checkpoint disposition, the prose says the consumer now grades the persisted
    checkpoint, all of it BELOW the human-owned portfolio intro -- and the sample
    publishes NO minted run id, which would be stale on the very next run."""
    lines = README.read_text(encoding="utf-8").splitlines()
    markers = [i for i, ln in enumerate(lines, start=1) if HUMAN_OWNED_MARKER in ln]
    assert len(markers) == 1, f"expected exactly one marker line, found {markers}"
    marker = markers[0]
    above = "\n".join(lines[: marker - 1])
    below_lines = lines[marker:]
    below = "\n".join(below_lines)

    for needle in (CHECKPOINT_NAME, RUN_DIR_TOKEN):
        assert needle in below, (
            f"the reference sections must document {needle!r}; it is absent below "
            "the human-owned marker"
        )
    assert CHECKPOINT_NAME not in above, (
        f"{CHECKPOINT_NAME!r} appears ABOVE the human-owned marker -- the "
        "portfolio intro must not be restructured by an automated contributor"
    )

    samples = [ln for ln in below_lines if ln.startswith(OK_PREFIX + RUN_ID_TOKEN)]
    assert samples, (
        "the README must still publish a sample success line starting "
        f"{OK_PREFIX + RUN_ID_TOKEN!r}, or this guard is vacuous"
    )
    for sample in samples:
        assert RUN_DIR_TOKEN in sample, (
            f"the published sample line must carry the new token: {sample!r}"
        )
        assert "checkpoint=" in sample, (
            f"the published sample line must report the join: {sample!r}"
        )
        found = HEX12.findall(sample)
        assert not found, (
            f"the sample line publishes the volatile literal(s) {found!r}, which "
            f"are stale on the next run; use a placeholder: {sample!r}"
        )
