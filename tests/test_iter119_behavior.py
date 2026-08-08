"""Behavior tests for state-dir iteration 112 (ships as commit-seq ``factory iter 119``).

Feature under test: the two ONBOARDING claims in ``README.md`` -- the Quickstart's
install line and the ``### Try it on your own repo`` paragraph -- are made exact,
and both are locked by a guard that DERIVES the standalone-vs-needs-a-prior-run
split from the live parser instead of trusting prose.

Why this file is the oracle
Two published statements were measurably false at HEAD and a green suite could
not see either one. (a) The Quickstart fenced block published a bare
``uv sync``, which is precisely the form that may re-resolve and mutate
``uv.lock`` -- while the ``Makefile`` and CI both run ``uv sync --locked``, and
``tests/test_iter100_behavior.py`` already forbids the bare form IN THE MAKEFILE
ONLY, so the README was free to publish the exact command the suite bans
elsewhere. (b) The paragraph concluded that ten LLM-free verbs "work on a bare
``uv sync``"; three of the ten (``diff``, ``explain``, ``trace``) exit ``2``
until a PRIOR run has produced the artifact they inspect.

Why both buckets are DERIVED and never written down as an allowlist
A hand-written list of seven standalone verbs would be a second copy of the
truth, and it would rot silently in the SAFE direction the first time a verb
gained a required option. So the split is computed from the live
``build_parser()``: a verb is standalone when every ``required=True`` option it
declares is satisfiable from the reader's own checkout, and needs a prior run
when at least one required option names an artifact a previous run produced. The
classification is fail-CLOSED -- a required option in NEITHER declared bucket
fails the test naming that option, so a new required flag cannot be quietly
absorbed into the standalone side.

Every reader here is fired on a known-bad sample AND on a known-good one in the
same module (behavior 9): a paragraph reader that silently matched nothing, or a
classifier that could not reject an unclassified option, would make these guards
pass vacuously -- strictly worse than no guard at all.

Ambiguity note for the PM (spec behavior 10): the spec asks for the bytes above
the ``PORTFOLIO INTRO -- human-owned`` marker to be "byte-identical to HEAD". A
literal byte-equality assertion would DEADLOCK the loop, because the marker's own
NARROW CARVE-OUT *requires* an automated contributor to correct three numbers
inside that intro (collector count, CLI-verb count, tests floor) -- such an
iteration would go red in its own tester stage before it could commit. This file
therefore asserts LINE-SCOPED byte-equality: a differing intro line is forgiven
only when it carries one of the three carve-out anchors AND differs in digits
alone. Every other change -- prose, title, badge, ordering, a deleted line, or a
digit on a line with no anchor -- is a failure, and behavior 10b proves that
two-sided on synthetic input. The exempted digits are not unguarded either:
``tests/test_readme_and_ci_contract.py`` already pins each of the three against
its live source.

Isolation: black-box, contract honored. The seams used are (a) ``README.md``,
``uv.lock`` and the git object store read as TEXT -- the README is the artifact
under test, (b) the public ``build_parser()`` entry point, and (c) the reused
``derive_llm_free_verbs()`` helper from ``tests/test_iter116_behavior.py``, which
spec behavior 4 mandates. No implementation module was read to learn how it
works, and no engineer, reviewer or fix note was opened.

Offline and deterministic: file reads, one in-process parser construction, and
one local ``git show`` of a blob already in ``.git`` (no network, no fetch, no
remote). Nothing is written anywhere. Runtime is milliseconds.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser
from tests.test_iter116_behavior import derive_llm_free_verbs

# --------------------------------------------------------------------------
# Paths and the tester's ground facts -- transcribed from the spec (pm.md),
# never imported from the implementation, so drift in EITHER direction is caught.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
LOCK = REPO / "uv.lock"

# The live marker line reads "PORTFOLIO INTRO <em-dash> human-owned"; match on the
# stable ASCII prefix only -- the same substring the README contract test uses --
# so a dash-style edit cannot silently disarm this guard.
MARKER = "PORTFOLIO INTRO"

QUICKSTART_HEADING = "## Quickstart"
OWN_REPO_HEADING = "### Try it on your own repo"

# Spec behavior 3: the two DECLARED buckets. A required option must be in exactly
# one of them; anything else is a test FAILURE, never a silent default.
WORKSPACE_SATISFIABLE = frozenset({"--workspace"})
PRIOR_RUN_ARTIFACT = frozenset({"--slate", "--goal-id", "--run-dir", "--old", "--new"})

# Spec behaviors 3-5: assertions ON the derivation, not the source of truth.
EXPECTED_REQUIRED_OPTIONS: dict[str, frozenset[str]] = {
    "collectors": frozenset(),
    "config": frozenset(),
    "diff": frozenset({"--old", "--new"}),
    "dispatch": frozenset({"--slate", "--goal-id"}),
    "explain": frozenset({"--slate"}),
    "policy": frozenset(),
    "providers": frozenset(),
    "resume": frozenset({"--run-dir"}),
    "run": frozenset({"--workspace"}),
    "runs": frozenset(),
    "scan": frozenset({"--workspace"}),
    "signals": frozenset({"--workspace"}),
    "tools": frozenset(),
    "trace": frozenset({"--run-dir"}),
    "watch": frozenset({"--workspace"}),
}
EXPECTED_STANDALONE = frozenset(
    {"collectors", "config", "policy", "providers", "runs", "signals", "tools"}
)
EXPECTED_PRIOR_RUN = frozenset({"diff", "explain", "trace"})

# Spec behavior 2: the Quickstart block, in order, commands only (comments stripped).
EXPECTED_QUICKSTART_COMMANDS = [
    "uv sync --locked",
    "make demo",
    "make test",
    "make cov",
    "make typecheck",
]

# Spec behavior 8: the published false conclusion, verbatim.
REMOVED_CLAIM = "so they work on a bare"

NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
}


# --------------------------------------------------------------------------
# README readers -- fenced blocks, the Quickstart block, the own-repo paragraph
# --------------------------------------------------------------------------


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def fenced_blocks(text: str) -> list[list[tuple[int, str]]]:
    """The fenced code blocks as lists of ``(1-based lineno, raw_line)``."""
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    inside = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if raw.lstrip().startswith("```"):
            if inside:
                blocks.append(current)
                current = []
            inside = not inside
            continue
        if inside:
            current.append((lineno, raw))
    assert not inside, "README.md has an unbalanced code fence"
    return blocks


def fenced_lines(text: str) -> list[tuple[int, str]]:
    return [pair for block in fenced_blocks(text) for pair in block]


def heading_lineno(text: str, heading: str) -> int:
    hits = [i for i, line in enumerate(text.splitlines(), start=1) if line.strip() == heading]
    assert len(hits) == 1, f"expected exactly one {heading!r} heading in README.md, found {hits}"
    return hits[0]


def quickstart_block(text: str) -> list[tuple[int, str]]:
    """The first fenced block below the ``## Quickstart`` heading."""
    start = heading_lineno(text, QUICKSTART_HEADING)
    for block in fenced_blocks(text):
        if block and block[0][0] > start:
            return block
    raise AssertionError("no fenced block follows the ## Quickstart heading")


