"""Independent black-box verification of factory iteration 190 (state dir ``iter-188``).

WHAT THIS MODULE IS, AND WHY IT IS SEPARATE FROM ``test_iter190_behavior.py``.
Factory iteration 190 was built in state dir ``iter-187``, reviewed, tested and
then destroyed by a final-gate bookkeeping failure; state dir ``iter-188``
re-landed the identical patch. The re-landed patch ships its own oracle,
``tests/test_iter190_behavior.py``. This module is the RE-LANDING iteration's
independent second opinion on the same eight Expected Behaviors: a different
harness, a different scrubber, a different census technique. Two modules that
agree while sharing no helper code is corroboration; one module re-run is not.

MODULE NAME, derived from the repo and never from the state-dir counter. The two
counters differ here (state dir 188 ships as factory 190) and the offset is not
guaranteed, so the name was derived: the highest tracked
``tests/test_iterNN_behavior.py`` at measurement time was ``190`` (the re-landed
oracle, staged), +1 = ``191``, and ``git cat-file -e
HEAD:tests/test_iter191_behavior.py`` FAILED before a byte was written -- the path
is provably free in HEAD.

FEATURE UNDER TEST: ``pla scan --json`` is a PARSE-TIME alias for ``pla scan
--format json`` -- a two-member mutually exclusive group on the ``scan``
subparser resolving into the EXISTING ``format`` dest, so no rendering code
changes. It takes the machine-readable idiom to the first verb in the CLI's own
help order.

ISOLATION CONTRACT, honored. Nothing under ``src/`` was read; no engineer,
reviewer or fix note was opened; no ``git diff`` was run. Every assertion drives
``proactive_loop.cli.main`` with an argv list and reads back only the exit code,
captured stdout/stderr, and files the CLI itself wrote.

WHY A RAW BYTE COMPARISON IS THE WRONG ORACLE, MEASURED. Two runs of the SAME
flag do not produce identical bytes: every goal ``id`` is a random 12-hex token
and the persisted slate carries a wall-clock ``created_at``. A raw compare would
therefore RED a correct implementation. This module compares under its own
scrubber and runs the CONTROL -- ``--format json`` against ITSELF -- which must
differ raw and agree scrubbed in exactly the same way. It also pins the scrubber
NON-VACUOUS: the table view must stay distinguishable from the JSON view under
it, otherwise "the two views agree" would be a statement about the scrubber.

TRAPS RESPECTED ON PURPOSE
1. AMBIENT TREE. Every workspace, slate, state dir and snapshot lives under
   ``tmp_path``. Nothing asserts on the checkout or on any gitignored path,
   because every ship is re-verified from a throwaway fresh clone.
2. TRAILER PATHS. The table view prints a ``slate written: <path>`` trailer, so
   two runs being compared are pointed at the SAME ``--out`` AND the SAME
   ``--state-dir``; any other harness bakes a path difference into the output and
   then reports the fixture as the regression.
3. INTERPRETER SKEW. CI is a 3.12/3.13 matrix and 3.13 strips the common leading
   docstring indent at compile time, so nothing here asserts on indentation:
   help text is flattened to single-spaced tokens before matching.
4. FUTURE-BRITTLE COUNTS. ``watch --json`` is the named remaining gap. The
   cross-verb census therefore asserts a FLOOR on the sibling count and an
   EXACT set for the exclusive-group membership, so adding ``watch --json``
   later cannot red this build for a correct change.

Coverage, numbered to match the spec's Expected Behaviors:

1. ``--json`` selects the JSON rendering and its stdout equals ``--format
   json``'s under the scrubber, with the self-control and the non-vacuity pin.
2. The persisted slate is unaffected.
3. ``--json`` with a DIFFERENT ``--format`` is a parse-time usage error in
   either argv order: exit 2, empty stdout, ``not allowed with argument``, and
   NEITHER the state dir NOR the out file created.
4. The exclusion holds when the two AGREE, in either argv order.
5. A bare ``scan`` is unchanged and still renders the TABLE.
6. ``--json`` composes with ``--top``, ``--collector``, ``--out``, ``--snapshot``.
7. ``scan --help`` documents the flag as ONE exclusive pair.
8. No other verb changes: ``scan`` is the only verb whose ``--json`` sits in an
   exclusive group, the siblings keep a plain optional, and a sibling still
   emits its JSON object.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"

# The two documented sources of run-to-run variation. Deliberately narrow: a
# 12-hex word and an ISO-8601 instant, nothing else, so the scrubber cannot
# quietly erase a real content difference.
_HEX12 = re.compile(r"\b[0-9a-f]{12}\b")
_INSTANT = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)

# Asserted as a SUBSTRING on purpose: argparse names whichever of the two flags
# it saw SECOND, so the pair ordering inside the message flips with argv order.
_CONFLICT = "not allowed with argument"

# A collector name that provably exists in the live CLI (checked by behavior 6).
_ONE_COLLECTOR = "todos"

# Markers that end the usage block of an argparse help screen.
_HELP_BODY_MARKERS = ("\noptions:", "\npositional arguments:", "\noptional arguments:")


def _scrub(text: str) -> str:
    """Replace only the random goal id and the wall-clock instant."""
    return _INSTANT.sub("<INSTANT>", _HEX12.sub("<ID>", text))


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """argv in -> (exit code, stdout, stderr). Guards return 2; an argparse
    conflict raises SystemExit, so both paths are tolerated."""
    try:
        rc = main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _usage_of(help_text: str) -> str:
    """The usage block only, flattened to single-spaced tokens.

    The option DESCRIPTIONS mention ``--json`` in prose, so a census that
    searched the whole help screen would count prose as a flag declaration.
    """
    cut = len(help_text)
    for marker in _HELP_BODY_MARKERS:
        idx = help_text.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return " ".join(help_text[:cut].split())


def _bracket_groups(usage: str) -> list[str]:
    return re.findall(r"\[[^\[\]]*\]", usage)


def _build_workspace(root: Path) -> Path:
    """A small tree that provably emits signals from more than one collector."""
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "keep.py").write_text("k = 5\n", encoding="utf-8")
    filler = "\n".join(f"line {i}" for i in range(1, 12))
    (root / "notes.md").write_text(
        filler + "\n- TODO: alpha here\n- TODO: beta here\n", encoding="utf-8"
    )
    return root


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    return _build_workspace(tmp_path / "ws")


def _scan_argv(
    ws_dir: Path,
    *,
    out: Path,
    state_dir: Path,
    view: list[str] | None = None,
    extra: list[str] | None = None,
) -> list[str]:
    """``view`` is spliced in VERBATIM so a test controls flag ORDER."""
    return [
        "scan",
        "--workspace", str(ws_dir),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--out", str(out),
        "--state-dir", str(state_dir),
        *(view or []),
        *(extra or []),
    ]


# ---------------------------------------------------------------------------
# Behavior 1 -- ``--json`` selects the JSON rendering.
# ---------------------------------------------------------------------------


def test_b01_json_stdout_equals_format_json_under_the_scrubber(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "slate.json"
    state = tmp_path / "state"
    rc_alias, alias_out, alias_err = _run(
        _scan_argv(ws, out=out, state_dir=state, view=["--json"]), capsys
    )
    rc_long, long_out, long_err = _run(
        _scan_argv(ws, out=out, state_dir=state, view=["--format", "json"]), capsys
    )
    assert rc_alias == 0, f"--json exited {rc_alias}; stderr={alias_err!r}"
    assert rc_long == 0, f"--format json exited {rc_long}; stderr={long_err!r}"
    # Exactly one JSON object on stdout, no trailer: the whole stream parses.
    doc = json.loads(alias_out)
    assert isinstance(doc, dict), f"--json stdout is not one object: {type(doc)!r}"
    assert alias_out.strip().endswith("}"), "a trailer follows the JSON object"
    assert _scrub(alias_out) == _scrub(long_out)


def test_b01_control_format_json_against_itself_differs_the_same_way(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The control that makes the comparison above meaningful.

    If this passes, a RAW compare of the two views would have failed a CORRECT
    implementation, and the scrubbed equality above is not hiding anything the
    same flag does not already do to itself.
    """
    out = tmp_path / "slate.json"
    state = tmp_path / "state"
    argv = _scan_argv(ws, out=out, state_dir=state, view=["--format", "json"])
    rc_one, one, _ = _run(argv, capsys)
    rc_two, two, _ = _run(argv, capsys)
    assert (rc_one, rc_two) == (0, 0)
    assert one != two, "the same flag produced identical bytes twice; the ids are not random"
    assert _scrub(one) == _scrub(two)


