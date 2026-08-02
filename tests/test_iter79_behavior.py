"""Black-box behavior tests for iteration 69 (commit-sequence factory iter 79):
a scoped docs-vs-code INTEGRITY fix. Two stale spelled-out counts in cli.py
FUNCTION docstrings were corrected to their live registry sizes, and each
spelled-out catalog count is pinned to the LIVE count so it cannot silently
rot again on a future verb / tool / collector add:

  - build_parser  docstring: "eleven subcommands"      -> "fourteen subcommands"  (14 live)
  - _cmd_tools    docstring: "the ten registered tools" -> "the fourteen ..."      (14 live)
  - _cmd_collectors docstring: "fifteen registered collectors" (already correct; PINNED)

ISOLATION CONTRACT (honored): these tests are written strictly against this
iteration's public contract -- the spec's "Expected Behaviors" (pm.md),
README.md, ROADMAP.md, and the product's own observable output. They drive ONLY
documented public surfaces: the function docstrings via
proactive_loop.cli.{build_parser,_cmd_tools,_cmd_collectors}.__doc__; the LIVE
registries (build_parser() subparser choices / ToolRegistry.tool_names() /
all_collectors()); the CLI via proactive_loop.cli.main(argv) (observable
stdout / stderr / exit code); and proactive_loop.__version__. NO file under
src/ was read, NO engineer or reviewer notes were consulted, and NO git diff was
inspected. Every expected count-WORD is DERIVED from the live registry size (a
1..20 int->word map), never hardcoded, so the guard catches a future
capability-add that forgets to bump the docstring. All tests are fully offline:
zero network, zero LLM, no filesystem writes, no subprocess.

SPEC-WORDING NOTE (Behavior 1, reported as PM feedback): pm.md Behavior 1
literally names build_parser().__doc__ (WITH the call), but build_parser()
returns an argparse.ArgumentParser INSTANCE whose .__doc__ is the argparse CLASS
docstring ("Object for parsing command line strings into Python objects."), NOT
the function docstring the edit touches. Behavior 3/4 use the parens-less
_cmd_tools.__doc__ form, so the clear intent is the FUNCTION docstring
throughout; these tests assert against cli.build_parser.__doc__ (no parens) and
document the trap in test_b01_paren_trap_is_the_class_docstring.
"""

from __future__ import annotations

import argparse
import contextlib
import io

import pytest

from proactive_loop import __version__, cli
from proactive_loop.cli import main
from proactive_loop.collectors import all_collectors
from proactive_loop.loop.tools import ToolRegistry

# --------------------------------------------------------------------------
# int -> English number word, covering >= 1..20 so a growing tree cannot rot
# the guard. Every expected count-word is DERIVED from a live registry size
# via _word(), never hardcoded, so a future verb/tool/collector add that
# forgets to bump the docstring fails these tests.
# --------------------------------------------------------------------------
_NUM_WORD: dict[int, str] = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
}

# The 14 subcommands the CLI must expose (Behavior 6). Encoded here as the
# spec-declared ground truth, NOT imported from a private catalog.
EXPECTED_SUBCOMMANDS = [
    "scan", "dispatch", "run", "resume", "runs", "explain", "trace",
    "signals", "watch", "diff", "policy", "tools", "collectors", "providers",
]


def _word(n: int) -> str:
    assert n in _NUM_WORD, f"extend _NUM_WORD past {n} to keep the drift-guard sound"
    return _NUM_WORD[n]


def _subcommand_count() -> int:
    """Live subcommand count = choices of the single argparse subparsers action."""
    parser = cli.build_parser()
    subparsers = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(subparsers) == 1, (
        f"expected exactly one _SubParsersAction in build_parser(), got {len(subparsers)}"
    )
    return len(subparsers[0].choices)


