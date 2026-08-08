"""Black-box behavior tests for factory iteration 123 --- ``pla diff --dir DIR``.

Feature under test: a ``--dir DIR`` selector mode on the ``pla diff`` verb that
resolves the two newest ``slate-<NNN>.json`` ticks in a ``pla watch --out-dir``
stream directory and diffs them, so the pair the README already advertises as
composable actually composes without human filename arithmetic. ``--new`` binds
to the highest tick index present and ``--old`` to the second-highest, compared
as PARSED INTEGERS (so ``slate-1000.json`` beats ``slate-999.json``); directory
entries that are not stream files are ignored; and every wrong invocation stays
a usage error (exit 2) with a single ``error: ``-prefixed stderr line rather
than a traceback. The explicit ``--old``/``--new`` contract, and the producer's
observable output, are unchanged.

ISOLATION CONTRACT (honored): written strictly against this iteration's spec
(``pm.md`` "Expected Behaviors" 1-12) and the published ``README.md``. The tests
drive only documented public surfaces --- the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (its observable stdout / stderr / exit
codes / on-disk artifacts), ``pla diff --help``, and the public
``proactive_loop.models`` schema as a parse oracle. **No file under ``src/`` was
read by the author, no engineer/reviewer notes were read, and no ``git diff``
was consulted.** Behavior 10 is a SOURCE-STRUCTURE claim that the spec requires
to be pinned, so it is asserted MECHANICALLY: the test parses
``proactive_loop.cli``'s own file with ``ast`` and asserts shape only (in-tree
precedent: ``tests/test_iter117_behavior.py`` derives the exit-code contract
from ``main()``'s source). No implementation logic is read or mirrored.

Fully offline and deterministic: zero network, zero API keys, the scripted
provider seam only, no sleeps. Synthetic ``tmp_path`` workspaces throughout
(never the in-repo tree), so the git_activity / working_tree / test_posture
collectors cannot leak repo state (iter-15 lesson), and every ``watch`` is
bounded by a small ``--max-scans`` (an unbounded run would hang the suite).

AMBIGUITY NOTES (PM feedback):

* Behavior 4 requires the stderr line to "contain ... the fact that at least two
  stream slates are required". A word-for-word match would pin a phrasing, so
  the guard requires the directory path, a two-ness token (``two`` or ``2``) and
  the word ``slate`` in the SAME single ``error:`` line --- the claim, not the
  wording.
* Behavior 10 says the convention lives in "exactly ONE module-level location".
  A derived index REGEX is a second module-level string that legitimately
  contains ``slate-``, so the guard pins the FILENAME TEMPLATE (the only
  module-level literal carrying both ``slate-`` and a ``:03d`` placeholder) and
  separately forbids inline construction anywhere in the module (an f-string or
  ``.format`` on a literal that builds a zero-padded slate name). Prose/help
  literals mentioning ``slate-<NNN>.json`` are deliberately NOT flagged --- they
  are documentation, not a second source of truth.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import re
from pathlib import Path

import pytest

from proactive_loop import cli as cli_module
from proactive_loop.cli import main
from proactive_loop.models import GoalSlate

_CLI_SOURCE = Path(cli_module.__file__).resolve()

_JSON_KEYS = {"old", "new", "added", "removed", "changed", "unchanged_count"}

_STREAM_NAME_RE = re.compile(r"^slate-\d+\.json$")


# ---------------------------------------------------------------------------
# Helpers --- black-box: build a synthetic workspace + scripted script, drive
# main(), read back stdout / stderr / exit code / on-disk artifacts. (Local
# copies of the iter-120 / iter-122 watch helpers: a local copy is lower risk
# than a cross-module test import.)
# ---------------------------------------------------------------------------


def _workspace(tmp_path: Path) -> Path:
    """A minimal, real, synthetic workspace directory (one source file)."""
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    (ws / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    return ws


def _goal_dict(title: str, *, impact: float = 5.0) -> dict:
    """One goal dict matching the documented synthesize JSON contract."""
    return {
        "title": title,
        "rationale": "black-box diff --dir probe",
        "category": "learning",
        "impact": impact,
        "urgency": 5.0,
        "confidence": 1.0,
        "effort_weight": 1.0,
        "appropriate_now": True,
        "sources": ["foo.py"],
        "suggested_first_steps": ["do a thing"],
    }


def _script(tmp_path: Path, titles: list[str], *, name: str = "script.json") -> Path:
    """One ``synthesize`` response per tick, each with a distinct goal title."""
    responses = [
        {"tag": "synthesize", "text": json.dumps([_goal_dict(t)])} for t in titles
    ]
    path = tmp_path / name
    path.write_text(json.dumps({"responses": responses}), encoding="utf-8")
    return path


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Drive main() and return (exit_code, stdout, stderr)."""
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _watch_argv(
    ws: Path,
    script: Path,
    *,
    state_dir: Path,
    max_scans: str,
    out_dir: Path | str | None = None,
) -> list[str]:
    argv = [
        "watch",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(script),
        "--interval", "0",
        "--max-scans", max_scans,
        "--state-dir", str(state_dir),
    ]
    if out_dir is not None:
        argv += ["--out-dir", str(out_dir)]
    return argv


