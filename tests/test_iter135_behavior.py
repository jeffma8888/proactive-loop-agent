"""Black-box behavior tests for iteration 135 --- the bundled offline driver
must support a real TWO-TICK ``watch``.

Feature under test: ``examples/scripted_responses.json`` is the repo's ONLY
offline, copy-pasteable driver, and it held exactly ONE ``synthesize`` response.
``ScriptedLLMClient.complete`` pops the first entry whose tag matches, so a
second ``watch`` tick had no ``synthesize`` left: a 2-tick run wrote ONE
``slate-001.json`` and the documented ``watch --out-dir DIR`` ->
``diff --dir DIR`` chain (README:207) then refused with *"--dir needs at least
two stream slates to compare, found 1"*. This iteration appends a SECOND
``synthesize`` entry whose goal set deliberately differs from the first, so the
bundled driver now feeds two ticks and the offline change feed is runnable end
to end. Nothing under ``src/`` moves; ``watch``'s resilient exit-0 contract and
the pop-the-first-matching-tag semantics are unchanged.

ISOLATION CONTRACT (honored): every assertion below is written against THIS
iteration's spec (``pm.md`` "Expected Behaviors" 1-10) and drives only public
surfaces --- the ``pla`` CLI through ``proactive_loop.cli.main(argv) -> int``
(its exit codes / stdout / stderr / on-disk artifacts, the same seam
``tests/test_iter120_behavior.py`` and ``tests/test_iter123_behavior.py`` use)
plus ``examples/scripted_responses.json`` read as DATA. **No file under
``src/`` was read, no engineer / reviewer / fix notes were read, and no
``git diff`` was consulted.** Behavior 2 mandates byte-identity against HEAD,
so this module reads HEAD's copy of that one JSON fixture through a guarded
local ``git show`` (see ``_head_responses``) --- the spec authorizes exactly
that comparison, and the durable digests below were derived from it.

Fully offline and deterministic: no network, no API keys, the scripted provider
seam only, ``--interval 0`` so no sleeps, and every writable target under
``tmp_path``. The single ``git show`` is a local object-store read that never
contacts a remote, and it degrades to a skip on a checkout without git.

AMBIGUITY NOTES (PM feedback):
* Behavior 2 says entry 0's text is "byte-identical to HEAD". A bare live
  comparison against ``HEAD`` goes VACUOUS the moment this change is committed
  (HEAD then contains the new file), so the HEAD prefix is ALSO pinned as two
  literal SHA-256 digests derived from HEAD before the commit. The digests are
  the durable oracle; the ``git show`` comparison is the belt-and-braces check
  that they were derived from the real pre-change bytes.
* Behavior 10 says "``make demo`` still succeeds". Shelling out to ``make``/
  ``uv`` inside the graded suite would add a nested-build cost the spec's own
  "Out of Scope" section rules out for this iteration, so the demo's EXACT
  Makefile argv (``pla run`` over the two bundled ``examples/`` fixtures) is
  driven in-process against a ``tmp_path`` state dir. That proves the demo path
  still binds ``synthesize[0]`` and still writes its slate plus artifacts; the
  literal ``make demo`` invocation stays owned by ``make check`` and CI.
* Behavior 5 names the tokens "no scripted response left" / "scan 2 failed"
  without saying which stream carries them. Both streams are captured and the
  assertion is made over their concatenation, which is the strictest reading.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"
FIXTURE_WS = REPO / "examples" / "fixture_workspace"

# The ten documented keys of a synthesize goal object (pm.md "Design notes").
GOAL_KEYS = {
    "title",
    "rationale",
    "category",
    "impact",
    "urgency",
    "confidence",
    "effort_weight",
    "appropriate_now",
    "sources",
    "suggested_first_steps",
}

# Behavior 1/2: the exact post-change tag sequence. The appended entry is the
# LAST element, so entries 0-6 keep HEAD's order and `make demo` still binds
# synthesize[0].
EXPECTED_TAGS = [
    "synthesize",
    "plan",
    "check",
    "plan",
    "check",
    "plan",
    "check",
    "synthesize",
]

# Behavior 2, durable pins derived from HEAD (4e48072) BEFORE this change.
HEAD_ENTRY0_TEXT_SHA256 = (
    "862a3a85bd6ae6601360dd2a1c315c6f8ae5797b2106b0f85d1ab39a8806ecf3"
)
HEAD_PREFIX_SHA256 = (
    "0b64a263d40f22ebe54a543937fd1744ec6a80af5e6d31e0d247fc4b5e44b8ce"
)
# Behavior 2/10: HEAD's synthesize[0] renders these four scores
# (impact * urgency * confidence / effort_weight), and the APPENDED entry does
# not, so a slate carrying them proves entry 0 was the one consumed.
HEAD_ENTRY0_SCORES = [1.5, 2.4, 18.0, 25.0]


# ---------------------------------------------------------------------------
# Helpers --- data reads and CLI drives only.
# ---------------------------------------------------------------------------


def _responses() -> list[dict]:
    """The bundled driver's ``responses`` list, read as data."""
    payload = json.loads(SCRIPT.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"top level must be a JSON object, got {type(payload)}"
    assert "responses" in payload, f"missing top-level 'responses' key; keys={sorted(payload)}"
    responses = payload["responses"]
    assert isinstance(responses, list), f"'responses' must be a list, got {type(responses)}"
    return responses


def _synthesize_entries() -> list[dict]:
    return [entry for entry in _responses() if entry.get("tag") == "synthesize"]


def _canonical(entries: list[dict]) -> str:
    return json.dumps(entries, sort_keys=True, separators=(",", ":"))


def _head_responses() -> list[dict] | None:
    """HEAD's copy of the bundled driver, or ``None`` when unavailable.

    A local object-store read (``git show`` never contacts a remote), so this
    stays inside the repo's offline-first contract. Returns ``None`` on a
    checkout with no ``.git``, no ``git`` binary, or no such blob --- the
    durable digests above then carry behavior 2 alone.
    """
    if not (REPO / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO), "show", "HEAD:examples/scripted_responses.json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    entries = payload.get("responses")
    return entries if isinstance(entries, list) else None


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and return (exit_code, stdout, stderr)."""
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _watch_argv(*, state_dir: Path, out_dir: Path, max_scans: str) -> list[str]:
    """The README's offline watch invocation, with writable targets redirected."""
    return [
        "watch",
        "--workspace", str(FIXTURE_WS),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--interval", "0",
        "--max-scans", max_scans,
        "--state-dir", str(state_dir),
        "--out-dir", str(out_dir),
    ]


def _watch(tmp_path: Path, capsys, *, max_scans: str, name: str) -> tuple[int, str, str, Path]:
    out_dir = tmp_path / f"stream-{name}"
    rc, out, err = _run(
        _watch_argv(
            state_dir=tmp_path / f"state-{name}",
            out_dir=out_dir,
            max_scans=max_scans,
        ),
        capsys,
    )
    return rc, out, err, out_dir


def _stream_names(out_dir: Path) -> list[str]:
    return sorted(p.name for p in out_dir.iterdir()) if out_dir.exists() else []


def _slate_scores(path: Path) -> list[float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return sorted(round(float(goal["score"]), 2) for goal in payload["goals"])


# ===========================================================================
# Behavior 1 --- 8 entries, exactly 2 synthesize, every tag non-empty.
# ===========================================================================


def test_b01a_driver_holds_eight_entries_two_of_them_synthesize() -> None:
    responses = _responses()
    assert len(responses) == 8, (
        f"the bundled driver must hold exactly 8 responses, found {len(responses)}: "
        f"tags={[e.get('tag') for e in responses]}"
    )
    synth = _synthesize_entries()
    assert len(synth) == 2, (
        f"exactly 2 entries must be tagged 'synthesize' (one per watch tick), found "
        f"{len(synth)}; tags={[e.get('tag') for e in responses]}"
    )


def test_b01b_no_entry_carries_an_empty_or_missing_tag() -> None:
    """An empty tag matches ANY requested tag and would poison plan/check."""
    offenders = [
        (index, entry.get("tag"))
        for index, entry in enumerate(_responses())
        if not isinstance(entry.get("tag"), str) or entry.get("tag") == ""
    ]
    assert offenders == [], (
        "no entry may carry an empty or missing 'tag' --- complete() treats the "
        f"empty string as a wildcard that silently consumes the next tick's "
        f"response. Offending (index, tag) pairs: {offenders}"
    )


def test_b01c_every_entry_is_a_tag_text_pair_of_strings() -> None:
    bad = [
        (index, sorted(entry) if isinstance(entry, dict) else type(entry).__name__)
        for index, entry in enumerate(_responses())
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str)
    ]
    assert bad == [], f"every entry must be a dict with a string 'text'; offenders: {bad}"


# ===========================================================================
# Behavior 2 --- append-only: entries 0-6 are HEAD's, untouched and in order.
# ===========================================================================


def test_b02a_tag_sequence_is_heads_prefix_plus_one_appended_synthesize() -> None:
    tags = [entry.get("tag") for entry in _responses()]
    assert tags == EXPECTED_TAGS, (
        "the new synthesize entry must be APPENDED (last), leaving HEAD's "
        f"7-entry order intact.\n  expected: {EXPECTED_TAGS}\n  actual:   {tags}"
    )


def test_b02b_head_prefix_bytes_are_unchanged() -> None:
    responses = _responses()
    prefix_digest = hashlib.sha256(_canonical(responses[0:7]).encode("utf-8")).hexdigest()
    assert prefix_digest == HEAD_PREFIX_SHA256, (
        "entries 0-6 must be byte-identical to HEAD (no edit, no reorder, no "
        f"removal). canonical-JSON sha256 was {prefix_digest}, expected "
        f"{HEAD_PREFIX_SHA256}"
    )
    entry0_digest = hashlib.sha256(responses[0]["text"].encode("utf-8")).hexdigest()
    assert entry0_digest == HEAD_ENTRY0_TEXT_SHA256, (
        f"responses[0]['text'] must be byte-identical to HEAD; sha256 was "
        f"{entry0_digest}, expected {HEAD_ENTRY0_TEXT_SHA256}"
    )
    assert responses[0].get("tag") == "synthesize", (
        "responses[0] must still be the synthesize entry `make demo` binds; got "
        f"{responses[0].get('tag')!r}"
    )


def test_b02c_head_prefix_matches_the_committed_blob() -> None:
    """Live cross-check of the digests above against HEAD's actual bytes."""
    head = _head_responses()
    if head is None:
        pytest.skip("no readable HEAD blob for examples/scripted_responses.json")
    assert len(head) >= 7, f"HEAD is expected to hold at least 7 entries, found {len(head)}"
    responses = _responses()
    assert responses[0:7] == head[0:7], (
        "entries 0-6 must equal HEAD's entries 0-6 element for element.\n"
        f"  HEAD tags: {[e.get('tag') for e in head]}\n"
        f"  now tags:  {[e.get('tag') for e in responses]}"
    )
    # ``HEAD`` is the PRE-change blob only until this iteration is committed;
    # afterwards it IS this file, so a literal ``len(head) + 1`` here would turn
    # red on the very commit that ships this module (measured: "HEAD had 8, now
    # 8"). Append-only-ness is pinned DURABLY and exactly by ``EXPECTED_TAGS``
    # (8 entries, the appended synthesize last) plus the two literal digests in
    # ``test_b02b_head_prefix_bytes_are_unchanged``; this live check adds the
    # commit-invariant half -- this file never REMOVES an entry HEAD holds and
    # adds at most one.
    assert len(responses) - len(head) in (0, 1), (
        "at most ONE entry may be added and none removed (delta 1 before this "
        f"iteration is committed, 0 after): HEAD had {len(head)}, now "
        f"{len(responses)}"
    )


# ===========================================================================
# Behavior 3 --- the two synthesize texts differ and both parse as goal lists.
# ===========================================================================


def test_b03a_the_two_synthesize_texts_are_not_equal() -> None:
    first, second = _synthesize_entries()
    assert first["text"] != second["text"], (
        "the appended synthesize response must differ from the first, otherwise "
        "tick 2 renders an identical slate and `diff --dir` reports no change at all"
    )


def test_b03b_both_synthesize_texts_parse_as_lists_of_goal_objects() -> None:
    for index, entry in enumerate(_synthesize_entries()):
        goals = json.loads(entry["text"])
        assert isinstance(goals, list) and goals, (
            f"synthesize[{index}]['text'] must parse as a NON-EMPTY JSON list, got {goals!r}"
        )
        for position, goal in enumerate(goals):
            assert isinstance(goal, dict), (
                f"synthesize[{index}] goal {position} must be an object, got {type(goal)}"
            )
            missing = GOAL_KEYS - set(goal)
            assert not missing, (
                f"synthesize[{index}] goal {position} ({goal.get('title')!r}) is missing "
                f"documented keys: {sorted(missing)}"
            )


def test_b03c_head_synthesize_still_renders_its_four_documented_goals() -> None:
    goals = json.loads(_synthesize_entries()[0]["text"])
    assert len(goals) == 4, f"HEAD's synthesize must still hold 4 goals, found {len(goals)}"
    scores = sorted(
        round(g["impact"] * g["urgency"] * g["confidence"] / g["effort_weight"], 2)
        for g in goals
    )
    assert scores == HEAD_ENTRY0_SCORES, (
        f"HEAD's synthesize scores must be unchanged; expected {HEAD_ENTRY0_SCORES}, got {scores}"
    )


# ===========================================================================
# Behaviors 4 + 5 --- a 2-tick watch writes BOTH stream slates, no exhaustion.
# ===========================================================================


def test_b04_two_tick_watch_writes_exactly_two_stream_slates(tmp_path, capsys) -> None:
    rc, out, err, out_dir = _watch(tmp_path, capsys, max_scans="2", name="b04")
    assert rc == 0, f"the documented 2-tick offline watch must exit 0, got {rc}; stderr={err!r}"
    assert _stream_names(out_dir) == ["slate-001.json", "slate-002.json"], (
        "a 2-tick watch against the bundled driver must persist BOTH ticks; found "
        f"{_stream_names(out_dir)}\nstdout:\n{out}\nstderr:\n{err}"
    )


def test_b05_two_tick_watch_reports_no_exhaustion_and_no_failed_tick(tmp_path, capsys) -> None:
    _rc, out, err, _out_dir = _watch(tmp_path, capsys, max_scans="2", name="b05")
    combined = out + err
    for token in ("no scripted response left", "scan 2 failed"):
        assert token not in combined, (
            f"a 2-tick offline watch must not report {token!r} --- the bundled "
            f"driver now feeds two ticks.\nstdout:\n{out}\nstderr:\n{err}"
        )


# ===========================================================================
# Behaviors 6 + 7 + 8 --- diff --dir succeeds over that stream, binds the two
# newest ticks, and its change feed exercises all four classifications.
# ===========================================================================


def test_b06_diff_dir_over_the_bundled_stream_exits_zero(tmp_path, capsys) -> None:
    rc_watch, _out, err, out_dir = _watch(tmp_path, capsys, max_scans="2", name="b06")
    assert rc_watch == 0, f"producer setup failed: watch exited {rc_watch}; stderr={err!r}"

    rc, out, derr = _run(["diff", "--dir", str(out_dir)], capsys)

    assert rc == 0, (
        "the documented offline chain `watch --out-dir DIR` -> `diff --dir DIR` must "
        f"exit 0 (it exited 2 with 'found 1' before this change), got {rc}; stderr={derr!r}"
    )
    assert "needs at least two stream slates" not in derr, (
        f"diff must no longer refuse for want of a second slate; stderr={derr!r}"
    )
    assert out.strip(), "diff must render a human change feed on stdout"


def test_b07_diff_dir_json_binds_slate_001_to_slate_002(tmp_path, capsys) -> None:
    _rc, _out, _err, out_dir = _watch(tmp_path, capsys, max_scans="2", name="b07")

    rc, out, derr = _run(["diff", "--dir", str(out_dir), "--json"], capsys)

    assert rc == 0, f"diff --dir --json must exit 0, got {rc}; stderr={derr!r}"
    payload = json.loads(out)
    assert isinstance(payload, dict), f"--json must emit ONE JSON object, got {type(payload)}"
    assert set(payload) == {"old", "new", "added", "removed", "changed", "unchanged_count"}, (
        f"unexpected --json keys: {sorted(payload)}"
    )
    assert payload["old"].endswith("slate-001.json"), (
        f"--old must bind the first tick, got {payload['old']!r}"
    )
    assert payload["new"].endswith("slate-002.json"), (
        f"--new must bind the second tick, got {payload['new']!r}"
    )


def test_b08_change_feed_exercises_all_four_classifications(tmp_path, capsys) -> None:
    _rc, _out, _err, out_dir = _watch(tmp_path, capsys, max_scans="2", name="b08")
    _rc_json, out, derr = _run(["diff", "--dir", str(out_dir), "--json"], capsys)
    assert _rc_json == 0, f"diff --dir --json must exit 0; stderr={derr!r}"
    payload = json.loads(out)

    summary = {
        "added": len(payload["added"]),
        "removed": len(payload["removed"]),
        "changed": len(payload["changed"]),
        "unchanged_count": payload["unchanged_count"],
    }
    assert summary["added"] >= 1, f"the feed must be non-degenerate; got {summary}"
    assert summary["removed"] >= 1, f"the feed must be non-degenerate; got {summary}"
    assert summary["changed"] >= 1, f"the feed must be non-degenerate; got {summary}"
    assert summary["unchanged_count"] >= 1, f"the feed must be non-degenerate; got {summary}"


# ===========================================================================
# Behavior 9 --- a 3-tick watch STILL exhausts on tick 3 and STILL exits 0.
# ===========================================================================


def test_b09_three_tick_watch_exhausts_on_tick_three_but_still_exits_zero(
    tmp_path, capsys
) -> None:
    rc, out, err, out_dir = _watch(tmp_path, capsys, max_scans="3", name="b09")
    assert rc == 0, (
        "watch is resilient by design: a failing tick must not change its exit "
        f"code, got {rc}; stderr={err!r}"
    )
    assert _stream_names(out_dir) == ["slate-001.json", "slate-002.json"], (
        "the bundled driver feeds exactly TWO ticks, so tick 3 must persist nothing; "
        f"found {_stream_names(out_dir)}"
    )
    combined = out + err
    assert "scan 3 failed" in combined, (
        "tick 3 must still report its failure (the driver is deliberately not "
        f"extended to N ticks).\nstdout:\n{out}\nstderr:\n{err}"
    )
    assert "no scripted response left" in combined, (
        f"tick 3 must still surface the exhaustion cause.\nstdout:\n{out}\nstderr:\n{err}"
    )


# ===========================================================================
# Behavior 10 --- the demo path is untouched: it still binds synthesize[0] and
# still writes its slate plus run artifacts.
# ===========================================================================


def test_b10_demo_argv_still_binds_synthesize_zero_and_writes_artifacts(
    tmp_path, capsys
) -> None:
    state_dir = tmp_path / "pla_runs"
    rc, out, err = _run(
        [
            "run",
            "--workspace", str(FIXTURE_WS),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--state-dir", str(state_dir),
        ],
        capsys,
    )
    assert rc == 0, f"the demo invocation must exit 0, got {rc}; stderr={err!r}\nstdout:\n{out}"

    slate = state_dir / "slate.json"
    assert slate.is_file(), f"the demo must write slate.json; state dir held {_stream_names(state_dir)}"
    artifacts = sorted(state_dir.glob("run-*/artifacts/*.md"))
    assert artifacts, (
        "the demo must write at least one run artifact (the assertion `make check` "
        f"and CI make); state dir held {_stream_names(state_dir)}"
    )

    assert _slate_scores(slate) == HEAD_ENTRY0_SCORES, (
        "the demo's single scan must still bind synthesize[0] --- the appended entry "
        f"must be unreachable from the demo path. Expected scores "
        f"{HEAD_ENTRY0_SCORES}, got {_slate_scores(slate)}"
    )