def test_b01_the_scrubber_is_not_vacuous(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "slate.json"
    state = tmp_path / "state"
    rc_table, table_out, _ = _run(_scan_argv(ws, out=out, state_dir=state), capsys)
    rc_json, json_out, json_err = _run(
        _scan_argv(ws, out=out, state_dir=state, view=["--json"]), capsys
    )
    # Both legs must SUCCEED, otherwise a refused --json would leave an empty
    # stdout that trivially differs from the table and this pin would pass
    # while proving nothing.
    assert rc_table == 0
    assert rc_json == 0, f"--json exited {rc_json}; stderr={json_err!r}"
    assert _scrub(table_out) != _scrub(json_out), (
        "the scrubber erases the difference between the table and JSON views, "
        "so every other equality in this module would be vacuous"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- the persisted slate is unaffected; the alias changes the VIEW.
# ---------------------------------------------------------------------------


def test_b02_persisted_slate_is_unaffected_by_the_alias(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    alias_out = tmp_path / "alias.json"
    long_out = tmp_path / "long.json"
    state = tmp_path / "state"
    rc_alias, _, _ = _run(
        _scan_argv(ws, out=alias_out, state_dir=state, view=["--json"]), capsys
    )
    rc_long, _, _ = _run(
        _scan_argv(ws, out=long_out, state_dir=state, view=["--format", "json"]), capsys
    )
    assert (rc_alias, rc_long) == (0, 0)
    assert alias_out.is_file() and long_out.is_file()
    alias_text = alias_out.read_text(encoding="utf-8")
    long_text = long_out.read_text(encoding="utf-8")
    # The two out PATHS differ by construction, so scrub them out of the way
    # before comparing content -- the trailer-path trap in file form.
    alias_norm = _scrub(alias_text).replace(str(alias_out), "<OUT>")
    long_norm = _scrub(long_text).replace(str(long_out), "<OUT>")
    assert alias_norm == long_norm
    slate = json.loads(alias_text)
    assert isinstance(slate, dict) and slate.get("goals"), "empty slate written"


# ---------------------------------------------------------------------------
# Behavior 3 -- a DIFFERENT --format is a PARSE-time usage error.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "view",
    [
        ["--json", "--format", "csv"],
        ["--format", "csv", "--json"],
    ],
    ids=["json-then-format", "format-then-json"],
)
def test_b03_conflicting_format_is_rejected_before_any_work(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], view: list[str]
) -> None:
    out = tmp_path / "never_written.json"
    state = tmp_path / "never_created"
    rc, stdout, stderr = _run(
        _scan_argv(ws, out=out, state_dir=state, view=view), capsys
    )
    assert rc == 2, f"expected exit 2, got {rc}; stderr={stderr!r}"
    assert stdout == "", f"stdout was not empty on a usage error: {stdout!r}"
    assert _CONFLICT in stderr, f"stderr lacks {_CONFLICT!r}: {stderr!r}"
    # The filesystem is what proves the rejection precedes provider
    # construction and collection, not merely rendering.
    assert not state.exists(), "the state dir was created despite a usage error"
    assert not out.exists(), "a slate was written despite a usage error"


# ---------------------------------------------------------------------------
# Behavior 4 -- the exclusion holds even when the two AGREE.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "view",
    [
        ["--json", "--format", "json"],
        ["--format", "json", "--json"],
    ],
    ids=["json-then-format", "format-then-json"],
)
def test_b04_the_agreeing_pair_is_still_a_usage_error(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], view: list[str]
) -> None:
    out = tmp_path / "never_written.json"
    state = tmp_path / "never_created"
    rc, stdout, stderr = _run(
        _scan_argv(ws, out=out, state_dir=state, view=view), capsys
    )
    assert rc == 2, f"the agreeing pair was accepted (exit {rc}); a precedence rule leaked in"
    assert stdout == ""
    assert _CONFLICT in stderr
    assert not state.exists()