def split_command_and_comment(line: str) -> tuple[str, str]:
    """Split a shell line into ``(command, comment)``; comment excludes the ``#``."""
    command, _, comment = line.partition("#")
    return command.strip(), comment.strip()


def own_repo_paragraph(text: str) -> str:
    """The prose paragraph between ``### Try it on your own repo`` and its first fence."""
    lines = text.splitlines()
    start = heading_lineno(text, OWN_REPO_HEADING)  # 1-based
    collected: list[str] = []
    for line in lines[start:]:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("#"):
            break
        collected.append(line)
    paragraph = "\n".join(collected).strip()
    assert paragraph, f"{OWN_REPO_HEADING!r} is followed by no prose at all"
    return paragraph


def flatten(paragraph: str) -> str:
    return re.sub(r"\s+", " ", paragraph).strip()


def sentences(paragraph: str) -> list[tuple[int, str]]:
    """``(offset, sentence)`` pairs against the FLATTENED paragraph."""
    flat = flatten(paragraph)
    out: list[tuple[int, str]] = []
    offset = 0
    for part in re.split(r"(?<=[.!?]) ", flat):
        out.append((offset, part))
        offset += len(part) + 1
    return out


def numbers_in(sentence: str) -> list[int]:
    """Every integer a sentence states, as digits or as an English number word."""
    values: list[int] = []
    for token in re.findall(r"[A-Za-z]+|\d+", sentence):
        if token.isdigit():
            values.append(int(token))
        elif token.lower() in NUMBER_WORDS:
            values.append(NUMBER_WORDS[token.lower()])
    return values