def _stream(tmp_path: Path, titles: list[str], capsys, *, name: str = "stream") -> Path:
    """A REAL stream directory: one persisted slate per tick, via the producer."""
    ws = _workspace(tmp_path)
    script = _script(tmp_path, titles, name=f"script-{name}.json")
    out = tmp_path / name
    rc = main(
        _watch_argv(
            ws,
            script,
            state_dir=tmp_path / f"state-{name}",
            max_scans=str(len(titles)),
            out_dir=out,
        )
    )
    capsys.readouterr()
    assert rc == 0, "producer setup failed: watch --out-dir did not exit 0"
    return out


def _reindex(src: Path, mapping: dict[str, str], dest: Path) -> Path:
    """Copy real slate BYTES from a produced stream into arbitrary tick names."""
    dest.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in mapping.items():
        (dest / dst_name).write_bytes((src / src_name).read_bytes())
    return dest


def _error_lines(err: str) -> list[str]:
    return [ln for ln in err.splitlines() if ln.startswith("error:")]


def _assert_single_usage_error(rc: int, out: str, err: str) -> str:
    """Exit 2, empty stdout, exactly one ``error: `` line, no traceback."""
    assert rc == 2, f"expected exit 2, got {rc} (stderr={err!r})"
    assert out == "", f"expected empty stdout on a usage error, got {out!r}"
    lines = _error_lines(err)
    assert len(lines) == 1, f"expected exactly one error: line, got {lines!r}"
    assert "Traceback" not in err and "Traceback" not in out
    return lines[0]


def _listing(root: Path) -> list[tuple[str, int, str]]:
    """Exact recursive listing: (relative path, size, content hash)."""
    entries: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_dir():
            entries.append((rel + "/", -1, "dir"))
        else:
            data = path.read_bytes()
            entries.append((rel, len(data), hashlib.sha256(data).hexdigest()))
    return entries


@functools.lru_cache(maxsize=1)
def _cli_tree() -> ast.Module:
    """Parsed ONCE and cached: the doc/help allowlist keys on node identity, so
    every helper below must walk the SAME tree object."""
    return ast.parse(_CLI_SOURCE.read_text(encoding="utf-8"))


# ===========================================================================
# Behavior 1 --- happy path: the two NEWEST by index, byte-identical stdout.
# ===========================================================================


