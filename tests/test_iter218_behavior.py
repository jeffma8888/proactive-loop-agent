"""Repo contract: every iteration tag the Done ledger cites resolves to a real commit.

``README.md`` sends a reader to ``ROADMAP.md`` to learn what shipped and in which iteration,
and the Done ledger's trailing ``(foundry iter N)`` parenthesis is the ONLY thread tying a
roadmap row to the commit history. Iteration 239 found that thread broken for the 8 newest
rows: commit subjects carry ``factory iter 1..204`` and then ``foundry iter 231..238`` -- the
vocabulary switched mid-history -- while rows ``#236``..``#243`` cited a ``factory iter 20N``
number that appears in NO commit subject. A reader who followed the README's promise and
grepped ``git log`` for the cited tag found nothing and would conclude the row never shipped.

WHY an oracle rather than a one-time repair. Nothing in the suite read these tags, so the
drift was structurally invisible and grew by exactly one row per iteration. The two counters
are not a fixed offset either: over the ledger's rows ``state - factory`` took five different
values, so a reader cannot derive one from the other and neither can a future PM.

WHY the NEWEST tag is exempt. The PM records a row in the SAME commit that creates its tag,
so that tag cannot exist in ``git log`` while this suite runs. The exemption is pinned to the
MAXIMUM cited number (:func:`pending_tags`), never to a threshold: the 8 tags this iteration
repaired were all numerically ABOVE git's highest ``factory`` number (204), so an
"exempt anything large" rule would have hidden the entire defect. ``test_b05`` is that control.

WHY the audit is scoped to the LEDGER region of ``ROADMAP.md`` alone:

* ``ROADMAP_ARCHIVE.md`` is 438KB of retired detail and is not an audit target. Its rows are
  historical prose, it is never edited by this iteration, and reading it wholesale is exactly
  the cost the index/archive split exists to avoid.
* ``tests/`` and ``src/`` are not audit targets either. Four test modules legitimately spell
  ``factory iter 205``..``212`` in their own docstrings, describing the iteration that wrote
  them; a dated self-description is correct prose, and widening the domain would red the build
  on it. ``src/proactive_loop/cli.py`` carries a deliberately DATED count for the same reason.
* Only ROWS count. Row numbers are quoted inside other rows' prose constantly, so the row
  probe is line-anchored, mirroring ``tests/test_roadmap_ledger_conservation.py``.

The violation finder is a PURE function over ``(ledger_text, present)`` so the contract can be
proven two-sided on synthetic input with no ``git`` and no I/O at all. The real-tree assertion
runs the one subprocess this module is allowed (``git log --format=%s``, no blame, no diffs,
no counts, no network) and SKIPS with a named reason where it structurally cannot run, so a
checkout without history -- a GitHub source zip -- degrades instead of erroring. CI always has
history: ``tests/test_readme_and_ci_contract.py::test_ci_checks_out_full_git_history``.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

THIS_MODULE: Final[Path] = Path(__file__).resolve()
TESTS_DIR: Final[Path] = THIS_MODULE.parent
REPO: Final[Path] = THIS_MODULE.parents[1]
ROADMAP: Final[Path] = REPO / "ROADMAP.md"

#: The heading that opens the LEDGER region; the region runs to end of file.
LEDGER_HEADING: Final[str] = "## Done ledger"

#: A ledger ROW, LINE-ANCHORED for the reason the sibling conservation guard gives: row
#: numbers appear inside other rows' prose, so an unanchored probe would count prose.
ROW_RE: Final[re.Pattern[str]] = re.compile(r"(?m)^- #(\d+) ")

#: A CITED TAG, read as the pair ``(vocabulary, number)``. The number is parsed as an int so
#: the early zero-padded subjects (``factory iter 01``) compare equal to an unpadded citation.
TAG_RE: Final[re.Pattern[str]] = re.compile(r"\b(factory|foundry) iter (\d+)\b")

#: The 8 tag strings iteration 239 retired. Their numbers sit ABOVE git's highest ``factory``
#: number, which is why the exemption must be pinned to the maximum CITED number.
RETIRED_TAG_STRINGS: Final[tuple[str, ...]] = tuple(
    f"factory iter {n}" for n in range(205, 213)
)

#: ``row id -> clipped title``, measured from the pre-relabel file. Relabelling a tag must not
#: disturb the title, so these are pinned verbatim rather than re-derived from the live text.
RELABELLED_ROW_TITLES: Final[dict[str, str]] = {
    "236": "Budget the two seams #225 left open: Path.stat fan-out and read_text decodes",
    "237": (
        "cli.py module docstring names the live verb count; "
        "partial 15-of-17 roster dropped"
    ),
    "238": "scan --exclude-path: the perception INPUT filter reaches the synthesis verb",
    "239": "run reports the AUTO_DISPATCH goals it skipped, with paste-ready commands",
    "240": (
        "Relocate the settled Done-ledger tail to the archive under a conservation guard"
    ),
    "241": "Paste-ready dispatch commands carry an absolute --slate path",
    "242": (
        "merge_conflict + broken_link read the shared dirent listing; "
        "6 collectors share 1 walk"
    ),
    "243": (
        r"todos gates its checkbox pass on the \[\s\] subpattern _CHECKBOX_RE requires"
    ),
}

#: ``row id -> iteration number`` for the same 8 rows, in the commit's own vocabulary.
RELABELLED_ROW_ITERATIONS: Final[dict[str, int]] = {
    str(236 + offset): 231 + offset for offset in range(8)
}

#: Counted anti-vacuity floors for the real-tree assertion. Each fails LOUDLY rather than
#: letting an empty parse pass as a clean audit -- the failure mode a green absence-based
#: check cannot distinguish from health.
MIN_PRESENT_TAGS: Final[int] = 200
MIN_LEDGER_ROWS: Final[int] = 40
MIN_RESOLVED_TAGS: Final[int] = 30


# --------------------------------------------------------------------------- pure functions


def ledger_region(roadmap_text: str) -> str:
    """Return ``roadmap_text`` from :data:`LEDGER_HEADING` to end of file."""
    index = roadmap_text.find(LEDGER_HEADING)
    if index < 0:
        raise AssertionError(f"{LEDGER_HEADING!r} not found in ROADMAP.md")
    return roadmap_text[index:]


def ledger_rows(ledger_text: str) -> tuple[tuple[str, str], ...]:
    """Return ``(row id, whole line)`` for every ROW in the LEDGER region."""
    return tuple(
        (match.group(1), line)
        for line in ledger_text.splitlines()
        if (match := ROW_RE.match(line)) is not None
    )


def cited_tags(ledger_text: str) -> tuple[tuple[str, str, int, str], ...]:
    """Return ``(row id, vocabulary, number, raw text)`` for every CITED TAG in a ROW."""
    return tuple(
        (row_id, tag.group(1), int(tag.group(2)), tag.group(0))
        for row_id, line in ledger_rows(ledger_text)
        for tag in TAG_RE.finditer(line)
    )


def present_tags(commit_subjects: str) -> frozenset[tuple[str, int]]:
    """Return the ``(vocabulary, number)`` pairs that appear in real commit subjects."""
    return frozenset(
        (match.group(1), int(match.group(2))) for match in TAG_RE.finditer(commit_subjects)
    )


def pending_tags(ledger_text: str) -> frozenset[tuple[str, int]]:
    """Return the CITED TAGS exempt from resolution: those at the MAXIMUM cited number.

    Pinned to the maximum rather than to a threshold on purpose -- see the module docstring.
    """
    tags = cited_tags(ledger_text)
    if not tags:
        return frozenset()
    newest = max(number for _, _, number, _ in tags)
    return frozenset(
        (vocabulary, number) for _, vocabulary, number, _ in tags if number == newest
    )


def unresolved_cited_tags(
    ledger_text: str, present: frozenset[tuple[str, int]]
) -> list[str]:
    """Return one message per CITED TAG that resolves to no commit subject.

    ``present`` is injected rather than measured so the contract is provable with no ``git``.
    Each message names the ROW and the offending tag text, because "a tag does not resolve"
    is useless to a maintainer who then has to find which row said it.
    """
    exempt = pending_tags(ledger_text)
    return [
        f"row #{row_id} cites `{raw}`, which appears in no commit subject"
        for row_id, vocabulary, number, raw in cited_tags(ledger_text)
        if (vocabulary, number) not in exempt and (vocabulary, number) not in present
    ]


def missing_git_precondition(
    git_on_path: bool, dot_git_present: bool, log_returncode: int
) -> str | None:
    """Name the first structural precondition the real-tree audit lacks, else ``None``.

    Pure, so behavior 7 is asserted rather than simulated. ``log_returncode`` is checked last
    because it can only be known after the first two hold; callers pass ``0`` for "not yet run".
    """
    if not git_on_path:
        return "precondition missing: `git` is not on PATH"
    if not dot_git_present:
        return f"precondition missing: no `.git` entry at the repo root ({REPO})"
    if log_returncode != 0:
        return (
            "precondition missing: `git log --format=%s` exited "
            f"{log_returncode} -- this checkout carries no history (e.g. a source zip)"
        )
    return None


def _git_subjects() -> str:
    """Return every commit subject, or ``pytest.skip`` naming the missing precondition."""
    reason = missing_git_precondition(
        shutil.which("git") is not None, (REPO / ".git").exists(), 0
    )
    if reason is not None:
        pytest.skip(reason)
    proc = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    reason = missing_git_precondition(True, True, proc.returncode)
    if reason is not None:
        pytest.skip(reason)
    return proc.stdout


def _roadmap() -> str:
    return ROADMAP.read_text(encoding="utf-8")


def _load_sibling_guard(stem: str) -> ModuleType:
    """Load a sibling test module by PATH, so this works regardless of ``sys.path``.

    Registered in ``sys.modules`` before execution because a module-level ``@dataclass``
    looks its own module up by name at import time and dies with ``AttributeError`` otherwise.
    """
    spec = importlib.util.spec_from_file_location(
        f"_iter218_sibling_{stem}", TESTS_DIR / f"{stem}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------------- behavior 1 and 2


def test_b01_the_eight_dead_factory_tags_are_gone_from_the_roadmap() -> None:
    """Behavior 1: none of the 8 retired tag strings survives anywhere in ROADMAP.md."""
    text = _roadmap()
    survivors = {tag: text.count(tag) for tag in RETIRED_TAG_STRINGS if tag in text}
    assert survivors == {}, f"dead iteration tags still cited in ROADMAP.md: {survivors}"
    assert len(RETIRED_TAG_STRINGS) == 8


def test_b02_each_relabelled_row_identifies_its_iteration_in_the_commit_vocabulary() -> None:
    """Behavior 2: rows #236-#243 keep their titles and end with exactly ``(foundry iter N)``."""
    rows = dict(ledger_rows(ledger_region(_roadmap())))
    for row_id, iteration in RELABELLED_ROW_ITERATIONS.items():
        assert row_id in rows, f"ledger row #{row_id} vanished"
        line = rows[row_id]
        expected_tail = f" (foundry iter {iteration})"
        assert line.endswith(expected_tail), f"row #{row_id} tail is not {expected_tail!r}: {line!r}"
        title = RELABELLED_ROW_TITLES[row_id]
        assert line == f"- #{row_id} {title}{expected_tail}", f"row #{row_id} title drifted: {line!r}"


