"""Black-box behavior tests for state-dir iteration 173 (ships as ``factory iter 177``).

Feature under test: ``pla verify --slate S --snapshot N`` (roadmap #201) -- a
read-only, LLM-free inspector that resolves every goal's cited ``sources``
against the signals a collector actually emitted, and reports the ones it
cannot find. It is the missing consumer of ``scan --snapshot FILE``: before it,
a hallucinated ``sources`` entry read exactly like a perceived one.

MODULE NAME. This repo names behavior modules by the FACTORY iteration number,
which runs ahead of the state-dir counter (``tests/test_iter109_behavior.py``
documents the same offset for itself). The previous ship is
``aae1a80 (factory iter 176)`` and ``tests/test_iter176_behavior.py`` already
exists, so state-dir 173 is factory 177 and this file is 177 -- writing 173
would have SILENTLY OVERWRITTEN a shipped oracle (the iter-172 destroyed-oracle
lesson).

WHY BEHAVIORS ARE DRIVEN THROUGH A REAL SUBPROCESS. Behaviors 3, 7 and 9 are
claims about whole streams (an exact LAST stdout line, stdout parsing as exactly
ONE document with no trailer, an EMPTY stdout beside one ``error:`` line on
stderr). An in-process ``capsys`` run cannot falsify those honestly, so this
module spends real ``pla`` console-script invocations (the
iter-114 / iter-152 / iter-163 convention). Cost is bounded: ONE module-scoped
scan builds the fixture pair every happy-path test shares, each verify run is
~0.2s, and the malformed-snapshot ladder is one parametrized run per case.
Behavior 6's capability-denial half is the one deliberate in-process test --
denying a capability requires monkeypatching, which cannot cross a process
boundary.

CLAUSE 2 IS PINNED BY HAND-BUILT PAIRS, NOT BY THE FIXTURE PAIR -- AND THAT
DEPARTS FROM THE SPEC ON A MEASUREMENT. ``pm.md`` behavior 4 states that "only
3 of 6" fixture sources match exactly and the other 3 resolve ONLY after the
``:LINE`` suffix is stripped, so that a clause-1-only build would "report half
the bundled demo as fabricated". MEASURED against the pair this build actually
writes, that is not reproducible: all 6 cited sources equal a snapshot ``path``
EXACTLY (0 need clause 2), so the fixture pair passes under a clause-1-only
implementation and cannot be the clause-2 oracle. The known-good pair is still
asserted at ZERO unresolved -- it is the false-accusation trap and the reason
this feature must be measured against a good sample before a planted bad one --
but clause 2 gets its own minimal pairs that red in BOTH directions. See
``tester.md`` for the PM feedback.

ISOLATION CONTRACT (honored, with one disclosed exception). Every assertion here
is derived from this iteration's spec ("Expected Behaviors" in ``pm.md``), from
the repo's own ``tests/`` conventions, from ``README.md`` / ``ROADMAP.md``, and
from the product's OBSERVABLE output obtained by RUNNING it. **No file under
``src/`` was read and no ``git diff`` was inspected.** Disclosed exception: this
is retry attempt 2, and the retry directive requires checking what an earlier
attempt left behind, so ``engineer.md`` and ``fix_review.md`` were seen during
triage; no assertion in this module is taken from them -- the two names they
mention (``cli.create_client``, ``collectors.all_collectors``) were rediscovered
independently by enumerating the imported package's public attributes at
runtime. Fully offline and deterministic: the bundled scripted provider only,
no network, no API key. Every invocation is rooted at a PRIVATE COPY of
``examples/fixture_workspace`` under a ``tmp_path_factory`` dir (the iter-142
shared-mutable-tree hazard).
"""

from __future__ import annotations

import argparse
import hashlib
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

# Spec behavior 1: the live subparser-choice count after this additive verb.
# A frozen literal ON PURPOSE: b01 below compares it against the LIVE parser, so deriving
# it from build_parser() would collapse that assertion into `len(x) == len(x)`. The former
# `177 - 161` spelling claimed to stop a literal drifting and then drifted anyway, so it is
# retired -- one honest literal, bumped by each additive verb (iter-197 added `trend`).
_EXPECTED_VERB_COUNT = 17

