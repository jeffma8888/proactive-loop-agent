"""Black-box behavior tests for ``pla scan --from-snapshot FILE`` (foundry iter 270 re-land).

Feature under test: ``scan --snapshot FILE`` WRITES the perception a slate was synthesized
from, and ``--from-snapshot FILE`` is its READ half -- it replays that recorded document in
place of collecting the workspace, so a scan can be re-examined against saved evidence.
Only perception is replayed; synthesis is still an LLM call (the scripted provider here).

WHAT THIS MODULE GRADES (ONE collected item -- ``make readme-headroom`` read
``binding_headroom=6 == tests/test_iter263_behavior.py::MIN_BINDING_HEADROOM`` at the parent
commit, so the module is funded 1:1 by retiring the assert-message-only twin listed in
``RETIRED_TESTS``; every behavior is a ``_bN_`` helper called from the one body, never a
second item or a parametrization):
(1) the flag exists, a replayed scan exits 0 and writes the slate where a collecting scan
would, and ``--workspace`` stays required; (2) replay REPLACES collection -- the written
``--snapshot`` is byte-identical to the replayed document while a live TODO in the workspace
never leaks in; (3) the replayed ``workspace_root`` is the document's (a non-string root falls
back to ``--workspace``); (4) ``--exclude-path`` narrows a replay with the shipped
``_path_excluded`` predicate, keeps order, and never drops a path-less entry, not even for
``*``; (5) ``--collector`` with it is one ``error:`` line at exit 2, decided after the
workspace guard and before any client or file; (6) each of the seven malformed-document cases
is one ``error: from-snapshot file ...`` line at exit 2 with nothing written, while the
``--baseline`` / ``verify --snapshot`` wording is unchanged; (7) a schema-invalid value is the
same clean exit-2 refusal naming the entry and the field, never a pydantic dump; (8) extra
entry keys are dropped, so the published document does not widen; (9) the flag is on ``scan``
only and documented in ``scan --help``, SPEC 4.5's ``scan`` bullet and the README ``## CLI``
``scan`` row, none of which claims more than a replay of recorded evidence.

Fully offline: ``main()`` runs in-process with ``--provider scripted`` against ``tmp_path``
workspaces. No network, no sleeps, no wall-clock assertion, no gitignored state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Final

import pytest

from proactive_loop.cli import _path_excluded, build_parser, main

REPO: Final[Path] = Path(__file__).resolve().parents[1]
SCRIPT: Final[Path] = REPO / "examples" / "scripted_responses.json"
SPEC: Final[Path] = REPO / "SPEC.md"
README: Final[Path] = REPO / "README.md"
FLAG: Final[str] = "--from-snapshot"
IDENTITY_KEYS: Final[tuple[str, ...]] = ("source", "kind", "summary", "detail", "path", "weight")
FORBIDDEN: Final[tuple[str, ...]] = ("reproducib", "determinis")
LIVE_TODO: Final[str] = "live tree finding"

#: Funding: the assert-message-only duplicate retired in this commit. Its body made the
#: same ``main(["--version"])`` call and the same two assertions as the keeper below.
RETIRED_TESTS: Final[tuple[tuple[str, str], ...]] = (
    ("test_iter97_behavior.py", "test_b6_cli_version_prints_pla_0_1_1_and_exits_zero"),
)
#: The canonical copy that must SURVIVE (the lowest-numbered module holding the pair).
KEEPERS: Final[tuple[tuple[str, str], ...]] = (
    ("test_iter07_behavior.py", "test_behavior11b_version_unchanged"),
)


class _Env:
    """One tmp_path layout: a recorded source tree, a live workspace, and a runner."""

    def __init__(self, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self.root = root
        self.capsys = capsys
        self.src = root / "src"
        self.ws = root / "ws"
        self.src.mkdir()
        self.ws.mkdir()
        (self.src / "rec.py").write_text("y = 2  # TODO: recorded finding\n")
        (self.ws / "live.py").write_text(f"x = 1  # TODO: {LIVE_TODO}\n")
        self.runs = 0

    def scan(self, *extra: str, workspace: Path | None = None, script: Path = SCRIPT) -> tuple[int, str, str, Path]:
        """Run ``pla scan`` in-process; return (exit, stdout, stderr, state_dir)."""
        self.runs += 1
        state = self.root / f"state{self.runs}"
        argv = [
            "scan", "--workspace", str(workspace or self.ws), "--provider", "scripted",
            "--scripted-responses", str(script), "--state-dir", str(state), *extra,
        ]
        self.capsys.readouterr()
        code = main(argv)
        out, err = self.capsys.readouterr()
        return code, out, err, state

    def record(self) -> Path:
        """A canonical document, written by a real ``scan --snapshot`` of ``src``."""
        doc = self.root / "canon.json"
        code, _out, err, _state = self.scan("--snapshot", str(doc), "--format", "json", workspace=self.src)
        assert code == 0 and err == "", err
        return doc

    def write(self, name: str, document: Any) -> Path:
        path = self.root / name
        path.write_text(json.dumps(document, indent=2))
        return path


def _assert_refused(env: _Env, result: tuple[int, str, str, Path], out: Path, needle: str) -> str:
    code, stdout, stderr, state = result
    lines = stderr.splitlines()
    assert code == 2, (code, stderr)
    assert stdout == "", stdout
    assert len(lines) == 1 and lines[0].startswith("error: "), lines
    assert needle in lines[0], (needle, lines[0])
    assert not (state / "slate.json").exists(), "a refusal must write no slate"
    assert not out.exists(), "a refusal must write no snapshot"
    return lines[0]


def _b1_b2_b3_replay_replaces_collection(env: _Env, canon: Path) -> None:
    live = env.root / "live.json"
    code, _out, _err, _state = env.scan("--snapshot", str(live), "--format", "json")
    assert code == 0 and LIVE_TODO in live.read_text(), "precondition: a real collect of ws reports the TODO"
    assert LIVE_TODO not in canon.read_text(), "precondition: the recorded document does not"

    out = env.root / "out.json"
    code, stdout, stderr, state = env.scan(FLAG, str(canon), "--snapshot", str(out), "--format", "json")
    assert code == 0 and stderr == "", stderr
    assert json.loads(stdout)["goals"], "behavior 1: the replayed scan synthesized a slate"
    assert (state / "slate.json").is_file(), "behavior 1: the slate lands at <state_dir>/slate.json"
    assert out.read_bytes() == canon.read_bytes(), "behavior 2: OUT is byte-identical to the replayed F"
    assert LIVE_TODO not in (state / "slate.json").read_text() + out.read_text()
    recorded_root = json.loads(canon.read_text())["workspace_root"]
    assert recorded_root == str(env.src) != str(env.ws)
    assert json.loads(out.read_text())["workspace_root"] == recorded_root, "behavior 3"

    explicit = env.root / "explicit.json"
    code, _out, _err, _state = env.scan(FLAG, str(canon), "--out", str(explicit))
    assert code == 0 and explicit.is_file(), "behavior 1: --out still names the slate target"

    rootless = dict(json.loads(canon.read_text()), workspace_root=None)
    out_fallback = env.root / "fallback.json"
    code, _out, _err, _state = env.scan(FLAG, str(env.write("rootless.json", rootless)), "--snapshot", str(out_fallback))
    assert code == 0 and json.loads(out_fallback.read_text())["workspace_root"] == str(env.ws), (
        "behavior 3: a non-string root falls back to --workspace"
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["scan", FLAG, str(canon), "--provider", "scripted"])
    assert excinfo.value.code == 2, "behavior 1: --workspace stays required"
    assert "--workspace" in env.capsys.readouterr().err


def _b4_exclude_path_narrows_a_replay(env: _Env) -> None:
    def entry(summary: str, path: str | None) -> dict[str, object]:
        return {"source": "todos", "kind": "todo", "summary": summary, "detail": "", "path": path, "weight": 0.5}

    signals = [entry("a", "keep/a.py:1"), entry("b", "vendor/b.py:2"), entry("c", None),
               entry("d", "src/d.py"), entry("e", "vendor/deep/e.py:9")]
    doc = env.write("b4.json", {"workspace_root": str(env.src), "signals": signals})
    for globs in (["vendor"], ["*"], ["vendor", "src/*"]):
        out = env.root / f"b4-{len(globs)}-{globs[0].strip('*') or 'star'}.json"
        argv = [FLAG, str(doc), "--snapshot", str(out)]
        for glob in globs:
            argv += ["--exclude-path", glob]
        code, _out, err, _state = env.scan(*argv)
        assert code == 0, err
        kept = json.loads(out.read_text())["signals"]
        assert kept == [s for s in signals if not _path_excluded(s["path"], globs)], globs
        assert any(s["path"] is None for s in kept), f"behavior 4: a path-less entry survives {globs}"
    assert [s["summary"] for s in kept] == ["a", "c"], "order is preserved"


def _b5_collector_conflict_is_refused_first(env: _Env, canon: Path) -> None:
    out = env.root / "b5.json"
    missing_script = env.root / "no-such-script.json"
    line = _assert_refused(
        env, env.scan(FLAG, str(canon), "--collector", "todos", "--snapshot", str(out), script=missing_script),
        out, FLAG,
    )
    assert "--collector" in line, line  # decided before create_client (which would fail on the script)
    code, _out, err, _state = env.scan(FLAG, str(canon), "--collector", "todos", workspace=env.root / "nope")
    assert code == 2 and err.splitlines() == [f"error: workspace not found: {env.root / 'nope'}"], err


def _b6_b7_malformed_documents_fail_closed(env: _Env, canon: Path) -> None:
    good = json.loads(canon.read_text())
    (env.root / "bad_utf8.json").write_bytes(b"\xff\xfe")
    (env.root / "bad_json.json").write_text("not json")
    bad_weight = dict(good, signals=[dict(good["signals"][0], weight="not-a-number")])
    cases: list[tuple[Path, str]] = [
        (env.root / "absent.json", "not found or not a regular file: {f}"),
        (env.root / "bad_utf8.json", "is not valid UTF-8 text: {f}: "),
        (env.root / "bad_json.json", "is not valid JSON: {f}: "),
        (env.write("list.json", []), "must contain one JSON object: {f}: got list"),
        (env.write("nosig.json", {"workspace_root": "x"}), "has no 'signals' array: {f}: "),
        (env.write("notobj.json", {"signals": [1]}), "entry signals[0] is not a JSON object: {f}"),
        (env.write("partial.json", {"signals": [{"source": "s", "kind": "k"}]}),
         "entry signals[0] is missing summary, detail, path, weight: {f}"),
        (env.write("weight.json", bad_weight),
         "entry signals[0] has a value the signal schema rejects: {f}: weight"),
    ]
    missing_script = env.root / "no-such-script.json"
    for doc, wording in cases:
        out = env.root / f"out-{doc.stem}.json"
        line = _assert_refused(env, env.scan(FLAG, str(doc), "--snapshot", str(out), script=missing_script), out, "")
        expected = "error: from-snapshot file " + wording.format(f=doc)
        assert line.startswith(expected) if wording.endswith(": ") else line == expected, (expected, line)
        assert "pydantic" not in line and "input_value" not in line, f"behavior 7: no vendor dump: {line}"

    list_doc = str(env.root / "list.json")
    for argv, label in ((["signals", "--workspace", str(env.ws), "--baseline", list_doc], "baseline"),
                        (["verify", "--slate", str(env.root / "explicit.json"), "--snapshot", list_doc], "snapshot")):
        env.capsys.readouterr()
        assert main(argv) == 2
        assert env.capsys.readouterr().err == f"error: {label} file must contain one JSON object: {list_doc}: got list\n"


def _b8_extra_keys_are_dropped(env: _Env, canon: Path) -> None:
    widened = json.loads(canon.read_text())
    widened["signals"][0].update(timestamp="2026-01-01T00:00:00Z", future_field=1)
    out = env.root / "b8.json"
    code, _out, err, _state = env.scan(FLAG, str(env.write("widened.json", widened)), "--snapshot", str(out))
    assert code == 0, err
    assert tuple(json.loads(out.read_text())["signals"][0]) == IDENTITY_KEYS
    assert out.read_bytes() == canon.read_bytes(), "behavior 8: the wire contract does not widen"


def _b9_flag_is_scan_only_and_documented_honestly() -> None:
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    owners = sorted(v for v, p in sub.choices.items() if any(FLAG in a.option_strings for a in p._actions))
    assert owners == ["scan"], owners
    help_text = sub.choices["scan"].format_help()

    spec = SPEC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(spec) if line.lstrip().startswith("- `pla scan "))
    stop = next(i for i in range(start + 1, len(spec)) if spec[i].lstrip().startswith("- `pla "))
    spec_bullet = "\n".join(spec[start:stop])

    readme = README.read_text(encoding="utf-8").splitlines()
    marker = next(i for i, line in enumerate(readme) if "PORTFOLIO INTRO" in line)
    rows = [i for i, line in enumerate(readme) if line.startswith("| `scan`")]
    assert len(rows) == 1 and rows[0] > marker, "the README row lives BELOW the human-owned intro"

    for name, text in (("scan --help", help_text), ("SPEC 4.5 scan bullet", spec_bullet), ("README scan row", readme[rows[0]])):
        assert FLAG in text and "replay" in text.lower(), name
        assert [w for w in FORBIDDEN if w in text.lower()] == [], f"{name} over-claims"


def _funding_and_self_shape() -> None:
    tests_dir = REPO / "tests"
    for module, name in RETIRED_TESTS:
        assert f"def {name}(" not in (tests_dir / module).read_text(encoding="utf-8"), f"{module}::{name} is back"
    for module, name in KEEPERS:
        assert f"def {name}(" in (tests_dir / module).read_text(encoding="utf-8"), f"keeper {module}::{name} is gone"
    own = Path(__file__).read_text(encoding="utf-8")
    assert own.count("\ndef test_") == 1, "this module stays ONE collected item"


def test_scan_from_snapshot_replays_a_recorded_perception_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = _Env(tmp_path, capsys)
    canon = env.record()
    _b1_b2_b3_replay_replaces_collection(env, canon)
    _b4_exclude_path_narrows_a_replay(env)
    _b5_collector_conflict_is_refused_first(env, canon)
    _b6_b7_malformed_documents_fail_closed(env, canon)
    _b8_extra_keys_are_dropped(env, canon)
    _b9_flag_is_scan_only_and_documented_honestly()
    _funding_and_self_shape()
