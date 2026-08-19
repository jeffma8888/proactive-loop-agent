"""Black-box oracle for factory iteration 189 (state dir ``iter-185``).

Feature under test: ``README.md`` gains one ``## Project documents`` section
BELOW the human-owned portfolio marker, linking every tracked root-level
companion document, guarded by a check whose domain is DERIVED from
``git ls-files`` rather than hardcoded.

Why the guard is the point, not the section
Before this iteration the README linked exactly two non-anchor targets
(``LICENSE`` and one relative ``target`` inside a code sample) and mentioned
``SPEC.md``, ``ROADMAP.md``, ``ROADMAP_ARCHIVE.md`` and ``DIRECTIONS.md`` ZERO
times each -- roughly half a megabyte of committed design contract, live
backlog, archive and per-iteration decision log reachable only by browsing the
file tree and guessing. On a public portfolio repo those are the artifacts that
show the loop *reasons* rather than merely commits. The finding had also been
derived twice (iter-184 scout B3, iter-185 scout A1) and recorded as a roadmap
row neither time, so a one-off docs edit would rot the same way: this module is
what makes a future companion document impossible to add unlinked.

MODULE NAME. This repo names behavior modules by the FACTORY iteration number,
which runs ahead of the state-dir counter; state dir 185 ships as factory 189,
and ``tests/test_iter188_behavior.py`` does not exist because iter-184 extended
an existing module instead of adding one. Confirmed before writing: the highest
present module was ``test_iter187_behavior.py``, so nothing here overwrites a
shipped oracle (the trap ``test_iter187_behavior.py`` recorded in its own
docstring).

WHY THE DOMAIN COMES FROM GIT AND NOT FROM A GLOB, and why that is not a
hardcoded tuple either. Two root-level Markdown files on this machine
(``README_TOP.md``, ``LINKEDIN_POST.md``) are excluded through
``.git/info/exclude``, a per-clone UNCOMMITTED mechanism: they are absent from a
fresh clone and from CI, so a glob-derived domain would red the build on exactly
one machine (the failure mode the 2026-08-11 operator lesson records). A git
domain excludes them BY CONSTRUCTION. Equally, a pinned 4-tuple would pass green
the day a fifth companion is committed unlinked, which is the whole defect being
guarded. So the domain is derived, and the derivation is REUSED by import from
``tests/test_iter133_behavior.py`` rather than re-parsed here -- a second parser
is a second thing that can disagree.

DEGRADE CONTRACT, inherited rather than invented. Where git cannot say what is
tracked (a tarball export, no git binary) ``tracked_root_markdown`` SKIPS with a
stated reason, and its docstring reasons that out: a guard that silently audited
NOTHING there would report health while examining zero files. This module does
not add a second, contradictory rule that fails instead. The vacuity worry is
answered on the other side, the shape ``test_iter144_behavior.py`` already uses:
when git DOES answer, the derived domain is asserted non-empty and >= 4 members,
so a truncated-but-successful listing cannot make the link assertion pass by
finding nothing to check.

Isolation: black-box. This module reads the artifacts under test (``README.md``,
``ROADMAP_ARCHIVE.md``), its own synthetic strings, and two helpers from a
sibling test module. No file under ``src/`` was read, and no engineer, reviewer
or fix note was opened.

Offline and deterministic: pure string work plus the ONE read-only
``git ls-files`` call the reused helper already makes. No network, no clock, no
writes. Nothing asserts on docstring or help-text indentation, so the 3.12/3.13
matrix legs cannot diverge here.

Coverage (numbered to match this iteration's spec "Expected Behaviors"):

1. Exactly one ``## Project documents`` heading, strictly below the marker.
2. Every name in the git-derived domain is linked below the marker -- the
   assertion iterates the DERIVED set, never a literal list.
3. Non-vacuity and degrade: the domain is >= 4 members when git answers, and
   ``tracked_root_markdown`` skips where git cannot answer.
4. Known-BAD control: 3 of 4 companions linked -> exactly the missing one.
5. Known-GOOD control: all 4 linked -> ``[]``.
6. A link ABOVE the marker does not count as linking.
7. A README with NO marker raises ``ValueError`` instead of treating the whole
   file as below-marker.
8. The archive entry tells a reader to look up one row rather than read it
   wholesale.
9. The published-surface landmarks the intro carve-out depends on are intact,
   and no companion link leaked ABOVE the marker.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from tests.test_iter133_behavior import root_markdown_names, tracked_root_markdown

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
ARCHIVE = REPO_ROOT / "ROADMAP_ARCHIVE.md"

#: The marker comment is spelled with an EM DASH ("PORTFOLIO INTRO — human-owned"),
#: so match only the ASCII-safe prefix: an ASCII ``--`` spelling finds nothing and
#: every above/below-marker check would then fail OPEN while appearing to pass.
MARKER = "PORTFOLIO INTRO"

#: The new navigation section.
SECTION_HEADING = "## Project documents"

#: The smallest credible derived domain. Four companions are tracked today; a
#: successful-but-truncated listing that returned fewer would otherwise let
#: behavior 2 pass by finding nothing to check.
MIN_DOMAIN = 4

#: Names known today. Used ONLY in failure messages and as a floor check -- never
#: as the thing asserted, because a pinned list passes green the day a fifth
#: companion lands unlinked.
KNOWN_COMPANIONS = ("DIRECTIONS.md", "ROADMAP.md", "ROADMAP_ARCHIVE.md", "SPEC.md")


# --------------------------------------------------------------------------
# The checker: pure, total, no filesystem, no subprocess, no clock.
# --------------------------------------------------------------------------


def unlinked_companions(readme_text: str, domain: Iterable[str]) -> list[str]:
    """Names in ``domain`` that ``readme_text`` does not link BELOW the marker.

    Pure over the TEXT rather than over the repo, because that is the only way
    both sides of the rule are provable: the live README is (after this
    iteration) a known-GOOD sample only, so a known-BAD sample has to be
    synthetic, and a checker that read the file itself could not accept one.

    A name counts as linked only via the exact Markdown target ``](<name>)``.
    Matching the closing parenthesis is what keeps ``ROADMAP.md`` from being
    satisfied by ``](ROADMAP_ARCHIVE.md)``, and what keeps a bare prose mention
    of a filename from counting as navigation.

    Placement is part of the contract, not decoration: only occurrences at an
    offset past the human-owned marker count, since the intro above it is frozen
    and an automated contributor may not put the section there.

    Raises ``ValueError`` when the marker is absent. A missing marker means the
    caller is not looking at this project's README, and the alternative --
    treating offset 0 as "below the marker" -- would silently accept a link
    anywhere in the file, which is exactly the check being asked for.
    """
    marker_at = readme_text.find(MARKER)
    if marker_at < 0:
        raise ValueError(
            f"no {MARKER!r} marker in the given text: without it there is no "
            "above/below boundary to enforce, and defaulting to offset 0 would "
            "silently accept a link above the human-owned intro"
        )
    missing = [
        name for name in domain if readme_text.find(f"]({name})", marker_at) < 0
    ]
    return sorted(missing)


def companion_domain(names: Iterable[str]) -> list[str]:
    """``names`` minus the README itself, sorted.

    The README cannot be a companion of itself, and requiring it to link to
    itself would be a self-satisfying assertion.
    """
    return sorted({name for name in names if name != "README.md"})


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _synthetic(linked: Iterable[str], *, above: Iterable[str] = (), marker: bool = True) -> str:
    """A minimal README-shaped string: links ``above`` the marker, then ``linked``.

    Hand-built rather than derived from the live file so that behaviors 4-7 stay
    true no matter what the real README later says.
    """
    head = ["# Fixture", ""]
    head += [f"- [{name}]({name})" for name in above]
    if marker:
        head += ["", f"<!-- {MARKER} — human-owned -->", ""]
    head += [SECTION_HEADING, ""]
    head += [f"- [{name}]({name})" for name in linked]
    return "\n".join(head) + "\n"


# ==========================================================================
# Behavior 1 -- exactly one section, strictly below the human-owned marker.
# ==========================================================================


def test_b1_project_documents_section_sits_once_below_the_marker() -> None:
    text = _readme_text()
    assert text.count(SECTION_HEADING) == 1, (
        f"expected exactly one {SECTION_HEADING!r} heading, found "
        f"{text.count(SECTION_HEADING)}"
    )
    marker_at = text.find(MARKER)
    assert marker_at > 0, "README must still carry the human-owned marker"
    assert text.find(SECTION_HEADING) > marker_at, (
        f"{SECTION_HEADING!r} must sit BELOW the human-owned marker (offset "
        f"{marker_at}); it is at {text.find(SECTION_HEADING)}"
    )


# ==========================================================================
# Behavior 2 -- every tracked root companion is linked, domain DERIVED.
# ==========================================================================


def test_b2_every_tracked_root_companion_is_linked_below_the_marker() -> None:
    domain = companion_domain(tracked_root_markdown())

    # Anti-vacuity FIRST: an empty or truncated listing would make the
    # assertion below pass for the wrong reason.
    assert domain, "git listed no root *.md companions -- the guard would pass vacuously"
    assert len(domain) >= MIN_DOMAIN, (
        f"the derived companion domain is {domain}, fewer than {MIN_DOMAIN} -- a "
        f"truncated listing, not a shrinking repo (known today: "
        f"{list(KNOWN_COMPANIONS)})"
    )

    missing = unlinked_companions(_readme_text(), domain)
    assert missing == [], (
        f"README.md links no {missing} below the human-owned marker. Every "
        f"tracked root-level companion document must be reachable from the front "
        f"door; add it to the {SECTION_HEADING!r} section."
    )


# ==========================================================================
# Behavior 3 -- the degrade is the repo's settled one: skip, not fail.
# ==========================================================================


def test_b3_domain_skips_rather_than_audits_nothing_without_git(tmp_path: Path) -> None:
    """A tarball export has no index; auditing nothing there is worse than a skip.

    ``tmp_path`` rather than a parent of the checkout: the parent directory of a
    clone is a machine-dependent precondition (it could itself be a repo on
    someone else's box), and a test that passes only on this machine is not a
    test.
    """
    with pytest.raises(pytest.skip.Exception):
        tracked_root_markdown(root=tmp_path)


def test_b3b_derivation_drops_nested_paths_and_keeps_root_names() -> None:
    """The reused parser, exercised on a synthetic listing rather than the tree."""
    listing = "SPEC.md\nREADME.md\nexamples/fixture_workspace/README.md\n\n"
    assert root_markdown_names(listing) == ["README.md", "SPEC.md"]
    assert companion_domain(root_markdown_names(listing)) == ["SPEC.md"]


# ==========================================================================
# Behaviors 4-7 -- two-sided proof on synthetic strings.
# ==========================================================================


def test_b4_known_bad_reports_exactly_the_missing_companion() -> None:
    text = _synthetic(linked=[n for n in KNOWN_COMPANIONS if n != "DIRECTIONS.md"])
    assert unlinked_companions(text, KNOWN_COMPANIONS) == ["DIRECTIONS.md"]


def test_b5_known_good_reports_nothing() -> None:
    assert unlinked_companions(_synthetic(linked=KNOWN_COMPANIONS), KNOWN_COMPANIONS) == []


def test_b6_a_link_above_the_marker_does_not_count() -> None:
    """This is what makes behavior 2's "below the marker" clause enforceable."""
    text = _synthetic(
        linked=[n for n in KNOWN_COMPANIONS if n != "SPEC.md"], above=["SPEC.md"]
    )
    assert "](SPEC.md)" in text, "the fixture must really contain the above-marker link"
    assert unlinked_companions(text, KNOWN_COMPANIONS) == ["SPEC.md"]


def test_b6b_a_prefix_of_another_target_does_not_satisfy_a_name() -> None:
    """``](ROADMAP_ARCHIVE.md)`` must not be read as linking ``ROADMAP.md``."""
    text = _synthetic(linked=["ROADMAP_ARCHIVE.md"])
    assert unlinked_companions(text, ["ROADMAP.md"]) == ["ROADMAP.md"]


def test_b7_a_readme_without_the_marker_is_a_hard_failure() -> None:
    text = _synthetic(linked=KNOWN_COMPANIONS, marker=False)
    assert MARKER not in text
    with pytest.raises(ValueError, match=MARKER):
        unlinked_companions(text, KNOWN_COMPANIONS)


# ==========================================================================
# Behavior 8 -- the archive entry sets the reader's expectation.
# ==========================================================================


def test_b8_the_archive_entry_says_not_to_read_it_wholesale() -> None:
    lines = [line for line in _readme_text().splitlines() if "](ROADMAP_ARCHIVE.md)" in line]
    assert len(lines) == 1, f"expected one ROADMAP_ARCHIVE.md link line, found {len(lines)}"
    assert "wholesale" in lines[0], (
        "the ROADMAP_ARCHIVE.md entry must tell a reader to look up one row "
        f"rather than read the whole file; it reads: {lines[0]!r}"
    )
    assert ARCHIVE.exists(), "the linked archive must exist on disk"


# ==========================================================================
# Behavior 9 -- nothing above the marker moved, landmarks intact.
# ==========================================================================


def test_b9_no_companion_link_leaked_above_the_marker() -> None:
    text = _readme_text()
    intro = text[: text.find(MARKER)]
    leaked = [name for name in KNOWN_COMPANIONS if f"]({name})" in intro]
    assert leaked == [], (
        f"{leaked} are linked ABOVE the human-owned marker; the intro is frozen "
        "and the navigation section belongs below it"
    )
    assert text.count("## CLI") == 1, "the CLI reference heading must stay unique"
    assert text.count(MARKER) == 1, "the marker must stay unique"


# ==========================================================================
# TESTER additions -- the live pair, and proof the domain is not pinned.
#
# Behaviors 4-7 above prove the checker two-sided over SYNTHETIC strings, and
# behavior 2 proves the live README currently satisfies it. Neither of those
# shows that the pair actually in use -- the DERIVED domain against the REAL
# README -- would name a regression, and that is the pair the build depends on.
# A guard proven only on hand-written fixtures can still be wired to the wrong
# inputs and pass forever; these three assertions close that gap.
# ==========================================================================


def _link_targets(text: str) -> list[str]:
    """Every Markdown link target in ``text``, in document order.

    Written with ``str.find`` rather than a regex on purpose: the section under
    test is a handful of lines, a scan is exact, and it avoids adding an import
    to a module whose header is already settled.
    """
    targets: list[str] = []
    at = text.find("](")
    while at >= 0:
        close = text.find(")", at + 2)
        if close < 0:
            break
        targets.append(text[at + 2 : close])
        at = text.find("](", close)
    return targets


def _project_documents_section(text: str) -> str:
    """The new section only, from its heading to the next same-level heading."""
    start = text.find(SECTION_HEADING)
    assert start >= 0, f"{SECTION_HEADING!r} is absent from README.md"
    end = text.find("\n## ", start + len(SECTION_HEADING))
    return text[start : end if end >= 0 else len(text)]


def _derived_domain() -> list[str]:
    """The domain behavior 2 actually audits, with its vacuity floor applied."""
    domain = companion_domain(tracked_root_markdown())
    assert len(domain) >= MIN_DOMAIN, (
        f"the derived companion domain is {domain}, fewer than {MIN_DOMAIN} -- "
        "a truncated listing, so the assertions below would be vacuous"
    )
    return domain


def test_t1_the_derived_domain_and_the_live_readme_are_a_two_sided_pair() -> None:
    """Delete one real link from the real README: the real domain must name it.

    This is the known-BAD control for the pair the build depends on. Behavior 4
    proves the checker on a fixture and a literal list; here both inputs are the
    live ones, so a checker accidentally wired to a stale constant, or a domain
    that silently lost a member, is caught rather than reported green.
    """
    domain = _derived_domain()
    text = _readme_text()
    victim = domain[0]
    broken = text.replace(f"]({victim})", "](#)")
    assert broken != text, (
        f"the live README links no {victim!r}, so there was nothing to break -- "
        "behavior 2 should already have failed"
    )
    assert unlinked_companions(broken, domain) == [victim], (
        f"removing the only {victim!r} link must make the guard report exactly "
        f"[{victim!r}]; it reported {unlinked_companions(broken, domain)}"
    )


def test_t2_the_domain_is_derived_so_a_fifth_companion_cannot_arrive_unlinked() -> None:
    """The defect being guarded is a FUTURE unlinked companion, not today's four.

    A pinned 4-tuple passes green the day a fifth tracked document lands, which
    is precisely the rot that lost this finding twice. Simulating that fifth
    member proves the guard's verdict follows the domain it is handed.
    """
    domain = _derived_domain()
    newcomer = "ZZ_UNLINKED_COMPANION.md"
    assert newcomer not in domain, "the simulated newcomer must not really be tracked"
    text = _readme_text()
    assert f"]({newcomer})" not in text, "the simulated newcomer must not really be linked"
    assert unlinked_companions(text, [*domain, newcomer]) == [newcomer], (
        f"a tracked-but-unlinked {newcomer!r} must be reported; the guard said "
        f"{unlinked_companions(text, [*domain, newcomer])}"
    )


def test_t3_the_new_section_links_no_untracked_or_duplicated_document() -> None:
    """The front door must not point at a file a fresh clone does not have.

    Behavior 2 checks the direction "every tracked companion is linked". This is
    the other direction, the shape the repo already uses for CLI flags (a
    documented flag that exists on no parser is a ghost): a root-level ``*.md``
    target in this section that git does not track would render as a dead link
    on the public repo page. Scoped to root-level names, so a future link into a
    subdirectory is not a false red.
    """
    tracked = set(tracked_root_markdown())
    assert len(tracked) >= MIN_DOMAIN, f"truncated listing: {sorted(tracked)}"
    section = _project_documents_section(_readme_text())
    targets = [
        target
        for target in _link_targets(section)
        if target.endswith(".md") and "/" not in target and "://" not in target
    ]
    assert targets, (
        f"the {SECTION_HEADING!r} section links no documents at all -- it exists "
        "to be navigation"
    )
    ghosts = sorted({target for target in targets if target not in tracked})
    assert ghosts == [], (
        f"{ghosts} are linked from {SECTION_HEADING!r} but git does not track "
        f"them; a fresh clone would render a dead link (tracked: {sorted(tracked)})"
    )
    assert len(targets) == len(set(targets)), (
        f"the section links the same document twice: {targets}"
    )
