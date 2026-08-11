"""Black-box behavior tests for commit-seq **factory iter 132** (state dir iter-125):
``pla signals --exclude-path GLOB`` -- the perception inspector's first
LOCATION-aware selection axis.

Feature under test: a repeatable, case-insensitive path-glob EXCLUSION filter on the
``signals`` verb. It is a DOWNSTREAM (display-side) filter, so it must narrow every
``signals`` surface identically -- the human listing, ``--json``, ``--summary``,
``--summary --json`` -- and the ``--fail-on-kind`` exit gate with them, while leaving
collection (and therefore the ``--timings`` rows) untouched.

ISOLATION CONTRACT (honored): every assertion below was derived from this iteration's
spec (``pm.md`` "Expected Behaviors" 1-14) plus the conventions of the existing
modules under ``tests/``.  **No file under ``src/`` was read, no engineer / reviewer /
fix note was opened, and no ``git diff`` was consulted.**  Where the shape of the
output was needed it was obtained by RUNNING the installed ``pla`` console script
against throwaway fixture trees and reading its stdout/stderr/exit status -- never by
reading the implementation.  The two fixture helpers here were written fresh from the
spec rather than lifted from any upstream stage's probe (iter-124 lesson).

Fully offline and deterministic: synthetic ``tmp_path_factory`` trees only (never the
in-repo tree, so no collector can leak repo state -- iter-15 lesson), no network, no
API key, no ``git`` subprocess (the stash fixture hand-writes the reflog marker file
the way ``test_iter53_behavior.py`` does), and NO DURATION IS ASSERTED ANYWHERE
(roadmap row #129's standing constraint).

HARNESS FACT worth stating, because every path assertion depends on it: the reported
``path`` is rendered relative to the ``--workspace`` argument AS GIVEN.  Measured:
``--workspace /abs/dir`` prints absolute paths, while running with ``cwd`` set to the
fixture root and ``--workspace .`` prints ``sub/a.py``.  The spec is written in terms
of relative paths, so every invocation here uses ``cwd=<fixture root>`` plus
``--workspace .``.

AMBIGUITY NOTES (PM feedback):

* Behavior 2 says a bare invocation's stdout must be "byte-identical to stdout before
  this feature existed".  That pre-feature baseline is not reachable from inside the
  commit that adds the flag (reading ``git`` history is outside the isolation
  contract), so the checkable equivalent is asserted instead: the default is INERT --
  a bare run is byte-identical to the same run carrying a pattern that matches
  nothing, on both the human and the ``--json`` surface.  The pre-existing ``signals``
  stdout guards elsewhere in ``tests/`` are the real regression net for that clause.
* Behavior 5 needs a signal whose ``path`` is ``None``.  No collector emits one on a
  plain directory tree (measured: 0 of 79 on this repo, 0 of 12 on the main fixture),
  so this module builds a second fixture carrying a stash reflog marker: ``git_stash``
  is the kind that reports repo-level perception with ``path == null``.
* Behavior 10 names ``''`` and ``'   '``.  A lone TAB is the same class of
  whitespace-only pattern and is asserted too (measured: also exit 2).
* Behavior 11 pins the human LISTING, ``--json`` and ``--summary --json`` on an
  emptied view but is silent on the human ``--summary`` TABLE. Measured: it degrades
  to the same ``(no signals collected)`` marker, byte-identically to how the
  pre-existing ``--min-weight`` knob already empties it, so that established
  convention is what is asserted (my first draft wrongly demanded a ``total 0`` row
  and the product was right).
* Behavior 12 mandates only that the ``--timings`` row NAMES and the ``TOTAL`` row are
  unchanged.  The per-row SIGNAL COUNT is also measured to be unchanged (the column
  reports what each collector emitted, upstream of the filter), so this module asserts
  the stronger ``(name, count)`` pairing.  The elapsed-ms column is wall-clock and is
  deliberately never asserted.
* Behavior 14 says the bytes at/above the human-owned marker are "unchanged".  Without
  git that is asserted as its two observable consequences: ``--exclude-path`` appears
  only BELOW the marker line, and the intro's two carve-out counts still read 16
  collectors / 15 CLI verbs (this change adds neither).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_MARKER = "PORTFOLIO INTRO"
_EMPTY_MARKER = "(no signals collected)"
_GATE_PREFIX = "gate:"


# ---------------------------------------------------------------------------
# Harness -- drive the shipped console script, read observable output only.
# ---------------------------------------------------------------------------


def _console_script() -> Path:
    """The installed ``pla`` console script (iter114's resolution convention)."""
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
    """Run ``pla <args>`` with *cwd* as the process working directory."""
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _signals(ws: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """``pla signals --workspace .`` from inside *ws* (relative paths -- see docstring)."""
    return _run("signals", "--workspace", ".", *extra, cwd=ws)


def _doc(ws: Path, *extra: str) -> dict:
    """The parsed ``--json`` object; the ENTIRE stdout must be one clean JSON object."""
    proc = _signals(ws, "--json", *extra)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    doc = json.loads(proc.stdout)
    assert isinstance(doc, dict)
    assert set(doc) == {"workspace_root", "signals"}, sorted(doc)
    return doc


def _records(ws: Path, *extra: str) -> list[dict]:
    return list(_doc(ws, *extra)["signals"])


def _summary_doc(ws: Path, *extra: str) -> dict:
    proc = _signals(ws, "--summary", "--json", *extra)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    doc = json.loads(proc.stdout)
    assert set(doc) == {"workspace_root", "summary", "total"}, sorted(doc)
    return doc


def _paths(records: list[dict]) -> list[str | None]:
    return [r["path"] for r in records]


def _gate_lines(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.startswith(_GATE_PREFIX)]


def _table_rows(stderr: str) -> list[tuple[str, str]]:
    """(collector name, signal count) for each indented ``--timings`` row, in order."""
    rows: list[tuple[str, str]] = []
    for ln in stderr.splitlines():
        if not ln.startswith("  "):
            continue
        parts = ln.split()
        if len(parts) == 3:
            rows.append((parts[0], parts[2]))
    return rows


def _count_table(stdout: str) -> dict[str, int]:
    """Parse the human ``--summary`` table (``kind  N`` lines, ``total  N`` last)."""
    out: dict[str, int] = {}
    for ln in stdout.splitlines():
        parts = ln.split()
        if len(parts) == 2 and parts[1].lstrip("-").isdigit():
            out[parts[0]] = int(parts[1])
    return out


# ---------------------------------------------------------------------------
# Fixtures -- built fresh from the spec's own examples.
# ---------------------------------------------------------------------------


def _build_main(root: Path) -> None:
    """The spec's worked example: a ``sub/`` subtree, a decoy ``top/sub/``, a
    matches-nothing file, and a markdown file whose TODOs land on known lines."""
    (root / "sub" / "a").mkdir(parents=True)
    (root / "top" / "sub").mkdir(parents=True)
    (root / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "sub" / "a" / "b.py").write_text("q = 4\n", encoding="utf-8")
    (root / "top" / "sub" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (root / "keep.py").write_text("k = 5\n", encoding="utf-8")
    filler = "\n".join(f"line {i}" for i in range(1, 12))
    (root / "notes.md").write_text(
        filler + "\n- TODO: alpha here\n- TODO: beta here\n", encoding="utf-8"
    )


@pytest.fixture(scope="module")
def ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The main fixture workspace. Read-only for every test, so it is built once."""
    root = tmp_path_factory.mktemp("iter132_main")
    _build_main(root)
    return root


@pytest.fixture(scope="module")
def upper_ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A workspace whose directory is spelled in UPPER CASE (behavior 6, path side)."""
    root = tmp_path_factory.mktemp("iter132_upper")
    (root / "UPPER").mkdir()
    (root / "UPPER" / "a.py").write_text("x = 1\n", encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def stash_ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A workspace that emits a PATH-LESS signal (``git_stash``), plus path-carrying
    ones. No ``git`` subprocess: the reflog marker file is hand-written, the same
    discipline ``test_iter53_behavior.py`` uses."""
    root = tmp_path_factory.mktemp("iter132_stash")
    reflog = root / ".git" / "logs" / "refs" / "stash"
    reflog.parent.mkdir(parents=True)
    zeros = "0" * 40
    reflog.write_text(
        f"{zeros} f7a3af3 Tester <t@t.com> 1785545283 -0700\tWIP on main: shelved\n",
        encoding="utf-8",
    )
    (root / "sub").mkdir()
    (root / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "notes.md").write_text("# n\n- TODO: alpha\n", encoding="utf-8")
    return root


# ===========================================================================
# Behavior 1 -- the flag excludes by path, and the survivors are untouched.
# ===========================================================================


def test_b01_excludes_the_matching_signal(ws: Path) -> None:
    base = _records(ws)
    assert "sub/a.py" in _paths(base), f"fixture precondition; paths={_paths(base)}"
    filtered = _records(ws, "--exclude-path", "sub/a.py")
    assert "sub/a.py" not in _paths(filtered)


def test_b01_survivors_are_record_identical_and_in_the_same_order(ws: Path) -> None:
    base = _records(ws)
    filtered = _records(ws, "--exclude-path", "sub/a.py")
    expected = [r for r in base if r["path"] != "sub/a.py"]
    assert filtered == expected, (
        "every surviving record must be byte-identical (same fields, same order) to "
        "the unfiltered run; the filter may only REMOVE rows"
    )
    assert len(filtered) == len(base) - 1


# ===========================================================================
# Behavior 2 -- opt-in: absent means inert, on every surface.
# ===========================================================================


def test_b02_absent_flag_reports_the_signal(ws: Path) -> None:
    proc = _signals(ws)
    assert proc.returncode == 0, proc.stderr
    assert "sub/a.py" in proc.stdout


def test_b02_default_is_byte_identical_to_a_pattern_matching_nothing(ws: Path) -> None:
    bare = _signals(ws)
    inert = _signals(ws, "--exclude-path", "no-such-dir/*")
    assert inert.stdout == bare.stdout
    assert inert.returncode == bare.returncode == 0
    assert _records(ws) == _records(ws, "--exclude-path", "no-such-dir/*")


# ===========================================================================
# Behavior 3 -- repeatable, OR semantics, idempotent on a duplicate.
# ===========================================================================


def test_b03_two_patterns_are_ored(ws: Path) -> None:
    paths = _paths(_records(ws, "--exclude-path", "sub/*", "--exclude-path", "*.md"))
    assert "sub/a.py" not in paths
    assert "sub/a/b.py" not in paths
    assert "notes.md" not in paths
    assert "notes.md:12" not in paths
    assert "keep.py" in paths, "a signal matching neither pattern must survive"


def test_b03_repeating_the_same_pattern_changes_nothing(ws: Path) -> None:
    once = _signals(ws, "--exclude-path", "sub/*")
    twice = _signals(ws, "--exclude-path", "sub/*", "--exclude-path", "sub/*")
    assert twice.stdout == once.stdout
    assert twice.returncode == once.returncode == 0


# ===========================================================================
# Behavior 4 -- a trailing `:LINE` suffix does not defeat the match.
# ===========================================================================


@pytest.mark.parametrize("pattern", ["notes.md", "*.md", "notes.md:12"])
def test_b04_line_suffixed_path_is_excluded(ws: Path, pattern: str) -> None:
    base = _paths(_records(ws))
    assert "notes.md:12" in base, f"fixture precondition; paths={base}"
    paths = _paths(_records(ws, "--exclude-path", pattern))
    assert "notes.md:12" not in paths, f"pattern {pattern!r} must exclude notes.md:12"


def test_b04_an_exact_line_pattern_does_not_over_match(ws: Path) -> None:
    """``notes.md:12`` is exact: the sibling TODO on line 13 and the path-only
    ``recent_file`` for the same file both survive. This is what separates "strip one
    trailing `:<digits>` from the PATH" from "truncate the PATTERN at a colon"."""
    paths = _paths(_records(ws, "--exclude-path", "notes.md:12"))
    assert "notes.md:12" not in paths
    assert "notes.md:13" in paths
    assert "notes.md" in paths


def test_b04_a_whole_file_pattern_excludes_every_line_of_it(ws: Path) -> None:
    paths = _paths(_records(ws, "--exclude-path", "notes.md"))
    assert "notes.md:12" not in paths
    assert "notes.md:13" not in paths
    assert "notes.md" not in paths


# ===========================================================================
# Behavior 5 -- a path-less signal is NEVER excluded.
# ===========================================================================


def test_b05_fixture_emits_a_path_less_signal(stash_ws: Path) -> None:
    base = _records(stash_ws)
    nulls = [r for r in base if r["path"] is None]
    assert nulls, f"fixture precondition: need a path-less signal; got {_paths(base)}"
    assert {r["kind"] for r in nulls} == {"git_stash"}


@pytest.mark.parametrize("pattern", ["*", "*.md", "sub/*", "?"])
def test_b05_path_less_signal_survives_every_pattern(stash_ws: Path, pattern: str) -> None:
    nulls = [r for r in _records(stash_ws) if r["path"] is None]
    surviving = [r for r in _records(stash_ws, "--exclude-path", pattern) if r["path"] is None]
    assert surviving == nulls, (
        f"pattern {pattern!r} must not touch repo-level (path-less) perception"
    )


def test_b05_exclude_everything_leaves_exactly_the_path_less_signals(stash_ws: Path) -> None:
    base = _records(stash_ws)
    nulls = [r for r in base if r["path"] is None]
    assert len(nulls) < len(base), "fixture must also carry path-carrying signals"
    assert _records(stash_ws, "--exclude-path", "*") == nulls
    human = _signals(stash_ws, "--exclude-path", "*")
    assert human.returncode == 0, human.stderr
    assert "git_stash" in human.stdout
    assert _EMPTY_MARKER not in human.stdout


# ===========================================================================
# Behavior 6 -- case-insensitive on BOTH sides.
# ===========================================================================


@pytest.mark.parametrize("pattern", ["SUB/*", "Sub/A.py", "sub/A.PY"])
def test_b06_pattern_case_is_ignored(ws: Path, pattern: str) -> None:
    assert "sub/a.py" not in _paths(_records(ws, "--exclude-path", pattern))


@pytest.mark.parametrize("pattern", ["upper/*", "UPPER/*", "*.PY"])
def test_b06_path_case_is_ignored(upper_ws: Path, pattern: str) -> None:
    base = _paths(_records(upper_ws))
    assert "UPPER/a.py" in base, f"fixture precondition; paths={base}"
    assert "UPPER/a.py" not in _paths(_records(upper_ws, "--exclude-path", pattern))


# ===========================================================================
# Behavior 7 -- anchored at the start, and `*` crosses `/`.
# ===========================================================================


def test_b07_star_crosses_slash_so_a_prefix_hides_the_whole_subtree(ws: Path) -> None:
    paths = _paths(_records(ws, "--exclude-path", "sub/*"))
    assert "sub/a.py" not in paths
    assert "sub/a/b.py" not in paths, "'*' must cross '/' -- a subtree, not one level"


def test_b07_match_is_anchored_at_the_start_of_the_path(ws: Path) -> None:
    paths = _paths(_records(ws, "--exclude-path", "sub/*"))
    assert "top/sub/b.py" in paths, "an unanchored (substring) match would wrongly hide this"


def test_b07_a_leading_star_makes_it_any_depth(ws: Path) -> None:
    paths = _paths(_records(ws, "--exclude-path", "*sub/*"))
    assert "sub/a.py" not in paths
    assert "sub/a/b.py" not in paths
    assert "top/sub/b.py" not in paths


def test_b07_a_bare_directory_path_is_not_special_cased(ws: Path) -> None:
    """``test_posture`` reports a bare directory name (``sub``, no trailing slash), so
    ``sub/*`` legitimately leaves it standing. The spec calls this out as correct."""
    records = _records(ws, "--exclude-path", "sub/*")
    assert "sub" in _paths(records)
    assert {r["kind"] for r in records if r["path"] == "sub"} == {"test_posture"}


# ===========================================================================
# Behavior 8 -- logical AND with the other knobs, identical on every surface.
# ===========================================================================


def test_b08_json_and_summary_json_agree(ws: Path) -> None:
    records = _records(ws, "--exclude-path", "sub/*")
    doc = _summary_doc(ws, "--exclude-path", "sub/*")
    assert doc["summary"] == dict(Counter(r["kind"] for r in records))
    assert doc["total"] == len(records)


def test_b08_human_listing_and_human_summary_agree(ws: Path) -> None:
    records = _records(ws, "--exclude-path", "sub/*")
    counts = Counter(r["kind"] for r in records)
    listing = _signals(ws, "--exclude-path", "sub/*")
    assert listing.returncode == 0, listing.stderr
    for kind, n in counts.items():
        assert f"## {kind} ({n})" in listing.stdout
    table = _count_table(_signals(ws, "--summary", "--exclude-path", "sub/*").stdout)
    assert table == {**counts, "total": len(records)}


def test_b08_intersects_with_kind(ws: Path) -> None:
    records = _records(ws, "--exclude-path", "sub/*")
    narrowed = _records(ws, "--kind", "recent_file", "--exclude-path", "sub/*")
    assert narrowed == [r for r in records if r["kind"] == "recent_file"]
    assert narrowed, "the intersection must be non-empty for this to prove anything"


def test_b08_intersects_with_min_weight(ws: Path) -> None:
    records = _records(ws, "--exclude-path", "sub/*")
    narrowed = _records(ws, "--min-weight", "0.9", "--exclude-path", "sub/*")
    assert narrowed == [r for r in records if r["weight"] >= 0.9]
    assert 0 < len(narrowed) < len(records), "fixture must straddle the threshold"


# ===========================================================================
# Behavior 9 -- the exit gate can never contradict the listing.
# ===========================================================================


def test_b09_gate_trips_on_the_unfiltered_view(ws: Path) -> None:
    proc = _signals(ws, "--fail-on-kind", "todo")
    todos = [r for r in _records(ws) if r["kind"] == "todo"]
    assert len(todos) == 2, f"fixture precondition; got {todos}"
    assert proc.returncode == 5
    assert _gate_lines(proc.stderr) == ["gate: fail-on-kind tripped -- todo=2"]


def test_b09_excluding_every_signal_of_the_kind_exits_zero_and_prints_no_gate_line(
    ws: Path,
) -> None:
    proc = _signals(ws, "--fail-on-kind", "todo", "--exclude-path", "*.md")
    assert [r for r in _records(ws, "--exclude-path", "*.md") if r["kind"] == "todo"] == []
    assert proc.returncode == 0, proc.stderr
    assert _gate_lines(proc.stderr) == []
    assert _GATE_PREFIX not in proc.stderr


def test_b09_gate_count_equals_the_number_of_survivors(ws: Path) -> None:
    proc = _signals(ws, "--fail-on-kind", "todo", "--exclude-path", "notes.md:12")
    survivors = [
        r for r in _records(ws, "--exclude-path", "notes.md:12") if r["kind"] == "todo"
    ]
    assert len(survivors) == 1
    assert proc.returncode == 5
    assert _gate_lines(proc.stderr) == ["gate: fail-on-kind tripped -- todo=1"]


# ===========================================================================
# Behavior 10 -- an empty / whitespace-only pattern is a parse-time usage error.
# ===========================================================================


@pytest.mark.parametrize("pattern", ["", "   ", "\t", " \t "])
def test_b10_empty_pattern_is_a_usage_error(ws: Path, pattern: str) -> None:
    proc = _signals(ws, "--exclude-path", pattern)
    assert proc.returncode == 2, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout == "", "a parse-time error must emit no collection output"
    assert "usage:" in proc.stderr
    assert "--exclude-path" in proc.stderr


def test_b10_a_valid_pattern_alongside_an_empty_one_still_fails(ws: Path) -> None:
    proc = _signals(ws, "--exclude-path", "sub/*", "--exclude-path", "")
    assert proc.returncode == 2
    assert proc.stdout == ""


# ===========================================================================
# Behavior 11 -- excluding everything is an honest empty answer, not an error.
# ===========================================================================


def test_b11_human_view_degrades_to_the_empty_marker(ws: Path) -> None:
    base = _records(ws)
    assert all(r["path"] is not None for r in base), "precondition: no path-less signals"
    proc = _signals(ws, "--exclude-path", "*")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _EMPTY_MARKER


def test_b11_json_view_is_an_empty_array(ws: Path) -> None:
    doc = _doc(ws, "--exclude-path", "*")
    assert doc["signals"] == []
    assert doc["workspace_root"] == "."


def test_b11_summary_view_is_empty_with_a_zero_total(ws: Path) -> None:
    doc = _summary_doc(ws, "--exclude-path", "*")
    assert doc["summary"] == {}
    assert doc["total"] == 0
    human = _signals(ws, "--summary", "--exclude-path", "*")
    assert human.returncode == 0, human.stderr
    assert human.stdout.strip() == _EMPTY_MARKER, (
        "MEASURED product convention, not a spec clause: the human --summary view "
        "degrades to the same empty marker as the listing when the selection is "
        "empty -- identical to what the pre-existing --min-weight knob already does "
        "-- so --exclude-path must not invent a different empty rendering. The spec "
        "only pins the --summary --json shape here."
    )
    assert _signals(ws, "--summary", "--min-weight", "5").stdout == human.stdout


# ===========================================================================
# Behavior 12 -- collection is untouched (the filter is downstream).
# ===========================================================================


def test_b12_timings_rows_are_identical_with_and_without_the_filter(ws: Path) -> None:
    base = _signals(ws, "--timings")
    filtered = _signals(ws, "--timings", "--exclude-path", "*")
    assert base.returncode == filtered.returncode == 0
    base_rows = _table_rows(base.stderr)
    assert base_rows, f"precondition: a timings table on stderr; got {base.stderr!r}"
    assert "TOTAL" in [name for name, _ in base_rows]
    assert _table_rows(filtered.stderr) == base_rows, (
        "an UPSTREAM filter would shrink the row set; --exclude-path must not, and the "
        "per-collector signal counts report what was COLLECTED, not what was reported"
    )


def test_b12_timings_does_not_disturb_the_filtered_stdout(ws: Path) -> None:
    without = _signals(ws, "--exclude-path", "sub/*")
    with_timings = _signals(ws, "--exclude-path", "sub/*", "--timings")
    assert with_timings.stdout == without.stdout


# ===========================================================================
# Behavior 13 -- discoverability.
# ===========================================================================


def _exclude_path_help_block(help_text: str) -> str:
    """The ``--exclude-path`` entry of the options list, whitespace-normalized."""
    lines = help_text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith("  --exclude-path")), None
    )
    assert start is not None, f"no --exclude-path option entry in:\n{help_text}"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("  -") and not lines[i].startswith("   "):
            end = i
            break
    return " ".join(" ".join(lines[start:end]).split())


def test_b13_help_exits_zero_and_lists_the_flag(ws: Path) -> None:
    proc = _run("signals", "--help", cwd=ws)
    assert proc.returncode == 0, proc.stderr
    assert "--exclude-path GLOB" in " ".join(proc.stdout.split())


def test_b13_help_documents_the_four_load_bearing_facts(ws: Path) -> None:
    block = _exclude_path_help_block(_run("signals", "--help", cwd=ws).stdout).lower()
    assert "repeatable" in block, block
    assert "case-insensitive" in block, block
    assert "crosses" in block and "'/'" in block, block
    assert "leading" in block, "an any-depth exclusion needs a leading '*'"
    assert "never excluded" in block, block


def test_b13_top_level_usage_line_advertises_the_flag(ws: Path) -> None:
    usage = " ".join(_run("signals", "--help", cwd=ws).stdout.split())
    assert "[--exclude-path GLOB]" in usage


# ===========================================================================
# Behavior 14 -- README documents it BELOW the human-owned marker only.
# ===========================================================================


def _readme_split() -> tuple[list[str], list[str]]:
    lines = (REPO / "README.md").read_text(encoding="utf-8").splitlines()
    hits = [i for i, ln in enumerate(lines) if _MARKER in ln]
    assert len(hits) == 1, f"expected exactly one {_MARKER!r} marker line; got {hits}"
    return lines[: hits[0] + 1], lines[hits[0] + 1 :]


def test_b14_readme_mentions_the_flag_only_below_the_marker() -> None:
    above, below = _readme_split()
    assert not [ln for ln in above if "--exclude-path" in ln], (
        "the human-owned portfolio intro must not be edited to document this flag"
    )
    assert [ln for ln in below if "--exclude-path" in ln], (
        "the reference section below the marker must document the shipped flag"
    )


def test_b14_the_signals_verb_row_documents_the_flag() -> None:
    _, below = _readme_split()
    rows = [ln for ln in below if ln.lstrip().startswith("| `signals`")]
    assert len(rows) == 1, f"expected one CLI-table row for `signals`; got {len(rows)}"
    assert "--exclude-path" in rows[0]


def test_b14_intro_carve_out_counts_are_unchanged() -> None:
    above, _ = _readme_split()
    text = "\n".join(above)
    assert "17 context collectors" in text, "this change adds no collector"
    assert "15 CLI verbs" in text, "this change adds no verb"
