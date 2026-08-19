"""Black-box oracle for factory iteration 190 (state dir ``iter-187``).

Feature under test: ``pla scan --json`` becomes a PARSE-TIME alias for
``pla scan --format json`` -- a two-member mutually exclusive group on the
``scan`` subparser, resolving into the EXISTING ``format`` dest so no rendering
code changes. The idiom every other machine-readable verb already accepts
reaches the first verb in the CLI's own help order.

MODULE NAME, derived from the repo and never from the state-dir counter. The two
counters differ here (state dir 187 ships as factory 190) and the offset is not
guaranteed, so the name was derived: the highest tracked
``tests/test_iterNN_behavior.py`` was ``189``, +1 = ``190``, and
``git cat-file -e HEAD:tests/test_iter190_behavior.py`` FAILED before a byte was
written -- the path is provably free in HEAD and was absent from the worktree.

ISOLATION: black-box, honored. Nothing under ``src/`` was read; no engineer,
reviewer or fix note was opened; no ``git diff`` was run. Every assertion drives
``proactive_loop.cli.main`` with an argv list and reads back only the exit code,
captured stdout/stderr, and files the CLI itself wrote.

WHAT "BYTE-IDENTICAL" HAD TO MEAN HERE, and why that is a measurement and not a
concession. The spec asks for stdout and slate under ``--json`` to be
byte-identical to ``--format json``. Measured, RAW streams from two runs of the
SAME flag differ: the slate carries a wall-clock ``created_at`` and every goal
id is a random 12-hex token (``cli.py`` documents it as the random per-scan id).
So a raw comparison would fail a CORRECT implementation. This module therefore
compares under the normalisation the suite already ships (``_HEX12``, copied
from ``tests/test_iter179_behavior.py:78``) and, crucially, runs the CONTROL:
``--format json`` against ITSELF, which differs in exactly the same way. A
control that also "fails" exonerates the change in one command. The residual
difference is additionally pinned as CONFINED to those two fields, so the alias
cannot smuggle a content change past the scrubber.

THREE TRAPS RESPECTED ON PURPOSE
1. AMBIENT TREE. Every workspace, slate, state dir and snapshot lives under
   ``tmp_path``; no assertion reads the checkout or any gitignored path, because
   every ship is re-verified from a throwaway fresh clone.
2. TRAILER PATHS. "stdout is byte-identical" is only meaningful when both runs
   point at the SAME ``--out`` and ``--state-dir``; any other harness bakes a
   path difference into the output and reports the fixture as the regression.
3. INTERPRETER SKEW. CI is a 3.12/3.13 matrix and 3.13 strips the common
   leading docstring indent at compile time, so nothing here asserts on
   indentation: help text is matched by substring only.

Coverage, numbered to match the spec's Expected Behaviors:

1. ``--json`` selects the JSON rendering; stdout equals ``--format json``
   modulo the pre-existing random ids, with the self-control run.
2. The persisted slate is unaffected, and the residual delta is confined to
   ``created_at`` and the ids derived from it.
3. ``--json --format csv`` is a PARSE-time usage error: exit 2, empty stdout,
   ``not allowed with argument``, and NO slate and NO state dir created.
4. The exclusion holds even when the two AGREE (``--json --format json``).
5. A bare ``scan`` still renders the TABLE -- the ``dest``-sharing default trap.
6. ``--json`` composes with ``--top``, ``--collector``, ``--out``, ``--snapshot``.
7. ``scan --help`` documents the flag and shows the exclusive group.
8. No other verb changes: siblings still emit JSON, and ``scan`` is the ONLY
   verb whose usage puts ``--json`` in a mutually exclusive group.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"

# The pre-existing, documented source of run-to-run variation: the random
# per-scan goal id. Same normaliser the suite already uses.
_HEX12 = re.compile(r"\b[0-9a-f]{12}\b")

# Asserted as a SUBSTRING on purpose: argparse names whichever of the two flags
# it saw SECOND, so the pair ordering in the message flips with argv order.
_CONFLICT = "not allowed with argument"

# Behavior 6: a collector that provably narrows what the scan perceives.
_ONE_COLLECTOR = "todos"


# ---------------------------------------------------------------------------
# Helpers -- argv in, exit code + stdout/stderr + on-disk artifacts out.
# Guards return 2 rather than raising, but an argparse conflict raises
# SystemExit, so both are tolerated.
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        rc = main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _build_workspace(root: Path) -> Path:
    """A small tree that provably emits signals from several collectors."""
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
    view: list[str] = [],
    top: int | None = None,
    collector: str | None = None,
    snapshot: Path | None = None,
) -> list[str]:
    """``view`` is spliced in VERBATIM so a test controls flag ORDER, which is
    what decides which flag argparse names in a conflict message."""
    argv = [
        "scan",
        "--workspace", str(ws_dir),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--out", str(out),
        "--state-dir", str(state_dir),
        *view,
    ]
    if top is not None:
        argv += ["--top", str(top)]
    if collector is not None:
        argv += ["--collector", collector]
    if snapshot is not None:
        argv += ["--snapshot", str(snapshot)]
    return argv


def _norm(text: str) -> str:
    """Blank the documented random per-scan id so what remains is content."""
    return _HEX12.sub("<ID>", text)


def _scrub_slate(doc: dict) -> dict:
    """Drop the two fields that differ between ANY two scans (wall-clock
    ``created_at`` and the goal ids), so what remains is what must not move."""
    scrubbed = json.loads(json.dumps(doc))
    scrubbed.pop("created_at", None)
    for goal in scrubbed.get("goals", []):
        goal.pop("id", None)
    return scrubbed


def _verbs(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """The registered subcommands, DERIVED from the CLI's own root help rather
    than hardcoded, so a new verb joins the census automatically."""
    rc, out, err = _run(["--help"], capsys)
    assert rc == 0, f"root --help must exit 0; rc={rc}, stderr={err!r}"
    match = re.search(r"\{([^}]+)\}", out, re.S)
    assert match is not None, f"root help must list the subcommand choices; got:\n{out}"
    names = [n for n in re.split(r"[,\s]+", match.group(1)) if n]
    assert len(names) >= 15, (
        f"the derived verb census must not be vacuous; got {names!r}"
    )
    return names


# ===========================================================================
# Behavior 1 --- `--json` selects the JSON rendering: exit 0, exactly one JSON
# object, no trailer, and stdout equal to `--format json` modulo the documented
# random ids -- with `--format json` vs ITSELF as the exonerating control.
# ===========================================================================


def test_b01a_json_alias_emits_one_json_object_and_no_trailer(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _scan_argv(ws, out=tmp_path / "slate.json", state_dir=tmp_path / "state",
                      view=["--json"])
    rc, out, err = _run(argv, capsys)
    assert rc == 0, f"scan --json must exit 0; rc={rc}, stderr={err!r}"
    doc = json.loads(out)  # a trailer after the object would make this raise
    assert isinstance(doc, dict), f"stdout must be ONE JSON object; got {type(doc)!r}"
    assert set(doc) == {"workspace_root", "goals"}, (
        f"the JSON view's top-level keys must be unchanged; got {sorted(doc)}"
    )
    assert doc["goals"], "the fixture must produce goals, else nothing is compared"
    assert out.endswith("}\n"), f"stdout must end at the object; got tail {out[-40:]!r}"


def test_b01b_alias_stdout_equals_format_json_for_the_same_run(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_path, state = tmp_path / "slate.json", tmp_path / "state"
    long_form = _run(
        _scan_argv(ws, out=out_path, state_dir=state, view=["--format", "json"]), capsys
    )
    alias = _run(_scan_argv(ws, out=out_path, state_dir=state, view=["--json"]), capsys)
    assert long_form[0] == 0 and alias[0] == 0, (
        f"both forms must exit 0; got {long_form[0]} and {alias[0]}"
    )
    assert _norm(alias[1]) == _norm(long_form[1]), (
        "scan --json stdout must equal --format json modulo the random per-scan id\n"
        f"--format json:\n{_norm(long_form[1])}\n--json:\n{_norm(alias[1])}"
    )
    assert alias[2] == "" == long_form[2], (
        f"neither form may write to stderr; got {alias[2]!r} / {long_form[2]!r}"
    )


def test_b01c_control_the_long_form_against_itself_varies_identically(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The control that makes b01b honest. Two runs of the UNCHANGED flag differ
    raw in exactly the same way, so a raw inequality is not evidence against the
    alias -- and under the normaliser the long form matches itself, which is
    what proves the normaliser is not simply erasing the comparison."""
    out_path, state = tmp_path / "slate.json", tmp_path / "state"
    first = _run(
        _scan_argv(ws, out=out_path, state_dir=state, view=["--format", "json"]), capsys
    )[1]
    second = _run(
        _scan_argv(ws, out=out_path, state_dir=state, view=["--format", "json"]), capsys
    )[1]
    assert _norm(first) == _norm(second), (
        "the control must hold: --format json must equal ITSELF once normalised"
    )
    assert "<ID>" in _norm(first), (
        "non-vacuity: the normaliser must actually have blanked ids, else b01b "
        f"compared streams that never contained one; got:\n{_norm(first)}"
    )
    # Two-sided control on the normaliser itself: a genuinely different VIEW of
    # the same scan must NOT compare equal once normalised, else _norm would be
    # collapsing content and every equality above would pass vacuously.
    table = _run(_scan_argv(ws, out=out_path, state_dir=state,
                            view=["--format", "table"]), capsys)[1]
    assert _norm(table) != _norm(first), (
        "the normaliser must not erase real differences: the table view and the "
        "JSON view of the same scan must stay distinguishable under it"
    )


