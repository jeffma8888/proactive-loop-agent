"""Black-box behavior tests for state-dir iteration 175 (ships as ``factory iter 179``).

Feature under test: ``pla run --snapshot FILE`` (roadmap #213) -- the autonomous
verb can persist the perception record it collected, so the slate ``make demo``
and CI publish becomes checkable by ``pla verify`` instead of being a claim with
no evidence. Before this, ``scan --snapshot`` (row #200) could produce the
document and ``verify`` (row #201) could consume it, but the ONLY verb any gate
site invokes could not write one -- the newest feature was unreachable from the
dominant entry point.

MODULE NAME. This repo names behavior modules by the FACTORY iteration number,
which runs ahead of the state-dir counter (``tests/test_iter109_behavior.py`` and
``tests/test_iter177_behavior.py`` both document the same offset for themselves).
``git ls-files`` shows ``test_iter174/175/176/177/178_behavior.py`` all TRACKED
and ``test_iter179_behavior.py`` absent, so 179 is the free name -- checked with
``git ls-files`` BEFORE the first write, because taking a module name from prose
is what destroyed 14,889 bytes of shipped oracles in state-dir iter 174.

WHY A REAL SUBPROCESS. Behaviors 4, 5 and 7 are claims about whole streams (an
UNCHANGED stdout, an EMPTY stdout beside exactly one ``error:`` line, stdout
parsing as exactly ONE JSON object). ``capsys`` cannot falsify those honestly, so
this module spends real ``pla`` console-script invocations -- the
iter-114 / iter-152 / iter-163 / iter-177 convention. Cost is bounded: the
happy-path behaviors share ONE module-scoped run, behavior 4 shares one
module-scoped triple, and every invocation is offline (bundled scripted provider,
no network, no API key).

HOW BEHAVIOR 4 IS READ, AND WHY IT IS NOT LITERAL. The spec asks for stdout
"byte-identical to the same invocation before this change". A test cannot invoke
the pre-change tree, so the testable reading is the one that actually protects a
caller: adding the flag must not change what the PLAIN invocation prints. Two
masked quantities make that decidable, and both were forced on us by MEASUREMENT,
not assumed -- two runs of the *same plain command* already differ, because goal
ids are freshly generated per synthesis and the run dir is named for a fresh id,
and the state-dir path is echoed on four lines. So every comparison masks
12-hex ids and the state-dir path, and every comparison is preceded by a
PLAIN-vs-PLAIN CONTROL in the same test: if the control fails the mask is
insufficient and the fixture is the variable, which is a different bug from a
regression in the flag.

ISOLATION CONTRACT (honored, no exception). Every assertion here is derived from
this iteration's spec ("Expected Behaviors" in ``pm.md``), from the repo's own
``tests/`` conventions, from ``README.md``, and from the product's OBSERVABLE
output obtained by RUNNING it. **No file under ``src/`` was read, no ``git diff``
was inspected, and neither ``engineer.md`` nor ``reviewer.md`` was opened.**
Every invocation is rooted at a PRIVATE COPY of ``examples/fixture_workspace``
under a ``tmp_path_factory`` dir (the iter-142 shared-mutable-tree hazard).
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"
README = REPO / "README.md"

# Spec behavior 1: the snapshot document is a CLOSED shape.
_DOC_KEYS = frozenset({"workspace_root", "signals"})
_SIGNAL_KEYS = frozenset({"source", "kind", "summary", "detail", "path", "weight"})

# Acceptance criterion: `--snapshot` belongs to these verbs and NO others.
_SNAPSHOT_VERBS = frozenset({"run", "scan", "verify"})

# Behavior 4: the two measured sources of legitimate run-to-run variation.
_HEX12 = re.compile(r"\b[0-9a-f]{12}\b")

# Behavior 3: the refusal that must NOT appear once `run` can write the document.
_NOT_FOUND = "snapshot file not found"

# The README marker is copied VERBATIM from the file (it uses an EM DASH; a
# retyped ASCII double-hyphen finds nothing and reads as a clean scan).
_README_MARKER = "PORTFOLIO INTRO — human-owned"


# ---------------------------------------------------------------------------
# Helpers (iter-114 / iter-152 / iter-163 / iter-177 console-script convention)
# ---------------------------------------------------------------------------


def _console_script() -> Path:
    """The installed ``pla`` console script."""
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, (
        "the `pla` console script must be installed (declared in pyproject and "
        f"installed by `uv sync`); searched {[str(c) for c in candidates]}"
    )
    return script


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the real CLI in its own process so stdout/stderr are real fds."""
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=180,
    )


