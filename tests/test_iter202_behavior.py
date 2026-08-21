"""Black-box behavior tests for state-dir iteration 197 (ships as ``factory iter 199``).

Feature under test: ``pla trend --dir DIR [--json]`` (roadmap row #189) -- a
read-only, LLM-free inspector reporting which goal titles PERSIST across a
``watch --out-dir`` slate stream: a tick count plus the first and last tick index
each title was seen at, ranked by persistence.

MODULE NAME -- DERIVED FROM THE REPO, NOT FROM EITHER COUNTER. Older modules here
name themselves after the FACTORY iteration number, but the two counters have
drifted apart: the newest commit is ``factory iter 198`` while
``tests/test_iter201_behavior.py`` is already tracked. So BOTH candidate names --
"197" (state dir) and "199" (factory tag) -- already exist and writing either
would SILENTLY OVERWRITE a shipped oracle (the iter-172 destroyed-oracle
failure). The name is therefore derived: the highest tracked ``test_iterNN``
under ``tests/`` is 201, so this module is 202, and
``git cat-file -e HEAD:tests/test_iter202_behavior.py`` was proved to FAIL before
a byte was written.

WHY THE BEHAVIORS ARE DRIVEN THROUGH A REAL SUBPROCESS. Several behaviors are
claims about a whole stream -- an exit code paired with exactly ONE ``error:``
line on stderr (9, 10, 14), stdout parsing as exactly one JSON document (12), and
"never a traceback" (14). An in-process ``capsys`` run cannot falsify "no
traceback" honestly, because an escaping exception surfaces as a test error
instead of as output. So this module spends real ``pla`` console-script
invocations (the iter-114 / iter-152 / iter-163 / iter-177 convention).

FIXTURES ARE HAND-WRITTEN STREAMS IN ``tmp_path``, NEVER THE BUNDLED SCRIPT.
``examples/scripted_responses.json`` carries exactly TWO ``synthesize``
responses, so ``watch --max-scans 3`` against it can never produce a third tick
and the central >=3-tick assertion would be VACUOUS. Every stream here is written
directly as slate files, which is also cheaper: the reader only parses filenames.

Offline and deterministic: no network, no clock dependence, no LLM client; every
stream is built in a per-test ``tmp_path``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from proactive_loop.models import CandidateGoal, GoalSlate

REPO = Path(__file__).resolve().parents[1]


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
        timeout=120,
    )


def _goal(
    title: str,
    *,
    impact: float = 5.0,
    urgency: float = 4.0,
    confidence: float = 1.0,
    effort_weight: float = 1.0,
) -> CandidateGoal:
    """One schema-valid goal whose ``score`` is controllable via impact/urgency."""
    return CandidateGoal(
        title=title,
        rationale="persistence oracle fixture",
        category="learning",
        impact=impact,
        urgency=urgency,
        confidence=confidence,
        effort_weight=effort_weight,
        appropriate_now=True,
        sources=["foo.py"],
        suggested_first_steps=["do a thing"],
    )


def _write_stream(out_dir: Path, ticks: dict[int, list[CandidateGoal]]) -> Path:
    """Write one stream slate per ``{tick_index: goals}`` entry.

    The filename convention is the one ``watch --out-dir`` itself writes and the
    one the reader parses a tick index out of (``slate-007.json`` is tick 7).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for index, goals in ticks.items():
        slate = GoalSlate(workspace_root=str(out_dir), goals=list(goals))
        (out_dir / f"slate-{index:03d}.json").write_text(
            slate.model_dump_json(), encoding="utf-8"
        )
    return out_dir


def _lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def _error_lines(stderr: str) -> list[str]:
    return [ln for ln in _lines(stderr) if ln.lstrip().startswith("error:")]


def _json_doc(stdout: str) -> dict[str, object]:
    """Parse stdout as exactly ONE JSON document (no banner, no trailer)."""
    doc = json.loads(stdout)
    assert isinstance(doc, dict), f"--json must print one object; got {type(doc)}"
    return doc


