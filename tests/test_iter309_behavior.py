"""Factory iter 561 (ROADMAP #349): a UTF-8 BOM no longer voids the first ``run --decline`` title.

``--decline FILE`` is decoded as ``utf-8-sig``, so a leading BOM (Notepad and similar editors
write one) is stripped. Before the fix the first line loaded as ``'\\ufeff<title>'`` and never
matched, so the very goal the user refused was auto-dispatched -- the decline list failed OPEN.

Black-box: every behaviour drives ``cli.main([...])`` in-process and asserts observable
stdout/stderr, exit codes and the files under ``--state-dir``; B3 also calls the public-ish
loader ``_load_declined_titles`` named by the spec. ONE collected item (``make readme-headroom``
reads binding_headroom=6), paid for by folding a 2-item parametrize elsewhere. Offline and
deterministic: scripted provider, no subprocess, and the fixture workspace is a private
``tmp_path`` copy whose every mtime is stamped to one known age (fresh-clone safe).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.cli import _load_declined_titles, _normalize_title, main

REPO: Final = Path(__file__).resolve().parents[1]
FIXTURE: Final = REPO / "examples" / "fixture_workspace"
SCRIPT: Final = REPO / "examples" / "scripted_responses.json"
FLAG: Final = "--decline"
BOM: Final = b"\xef\xbb\xbf"
DECLINED: Final = "skipped (declined): "
ERR_MISSING: Final = "error: decline file not found or not a regular file: "
ERR_PREFIX: Final = "error: decline file "
STAMP_AGE_SEC: Final = 6 * 60 * 60


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)


def _workspace(root: Path) -> Path:
    dest = root / "ws"
    shutil.copytree(FIXTURE, dest)
    stamp = time.time() - STAMP_AGE_SEC
    for path in [dest, *dest.rglob("*")]:
        os.utime(path, (stamp, stamp))
    return dest


def _run(capsys: pytest.CaptureFixture[str], ws: Path, state: Path, *extra: str) -> tuple[int, str, str]:
    capsys.readouterr()
    rc = main(
        [
            "run",
            "--workspace",
            str(ws),
            "--provider",
            "scripted",
            "--scripted-responses",
            str(SCRIPT),
            "--state-dir",
            str(state),
            *extra,
        ]
    )
    out = capsys.readouterr()
    return rc, out.out, out.err


def _run_dirs(state: Path) -> list[Path]:
    return sorted(p for p in state.glob("run-*") if p.is_dir()) if state.exists() else []


def _lines(text: str, prefix: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith(prefix)]


def _top_title(doc: dict[str, object]) -> str | None:
    top = doc["top_goal"]
    if isinstance(top, dict):
        title = top.get("title")
        return title if isinstance(title, str) else None
    return top if isinstance(top, str) or top is None else str(top)


def _checkpoint_goals(state: Path) -> list[str]:
    """Every file under every run dir, flattened, so a goal title anywhere in a checkpoint is seen."""
    texts: list[str] = []
    for run_dir in _run_dirs(state):
        for f in sorted(run_dir.rglob("*")):
            if f.is_file():
                texts.append(f.read_text(encoding="utf-8", errors="replace"))
    return texts


def test_iter559_decline_file_with_bom_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    ws = _workspace(tmp_path)

    # TOP: the top auto-dispatchable goal a plain `run --dry-run --json` reports.
    rc, out, err = _run(capsys, ws, tmp_path / "s0", "--dry-run", "--json")
    assert rc == 0, err
    top = _top_title(json.loads(out))
    assert isinstance(top, str) and top.strip(), out

    bom_first = tmp_path / "bom-first.txt"
    bom_first.write_bytes(BOM + top.encode("utf-8") + b"\n")
    bom_comment = tmp_path / "bom-comment.txt"
    bom_comment.write_bytes(BOM + b"# my declines\n" + top.encode("utf-8") + b"\n")
    plain = tmp_path / "plain.txt"
    plain.write_bytes(top.encode("utf-8") + b"\n")

    # B1: BOM'd first line declines TOP under --dry-run; --json does not choose TOP.
    rc, out, err = _run(capsys, ws, tmp_path / "s1", FLAG, str(bom_first), "--dry-run")
    assert rc == 0, err
    assert _lines(out, DECLINED) == [f"{DECLINED}{top}"], out
    assert f"auto-dispatching top goal: {top}" not in out, out
    rc, out, err = _run(capsys, ws, tmp_path / "s1j", FLAG, str(bom_first), "--dry-run", "--json")
    assert rc == 0, err
    assert _top_title(json.loads(out)) != top, out

    # B2: a real (non-dry) run with the same BOM'd file dispatches no run for TOP.
    state = tmp_path / "s2"
    rc, out, err = _run(capsys, ws, state, FLAG, str(bom_first))
    assert rc == 0, err
    assert _lines(out, DECLINED) == [f"{DECLINED}{top}"], out
    assert not any(top in text for text in _checkpoint_goals(state)), "a declined TOP must not get a run dir"

    # B3: a BOM'd comment first line is still a comment; TOP is declined, no \ufeff key.
    rc, out, err = _run(capsys, ws, tmp_path / "s3", FLAG, str(bom_comment), "--dry-run")
    assert rc == 0, err
    assert _lines(out, DECLINED) == [f"{DECLINED}{top}"], out
    assert _load_declined_titles(bom_comment) == frozenset({_normalize_title(top)})

    # B4: BOM-less file unchanged; missing path and invalid UTF-8 still exit 2; no key has \ufeff.
    rc, out, err = _run(capsys, ws, tmp_path / "s4", FLAG, str(plain), "--dry-run")
    assert rc == 0, err
    assert _lines(out, DECLINED) == [f"{DECLINED}{top}"], out
    for path in (bom_first, bom_comment, plain):
        keys = _load_declined_titles(path)
        assert keys == frozenset({_normalize_title(top)}), (path.name, keys)
        assert not any("\ufeff" in k for k in keys), (path.name, keys)
    bad_utf8 = tmp_path / "bad.txt"
    bad_utf8.write_bytes(b"\xff\xfe")
    bad_cases = [(tmp_path / "missing.txt", ERR_MISSING), (bad_utf8, ERR_PREFIX)]
    assert len(bad_cases) == 2
    for i, (bad, prefix) in enumerate(bad_cases):
        state = tmp_path / f"s4-bad-{i}"
        rc, out, err = _run(capsys, ws, state, FLAG, str(bad))
        assert rc == 2, (bad.name, rc, out, err)
        err_lines = [ln for ln in err.splitlines() if ln.strip()]
        assert len(err_lines) == 1 and err_lines[0].startswith(prefix), err
        assert "Traceback" not in err and "Traceback" not in out
        assert not (state / "slate.json").exists(), "a usage error must write no slate"
        assert _run_dirs(state) == []