def test_b02_each_relabelled_row_and_its_new_tag_occur_exactly_once() -> None:
    """Behavior 2, the uniqueness half: no row and no tag was duplicated by the relabel."""
    ledger = ledger_region(_roadmap())
    row_ids = [row_id for row_id, _ in ledger_rows(ledger)]
    for row_id, iteration in RELABELLED_ROW_ITERATIONS.items():
        assert row_ids.count(row_id) == 1, f"row #{row_id} recorded {row_ids.count(row_id)} times"
        tag = f"foundry iter {iteration}"
        rows_citing = [rid for rid, _, _, raw in cited_tags(ledger) if raw == tag]
        assert rows_citing == [row_id], f"{tag!r} cited by {rows_citing}, expected only #{row_id}"


# ----------------------------------------------------------------------------- behavior 3


def test_b03_every_cited_iteration_tag_resolves_to_a_real_commit_subject() -> None:
    """Behavior 3: the live ledger cites no tag that ``git log`` cannot show, bar PENDING."""
    ledger = ledger_region(_roadmap())
    unresolved = unresolved_cited_tags(ledger, present_tags(_git_subjects()))
    assert unresolved == [], "Done-ledger rows cite iteration tags no commit carries:\n" + "\n".join(unresolved)


# ------------------------------------------------------------------------ behaviors 4 and 5