def _rows(doc: dict[str, object]) -> list[dict[str, object]]:
    goals = doc["goals"]
    assert isinstance(goals, list), f"`goals` must be a list; got {type(goals)}"
    return goals  # type: ignore[return-value]


def _by_title(doc: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["title"]): row for row in _rows(doc)}


def _titles(doc: dict[str, object]) -> list[str]:
    """Row titles in the exact order the report emitted them."""
    return [str(row["title"]) for row in _rows(doc)]


# ==========================================================================
# Behavior 1 -- a title present in all 3 ticks reports a tick count of 3.
# ==========================================================================
def test_b01_goal_in_all_three_ticks_reports_tick_count_three(tmp_path: Path) -> None:
    out_dir = _write_stream(
        tmp_path / "stream",
        {
            1: [_goal("Ship the thing"), _goal("Only once")],
            2: [_goal("Ship the thing")],
            3: [_goal("Ship the thing")],
        },
    )
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    row = _by_title(_json_doc(proc.stdout))["Ship the thing"]
    assert row["ticks"] == 3, f"expected 3 ticks; got row {row!r}"


# ==========================================================================
# Behavior 2 -- a title in only 1 of 3 ticks is REPORTED at 1, never filtered.
# ==========================================================================
def test_b02_goal_in_one_of_three_ticks_is_included_at_count_one(tmp_path: Path) -> None:
    out_dir = _write_stream(
        tmp_path / "stream",
        {
            1: [_goal("Ship the thing"), _goal("Only once")],
            2: [_goal("Ship the thing")],
            3: [_goal("Ship the thing")],
        },
    )
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    by_title = _by_title(_json_doc(proc.stdout))
    assert "Only once" in by_title, (
        f"a one-tick goal must be included, not filtered; rows: {sorted(by_title)}"
    )
    assert by_title["Only once"]["ticks"] == 1, by_title["Only once"]


# ==========================================================================
# Behavior 3 -- cross-tick identity is the NORMALIZED title, never the id.
# ==========================================================================
def test_b03_titles_differing_only_in_case_and_space_are_one_row(tmp_path: Path) -> None:
    """Two slates, two distinct ``CandidateGoal.id`` values, one logical goal.

    ``_goal`` mints a fresh id per call, so matching by id would yield two rows
    of one tick each. Matching by ``title.strip().lower()`` yields one row of 2.
    """
    out_dir = _write_stream(
        tmp_path / "stream",
        {1: [_goal("Ship the thing")], 2: [_goal("   SHIP The Thing   ")]},
    )
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    rows = _rows(_json_doc(proc.stdout))
    assert len(rows) == 1, f"whitespace/case variants must collapse to ONE row; got {rows!r}"
    assert rows[0]["ticks"] == 2, rows[0]


# ==========================================================================
# Behavior 4 -- duplicates INSIDE one slate contribute at most one occurrence.
# ==========================================================================
def test_b04_duplicate_titles_within_one_slate_count_once(tmp_path: Path) -> None:
    out_dir = _write_stream(
        tmp_path / "stream",
        {1: [_goal("Ship the thing"), _goal("ship the THING")]},
    )
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    doc = _json_doc(proc.stdout)
    rows = _rows(doc)
    assert len(rows) == 1, f"one normalized title must yield one row; got {rows!r}"
    assert rows[0]["ticks"] == 1, (
        f"a single tick cannot inflate a count to 2; got {rows[0]!r}"
    )
    assert doc["total_ticks"] == 1, doc


