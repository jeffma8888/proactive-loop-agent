"""Black-box behavior tests for factory iteration 542 (ROADMAP #333).

``pla watch --out-dir DIR`` on a directory that already holds a stream CONTINUES
the tick numbering after the highest existing ``slate-NNN.json`` instead of
restarting at ``slate-001.json``. Before this, a restarted watcher overwrote
tick 1 and left the previous run's last tick as the "newest" file, so
``diff --dir`` inverted old/new and ``trend --dir`` read a mixed history.
Offline and deterministic: in-process ``main()`` with the scripted provider.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"


def _watch(out_dir: Path, scans: int, capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    argv = [
        "watch", "--workspace", str(FIXTURE), "--provider", "scripted",
        "--scripted-responses", str(SCRIPT), "--interval", "0",
        "--max-scans", str(scans), "--out-dir", str(out_dir),
    ]  # fmt: skip
    assert main(argv) == 0
    return capsys.readouterr().out


def _stream(out_dir: Path) -> list[str]:
    return sorted(p.name for p in out_dir.iterdir() if p.name.startswith("slate-"))


def test_b1_restarted_watch_continues_the_stream_instead_of_clobbering_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("PLA_PROVIDER", "PLA_SCRIPTED_RESPONSES"):
        monkeypatch.delenv(var, raising=False)

    # A fresh directory still starts at slate-001 (existing contract unchanged).
    stream = tmp_path / "stream"
    _watch(stream, 2, capsys)
    assert _stream(stream) == ["slate-001.json", "slate-002.json"]
    first = {name: (stream / name).read_bytes() for name in _stream(stream)}

    # A restart appends tick 003; ticks 001/002 stay byte-identical.
    out = _watch(stream, 1, capsys)
    assert out.count("=== scan ") == 1, "one tick in the restarted run"
    assert _stream(stream) == ["slate-001.json", "slate-002.json", "slate-003.json"]
    for name, data in first.items():
        assert (stream / name).read_bytes() == data, f"{name} was overwritten"
    assert "=== scan 1 ===" in out, "the per-process scan header still counts from 1"
    assert f"slate written: {stream / 'slate-003.json'}" in out

    # diff --dir now binds the restart's tick as --new.
    capsys.readouterr()
    assert main(["diff", "--dir", str(stream), "--json"]) == 0
    via_dir = capsys.readouterr().out
    old, new = stream / "slate-002.json", stream / "slate-003.json"
    assert main(["diff", "--old", str(old), "--new", str(new), "--json"]) == 0
    assert capsys.readouterr().out == via_dir

    # Gaps and non-stream entries: continue after the highest PARSED index of a
    # regular stream FILE; `slate.json`, notes and a matching-named DIRECTORY are ignored.
    gapped = tmp_path / "gapped"
    gapped.mkdir()
    (gapped / "slate-001.json").write_bytes(first["slate-001.json"])
    (gapped / "slate-007.json").write_bytes(first["slate-002.json"])
    (gapped / "slate.json").write_text("{}")
    (gapped / "notes.txt").write_text("x")
    (gapped / "slate-050.json").mkdir()
    out = _watch(gapped, 1, capsys)
    assert (gapped / "slate-008.json").is_file()
    assert f"slate written: {gapped / 'slate-008.json'}" in out
    assert (gapped / "slate-001.json").read_bytes() == first["slate-001.json"]
    assert not (gapped / "slate-002.json").exists(), "the gap must not be filled"
    assert (gapped / "slate-050.json").is_dir(), "the directory entry is left alone"

    # EB6: the --out-dir help documents the continuation (whitespace-normalised
    # because argparse wraps to the terminal width).
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["watch", "--help"])
    assert exc.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    clause = "An existing stream in DIR is continued after its highest index."
    assert clause in help_text, "watch --out-dir help lacks the continuation clause"