def test_b01_dir_mode_selects_two_newest_and_matches_explicit_paths(tmp_path, capsys):
    d = _stream(tmp_path, ["alpha", "beta", "gamma"], capsys)

    rc_explicit, out_explicit, err_explicit = _run(
        ["diff", "--old", str(d / "slate-002.json"), "--new", str(d / "slate-003.json")],
        capsys,
    )
    assert rc_explicit == 0, err_explicit

    rc_dir, out_dir, err_dir = _run(["diff", "--dir", str(d)], capsys)

    assert rc_dir == 0, err_dir
    assert out_dir == out_explicit, (
        "--dir stdout must be byte-identical to the explicit two-newest pair"
    )
    assert _error_lines(err_dir) == []
    assert "slate-001" not in out_dir


# ===========================================================================
# Behavior 2 --- ordering is by parsed integer, never lexicographic.
# ===========================================================================


def test_b02_ordering_is_numeric_not_lexicographic(tmp_path, capsys):
    src = _stream(tmp_path, ["older", "newer"], capsys)
    d = _reindex(
        src,
        {"slate-001.json": "slate-999.json", "slate-002.json": "slate-1000.json"},
        tmp_path / "numeric",
    )

    rc_explicit, out_explicit, _ = _run(
        ["diff", "--old", str(d / "slate-999.json"), "--new", str(d / "slate-1000.json")],
        capsys,
    )
    assert rc_explicit == 0

    rc_dir, out_dir, err_dir = _run(["diff", "--dir", str(d)], capsys)

    assert rc_dir == 0, err_dir
    assert out_dir == out_explicit, (
        "slate-1000.json must win over slate-999.json (integer, not string, order)"
    )


# ===========================================================================
# Behavior 3 --- non-stream entries are ignored, not errors.
# ===========================================================================


def test_b03_non_stream_entries_are_ignored(tmp_path, capsys):
    d = _stream(tmp_path, ["first", "second"], capsys)
    payload = (d / "slate-002.json").read_bytes()
    for decoy in ("slate.json", "slate-abc.json", "slate-01.json.bak", "notes.txt"):
        (d / decoy).write_bytes(payload)
    (d / "slate-002.json.tmp").write_bytes(payload)
    (d / "slate-003.json").mkdir()

    rc_explicit, out_explicit, _ = _run(
        ["diff", "--old", str(d / "slate-001.json"), "--new", str(d / "slate-002.json")],
        capsys,
    )
    assert rc_explicit == 0

    rc_dir, out_dir, err_dir = _run(["diff", "--dir", str(d)], capsys)

    assert rc_dir == 0, err_dir
    assert out_dir == out_explicit, (
        "decoys (incl. a DIRECTORY named slate-003.json and a .tmp sibling) "
        "must never be selected"
    )


# ===========================================================================
# Behavior 4 --- fewer than two stream files is a usage error (exit 2).
# ===========================================================================


@pytest.mark.parametrize("keep", [0, 1])
def test_b04_too_few_stream_slates_is_a_usage_error(tmp_path, capsys, keep):
    src = _stream(tmp_path, ["one", "two"], capsys)
    d = tmp_path / f"thin-{keep}"
    mapping = {f"slate-{i:03d}.json": f"slate-{i:03d}.json" for i in range(1, keep + 1)}
    _reindex(src, mapping, d)
    (d / "notes.txt").write_text("not a slate\n", encoding="utf-8")

    rc, out, err = _run(["diff", "--dir", str(d)], capsys)

    line = _assert_single_usage_error(rc, out, err)
    assert str(d) in line, f"the error must name the directory: {line!r}"
    low = line.lower()
    assert "slate" in low, f"the error must mention slates: {line!r}"
    assert "two" in low or "2" in line, (
        f"the error must state that at least two are required: {line!r}"
    )


# ===========================================================================
# Behavior 5 --- a bad --dir target is a usage error, not a traceback.
# ===========================================================================


def test_b05_missing_dir_is_a_usage_error(tmp_path, capsys):
    rc, out, err = _run(["diff", "--dir", str(tmp_path / "nope")], capsys)
    line = _assert_single_usage_error(rc, out, err)
    assert "--dir" in line


