"""Unit tests for WorkingTreeCollector's INTERNAL pure helpers.

Scope is deliberately narrow: only the two fiddly stdlib parsers
(`_classify_porcelain_line`, `_parse_ahead_count`) that carry the "skip a
malformed line, never crash" contract. The black-box collector behaviors (a
real temp git repo with dirty/untracked/unpushed state) belong to the feature's
behavior suite; this module needs no git and stays fast + deterministic.
"""

from __future__ import annotations

import pytest

from proactive_loop.collectors.working_tree import (
    _classify_porcelain_line,
    _parse_ahead_count,
)


class TestClassifyPorcelainLine:
    @pytest.mark.parametrize(
        "line, expected",
        [
            (" M app.py", ("tracked", "app.py")),      # modified, unstaged
            ("M  app.py", ("tracked", "app.py")),      # modified, staged
            ("MM app.py", ("tracked", "app.py")),      # staged + further modified
            ("A  new.py", ("tracked", "new.py")),      # added (staged)
            ("D  gone.py", ("tracked", "gone.py")),    # deleted (staged)
            (" D gone.py", ("tracked", "gone.py")),    # deleted (unstaged)
            ("?? fresh.py", ("untracked", "fresh.py")),
            ("R  old.py -> new.py", ("tracked", "old.py -> new.py")),  # rename kept raw
        ],
    )
    def test_valid_lines(self, line: str, expected: tuple[str, str]) -> None:
        assert _classify_porcelain_line(line) == expected

    @pytest.mark.parametrize("line", ["", " ", "??", " M ", "!! ignored.py", "x"])
    def test_skipped_lines_return_none(self, line: str) -> None:
        """Blank, too-short, path-less, and ignored (!!) lines are skipped."""
        assert _classify_porcelain_line(line) is None

    def test_untracked_only_for_double_question(self) -> None:
        assert _classify_porcelain_line("?? a")[0] == "untracked"
        assert _classify_porcelain_line(" M a")[0] == "tracked"


class TestParseAheadCount:
    @pytest.mark.parametrize(
        "stdout, expected",
        [
            ("3\n", 3),
            ("0\n", 0),
            ("  12  ", 12),
            ("", None),
            ("   ", None),
            ("not-a-number", None),
            ("3\n4", None),  # unexpected multi-token output degrades to None
        ],
    )
    def test_parse(self, stdout: str, expected: int | None) -> None:
        assert _parse_ahead_count(stdout) == expected