# ===========================================================================
# Behavior 2 --- the persisted slate is unaffected; the alias changes the stdout
# VIEW only, and the residual delta is CONFINED to created_at and the ids.
# ===========================================================================


def test_b02_persisted_slate_is_unchanged_by_the_alias(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    long_slate, alias_slate = tmp_path / "long.json", tmp_path / "alias.json"
    state = tmp_path / "state"
    rc_long = _run(
        _scan_argv(ws, out=long_slate, state_dir=state, view=["--format", "json"]),
        capsys,
    )[0]
    rc_alias = _run(
        _scan_argv(ws, out=alias_slate, state_dir=state, view=["--json"]), capsys
    )[0]
    assert rc_long == 0 and rc_alias == 0, f"got {rc_long} and {rc_alias}"
    long_doc = json.loads(long_slate.read_text(encoding="utf-8"))
    alias_doc = json.loads(alias_slate.read_text(encoding="utf-8"))
    assert long_doc["goals"], "non-vacuity: the slate must carry goals to compare"
    assert _scrub_slate(alias_doc) == _scrub_slate(long_doc), (
        "the slate written under --json must match the one written under "
        "--format json once the wall-clock created_at and derived ids are scrubbed"
    )
    moved = {k for k in set(long_doc) | set(alias_doc)
             if long_doc.get(k) != alias_doc.get(k)}
    assert moved <= {"created_at", "goals"}, (
        f"the residual difference must be confined to the documented fields; "
        f"these top-level keys also moved: {sorted(moved - {'created_at', 'goals'})}"
    )


# ===========================================================================
# Behavior 3 --- `--json --format csv` is a PARSE-time usage error: exit 2,
# empty stdout, and neither the slate NOR the state dir is created, which is
# what distinguishes "rejected before collection" from "rejected before render".
# ===========================================================================


def test_b03_conflict_is_rejected_before_any_side_effect(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slate, state = tmp_path / "slate.json", tmp_path / "state"
    rc, out, err = _run(
        _scan_argv(ws, out=slate, state_dir=state, view=["--json", "--format", "csv"]),
        capsys,
    )
    assert rc == 2, f"the conflict must exit 2; rc={rc}, stderr={err!r}"
    assert out == "", f"stdout must be EMPTY on a usage error; got:\n{out!r}"
    assert _CONFLICT in err, f"stderr must report {_CONFLICT!r}; got:\n{err!r}"
    assert not slate.exists(), f"no slate may be written on a usage error: {slate}"
    assert not state.exists(), (
        f"the state dir must NOT be created -- the rejection must precede provider "
        f"construction and collection, not merely rendering: {state}"
    )


def test_b03b_the_conflict_holds_in_either_argv_order(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slate, state = tmp_path / "slate.json", tmp_path / "state"
    rc, out, err = _run(
        _scan_argv(ws, out=slate, state_dir=state, view=["--format", "csv", "--json"]),
        capsys,
    )
    assert rc == 2, f"the reversed conflict must exit 2; rc={rc}, stderr={err!r}"
    assert out == "", f"stdout must be EMPTY; got:\n{out!r}"
    assert _CONFLICT in err, f"stderr must report {_CONFLICT!r}; got:\n{err!r}"
    assert not slate.exists() and not state.exists(), "no side effect is allowed"


# ===========================================================================
# Behavior 4 --- the exclusion holds even when the two AGREE. Pinned so a later
# change cannot silently special-case the agreeing pair into acceptance.
# ===========================================================================


def test_b04_agreeing_pair_is_still_rejected(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slate, state = tmp_path / "slate.json", tmp_path / "state"
    rc, out, err = _run(
        _scan_argv(ws, out=slate, state_dir=state, view=["--json", "--format", "json"]),
        capsys,
    )
    assert rc == 2, (
        f"--json --format json must be rejected even though the two agree; rc={rc}"
    )
    assert out == "", f"stdout must be EMPTY; got:\n{out!r}"
    assert _CONFLICT in err, f"stderr must report {_CONFLICT!r}; got:\n{err!r}"


# ===========================================================================
# Behavior 5 --- a bare `scan` is byte-identical to today. This is the trap: two
# argparse actions on one `dest` means the FIRST-registered default survives, so
# a careless build resolves format=None and silently changes existing output.
# ===========================================================================


def test_b05a_bare_scan_still_renders_the_table(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err = _run(
        _scan_argv(ws, out=tmp_path / "slate.json", state_dir=tmp_path / "state"), capsys
    )
    assert rc == 0, f"a bare scan must still exit 0; rc={rc}, stderr={err!r}"
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)  # the default must NOT have become the JSON view
    assert "DECISION" in out and "SCORE" in out, (
        f"a bare scan must render the TABLE view; got:\n{out}"
    )


def test_b05b_bare_scan_equals_the_explicit_table_format(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pointed at the SAME --out and --state-dir, so no path difference is baked
    into the trailer and reported as the regression."""
    out_path, state = tmp_path / "slate.json", tmp_path / "state"
    bare = _run(_scan_argv(ws, out=out_path, state_dir=state), capsys)[1]
    explicit = _run(
        _scan_argv(ws, out=out_path, state_dir=state, view=["--format", "table"]), capsys
    )[1]
    assert _norm(bare) == _norm(explicit), (
        "a bare scan must still resolve format='table' -- if the alias was "
        "registered BEFORE --format, its default wins and this diverges\n"
        f"bare:\n{_norm(bare)}\nexplicit:\n{_norm(explicit)}"
    )


# ===========================================================================
# Behavior 6 --- `--json` composes with every other `scan` flag: the group holds
# ONLY --format and --json, so --top, --collector, --out and --snapshot all
# continue to apply underneath it.
# ===========================================================================


def test_b06a_top_caps_the_json_view_under_the_alias(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_path, state = tmp_path / "slate.json", tmp_path / "state"
    uncapped = json.loads(
        _run(_scan_argv(ws, out=out_path, state_dir=state, view=["--json"]), capsys)[1]
    )
    assert len(uncapped["goals"]) > 1, (
        "non-vacuity: the fixture must yield more than one goal for a cap to bite"
    )
    rc, out, err = _run(
        _scan_argv(ws, out=out_path, state_dir=state, view=["--json"], top=1), capsys
    )
    assert rc == 0, f"scan --json --top 1 must exit 0; rc={rc}, stderr={err!r}"
    assert len(json.loads(out)["goals"]) == 1, (
        f"--top must still cap the JSON view under the alias; got:\n{out}"
    )


def test_b06b_collector_out_and_snapshot_still_apply_under_the_alias(
    ws: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "state"
    alias_snap, long_snap, wide_snap = (
        tmp_path / "alias.snap.json",
        tmp_path / "long.snap.json",
        tmp_path / "wide.snap.json",
    )
    alias_slate = tmp_path / "alias.slate.json"
    rc_alias = _run(
        _scan_argv(ws, out=alias_slate, state_dir=state, view=["--json"],
                   collector=_ONE_COLLECTOR, snapshot=alias_snap),
        capsys,
    )[0]
    rc_long = _run(
        _scan_argv(ws, out=tmp_path / "long.slate.json", state_dir=state,
                   view=["--format", "json"], collector=_ONE_COLLECTOR,
                   snapshot=long_snap),
        capsys,
    )[0]
    rc_wide = _run(
        _scan_argv(ws, out=tmp_path / "wide.slate.json", state_dir=state,
                   view=["--json"], snapshot=wide_snap),
        capsys,
    )[0]
    assert (rc_alias, rc_long, rc_wide) == (0, 0, 0), (
        f"every composed form must exit 0; got {(rc_alias, rc_long, rc_wide)}"
    )
    assert alias_slate.is_file(), f"--out must still be honored: {alias_slate}"
    assert alias_snap.is_file(), f"--snapshot must still be honored: {alias_snap}"
    assert alias_snap.read_bytes() == long_snap.read_bytes(), (
        "the snapshot carries no timestamp, so the alias and the long form must "
        "write BYTE-IDENTICAL documents"
    )
    filtered = {s["source"] for s in json.loads(
        alias_snap.read_text(encoding="utf-8"))["signals"]}
    wide = {s["source"] for s in json.loads(
        wide_snap.read_text(encoding="utf-8"))["signals"]}
    assert filtered == {_ONE_COLLECTOR}, (
        f"--collector must still narrow the scan under --json; got {sorted(filtered)}"
    )
    assert len(wide) > 1, (
        f"non-vacuity: unfiltered must see more than one source; got {sorted(wide)}"
    )


# ===========================================================================
# Behavior 7 --- `scan --help` documents the flag and shows it as an exclusive
# alternative to --format. Substring only: 3.13 reflows help text.
# ===========================================================================


def test_b07_scan_help_documents_the_flag_and_the_exclusive_group(
    capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err = _run(["scan", "--help"], capsys)
    assert rc == 0, f"scan --help must exit 0; rc={rc}, stderr={err!r}"
    assert "--json" in out, f"scan --help must document --json; got:\n{out}"
    assert "| --json" in out, (
        f"the usage line must show --json as exclusive with --format; got:\n{out}"
    )
    assert "--format" in out, f"--format must remain documented; got:\n{out}"


# ===========================================================================
# Behavior 8 --- no other verb changes. Siblings still emit their JSON object,
# and `scan` is the ONLY verb whose usage puts --json in an exclusive group.
# ===========================================================================


def test_b08a_sibling_json_verbs_still_emit_one_json_object(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cases: list[list[str]] = [
        ["signals", "--workspace", str(ws), "--json"],
        ["collectors", "--json"],
        ["providers", "--json"],
    ]
    for argv in cases:
        rc, out, err = _run(argv, capsys)
        assert rc == 0, f"{' '.join(argv)} must still exit 0; rc={rc}, stderr={err!r}"
        assert isinstance(json.loads(out), dict), (
            f"{' '.join(argv)} must still emit ONE JSON object; got:\n{out}"
        )


def test_b08b_scan_is_the_only_verb_whose_json_joins_an_exclusive_group(
    capsys: pytest.CaptureFixture[str]
) -> None:
    """Derived census over the CLI's own verb list, so a sibling accidentally
    pulled into a mutually exclusive group reds the build."""
    offering: list[str] = []
    grouped: list[str] = []
    for verb in _verbs(capsys):
        rc, out, err = _run([verb, "--help"], capsys)
        assert rc == 0, f"{verb} --help must exit 0; rc={rc}, stderr={err!r}"
        if "--json" in out:
            offering.append(verb)
        if "| --json" in out:
            grouped.append(verb)
    assert "scan" in offering, "scan must now offer --json"
    assert len(offering) >= 15, (
        f"the idiom must reach at least 15 verbs; got {len(offering)}: {offering}"
    )
    assert grouped == ["scan"], (
        f"only scan's --json may sit in a mutually exclusive group; got {grouped}"
    )