def test_b05_dir_that_is_a_regular_file_is_a_usage_error(tmp_path, capsys):
    target = tmp_path / "afile"
    target.write_text("{}", encoding="utf-8")

    rc, out, err = _run(["diff", "--dir", str(target)], capsys)

    line = _assert_single_usage_error(rc, out, err)
    assert "--dir" in line
    assert str(target) in line


# ===========================================================================
# Behavior 6 --- --dir conflicts with the explicit-path mode.
# ===========================================================================


@pytest.mark.parametrize("extra", [["--old", "OLD", "--new", "NEW"], ["--old", "OLD"], ["--new", "NEW"]])
def test_b06_dir_conflicts_with_explicit_paths(tmp_path, capsys, extra):
    d = _stream(tmp_path, ["alpha", "beta"], capsys)
    old = str(d / "slate-001.json")
    new = str(d / "slate-002.json")
    argv = ["diff", "--dir", str(d)]
    for token in extra:
        argv.append({"OLD": old, "NEW": new}.get(token, token))

    rc, out, err = _run(argv, capsys)

    line = _assert_single_usage_error(rc, out, err)
    assert "--dir" in line, f"the conflict error must name --dir: {line!r}"
    assert "--old" in line or "--new" in line, (
        f"the conflict error must name the other mode: {line!r}"
    )


# ===========================================================================
# Behavior 7 --- incomplete invocations still exit 2 (mode-switch regression).
# ===========================================================================


@pytest.mark.parametrize("selectors", [[], ["--old"], ["--new"]])
def test_b07_incomplete_invocations_still_exit_2(tmp_path, capsys, selectors):
    d = _stream(tmp_path, ["alpha", "beta"], capsys)
    argv = ["diff"]
    if selectors == ["--old"]:
        argv += ["--old", str(d / "slate-001.json")]
    elif selectors == ["--new"]:
        argv += ["--new", str(d / "slate-002.json")]

    rc, out, err = _run(argv, capsys)

    _assert_single_usage_error(rc, out, err)


# ===========================================================================
# Behavior 8 --- the pre-existing explicit-path contract is unchanged.
# ===========================================================================


def test_b08_explicit_pair_still_exits_0(tmp_path, capsys):
    d = _stream(tmp_path, ["alpha", "beta"], capsys)

    rc, out, err = _run(
        ["diff", "--old", str(d / "slate-001.json"), "--new", str(d / "slate-002.json")],
        capsys,
    )

    assert rc == 0, err
    assert out.strip() != ""


def test_b08_missing_paths_still_exit_2_with_old_checked_first(tmp_path, capsys):
    d = _stream(tmp_path, ["alpha", "beta"], capsys)
    good_old = str(d / "slate-001.json")
    good_new = str(d / "slate-002.json")
    ghost_old = str(tmp_path / "ghost-old.json")
    ghost_new = str(tmp_path / "ghost-new.json")

    rc, out, err = _run(["diff", "--old", ghost_old, "--new", good_new], capsys)
    line = _assert_single_usage_error(rc, out, err)
    assert ghost_old in line

    rc, out, err = _run(["diff", "--old", good_old, "--new", ghost_new], capsys)
    line = _assert_single_usage_error(rc, out, err)
    assert ghost_new in line

    # "--old checked FIRST" is observable as WHICH path the single line names
    # when both are bad (the message identifies the file, not the flag).
    rc, out, err = _run(["diff", "--old", ghost_old, "--new", ghost_new], capsys)
    line = _assert_single_usage_error(rc, out, err)
    assert ghost_old in line and ghost_new not in line, (
        f"--old must be reported FIRST when both are bad: {line!r}"
    )

    rc, out, err = _run(["diff", "--old", str(d), "--new", good_new], capsys)
    _assert_single_usage_error(rc, out, err)


def test_b08_corrupt_slate_still_exits_1(tmp_path, capsys):
    d = _stream(tmp_path, ["alpha", "beta"], capsys)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json at all", encoding="utf-8")

    rc, out, err = _run(
        ["diff", "--old", str(d / "slate-001.json"), "--new", str(broken)], capsys
    )

    assert rc == 1, f"a corrupt slate must exit 1 via the error boundary, got {rc}"
    assert _error_lines(err), f"expected an error: line, got {err!r}"
    assert "Traceback" not in err


