"""Unit tests for the ``scan --format markdown`` INTERNAL cell sanitizer.

Scope is deliberately narrow (mirroring ``test_iter11_helpers.py``): only
``_md_cell``, the one fiddly pure helper that carries the "a goal title can
never break the GFM table layout" contract -- collapse ANY whitespace run
(incl. newlines/tabs) to a single space, then escape a literal ``|`` to ``\\|``
so the only unescaped delimiters on a row are the ones the renderer emits. The
black-box ``scan --format {table,json,markdown}`` behaviors (full CLI stdout,
ranked order, live gate decisions, empty-slate fallbacks, invalid-format
exit-2) belong to the feature's behavior suite; this module touches no disk and
stays fast + deterministic.
"""

from __future__ import annotations

import pytest

from proactive_loop.cli import _md_cell


class TestMdCell:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("plain title", "plain title"),           # unchanged
            ("a | b", r"a \| b"),                      # single pipe escaped
            ("a | b | c", r"a \| b \| c"),             # every pipe escaped
            ("line1\nline2", "line1 line2"),           # newline -> single space
            ("tab\there", "tab here"),                 # tab -> single space
            ("lots    of   space", "lots of space"),   # whitespace run collapsed
            ("  padded  ", "padded"),                  # leading/trailing stripped
            ("mix |\n  x", r"mix \| x"),               # pipe + newline + run together
            ("", ""),                                  # empty stays empty
        ],
    )
    def test_sanitizes(self, raw: str, expected: str) -> None:
        assert _md_cell(raw) == expected

    def test_output_is_single_physical_line(self) -> None:
        # No matter what whitespace went in, the result is exactly one line.
        assert "\n" not in _md_cell("a\nb\r\nc\td")

    def test_pipe_count_is_only_escaped(self) -> None:
        # A value with N raw pipes yields N escaped pipes and zero *unescaped*
        # ones, so a row's unescaped-delimiter count stays constant.
        out = _md_cell("x | y | z")
        assert out.count(r"\|") == 2
        assert out.replace(r"\|", "").count("|") == 0