# --------------------------------------------------------------------------
# Parser-derived buckets (behaviors 3-5) -- fail-closed
# --------------------------------------------------------------------------


def required_options_by_verb() -> dict[str, frozenset[str]]:
    """``verb -> its ``required=True`` option strings``, from the LIVE parser."""
    parser = build_parser()
    subparser_actions = [
        action
        for action in parser._subparsers._group_actions  # type: ignore[union-attr]
        if hasattr(action, "choices")
    ]
    assert len(subparser_actions) == 1, (
        f"expected exactly one subparsers action, got {len(subparser_actions)}"
    )
    out: dict[str, frozenset[str]] = {}
    for verb, subparser in subparser_actions[0].choices.items():
        names: set[str] = set()
        for action in subparser._actions:
            if not action.option_strings:
                continue  # positionals are not "option strings"
            if not getattr(action, "required", False):
                continue
            names.update(action.option_strings)
        out[verb] = frozenset(names)
    assert out, "derived ZERO subparsers -- the derivation is broken, not the README"
    return out


def unclassified_options(
    required_by_verb: dict[str, frozenset[str]],
    workspace_satisfiable: frozenset[str] = WORKSPACE_SATISFIABLE,
    prior_run_artifact: frozenset[str] = PRIOR_RUN_ARTIFACT,
) -> list[str]:
    """Required options that are in NEITHER declared bucket, or in BOTH."""
    offenders: list[str] = []
    for verb, options in sorted(required_by_verb.items()):
        for option in sorted(options):
            in_workspace = option in workspace_satisfiable
            in_prior_run = option in prior_run_artifact
            if in_workspace == in_prior_run:  # neither, or ambiguously both
                where = "BOTH buckets" if in_workspace else "NEITHER bucket"
                offenders.append(f"{verb} {option} ({where})")
    return offenders


def derive_buckets() -> tuple[frozenset[str], frozenset[str]]:
    """``(standalone, needs a prior run)`` over the LLM-free verbs."""
    required = required_options_by_verb()
    offenders = unclassified_options(required)
    assert not offenders, (
        "refusing to derive the standalone set while a required option is "
        f"unclassified: {offenders}"
    )
    llm_free = derive_llm_free_verbs()
    assert llm_free, "derive_llm_free_verbs() yielded nothing -- the derivation is broken"
    standalone: set[str] = set()
    prior_run: set[str] = set()
    for verb in sorted(llm_free):
        assert verb in required, f"LLM-free verb {verb!r} is not a live subcommand"
        if any(option in PRIOR_RUN_ARTIFACT for option in required[verb]):
            prior_run.add(verb)
        else:
            standalone.add(verb)
    return frozenset(standalone), frozenset(prior_run)


# --------------------------------------------------------------------------
# Paragraph guard (behaviors 6-7) -- one helper, exercised two-sided in b9
# --------------------------------------------------------------------------