# ==========================================================================
# Behavior 5 -- first_seen/last_seen are the LOWEST/HIGHEST TICK INDEX.
# ==========================================================================
def test_b05_first_and_last_seen_are_tick_indexes_not_positions(tmp_path: Path) -> None:
    """Ticks 1/5/9 -- a 0-based position would report 0/2 and 1, not 1/9 and 5."""
    out_dir = _write_stream(
        tmp_path / "stream",
        {
            1: [_goal("Everywhere")],
            5: [_goal("Everywhere"), _goal("Middle only")],
            9: [_goal("Everywhere")],
        },
    )
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    by_title = _by_title(_json_doc(proc.stdout))
    assert (by_title["Everywhere"]["first_seen"], by_title["Everywhere"]["last_seen"]) == (
        1,
        9,
    ), by_title["Everywhere"]
    assert (by_title["Middle only"]["first_seen"], by_title["Middle only"]["last_seen"]) == (
        5,
        5,
    ), by_title["Middle only"]


# ==========================================================================
# Behavior 6 -- the displayed title and score come from the LAST tick seen.
# ==========================================================================
def test_b06_title_and_score_come_from_the_last_tick_seen(tmp_path: Path) -> None:
    newest = _goal("Ship The Thing", impact=5.0, urgency=5.0)
    oldest = _goal("ship the thing", impact=1.0, urgency=1.0)
    assert newest.score != oldest.score, "fixture must make the two spellings distinguishable"
    out_dir = _write_stream(tmp_path / "stream", {1: [oldest], 2: [newest]})
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    rows = _rows(_json_doc(proc.stdout))
    assert len(rows) == 1, rows
    assert rows[0]["title"] == "Ship The Thing", (
        f"the newest spelling must win (the `diff` precedent); got {rows[0]!r}"
    )
    assert rows[0]["score"] == pytest.approx(newest.score), rows[0]


# ==========================================================================
# Behavior 7 -- total order: ticks desc, score desc, normalized title asc.
# ==========================================================================
def test_b07_ranking_is_ticks_then_score_then_title(tmp_path: Path) -> None:
    plain = {"impact": 3.0, "urgency": 3.0}
    out_dir = _write_stream(
        tmp_path / "stream",
        {
            1: [_goal("beta two ticks", **plain), _goal("alpha one tick", **plain)],
            2: [
                _goal("beta two ticks", **plain),
                _goal("zeta high score", impact=5.0, urgency=5.0),
                _goal("cee one tick", **plain),
            ],
        },
    )
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert _titles(_json_doc(proc.stdout)) == [
        "beta two ticks",
        "zeta high score",
        "alpha one tick",
        "cee one tick",
    ], "order must be ticks desc, then score desc, then normalized title asc"


# ==========================================================================
# Behavior 8 -- the report states the total tick count read.
# ==========================================================================
def test_b08_total_tick_count_equals_the_number_of_stream_slates(tmp_path: Path) -> None:
    out_dir = _write_stream(
        tmp_path / "stream",
        {1: [_goal("A")], 4: [_goal("B")], 7: [_goal("C")]},
    )
    slates = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    assert len(slates) == 3, slates
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert _json_doc(proc.stdout)["total_ticks"] == 3, proc.stdout
    human = _run("trend", "--dir", str(out_dir), cwd=tmp_path)
    assert human.returncode == 0, f"stderr:\n{human.stderr}"
    assert any("3" in ln for ln in _lines(human.stdout) if "tick" in ln.lower()), (
        f"the human report must state the total tick count; got:\n{human.stdout}"
    )


# ==========================================================================
# Behavior 9 -- a --dir that is missing, or is not a directory: exit 2.
# ==========================================================================
@pytest.mark.parametrize("kind", ["missing", "regular_file"])
def test_b09_bad_dir_prints_one_error_line_and_exits_2(tmp_path: Path, kind: str) -> None:
    if kind == "missing":
        target = tmp_path / "nope"
    else:
        target = tmp_path / "afile"
        target.write_text("not a directory", encoding="utf-8")
    proc = _run("trend", "--dir", str(target), cwd=tmp_path)
    assert proc.returncode == 2, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert len(_error_lines(proc.stderr)) == 1, f"stderr:\n{proc.stderr}"
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.stdout.strip() == "", f"a usage error must load nothing; stdout:\n{proc.stdout}"


