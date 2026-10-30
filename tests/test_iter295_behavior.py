"""Black-box behavior tests for factory iteration 545 (ROADMAP #335; re-land of 544).

The README's ``watch --out-dir`` section documents that a restarted watch
CONTINUES an existing slate stream (iter 542's behaviour) and no longer claims
"two identical runs produce identical filenames", which became false for a
second run into the same DIR. ONE test item (the suite-size gauge has no spare
items); the README's own worked example is executed so the prose is proven
true, not merely present. Offline and deterministic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proactive_loop import cli
from proactive_loop.cli import main

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
ROADMAP = REPO / "ROADMAP.md"
ROW_335 = "- #335 README: a restarted `watch --out-dir` continues its stream (foundry iter 327)"
FIXTURE = REPO / "examples" / "fixture_workspace"
SCRIPT = REPO / "examples" / "scripted_responses.json"
STALE = "two identical runs produce identical filenames"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _watch(out_dir: Path, scans: int, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    argv = [
        "watch", "--workspace", str(FIXTURE), "--provider", "scripted",
        "--scripted-responses", str(SCRIPT), "--interval", "0",
        "--max-scans", str(scans), "--out-dir", str(out_dir),
    ]  # fmt: skip
    assert main(argv) == 0


def test_b1_readme_documents_watch_stream_continuation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    readme = _flat(README.read_text(encoding="utf-8"))
    # B1: the stale claim is gone from README.
    assert STALE not in readme, f"README still claims {STALE!r}"
    # B5: _cmd_watch's docstring drops the stale claim and names continuation.
    doc = _flat(cli._cmd_watch.__doc__ or "")
    assert "two identical runs produce the same names" not in doc
    assert "continues after its highest index" in doc
    # B2: the --out-dir paragraph states continuation with the worked example.
    para = readme[readme.index("`--out-dir DIR` makes the monitor the *producer*") :]
    para = para[: para.index("Retention stays yours")]
    for phrase in (
        "A restarted watch **continues** an existing stream",
        "numbering resumes after the highest tick index already in `DIR`",
        "write `slate-003.json` and `slate-004.json`",
        "no earlier tick is ever overwritten",
    ):
        assert phrase in para, f"--out-dir paragraph lacks {phrase!r}"
    # B3: exactly one CLI-table watch row, and it names continuation.
    rows = [ln for ln in README.read_text(encoding="utf-8").splitlines() if ln.startswith("| `watch`")]
    assert len(rows) == 1, rows
    assert "continues an existing stream after its highest index" in rows[0]
    assert "--out-dir" in rows[0]
    # B4: the help text agrees (it is the surface iter 542 already updated).
    capsys.readouterr()
    with pytest.raises(SystemExit) as ei:
        main(["watch", "--help"])
    assert ei.value.code == 0
    assert "continued after its highest index" in _flat(capsys.readouterr().out)
    # B6: the README's worked example is TRUE when executed.
    for var in ("PLA_PROVIDER", "PLA_SCRIPTED_RESPONSES"):
        monkeypatch.delenv(var, raising=False)
    stream = tmp_path / "stream"
    _watch(stream, 2, capsys)
    before = {p.name: p.read_bytes() for p in stream.iterdir()}
    assert sorted(before) == ["slate-001.json", "slate-002.json"]
    _watch(stream, 2, capsys)
    names = sorted(p.name for p in stream.iterdir())
    assert names == ["slate-001.json", "slate-002.json", "slate-003.json", "slate-004.json"]
    for name, data in before.items():
        assert (stream / name).read_bytes() == data, f"{name} was overwritten"
    # B7: ROADMAP gains exactly one #335 ledger row.
    roadmap = ROADMAP.read_text(encoding="utf-8")
    hits = [ln for ln in roadmap.splitlines() if ln.startswith("- #335 ")]
    assert hits == [ROW_335], hits