def paragraph_defects(
    paragraph: str,
    standalone: frozenset[str],
    prior_run: frozenset[str],
) -> list[str]:
    """Every way the own-repo paragraph disagrees with the DERIVED buckets."""
    flat = flatten(paragraph)
    defects: list[str] = []

    for verb in sorted(standalone | prior_run):
        if f"`{verb}`" not in flat:
            defects.append(f"verb `{verb}` is not named in the paragraph")

    parsed = sentences(paragraph)

    # The sentence that LISTS the standalone verbs: the one naming the most of
    # them, and at least four, so a passing mention cannot be mistaken for it.
    scored = [
        (sum(1 for verb in standalone if f"`{verb}`" in sentence), offset, sentence)
        for offset, sentence in parsed
    ]
    best = max(scored, key=lambda item: item[0]) if scored else (0, 0, "")
    if best[0] < 4:
        defects.append("no sentence in the paragraph lists the standalone verbs")
        return defects
    standalone_offset, standalone_sentence = best[1], best[2]

    stated = numbers_in(standalone_sentence)
    if len(standalone) not in stated:
        defects.append(
            f"the standalone sentence does not state the derived standalone count "
            f"{len(standalone)}; it states {stated}: {standalone_sentence!r}"
        )

    # The sentence that INTRODUCES the exception: the first one after the
    # standalone list whose numbers include the derived prior-run count.
    exception: tuple[int, str] | None = None
    for offset, sentence in parsed:
        if offset <= standalone_offset:
            continue
        if len(prior_run) in numbers_in(sentence):
            exception = (offset, sentence)
            break
    if exception is None:
        defects.append(
            f"no sentence after the standalone list states the derived prior-run "
            f"count {len(prior_run)}"
        )
        return defects

    exception_end = exception[0] + len(exception[1])
    for verb in sorted(prior_run):
        position = flat.find(f"`{verb}`")
        if position < 0:
            continue  # already reported above
        if position < exception_end:
            defects.append(
                f"prior-run verb `{verb}` is named at offset {position}, BEFORE the "
                f"sentence that introduces the exception ends ({exception_end})"
            )
    return defects


# --------------------------------------------------------------------------
# uv.lock reader (behavior 2) -- what the Quickstart comment must name
# --------------------------------------------------------------------------


def lock_declared_dependencies() -> frozenset[str]:
    """Every dependency name this project DECLARES in ``uv.lock`` (runtime + dev)."""
    text = LOCK.read_text(encoding="utf-8")
    match = re.search(r'^\[\[package\]\]\nname = "proactive-loop-agent"$', text, re.MULTILINE)
    assert match, "uv.lock has no [[package]] block for proactive-loop-agent"
    tail = text[match.end() :]
    next_package = re.search(r"^\[\[package\]\]$", tail, re.MULTILINE)
    block = tail[: next_package.start()] if next_package else tail
    names = frozenset(re.findall(r'\{\s*name\s*=\s*"([^"]+)"', block))
    assert "pydantic" in names, (
        f"the uv.lock reader did not find the runtime dependency; got {sorted(names)}"
    )
    return names


# --------------------------------------------------------------------------
# git reader (behavior 10)
# --------------------------------------------------------------------------


def git_blob(rev_path: str) -> str | None:
    """A committed blob's text, or ``None`` when this checkout has no git objects.

    Local object-store read only: ``git show`` never contacts a remote, so this
    stays inside the repo's offline-first contract.
    """
    if not (REPO / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO), "show", rev_path],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None  # no git binary on PATH (e.g. an exported tarball)
    if proc.returncode != 0:
        return None
    return proc.stdout


def above_marker(text: str) -> str:
    """Everything from line 1 through the human-owned marker line, inclusive."""
    lines = text.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if MARKER in line]
    assert len(hits) == 1, f"expected exactly one {MARKER!r} marker line, found {len(hits)}"
    return "".join(lines[: hits[0] + 1])


def digits_masked(text: str) -> str:
    """``text`` with every digit group replaced by ``#``."""
    return re.sub(r"[\d,]*\d", "#", text)


# The three -- and only three -- claims the marker's NARROW CARVE-OUT lets an
# automated contributor renumber. A differing intro line is forgiven ONLY when it
# carries one of these anchors AND differs in digits alone; every other change,
# on any line, is a defect. Each anchor's number is separately pinned to its live
# source by tests/test_readme_and_ci_contract.py, so nothing here is left unguarded.
CARVE_OUT_ANCHORS = ("context collectors", "CLI verbs", "tests")