def _run(argv: list[str]) -> tuple[int | None, int | None, str, str]:
    """Drive main(argv); return (return_value, SystemExit.code, stdout, stderr).

    Either return_value (normal path, e.g. `tools`) or exit_code (SystemExit
    path, e.g. `--help`/`--version`) is populated; the other is None.
    """
    out, err = io.StringIO(), io.StringIO()
    rc: int | None = None
    exit_code: int | None = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as e:  # argparse --help/--version exit here
            exit_code = e.code if isinstance(e.code, int) else 0
    return rc, exit_code, out.getvalue(), err.getvalue()


# ==========================================================================
# Behavior 1 -- build_parser docstring names the LIVE subcommand count as an
# English word (currently "fourteen subcommands").
# ==========================================================================
def test_b01_build_parser_docstring_names_live_subcommand_count():
    n = _subcommand_count()
    doc = cli.build_parser.__doc__ or ""
    phrase = f"{_word(n)} subcommands"
    assert phrase in doc, (
        f"build_parser.__doc__ must name the live subcommand count as "
        f"{phrase!r} (live count = {n}); got docstring:\n{doc}"
    )


def test_b01_live_subcommand_count_is_fourteen():
    # Anchor the current tree: the fix targets exactly 14 subcommands.
    assert _subcommand_count() == 14


def test_b01_paren_trap_is_the_class_docstring():
    # Documents the spec-wording ambiguity: build_parser() returns an
    # argparse.ArgumentParser INSTANCE whose .__doc__ is the argparse CLASS
    # docstring, NOT the function docstring. The edit lives on the function.
    instance_doc = cli.build_parser().__doc__ or ""
    func_doc = cli.build_parser.__doc__ or ""
    assert "fourteen subcommands" not in instance_doc
    assert "fourteen subcommands" in func_doc


# ==========================================================================
# Behavior 2 -- the stale "eleven subcommands" (and, while the live count is
# not 11, the bare word "eleven") is gone from build_parser's docstring;
# no OTHER count-word precedes "subcommands" (drift-safe stale guard).
# ==========================================================================
def test_b02_stale_eleven_subcommands_gone():
    doc = cli.build_parser.__doc__ or ""
    assert "eleven subcommands" not in doc, (
        "the stale 'eleven subcommands' count must be gone; got:\n" + doc
    )
    n = _subcommand_count()
    if n != 11:
        # spec-literal bare-word check, valid while the tree is not 11 wide
        assert "eleven" not in doc, (
            "the bare stale word 'eleven' must be gone; got:\n" + doc
        )


def test_b02_no_other_count_word_precedes_subcommands():
    doc = cli.build_parser.__doc__ or ""
    n = _subcommand_count()
    for k, w in _NUM_WORD.items():
        if k == n:
            continue
        assert f"{w} subcommands" not in doc, (
            f"stale count '{w} subcommands' must not appear "
            f"(the live subcommand count is {n}); got:\n{doc}"
        )


# ==========================================================================
# Behavior 3 -- _cmd_tools docstring names the LIVE tool count as an English
# word (currently "fourteen registered tools").
# ==========================================================================
def test_b03_cmd_tools_docstring_names_live_tool_count():
    n = len(ToolRegistry.tool_names())
    doc = cli._cmd_tools.__doc__ or ""
    phrase = f"{_word(n)} registered tools"
    assert phrase in doc, (
        f"_cmd_tools.__doc__ must name the live tool count as {phrase!r} "
        f"(live count = {n}); got docstring:\n{doc}"
    )


def test_b03_live_tool_count_is_fourteen():
    assert len(ToolRegistry.tool_names()) == 14


# ==========================================================================
# Behavior 4 -- the stale "ten registered tools" is gone; no OTHER count-word
# precedes "registered tools" (drift-safe stale guard).
# ==========================================================================
def test_b04_stale_ten_registered_tools_gone():
    doc = cli._cmd_tools.__doc__ or ""
    assert "ten registered tools" not in doc, (
        "the stale 'ten registered tools' count must be gone; got:\n" + doc
    )