_SYNTHETIC_LEDGER: Final[str] = "\n".join(
    (
        "## Done ledger (synthetic)",
        "",
        "Prose mentioning row #999 and factory iter 777 outside a ROW must be ignored.",
        "",
        "- #101 an older row (factory iter 50)",
        "- #102 the newest row (foundry iter 60)",
        "",
    )
)


def test_b04_the_finder_is_empty_when_every_cited_tag_is_present() -> None:
    """Behavior 4, the good side: two resolvable rows produce no findings, with no ``git``."""
    present = frozenset({("factory", 50), ("foundry", 60)})
    assert unresolved_cited_tags(_SYNTHETIC_LEDGER, present) == []


def test_b04_the_finder_names_the_row_and_the_tag_of_the_one_broken_citation() -> None:
    """Behavior 4, the bad side: change the older row's number and exactly one entry names both."""
    broken = _SYNTHETIC_LEDGER.replace("(factory iter 50)", "(factory iter 51)")
    present = frozenset({("factory", 50), ("foundry", 60)})
    findings = unresolved_cited_tags(broken, present)
    assert len(findings) == 1, findings
    assert "#101" in findings[0] and "factory iter 51" in findings[0], findings[0]


def test_b04_prose_outside_a_row_is_never_audited() -> None:
    """Behavior 4's domain: the ``factory iter 777`` in the synthetic preamble is not a ROW."""
    assert "factory iter 777" in _SYNTHETIC_LEDGER
    assert all(raw != "factory iter 777" for _, _, _, raw in cited_tags(_SYNTHETIC_LEDGER))