def intro_defects(before: str, after: str) -> list[str]:
    """Every change between two versions of the human-owned intro that is NOT the carve-out."""
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    defects: list[str] = []
    if len(before_lines) != len(after_lines):
        defects.append(
            f"the intro's line count changed: {len(before_lines)} -> {len(after_lines)}"
        )
    for index in range(min(len(before_lines), len(after_lines))):
        old_line = before_lines[index]
        new_line = after_lines[index]
        if old_line == new_line:
            continue
        renumbered = digits_masked(old_line) == digits_masked(new_line)
        carve_out = any(anchor in new_line for anchor in CARVE_OUT_ANCHORS)
        if renumbered and carve_out:
            continue  # the sanctioned numeric correction
        defects.append(
            f"line {index + 1} changed outside the numeric carve-out:\n"
            f"    HEAD: {old_line!r}\n    WORK: {new_line!r}"
        )
    return defects


# ==========================================================================
# Behavior 1 -- every fenced `uv sync` installs the LOCKED set
# ==========================================================================


def test_behavior1_every_fenced_uv_sync_is_locked() -> None:
    text = readme_text()
    lines = fenced_lines(text)
    assert lines, "the fenced-block extractor yielded NOTHING -- the guard would be vacuous"

    mentions = [(lineno, line) for lineno, line in lines if "uv sync" in line]
    assert mentions, (
        "no fenced README line mentions `uv sync` at all; this guard is meant to "
        "police the Quickstart install line, so its absence means the extractor or "
        "the README moved"
    )
    offenders = [(lineno, line) for lineno, line in mentions if "--locked" not in line]
    assert not offenders, (
        "README.md publishes a bare `uv sync` inside a fenced block, which is the "
        "form that may re-resolve and mutate uv.lock -- the Makefile and CI both "
        f"use `uv sync --locked`: {offenders}"
    )


# ==========================================================================
# Behavior 2 -- the Quickstart block installs the locked set, truthfully,
# and its other four commands are unchanged and in order
# ==========================================================================


def test_behavior2_quickstart_block_is_truthful_and_otherwise_unchanged() -> None:
    text = readme_text()
    block = quickstart_block(text)
    assert block, "the ## Quickstart fenced block is empty"

    commands = [split_command_and_comment(line)[0] for _, line in block if line.strip()]
    assert commands == EXPECTED_QUICKSTART_COMMANDS, (
        "the Quickstart block's commands changed; expected exactly "
        f"{EXPECTED_QUICKSTART_COMMANDS} in that order, got {commands}"
    )

    install = [
        (lineno, line)
        for lineno, line in block
        if split_command_and_comment(line)[0] == "uv sync --locked"
    ]
    assert len(install) == 1, (
        f"expected exactly one `uv sync --locked` line in the Quickstart block, got {install}"
    )
    lineno, line = install[0]
    comment = split_command_and_comment(line)[1]
    assert comment, (
        f"README.md:{lineno} dropped the install line's trailing comment; the "
        "Quickstart teaches what the command does, so the comment must survive"
    )
    assert "install" in comment.lower(), (
        f"README.md:{lineno} comment no longer says what the command installs: {comment!r}"
    )
    assert "locked" in comment.lower(), (
        f"README.md:{lineno} comment must still name the LOCKED set (that is the "
        f"whole point of --locked): {comment!r}"
    )
    declared = lock_declared_dependencies()
    missing = sorted(name for name in declared if name not in comment)
    assert not missing, (
        f"README.md:{lineno} claims to name the locked dependency set but omits "
        f"{missing}, which uv.lock declares for this project; comment was {comment!r}"
    )


# ==========================================================================
# Behavior 3 -- every LIVE required option is classified (fail-closed)
# ==========================================================================


