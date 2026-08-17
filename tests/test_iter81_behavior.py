"""Behavior tests for commit-seq factory iter 81 (state-dir iter-71).

Feature under test: ``NotesCollector`` must ignore ATX Markdown headings that
appear INSIDE fenced code blocks (```` ``` ````/``~~~``) so an unindented ``#``
comment line inside a code fence is no longer misread as a note heading and
emitted as a spurious ``kind="note"`` signal.

ISOLATION: black-box. These tests drive only the public interface
(``NotesCollector().collect(root)`` + the public ``all_collectors()`` /
``ToolRegistry`` / ``VALID_PROVIDERS`` / ``__version__`` registries). No file
under ``src/`` was read; the assertions encode the pm.md Expected Behaviors, not
the implementation.

File naming: the prompt's state-dir iteration is 71, but ``tests/test_iter71_
behavior.py`` already exists (an earlier commit-seq iteration). The repo names
behavior files after the COMMIT SEQUENCE, which for this iteration is factory
iter 81 (pm.md header + ROADMAP row #81); ``test_iter81_behavior.py`` was
confirmed unused before creation.
"""

from __future__ import annotations

from pathlib import Path

from proactive_loop import __version__
from proactive_loop.cli import build_parser
from proactive_loop.collectors import NotesCollector, all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry

# ---------------------------------------------------------------------------
# Black-box helpers -- write a single Markdown notes file under a scanned dir
# (notes|journal|docs) and collect the emitted signals / summaries.
# ---------------------------------------------------------------------------


def _signals(tmp_path: Path, content: str, *, subdir: str = "docs", name: str = "guide.md"):
    """Write *content* to <tmp_path>/<subdir>/<name> and return NotesCollector signals."""
    d = tmp_path / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content, encoding="utf-8")
    return NotesCollector().collect(tmp_path)


def _summaries(tmp_path: Path, content: str, **kw) -> set[str]:
    return {s.summary for s in _signals(tmp_path, content, **kw)}


# ---------------------------------------------------------------------------
# Behavior 1 -- backward-compat: real headings OUTSIDE fences still emit.
# ---------------------------------------------------------------------------


def test_b1_real_headings_outside_fences_still_emit(tmp_path: Path) -> None:
    content = "# Alpha\n\nIntro text.\n\n## Beta\n\nBody.\n"
    signals = _signals(tmp_path, content, subdir="notes", name="a.md")
    summaries = {s.summary for s in signals}
    assert "Alpha" in summaries, f"real top-level heading dropped; got {summaries}"
    assert "Beta" in summaries, f"real sub-heading dropped; got {summaries}"