def test_b05_the_exemption_is_the_maximum_cited_number_not_a_large_number() -> None:
    """Behavior 5: with NOTHING present, only the numerically newest tag is exempt.

    The control that matters. The 8 tags iteration 239 repaired all sat above git's highest
    ``factory`` number, so an "exempt anything above the maximum PRESENT number" rule -- or any
    threshold -- would have reported the whole defect as clean.
    """
    ledger = _SYNTHETIC_LEDGER.replace("factory iter 50", "factory iter 9999").replace(
        "foundry iter 60", "foundry iter 10000"
    )
    findings = unresolved_cited_tags(ledger, frozenset())
    assert len(findings) == 1, findings
    assert "factory iter 9999" in findings[0], findings[0]
    assert "foundry iter 10000" not in findings[0], findings[0]
    assert pending_tags(ledger) == frozenset({("foundry", 10000)})


def test_b05_a_tie_at_the_maximum_exempts_every_tag_at_that_number() -> None:
    """Behavior 5's definition, stated exactly: PENDING is by NUMBER, across vocabularies."""
    ledger = _SYNTHETIC_LEDGER.replace("factory iter 50", "factory iter 60")
    assert pending_tags(ledger) == frozenset({("factory", 60), ("foundry", 60)})
    assert unresolved_cited_tags(ledger, frozenset()) == []


# ----------------------------------------------------------------------------- behavior 6


def test_b06_the_real_tree_audit_clears_three_counted_anti_vacuity_floors() -> None:
    """Behavior 6: prove the audit looked at something before believing its clean verdict."""
    ledger = ledger_region(_roadmap())
    present = present_tags(_git_subjects())
    rows = ledger_rows(ledger)
    tags = cited_tags(ledger)
    exempt = pending_tags(ledger)
    resolved = [t for t in tags if (t[1], t[2]) in present and (t[1], t[2]) not in exempt]
    assert len(present) >= MIN_PRESENT_TAGS, f"only {len(present)} tags parsed from git log"
    assert len(rows) >= MIN_LEDGER_ROWS, f"only {len(rows)} ledger rows parsed"
    assert len(resolved) >= MIN_RESOLVED_TAGS, f"only {len(resolved)} cited tags resolved"


# ----------------------------------------------------------------------------- behavior 7


def test_b07_the_precondition_probe_names_each_missing_precondition() -> None:
    """Behavior 7: each of the three structural preconditions yields a message naming it."""
    assert "git` is not on PATH" in str(missing_git_precondition(False, True, 0))
    assert "`.git`" in str(missing_git_precondition(True, False, 0))
    assert "no history" in str(missing_git_precondition(True, True, 128))
    assert "128" in str(missing_git_precondition(True, True, 128))


