"""Black-box behavior tests for factory iteration 204 (foundry state iter-230) ---
``make demo`` publishes its autonomy audit to ``.pla_runs/explain.json``, and the
new committed grader ``examples/check_autonomy.py`` fails the gate when that audit
violates the product's autonomy contract.

The hole this closes: ``SPEC.md``'s headline claim is that a goal in a sensitive
category always needs human approval, at any score -- and NOTHING enforced it on
what the demo publishes.  All four previously-graded demo steps (slate exists,
artifacts exist, citations resolve, checkout hygiene) pass unchanged on a slate
that auto-dispatched a ``finance_legal`` goal at score 25.0.

MODULE NAME PROVENANCE: ``207`` is derived from the repository -- ``git ls-files
tests`` tops out at ``test_iter206``, and ``git cat-file -e
HEAD:tests/test_iter207_behavior.py`` exits 128, so the path was free -- never from
the foundry state-dir number ``230``.  The two counters differ here and naming a
module from the state dir overwrites an already-shipped oracle.

ISOLATION CONTRACT (honored): every assertion below is written against THIS
iteration's spec (``pm.md`` "Expected Behaviors" 1-10) and drives only observable
surfaces -- the grader as a SUBPROCESS over stdin and its exit code (the convention
``test_iter198``/``test_iter199`` established for ``examples/`` consumers), the
published ``Makefile`` recipe, the CI workflow, and the product's own CLI.  **No
file under ``src/`` was read, no ``examples/check_autonomy.py`` source was read by
the author, no engineer or reviewer note was read, and no ``git diff`` was
consulted.**  Behaviors 8 and 9 are TEXTUAL contracts the spec states *about* that
file (it must spell no category literal, it must import nothing off-stdlib), so the
TEST parses it mechanically -- reading it programmatically is the only way to
assert them at all, and the author still never read it.

ANTI-VACUITY (deliberate): a grader's whole value is REFUSAL, and an exit-1
assertion passes against a script that refuses everything.  So every refusing arm
here is a planted-bad sample written to ``tmp_path`` and PAIRED with a control that
must exit 0 -- the identical payload with the single defect repaired.  Behavior 2
is the real-artifact control: the audit is produced by actually performing the
demo's own ``pla run`` argument set and then ``pla explain --json`` over the slate
it wrote.

Offline and deterministic: no network, the only subprocess is the committed grader
itself, and no assertion depends on the ambient gitignored ``.pla_runs/`` tree
(which ``make check`` deletes), so this module is fresh-clone safe.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest

from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.models import GoalCategory

REPO: Final = Path(__file__).resolve().parents[1]
MAKEFILE: Final = REPO / "Makefile"
WORKFLOW: Final = REPO / ".github" / "workflows" / "ci.yml"
PYPROJECT: Final = REPO / "pyproject.toml"
GRADER: Final = REPO / "examples" / "check_autonomy.py"
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"

STATE_DIR_NAME: Final = ".pla_runs"
AUDIT_NAME: Final = "explain.json"
EXPECTED_DEMO_STEPS: Final = 5

# Spec behavior 1 fixes this step verbatim.
PUBLISH_STEP: Final = (
    f"uv run pla explain --slate {STATE_DIR_NAME}/slate.json --json"
    f" > {STATE_DIR_NAME}/{AUDIT_NAME}"
)
# Spec behavior 10 fixes the LAST step verbatim; it must not move.
CONSUMER_STEP: Final = f"uv run python examples/check_run.py < {STATE_DIR_NAME}/run.json"
GRADER_NAME: Final = "examples/check_autonomy.py"

REQUIRED_KEYS: Final = ("id", "category", "score", "decision", "auto_dispatch_threshold")
AUTO: Final = "auto_dispatch"
NEEDS: Final = "needs_approval"

# DERIVED from the product, never typed here -- exactly the discipline spec
# behavior 8 imposes on the grader itself.
_SETTINGS: Final = Settings.from_env()
SENSITIVE: Final = tuple(sorted(c.value for c in _SETTINGS.sensitive_categories))
SAFE: Final = tuple(sorted(c.value for c in GoalCategory if c.value not in SENSITIVE))
MIN_SCORE: Final = float(_SETTINGS.auto_dispatch_min_score)

NETWORK_TOKENS: Final = ("subprocess", "socket", "urllib", "requests", "httpx")
TRACEBACK: Final = "Traceback (most recent call last)"
NUMBER_RE: Final = re.compile(r"-?\d+(?:\.\d+)?")

EXIT_OK: Final = 0
EXIT_VIOLATION: Final = 1
EXIT_MALFORMED: Final = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _recipe(target: str) -> list[str]:
    """The command lines of one ``Makefile`` target, backslash-continuations joined
    into ONE logical command each and whitespace normalized.  ``test_iter198``'s
    extractor, reused rather than reworded."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"{target}:")), None)
    assert start is not None, f"Makefile must define a `{target}:` target"
    out: list[str] = []
    pending = ""
    for raw in lines[start + 1 :]:
        if raw and not raw.startswith("\t"):
            break
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