def test_b1_first_paragraph_detail_unchanged(tmp_path: Path) -> None:
    content = "# Alpha\n\nIntro text.\n\n## Beta\n\nBody.\n"
    signals = _signals(tmp_path, content, subdir="notes", name="a.md")
    alpha = next((s for s in signals if s.summary == "Alpha"), None)
    assert alpha is not None, "expected an 'Alpha' heading signal"
    assert alpha.detail.startswith("Intro text."), (
        f"Alpha first-paragraph detail regressed; got {alpha.detail!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- backtick fence suppresses interior '#' headings (core fix).
# ---------------------------------------------------------------------------


def test_b2_backtick_fence_suppresses_interior_headings(tmp_path: Path) -> None:
    content = (
        "# Real One\n"
        "Intro.\n"
        "\n"
        "```python\n"
        "# not a heading\n"
        "## also not a heading\n"
        "def f():\n"
        "    return 1\n"
        "```\n"
        "\n"
        "## Real Two\n"
        "Body.\n"
    )
    summaries = _summaries(tmp_path, content)
    assert summaries == {"Real One", "Real Two"}, (
        f"expected exactly the two real headings; got {summaries}"
    )
    assert "not a heading" not in summaries
    assert "also not a heading" not in summaries


def test_b2_fenced_heading_does_not_truncate_real_paragraph(tmp_path: Path) -> None:
    """Acceptance: an interior fenced '#' must NOT prematurely truncate the real
    heading's paragraph nor re-surface itself (inner-loop fence-awareness)."""
    content = (
        "# Heading\n"
        "Intro.\n"
        "```\n"
        "# fenced\n"
        "```\n"
        "More.\n"
    )
    summaries = _summaries(tmp_path, content)
    assert summaries == {"Heading"}, (
        f"a fenced '#' inside a real heading's paragraph must be absorbed, not "
        f"emitted as its own heading; got {summaries}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- tilde (~~~) fences honored identically.
# ---------------------------------------------------------------------------


def test_b3_tilde_fence_suppresses_interior_headings(tmp_path: Path) -> None:
    content = (
        "# Real One\n"
        "Intro.\n"
        "\n"
        "~~~python\n"
        "# not a heading\n"
        "## also not a heading\n"
        "def f():\n"
        "    return 1\n"
        "~~~\n"
        "\n"
        "## Real Two\n"
        "Body.\n"
    )
    summaries = _summaries(tmp_path, content)
    assert summaries == {"Real One", "Real Two"}, (
        f"tilde fence must suppress interior headings identically; got {summaries}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- info-string open + bare close bound the block; a heading AFTER
# the close is detected.
# ---------------------------------------------------------------------------


def test_b4_infostring_open_bare_close_then_heading(tmp_path: Path) -> None:
    content = (
        "```python\n"
        "# inside\n"
        "```\n"
        "\n"
        "# After Fence\n"
        "Body.\n"
    )
    summaries = _summaries(tmp_path, content)
    assert "After Fence" in summaries, (
        f"a heading after the closing fence must be detected; got {summaries}"
    )
    assert "inside" not in summaries, (
        f"a '#' between the fence delimiters must be suppressed; got {summaries}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- delimiter char must match to close (mismatched markers inert).
# ---------------------------------------------------------------------------


def test_b5_mismatched_delimiter_does_not_close(tmp_path: Path) -> None:
    content = (
        "```\n"
        "# hidden\n"
        "~~~\n"
        "# still inside\n"
        "```\n"
        "\n"
        "# Reopened\n"
        "Body.\n"
    )
    summaries = _summaries(tmp_path, content)
    assert "Reopened" in summaries, (
        f"after the matching ``` closes, a real heading must emit; got {summaries}"
    )
    assert "hidden" not in summaries
    assert "still inside" not in summaries, (
        f"a ~~~ line must NOT close a ``` fence, so '# still inside' stays "
        f"suppressed; got {summaries}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- only 3+ backticks/tildes at line start open a fence.
# ---------------------------------------------------------------------------


def test_b6_inline_and_short_backticks_do_not_open_fence(tmp_path: Path) -> None:
    content = (
        "Use the `grep` command.\n"
        "``two backticks are not a fence\n"
        "\n"
        "# Real Heading\n"
        "Body.\n"
    )
    summaries = _summaries(tmp_path, content)
    assert "Real Heading" in summaries, (
        f"inline single backticks and a two-backtick line must NOT open a fence, "
        f"so a later '# Real Heading' still emits; got {summaries}"
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- unterminated fence suppresses headings to EOF, never raises.
# ---------------------------------------------------------------------------


def test_b7_unterminated_fence_suppresses_to_eof(tmp_path: Path) -> None:
    content = (
        "# Real Top\n"
        "Intro.\n"
        "\n"
        "```\n"
        "# buried\n"
        "some code\n"
    )
    signals = _signals(tmp_path, content)
    summaries = {s.summary for s in signals}
    assert "Real Top" in summaries, f"the pre-fence heading must emit; got {summaries}"
    assert "buried" not in summaries, (
        f"an open fence runs to EOF, suppressing '# buried'; got {summaries}"
    )


def test_b7_collect_never_raises_and_returns_list(tmp_path: Path) -> None:
    content = "```\n# buried\nno closing fence ever\n"
    # Must return normally (a list), never raise, on an unterminated fence.
    signals = _signals(tmp_path, content)
    assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# Behavior 8 -- no registry change + version frozen (count-lock drift guard).
# ---------------------------------------------------------------------------


def test_b8_collector_registry_count_unchanged(tmp_path: Path) -> None:
    assert len(all_collectors()) == 17, (
        "a fence-awareness fix on NotesCollector must add NO collector; "
        f"expected 17, got {len(all_collectors())}"
    )


def test_b8_tool_registry_count_unchanged() -> None:
    assert len(ToolRegistry.tool_names()) == 14, (
        f"tool registry count must stay 14; got {len(ToolRegistry.tool_names())}"
    )


def test_b8_provider_count_unchanged() -> None:
    assert len(VALID_PROVIDERS) == 7, (
        f"provider count must stay 7; got {len(VALID_PROVIDERS)}"
    )


def test_b8_cli_subcommand_count_unchanged() -> None:
    import argparse

    parser = build_parser()
    subactions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert len(subactions) == 1, "expected exactly one subparsers action"
    assert len(subactions[0].choices) == 16, (
        f"CLI subcommand count must stay 16; got {len(subactions[0].choices)}"
    )


def test_b8_version_frozen() -> None:
    assert __version__ == "0.1.1", (
        f"a behavior-only collector fix must NOT bump the version; got {__version__!r}"
    )
