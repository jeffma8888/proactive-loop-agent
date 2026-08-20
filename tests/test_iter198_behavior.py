"""Black-box oracle for factory iteration 195 (state dir ``iter-193``).

Feature under test: ``make demo`` publishes the run it just performed as one
machine-readable document at ``.pla_runs/run.json`` and GRADES that document
with the committed consumer ``examples/check_run.py`` -- so both graded gates
(``make check`` locally, ``.github/workflows/ci.yml`` on every push) now EXECUTE
the published ``run --json`` contract instead of only asserting that files
exist.

MODULE NAME -- DERIVED FROM THE REPO, NEVER FROM THE STATE-DIR NUMBER. This
repo names behavior modules by the FACTORY iteration number, which runs ahead of
the state-dir counter (state dir ``iter-193`` ships as ``factory iter 195``).
The highest tracked ``test_iterNN_behavior.py`` is 197, so this file is 198, and
the path was proven free two-sided before a byte was written:
``git cat-file -e HEAD:tests/test_iter198_behavior.py`` exits 128 (free) while
the same probe for 197 exits 0 (taken). Writing the state-dir number here would
overwrite a shipped oracle, which is the iter-172/iter-186 destroyed-oracle
failure.

ISOLATION CONTRACT (honored, no exceptions). Every assertion is derived from
this iteration's spec ("Expected Behaviors" in ``pm.md``), the repo's own
``tests/`` conventions, the two GATE DEFINITIONS the behaviors are about
(``Makefile``, ``.github/workflows/ci.yml``), the human-readable ``README.md``,
and the product's OBSERVABLE output obtained by RUNNING it. **No file under
``src/`` was read, no ``examples/check_run.py`` source was read, no
``engineer.md`` / ``reviewer.md`` / ``fix_review.md`` was opened, and no
``git diff`` was inspected.** Fully offline and deterministic: the bundled
scripted provider only, no network, no API key.

WHY THE CONSUMER IS A SUBPROCESS AND NOT AN IMPORTED ``grade()`` (a deliberate,
recorded deviation from the spec's phrasing of behavior 4). The spec suggests
importing ``examples/check_run.py``'s ``grade()``; ``examples/`` is not a
package, so importing a named private function out of it means READING that
script, which the isolation contract forbids. The graded gate does not call
``grade()`` either -- the ``demo`` recipe runs the script and ``make`` reads its
EXIT CODE -- so this module drives it exactly as the recipe does, through
``sys.executable`` (which IS the project venv's interpreter under
``uv run pytest``, the same interpreter ``uv run python`` selects), with the
document on stdin. Both spec directions are still proven, and they are proven
against the contract the Makefile actually grades.

BOTH DIRECTIONS FROM ONE RUN. A gate step proven green but never proven to FIRE
is a fail-open gate, so behavior 4 asserts acceptance AND rejection. The demo's
own argument set is performed exactly ONCE, in a module-scoped fixture, and
every behavior-4 test reads that one result -- the ``tester`` stage is measured
near the 600s cap and a tester timeout reverts the engineer's work too.

NO NESTED BUILD TOOLS. ``tests/test_iter110_behavior.py`` forbids the suite from
shelling out to a gate step; a nested ``uv``/``make``/``pytest`` run strands
this stage against its cap. The demo run is therefore driven IN-PROCESS through
``proactive_loop.cli.main([...])`` (the idiom ~99 existing call sites use) and
every byte it writes lands under ``tmp_path_factory``. ``examples/fixture_workspace``
is read as the recipe reads it; nothing here writes inside it, and nothing is
written inside the product repo.

NO INDENTATION ASSERTIONS. CI is a 3.12 + 3.13 matrix and 3.13 strips the common
leading docstring indent at compile time, so nothing here asserts on docstring,
comment or help-text indentation.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.cli import main
from proactive_loop.models import RunStatus

REPO: Final = Path(__file__).resolve().parents[1]
MAKEFILE: Final = REPO / "Makefile"
README: Final = REPO / "README.md"
CONSUMER: Final = REPO / "examples" / "check_run.py"
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"

# The published document and the three recipe steps of spec behavior 1.
RUN_DOC: Final = ".pla_runs/run.json"
MKDIR_STEP: Final = "mkdir -p .pla_runs"
CONSUMER_STEP: Final = f"uv run python examples/check_run.py < {RUN_DOC}"
RUN_STEP_PREFIX: Final = "uv run pla run"
EXPECTED_DEMO_STEPS: Final = 3

# `make check`'s opening step -- the reason `mkdir -p` has to exist at all.
FRESHNESS_PRESTEP: Final = "rm -rf .pla_runs"

# Spec behavior 3: the live assertions of the two shipped demo pins.
ADJACENT_PAIR: Final = "--state-dir .pla_runs --snapshot .pla_runs/snapshot.json"
SNAPSHOT_VALUE: Final = "--snapshot .pla_runs/snapshot.json"
STATE_DIR: Final = ".pla_runs"
# test_iter110_behavior.py's own extractor, reused verbatim rather than reworded.
STATE_DIR_RE: Final = re.compile(r"--state-dir[=\s]+(\S+)")

# Spec behavior 5: a standalone shell redirect operator. A `<DIR>`-style
# placeholder is NOT one (it ends `>`), which is why this is a token set and not
# a substring scan -- the guard must not forbid a future published placeholder.
REDIRECT_TOKENS: Final = frozenset({">", ">>", ">|", "<", "<<", "1>", "2>", "&>"})
HUMAN_OWNED_MARKER: Final = "PORTFOLIO INTRO"

# DERIVED, never typed: the one status value that means success.
DONE: Final = RunStatus.DONE.value
NON_SUCCESS: Final = tuple(sorted(m.value for m in RunStatus if m.value != DONE))


# ---------------------------------------------------------------------------
# Helpers -- an INDEPENDENT reading of the gate definition, so this oracle can
# DISAGREE with the shipped drift guards instead of echoing them. Behavior 3b
# then cross-checks it against the shipped parser it is allowed to disagree with.
# ---------------------------------------------------------------------------


def _recipe(target: str) -> list[str]:
    """The command lines of one ``Makefile`` target, backslash-continuations
    joined into ONE logical command each and whitespace normalized."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"{target}:")), None)
    assert start is not None, f"Makefile must define a `{target}:` target"
    out: list[str] = []
    pending = ""
    for raw in lines[start + 1 :]:
        if raw and not raw.startswith("\t"):
            break  # the next target (or a blank-separated block) ends the recipe
        body = raw.strip()
        if not body:
            continue
        if body.endswith("\\"):
            pending += body[:-1].strip() + " "
            continue
        out.append(" ".join((pending + body).split()))
        pending = ""
    assert not pending, f"`{target}:` ends on a dangling continuation"
    return out