def _base_run_args(ws: Path, state: Path) -> list[str]:
    """The offline ``run`` invocation every behavior starts from."""
    return [
        "run",
        "--workspace",
        str(ws),
        "--state-dir",
        str(state),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
    ]


def _private_workspace(root: Path) -> Path:
    """A per-module copy of the bundled fixture, never the shared tree."""
    ws = root / "workspace"
    shutil.copytree(FIXTURE, ws)
    return ws


def _run_dirs(state: Path) -> list[Path]:
    if not state.is_dir():
        return []
    return sorted(p for p in state.glob("run-*") if p.is_dir())


def _mask(text: str, state: Path) -> str:
    """Erase the two MEASURED sources of run-to-run variation, nothing else."""
    return _HEX12.sub("<ID>", text.replace(str(state), "<STATE>"))


def _residual(left: str, right: str) -> str:
    """A printable diff, so an equality failure carries evidence, not a boolean."""
    lines = list(
        difflib.unified_diff(
            left.splitlines(), right.splitlines(), fromfile="left", tofile="right", lineterm="", n=0
        )
    )
    return "\n".join(lines[:24])


def _err_lines(proc: subprocess.CompletedProcess[str]) -> list[str]:
    return [ln for ln in proc.stderr.splitlines() if ln.strip()]


def _assert_nothing_produced(state: Path, snap: Path, *, where: str) -> None:
    """Spec behavior 5: the refusal precedes every collect / LLM / write step."""
    assert not snap.exists(), f"{where}: no snapshot file may be written; {snap} exists"
    assert not (state / "slate.json").exists(), f"{where}: no slate may be written under {state}"
    assert _run_dirs(state) == [], f"{where}: no run-<id>/ dir may be created under {state}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def flagged(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """ONE ``run --snapshot`` over a private fixture copy; shared by behaviors 1-3."""
    root = tmp_path_factory.mktemp("run_snapshot")
    ws = _private_workspace(root)
    state = root / "state"
    snap = root / "snap.json"
    proc = _run(*_base_run_args(ws, state), "--snapshot", str(snap), cwd=root)
    assert proc.returncode == 0, (
        f"`run --snapshot` must exit 0 offline; rc={proc.returncode} stderr={proc.stderr!r}"
    )
    return {"root": root, "ws": ws, "state": state, "snap": snap}


@pytest.fixture(scope="module")
def unchanged(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Behavior 4's triple: TWO plain runs (the control) and one flagged run.

    Three separate state dirs so no run can observe another's leftovers; the
    state-dir path is masked out of every comparison for exactly that reason.
    """
    root = tmp_path_factory.mktemp("run_unchanged")
    ws = _private_workspace(root)
    out: dict[str, object] = {"root": root, "ws": ws}
    for name in ("plain_a", "plain_b"):
        state = root / name
        proc = _run(*_base_run_args(ws, state), cwd=root)
        assert proc.returncode == 0, f"plain `run` must exit 0; stderr={proc.stderr!r}"
        out[name] = _mask(proc.stdout, state)
        out[f"{name}_state"] = state
        out[f"{name}_raw"] = proc.stdout
    state_f = root / "flagged"
    snap = root / "unchanged-snap.json"
    proc = _run(*_base_run_args(ws, state_f), "--snapshot", str(snap), cwd=root)
    assert proc.returncode == 0, f"`run --snapshot` must exit 0; stderr={proc.stderr!r}"
    out["flagged"] = _mask(proc.stdout, state_f)
    out["flagged_state"] = state_f
    out["snap"] = snap
    return out


# ==========================================================================
# Behavior 1 -- the flag writes a closed, signals-shaped document
# ==========================================================================


def test_b01_snapshot_file_is_a_regular_file_with_exactly_two_top_level_keys(
    flagged: dict[str, Path],
) -> None:
    snap = flagged["snap"]
    assert snap.is_file(), f"--snapshot must write a regular file at {snap}"
    doc = json.loads(snap.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), f"snapshot must be a JSON object, got {type(doc).__name__}"
    assert set(doc) == _DOC_KEYS, (
        f"snapshot top-level keys must be exactly {sorted(_DOC_KEYS)}; got {sorted(doc)}"
    )


