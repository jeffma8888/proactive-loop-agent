"""Tests for the LLM boundary's JSON extraction (``parse_json_block``).

The parser is the single point where free-form model text becomes structured
data for both the synthesizer (a JSON array of goals) and the goal loop (plan /
check objects). It must be robust to the small formatting sins a live model
commits: code fences, prose around the JSON, and -- the case a live run
actually hit -- a stray brace or sentence appended AFTER an otherwise-valid
value. Anything it cannot parse must raise ``ValueError`` so callers can degrade
(the synthesizer skips, the loop feeds the error back to the model).
"""

from __future__ import annotations

import pytest

from proactive_loop.llm.client import parse_json_block


def test_plain_object() -> None:
    assert parse_json_block('{"done": true, "reason": "ok"}') == {"done": True, "reason": "ok"}


def test_plain_array_is_decoded_as_array_not_first_object() -> None:
    """A top-level array must decode whole -- not just its first object.

    The earliest opener wins, so ``[`` at index 0 beats the inner ``{``.
    """
    out = parse_json_block('[{"a": 1}, {"b": 2}]')
    assert out == [{"a": 1}, {"b": 2}]


def test_fenced_json_block() -> None:
    text = 'Here is the plan:\n```json\n{"tool": "write_file"}\n```\nthanks!'
    assert parse_json_block(text) == {"tool": "write_file"}


def test_leading_prose_before_object() -> None:
    text = 'Sure, here you go: {"done": false, "reason": "keep going"}'
    assert parse_json_block(text) == {"done": False, "reason": "keep going"}


def test_trailing_stray_brace_is_ignored() -> None:
    """The exact live-run failure: a valid object with an extra ``}`` appended."""
    text = '{"thought": "x", "action": {"tool": "write_file", "args": {"path": "a"}}} }'
    out = parse_json_block(text)
    assert out["action"]["tool"] == "write_file"
    assert out["action"]["args"]["path"] == "a"


def test_trailing_junk_sentence_is_ignored() -> None:
    text = '{"done": true, "reason": "finished"}\nThat completes the task.'
    assert parse_json_block(text) == {"done": True, "reason": "finished"}


def test_braces_inside_string_values_are_preserved() -> None:
    """Markdown/code content with its own braces must not confuse the parser."""
    content = "# Title\n\n```python\ndef f(): return {}\n```\n"
    text = '{"action": {"tool": "write_file", "args": {"content": %s}}}' % (
        __import__("json").dumps(content)
    )
    out = parse_json_block(text)
    assert out["action"]["args"]["content"] == content


def test_multiple_extra_braces_ignored() -> None:
    text = '{"done": true, "reason": "done"}}}}'
    assert parse_json_block(text) == {"done": True, "reason": "done"}


def test_whole_string_fallback() -> None:
    """No prose, no fence, just clean JSON with surrounding whitespace."""
    assert parse_json_block('   \n  [1, 2, 3]  \n ') == [1, 2, 3]


@pytest.mark.parametrize("bad", ["", "not json at all", "{unbalanced", "just words {"])
def test_unparseable_raises_valueerror(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_json_block(bad)
