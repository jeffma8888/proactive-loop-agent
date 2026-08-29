"""Black-box behavior tests for state-dir iteration 233 (ships as ``foundry iter 233``):
``pla scan --exclude-path GLOB`` -- the perception INPUT filter reaches the verb that
actually feeds synthesis.

Feature under test: ``scan`` gains the repeatable path-glob exclusion that ``signals``
already ships, applied to the collected snapshot BEFORE the bounded synthesis prompt and
before ``--snapshot`` is written.  The point of the feature is that ``synthesizer.py``
slices a fixed number of signals per kind, so on a real repo a vendored / generated /
settled-history subtree can crowd live findings out of the prompt with no way for a user
to say so.  ``signals`` (preview) could already be narrowed; ``scan`` (the verb whose
output the human acts on) could not.

MODULE NAME -- derived from the REPO, never from the state-dir number.  ``git ls-files
tests`` holds 206 ``test_iterNN_behavior.py`` modules with the highest at **211**, so 212
is the next free name, and ``git cat-file -e HEAD:tests/test_iter212_behavior.py`` FAILED
(``does not exist in 'HEAD'``) before the first byte was written.  Taking the name from
the state-dir counter is what overwrote a shipped 18,786-byte oracle in state-dir 186.

ISOLATION CONTRACT (honored, no exception).  Every assertion below is derived from this
iteration's spec (``pm.md`` "Expected Behaviors" 1-8), from the conventions of the
existing modules under ``tests/`` (``test_iter155_behavior.py`` is the shipped
``signals --exclude-path`` module and its fixture recipes -- the markdown TODO body and
the hand-written stash reflog -- are reused; ``test_iter179_behavior.py`` is the shipped
``--snapshot`` module and its offline console-script harness is reused), and from the
product's OBSERVABLE output obtained by RUNNING it.  **No file under ``src/`` was read,
no ``git diff`` was inspected, and neither ``engineer.md`` nor ``reviewer.md`` was
opened.**  The one flag description quoted below was read from ``pla scan --help``, which
is output, not source.

OFFLINE AND DETERMINISTIC.  Every invocation uses the bundled scripted provider
(``--provider scripted --scripted-responses examples/scripted_responses.json``): no
network, no API key.  Every workspace is a PRIVATE ``tmp_path_factory`` copy of the
tracked ``examples/fixture_workspace`` plus a synthetic ``vendor/`` subtree -- never the
ambient repo tree, whose signal count and gitignored paths differ in a fresh clone (the
iter-154 fresh-clone trap), and never the shared fixture in place (the iter-142
shared-mutable-tree hazard).  No duration is asserted.  Every ``--state-dir`` lives
OUTSIDE the scanned workspace so the run's own artifacts cannot become perception input.

NON-VACUITY IS ASSERTED, NOT ASSUMED.  Every exclusion test first asserts from the
unfiltered baseline that the tree really does hold both an excluded-subtree signal and a
survivor, so a fixture that stopped producing signals fails loudly instead of passing an
emptied set against an emptied set.  Behavior 4 additionally asserts the pattern dropped
at least one signal, which the spec requires explicitly.

AMBIGUITY NOTES (PM feedback):

* Behavior 2 asks for stdout "byte-identical to the pre-change path".  A test cannot
  invoke the pre-change tree, so the testable reading -- the one that actually protects a
  caller -- is asserted instead: with the flag ABSENT the snapshot document is exactly
  what the unfiltered perception layer reports, element for element in order, which is
  the same claim without the unreachable comparison.  ``test_iter179_behavior.py`` reached
  the same reading for the same wording and is followed here.
* Behavior 6 says the refusal is "identical to the ``signals`` verb's for the same
  input".  The two streams cannot be equal in full -- argparse prefixes each with its own
  ``prog`` (``pla scan: error:`` vs ``pla signals: error:``) and prints a per-verb usage
  block -- so what is asserted is equality of the message AFTER the ``error:`` marker,
  which is the part the shared validator owns.
* Behavior 6's "no slate file and no snapshot file are written" is asserted for the empty
  pattern through a real subprocess (a parser-level check cannot observe the filesystem),
  while the whitespace-only variant and the cross-verb message equality are driven
  through ``build_parser()`` in-process, which keeps the stage's subprocess budget for the
  claims that genuinely need a real process.
* Help-text matching is whitespace-normalised on purpose: Python 3.13 strips the common
  leading indent of a docstring at compile time and 3.12 does not, and argparse re-wraps
  help strings to the terminal width, so asserting literal indentation is a known
  version-dependent breakage.
"""