def test_b04_no_other_count_word_precedes_registered_tools():
    doc = cli._cmd_tools.__doc__ or ""
    n = len(ToolRegistry.tool_names())
    for k, w in _NUM_WORD.items():
        if k == n:
            continue
        assert f"{w} registered tools" not in doc, (
            f"stale count '{w} registered tools' must not appear "
            f"(the live tool count is {n}); got:\n{doc}"
        )


# ==========================================================================
# Behavior 5 -- _cmd_collectors docstring count matches the live registry
# (consistency pin so the already-correct "fifteen" cannot drift on a future
# collector-add).
# ==========================================================================
def test_b05_cmd_collectors_docstring_matches_live_count():
    n = len(all_collectors())
    doc = cli._cmd_collectors.__doc__ or ""
    phrase = f"{_word(n)} registered collectors"
    assert phrase in doc, (
        f"_cmd_collectors.__doc__ must name the live collector count as "
        f"{phrase!r} (live count = {n}); got docstring:\n{doc}"
    )


def test_b05_live_collector_count_is_fifteen():
    assert len(all_collectors()) == 15


def test_b05_no_other_count_word_precedes_registered_collectors():
    doc = cli._cmd_collectors.__doc__ or ""
    n = len(all_collectors())
    for k, w in _NUM_WORD.items():
        if k == n:
            continue
        assert f"{w} registered collectors" not in doc, (
            f"stale count '{w} registered collectors' must not appear "
            f"(the live collector count is {n}); got:\n{doc}"
        )


# ==========================================================================
# Behavior 6 -- the edits are INERT: no runtime behavior change. --help exits 0
# and lists ALL 14 subcommand names; tools/collectors/providers/policy each
# return 0; the docstring text is never printed to stdout.
# ==========================================================================
def test_b06_help_exits_zero_and_lists_all_subcommands():
    rc, code, out, err = _run(["--help"])
    assert code == 0, f"--help must exit 0 (argparse convention); got {code!r}"
    for name in EXPECTED_SUBCOMMANDS:
        assert name in out, f"--help stdout must list subcommand {name!r}; got:\n{out}"


def test_b06_help_does_not_leak_function_docstrings():
    rc, code, out, err = _run(["--help"])
    for phrase in (
        "fourteen subcommands",
        "eleven subcommands",
        "registered tools",
        "registered collectors",
    ):
        assert phrase not in out, (
            f"function docstring text {phrase!r} must not leak into --help stdout"
        )


@pytest.mark.parametrize("verb", ["tools", "collectors", "providers", "policy"])
def test_b06_catalog_verbs_return_zero_no_docstring_leak(verb):
    rc, code, out, err = _run([verb])
    assert rc == 0, f"`pla {verb}` must return 0; got rc={rc!r} exit={code!r}"
    for phrase in ("registered tools", "registered collectors", "eleven subcommands"):
        assert phrase not in out, (
            f"`pla {verb}` stdout must not print the docstring phrase {phrase!r}"
        )


# ==========================================================================
# Behavior 7 -- version unchanged (docstring-only edit): __version__ == 0.1.1
# and --version prints "pla 0.1.1".
# ==========================================================================
def test_b07_version_constant_unchanged():
    assert __version__ == "0.1.1", (
        f"a docstring-only fix must NOT bump the version; got {__version__!r}"
    )


def test_b07_cli_version_flag_prints_pla_version():
    rc, code, out, err = _run(["--version"])
    assert code == 0, f"--version must exit 0; got {code!r}"
    assert out.strip() == "pla 0.1.1", f"--version stdout; got {out.strip()!r}"


# ==========================================================================
# Behavior 8 (registry no-regression anchor) -- the docstring fix added NO
# verb/tool/collector, so the three live registry sizes are unchanged. This
# locks the count trio the drift-guards are bound to.
# ==========================================================================
def test_b08_registry_sizes_unchanged():
    assert _subcommand_count() == 14
    assert len(ToolRegistry.tool_names()) == 14
    assert len(all_collectors()) == 15