def _invokes(text: str, script: str) -> bool:
    """True when ``text`` RUNS ``script`` as a program, rather than merely NAMING it
    as an input to some other tool.

    Behavior 10 bans a second *invocation* of the grader, not every mention of its
    path, and factory iter 276 made that distinction load-bearing: the type oracle
    was widened to ``uv run mypy src/proactive_loop examples/check_run.py
    examples/check_autonomy.py``, which grades the grader's source without executing
    it.  A bare ``"check_autonomy" in text`` substring ban read that static check as
    a new gate step -- a fail-CLOSED reading of a rule about runtime.

    The discriminator is the interpreter, because this repo runs a script exactly one
    way: ``python <path>`` (``CONSUMER_STEP`` is the reference spelling).  So the
    token immediately before the path decides, and ``mypy <path>`` is not an
    invocation.  The callers pair this with a positive assertion that any NAMING
    site is the type oracle, so the loosened ban cannot fail open.
    """
    return re.search(rf"\bpython[0-9.]*\s+\S*{re.escape(script)}", text) is not None


def _grade(payload: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the COMMITTED grader exactly as the ``demo`` recipe does -- script,
    stdin, exit code.  ``sys.executable`` under ``uv run pytest`` is the project
    venv interpreter, which is the one ``uv run python`` selects too."""
    environ = dict(os.environ)
    environ.pop("PLA_SENSITIVE_CATEGORIES", None)
    if env:
        environ.update(env)
    return subprocess.run(
        [sys.executable, str(GRADER)],
        input=payload,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
        env=environ,
    )


def _grade_audit(
    tmp_path: Path,
    audit: object,
    *,
    name: str = "audit.json",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Write a synthetic audit under ``tmp_path`` (never into the repo), then feed
    that file's bytes to the grader on stdin, which is how the recipe invokes it."""
    doc = tmp_path / name
    doc.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return _grade(doc.read_text(encoding="utf-8"), env=env)


def _messages(proc: subprocess.CompletedProcess[str]) -> str:
    """Everything the grader said, on either stream.  The spec fixes the EXIT CODE
    and requires the message to NAME certain values; it does not fix which stream
    carries a refusal, so pinning one stream would test an unspecified detail."""
    return proc.stdout + proc.stderr


def _numbers(text: str) -> set[float]:
    """Every numeric token in a message, as floats -- so an assertion that the
    message NAMES a score or a threshold does not also pin its formatting
    (``4`` vs ``4.0`` vs ``4.00`` are all "naming 4.0")."""
    return {float(m.group(0)) for m in NUMBER_RE.finditer(text)}


def _entry(**over: Any) -> dict[str, Any]:
    """One audit entry carrying the full 12-key shape ``pla explain --json`` emits
    (roadmap #193 records that set as SPEC-closed), overridable per test."""
    base: dict[str, Any] = {
        "id": "aaaaaaaaaaaa",
        "title": "a goal",
        "category": SAFE[0],
        "score": MIN_SCORE + 10.0,
        "score_components": {},
        "auto_dispatch_threshold": MIN_SCORE,
        "decision": NEEDS,
        "reason": "a reason",
        "appropriate_now": True,
        "rationale": "a rationale",
        "sources": [],
        "suggested_first_steps": [],
    }
    base.update(over)
    return base


def _good_audit() -> list[dict[str, Any]]:
    """The smallest audit that is NOT vacuous and violates nothing: one compliant
    ``auto_dispatch`` above threshold in a SAFE category, plus one sensitive-category
    goal correctly held for approval, plus a spare safe row that carries no weight
    (so a test may deface it without emptying either non-vacuity arm)."""
    return [
        _entry(id="aaaaaaaaaaaa", category=SAFE[0], score=MIN_SCORE + 10.0, decision=AUTO),
        _entry(id="bbbbbbbbbbbb", category=SENSITIVE[0], score=25.0, decision=NEEDS),
        _entry(id="cccccccccccc", category=SAFE[-1], score=1.5, decision=NEEDS),
    ]


# ---------------------------------------------------------------------------
# The single real demo performance, shared by every real-artifact behavior.
# Performed ONCE: this stage is measured near the 600s cap and a tester timeout
# reverts the engineer's work too.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_audit(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, list[dict[str, Any]]]:
    """``(raw_stdout, parsed_audit)`` from the demo's OWN argument set: perform
    ``pla run`` into a private relative state dir, then ``pla explain --json`` over
    the slate it wrote -- the two commands the recipe chains."""
    root = tmp_path_factory.mktemp("iter207-demo")
    (root / STATE_DIR_NAME).mkdir()
    run_argv = [
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
    out, err = io.StringIO(), io.StringIO()
    with contextlib.chdir(root):
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(run_argv)
    assert rc == EXIT_OK, (
        "the demo's own run must exit 0 before its audit can be graded; "
        f"rc={rc}\nstdout={out.getvalue()!r}\nstderr={err.getvalue()!r}"
    )
    slate = root / STATE_DIR_NAME / "slate.json"
    assert slate.is_file(), f"the run must write {STATE_DIR_NAME}/slate.json; got {slate}"

    out2, err2 = io.StringIO(), io.StringIO()
    with contextlib.chdir(root):
        with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(err2):
            rc2 = main(["explain", "--slate", f"{STATE_DIR_NAME}/slate.json", "--json"])
    raw = out2.getvalue()
    assert rc2 == EXIT_OK, f"`pla explain --json` must exit 0; rc={rc2}\nstderr={err2.getvalue()!r}"
    audit = json.loads(raw)
    assert isinstance(audit, list) and audit, f"the audit must be a non-empty array; got {audit!r}"
    return raw, audit


# ---------------------------------------------------------------------------
# Behavior 1 -- the demo publishes the audit
# ---------------------------------------------------------------------------


def test_b1_demo_recipe_publishes_the_audit_after_the_run_step() -> None:
    """Spec behavior 1: the recipe gains EXACTLY ONE step producing the audit, it is
    the verbatim ``explain`` redirect, and it sits AFTER the ``pla run`` step."""
    recipe = _demo()
    assert len(recipe) == EXPECTED_DEMO_STEPS, (
        f"the demo recipe must be exactly {EXPECTED_DEMO_STEPS} logical steps "
        f"(mkdir, run, publish, grade, consumer); got {len(recipe)}: {recipe!r}"
    )
    publishers = [i for i, step in enumerate(recipe) if step == PUBLISH_STEP]
    assert len(publishers) == 1, (
        f"exactly one step must be {PUBLISH_STEP!r}; got {publishers!r} in {recipe!r}"
    )
    runners = [i for i, step in enumerate(recipe) if "pla run" in step]
    assert len(runners) == 1, f"exactly one step must invoke `pla run`; got {runners!r}"
    assert publishers[0] > runners[0], (
        "the audit is derived from the slate the run writes, so the publish step "
        f"must come AFTER it; publish={publishers[0]} run={runners[0]}: {recipe!r}"
    )


def test_b1_published_audit_is_a_json_array_of_objects(
    real_audit: tuple[str, list[dict[str, Any]]],
) -> None:
    """Spec behavior 1: what that step writes parses as a JSON array whose EVERY
    element is an object -- the shape the grader is contracted to consume."""
    _raw, audit = real_audit
    assert isinstance(audit, list), type(audit).__name__
    offenders = [(i, type(e).__name__) for i, e in enumerate(audit) if not isinstance(e, dict)]
    assert not offenders, f"every audit element must be an object; non-objects: {offenders!r}"
    for i, entry in enumerate(audit):
        missing = [k for k in REQUIRED_KEYS if k not in entry]
        assert not missing, f"entry {i} is missing {missing!r}; the grader reads those keys"


# ---------------------------------------------------------------------------
# Behavior 2 -- the grader passes on the shipped demo audit (real-artifact control)
# ---------------------------------------------------------------------------


def test_b2_grader_exits_zero_on_the_demos_own_audit(
    real_audit: tuple[str, list[dict[str, Any]]],
) -> None:
    """Spec behavior 2: exit 0 on the real audit, and ONE summary line on stdout."""
    raw, _audit = real_audit
    proc = _grade(raw)
    assert proc.returncode == EXIT_OK, (
        "the grader must accept the audit the demo itself publishes; "
        f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"exactly one summary line on stdout; got {proc.stdout!r}"


def test_b2_summary_line_names_the_three_counts(
    real_audit: tuple[str, list[dict[str, Any]]],
) -> None:
    """Spec behavior 2: the summary names goals audited, goals marked
    ``auto_dispatch``, and goals in a sensitive category -- each count re-derived
    here from the artifact, so the line cannot pass by printing three constants."""
    raw, audit = real_audit
    expected_total = len(audit)
    expected_auto = sum(1 for e in audit if e.get("decision") == AUTO)
    expected_sensitive = sum(1 for e in audit if e.get("category") in SENSITIVE)
    # The demo fixture is what makes the gate non-vacuous; if this ever stops
    # holding, the gate silently turns into theatre.
    assert expected_auto >= 1, f"the demo audit must contain an {AUTO} goal; got {audit!r}"
    assert expected_sensitive >= 1, f"the demo audit must contain a sensitive goal; {audit!r}"

    proc = _grade(raw)
    assert proc.returncode == EXIT_OK, proc.stderr
    line = [ln for ln in proc.stdout.splitlines() if ln.strip()][0]
    seen = _numbers(line)
    for label, count in (
        ("goals audited", expected_total),
        (f"goals marked {AUTO}", expected_auto),
        ("goals in a sensitive category", expected_sensitive),
    ):
        assert float(count) in seen, (
            f"the summary must name {label}={count}; numbers named were "
            f"{sorted(seen)!r} in {line!r}"
        )


# ---------------------------------------------------------------------------
# Behavior 3 -- a sensitive-category auto_dispatch is a violation at ANY score
# ---------------------------------------------------------------------------


def test_b3_sensitive_category_auto_dispatch_exits_one(tmp_path: Path) -> None:
    """Spec behavior 3: exit 1, and the message names that entry's ``id`` and its
    ``category``.  This is the product's headline safety claim."""
    audit = _good_audit()
    audit[1]["decision"] = AUTO
    proc = _grade_audit(tmp_path, audit)
    assert proc.returncode == EXIT_VIOLATION, (
        f"a sensitive-category goal marked {AUTO} must fail the gate; "
        f"rc={proc.returncode}\n{_messages(proc)}"
    )
    msg = _messages(proc)
    assert audit[1]["id"] in msg, f"the message must name the offending id; got {msg!r}"
    assert audit[1]["category"] in msg, f"the message must name the category; got {msg!r}"


def test_b3_control_the_same_audit_without_the_defect_exits_zero(tmp_path: Path) -> None:
    """Two-sided pairing for behavior 3: the identical payload with the ONE defect
    repaired must exit 0, so the arm above cannot pass against a grader that
    refuses everything."""
    proc = _grade_audit(tmp_path, _good_audit())
    assert proc.returncode == EXIT_OK, (
        f"the compliant control must pass; rc={proc.returncode}\n{_messages(proc)}"
    )


def test_b3_a_high_score_does_not_rescue_a_sensitive_auto_dispatch(tmp_path: Path) -> None:
    """Spec behavior 3 says "at any score": the sensitive rule is unconditional, so
    a score far ABOVE the threshold must still fail (it is the score that makes a
    sensitive goal tempting to auto-dispatch in the first place)."""
    audit = _good_audit()
    audit[1]["decision"] = AUTO
    audit[1]["score"] = 999.0
    proc = _grade_audit(tmp_path, audit)
    assert proc.returncode == EXIT_VIOLATION, (
        f"score must not override the sensitive rule; rc={proc.returncode}\n{_messages(proc)}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- an auto_dispatch below its own threshold is a violation
# ---------------------------------------------------------------------------


def test_b4_auto_dispatch_below_its_own_threshold_exits_one(tmp_path: Path) -> None:
    """Spec behavior 4: exit 1 naming the ``id``, the score and the threshold."""
    audit = _good_audit()
    audit[0]["score"] = MIN_SCORE - 0.5
    proc = _grade_audit(tmp_path, audit)
    assert proc.returncode == EXIT_VIOLATION, (
        f"an {AUTO} below threshold must fail; rc={proc.returncode}\n{_messages(proc)}"
    )
    msg = _messages(proc)
    assert audit[0]["id"] in msg, f"the message must name the offending id; got {msg!r}"
    named = _numbers(msg)
    assert MIN_SCORE - 0.5 in named, f"the message must name the score; numbers={sorted(named)!r}"
    assert MIN_SCORE in named, f"the message must name the threshold; numbers={sorted(named)!r}"


def test_b4_the_threshold_is_read_per_entry_not_from_the_product(tmp_path: Path) -> None:
    """Spec behavior 4 says "its own ``auto_dispatch_threshold``": the comparison is
    against the value the AUDIT publishes for that entry, so raising only that
    field turns a previously-compliant score into a violation."""
    audit = _good_audit()
    audit[0]["auto_dispatch_threshold"] = audit[0]["score"] + 1.0
    proc = _grade_audit(tmp_path, audit)
    assert proc.returncode == EXIT_VIOLATION, (
        "the per-entry threshold must be the one compared against; "
        f"rc={proc.returncode}\n{_messages(proc)}"
    )
    assert audit[0]["score"] + 1.0 in _numbers(_messages(proc)), _messages(proc)


def test_b4_control_score_exactly_at_the_threshold_exits_zero(tmp_path: Path) -> None:
    """Two-sided pairing, and the boundary the spec fixes with "strictly less":
    equality is COMPLIANT and must not be refused."""
    audit = _good_audit()
    audit[0]["score"] = MIN_SCORE
    proc = _grade_audit(tmp_path, audit)
    assert proc.returncode == EXIT_OK, (
        f"score == threshold is compliant; rc={proc.returncode}\n{_messages(proc)}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- a vacuous audit exits 1, never 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["empty_array", "no_auto_dispatch_entry", "no_sensitive_entry"],
)
def test_b5_a_vacuous_audit_exits_one(tmp_path: Path, label: str) -> None:
    """Spec behavior 5: an audit that cannot exercise the contract must FAIL, not
    pass.  Without this, a demo that stopped auto-dispatching anything, or stopped
    surfacing a sensitive goal, would turn the gate green by emptying it -- the
    exact way a passing gate becomes theatre."""
    if label == "empty_array":
        audit: list[dict[str, Any]] = []
    elif label == "no_auto_dispatch_entry":
        audit = [e for e in _good_audit() if e["decision"] != AUTO]
    else:
        audit = [e for e in _good_audit() if e["category"] not in SENSITIVE]
    proc = _grade_audit(tmp_path, audit, name=f"{label}.json")
    assert proc.returncode == EXIT_VIOLATION, (
        f"a vacuous audit ({label}) must exit 1, never 0; "
        f"rc={proc.returncode}\n{_messages(proc)}"
    )
    assert "cannot exercise" in _messages(proc), (
        "the message must say the audit cannot exercise the contract, so the "
        f"failure is not mistaken for a real violation; got {_messages(proc)!r}"
    )


def test_b5_control_the_non_vacuous_audit_exits_zero(tmp_path: Path) -> None:
    """Two-sided pairing for behavior 5: adding BOTH arms back makes the same
    grader pass, so the refusals above are about vacuity and not about the
    grader disliking synthetic input."""
    proc = _grade_audit(tmp_path, _good_audit())
    assert proc.returncode == EXIT_OK, f"rc={proc.returncode}\n{_messages(proc)}"


# ---------------------------------------------------------------------------
# Behavior 6 -- a missing required key exits 1, naming the key and the index
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_b6_a_missing_required_key_exits_one(tmp_path: Path, key: str) -> None:
    """Spec behavior 6: the offending index and the missing key are both named.

    The defect is planted on index 2 -- the spare row -- deliberately: defacing
    index 0 or 1 would ALSO empty a non-vacuity arm, so the refusal could not be
    attributed to the missing key.
    """
    audit = _good_audit()
    del audit[2][key]
    proc = _grade_audit(tmp_path, audit, name=f"missing_{key}.json")
    assert proc.returncode == EXIT_VIOLATION, (
        f"an entry missing {key!r} must exit 1; rc={proc.returncode}\n{_messages(proc)}"
    )
    msg = _messages(proc)
    assert re.search(rf"\b{re.escape(key)}\b", msg), (
        f"the message must name the missing key {key!r}; got {msg!r}"
    )
    assert "2" in msg, f"the message must name the offending index 2; got {msg!r}"


# ---------------------------------------------------------------------------
# Behavior 7 -- malformed stdin exits 2, and never as a traceback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("not_json", "this is not json"),
        ("empty_stdin", ""),
        ("truncated_array", "[{"),
        ("json_object", "{}"),
        ("json_string", '"an audit"'),
        ("json_number", "12"),
        ("array_of_scalars", "[1]"),
        ("object_then_scalar", '[{"id": "a"}, 7]'),
        ("array_of_null", "[null]"),
    ],
)
def test_b7_malformed_stdin_exits_two_without_a_traceback(label: str, payload: str) -> None:
    """Spec behavior 7: a MALFORMED input is exit 2 -- distinct from exit 1, which
    means "well-formed audit, contract violated" -- and no ``Traceback`` reaches
    stderr, because an unhandled exception is exit 1 in Python and would be
    indistinguishable from a real violation."""
    proc = _grade(payload)
    assert proc.returncode == EXIT_MALFORMED, (
        f"{label}: malformed stdin must exit {EXIT_MALFORMED} (not "
        f"{EXIT_VIOLATION}, which means a real violation); rc={proc.returncode}\n"
        f"{_messages(proc)}"
    )
    assert TRACEBACK not in proc.stderr, f"{label}: a crash must not be the error path:\n{proc.stderr}"
    assert _messages(proc).strip(), f"{label}: exit 2 must still say what was wrong"


def test_b7_the_three_exit_codes_are_distinct(tmp_path: Path) -> None:
    """Spec behaviors 2/3/7 read together: 0, 1 and 2 must be three DIFFERENT
    outcomes over the same grader, or the gate cannot tell "audit is fine" from
    "contract broken" from "input unreadable"."""
    ok = _grade_audit(tmp_path, _good_audit())
    violation = _good_audit()
    violation[1]["decision"] = AUTO
    bad = _grade_audit(tmp_path, violation, name="violation.json")
    malformed = _grade("{}")
    codes = (ok.returncode, bad.returncode, malformed.returncode)
    assert codes == (EXIT_OK, EXIT_VIOLATION, EXIT_MALFORMED), (
        f"expected (0, 1, 2) for (compliant, violation, malformed); got {codes!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 8 -- the sensitive set is DERIVED from the product, never spelled
# ---------------------------------------------------------------------------


def test_b8_grader_source_spells_no_category_literal() -> None:
    """Spec behavior 8: a grep of the grader for each sensitive category finds ZERO
    hits, so the policy cannot drift out of sync with the product by being copied."""
    source = GRADER.read_text(encoding="utf-8")
    for value in SENSITIVE:
        assert value not in source, (
            f"{GRADER.name} must not spell the category literal {value!r}; it must "
            "derive the sensitive set from the product (Settings.from_env())"
        )


def test_b8_changing_the_effective_set_changes_the_verdict(tmp_path: Path) -> None:
    """Spec behavior 8, the half that actually proves derivation: the SAME audit that
    exits 0 under the default policy must exit 1 once the effective sensitive set is
    changed -- with no edit to the grader.

    The audit's ``auto_dispatch`` entry sits in a SAFE category, so declaring that
    category sensitive makes the identical payload a behavior-3 violation.  Both
    non-vacuity arms still hold under the override (one auto_dispatch, and the
    now-sensitive category is present), so the exit 1 is the sensitive rule firing
    and not vacuity.
    """
    audit = _good_audit()
    baseline = _grade_audit(tmp_path, audit)
    assert baseline.returncode == EXIT_OK, (
        f"baseline must pass under the default policy; {_messages(baseline)}"
    )
    override = _grade_audit(
        tmp_path,
        audit,
        name="derived.json",
        env={"PLA_SENSITIVE_CATEGORIES": SAFE[0]},
    )
    assert override.returncode == EXIT_VIOLATION, (
        f"declaring {SAFE[0]!r} sensitive must change the verdict with no grader "
        f"edit; rc={override.returncode}\n{_messages(override)}"
    )
    assert SAFE[0] in _messages(override), _messages(override)
    assert audit[0]["id"] in _messages(override), _messages(override)


# ---------------------------------------------------------------------------
# Behavior 9 -- offline: stdlib plus the product, nothing else
# ---------------------------------------------------------------------------


def test_b9_grader_imports_only_stdlib_and_the_product() -> None:
    """Spec behavior 9, measured with ``ast`` rather than by reading prose: every
    imported top-level module is either in the standard library or ``proactive_loop``.
    A third-party import here would also break CI's ``uv sync --locked``."""
    tree = ast.parse(GRADER.read_text(encoding="utf-8"), filename=str(GRADER))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # a relative import inside examples/ is not importable
                raise AssertionError(f"relative import in {GRADER.name}: level={node.level}")
            roots.add((node.module or "").split(".")[0])
    allowed = set(sys.stdlib_module_names) | {"proactive_loop"}
    offenders = sorted(r for r in roots if r and r not in allowed)
    assert not offenders, (
        f"{GRADER.name} may import only the stdlib and proactive_loop; got {offenders!r}"
    )
    assert "proactive_loop" in roots, (
        "the grader must import the product -- that IS how it derives the policy "
        f"(behavior 8); imports found: {sorted(roots)!r}"
    )


@pytest.mark.parametrize("token", NETWORK_TOKENS)
def test_b9_grader_source_carries_no_network_or_subprocess_token(token: str) -> None:
    """Spec behavior 9: offline-first is a hard product constraint, so the grader's
    source must not even name a network or subprocess entry point."""
    source = GRADER.read_text(encoding="utf-8")
    assert token not in source, f"{GRADER.name} must not name {token!r} (offline-first)"


def test_b9_runtime_dependency_set_is_still_pydantic_only() -> None:
    """Spec behavior 9 and the Out-of-Scope list: no dependency change, so CI's
    ``uv sync --locked`` cannot drift.  Asserted on the declared runtime set --
    the durable, fresh-clone-safe form of "``pyproject.toml`` is untouched"."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    roots = sorted(re.split(r"[<>=!~\[ ]", d, maxsplit=1)[0] for d in deps)
    assert roots == ["pydantic"], f"the runtime dependency set must stay pydantic-only; got {deps!r}"


# ---------------------------------------------------------------------------
# Behavior 10 -- the new gate reaches CI through `make demo` only
# ---------------------------------------------------------------------------


def test_b10_ci_workflow_gains_no_step_of_its_own() -> None:
    """Spec behavior 10: the gate rides CI's existing ``make demo`` step.  A second
    invocation would double the runtime and give the gate two definitions.

    Widened factory iter 276 from a substring ban to an INVOCATION ban plus a
    whitelist of the one NAMING site -- see ``_invokes``.  The claim is unchanged
    (nothing but ``make demo`` may RUN the grader in CI) and it is now asserted in
    two directions, so the type oracle may cite the grader as a file to check while
    a second ``run:`` step that executes it is still red.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert not _invokes(workflow, GRADER_NAME), (
        "the autonomy gate must reach CI via the existing `make demo` step, not a "
        "new `run:` step that invokes the grader itself"
    )
    naming = [
        line.split("run:", 1)[1].strip()
        for line in workflow.splitlines()
        if line.lstrip().startswith("run:") and "check_autonomy" in line
    ]
    assert all(command.startswith("uv run mypy ") for command in naming), (
        "the only CI step allowed to NAME the grader is the static type oracle; got "
        f"{naming!r}"
    )
    assert "make demo" in workflow, "CI must still run `make demo`, which is the gate's only route"


def test_b10_make_check_gains_no_step_of_its_own() -> None:
    """Spec behavior 10: ``make check`` must not grow a step either -- it already
    runs the demo, so a direct invocation would be a second definition.  Same iter-276
    widening as the CI guard above: an invocation ban, plus the type oracle as the one
    permitted naming site.
    """
    steps = _recipe("check")
    invoking = [s for s in steps if _invokes(s, GRADER_NAME)]
    assert not invoking, f"`make check` must not invoke the grader directly; got {invoking!r}"
    naming = [s for s in steps if "check_autonomy" in s]
    assert all(s.startswith("uv run mypy ") for s in naming), (
        "inside `make check` the grader may be NAMED only by the static type oracle, "
        f"never run as a step of its own; got {naming!r}"
    )


def test_b10_the_invocation_ban_is_not_vacuous() -> None:
    """Anti-vacuity control for the two guards above, added factory iter 276 with the
    widening itself: a ban is worthless if its discriminator matches nothing.

    The positive arm is the REAL step -- the demo recipe's own grader invocation, read
    from the shipped ``Makefile`` -- and the negative arm is the type-oracle spelling,
    which names the same path as a file to CHECK.  Both live in the shipped tree, so
    this control moves with them rather than with a hand-typed sample.
    """
    invocation = f"uv run python {GRADER_NAME} < {STATE_DIR_NAME}/{AUDIT_NAME}"
    assert invocation in _demo(), (
        f"the demo recipe must still invoke the grader as {invocation!r}; got {_demo()!r}"
    )
    assert _invokes(invocation, GRADER_NAME), (
        "the discriminator must MATCH the real invocation, or both bans above are "
        f"vacuous: {invocation!r}"
    )
    assert not _invokes(f"uv run mypy src/proactive_loop {GRADER_NAME}", GRADER_NAME), (
        "naming the grader as an input to a static type checker is not an invocation, "
        "so the type oracle may cite it"
    )


def test_b10_the_consumer_is_still_the_demos_last_step() -> None:
    """Spec behavior 10, verbatim: the recipe's LAST step is unchanged.  The two new
    steps are INSERTED before it, so ``check_run.py``'s exit status stays the demo's
    final word -- the invariant ``test_iter198``/``test_iter199`` pin."""
    recipe = _demo()
    assert recipe[-1] == CONSUMER_STEP, (
        f"the LAST demo step must still be exactly {CONSUMER_STEP!r}; got {recipe[-1]!r}"
    )


def test_b10_the_grader_runs_between_the_publish_step_and_the_consumer() -> None:
    """Spec behaviors 1, 2 and 10 read together as an ORDER: publish the audit, grade
    it, then grade the run document.  Grading before publishing would read a stale
    artifact (or none at all in a fresh checkout)."""
    recipe = _demo()
    graders = [i for i, step in enumerate(recipe) if GRADER_NAME in step]
    assert len(graders) == 1, f"exactly one step must invoke {GRADER_NAME}; got {graders!r}"
    step = recipe[graders[0]]
    assert f"{STATE_DIR_NAME}/{AUDIT_NAME}" in step, (
        f"the grader step must read {STATE_DIR_NAME}/{AUDIT_NAME}; got {step!r}"
    )
    publish = recipe.index(PUBLISH_STEP)
    assert publish < graders[0] < len(recipe) - 1, (
        "order must be publish -> grade the audit -> consumer last; "
        f"publish={publish} grade={graders[0]} of {len(recipe)}: {recipe!r}"
    )


def test_b10_the_grader_step_is_not_a_pipeline() -> None:
    """``test_iter198``'s own recorded reason the run document is a FILE: a shell
    pipeline masks the left-hand exit status under make's ``/bin/sh``, so a piped
    grader could fail silently.  The audit is a file and the grader reads it."""
    recipe = _demo()
    step = next(s for s in recipe if GRADER_NAME in s)
    assert "|" not in step, f"the grader must not be piped (its exit status is the gate); {step!r}"
    assert "<" in step, f"the grader must read the audit FILE on stdin; got {step!r}"