# ---------------------------------------------------------------------------
# Behavior 5 -- a bare ``scan`` is unchanged (the shared-dest default trap).
# ---------------------------------------------------------------------------


def test_b05_bare_scan_still_renders_the_table_view(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "slate.json"
    state = tmp_path / "state"
    rc_bare, bare_out, bare_err = _run(_scan_argv(ws, out=out, state_dir=state), capsys)
    rc_table, table_out, _ = _run(
        _scan_argv(ws, out=out, state_dir=state, view=["--format", "table"]), capsys
    )
    assert rc_bare == 0, f"a bare scan exited {rc_bare}; stderr={bare_err!r}"
    assert rc_table == 0
    assert _scrub(bare_out) == _scrub(table_out), (
        "a bare scan no longer matches --format table: the shared format dest "
        "lost its default"
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(bare_out)


# ---------------------------------------------------------------------------
# Behavior 6 -- ``--json`` composes with the other ``scan`` flags.
# ---------------------------------------------------------------------------


def test_b06_json_composes_with_top_and_leaves_the_slate_complete(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "slate.json"
    state = tmp_path / "state"
    rc, stdout, stderr = _run(
        _scan_argv(ws, out=out, state_dir=state, view=["--json"], extra=["--top", "1"]),
        capsys,
    )
    assert rc == 0, f"--json --top 1 exited {rc}; stderr={stderr!r}"
    doc = json.loads(stdout)
    assert len(doc["goals"]) == 1, f"--top 1 printed {len(doc['goals'])} goals"
    written = json.loads(out.read_text(encoding="utf-8"))
    assert len(written["goals"]) > 1, "--top truncated the persisted slate"


def test_b06_json_composes_with_collector_out_and_snapshot(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "custom" / "slate.json"
    out.parent.mkdir()
    state = tmp_path / "state"
    snap = tmp_path / "snapshot.json"
    rc, stdout, stderr = _run(
        _scan_argv(
            ws,
            out=out,
            state_dir=state,
            view=["--json"],
            extra=["--collector", _ONE_COLLECTOR, "--snapshot", str(snap)],
        ),
        capsys,
    )
    assert rc == 0, f"composed invocation exited {rc}; stderr={stderr!r}"
    assert isinstance(json.loads(stdout), dict)
    assert out.is_file(), "--out was ignored under --json"
    assert snap.is_file(), "--snapshot was ignored under --json"
    snapshot = json.loads(snap.read_text(encoding="utf-8"))
    assert "signals" in snapshot and "workspace_root" in snapshot


# ---------------------------------------------------------------------------
# Behavior 7 -- ``scan --help`` documents the flag as ONE exclusive pair.
# ---------------------------------------------------------------------------


def test_b07_scan_help_shows_json_and_format_as_one_exclusive_pair(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc, stdout, _ = _run(["scan", "--help"], capsys)
    assert rc == 0
    assert "--json" in stdout, "scan --help does not mention --json"
    usage = _usage_of(stdout)
    holding_json = [g for g in _bracket_groups(usage) if "--json" in g]
    assert len(holding_json) == 1, (
        f"expected exactly one usage group holding --json, got {holding_json!r}"
    )
    group = holding_json[0]
    assert "|" in group, f"--json is a separate optional, not an exclusive pair: {group!r}"
    assert "--format" in group, f"--json is paired with the wrong flag: {group!r}"


# ---------------------------------------------------------------------------
# Behavior 8 -- no other verb changes.
# ---------------------------------------------------------------------------


def _verbs(capsys: pytest.CaptureFixture[str]) -> list[str]:
    rc, stdout, _ = _run(["--help"], capsys)
    assert rc == 0
    candidates = [m for m in re.findall(r"\{([a-z_,]+)\}", stdout) if "scan," in m]
    assert candidates, "could not read the subcommand list from the top-level help"
    return candidates[0].split(",")


def test_b08_scan_is_the_only_verb_whose_json_joins_an_exclusive_group(
    capsys: pytest.CaptureFixture[str],
) -> None:
    verbs = _verbs(capsys)
    assert len(verbs) >= 16, f"only {len(verbs)} verbs discovered: {verbs!r}"
    exclusive: list[str] = []
    plain: list[str] = []
    for verb in verbs:
        rc, stdout, _ = _run([verb, "--help"], capsys)
        assert rc == 0, f"{verb} --help exited {rc}"
        groups = [g for g in _bracket_groups(_usage_of(stdout)) if "--json" in g]
        if not groups:
            continue
        if any("|" in g for g in groups):
            exclusive.append(verb)
        else:
            plain.append(verb)
    assert exclusive == ["scan"], f"exclusive-group --json spread to {exclusive!r}"
    # A FLOOR, not an exact count: `watch --json` is the named remaining gap and
    # adding it later must not red this build.
    assert len(plain) >= 14, f"sibling --json flags regressed to {len(plain)}: {plain!r}"


def test_b08_a_sibling_verb_still_emits_its_json_object(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, stdout, stderr = _run(
        ["signals", "--workspace", str(ws), "--json"], capsys
    )
    assert rc == 0, f"signals --json exited {rc}; stderr={stderr!r}"
    doc = json.loads(stdout)
    assert isinstance(doc, dict) and "signals" in doc
