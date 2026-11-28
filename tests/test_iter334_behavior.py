"""Black-box oracle for foundry iter 598 (factory iter 334): the README "Shared flags"
paragraph tells the truth about argparse -- ``--provider``, ``--scripted-responses`` and
``--state-dir`` are accepted by EVERY verb and go AFTER it, while ``--version`` is the
only top-level flag. A live ``build_parser()`` census guards the prose from drifting.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``), ``README.md``
and the conventions under ``tests/`` (the README x parser census shape mirrors
test_iter329). The paragraph is located by its ``Shared flags:`` content anchor, never by
line number; no sha pin, no wall-clock bound, no network.

The module collects ONE item, ``test_readme_shared_flags_go_after_the_verb``, which
clears every ``PLA_*`` env var and asserts ``iter598_shared_flags_census``'s returned
check count (until factory iter 602 it was hosted, uncollected, in test_iter317 under
the 6-item binding wall).

Spec ambiguity noted: behaviour 2 asks the paragraph to say the flags are settable via
``PLA_*`` environment variables; that is asserted as prose (the ``PLA_*`` token), not by
driving each env var, because the env mapping is not part of this docs-only change.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import pytest

from proactive_loop import cli

REPO = Path(__file__).resolve().parents[1]
ANCHOR = "Shared flags:"
MARKER = "PORTFOLIO INTRO"
TOP_LEVEL_LEAD = "The only top-level flag is"
SHARED_EXPECTED = frozenset({"--provider", "--scripted-responses", "--state-dir"})
_FLAG = re.compile(r"`(--[a-z][a-z0-9-]*)`")


def _readme() -> str:
    return (REPO / "README.md").read_text(encoding="utf-8")


def shared_flags_paragraph(text: str) -> str:
    """Return the paragraph whose first line starts with ANCHOR; fail loudly if absent."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(ANCHOR)]
    assert len(starts) == 1, f"expected exactly one line starting {ANCHOR!r}, got {len(starts)}"
    out: list[str] = []
    for line in lines[starts[0] :]:
        if not line.strip():
            break
        out.append(line)
    return " ".join(out)


def classify_flags(paragraph: str) -> tuple[list[str], list[str]]:
    """Split the paragraph's standalone backticked ``--flag`` tokens into
    (per-verb, top-level): everything before TOP_LEVEL_LEAD is per-verb."""
    assert TOP_LEVEL_LEAD in paragraph, f"paragraph lacks {TOP_LEVEL_LEAD!r}"
    head, tail = paragraph.split(TOP_LEVEL_LEAD, 1)
    per_verb = _FLAG.findall(head)
    top = _FLAG.findall(tail)
    return per_verb, top


def _top_and_sub_options(
    parser: argparse.ArgumentParser,
) -> tuple[set[str], dict[str, set[str]]]:
    top = {o for a in parser._actions for o in a.option_strings}
    subs: dict[str, set[str]] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                subs[name] = {o for a in sub._actions for o in a.option_strings}
    return top, subs


def _census_violations(
    per_verb: list[str], top_flags: list[str], parser: argparse.ArgumentParser
) -> list[str]:
    top, subs = _top_and_sub_options(parser)
    bad: list[str] = []
    for flag in per_verb:
        if flag in top:
            bad.append(f"{flag} is top-level but documented as per-verb")
        for verb, opts in sorted(subs.items()):
            if flag not in opts:
                bad.append(f"{flag} missing from verb {verb}")
    for flag in top_flags:
        if flag not in top:
            bad.append(f"{flag} documented as top-level but absent from build_parser()")
    return bad


def iter598_shared_flags_census(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, root: Path
) -> int:
    text = _readme()
    marker_at = text.find(MARKER)
    assert marker_at > 0, "human-owned README marker not found"
    checks = 0

    # B1: the false "Global flags" claim is gone everywhere.
    assert "Global flags" not in text
    checks += 1

    # B2: the paragraph sits BELOW the marker, names the three shared flags as
    # after-the-verb flags, and mentions the PLA_* env mapping.
    assert text.find(ANCHOR) > marker_at
    para = shared_flags_paragraph(text)
    per_verb, top_flags = classify_flags(para)
    assert set(per_verb) == SHARED_EXPECTED, per_verb
    assert "every verb" in para and "AFTER" in para
    assert "PLA_*" in para
    checks += 1

    # B3: --version is the only top-level flag, and the version sentence survives.
    assert top_flags == ["--version"], top_flags
    assert "pla --version" in para and "proactive_loop.__version__" in para
    checks += 1

    # B4 + B5: live census of both parser sides; the real parser has 17 verbs.
    parser = cli.build_parser()
    top, subs = _top_and_sub_options(parser)
    assert len(subs) >= 17, sorted(subs)
    assert top >= {"--version"}
    assert _census_violations(per_verb, top_flags, parser) == []
    checks += 1

    # B6: non-vacuous -- >= 3 per-verb flags checked, a missing anchor fails loudly,
    # and a drifted paragraph is caught by the census.
    assert len(per_verb) >= 3
    with pytest.raises(AssertionError):
        shared_flags_paragraph(text.replace(ANCHOR, "Global flags:"))
    drifted = classify_flags(
        "Shared flags: `--provider`, `--version` are accepted by every verb. "
        "The only top-level flag is `--state-dir`."
    )
    found = _census_violations(drifted[0], drifted[1], parser)
    assert any(v.startswith("--version is top-level") for v in found), found
    assert any(v.startswith("--state-dir documented as top-level") for v in found), found
    checks += 1

    # B7: the pasteable example is real -- after the verb works, before it exits 2.
    for key in ("PLA_PROVIDER", "PLA_SCRIPTED_RESPONSES", "PLA_STATE_DIR"):
        monkeypatch.delenv(key, raising=False)
    root.mkdir(parents=True, exist_ok=True)
    state = root / ".pla_runs"
    capsys.readouterr()
    assert cli.main(["runs", "--provider", "scripted", "--state-dir", str(state)]) == 0
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        cli.main(["--provider", "scripted", "runs"])
    assert exc.value.code == 2
    assert "invalid choice: 'scripted'" in capsys.readouterr().err
    checks += 1

    # B8 (persistable half): the human-owned intro keeps its heading and carries none
    # of the reference-section paragraph.
    intro = text[:marker_at]
    assert "### What this project demonstrates" in intro
    assert ANCHOR not in intro
    checks += 1

    return checks


def test_readme_shared_flags_go_after_the_verb(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Own collected item (no longer hosted in test_iter317), so a regression is reported
    under THIS behavior's name and cannot hide the other harnesses."""
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    assert iter598_shared_flags_census(capsys, monkeypatch, tmp_path / "h") == 7
