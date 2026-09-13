"""Black-box behavior tests for factory iteration 289 -- the ``--dir`` on-ramp.

Feature under test: the two exit-2 refusals that ``pla diff --dir`` and ``pla
trend --dir`` print when the directory holds too few stream slates now carry a
SECOND stderr line -- a paste-ready ``pla watch --out-dir <ABS>`` command plus the
``slate-<NNN>.json`` filename shape -- composed from the constants that already
define that convention, so the hint can never drift away from the files the
consumers actually look for.

ISOLATION CONTRACT (honored): written from this iteration's spec
(``state/iter-289/pm.md`` Expected Behaviors 1-9 and its Acceptance Criteria) plus
the conventions of existing modules under ``tests/`` -- chiefly
``tests/test_iter135_behavior.py``, which owns the ``watch --out-dir`` -> ``diff
--dir`` chain and whose ``_run``/``_watch_argv`` helper shape is reused here. No
implementation source was READ, no engineer or reviewer notes, and no ``git
diff``. Behaviors 5 and 6a are structural claims the spec makes ABOUT
``cli.py``'s text ("one helper, no shape literals in its body"), so their oracles
parse that file MECHANICALLY with ``ast`` and derive every needle from the
product's own printed output -- no expectation below was copied from a diff.

Determinism and offline-ness: every case drives ``proactive_loop.cli.main(argv)``
in-process with captured streams, or reads tracked text. The single round trip
(behavior 7) runs the offline ``scripted`` provider with ``--interval 0``. No
network, no sleep, no wall-clock assertion, and NO mtime-sensitive precondition:
each stream directory is BUILT under ``tmp_path`` (the iteration-278 lesson --
a fresh clone resets every mtime, so an ambient-mtime precondition that passes
vacuously here runs for the first time at preship).
"""

from __future__ import annotations

import ast
import re
import shlex
import subprocess
from pathlib import Path

from proactive_loop import cli
from proactive_loop.cli import main

REPO = Path(__file__).resolve().parent.parent
CLI_SOURCE = REPO / "src" / "proactive_loop" / "cli.py"
FIXTURE_WS = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"

#: The two refusals under test, keyed by verb, with their byte-exact first line.
#: ``{dir}`` is the spelling the user PASSED to ``--dir`` (not a re-spelling).
TREND_FIRST_LINE = "error: --dir needs at least one stream slate to report on, found 0: {dir}"
DIFF_FIRST_LINE = "error: --dir needs at least two stream slates to compare, found 1: {dir}"

#: Behavior 8's untouched refusal, shared by both verbs.
NOT_A_DIR_LINE = "error: --dir must be an existing directory: {dir}"

#: The two consumers of the stream directory. Both refusals are theirs.
VERBS = ("diff", "trend")

#: Behavior 2/4's three required substrings. The slate NAME is derived at call
#: time from the shipped convention helper, never spelled here.
HINT_COMMAND_PREFIX = "pla watch --out-dir"