def test_behavior3_every_live_required_option_is_classified() -> None:
    assert not (WORKSPACE_SATISFIABLE & PRIOR_RUN_ARTIFACT), (
        "the two declared buckets overlap, so 'exactly one' is unprovable"
    )
    required = required_options_by_verb()
    assert len(required) == 15, (
        f"expected the 15 documented verbs, got {len(required)}: {sorted(required)}"
    )
    offenders = unclassified_options(required)
    assert not offenders, (
        "a live required CLI option belongs to neither declared bucket, so the "
        "standalone/prior-run split published in the README cannot be derived. "
        "Classify it in WORKSPACE_SATISFIABLE or PRIOR_RUN_ARTIFACT: " + str(offenders)
    )
    assert required == EXPECTED_REQUIRED_OPTIONS, (
        "the live required-option map drifted from the spec's measured facts; "
        f"live={ {k: sorted(v) for k, v in sorted(required.items())} }"
    )


# ==========================================================================
# Behavior 4 -- the derived standalone set is exactly the 7 published names
# ==========================================================================


def test_behavior4_derived_standalone_set_is_the_seven_published_verbs() -> None:
    standalone, _ = derive_buckets()
    assert standalone == EXPECTED_STANDALONE, (
        f"derived standalone verbs {sorted(standalone)} != published "
        f"{sorted(EXPECTED_STANDALONE)}"
    )
    assert len(standalone) == 7, f"expected 7 standalone verbs, got {len(standalone)}"


# ==========================================================================
# Behavior 5 -- the derived prior-run set is exactly the 3 published names
# ==========================================================================


def test_behavior5_derived_prior_run_set_is_the_three_published_verbs() -> None:
    standalone, prior_run = derive_buckets()
    assert prior_run == EXPECTED_PRIOR_RUN, (
        f"derived prior-run verbs {sorted(prior_run)} != published "
        f"{sorted(EXPECTED_PRIOR_RUN)}"
    )
    assert len(prior_run) == 3, f"expected 3 prior-run verbs, got {len(prior_run)}"
    assert not (standalone & prior_run), "a verb landed in both buckets"
    assert standalone | prior_run == derive_llm_free_verbs(), (
        "the two buckets do not partition the LLM-free verb set; some LLM-free "
        "verb is in neither"
    )


# ==========================================================================
# Behavior 6 -- the paragraph states both derived counts (and the 10-of-15 claim)
# ==========================================================================


def test_behavior6_paragraph_states_the_derived_counts() -> None:
    text = readme_text()
    paragraph = own_repo_paragraph(text)
    standalone, prior_run = derive_buckets()

    defects = [
        defect
        for defect in paragraph_defects(paragraph, standalone, prior_run)
        if "count" in defect or "no sentence" in defect
    ]
    assert not defects, (
        "the `### Try it on your own repo` paragraph's counts drifted from the "
        f"derived split ({len(standalone)} standalone / {len(prior_run)} prior-run): {defects}"
    )

    # The paragraph's own "ten of the fifteen" framing must also stay true.
    flat = flatten(paragraph)
    llm_free_sentences = [
        sentence for _, sentence in sentences(paragraph) if "LLM client" in sentence
    ]
    assert llm_free_sentences, (
        f"the paragraph no longer explains the LLM-free split at all: {flat!r}"
    )
    stated = numbers_in(llm_free_sentences[0])
    live_verb_count = len(required_options_by_verb())
    llm_free_count = len(derive_llm_free_verbs())
    assert llm_free_count in stated and live_verb_count in stated, (
        f"the paragraph claims {stated} but the live parser has {live_verb_count} "
        f"verbs of which {llm_free_count} never construct an LLM client: "
        f"{llm_free_sentences[0]!r}"
    )


# ==========================================================================
# Behavior 7 -- all 10 verbs are named, each on the correct side
# ==========================================================================


def test_behavior7_paragraph_names_all_ten_verbs_on_the_correct_side() -> None:
    text = readme_text()
    paragraph = own_repo_paragraph(text)
    standalone, prior_run = derive_buckets()

    defects = paragraph_defects(paragraph, standalone, prior_run)
    assert not defects, (
        "the `### Try it on your own repo` paragraph disagrees with the derived "
        f"verb split: {defects}"
    )

    # The paragraph must also SAY what the exception is, not merely count it.
    flat = flatten(paragraph)
    assert "2" in flat, (
        "the paragraph must tell the reader that diff/explain/trace exit `2` "
        f"until a prior run exists: {flat!r}"
    )


