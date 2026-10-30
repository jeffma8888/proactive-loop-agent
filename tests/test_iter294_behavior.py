"""Black-box behavior tests for factory iteration 543 (ROADMAP #334).

broken_link's ``_scan_link_refs`` builds a line's inline-code-span mask lazily: only on a
line that holds at least one ``_LINK_RE`` match, at most once per such line, with the refs
unchanged versus an eager per-line mask. ONE pytest item (budget: binding_headroom=7).
Offline and deterministic: pure in-process calls on an inline Markdown fixture.
"""

from __future__ import annotations

import inspect

import pytest

from proactive_loop.collectors import broken_link as bl

DOC = inspect.cleandoc(
    """
    # Title

    plain prose with no link at all
    another plain line, `code` but no link
    see [`SPEC.md`](SPEC.md) and [two](docs/two.md) on one line
    a sample `[x](inside-code.md)` stays silent
    unclosed ``run [y](after-unclosed.md)
    <https://example.com> and [web](https://example.com/a.md)

    ```
    [fenced](fenced.md)
    ```
    last [z](<angle dir/z.md>) line
    """
)


def _eager(text: str) -> tuple[object, ...]:
    """The pre-change rule: mask every non-fenced line, filter matches by destination."""
    lines = text.splitlines()
    fence = bl._fence_mask(lines)
    refs = []
    for idx, line in enumerate(lines):
        if fence[idx]:
            continue
        ranges = bl._code_span_ranges(line)
        for m in bl._LINK_RE.finditer(line):
            angle = m.group("angle")
            s, e = m.span("angle" if angle is not None else "target")
            if any(s < end and start < e for start, end in ranges):
                continue
            target = angle if angle is not None else m.group("target")
            if not bl._is_filesystem_target(target):
                continue
            cands = bl._target_paths(target)
            if not cands[0]:
                continue
            refs.append((idx + 1, m.start(), target, cands, line.strip()[:200]))
    return tuple(refs)


def test_b1_code_span_mask_is_lazy_and_refs_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _eager(DOC)
    assert expected, "fixture must yield at least one ref"

    seen: list[str] = []
    real = bl._code_span_ranges

    def spy(line: str) -> list[tuple[int, int]]:
        seen.append(line)
        return real(line)

    monkeypatch.setattr(bl, "_code_span_ranges", spy)
    got = bl._scan_link_refs(DOC)
    assert got == expected

    # Spot-check the semantics the equality must preserve, independent of _eager.
    targets = [ref[2] for ref in got]
    assert "SPEC.md" in targets  # backticked label, plain destination: still reported
    assert "docs/two.md" in targets  # second link on the same line
    assert "inside-code.md" not in targets  # destination inside a code span: silent
    assert "fenced.md" not in targets  # fenced block: silent
    assert "https://example.com/a.md" not in targets  # URL, not a filesystem target

    lines = DOC.splitlines()
    fence = bl._fence_mask(lines)
    link_lines = [
        ln for i, ln in enumerate(lines) if not fence[i] and bl._LINK_RE.search(ln)
    ]
    # Called once per link-bearing non-fenced line, never on a link-less or fenced line.
    assert seen == link_lines, seen
    assert len(set(seen)) == len(seen)