# Spec behavior 3: the exact human-mode trailer shape.
_TRAILER_RE = re.compile(
    r"^verified: (?P<goals>\d+) goals, (?P<sources>\d+) sources, (?P<unresolved>\d+) unresolved$"
)

# Spec behavior 7: the closed ``--json`` document.
_DOC_KEYS = frozenset({"slate", "snapshot", "goals", "source_count", "unresolved_count"})
_GOAL_KEYS = frozenset({"id", "title", "resolved", "unresolved"})

_RESOLVED = "resolved: "
_UNRESOLVED = "UNRESOLVED: "


# ---------------------------------------------------------------------------
# Helpers (iter-114 / iter-152 / iter-163 console-script convention)
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
        timeout=120,
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lines(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if ln.strip()]


def _signal_entry(path: str, summary: str) -> dict[str, object]:
    """One snapshot entry carrying exactly the six published identity keys."""
    return {
        "source": "synthetic",
        "kind": "notes",
        "summary": summary,
        "detail": "synthetic detail",
        "path": path,
        "weight": 1.0,
    }


@pytest.fixture(scope="module")
def pair(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """The bundled fixture pair: one offline scan writing BOTH slate and snapshot.

    This is the known-GOOD sample. Everything downstream reuses it, so the whole
    module costs exactly one scan.
    """
    root = tmp_path_factory.mktemp("verify")
    ws = root / "workspace"
    shutil.copytree(FIXTURE, ws)
    slate = root / "slate.json"
    snapshot = root / "snapshot.json"
    proc = _run(
        "scan",
        "--workspace",
        str(ws),
        "--provider",
        "scripted",
        "--scripted-responses",
        str(SCRIPT),
        "--state-dir",
        str(root / "state"),
        "--out",
        str(slate),
        "--snapshot",
        str(snapshot),
        cwd=root,
    )
    assert proc.returncode == 0, f"fixture scan must succeed offline; stderr={proc.stderr!r}"
    assert slate.is_file() and snapshot.is_file(), "scan must write both --out and --snapshot"
    return {"root": root, "slate": slate, "snapshot": snapshot}


@pytest.fixture(scope="module")
def good(pair: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    """One human-mode verify run over the known-good pair."""
    return _run(
        "verify",
        "--slate",
        str(pair["slate"]),
        "--snapshot",
        str(pair["snapshot"]),
        cwd=pair["root"],
    )


def _derive_slate(pair: dict[str, Path], dest: Path, sources: list[str]) -> Path:
    """A one-goal slate cloned from the real slate, with ``sources`` replaced.

    Cloned rather than hand-composed so the slate schema is whatever the product
    actually writes -- a transcribed slate would rot the moment a field is added.
    """
    doc = json.loads(pair["slate"].read_text(encoding="utf-8"))
    goal = json.loads(json.dumps(doc["goals"][0]))
    goal["sources"] = sources
    doc["goals"] = [goal]
    dest.write_text(json.dumps(doc), encoding="utf-8")
    return dest


# ==========================================================================
# Behavior 1 -- the verb exists and states its contract
# ==========================================================================


def test_b01_verify_help_exits_zero_and_names_both_required_options(
    pair: dict[str, Path],
) -> None:
    proc = _run("verify", "--help", cwd=pair["root"])
    assert proc.returncode == 0, f"`verify --help` must exit 0; got {proc.returncode}"
    assert "--slate" in proc.stdout, "help must name --slate"
    assert "--snapshot" in proc.stdout, "help must name --snapshot"


def test_b01_verify_is_a_registered_subparser_choice_and_count_is_live(
    pair: dict[str, Path],
) -> None:
    parser = build_parser()
    subs = [
        a
        for a in parser._subparsers._group_actions  # noqa: SLF001 -- repo convention
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(subs) == 1, f"expected exactly one subparser action, got {len(subs)}"
    choices = subs[0].choices
    assert "verify" in choices, f"`verify` must be registered; got {sorted(choices)}"
    assert len(choices) == _EXPECTED_VERB_COUNT, (
        f"live verb count must be {_EXPECTED_VERB_COUNT} after this additive verb; "
        f"got {len(choices)} ({sorted(choices)})"
    )
    top = _run("--help", cwd=pair["root"])
    assert top.returncode == 0
    assert "verify" in top.stdout, "`pla --help` must list the verify subcommand"


@pytest.mark.parametrize("omit", ["--slate", "--snapshot"])
def test_b01_each_option_is_required_so_omitting_it_is_a_usage_error(
    pair: dict[str, Path], omit: str
) -> None:
    args = ["verify", "--slate", str(pair["slate"]), "--snapshot", str(pair["snapshot"])]
    idx = args.index(omit)
    del args[idx : idx + 2]
    proc = _run(*args, cwd=pair["root"])
    assert proc.returncode == 2, (
        f"omitting {omit} must be an argparse usage error (exit 2); got "
        f"{proc.returncode}; stderr={proc.stderr!r}"
    )


# ==========================================================================
# Behavior 2 -- happy path on the bundled fixture pair
# ==========================================================================


def test_b02_happy_path_exits_zero_and_prints_one_block_per_goal_in_rank_order(
    good: subprocess.CompletedProcess[str],
) -> None:
    assert good.returncode == 0, f"verify must exit 0 on a clean pair; stderr={good.stderr!r}"
    ranks = [
        int(m.group(1))
        for m in (re.match(r"^(\d+)\. \S", ln) for ln in _lines(good.stdout))
        if m
    ]
    assert ranks, f"expected `<rank>. <title>` goal blocks; got {good.stdout!r}"
    assert ranks == sorted(ranks) and ranks == list(range(1, len(ranks) + 1)), (
        f"goal blocks must be printed in ranked() order starting at 1; got {ranks}"
    )


def test_b02_every_fixture_source_is_reported_resolved_and_none_unresolved(
    good: subprocess.CompletedProcess[str], pair: dict[str, Path]
) -> None:
    slate = json.loads(pair["slate"].read_text(encoding="utf-8"))
    cited = [s for g in slate["goals"] for s in g["sources"]]
    resolved = [
        ln.strip()[len(_RESOLVED) :] for ln in good.stdout.splitlines()
        if ln.strip().startswith(_RESOLVED)
    ]
    assert _UNRESOLVED not in good.stdout, (
        "the bundled demo slate is genuine: reporting ANY source unresolved here is the "
        f"fail-closed accusation this feature must never make; got {good.stdout!r}"
    )
    assert len(resolved) == len(cited), (
        f"every cited source must be reported once: {len(cited)} cited, {len(resolved)} printed"
    )
    for src in cited:
        assert src in resolved, f"source {src!r} must be reproduced verbatim; got {resolved}"


def test_b02_source_lines_are_indented_under_their_goal_block(
    good: subprocess.CompletedProcess[str],
) -> None:
    for ln in good.stdout.splitlines():
        if ln.strip().startswith((_RESOLVED, _UNRESOLVED)):
            assert ln != ln.lstrip(), f"source line must be indented under its goal: {ln!r}"


# ==========================================================================
# Behavior 3 -- the trailer is the summary line
# ==========================================================================


def test_b03_last_human_stdout_line_is_the_trailer_and_its_integers_match_what_was_printed(
    good: subprocess.CompletedProcess[str],
) -> None:
    lines = _lines(good.stdout)
    m = _TRAILER_RE.match(lines[-1])
    assert m is not None, (
        "the LAST non-empty stdout line must be exactly "
        f"`verified: <G> goals, <S> sources, <U> unresolved`; got {lines[-1]!r}"
    )
    printed_resolved = sum(1 for ln in lines if ln.strip().startswith(_RESOLVED))
    printed_unresolved = sum(1 for ln in lines if ln.strip().startswith(_UNRESOLVED))
    goal_blocks = sum(1 for ln in lines if re.match(r"^\d+\. \S", ln))
    assert int(m.group("goals")) == goal_blocks, "trailer goal count must match printed blocks"
    assert int(m.group("sources")) == printed_resolved + printed_unresolved, (
        "trailer source count must match the printed source lines"
    )
    assert int(m.group("unresolved")) == printed_unresolved == 0, (
        "the known-good pair must report zero unresolved"
    )


# ==========================================================================
# Behavior 4 -- the resolution rule, both clauses
# ==========================================================================


def test_b04_clause2_resolves_when_the_snapshot_carries_the_line_suffix(
    pair: dict[str, Path], tmp_path: Path
) -> None:
    """Snapshot path ``README.md:5`` must resolve a source cited as ``README.md``."""
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"signals": [_signal_entry("README.md:5", "s")]}), encoding="utf-8")
    slate = _derive_slate(pair, tmp_path / "slate.json", ["README.md"])
    proc = _run("verify", "--slate", str(slate), "--snapshot", str(snap), cwd=tmp_path)
    assert proc.returncode == 0
    assert _UNRESOLVED not in proc.stdout, (
        "clause 2 must strip a trailing :LINE from the SNAPSHOT side; a clause-1-only "
        f"build reds here. got {proc.stdout!r}"
    )