def _demo() -> list[str]:
    return _recipe("demo")


def _consume(payload: str) -> subprocess.CompletedProcess[str]:
    """Run the COMMITTED consumer exactly as the recipe does: script, stdin, exit
    code. ``sys.executable`` is the project venv's interpreter under
    ``uv run pytest``, which is the interpreter ``uv run python`` selects too."""
    return subprocess.run(
        [sys.executable, str(CONSUMER)],
        input=payload,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _sole_line(stream: str, label: str) -> str:
    lines = stream.splitlines()
    assert len(lines) == 1, f"{label}: expected exactly one line, got {lines!r}"
    return lines[0]


def _redirects(command: str) -> list[str]:
    """The standalone shell-redirect operators in one published command line.

    Tokenized with ``shlex`` -- the same split ``test_iter116_behavior.argv_of``
    performs before handing every token to the LIVE argparse parser, which is
    precisely why a redirect published inside a fenced ``pla`` line reds the
    build: ``>`` arrives as an unexpected positional and argparse exits.
    """
    return [tok for tok in shlex.split(command) if tok in REDIRECT_TOKENS]


def _published() -> list[tuple[int, str]]:
    """Every fenced README logical line the shipped guard considers a published
    ``pla`` invocation -- read through THAT guard's own extractor, so this
    module cannot pass by disagreeing with the domain it is guarding."""
    from tests.test_iter116_behavior import published_commands

    text = README.read_text(encoding="utf-8")
    return [(c.lineno, c.line) for c in published_commands(text)]


# ---------------------------------------------------------------------------
# The single real demo run, shared by every behavior-4 test.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, dict[str, object]]:
    """``(raw_stdout, parsed_document)`` from ONE in-process performance of the
    demo recipe's own argument set, ``--json`` included, into a private dir."""
    root = tmp_path_factory.mktemp("iter198-demo")
    state = root / "state"
    argv = [
        "run",
        "--workspace",
        str(FIXTURE),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(state),
        "--snapshot",
        str(state / "snapshot.json"),
        "--json",
    ]
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        rc = main(argv)
    raw = stdout.getvalue()
    assert rc == 0, (
        "the demo's own argument set must exit 0 before its document can be "
        f"graded; rc={rc}\nstdout:{raw!r}\nstderr:{stderr.getvalue()!r}"
    )
    document = json.loads(raw)
    assert isinstance(document, dict), type(document).__name__
    return raw, document


# ---------------------------------------------------------------------------
# Behavior 1 -- recipe shape: exactly three steps, in this order
# ---------------------------------------------------------------------------


def test_b1_demo_recipe_is_exactly_three_steps_in_the_specified_order() -> None:
    """Spec behavior 1: ``mkdir -p`` -> the redirecting run -> the consumer."""
    recipe = _demo()
    assert len(recipe) == EXPECTED_DEMO_STEPS, (
        f"the demo recipe must be exactly {EXPECTED_DEMO_STEPS} logical steps; "
        f"got {len(recipe)}: {recipe!r}"
    )
    assert recipe[0] == MKDIR_STEP, (
        f"step (a) must be exactly {MKDIR_STEP!r}; got {recipe[0]!r}"
    )
    assert recipe[1].startswith(RUN_STEP_PREFIX), (
        f"step (b) must be the pre-existing `pla run` invocation; got {recipe[1]!r}"
    )
    assert recipe[1].endswith(f"> {RUN_DOC}"), (
        f"step (b) must redirect into {RUN_DOC}; got {recipe[1]!r}"
    )
    assert recipe[1].count("--json") == 1, (
        f"step (b) must carry EXACTLY one --json; got {recipe[1]!r}"
    )
    assert recipe[2] == CONSUMER_STEP, (
        f"step (c) must be exactly {CONSUMER_STEP!r}; got {recipe[2]!r}"
    )


def test_b1b_consumer_step_runs_through_the_project_venv() -> None:
    """Spec behavior 1: the consumer imports ``proactive_loop``, so its first
    three tokens are ``uv run python`` -- never a bare ``python``."""
    recipe = _demo()
    tokens = recipe[-1].split()
    assert tokens[:3] == ["uv", "run", "python"], (
        "the consumer step must run through the project virtualenv (it imports "
        f"proactive_loop); step is {recipe[-1]!r}"
    )
    assert "examples/check_run.py" in tokens, recipe[-1]


# ---------------------------------------------------------------------------
# Behavior 2 -- ordering, and a document that can never be graded stale
# ---------------------------------------------------------------------------


def test_b2_mkdir_precedes_the_redirect_and_the_consumer_is_last() -> None:
    """Spec behavior 2. The shell opens ``>`` BEFORE ``pla run`` starts, and
    ``make check`` opens by deleting ``.pla_runs`` -- so without an earlier
    ``mkdir -p`` the gate dies on a missing directory rather than on anything
    the demo did."""
    recipe = _demo()
    idx_mkdir = recipe.index(MKDIR_STEP)
    idx_redirect = next(i for i, s in enumerate(recipe) if f"> {RUN_DOC}" in s)
    idx_consumer = recipe.index(CONSUMER_STEP)
    assert idx_mkdir < idx_redirect, (
        f"mkdir={idx_mkdir} must precede the redirecting step={idx_redirect}: {recipe!r}"
    )
    assert idx_consumer == len(recipe) - 1, (
        f"the consumer must be the LAST step of the recipe; got index "
        f"{idx_consumer} of {len(recipe)}: {recipe!r}"
    )
    # The premise that makes the mkdir step necessary, asserted rather than
    # assumed: the gate really does wipe that directory first.
    assert _recipe("check")[0] == FRESHNESS_PRESTEP, (
        "`make check` must still open by wiping .pla_runs, or behavior 2's "
        f"ordering requirement is arbitrary; check recipe is {_recipe('check')!r}"
    )


def test_b2b_the_redirect_is_a_single_truncating_gt_and_never_appends() -> None:
    """Spec behavior 2: a single ``>``, so the graded document is always THIS
    run's and can neither accumulate nor be graded stale."""
    recipe = _demo()
    joined = " ".join(recipe)
    assert ">>" not in joined, (
        "the demo recipe must never APPEND to the graded document -- an "
        f"accumulating {RUN_DOC} is not one JSON object; recipe is {recipe!r}"
    )
    write_redirects = [tok for tok in recipe[1].split() if tok.startswith(">")]
    assert write_redirects == [">"], (
        f"step (b) must carry exactly one truncating `>`; got {write_redirects!r} "
        f"in {recipe[1]!r}"
    )
    assert joined.count(f"> {RUN_DOC}") == 1, (
        f"exactly one step may write {RUN_DOC}; recipe is {recipe!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- every pre-existing `demo` pin still holds
# ---------------------------------------------------------------------------


def test_b3_pre_existing_demo_pins_still_hold() -> None:
    """Spec behavior 3: the live assertions of
    ``test_iter186_behavior.py::test_b1`` and
    ``test_iter110_behavior.py::test_b4_demo_recipe_passes_the_same_state_dir``,
    restated so they are pinned to THIS recipe shape. The adjacency substring is
    the reason the new flag had to be APPENDED after ``--snapshot`` rather than
    inserted between the pair."""
    joined = " ".join(_demo())
    assert joined.count("--snapshot") == 1, joined
    assert SNAPSHOT_VALUE in joined, joined
    assert ADJACENT_PAIR in joined, (
        "the --state-dir/--snapshot pair must stay ADJACENT and in that order; "
        f"joined recipe is {joined!r}"
    )
    values = {v.rstrip("/") for v in STATE_DIR_RE.findall(joined)}
    assert values, f"no --state-dir argument found in the demo recipe: {joined!r}"
    assert values == {STATE_DIR}, (
        f"every --state-dir value must resolve to {STATE_DIR!r}; found {values}"
    )


def test_b3b_independent_recipe_reading_agrees_with_the_shipped_pin_parser() -> None:
    """Two readings of the same recipe must agree, or one of them is wrong.

    This module parses the Makefile itself so it CAN disagree with the shipped
    guards; that freedom is only useful if the disagreement surfaces, so the
    shipped parser is imported and both step lists are compared.
    """
    from tests.test_iter186_behavior import _recipe as shipped_recipe

    assert _demo() == shipped_recipe("demo"), (
        "this module's reading of the `demo` recipe disagrees with "
        f"test_iter186_behavior._recipe: mine={_demo()!r} "
        f"shipped={shipped_recipe('demo')!r}"
    )


def test_b3c_no_gate_step_was_added_by_this_iteration() -> None:
    """Spec acceptance criteria / Out of Scope: the whole point of grading inside
    the ``demo`` recipe is that BOTH gates get it with ``ci.yml``, the ``check``
    recipe and the 3-site byte-identical pins untouched."""
    from tests.test_iter102_behavior import EXPECTED_CI_RUN_STEPS as C102
    from tests.test_iter110_behavior import (
        ARTIFACT_ASSERTION_STEPS,
        CI_GATE_STEPS,
        EXPECTED_CI_RUN_STEPS as C110,
    )

    assert C102 == C110 == 7, f"the graded step count changed: {C102} / {C110}"
    expensive = [s for s in CI_GATE_STEPS if s not in tuple(ARTIFACT_ASSERTION_STEPS)]
    assert len(expensive) == 6, (
        f"the expensive gate-step set must stay 6 -- this iteration adds a graded "
        f"consumer WITHOUT adding a gate step; got {len(expensive)}: {expensive!r}"
    )
    assert CONSUMER_STEP not in tuple(CI_GATE_STEPS), (
        "the consumer must reach CI through `make demo`, not as its own graded "
        f"step; CI_GATE_STEPS is {list(CI_GATE_STEPS)!r}"
    )
    # `check` composes the demo rather than re-inlining it, which is HOW the new
    # step reaches the local gate without a new step.
    assert any("demo" in step for step in _recipe("check")), (
        f"`make check` must still compose the demo target: {_recipe('check')!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- the demo's document is one the committed consumer accepts, and
# the same gate is proven to FIRE. Both directions, one run.
# ---------------------------------------------------------------------------


def test_b4_the_demo_document_is_one_object_carrying_a_dispatched_run(
    demo_run: tuple[str, dict[str, object]],
) -> None:
    """Spec behavior 4, and the anti-vacuity premise for both directions below:
    the graded document must actually carry a SUCCEEDED dispatched run, else
    'accepted' and 'rejected' would not be testing opposite things."""
    _, document = demo_run
    dispatched = document.get("dispatched")
    assert isinstance(dispatched, dict), (
        "the demo must dispatch a run, or the graded document proves nothing; "
        f"top-level keys are {sorted(document)}"
    )
    assert dispatched.get("status") == DONE, (
        f"the demo's dispatched run must reach {DONE!r}; got "
        f"{dispatched.get('status')!r}"
    )
    assert NON_SUCCESS, (
        "no non-success RunStatus member exists, so the rejection direction "
        "below would assert nothing"
    )


def test_b4b_committed_consumer_accepts_the_demos_own_document(
    demo_run: tuple[str, dict[str, object]],
) -> None:
    """Spec behavior 4, direction 1: exit 0 and one ``ok: `` summary line."""
    raw, document = demo_run
    proc = _consume(raw)
    assert proc.returncode == 0, (
        "the demo's own published document must be ACCEPTED by the consumer the "
        f"recipe grades it with; rc={proc.returncode}\nstdout:{proc.stdout!r}\n"
        f"stderr:{proc.stderr!r}"
    )
    line = _sole_line(proc.stdout, "stdout")
    assert line.startswith("ok: "), line
    assert f"status={DONE}" in line, line
    run_id = document["dispatched"]["run_id"]  # type: ignore[index]
    assert str(run_id) in line, (
        f"the summary must name the document's own run_id {run_id!r}: {line!r}"
    )
    assert proc.stderr == "", f"an accepted document must be silent on stderr: {proc.stderr!r}"


def test_b4c_the_same_document_with_a_non_success_status_is_rejected(
    demo_run: tuple[str, dict[str, object]],
) -> None:
    """Spec behavior 4, direction 2. A gate proven green but never proven to
    fire is a fail-open gate: the SAME document, with only
    ``dispatched["status"]`` flipped to a non-success member of the LIVE enum,
    must exit 1."""
    _, document = demo_run
    tampered = json.loads(json.dumps(document))
    status = NON_SUCCESS[0]
    assert status != DONE, status
    tampered["dispatched"]["status"] = status
    proc = _consume(json.dumps(tampered))
    assert proc.returncode == 1, (
        f"a document whose run did not succeed (status={status!r}) must exit 1 -- "
        "kept distinct from a malformed-input 2; "
        f"rc={proc.returncode}\nstdout:{proc.stdout!r}\nstderr:{proc.stderr!r}"
    )
    assert proc.stdout == "", f"a rejected document must print no ok line: {proc.stdout!r}"


# ---------------------------------------------------------------------------
# Behavior 5 -- README documents it, and no fenced `pla` line may redirect
# ---------------------------------------------------------------------------


def test_b5_readme_documents_the_graded_document_below_the_human_owned_marker() -> None:
    """Spec behavior 5: the reference sections state that ``make demo`` also
    writes ``.pla_runs/run.json`` and grades it with ``examples/check_run.py``,
    and the whole statement lives BELOW the human-owned marker."""
    lines = README.read_text(encoding="utf-8").splitlines()
    markers = [i for i, ln in enumerate(lines, start=1) if HUMAN_OWNED_MARKER in ln]
    assert len(markers) == 1, f"expected exactly one marker line, found {markers}"
    marker = markers[0]
    below = "\n".join(lines[marker:])
    above = "\n".join(lines[: marker - 1])
    for needle in (RUN_DOC, "examples/check_run.py"):
        assert needle in below, (
            f"the reference sections must document {needle!r}; it is absent below "
            "the human-owned marker"
        )
        assert needle not in above, (
            f"{needle!r} appears ABOVE the human-owned marker -- the portfolio "
            "intro must not be restructured by an automated contributor"
        )


def test_b5b_no_published_pla_line_carries_a_shell_redirect() -> None:
    """Spec behavior 5, as a DERIVED guard so the trap is enforced rather than
    remembered. ``test_iter116_behavior.argv_of`` ``shlex.split``s every fenced
    ``pla`` line and hands each token to the live parser, so a ``>`` becomes
    argv, argparse exits, and the build reds. The redirecting recipe therefore
    has to be documented in the PROSE lead-in, never inside the fence."""
    from tests.test_iter116_behavior import parse_published

    published = _published()
    assert published, "the README publishes no fenced `pla` command at all"
    # Anti-vacuity: the guard's domain must contain the very line an author
    # would be tempted to paste the recipe's redirect into.
    demo_lines = [
        (lineno, line)
        for lineno, line in published
        if "pla run" in line and "examples/fixture_workspace" in line
    ]
    assert demo_lines, (
        "the README must still publish the demo's own `pla run` invocation, or "
        f"this guard is vacuous; published lines are {published!r}"
    )
    for lineno, line in published:
        found = _redirects(line)
        assert not found, (
            f"README.md:{lineno} publishes a fenced `pla` line carrying the shell "
            f"redirect(s) {found!r}: {line!r}. A redirect must live in the prose "
            "lead-in instead -- inside the fence it is handed to argparse as argv."
        )
        parse_published(line)  # SystemExit propagates -- the invariant behind it


def test_b5c_the_redirect_guard_fires_on_a_planted_bad_line() -> None:
    """Positive control for behavior 5. An absence-based check needs proof it
    CAN fail, or a guard that never fires reads exactly like a clean README."""
    from tests.test_iter116_behavior import published_commands

    planted = "```bash\nuv run pla run --workspace . --json > .pla_runs/run.json\n```\n"
    commands = published_commands(planted)
    assert len(commands) == 1, commands
    assert _redirects(commands[0].line) == [">"], (
        "the guard must detect a redirect published inside a fenced `pla` line; "
        f"it found {_redirects(commands[0].line)!r}"
    )
    # And the placeholder form must NOT be flagged: the guard is a token check,
    # not a substring scan, so it cannot forbid a future `<DIR>` placeholder.
    assert _redirects("pla resume --run-dir <DIR>") == []