def test_b01_signals_is_a_non_empty_list_of_six_key_entries(flagged: dict[str, Path]) -> None:
    doc = json.loads(flagged["snap"].read_text(encoding="utf-8"))
    signals = doc["signals"]
    assert isinstance(signals, list) and signals, f"signals must be a NON-EMPTY list; got {signals!r}"
    for i, entry in enumerate(signals):
        assert isinstance(entry, dict), f"signals[{i}] must be an object, got {entry!r}"
        assert set(entry) == _SIGNAL_KEYS, (
            f"signals[{i}] keys must be exactly {sorted(_SIGNAL_KEYS)}; got {sorted(entry)}"
        )


def test_b01_workspace_root_names_the_scanned_workspace(flagged: dict[str, Path]) -> None:
    """The record must identify WHAT was perceived, or it cannot be audited."""
    doc = json.loads(flagged["snap"].read_text(encoding="utf-8"))
    root = doc["workspace_root"]
    assert isinstance(root, str) and root, f"workspace_root must be a non-empty string; got {root!r}"
    assert Path(root).name == Path(flagged["ws"]).name, (
        f"workspace_root {root!r} must name the scanned workspace {str(flagged['ws'])!r}"
    )


# ==========================================================================
# Behavior 2 -- --snapshot is additive: it removes nothing
# ==========================================================================


def test_b02_flag_removes_no_existing_artifact(flagged: dict[str, Path]) -> None:
    state = flagged["state"]
    assert (state / "slate.json").is_file(), "run --snapshot must still write S/slate.json"
    runs = _run_dirs(state)
    assert len(runs) == 1, f"expected exactly one run-<id>/ dir under {state}; got {runs}"
    run = runs[0]
    assert (run / "checkpoint.json").is_file(), f"{run.name}/checkpoint.json must exist"
    assert (run / "meta.json").is_file(), f"{run.name}/meta.json must exist"
    arts = sorted((run / "artifacts").glob("*.md"))
    assert arts, f"{run.name}/artifacts/ must hold at least one .md; found {arts}"


# ==========================================================================
# Behavior 3 -- the round trip the whole feature exists for: run -> verify
# ==========================================================================


def test_b03_verify_accepts_the_pair_run_produced(flagged: dict[str, Path]) -> None:
    proc = _run(
        "verify",
        "--slate",
        str(flagged["state"] / "slate.json"),
        "--snapshot",
        str(flagged["snap"]),
        cwd=flagged["root"],
    )
    assert proc.returncode == 0, f"verify must exit 0 on a run-produced pair; stderr={proc.stderr!r}"
    offenders = [
        ln for ln in (proc.stdout + "\n" + proc.stderr).splitlines() if ln.startswith("error:")
    ]
    assert offenders == [], f"no line may start with 'error:'; got {offenders}"
    assert _NOT_FOUND not in proc.stdout + proc.stderr, (
        f"the {_NOT_FOUND!r} refusal must be gone now that `run` writes the document"
    )


def test_b03_verify_json_reports_at_least_one_source_and_an_integer_unresolved_count(
    flagged: dict[str, Path],
) -> None:
    proc = _run(
        "verify",
        "--slate",
        str(flagged["state"] / "slate.json"),
        "--snapshot",
        str(flagged["snap"]),
        "--json",
        cwd=flagged["root"],
    )
    assert proc.returncode == 0, f"verify --json must exit 0; stderr={proc.stderr!r}"
    doc = json.loads(proc.stdout)
    assert doc["source_count"] >= 1, f"source_count must be >= 1; got {doc['source_count']!r}"
    unresolved = doc["unresolved_count"]
    # bool is an int subclass; an accidental True must not satisfy this.
    assert isinstance(unresolved, int) and not isinstance(unresolved, bool), (
        f"unresolved_count must be an integer; got {unresolved!r} ({type(unresolved).__name__})"
    )
    # Deliberately NOT `== 0`: several collectors are mtime-driven and post-release
    # verification runs in a FRESH CLONE (the documented fresh-clone trap).
    assert unresolved >= 0, f"unresolved_count must be non-negative; got {unresolved!r}"