def test_b04_clause2_resolves_when_the_cited_source_carries_the_line_suffix(
    pair: dict[str, Path], tmp_path: Path
) -> None:
    """Source cited as ``docs/x.md:23`` must resolve against snapshot path ``docs/x.md``."""
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"signals": [_signal_entry("docs/x.md", "s")]}), encoding="utf-8")
    slate = _derive_slate(pair, tmp_path / "slate.json", ["docs/x.md:23"])
    proc = _run("verify", "--slate", str(slate), "--snapshot", str(snap), cwd=tmp_path)
    assert proc.returncode == 0
    assert _UNRESOLVED not in proc.stdout, (
        "clause 2 must strip a trailing :LINE from EITHER side, including the cited "
        f"source; got {proc.stdout!r}"
    )


def test_b04_clause1_also_matches_a_snapshot_summary_not_only_a_path(
    pair: dict[str, Path], tmp_path: Path
) -> None:
    snap = tmp_path / "snap.json"
    snap.write_text(
        json.dumps({"signals": [_signal_entry("some/other/path.py", "SUM-0")]}), encoding="utf-8"
    )
    slate = _derive_slate(pair, tmp_path / "slate.json", ["SUM-0"])
    proc = _run("verify", "--slate", str(slate), "--snapshot", str(snap), cwd=tmp_path)
    assert proc.returncode == 0
    assert _UNRESOLVED not in proc.stdout, (
        f"clause 1 matches a snapshot `summary` as well as a `path`; got {proc.stdout!r}"
    )