# ==========================================================================
# Behavior 10 -- N=0 stream slates is a usage error naming the count; N=1 is NOT.
# ==========================================================================
def test_b10a_zero_stream_slates_exits_2_reporting_the_count(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.txt").write_text("no slates here", encoding="utf-8")
    proc = _run("trend", "--dir", str(empty), cwd=tmp_path)
    assert proc.returncode == 2, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    errors = _error_lines(proc.stderr)
    assert len(errors) == 1, f"stderr:\n{proc.stderr}"
    assert "0" in errors[0], f"the error must report the count found (0); got {errors[0]!r}"


def test_b10b_exactly_one_stream_slate_is_a_valid_report(tmp_path: Path) -> None:
    """Deliberately UNLIKE ``diff --dir``, which requires >=2."""
    out_dir = _write_stream(tmp_path / "stream", {4: [_goal("Solo goal")]})
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    doc = _json_doc(proc.stdout)
    assert doc["total_ticks"] == 1, doc
    rows = _rows(doc)
    assert len(rows) == 1 and rows[0]["ticks"] == 1, rows
    assert (rows[0]["first_seen"], rows[0]["last_seen"]) == (4, 4), rows[0]


# ==========================================================================
# Behavior 11 -- non-stream entries are skipped and excluded from the total.
# ==========================================================================
def test_b11_non_stream_entries_are_skipped_and_not_counted(tmp_path: Path) -> None:
    """A wrongly-named FILE and a rightly-named DIRECTORY are both non-ticks."""
    out_dir = _write_stream(tmp_path / "stream", {1: [_goal("Real")], 2: [_goal("Real")]})
    (out_dir / "notes.txt").write_text("prose", encoding="utf-8")
    (out_dir / "slate-999.json").mkdir()
    (out_dir / "slate-999.json" / "inner.json").write_text("{}", encoding="utf-8")
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    doc = _json_doc(proc.stdout)
    assert doc["total_ticks"] == 2, (
        f"only the 2 real stream FILES are ticks; a decoy dir and a stray file are not: {doc!r}"
    )
    assert _by_title(doc)["Real"]["ticks"] == 2, doc


# ==========================================================================
# Behavior 12 -- --json is ONE object with explicit keys; same exit contract.
# ==========================================================================
def test_b12a_json_object_carries_explicit_keys_only(tmp_path: Path) -> None:
    out_dir = _write_stream(tmp_path / "stream", {1: [_goal("A")], 2: [_goal("A")]})
    proc = _run("trend", "--dir", str(out_dir), "--json", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    doc = _json_doc(proc.stdout)
    row = _rows(doc)[0]
    assert set(row) == {"title", "score", "ticks", "first_seen", "last_seen"}, (
        f"no pydantic model_dump leakage: unexpected keys {sorted(set(row))}"
    )
    for leaked in ("id", "rationale", "impact", "urgency", "effort_weight", "sources"):
        assert leaked not in row, f"`{leaked}` leaked into the trend row: {row!r}"


def test_b12b_exit_contract_is_identical_with_and_without_json(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    good = _write_stream(tmp_path / "stream", {1: [_goal("A")]})
    for args, expected in ((["--dir", str(empty)], 2), (["--dir", str(good)], 0)):
        plain = _run("trend", *args, cwd=tmp_path)
        as_json = _run("trend", *args, "--json", cwd=tmp_path)
        assert plain.returncode == expected, f"{args} plain: {plain.returncode}"
        assert as_json.returncode == plain.returncode, (
            f"{args}: --json changed the exit code {plain.returncode} -> {as_json.returncode}"
        )


# ==========================================================================
# Behavior 13 -- LLM-free and read-only (capability denial, not prose scanning).
# ==========================================================================
def test_b13a_builds_no_llm_client_and_runs_no_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Deny the capability rather than scanning for the words (iter-177 precedent)."""
    from proactive_loop import cli as cli_mod
    from proactive_loop import collectors as collectors_mod

    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("trend must build no LLMClient and run no collector")

    monkeypatch.setattr(cli_mod, "create_client", _boom)
    monkeypatch.setattr(collectors_mod, "all_collectors", _boom)

    out_dir = _write_stream(tmp_path / "stream", {1: [_goal("A")], 2: [_goal("A")]})
    try:
        rc = cli_mod.main(["trend", "--dir", str(out_dir)])
    except SystemExit as exc:  # pragma: no cover -- main() returns an int in this repo
        rc = exc.code if isinstance(exc.code, int) else 1
    out = capsys.readouterr().out
    assert rc == 0, f"trend must exit 0 with both capabilities denied; stdout:\n{out}"
    assert out.strip(), "trend must still print its report with capabilities denied"


def test_b13b_writes_no_file_and_succeeds_under_a_hostile_provider(tmp_path: Path) -> None:
    out_dir = _write_stream(tmp_path / "stream", {1: [_goal("A")], 2: [_goal("A")]})
    before = sorted(p.name for p in out_dir.iterdir())
    proc = _run(
        "trend", "--provider", "anthropic", "--dir", str(out_dir), "--json", cwd=tmp_path
    )
    assert proc.returncode == 0, (
        f"a read-only verb must not need a reachable provider; stderr:\n{proc.stderr}"
    )
    assert sorted(p.name for p in out_dir.iterdir()) == before, "trend must write no file"
    assert not (tmp_path / ".pla_runs").exists(), "trend must not create a state dir"


# ==========================================================================
# Behavior 14 -- a corrupt or schema-invalid slate: one error: line, exit 1.
# ==========================================================================
@pytest.mark.parametrize(
    ("label", "payload"),
    [("malformed_json", "{ this is not json"), ("schema_invalid", '{"goals": [{"title": 5}]}')],
)
def test_b14_corrupt_slate_is_one_error_line_at_exit_1(
    tmp_path: Path, label: str, payload: str
) -> None:
    out_dir = _write_stream(tmp_path / f"stream-{label}", {1: [_goal("Fine")]})
    (out_dir / "slate-002.json").write_text(payload, encoding="utf-8")
    proc = _run("trend", "--dir", str(out_dir), cwd=tmp_path)
    assert proc.returncode == 1, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert len(_error_lines(proc.stderr)) == 1, f"stderr:\n{proc.stderr}"
    assert "Traceback" not in proc.stderr, f"never a traceback; stderr:\n{proc.stderr}"


# ==========================================================================
# Behavior 15 -- trend is discoverable, and its own help describes both flags.
# ==========================================================================
def test_b15a_trend_is_listed_in_top_level_help(tmp_path: Path) -> None:
    proc = _run("--help", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert "trend" in proc.stdout, f"`trend` missing from top-level help:\n{proc.stdout}"


def test_b15b_trend_help_describes_dir_and_json(tmp_path: Path) -> None:
    proc = _run("trend", "--help", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    for flag in ("--dir", "--json"):
        assert flag in proc.stdout, f"`pla trend --help` must describe {flag}:\n{proc.stdout}"


# ==========================================================================
# Behavior 16 -- the live subcommand count is 17, trend included.
# ==========================================================================
_CHOICES_RE = re.compile(r"\{(scan[^}]*)\}", re.S)


def test_b16_live_subcommand_count_is_seventeen(tmp_path: Path) -> None:
    """Counted from real ``pla --help`` stdout -- the user-visible roster."""
    proc = _run("--help", cwd=tmp_path)
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    match = _CHOICES_RE.search(proc.stdout)
    assert match is not None, f"could not find the subcommand choices in:\n{proc.stdout}"
    verbs = [v for v in re.sub(r"\s+", "", match.group(1)).split(",") if v]
    assert len(verbs) == len(set(verbs)), f"duplicate verbs in help: {verbs}"
    assert "trend" in verbs, verbs
    assert len(verbs) == 17, f"expected 17 verbs after adding `trend`; got {len(verbs)}: {verbs}"