# ==========================================================================
# Behavior 8 -- the false conclusion is gone
# ==========================================================================


def test_behavior8_the_false_bare_uv_sync_conclusion_is_gone() -> None:
    text = readme_text()
    # Prove the matcher can see the claim before trusting its absence.
    planted = f"ten of the fifteen verbs never construct an LLM client, {REMOVED_CLAIM} uv sync."
    assert REMOVED_CLAIM in planted, "the matcher for the removed claim does not match"
    assert REMOVED_CLAIM not in text, (
        f"README.md still publishes the false conclusion {REMOVED_CLAIM!r}: three "
        "of the ten LLM-free verbs need a prior run's artifacts"
    )


# ==========================================================================
# Behavior 9 -- the guards are proven to FIRE (two-sided, synthetic input)
# ==========================================================================

GOOD_PARAGRAPH = (
    "Ten of the fifteen verbs never construct an LLM client at all. "
    "Seven of those ten -- `collectors`, `config`, `policy`, `providers`, "
    "`runs`, `signals` and `tools` -- need nothing but the checkout itself. "
    "The other three are inspectors of a run that already happened, so they are "
    "not standalone. `diff` and `explain` read a slate file and `trace` reads a "
    "run directory's checkpoint, so each exits `2` until one exists."
)


def test_behavior9a_paragraph_guard_accepts_a_known_good_sample() -> None:
    defects = paragraph_defects(GOOD_PARAGRAPH, EXPECTED_STANDALONE, EXPECTED_PRIOR_RUN)
    assert defects == [], (
        f"the paragraph guard rejects a correct paragraph, so every failure it "
        f"reports is untrustworthy: {defects}"
    )


def test_behavior9b_classifier_fires_on_an_unclassified_required_option() -> None:
    offenders = unclassified_options({"ghost": frozenset({"--mystery"})})
    assert offenders == ["ghost --mystery (NEITHER bucket)"], (
        f"an unclassified required option must FAIL the guard, got {offenders}"
    )
    both = unclassified_options(
        {"ghost": frozenset({"--workspace"})},
        workspace_satisfiable=frozenset({"--workspace"}),
        prior_run_artifact=frozenset({"--workspace"}),
    )
    assert both == ["ghost --workspace (BOTH buckets)"], (
        f"an option in both buckets must FAIL the guard, got {both}"
    )


def test_behavior9c_paragraph_guard_fires_on_a_wrong_count() -> None:
    wrong = GOOD_PARAGRAPH.replace("Seven of those ten", "Six of those ten")
    assert wrong != GOOD_PARAGRAPH, "the synthetic mutation did not apply"
    defects = paragraph_defects(wrong, EXPECTED_STANDALONE, EXPECTED_PRIOR_RUN)
    assert any("standalone count 7" in defect for defect in defects), (
        f"a wrong standalone count must be reported, got {defects}"
    )

    wrong_other = GOOD_PARAGRAPH.replace("The other three", "The other four")
    defects_other = paragraph_defects(wrong_other, EXPECTED_STANDALONE, EXPECTED_PRIOR_RUN)
    assert any("prior-run count 3" in defect for defect in defects_other), (
        f"a wrong prior-run count must be reported, got {defects_other}"
    )


def test_behavior9d_paragraph_guard_fires_on_an_omitted_verb() -> None:
    missing = GOOD_PARAGRAPH.replace("`runs`, ", "")
    assert missing != GOOD_PARAGRAPH, "the synthetic mutation did not apply"
    defects = paragraph_defects(missing, EXPECTED_STANDALONE, EXPECTED_PRIOR_RUN)
    assert any("`runs`" in defect and "not named" in defect for defect in defects), (
        f"an omitted verb must be reported by name, got {defects}"
    )