def test_b07_the_probe_returns_none_when_every_precondition_holds() -> None:
    """Behavior 7, the good side: a healthy checkout is not skipped."""
    assert missing_git_precondition(True, True, 0) is None


def test_b07_the_real_tree_probe_skips_rather_than_errors_without_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavior 7 end to end: ``_git_subjects`` raises pytest's Skipped, not an exception."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(BaseException) as caught:
        _git_subjects()
    assert caught.typename == "Skipped", caught.typename
    assert "not on PATH" in str(caught.value)


def test_b07_the_synthetic_finder_can_never_skip_or_shell_out() -> None:
    """Behavior 7's other half: behaviors 4 and 5 are pure, so they cannot skip.

    Asserted over the SOURCE of the pure functions rather than by running them, because "it
    did not skip this time" is not evidence that it cannot.
    """
    tree = ast.parse(THIS_MODULE.read_text(encoding="utf-8"))
    pure = {"cited_tags", "ledger_rows", "pending_tags", "unresolved_cited_tags", "present_tags"}
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in pure:
            seen.add(node.name)
            body = ast.dump(node)
            assert "subprocess" not in body, f"{node.name} shells out"
            assert "skip" not in body, f"{node.name} can skip"
    assert seen == pure, f"pure functions not found: {pure - seen}"


# ----------------------------------------------------------------------------- behavior 8


def test_b08_the_ledger_preamble_states_the_tag_contract_and_names_this_oracle() -> None:
    """Behavior 8: the contract lives where the next PM writes, not only in this file."""
    ledger = ledger_region(_roadmap())
    first_row = ROW_RE.search(ledger)
    assert first_row is not None
    preamble = ledger[: first_row.start()]
    assert "tests/test_iter218_behavior.py" in preamble, "the preamble does not name its oracle"
    assert "VERBATIM" in preamble
    assert "commit's subject" in preamble
    assert "`(foundry iter N)`" in preamble


# ----------------------------------------------------------------------------- behavior 9


def test_b09_this_module_audits_roadmap_md_and_nothing_else() -> None:
    """Behavior 9: the audit domain is one document -- no archive, no ``src/``, no other doc."""
    paths = {value for value in globals().values() if isinstance(value, Path)}
    assert paths == {THIS_MODULE, TESTS_DIR, REPO, ROADMAP}, sorted(str(p) for p in paths)