from __future__ import annotations

import argparse
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

# The shared `_nonempty_glob` refusal, quoted from the spec's behavior 6.
_GLOB_REFUSAL = "must be a non-empty path glob"

# The default (`table`) format's trailer, per behavior 8.
_TRAILER = "slate written:"

# The snapshot document is a CLOSED shape (the shipped `--snapshot` contract).
_DOC_KEYS = frozenset({"workspace_root", "signals"})

# The excluded subtree every fixture carries, and the glob that names it.
_VENDOR = "vendor/"
_VENDOR_GLOB = "vendor/*"


# ---------------------------------------------------------------------------
# Harness -- drive the shipped console script, read observable output only.
# ---------------------------------------------------------------------------


def _console_script() -> Path:
    """The installed ``pla`` console script (the iter-114/152/179 convention)."""
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


def _scan(ws: Path, state: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """An offline ``scan`` rooted at ``ws``; paths render relative to ``--workspace``."""
    return _run(
        "scan",
        "--workspace",
        ".",
        "--state-dir",
        str(state),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        *extra,
        cwd=ws,
    )


def _signals(ws: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run("signals", "--workspace", ".", *extra, cwd=ws)


def _records(ws: Path, *extra: str) -> list[dict]:
    """The unfiltered-or-filtered perception records as ``signals --json`` reports them."""
    proc = _signals(ws, "--json", *extra)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    doc = json.loads(proc.stdout)
    assert set(doc) == _DOC_KEYS, sorted(doc)
    return list(doc["signals"])


def _snapshot(path: Path) -> list[dict]:
    """The signals recorded by ``--snapshot FILE``."""
    assert path.is_file(), f"--snapshot must have written {path}"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert set(doc) == _DOC_KEYS, sorted(doc)
    return list(doc["signals"])


def _snapshot_doc(path: Path) -> dict:
    """The WHOLE ``--snapshot`` document, for the fields that are not signals."""
    assert path.is_file(), f"--snapshot must have written {path}"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert set(doc) == _DOC_KEYS, sorted(doc)
    return doc


def _paths(records: list[dict]) -> list[str | None]:
    return [r["path"] for r in records]


def _triples(records: list[dict]) -> set[tuple[str, str | None, str]]:
    """The spec's behavior-4 identity key: ``(kind, path, summary)``."""
    return {(r["kind"], r["path"], r["summary"]) for r in records}


def _under_vendor(paths: list[str | None]) -> list[str]:
    return [p for p in paths if p is not None and p.startswith(_VENDOR)]


def _norm(text: str) -> str:
    """Whitespace-normalised, for argparse-rewrapped help text."""
    return re.sub(r"\s+", " ", text).strip()


def _error_tail(stderr: str) -> str:
    """The part of an argparse refusal AFTER ``error:`` -- the verb-independent half."""
    marker = "error:"
    assert marker in stderr, f"expected an argparse refusal; stderr={stderr!r}"
    return _norm(stderr.split(marker, 1)[1])


# ---------------------------------------------------------------------------
# Fixtures -- private copies of the tracked fixture workspace, plus a vendored
# subtree that the exclusion is supposed to remove.
# ---------------------------------------------------------------------------

_TODO_FILLER = "\n".join(f"line {i}" for i in range(1, 12))
_TODO_BODY = _TODO_FILLER + "\n- TODO: alpha here\n- TODO: beta here\n"


def _private_workspace(root: Path) -> Path:
    """A per-module copy of the bundled fixture with a synthetic ``vendor/`` subtree."""
    ws = root / "workspace"
    shutil.copytree(FIXTURE, ws)
    (ws / "vendor" / "lib").mkdir(parents=True)
    (ws / "vendor" / "lib" / "notes.md").write_text(_TODO_BODY, encoding="utf-8")
    (ws / "vendor" / "lib" / "bundle.py").write_text("v = 1\n", encoding="utf-8")
    return ws


@pytest.fixture(scope="module")
def main_ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The main workspace: TODOs under ``vendor/`` AND TODOs in kept files."""
    return _private_workspace(tmp_path_factory.mktemp("iter212_main"))


@pytest.fixture(scope="module")
def stash_ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A workspace emitting a PATH-LESS signal beside path-carrying ones.

    No ``git`` subprocess: the stash reflog marker is hand-written, the iter-53 /
    iter-155 discipline.
    """
    root = tmp_path_factory.mktemp("iter212_stash")
    ws = _private_workspace(root)
    reflog = ws / ".git" / "logs" / "refs" / "stash"
    reflog.parent.mkdir(parents=True)
    zeros = "0" * 40
    reflog.write_text(
        f"{zeros} f7a3af3 Tester <t@t.com> 1785545283 -0700\tWIP on main: shelved\n",
        encoding="utf-8",
    )
    return ws


@pytest.fixture(scope="module")
def state_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """State dirs live OUTSIDE every scanned workspace."""
    return tmp_path_factory.mktemp("iter212_state")


@pytest.fixture(scope="module")
def baseline(main_ws: Path) -> list[dict]:
    """The unfiltered perception record of the main workspace."""
    records = _records(main_ws)
    assert _under_vendor(_paths(records)), (
        "fixture precondition: the tree must hold at least one signal under "
        f"{_VENDOR!r}; paths={_paths(records)}"
    )
    assert [p for p in _paths(records) if p is not None and not p.startswith(_VENDOR)], (
        f"fixture precondition: a survivor must exist; paths={_paths(records)}"
    )
    return records


@pytest.fixture(scope="module")
def plain_scan(
    main_ws: Path, state_root: Path
) -> tuple[subprocess.CompletedProcess[str], list[dict], dict]:
    """ONE shared unfiltered ``scan`` run (behaviors 2 and 8)."""
    state = state_root / "plain"
    snap = state_root / "plain-snapshot.json"
    out = state_root / "plain-slate.json"
    proc = _scan(main_ws, state, "--snapshot", str(snap), "--out", str(out))
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    slate = json.loads(out.read_text(encoding="utf-8"))
    return proc, _snapshot(snap), slate


@pytest.fixture(scope="module")
def excluded_scan(
    main_ws: Path, state_root: Path
) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    """ONE shared ``scan --exclude-path 'vendor/*'`` run (behaviors 3, 4 and 8)."""
    state = state_root / "excluded"
    snap = state_root / "excluded-snapshot.json"
    out = state_root / "excluded-slate.json"
    proc = _scan(
        main_ws,
        state,
        "--exclude-path",
        _VENDOR_GLOB,
        "--snapshot",
        str(snap),
        "--out",
        str(out),
    )
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    assert out.is_file(), "the slate must still be written when signals are excluded"
    return proc, _snapshot(snap)


# ===========================================================================
# Behavior 1 -- the flag exists on `scan`, is repeatable, absent by default.
# ===========================================================================


def test_b01_flag_is_repeatable_and_appends_in_order() -> None:
    args = build_parser().parse_args(
        ["scan", "--workspace", "W", "--exclude-path", "a", "--exclude-path", "b"]
    )
    assert args.exclude_path == ["a", "b"], (
        "the flag must append into `exclude_path` in the order given; "
        f"got {args.exclude_path!r}"
    )


def test_b01_absent_flag_defaults_to_none() -> None:
    args = build_parser().parse_args(["scan", "--workspace", "W"])
    assert args.exclude_path is None, (
        f"absent must be None, not an empty list; got {args.exclude_path!r}"
    )


def test_b01_help_advertises_the_glob_metavar(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["scan", "--help"])
    assert exit_info.value.code == 0
    rendered = _norm(capsys.readouterr().out)
    assert "--exclude-path GLOB" in rendered, (
        f"`scan --help` must advertise the flag with a GLOB metavar; got {rendered!r}"
    )


def test_b01_sibling_verbs_are_untouched() -> None:
    """Scope fence, NARROWED in iter 249 -- point-in-time, not a product invariant.

    Iteration 212's criterion was "only `scan` changes; `run` and `watch` gain
    nothing", scoped by its own words "in this iteration". Row #249 removed `run`
    from the fence on PM authority: it shipped `run --exclude-path`, the LOCATION
    half of the pair whose `--collector` half shipped as row #248. `watch` stays
    fenced because row #249's Out of Scope keeps it so -- "`--exclude-path` on
    `watch` -- unchanged, exactly as iter-245 left `--collector` there". A later
    iteration may narrow this further by PM decision; it may not widen it back
    over `run`.
    """
    parser = build_parser()
    for verb in ("watch",):
        with pytest.raises(SystemExit) as exit_info:
            parser.parse_args([verb, "--workspace", "W", "--exclude-path", "x"])
        assert exit_info.value.code == 2, (
            f"`{verb}` must not gain --exclude-path: it is still fenced as of iter 249"
        )


# ===========================================================================
# Behavior 2 -- absent flag changes nothing.
# ===========================================================================


def test_b02_absent_flag_records_the_unfiltered_perception_in_order(
    plain_scan: tuple[subprocess.CompletedProcess[str], list[dict], dict],
    baseline: list[dict],
) -> None:
    _, snapshot_signals, _ = plain_scan
    assert _paths(snapshot_signals) == _paths(baseline), (
        "with no --exclude-path the snapshot must hold exactly the collected signals "
        "in the same order"
    )
    assert _triples(snapshot_signals) == _triples(baseline)


def test_b02_absent_flag_keeps_the_vendored_subtree(
    plain_scan: tuple[subprocess.CompletedProcess[str], list[dict], dict],
) -> None:
    """The control that makes every exclusion assertion non-vacuous."""
    _, snapshot_signals, _ = plain_scan
    assert _under_vendor(_paths(snapshot_signals)), (
        "an unfiltered scan MUST still see the vendored subtree, otherwise the "
        "exclusion tests below would pass against an already-empty set"
    )


# ===========================================================================
# Behavior 3 -- an excluded path does not reach synthesis.
# ===========================================================================


def test_b03_excluded_subtree_is_absent_from_the_synthesis_record(
    excluded_scan: tuple[subprocess.CompletedProcess[str], list[dict]],
) -> None:
    _, kept = excluded_scan
    offenders = _under_vendor(_paths(kept))
    assert offenders == [], (
        f"no signal under {_VENDOR!r} may reach synthesis; leaked={offenders}"
    )


def test_b03_kept_file_still_reaches_synthesis(
    excluded_scan: tuple[subprocess.CompletedProcess[str], list[dict]],
    baseline: list[dict],
) -> None:
    _, kept = excluded_scan
    survivors = [
        p for p in _paths(baseline) if p is not None and not p.startswith(_VENDOR)
    ]
    kept_paths = _paths(kept)
    missing = [p for p in survivors if p not in kept_paths]
    assert missing == [], (
        f"excluding {_VENDOR_GLOB!r} must not drop unrelated signals; missing={missing}"
    )


# ===========================================================================
# Behavior 4 -- one matcher: `scan` and `signals` select the same set.
# ===========================================================================


def test_b04_scan_and_signals_agree_on_the_same_pattern(
    excluded_scan: tuple[subprocess.CompletedProcess[str], list[dict]],
    main_ws: Path,
    baseline: list[dict],
) -> None:
    _, kept = excluded_scan
    from_signals = _records(main_ws, "--exclude-path", _VENDOR_GLOB)
    assert len(from_signals) < len(baseline), (
        "NON-VACUITY: the chosen pattern must actually drop at least one signal, "
        f"but signals reported {len(from_signals)} of {len(baseline)}"
    )
    assert _triples(kept) == _triples(from_signals), (
        "one matcher, not two: `scan --exclude-path P` and `signals --exclude-path P` "
        "must select the same (kind, path, summary) set"
    )


# ===========================================================================
# Behavior 5 -- a path-less signal is NEVER excluded, not even by '*'.
# ===========================================================================


def test_b05_star_keeps_every_path_less_signal_and_drops_every_path(
    stash_ws: Path, state_root: Path
) -> None:
    base = _records(stash_ws)
    path_less = [r for r in base if r["path"] is None]
    assert path_less, (
        f"fixture precondition: a path-less signal must exist; paths={_paths(base)}"
    )
    assert [p for p in _paths(base) if p is not None], "fixture must also hold paths"

    state = state_root / "star"
    snap = state_root / "star-snapshot.json"
    proc = _scan(stash_ws, state, "--exclude-path", "*", "--snapshot", str(snap))
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"

    kept = _snapshot(snap)
    assert _paths(kept) == [None] * len(kept), (
        f"'*' must drop every path-carrying signal; kept={_paths(kept)}"
    )
    assert _triples(kept) == _triples(path_less), (
        "and it must keep EVERY path-less signal -- collectors still ran, so this also "
        "proves the exclusion is post-collect rather than upstream pruning"
    )


# ===========================================================================
# Behavior 6 -- an empty or whitespace-only pattern is a usage error (exit 2).
# ===========================================================================


def test_b06_empty_pattern_exits_2_and_writes_nothing(
    main_ws: Path, state_root: Path
) -> None:
    state = state_root / "refusal"
    snap = state_root / "refusal-snapshot.json"
    out = state_root / "refusal-slate.json"
    proc = _scan(
        main_ws,
        state,
        "--exclude-path",
        "",
        "--snapshot",
        str(snap),
        "--out",
        str(out),
    )
    assert proc.returncode == 2, f"expected a usage error; stderr={proc.stderr!r}"
    assert _GLOB_REFUSAL in _norm(proc.stderr), (
        f"stderr must carry the shared validator wording; got {proc.stderr!r}"
    )
    assert not out.exists(), "a parse-time refusal must not write a slate"
    assert not snap.exists(), "a parse-time refusal must not write a snapshot"


def test_b06_whitespace_only_pattern_is_also_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(
            ["scan", "--workspace", "W", "--exclude-path", "   "]
        )
    assert exit_info.value.code == 2
    assert _GLOB_REFUSAL in _norm(capsys.readouterr().err)


def test_b06_refusal_matches_the_signals_verb_verbatim(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The message after ``error:`` is the shared validator's, so it must be identical."""
    tails = []
    for verb in ("scan", "signals"):
        with pytest.raises(SystemExit) as exit_info:
            build_parser().parse_args(
                [verb, "--workspace", "W", "--exclude-path", ""]
            )
        assert exit_info.value.code == 2
        tails.append(_error_tail(capsys.readouterr().err))
    assert tails[0] == tails[1], (
        f"scan and signals must share one refusal; scan={tails[0]!r} "
        f"signals={tails[1]!r}"
    )


# ===========================================================================
# Behavior 7 -- composes as a logical AND with `--collector`.
# ===========================================================================


def test_b07_composes_as_an_and_with_collector(main_ws: Path, state_root: Path) -> None:
    state = state_root / "and"
    snap = state_root / "and-snapshot.json"
    proc = _scan(
        main_ws,
        state,
        "--collector",
        "todos",
        "--exclude-path",
        _VENDOR_GLOB,
        "--snapshot",
        str(snap),
    )
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    kept = _snapshot(snap)
    assert kept, "NON-VACUITY: the AND must leave survivors, not an empty record"
    kinds = sorted({r["kind"] for r in kept})
    assert kinds == ["todo"], f"--collector todos must bound the kinds; got {kinds}"
    assert _under_vendor(_paths(kept)) == [], (
        f"and the exclusion must still apply; kept={_paths(kept)}"
    )


# ===========================================================================
# Behavior 8 -- the success path is otherwise unchanged.
# ===========================================================================


def test_b08_excluding_signals_still_exits_0_and_writes_a_complete_slate(
    excluded_scan: tuple[subprocess.CompletedProcess[str], list[dict]],
    plain_scan: tuple[subprocess.CompletedProcess[str], list[dict], dict],
    state_root: Path,
) -> None:
    proc, _ = excluded_scan
    assert proc.returncode == 0
    slate = json.loads(
        (state_root / "excluded-slate.json").read_text(encoding="utf-8")
    )
    _, _, plain_slate = plain_scan
    assert set(slate) == set(plain_slate), (
        "the slate document's shape must not change when signals are excluded; "
        f"excluded={sorted(slate)} plain={sorted(plain_slate)}"
    )
    assert slate["goals"], "the slate must still carry goals"


def test_b08_default_table_format_still_prints_the_trailer(
    excluded_scan: tuple[subprocess.CompletedProcess[str], list[dict]],
) -> None:
    proc, _ = excluded_scan
    assert _TRAILER in proc.stdout, (
        f"the default table format must still print the {_TRAILER!r} trailer; "
        f"stdout={proc.stdout!r}"
    )


# ===========================================================================
# Behavior 3 (cont.) -- the filter narrows the SIGNALS and nothing else.
# ===========================================================================


def test_b03_snapshot_identity_survives_the_filter(
    plain_scan: tuple[subprocess.CompletedProcess[str], list[dict], dict],
    excluded_scan: tuple[subprocess.CompletedProcess[str], list[dict]],
    state_root: Path,
) -> None:
    """The acceptance criterion "``root``/``collected_at`` survive the filter", from
    the outside: the snapshot document's non-signal fields must be the SAME under an
    exclusion as without one, so the filtered snapshot is still a record OF THIS
    WORKSPACE rather than a freshly constructed document that lost its identity.
    ``collected_at`` is not part of the closed ``--snapshot`` shape, so
    ``workspace_root`` is the observable half and is what is asserted.

    Both runs are REQUESTED as fixtures rather than read as files another test happened
    to leave behind: ``addopts = -q -n auto`` gives every xdist worker its own
    module-scoped ``state_root``, so reading the two documents by path alone passed or
    failed on which worker drew this test.  Measured: it failed exactly that way on
    ``gw4`` (``plain-snapshot.json`` present, ``excluded-snapshot.json`` absent) before
    the fixtures were named here.
    """
    plain_doc = _snapshot_doc(state_root / "plain-snapshot.json")
    excluded_doc = _snapshot_doc(state_root / "excluded-snapshot.json")
    assert excluded_doc["workspace_root"] == plain_doc["workspace_root"], (
        "an exclusion must not change the snapshot's workspace_root; "
        f"plain={plain_doc['workspace_root']!r} "
        f"excluded={excluded_doc['workspace_root']!r}"
    )
    assert len(excluded_doc["signals"]) < len(plain_doc["signals"]), (
        "NON-VACUITY: this pair is only evidence if the exclusion actually dropped "
        f"signals; plain={len(plain_doc['signals'])} "
        f"excluded={len(excluded_doc['signals'])}"
    )


def test_b03_repeated_patterns_exclude_the_UNION(
    main_ws: Path, state_root: Path, baseline: list[dict]
) -> None:
    """Behavior 1 makes the flag repeatable; the only useful reading of two patterns is
    that BOTH are excluded (a logical OR over patterns).  The second pattern is derived
    from the live baseline rather than hardcoded, so the test cannot silently go vacuous
    if the bundled fixture's filenames change.
    """
    survivors = [
        p for p in _paths(baseline) if p is not None and not p.startswith(_VENDOR)
    ]
    assert survivors, f"fixture precondition: a survivor must exist; {_paths(baseline)}"
    second = survivors[0]

    state = state_root / "union"
    snap = state_root / "union-snapshot.json"
    proc = _scan(
        main_ws,
        state,
        "--exclude-path",
        _VENDOR_GLOB,
        "--exclude-path",
        second,
        "--snapshot",
        str(snap),
    )
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    kept = _paths(_snapshot(snap))
    assert _under_vendor(kept) == [], f"first pattern must still apply; kept={kept}"
    assert second not in kept, (
        f"the second pattern must also apply; {second!r} survived in {kept}"
    )