#: Placeholders the hint is allowed to leave for the user to fill in, mapped to
#: the values this repo ships for them. Behavior 7 substitutes these and nothing
#: else: an unknown ALL-CAPS token makes the round trip FAIL rather than guess.
PLACEHOLDERS: dict[str, str] = {
    "WORKSPACE": str(FIXTURE_WS),
    "SCRIPT": str(SCRIPT),
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive ``main()`` and return ``(exit_code, stdout, stderr)``."""
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _slate_name(index: int) -> str:
    """The shipped filename shape for tick ``index`` -- the ONE source of truth."""
    return cli._stream_slate_name(index)  # type: ignore[attr-defined]


def _empty_stream_dir(tmp_path: Path, name: str) -> Path:
    out = tmp_path / name
    out.mkdir()
    return out


def _one_slate_dir(tmp_path: Path, capsys, name: str) -> Path:
    """A stream directory holding EXACTLY one real slate, produced by ``watch``."""
    out_dir = tmp_path / name
    rc, _out, err = _run(
        [
            "watch",
            "--workspace", str(FIXTURE_WS),
            "--provider", "scripted",
            "--scripted-responses", str(SCRIPT),
            "--interval", "0",
            "--max-scans", "1",
            "--state-dir", str(tmp_path / f"state-{name}"),
            "--out-dir", str(out_dir),
        ],
        capsys,
    )
    assert rc == 0, f"one-tick watch failed (rc={rc}): {err}"
    names = sorted(p.name for p in out_dir.iterdir())
    assert names == [_slate_name(1)], f"expected exactly one slate, got {names}"
    return out_dir


def _stderr_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.strip()]


def _hint_line(err: str) -> str:
    """The ADDITIONAL line after the refusal's first line (behaviors 2 and 4)."""
    lines = _stderr_lines(err)
    assert len(lines) >= 2, f"no additional line after the refusal:\n{err}"
    extra = [line for line in lines[1:] if HINT_COMMAND_PREFIX in line]
    assert len(extra) == 1, (
        f"expected exactly one line naming `{HINT_COMMAND_PREFIX}`, got {extra!r}"
    )
    return extra[0]


def _hint_command(err: str) -> str:
    """The backtick-quoted command inside the hint line, unquoted."""
    line = _hint_line(err)
    parts = line.split("`")
    assert len(parts) >= 3, f"hint command is not backtick-quoted: {line!r}"
    return parts[1]


def _hint_prose(err: str) -> str:
    """The hint's own sentence AFTER the command, with the derived name removed.

    Derived from the product's output so behavior 5's "defined once" census needs
    no hardcoded copy of the implementation's string.
    """
    tail = _hint_line(err).split("`")[-1]
    return tail.replace(_slate_name(1), "").rstrip()


def _squash(text: str) -> str:
    """Drop whitespace and quote characters so a WRAPPED literal still matches.

    A source-level census cannot look for the RENDERED sentence verbatim: the
    implementation is free to wrap that string across lines or build it from
    implicitly concatenated pieces, both of which insert whitespace and quote
    characters the rendered output never carries (string PREFIXES like ``f`` too).
    Squashing both sides keeps the
    census honest about the ONE thing it is testing (is this sentence written
    once, or copied?) without pinning a formatting choice.
    """
    without_prefixes = re.sub(r"(?<![A-Za-z0-9_])[fFrRbBuU]{1,2}(?=[\"'])", "", text)
    return "".join(ch for ch in without_prefixes if ch not in " \t\r\n\"'\\")


def _module_level_functions() -> dict[str, str]:
    """``{name: source segment}`` for every module-level ``def`` in ``cli.py``."""
    text = CLI_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = ast.get_source_segment(text, node)
            if segment is not None:
                out[node.name] = segment
    return out


def _shape_literal_violations(source: str) -> list[str]:
    """Behavior 5's census: the filename shape must not be re-spelled by hand."""
    return [literal for literal in ("slate-", "001", ".json") if literal in source]


def _runtime_dependencies() -> list[str]:
    """The ``[project] dependencies`` list from ``pyproject.toml``, as strings."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
    assert match is not None, "no [project] dependencies list found in pyproject.toml"
    return re.findall(r'"([^"]+)"', match.group(1))


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


# ===========================================================================
# Behavior 1 -- trend's refusal keeps its byte-exact first line, rc 2, no stdout.
# ===========================================================================


def test_b1_trend_refusal_first_line_and_exit_code_are_unchanged(tmp_path, capsys) -> None:
    out_dir = _empty_stream_dir(tmp_path, "b1-empty")
    rc, out, err = _run(["trend", "--dir", str(out_dir)], capsys)

    assert rc == 2, f"expected exit 2, got {rc}"
    assert out == "", f"stdout must stay empty on the refusal path, got {out!r}"
    lines = _stderr_lines(err)
    assert lines[0] == TREND_FIRST_LINE.format(dir=out_dir), (
        "trend's FIRST stderr line changed:\n"
        f"  expected: {TREND_FIRST_LINE.format(dir=out_dir)!r}\n"
        f"  actual:   {lines[0]!r}"
    )


# ===========================================================================
# Behavior 2 -- trend's refusal adds the paste-ready producer hint.
# ===========================================================================


def test_b2_trend_refusal_adds_a_paste_ready_producer_hint(tmp_path, capsys) -> None:
    out_dir = _empty_stream_dir(tmp_path, "b2-empty")
    _rc, _out, err = _run(["trend", "--dir", str(out_dir)], capsys)

    hint = _hint_line(err)
    for needle in (HINT_COMMAND_PREFIX, str(out_dir.absolute()), _slate_name(1)):
        assert needle in hint, f"hint line is missing {needle!r}:\n{hint}"


# ===========================================================================
# Behavior 3 -- diff's refusal keeps its byte-exact first line, rc 2, no stdout.
# ===========================================================================


def test_b3_diff_refusal_first_line_and_exit_code_are_unchanged(tmp_path, capsys) -> None:
    out_dir = _one_slate_dir(tmp_path, capsys, "b3-one")
    rc, out, err = _run(["diff", "--dir", str(out_dir)], capsys)

    assert rc == 2, f"expected exit 2, got {rc}"
    assert out == "", f"stdout must stay empty on the refusal path, got {out!r}"
    lines = _stderr_lines(err)
    assert lines[0] == DIFF_FIRST_LINE.format(dir=out_dir), (
        "diff's FIRST stderr line changed:\n"
        f"  expected: {DIFF_FIRST_LINE.format(dir=out_dir)!r}\n"
        f"  actual:   {lines[0]!r}"
    )


# ===========================================================================
# Behavior 4 -- diff's refusal carries the SAME hint as trend's.
# ===========================================================================


def test_b4_diff_refusal_carries_the_same_producer_hint(tmp_path, capsys) -> None:
    out_dir = _one_slate_dir(tmp_path, capsys, "b4-one")
    _rc, _out, err = _run(["diff", "--dir", str(out_dir)], capsys)
    diff_hint = _hint_line(err)
    for needle in (HINT_COMMAND_PREFIX, str(out_dir.absolute()), _slate_name(1)):
        assert needle in diff_hint, f"hint line is missing {needle!r}:\n{diff_hint}"

    # Same directory, other verb: one definition, so the rendered text matches.
    _rc2, _out2, err2 = _run(["trend", "--dir", str(out_dir)], capsys)
    trend_lines = _stderr_lines(err2)
    if len(trend_lines) >= 2:
        assert _hint_line(err2) == diff_hint, (
            "the two verbs render DIFFERENT hints for the same directory, which "
            "means the string was hand-copied:\n"
            f"  diff:  {diff_hint!r}\n"
            f"  trend: {_hint_line(err2)!r}"
        )


# ===========================================================================
# Behavior 5 -- ONE helper, and its body re-spells no part of the shape.
# ===========================================================================


def test_b5a_the_hints_sentence_is_defined_exactly_once_in_cli_source(
    tmp_path, capsys
) -> None:
    out_dir = _empty_stream_dir(tmp_path, "b5a-empty")
    _rc, _out, err = _run(["trend", "--dir", str(out_dir)], capsys)
    prose = _hint_prose(err)
    assert len(prose) >= 12, f"hint prose too short to census: {prose!r}"

    needle = _squash(prose)
    haystack = _squash(CLI_SOURCE.read_text(encoding="utf-8"))
    assert haystack.count(needle) == 1, (
        f"the hint sentence {prose!r} appears {haystack.count(needle)} times in "
        "cli.py -- the two call sites must SHARE one definition, not copy a string"
    )


def test_b5b_the_hint_helper_body_holds_no_hand_copied_shape_literal(
    tmp_path, capsys
) -> None:
    out_dir = _empty_stream_dir(tmp_path, "b5b-empty")
    _rc, _out, err = _run(["trend", "--dir", str(out_dir)], capsys)
    prose = _hint_prose(err)

    needle = _squash(prose)
    carriers = {
        name: src
        for name, src in _module_level_functions().items()
        if needle in _squash(src)
    }
    assert len(carriers) == 1, (
        "expected exactly ONE module-level helper to carry the hint sentence, "
        f"found {sorted(carriers)}"
    )
    name, source = next(iter(carriers.items()))
    assert _shape_literal_violations(source) == [], (
        f"{name} re-spells the filename shape by hand instead of calling the "
        f"convention helper: {_shape_literal_violations(source)}"
    )
    # The shape and the path spelling both come from the shipped helpers.
    for callee in ("_stream_slate_name", "_pasteable_slate_arg"):
        assert callee in source, f"{name} does not call {callee}"


def test_b5c_the_shape_literal_census_fires_on_a_hand_copied_second_literal() -> None:
    """The behavior-5 census is proven to FIRE, not merely to pass."""
    planted = 'def _hint(d):\n    return f"see {_stream_slate_name(1)} in slate-001.json"\n'
    assert _shape_literal_violations(planted) == ["slate-", "001", ".json"], (
        "the census does not detect a hand-copied literal, so behavior 5's "
        "passing verdict would be vacuous"
    )


# ===========================================================================
# Behavior 6 -- drift guard, both directions.
# ===========================================================================


def test_b6a_rebinding_the_prefix_changes_the_name_the_hint_reports(
    tmp_path, capsys, monkeypatch
) -> None:
    out_dir = _empty_stream_dir(tmp_path, "b6a-empty")
    _rc, _out, err = _run(["trend", "--dir", str(out_dir)], capsys)
    before_hint = _hint_line(err)
    before_name = _slate_name(1)
    assert before_name in before_hint

    monkeypatch.setattr(cli, "_STREAM_SLATE_PREFIX", "tick-")
    after_name = _slate_name(1)
    assert after_name != before_name, (
        "rebinding _STREAM_SLATE_PREFIX did not change _stream_slate_name(1), so "
        "this drift guard cannot fire"
    )

    _rc2, _out2, err2 = _run(["trend", "--dir", str(out_dir)], capsys)
    after_hint = _hint_line(err2)
    assert after_name in after_hint, (
        f"hint still does not report the rebound name {after_name!r}:\n{after_hint}"
    )
    assert before_name not in after_hint, (
        f"hint kept the stale name {before_name!r} after the rebind:\n{after_hint}"
    )
    assert after_hint != before_hint, "the hint did not change at all"


def test_b6b_the_hint_path_is_absolute_not_resolved(tmp_path, capsys) -> None:
    """A symlinked stream dir keeps the spelling the user typed."""
    real = tmp_path / "real-stream"
    real.mkdir()
    link = tmp_path / "link-stream"
    link.symlink_to(real, target_is_directory=True)
    assert str(link.absolute()) != str(link.resolve()), (
        "precondition failed: the symlink does not distinguish absolute() from "
        "resolve(), so this case cannot tell them apart"
    )

    _rc, _out, err = _run(["trend", "--dir", str(link)], capsys)
    hint = _hint_line(err)
    assert str(link.absolute()) in hint, (
        f"hint does not spell the passed path {str(link.absolute())!r}:\n{hint}"
    )
    assert str(link.resolve()) not in hint, (
        "hint re-spelled the path through resolve(), which rewrites macOS "
        f"/var -> /private/var:\n{hint}"
    )


# ===========================================================================
# Behavior 7 -- the hint's OWN printed command produces a comparable stream.
# ===========================================================================


def test_b7_the_printed_command_produces_a_stream_diff_dir_accepts(
    tmp_path, capsys, monkeypatch
) -> None:
    """Parse the command the product PRINTED and run it -- do not retype it.

    Only the ALL-CAPS placeholders the hint leaves for the user are substituted;
    every other token is executed exactly as printed. An unknown placeholder is a
    failure, not a guess.
    """
    out_dir = _one_slate_dir(tmp_path, capsys, "b7-one")
    rc_refusal, _out, err = _run(["diff", "--dir", str(out_dir)], capsys)
    assert rc_refusal == 2

    printed = _hint_command(err)
    tokens = shlex.split(printed)
    assert tokens[0] == "pla", f"hint command does not start with `pla`: {printed!r}"
    argv: list[str] = []
    for token in tokens[1:]:
        if token in PLACEHOLDERS:
            argv.append(PLACEHOLDERS[token])
            continue
        assert not (token.isupper() and token.isalpha() and len(token) > 2), (
            f"hint leaves an unfillable placeholder {token!r}; this oracle can "
            f"only substitute {sorted(PLACEHOLDERS)}: {printed!r}"
        )
        argv.append(token)

    # Run it where a user would: their own cwd, so the default state dir
    # (`.pla_runs`) lands under tmp_path and never in the repo.
    monkeypatch.chdir(tmp_path)
    rc_watch, out_watch, err_watch = _run(argv, capsys)
    assert rc_watch == 0, (
        "the command the hint printed FAILED:\n"
        f"  argv:   {argv}\n  rc:     {rc_watch}\n  stderr: {err_watch}"
    )

    names = sorted(p.name for p in out_dir.iterdir())
    assert len(names) >= 2, (
        "the command the hint printed exited 0 but did not grow the stream to at "
        f"least two slates: {names}\nstdout was:\n{out_watch}"
    )

    rc_diff, out_diff, err_diff = _run(["diff", "--dir", str(out_dir)], capsys)
    assert rc_diff == 0, (
        f"diff --dir still refuses after following the hint (rc={rc_diff}): {err_diff}"
    )
    assert out_diff.strip() != "", "diff --dir exited 0 but printed nothing"


# ===========================================================================
# Behavior 8 -- the OTHER exit-2 path is untouched, for both verbs.
# ===========================================================================


def test_b8a_a_missing_dir_still_prints_only_the_existing_directory_refusal(
    tmp_path, capsys
) -> None:
    missing = tmp_path / "nope"
    for verb in VERBS:
        rc, out, err = _run([verb, "--dir", str(missing)], capsys)
        assert rc == 2, f"{verb}: expected exit 2, got {rc}"
        assert out == "", f"{verb}: stdout must stay empty, got {out!r}"
        assert _stderr_lines(err) == [NOT_A_DIR_LINE.format(dir=missing)], (
            f"{verb}: the missing-dir refusal changed:\n{err}"
        )


def test_b8b_a_file_dir_still_prints_only_the_existing_directory_refusal(
    tmp_path, capsys
) -> None:
    not_a_dir = tmp_path / "a-file.json"
    not_a_dir.write_text("{}", encoding="utf-8")
    for verb in VERBS:
        rc, out, err = _run([verb, "--dir", str(not_a_dir)], capsys)
        assert rc == 2, f"{verb}: expected exit 2, got {rc}"
        assert out == "", f"{verb}: stdout must stay empty, got {out!r}"
        assert _stderr_lines(err) == [NOT_A_DIR_LINE.format(dir=not_a_dir)], (
            f"{verb}: the not-a-directory refusal changed:\n{err}"
        )


# ===========================================================================
# Behavior 9 -- the refusal path stays inert; no dependency or lock drift.
# ===========================================================================


def test_b9a_the_refusal_path_builds_no_client_and_writes_no_file(
    tmp_path, capsys, monkeypatch
) -> None:
    clients = [name for name in dir(cli) if "LLMClient" in name]
    assert clients, "no LLMClient symbol on the cli module to guard"

    for verb in VERBS:
        out_dir = (
            _empty_stream_dir(tmp_path, f"b9a-{verb}")
            if verb == "trend"
            else _one_slate_dir(tmp_path, capsys, f"b9a-{verb}")
        )
        before = sorted((p.name, p.stat().st_size) for p in out_dir.iterdir())

        def _boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("--dir refusal built an LLM client")

        with monkeypatch.context() as patch:
            for name in clients:
                patch.setattr(cli, name, _boom)
            patch.chdir(tmp_path)
            rc, out, _err = _run([verb, "--dir", str(out_dir)], capsys)

        assert rc == 2, f"{verb}: expected exit 2, got {rc}"
        assert out == "", f"{verb}: stdout must stay empty, got {out!r}"
        after = sorted((p.name, p.stat().st_size) for p in out_dir.iterdir())
        assert after == before, (
            f"{verb} --dir wrote into the stream dir: {before} -> {after}"
        )
        assert not (tmp_path / ".pla_runs").exists(), (
            f"{verb} --dir created a state directory on the refusal path"
        )

    # ------------------------------------------------------------------ #
    # state-dir iteration 386 (ships as ``factory iter 299``) -- the
    # scripted-provider refusal gains a paste-ready ``hint:`` line naming
    # the bundled ``examples/scripted_responses.json``. Landed as ARMS
    # inside this existing function BY CONSTRUCTION, not by preference:
    # four shipped modules pin ``(live + 1) // 100 * 100 ==
    # published_floor()`` against floor 5900 at live=5998, so ONE new
    # collected item -- a module, a function or a parametrize case --
    # moves the floor and reds a PUBLIC build. This function's subject,
    # a refusal that stays inert, is the same subject one refusal further
    # up the on-ramp.
    # ------------------------------------------------------------------ #
    shipped_error_line = (
        "error: provider is 'scripted' but no scripted_responses_path was configured. "
        "Set PLA_SCRIPTED_RESPONSES (or pass --scripted-responses) to a JSON script "
        "file, or choose a live provider (anthropic, openai, bedrock, ollama, groq, "
        "together)."
    )
    unconfigured_ws = tmp_path / "b9a-unconfigured-ws"
    unconfigured_ws.mkdir()
    (unconfigured_ws / "TODO.md").write_text(
        "- TODO: give the collectors something to perceive\n", encoding="utf-8"
    )

    def _unconfigured(head: list[str], cwd: Path, tag: str) -> tuple[int, str, str, Path]:
        """Drive a synthesizing verb with provider ``scripted`` and NO script."""
        state = tmp_path / f"b9a-state-{tag}"
        with monkeypatch.context() as patch:
            for var in ("PLA_SCRIPTED_RESPONSES", "PLA_PROVIDER", "PLA_STATE_DIR"):
                patch.delenv(var, raising=False)
            patch.chdir(cwd)
            rc_, out_, err_ = _run(
                [*head, "--workspace", str(unconfigured_ws), "--state-dir", str(state)],
                capsys,
            )
        return rc_, out_, err_, state

    # Behaviors 1-4, 6 (scan) and 7, from a cwd holding no ``examples/`` dir.
    rc, out, err, _state = _unconfigured(["scan"], tmp_path, "scan-tmpcwd")
    lines = _stderr_lines(err)
    error_lines = [line for line in lines if line.startswith("error: ")]
    hints = [line for line in lines if line.strip().startswith("hint: ")]
    assert len(hints) == 1, f"expected exactly one `hint: ` line, got {hints!r}\n{err}"
    assert "examples/scripted_responses.json" in hints[0], (
        f"the hint does not name the bundled script: {hints[0]!r}"
    )
    assert "--scripted-responses" in hints[0], (
        f"the hint does not name the flag that consumes it: {hints[0]!r}"
    )
    assert len(error_lines) == 1, (
        f"expected exactly one `error: ` line, got {error_lines!r}"
    )
    assert error_lines[0] == shipped_error_line, (
        "the shipped refusal line moved; README and three test docstrings quote it\n"
        f"  expected: {shipped_error_line!r}\n  actual:   {error_lines[0]!r}"
    )
    assert lines == [shipped_error_line, hints[0]], (
        f"the hint must be its own un-prefixed line AFTER the error line: {lines!r}"
    )
    assert not hints[0].startswith("error: "), (
        f"the hint carries an `error: ` prefix: {hints[0]!r}"
    )
    assert rc == 1, f"scan must still exit 1 on this refusal, got {rc}"
    assert out == "", f"stdout must stay empty on this refusal, got {out!r}"

    # Behavior 5 -- byte-identical from the repo root, where the named file DOES
    # exist. The hint is unconditional, so nothing probes the filesystem.
    rc_repo, out_repo, err_repo, _ = _unconfigured(["scan"], REPO, "scan-repocwd")
    assert (rc_repo, out_repo, err_repo) == (rc, out, err), (
        "the refusal is cwd-sensitive, so something probes the filesystem:\n"
        f"  tmp cwd:  {(rc, out, err)!r}\n  repo cwd: {(rc_repo, out_repo, err_repo)!r}"
    )

    # Behavior 7 -- ``--json`` moves neither stdout nor the two stderr lines.
    rc_json, out_json, err_json, _ = _unconfigured(
        ["scan", "--json"], tmp_path, "scan-json"
    )
    assert (rc_json, out_json) == (1, ""), (
        f"--json refusal drifted: rc={rc_json} stdout={out_json!r}"
    )
    assert _stderr_lines(err_json) == lines, (
        f"--json changed the refusal lines:\n{err_json}"
    )

    # Behavior 6 -- ``watch`` still exits 0, still prints its per-tick line, and
    # still creates no state dir and no slate (the test_iter196 contract).
    rc_watch, out_watch, err_watch, watch_state = _unconfigured(
        ["watch", "--interval", "0", "--max-scans", "1"], tmp_path, "watch"
    )
    assert rc_watch == 0, f"watch must stay resilient per tick, got {rc_watch}"
    assert "scan 1 failed: " in err_watch, (
        f"watch dropped its per-tick failure line:\n{err_watch}"
    )
    watch_hints = [
        line for line in _stderr_lines(err_watch) if line.strip().startswith("hint: ")
    ]
    assert watch_hints == [hints[0]], (
        f"the failed tick must carry the same single hint: {watch_hints!r}"
    )
    assert not watch_state.exists(), "the failed tick created a state directory"
    assert "slate written:" not in out_watch, (
        f"the failed tick wrote a slate:\n{out_watch}"
    )


def test_b9b_no_runtime_dependency_or_lock_change_lands_with_this_feature() -> None:
    changed = {
        line.strip()
        for line in _git("diff", "--name-only", "HEAD").splitlines()
        if line.strip()
    }
    assert "uv.lock" not in changed, "uv.lock drifted; CI runs `uv sync --locked`"
    assert "pyproject.toml" not in changed, (
        "pyproject.toml changed: this feature adds no dependency"
    )
    deps = _runtime_dependencies()
    assert deps and all(spec.lower().startswith("pydantic") for spec in deps), (
        f"runtime dependencies are no longer pydantic-only: {deps}"
    )


# ===========================================================================
# Acceptance criteria -- the retired ledger pin and this iteration's row.
# ===========================================================================


def test_ac1_the_ledger_max_id_pin_is_gone_from_test_iter256() -> None:
    """The pin that reds the build on every new ledger row must not return."""
    source = (REPO / "tests" / "test_iter256_behavior.py").read_text(encoding="utf-8")
    assert "max(ids)" not in source, (
        "tests/test_iter256_behavior.py pins the highest ledger id again; the "
        "append-only invariant is owned by test_iter251_behavior.py::test_b8c"
    )


def test_ac2_the_roadmap_ledger_records_this_iteration_exactly_once() -> None:
    roadmap = (REPO / "ROADMAP.md").read_text(encoding="utf-8")
    tag = "(foundry iter 289)"
    assert roadmap.count(tag) == 1, (
        f"expected exactly one {tag} row in ROADMAP.md, found {roadmap.count(tag)}"
    )
    rows = [line for line in roadmap.splitlines() if tag in line]
    row = rows[0]
    assert row.lstrip().startswith("- #272 "), f"row is not ledger id 272: {row!r}"
    assert "pla watch --out-dir" in row, f"row does not name the feature: {row!r}"