# ===========================================================================
# Behavior 9 --- --json in --dir mode echoes the RESOLVED paths.
# ===========================================================================


def test_b09_json_dir_mode_echoes_resolved_paths(tmp_path, capsys):
    d = _stream(tmp_path, ["alpha", "beta", "gamma"], capsys)

    rc_explicit, out_explicit, _ = _run(
        [
            "diff",
            "--old", str(d / "slate-002.json"),
            "--new", str(d / "slate-003.json"),
            "--json",
        ],
        capsys,
    )
    assert rc_explicit == 0
    explicit = json.loads(out_explicit)

    rc, out, err = _run(["diff", "--dir", str(d), "--json"], capsys)

    assert rc == 0, err
    payload = json.loads(out)
    assert isinstance(payload, dict)
    assert set(payload) == set(explicit) == _JSON_KEYS
    assert isinstance(payload["old"], str) and isinstance(payload["new"], str)
    assert Path(payload["old"]).name == "slate-002.json"
    assert Path(payload["new"]).name == "slate-003.json"
    assert Path(payload["old"]).resolve() == (d / "slate-002.json").resolve()
    assert Path(payload["new"]).resolve() == (d / "slate-003.json").resolve()


# ===========================================================================
# Behavior 10 --- the filename convention is single-sourced (structural).
# ===========================================================================


def _module_level_str_constants() -> dict[str, str]:
    consts: dict[str, str] = {}
    for node in _cli_tree().body:
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                consts[target.id] = value.value
    return consts


def _inline_padded_slate_literals() -> list[str]:
    """Any INLINE construction of a zero-padded slate filename."""
    offenders: list[str] = []
    for node in ast.walk(_cli_tree()):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                p.value
                for p in node.values
                if isinstance(p, ast.Constant) and isinstance(p.value, str)
            )
            if "slate-" not in text:
                continue
            specs: list[str] = []
            for part in node.values:
                if isinstance(part, ast.FormattedValue) and part.format_spec is not None:
                    specs.append(
                        "".join(
                            c.value
                            for c in part.format_spec.values
                            if isinstance(c, ast.Constant) and isinstance(c.value, str)
                        )
                    )
            if any("03d" in spec for spec in specs):
                offenders.append(ast.unparse(node))
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "format"
                and isinstance(func.value, ast.Constant)
                and isinstance(func.value.value, str)
                and "slate-" in func.value.value
            ):
                offenders.append(ast.unparse(node))
    return offenders


def _slate_literal_nodes() -> list[ast.Constant]:
    return [
        node
        for node in ast.walk(_cli_tree())
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "slate-" in node.value
    ]


def _doc_and_help_literal_ids() -> set[int]:
    """Literals that are DOCUMENTATION, not a source of truth: docstrings and
    argparse help/description/metavar/epilog values."""
    tree = _cli_tree()
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                allowed.add(id(body[0].value))
        if isinstance(node, ast.keyword) and node.arg in {
            "help",
            "description",
            "metavar",
            "epilog",
            "usage",
        }:
            if isinstance(node.value, ast.Constant):
                allowed.add(id(node.value))
    return allowed


def _module_level_slate_literal_names() -> dict[str, str]:
    return {
        name: value
        for name, value in _module_level_str_constants().items()
        if "slate-" in value
    }


def test_b10_stream_filename_convention_is_single_sourced():
    """Exactly ONE module-level definition carries the ``slate-`` convention."""
    defs = _module_level_slate_literal_names()

    assert len(defs) == 1, (
        "exactly ONE module-level definition of the stream-filename convention "
        f"expected, found {sorted(defs)}"
    )
    name, value = next(iter(defs.items()))
    assert value.startswith("slate-"), f"{name} = {value!r}"
    assert getattr(cli_module, name) == value