# ==========================================================================
# Behavior 4 -- default off: omitting the flag changes nothing
# ==========================================================================


def test_b04_control_two_plain_runs_agree_once_ids_and_state_path_are_masked(
    unchanged: dict[str, object],
) -> None:
    """The CONTROL. If this fails the MASK is insufficient, not the feature."""
    a, b = unchanged["plain_a"], unchanged["plain_b"]
    assert isinstance(a, str) and a.strip(), "plain stdout must be non-empty (an empty compare is vacuous)"
    assert a == b, (
        "two runs of the SAME plain command must agree after masking 12-hex ids and "
        f"the state-dir path; residual diff:\n{_residual(a, b)}"
    )


def test_b04_adding_the_flag_does_not_change_plain_stdout(unchanged: dict[str, object]) -> None:
    plain, flag = unchanged["plain_a"], unchanged["flagged"]
    assert plain == flag, (
        "`run --snapshot` stdout must match the plain invocation's after masking; "
        f"residual diff:\n{_residual(str(plain), str(flag))}"
    )
    assert len(str(unchanged["plain_a_raw"])) > 0, "control: plain stdout bytes must be non-zero"


def test_b04_plain_run_writes_no_snapshot_file_and_never_mentions_one(
    unchanged: dict[str, object],
) -> None:
    state = unchanged["plain_a_state"]
    assert isinstance(state, Path)
    stray = sorted(str(p.relative_to(state)) for p in state.rglob("snapshot*.json"))
    assert stray == [], f"no snapshot*.json may appear under {state} without the flag; found {stray}"
    assert "--snapshot" not in str(unchanged["plain_a"]), (
        "the plain invocation must not print the flag it was not given"
    )


# ==========================================================================
# Behavior 5 -- the target is guarded BEFORE any collect or LLM call
# ==========================================================================


def test_b05_snapshot_pointing_at_a_directory_is_refused_on_one_stderr_line(
    tmp_path: Path,
) -> None:
    ws = _private_workspace(tmp_path)
    target = tmp_path / "already-a-dir"
    target.mkdir()
    state = tmp_path / "state5a"
    proc = _run(*_base_run_args(ws, state), "--snapshot", str(target), cwd=tmp_path)
    assert proc.returncode == 2, f"a directory target must exit 2; got {proc.returncode}"
    assert proc.stdout == "", f"stdout must stay EMPTY on a refusal; got {proc.stdout!r}"
    assert _err_lines(proc) == [f"error: --snapshot is a directory: {target}"], (
        f"exactly one exact stderr line expected; got {_err_lines(proc)}"
    )
    _assert_nothing_produced(state, target / "unused.json", where="directory target")


def test_b05_snapshot_whose_parent_chain_hits_a_regular_file_is_refused(tmp_path: Path) -> None:
    ws = _private_workspace(tmp_path)
    blocker = tmp_path / "not-a-dir.txt"
    blocker.write_text("i am a regular file\n", encoding="utf-8")
    snap = blocker / "nested" / "snap.json"
    state = tmp_path / "state5b"
    proc = _run(*_base_run_args(ws, state), "--snapshot", str(snap), cwd=tmp_path)
    assert proc.returncode == 2, f"a file in the parent chain must exit 2; got {proc.returncode}"
    assert proc.stdout == "", f"stdout must stay EMPTY on a refusal; got {proc.stdout!r}"
    assert _err_lines(proc) == [f"error: --snapshot parent is not a directory: {blocker}"], (
        f"exactly one exact stderr line expected; got {_err_lines(proc)}"
    )
    _assert_nothing_produced(state, snap, where="file in parent chain")
    assert blocker.read_text(encoding="utf-8") == "i am a regular file\n", (
        "the refusal must not touch the file that blocked the path"
    )


# ==========================================================================
# Behavior 6 -- --dry-run still records what it perceived
# ==========================================================================