def test_b09_this_module_imports_no_product_code() -> None:
    """Behavior 9: a docs-and-tests iteration must not couple its oracle to ``src/``."""
    tree = ast.parse(THIS_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    assert "proactive_loop" not in imported, sorted(imported)


# ---------------------------------------------------------------------------- behavior 10


def test_b10_relabelling_is_invisible_to_the_sibling_conservation_guard() -> None:
    """Behavior 10: the conservation guard keys on ``- #N ``, which the relabel never touched."""
    conservation = _load_sibling_guard("test_roadmap_ledger_conservation")
    ledger = ledger_region(_roadmap())
    seen = set(conservation.LEDGER_BULLET.findall(ledger))
    assert set(RELABELLED_ROW_ITERATIONS) <= seen, sorted(set(RELABELLED_ROW_ITERATIONS) - seen)


def test_b10_the_roadmap_stays_inside_the_sibling_size_budget() -> None:
    """Behavior 10: the new rows and preamble sentence keep real headroom under the ceiling."""
    budget = _load_sibling_guard("test_roadmap_size_budget")
    limit = int(budget.ROADMAP_CHAR_LIMIT)
    measured = len(_roadmap())
    assert limit == 40_000, limit
    assert measured < limit, f"ROADMAP.md is {measured} chars against a {limit} ceiling"
    assert budget.settled_rows_needing_retirement(_roadmap()) == (), "a settled row needs retiring"


# ------------------------------------------------------- tester-added controls (iteration 239)
#
# Written by the TESTER stage against the spec's Expected Behaviors, black-box, in this same
# module because behavior 9 fixes the iteration's diff at exactly ``ROADMAP.md`` plus this file.
# Each one closes a hole the behaviors above leave open, and each was MEASURED against today's
# tree before being asserted (numbers quoted in this iteration's ``tester.md``).


def test_t01_behavior_4_publishes_the_signature_the_spec_names() -> None:
    """Behavior 4 states the finder is exposed as ``f(ledger_text, present) -> list[str]``.

    The behaviors above prove the finder's SEMANTICS but never its published shape, so a rename
    of either parameter -- the thing a caller in a future iteration depends on -- is invisible.
    """
    signature = inspect.signature(unresolved_cited_tags)
    assert list(signature.parameters) == ["ledger_text", "present"], signature
    assert isinstance(unresolved_cited_tags(_SYNTHETIC_LEDGER, frozenset()), list)


def test_t02_the_real_tree_audit_is_two_sided_against_real_commit_subjects() -> None:
    """Behavior 3's known-bad control, on REAL data rather than a synthetic fixture.

    ``test_b03`` asserts an EMPTY finding list, and behavior 6's counted floors only prove the
    parse was non-empty -- neither proves the finder would SPEAK UP about this tree. So plant one
    dead tag in the live ledger text (in memory; nothing is written) and require exactly one
    finding naming that row. ``foundry iter 205`` is chosen because git carries ``factory``
    1..204 and ``foundry`` 231.., so that pair is absent by construction, and it is below the
    maximum cited number, so it is not exempt as PENDING.
    """
    ledger = ledger_region(_roadmap())
    present = present_tags(_git_subjects())
    assert unresolved_cited_tags(ledger, present) == [], "precondition: the live ledger is clean"

    planted = ledger.replace("(foundry iter 231)", "(foundry iter 205)", 1)
    assert planted != ledger, "row #236 no longer cites `foundry iter 231`; re-point this control"
    findings = unresolved_cited_tags(planted, present)
    assert len(findings) == 1, findings
    assert "#236" in findings[0] and "foundry iter 205" in findings[0], findings[0]


def test_t03_every_ledger_row_cites_at_least_one_iteration_tag() -> None:
    """Anti-vacuity behavior 6 does not cover: a ROW that cites NO tag is silently unaudited.

    :data:`TAG_RE` is closed to the two vocabularies git carries today. The vocabulary has
    already switched once mid-history (``factory`` -> ``foundry``), so if it switches again a row
    reading ``(harness iter 250)`` yields zero CITED TAGS, contributes nothing to the counted
    floors, and passes every assertion above while being entirely unchecked. Requiring each ROW
    to cite something makes the next switch a loud failure instead of a silent gap.
    """
    ledger = ledger_region(_roadmap())
    rows = ledger_rows(ledger)
    tagged = {row_id for row_id, _, _, _ in cited_tags(ledger)}
    untagged = [(row_id, line) for row_id, line in rows if row_id not in tagged]
    assert untagged == [], (
        "Done-ledger rows cite no recognised iteration tag -- if the commit-subject vocabulary "
        f"changed, TAG_RE must learn the new word: {untagged}"
    )
    assert len(rows) >= MIN_LEDGER_ROWS, len(rows)


def test_t04_the_pending_exemption_cannot_be_widened_by_a_mistyped_number() -> None:
    """Behavior 5 pins the exemption to the MAXIMUM cited number, which leaves one hole open.

    Because PENDING is whatever is numerically newest, a row that mistypes its tag -- say
    ``foundry iter 2390`` -- becomes the maximum and exempts ITSELF, so the one row nobody has
    checked yet is also the one row the oracle refuses to check. Bound it: the newest cited
    number may run at most ONE ahead of the newest number git carries, which is exactly the
    same-commit race behavior 3 grants an exemption for and nothing wider.
    """
    ledger = ledger_region(_roadmap())
    present = present_tags(_git_subjects())
    tags = cited_tags(ledger)
    assert tags, "no cited tags parsed"
    newest_cited = max(number for _, _, number, _ in tags)
    newest_present = max(number for _, number in present)
    assert newest_cited <= newest_present + 1, (
        f"the ledger's newest cited iteration is {newest_cited} while git's newest is "
        f"{newest_present}: a tag more than one iteration ahead exempts itself from behavior 3"
    )
    expected_pending = frozenset(
        (vocabulary, number) for _, vocabulary, number, _ in tags if number == newest_cited
    )
    assert pending_tags(ledger) == expected_pending, pending_tags(ledger)