def test_behavior9e_paragraph_guard_fires_on_a_verb_on_the_wrong_side() -> None:
    swapped = (
        "Ten of the fifteen verbs never construct an LLM client at all. "
        "`diff` is one of them. "
        "Seven of those ten -- `collectors`, `config`, `policy`, `providers`, "
        "`runs`, `signals` and `tools` -- need nothing but the checkout itself. "
        "The other three are inspectors of a run that already happened. "
        "`explain` reads a slate file and `trace` reads a checkpoint, exiting `2` "
        "until one exists."
    )
    defects = paragraph_defects(swapped, EXPECTED_STANDALONE, EXPECTED_PRIOR_RUN)
    assert any("BEFORE the sentence" in defect for defect in defects), (
        f"a prior-run verb named on the standalone side must be reported, got {defects}"
    )


def test_behavior9f_own_repo_paragraph_reader_is_not_reading_the_whole_readme() -> None:
    text = readme_text()
    paragraph = own_repo_paragraph(text)
    assert "pla signals --workspace ." not in paragraph, (
        "the paragraph reader swallowed the fenced block below it, so behavior 7's "
        "'which side is this verb on' check would be meaningless"
    )
    assert len(paragraph) < len(text) / 4, (
        f"the paragraph reader returned {len(paragraph)} of {len(text)} README "
        "bytes -- it is not reading one paragraph"
    )


# ==========================================================================
# Behavior 10 -- nothing above the human-owned marker changed
# ==========================================================================


def test_behavior10_human_owned_intro_is_unchanged_except_carve_out_numbers() -> None:
    text = readme_text()
    intro = above_marker(text)

    # Always-on structural assertions, so this test is never vacuous.
    assert intro.lstrip().startswith("# proactive-loop-agent"), "the intro title changed"
    assert "What this project demonstrates" in intro, "the intro lost its demonstrates section"
    assert "img.shields.io" in intro, "the intro lost its badges"
    assert intro.count("```") == 0, "a fenced block appeared in the human-owned intro"

    committed = git_blob("HEAD:README.md")
    if committed is None:
        pytest.skip("no git object store in this checkout; structural checks above still ran")
    defects = intro_defects(above_marker(committed), intro)
    assert not defects, (
        "the human-owned portfolio intro changed above the PORTFOLIO INTRO marker. "
        "Only the marker's narrow numeric carve-out (collector count, CLI-verb "
        "count, tests floor) may move there:\n" + "\n".join(defects)
    )


def test_behavior10b_intro_guard_forgives_only_the_numeric_carve_out() -> None:
    """Two-sided proof for the ONE region behavior 10 exempts."""
    baseline = (
        "# proactive-loop-agent\n"
        "\n"
        "- 16 context collectors, 15 CLI verbs, **2,200+ tests**\n"
        "- Safety by construction, sandboxed by default\n"
    )

    renumbered = baseline.replace(
        "16 context collectors, 15 CLI verbs, **2,200+ tests**",
        "17 context collectors, 16 CLI verbs, **2,600+ tests**",
    )
    assert renumbered != baseline, "the synthetic renumbering did not apply"
    assert intro_defects(baseline, renumbered) == [], (
        "the sanctioned numeric carve-out must be allowed, otherwise the operator's "
        "own required number-fix would go red in its own tester stage"
    )

    reworded = baseline.replace("Safety by construction", "Safety by convention")
    assert intro_defects(baseline, reworded), "a PROSE edit above the marker must be reported"

    unanchored = baseline.replace("proactive-loop-agent", "proactive-loop-agent v2")
    assert intro_defects(baseline, unanchored), "a title edit above the marker must be reported"

    digits_without_anchor = baseline.replace(
        "- Safety by construction, sandboxed by default",
        "- Safety by construction, 3 sandboxed by default",
    )
    assert intro_defects(baseline, digits_without_anchor), (
        "a digit change on a line with NO carve-out anchor must still be reported"
    )

    dropped = baseline.replace("- Safety by construction, sandboxed by default\n", "")
    assert any("line count changed" in defect for defect in intro_defects(baseline, dropped)), (
        "deleting an intro line must be reported"
    )