def test_b10_no_inline_slate_literal_outside_docs_and_help():
    """No function body may carry its own ``slate-`` literal: the writer and the
    resolver have to consume the single module-level definition."""
    allowed = _doc_and_help_literal_ids()
    module_def_linenos = {
        node.lineno
        for node in _cli_tree().body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and "slate-" in node.value.value
    }
    offenders = [
        (node.lineno, node.value)
        for node in _slate_literal_nodes()
        if id(node) not in allowed and node.lineno not in module_def_linenos
    ]

    assert offenders == [], (
        "a second, inline source of truth for the stream-filename convention: "
        f"{offenders!r}"
    )


def test_b10_no_inline_padded_filename_construction():
    """The old inline ``f"slate-{count:03d}.json"`` must be gone for good."""
    offenders = _inline_padded_slate_literals()
    assert offenders == [], (
        "the slate-<NNN>.json name must never be built inline; found: "
        f"{offenders!r}"
    )


def test_b10_writer_and_resolver_agree_on_the_single_convention(tmp_path, capsys):
    """The one definition is what the PRODUCER writes and the RESOLVER reads."""
    name, value = next(iter(_module_level_slate_literal_names().items()))
    d = _stream(tmp_path, ["alpha", "beta"], capsys)

    produced = sorted(q.name for q in d.iterdir())
    assert produced == ["slate-001.json", "slate-002.json"]
    assert all(n.startswith(value) for n in produced), (
        f"the producer must build names from {name} = {value!r}"
    )

    rc, out, err = _run(["diff", "--dir", str(d), "--json"], capsys)
    assert rc == 0, err
    payload = json.loads(out)
    assert [Path(payload["old"]).name, Path(payload["new"]).name] == produced


# ===========================================================================
# Behavior 11 --- the producer's observable output is untouched.
# ===========================================================================


def test_b11_producer_names_trailer_and_no_tmp_are_unchanged(tmp_path, capsys):
    ws = _workspace(tmp_path)
    script = _script(tmp_path, ["alpha", "beta"], name="producer.json")
    out_dir = tmp_path / "produced"

    rc, out, err = _run(
        _watch_argv(
            ws, script, state_dir=tmp_path / "state-producer", max_scans="2", out_dir=out_dir
        ),
        capsys,
    )

    assert rc == 0, err
    names = sorted(p.name for p in out_dir.iterdir())
    assert names == ["slate-001.json", "slate-002.json"]
    assert not any(p.name.endswith(".tmp") for p in out_dir.iterdir())
    trailers = [ln for ln in out.splitlines() if ln.startswith("slate written:")]
    assert trailers == [
        f"slate written: {out_dir / 'slate-001.json'}",
        f"slate written: {out_dir / 'slate-002.json'}",
    ]
    for name in names:
        GoalSlate.model_validate_json((out_dir / name).read_text(encoding="utf-8"))


# ===========================================================================
# Behavior 12 --- --dir mode stays read-only and LLM-free.
# ===========================================================================


@pytest.mark.parametrize(
    "provider_argv",
    [
        ["--provider", "scripted", "--scripted-responses", "NO_SUCH_SCRIPT"],
        ["--provider", "anthropic"],
    ],
)
def test_b12_dir_mode_builds_no_client_and_mutates_nothing(tmp_path, capsys, provider_argv):
    d = _stream(tmp_path, ["alpha", "beta", "gamma"], capsys)
    argv = ["diff", "--dir", str(d)]
    for token in provider_argv:
        argv.append(str(tmp_path / "missing-script.json") if token == "NO_SUCH_SCRIPT" else token)

    before = _listing(d)
    rc, out, err = _run(argv, capsys)
    after = _listing(d)

    assert rc == 0, f"--dir must not build an LLM client (stderr={err!r})"
    assert out.strip() != ""
    assert after == before, "--dir mode must not mutate the stream directory"