@pytest.mark.parametrize(
    ("source", "why"),
    [
        ("readme.md", "matching is case-SENSITIVE because paths are"),
        ("   ", "a source that is empty after strip() never resolves"),
        ("README.md:5:9", "only ONE trailing :<digits> group is stripped"),
    ],
)
def test_b04_negative_cases_stay_unresolved(
    pair: dict[str, Path], tmp_path: Path, source: str, why: str
) -> None:
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"signals": [_signal_entry("README.md", "s")]}), encoding="utf-8")
    slate = _derive_slate(pair, tmp_path / "slate.json", [source])
    proc = _run("verify", "--slate", str(slate), "--snapshot", str(snap), cwd=tmp_path)
    assert proc.returncode == 0, "an unresolved source is REPORTED, never an error"
    assert _UNRESOLVED in proc.stdout, f"{source!r} must stay unresolved: {why}; got {proc.stdout!r}"


# ==========================================================================
# Behavior 5 -- a fabrication is reported, and only it
# ==========================================================================


def test_b05_exactly_the_planted_fabrication_is_marked_unresolved_and_exit_is_still_zero(
    pair: dict[str, Path], tmp_path: Path
) -> None:
    slate_doc = json.loads(pair["slate"].read_text(encoding="utf-8"))
    genuine = slate_doc["goals"][0]["sources"][0]
    planted = "does/not/exist.py"
    slate = _derive_slate(pair, tmp_path / "slate.json", [genuine, planted])
    proc = _run(
        "verify", "--slate", str(slate), "--snapshot", str(pair["snapshot"]), cwd=tmp_path
    )
    assert proc.returncode == 0, "reporting-only: a fabrication does NOT change the exit code"
    lines = _lines(proc.stdout)
    unresolved = [ln.strip()[len(_UNRESOLVED) :] for ln in lines if ln.strip().startswith(_UNRESOLVED)]
    resolved = [ln.strip()[len(_RESOLVED) :] for ln in lines if ln.strip().startswith(_RESOLVED)]
    assert unresolved == [planted], f"exactly the planted source must be flagged; got {unresolved}"
    assert resolved == [genuine], f"the genuine source must stay resolved; got {resolved}"
    m = _TRAILER_RE.match(lines[-1])
    assert m is not None and int(m.group("unresolved")) == 1, (
        f"trailer must count exactly 1 unresolved; got {lines[-1]!r}"
    )