def test_b06_dry_run_writes_snapshot_and_slate_but_no_run_dir(tmp_path: Path) -> None:
    ws = _private_workspace(tmp_path)
    state = tmp_path / "state6"
    snap = tmp_path / "dry.json"
    proc = _run(*_base_run_args(ws, state), "--dry-run", "--snapshot", str(snap), cwd=tmp_path)
    assert proc.returncode == 0, f"`run --dry-run --snapshot` must exit 0; stderr={proc.stderr!r}"
    assert snap.is_file(), "--dry-run must still write the snapshot (perception precedes synthesis)"
    assert (state / "slate.json").is_file(), "--dry-run must still write the slate"
    assert _run_dirs(state) == [], f"--dry-run must create NO run-<id>/ dir; got {_run_dirs(state)}"
    doc = json.loads(snap.read_text(encoding="utf-8"))
    assert set(doc) == _DOC_KEYS, f"the dry-run snapshot must be the same shape; got {sorted(doc)}"
    assert doc["signals"], "the dry-run snapshot must not be empty"


# ==========================================================================
# Behavior 7 -- the --json contract gains no key
# ==========================================================================


def test_b07_json_key_set_is_identical_with_and_without_the_flag(tmp_path: Path) -> None:
    ws = _private_workspace(tmp_path)
    snap = tmp_path / "json.json"
    plain = _run(*_base_run_args(ws, tmp_path / "state7a"), "--json", cwd=tmp_path)
    flag = _run(*_base_run_args(ws, tmp_path / "state7b"), "--json", "--snapshot", str(snap), cwd=tmp_path)
    assert plain.returncode == 0 and flag.returncode == 0, (
        f"both --json runs must exit 0; got {plain.returncode} / {flag.returncode}"
    )
    plain_doc = json.loads(plain.stdout)
    flag_doc = json.loads(flag.stdout)
    assert isinstance(flag_doc, dict), "stdout must be exactly one JSON object"
    assert set(plain_doc), "control: the plain --json document must not be empty"
    assert set(flag_doc) == set(plain_doc), (
        "`run --json --snapshot` must add NO top-level key (the row #186 contract); "
        f"plain={sorted(plain_doc)} flagged={sorted(flag_doc)}"
    )
    assert snap.is_file(), "--json --snapshot must still write the snapshot file"


# ==========================================================================
# Acceptance criteria with observable oracles
# ==========================================================================


def test_ac_snapshot_is_owned_by_exactly_run_scan_and_verify(flagged: dict[str, Path]) -> None:
    """Flag OWNERSHIP measured PER SUBPARSER -- flag EXISTENCE is the blind spot.

    ``flag_universe``/``missing_flags`` in ``test_readme_and_ci_contract.py`` only
    asks whether a LIVE flag is documented somewhere, so ``--snapshot`` missing
    from ``run`` stayed green for two rows. This asks the ownership question.
    """
    parser = build_parser()
    subs = [
        a
        for a in parser._subparsers._group_actions  # noqa: SLF001 -- repo convention
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(subs) == 1, f"expected exactly one subparser action, got {len(subs)}"
    owners = {
        verb
        for verb, sub in subs[0].choices.items()
        if any("--snapshot" in (a.option_strings or []) for a in sub._actions)  # noqa: SLF001
    }
    assert owners == set(_SNAPSHOT_VERBS), (
        f"--snapshot must be declared on exactly {sorted(_SNAPSHOT_VERBS)}; got {sorted(owners)}"
    )


def test_ac_run_help_names_the_flag_with_a_file_metavar(flagged: dict[str, Path]) -> None:
    proc = _run("run", "--help", cwd=flagged["root"])
    assert proc.returncode == 0, f"`run --help` must exit 0; got {proc.returncode}"
    assert "--snapshot" in proc.stdout, "`run --help` must name --snapshot"
    assert re.search(r"--snapshot\s+FILE", proc.stdout), (
        "`run --help` must show a FILE metavar for --snapshot; "
        f"help text was:\n{proc.stdout[:800]}"
    )


def test_ac_readme_documents_the_flag_on_the_run_row_below_the_human_owned_marker() -> None:
    text = README.read_text(encoding="utf-8")
    marker_at = text.find(_README_MARKER)
    assert marker_at != -1, f"the human-owned marker {_README_MARKER!r} must be present verbatim"
    rows = [ln for ln in text.splitlines() if ln.startswith("| `run`")]
    assert len(rows) == 1, f"expected exactly one CLI table row for `run`; got {len(rows)}"
    row = rows[0]
    assert "--snapshot" in row, f"the README `run` row must document --snapshot; row was:\n{row}"
    assert text.index(row) > marker_at, (
        "the `run` row must sit BELOW the human-owned portfolio-intro marker"
    )