# ==========================================================================
# Behavior 6 -- reporting-only, and provably inert
# ==========================================================================


def test_b06_writes_no_file_and_mutates_neither_input(pair: dict[str, Path], tmp_path: Path) -> None:
    before_slate, before_snap = _sha(pair["slate"]), _sha(pair["snapshot"])
    before_tree = sorted(p.name for p in tmp_path.iterdir())
    proc = _run(
        "verify", "--slate", str(pair["slate"]), "--snapshot", str(pair["snapshot"]), cwd=tmp_path
    )
    assert proc.returncode == 0
    assert _sha(pair["slate"]) == before_slate, "the slate must be byte-identical after a verify"
    assert _sha(pair["snapshot"]) == before_snap, "the snapshot must be byte-identical"
    assert sorted(p.name for p in tmp_path.iterdir()) == before_tree, (
        f"verify must write NO file; cwd gained {sorted(p.name for p in tmp_path.iterdir())}"
    )


def test_b06_builds_no_llm_client_and_runs_no_collector_by_capability_denial(
    pair: dict[str, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Deny the capability rather than scanning source text for the words.

    The iter-172 lesson: a docstring advertising "no LLM, no collectors" makes a
    substring scan report IMPURE on provably clean code. Monkeypatching the two
    entry points to raise tests the CAPABILITY, and is immune to prose.
    """
    from proactive_loop import cli as cli_mod
    from proactive_loop import collectors as collectors_mod

    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("verify must build no LLMClient and run no collector")

    monkeypatch.setattr(cli_mod, "create_client", _boom)
    monkeypatch.setattr(collectors_mod, "all_collectors", _boom)

    argv = ["verify", "--slate", str(pair["slate"]), "--snapshot", str(pair["snapshot"])]
    try:
        rc = cli_mod.main(argv)
    except SystemExit as exc:  # pragma: no cover -- main() returns an int in this repo
        rc = exc.code if isinstance(exc.code, int) else 1
    out = capsys.readouterr().out
    assert rc == 0, "verify must exit 0 with both capabilities denied"
    assert _TRAILER_RE.match(_lines(out)[-1]) is not None, (
        f"the run must still produce its trailer with capabilities denied; got {out!r}"
    )


# ==========================================================================
# Behavior 7 -- ``--json`` is one closed document
# ==========================================================================


def test_b07_json_stdout_is_exactly_one_document_with_exactly_five_top_level_keys(
    pair: dict[str, Path],
) -> None:
    proc = _run(
        "verify",
        "--slate",
        str(pair["slate"]),
        "--snapshot",
        str(pair["snapshot"]),
        "--json",
        cwd=pair["root"],
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    doc = json.loads(proc.stdout)  # ONE document: a trailer would break this parse
    assert isinstance(doc, dict)
    assert set(doc) == _DOC_KEYS, f"exactly {sorted(_DOC_KEYS)}, no more, no fewer; got {sorted(doc)}"
    assert doc["slate"] == str(pair["slate"]), "`slate` echoes the path AS GIVEN"
    assert doc["snapshot"] == str(pair["snapshot"]), "`snapshot` echoes the path AS GIVEN"
    assert "verified:" not in proc.stdout, "no human trailer under --json"
    for goal in doc["goals"]:
        assert set(goal) == _GOAL_KEYS, (
            f"each goal object holds exactly {sorted(_GOAL_KEYS)}; got {sorted(goal)}"
        )
        assert isinstance(goal["resolved"], list) and isinstance(goal["unresolved"], list)
    assert doc["source_count"] == sum(
        len(g["resolved"]) + len(g["unresolved"]) for g in doc["goals"]
    ), "source_count must equal the reported sources"
    assert doc["unresolved_count"] == sum(len(g["unresolved"]) for g in doc["goals"]) == 0


def test_b07_json_goal_order_matches_the_human_ranked_order(pair: dict[str, Path]) -> None:
    human = _run(
        "verify", "--slate", str(pair["slate"]), "--snapshot", str(pair["snapshot"]), cwd=pair["root"]
    )
    js = _run(
        "verify",
        "--slate",
        str(pair["slate"]),
        "--snapshot",
        str(pair["snapshot"]),
        "--json",
        cwd=pair["root"],
    )
    titles = [
        m.group(1) for m in (re.match(r"^\d+\. (.+)$", ln) for ln in _lines(human.stdout)) if m
    ]
    assert [g["title"] for g in json.loads(js.stdout)["goals"]] == titles, (
        "both modes must walk ranked() order"
    )


# ==========================================================================
# Behavior 8 -- an empty slate degrades, it does not error
# ==========================================================================


def test_b08_empty_slate_prints_the_shipped_phrasing_and_exits_zero(
    pair: dict[str, Path], tmp_path: Path
) -> None:
    doc = json.loads(pair["slate"].read_text(encoding="utf-8"))
    doc["goals"] = []
    slate = tmp_path / "empty.json"
    slate.write_text(json.dumps(doc), encoding="utf-8")
    proc = _run("verify", "--slate", str(slate), "--snapshot", str(pair["snapshot"]), cwd=tmp_path)
    assert proc.returncode == 0, f"an empty slate is not an error; stderr={proc.stderr!r}"
    assert "(no goals in slate)" in proc.stdout, (
        f"must reuse the shipped whole-slate `explain` phrasing; got {proc.stdout!r}"
    )
    js = _run(
        "verify",
        "--slate",
        str(slate),
        "--snapshot",
        str(pair["snapshot"]),
        "--json",
        cwd=tmp_path,
    )
    empty = json.loads(js.stdout)
    assert empty["goals"] == [] and empty["source_count"] == 0 and empty["unresolved_count"] == 0


# ==========================================================================
# Behavior 9 -- fail-closed input guards, all before any stdout
# ==========================================================================


def _malformed(kind: str, dest: Path) -> Path:
    if kind == "missing":
        return dest  # deliberately never created
    if kind == "not_utf8":
        dest.write_bytes(b'{"signals": [], "x": "\xff\xfe"}')
        return dest
    payloads: dict[str, object] = {
        "not_json": None,
        "top_level_list": [1, 2],
        "no_signals_array": {"summary": {"total": 0}},
        "entry_not_object": {"signals": [1]},
        "entry_missing_key": {
            "signals": [
                {"source": "a", "kind": "notes", "summary": "s", "detail": "d", "path": "p"}
            ]
        },
    }
    if kind == "not_json":
        dest.write_text("{not json", encoding="utf-8")
    else:
        dest.write_text(json.dumps(payloads[kind]), encoding="utf-8")
    return dest


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "not_utf8",
        "not_json",
        "top_level_list",
        "no_signals_array",
        "entry_not_object",
        "entry_missing_key",
    ],
)
def test_b09_a_malformed_snapshot_prints_one_error_line_and_exits_two_with_empty_stdout(
    pair: dict[str, Path], tmp_path: Path, kind: str
) -> None:
    snap = _malformed(kind, tmp_path / f"snap_{kind}.json")
    proc = _run("verify", "--slate", str(pair["slate"]), "--snapshot", str(snap), cwd=tmp_path)
    assert proc.returncode == 2, (
        f"a {kind} snapshot must be fail-closed at exit 2; got {proc.returncode}; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert proc.stdout == "", f"the guard must fire BEFORE any stdout; got {proc.stdout!r}"
    errs = _lines(proc.stderr)
    assert len(errs) == 1, f"exactly ONE error line; got {errs}"
    assert errs[0].startswith("error: "), f"must be an `error: ` line; got {errs[0]!r}"
    assert str(snap) in errs[0], f"the error must name the offending file; got {errs[0]!r}"


def test_b09_a_missing_slate_exits_two_and_a_corrupt_slate_exits_one(
    pair: dict[str, Path], tmp_path: Path
) -> None:
    missing = _run(
        "verify",
        "--slate",
        str(tmp_path / "nope.json"),
        "--snapshot",
        str(pair["snapshot"]),
        cwd=tmp_path,
    )
    assert missing.returncode == 2, f"a missing slate file -> exit 2; got {missing.returncode}"
    assert missing.stdout == ""
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    bad = _run(
        "verify", "--slate", str(corrupt), "--snapshot", str(pair["snapshot"]), cwd=tmp_path
    )
    assert bad.returncode == 1, (
        f"an unparseable slate -> exit 1 via the main() boundary; got {bad.returncode}"
    )
    assert bad.stdout == ""


# ==========================================================================
# Behavior 10 -- the hardcoded verb-count literals moved in the SAME commit
# ==========================================================================


def test_b10_readme_intro_states_the_live_verb_count_derived_from_the_parser(
    pair: dict[str, Path],
) -> None:
    """Derived, not transcribed: the number is read off the live parser."""
    parser = build_parser()
    subs = [
        a
        for a in parser._subparsers._group_actions  # noqa: SLF001 -- repo convention
        if isinstance(a, argparse._SubParsersAction)
    ]
    live = len(subs[0].choices)
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert re.search(rf"\b{live} CLI verbs\b", text), (
        f"the README PORTFOLIO-INTRO must state the LIVE verb count ({live} CLI verbs) -- "
        "the mandated numeric carve-out. A stale number here reds the build by design."
    )
    stale = [n for n in range(live - 3, live) if re.search(rf"\b{n} CLI verbs\b", text)]
    assert not stale, f"the README still carries a stale verb count: {stale}"


def test_b10_no_test_function_name_embeds_a_verb_count_literal() -> None:
    """A test named ``states_15`` asserting 16 is the decaying-constant defect
    this repo has retired three times (#199, the iter-149 worked example, the
    banned exact test count). Filesystem glob, NOT ``git ls-files``: an
    untracked new module would otherwise be outside the domain and the census
    blind to itself (OPERATOR 2026-08-14)."""
    offenders: list[str] = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        for m in re.finditer(r"^def (test_\w*?_\d+_cli_verbs\w*)", path.read_text(encoding="utf-8"), re.M):
            offenders.append(f"{path.name}:{m.group(1)}")
    assert not offenders, (
        f"test function names must not hardcode a verb count: {offenders}"
    )


def test_b10_cli_reference_below_the_human_owned_marker_documents_verify() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    # The live marker spells the dash as an EM DASH; matched by regex so this
    # assertion cannot red on a punctuation change it does not care about.
    marker = re.search(r"PORTFOLIO INTRO\s*[\u2014-]+\s*human-owned", text)
    assert marker is not None, "the human-owned marker must still be present"
    below = text[marker.end() :]
    assert re.search(r"\|\s*`verify`", below), (
        "the CLI-reference TABLE below the human-owned marker must carry a `verify` row"
    )
