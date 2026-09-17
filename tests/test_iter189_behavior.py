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
``ROADMAP_ARCHIVE.md``, ``DIRECTIONS.md``), its own synthetic strings, and three
helpers from two sibling test modules (``root_markdown_names`` and
``tracked_root_markdown`` from ``test_iter133_behavior``, ``_directions_blocks``
from ``test_iter240_behavior``). No file under ``src/`` was read, and no
engineer, reviewer or fix note was opened.

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

Factory iter 306 (roadmap row #287) EXTENDED item 8 above rather than adding any
test function or a new module, because the collected-item window was CLOSED:
``make readme-headroom`` reported ``binding_headroom=6`` on the tree this landed
on, which is exactly ``tests/test_iter263_behavior.py::MIN_BINDING_HEADROOM``,
so ONE new collected item anywhere would have redded that shipped assertion
(reopening the window means raising the published floor, which is ROADMAP row
#282 and a separate ship). Item 8 therefore also grades the ``DIRECTIONS.md``
bullet, in five arms keyed to that spec's Expected Behaviors and labelled with
those numbers in the test body: B1 the live bullet carries none of the
over-claiming phrases the log cannot deliver; B2 the SAME census, run FIRST on
the sentence this iteration deleted, returns both of them, so a clean live
result is evidence rather than a check that matches nothing; B3 every
```field:``` label the bullet quotes exists in ``DIRECTIONS.md``; B4 the log's
``iter-NNN`` blocks are measurably NON-contiguous, which is why the bullet says
"most of the commit history" rather than "every iteration"; B5 the rewrite
stayed BELOW the human-owned marker and kept its Markdown link.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import pytest

from tests.test_iter133_behavior import root_markdown_names, tracked_root_markdown

# The shipped ``iter-NNN`` block parser, imported rather than re-spelled: a second copy
# of the regex could drift from the one four shipped assertions in that module already
# grade the log with, and then the two would disagree about what a block IS.
from tests.test_iter240_behavior import _directions_blocks as directions_blocks

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
ARCHIVE = REPO_ROOT / "ROADMAP_ARCHIVE.md"
DIRECTIONS = REPO_ROOT / "DIRECTIONS.md"

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

#: Claims the ``DIRECTIONS.md`` bullet may never make again, matched case-insensitively.
#: Each one was TRUE-BY-ASSERTION only: the harness regenerates the whole log from ``##``
#: headings in state-dir notes outside this checkout, so per-iteration coverage and a
#: rejection field are shapes this repo cannot deliver however carefully it is edited.
#: Measured on the committed log at factory iter 306: 193 blocks spanning iter-92..iter-418
#: (134 of that span absent), and "reject" appears only inside candidate TITLES.
DIRECTIONS_OVERCLAIMS = (
    "one block per iteration",
    "every iteration",
    "what was rejected",
    "rejected and why",
    "why it was rejected",
)

#: Floors that keep the two live DIRECTIONS.md checks from passing by finding nothing:
#: a bullet naming one field label proves no binding, and a log parsed down to a handful
#: of blocks would satisfy the non-contiguity check arithmetically rather than factually.
MIN_DIRECTIONS_LABELS = 2
MIN_DIRECTIONS_BLOCKS = 50


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


def directions_bullet(readme_text: str) -> str:
    """The ``DIRECTIONS.md`` bullet of ``readme_text``, header line through last wrap.

    SCOPING IS THE CONTRACT, not an optimisation. A census for over-claiming phrases run
    over the whole README reds the build on an innocent neighbour: the
    ``SPEC_ARCHIVE.md`` bullet legitimately says "every iteration" about a file that
    really is rewritten every iteration. So the slice ends at the next line opening a
    sibling bullet (``- **[``) or at the next heading, and nothing outside one bullet is
    ever graded.

    Raises ``ValueError`` when the bullet is absent, because a checker that returned ""
    would report a clean census for a README that had dropped the entry entirely.
    """
    lines = readme_text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("- **[DIRECTIONS.md](")]
    if len(starts) != 1:
        raise ValueError(
            f"expected exactly one `- **[DIRECTIONS.md](` bullet, found {len(starts)}"
        )
    start = starts[0]
    end = start + 1
    while end < len(lines) and not (
        lines[end].startswith("- **[") or lines[end].startswith("#")
    ):
        end += 1
    return "\n".join(lines[start:end])


def directions_overclaims(bullet_text: str) -> list[str]:
    """Every phrase from ``DIRECTIONS_OVERCLAIMS`` that ``bullet_text`` carries.

    Case-insensitive, and returns the PHRASES rather than a bool so a failure names the
    words to delete. Pure over text, so the same function grades the live bullet and a
    synthetic one carrying the pre-change sentence -- which is what stops the live check
    from passing vacuously.
    """
    lowered = bullet_text.lower()
    return [phrase for phrase in DIRECTIONS_OVERCLAIMS if phrase in lowered]


def backticked_labels(bullet_text: str) -> list[str]:
    """Field labels the bullet names in the ```word:``` shape, in document order.

    The bullet earns the right to describe the log's contents by quoting the log's own
    field labels; this is what binds the description to the artifact. Only the
    backtick-plus-colon shape counts, so ordinary prose (or a link target such as
    ``iter-92``) can never be mistaken for a claim about a field.
    """
    return re.findall(r"`(\w+):`", bullet_text)


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


def test_b8_every_companion_bullet_that_describes_its_file_describes_it_truly() -> None:
    """The section's DESCRIPTIONS are graded, not just its links.

    Behavior 2 above proves each companion is LINKED; nothing proved the prose about it
    was TRUE, and a recruiter who follows a link is reading the prose. Two bullets make a
    checkable claim today: ``ROADMAP_ARCHIVE.md`` ("do not read it wholesale", shipped at
    factory iter 189) and, from factory iter 306, ``DIRECTIONS.md``.

    WHY THE DIRECTIONS.md HALF LIVES HERE INSTEAD OF IN A NEW MODULE. It is the same
    domain -- one bullet of this section, above/below the same marker -- and the
    collected-item window is CLOSED: ``make readme-headroom`` reports
    ``binding_headroom=6`` on the tree this lands on, which is exactly
    ``tests/test_iter263_behavior.py::MIN_BINDING_HEADROOM``, so ONE new collected item
    anywhere (a new module, or a ``test_b8b`` beside this one) reds that shipped
    assertion. Raising the published floor to reopen the window is ROADMAP row #282 and a
    separate ship. Extending an existing module for exactly this reason is this repo's own
    precedent, recorded in this file's header: ``test_iter188_behavior.py`` does not exist
    because iter-184 extended a module rather than adding one.

    The trailing ``T1``-``T4`` block is the ISOLATED tester's independent pass over the
    same five Expected Behaviors, added under the same closed window: it pins the phrase
    tuple against being emptied, proves the ban is case-insensitive, proves the
    bullet-scoping is load-bearing on the live file, and requires each quoted label to be
    a per-block field rather than a one-off word.
    """
    lines = [line for line in _readme_text().splitlines() if "](ROADMAP_ARCHIVE.md)" in line]
    assert len(lines) == 1, f"expected one ROADMAP_ARCHIVE.md link line, found {len(lines)}"
    assert "wholesale" in lines[0], (
        "the ROADMAP_ARCHIVE.md entry must tell a reader to look up one row "
        f"rather than read the whole file; it reads: {lines[0]!r}"
    )
    assert ARCHIVE.exists(), "the linked archive must exist on disk"

    # -- The census can fail. Graded FIRST, on the sentence this iteration deleted, so a
    # clean live result below is evidence rather than the absence of a working check.
    was = (
        "- **[DIRECTIONS.md](DIRECTIONS.md)** -- one block per iteration recording what "
        "was considered,\n  what was rejected and why."
    )
    caught = directions_overclaims(directions_bullet(was))
    assert "one block per iteration" in caught and "rejected and why" in caught, (
        "the phrase census must flag the pre-change sentence and name the offending "
        f"phrases; on that exact text it returned {caught}"
    )

    # -- The slice really is one bullet. Named neighbours, because a census widened to the
    # section would red on ``SPEC_ARCHIVE.md``'s legitimate "every iteration".
    bullet = directions_bullet(_readme_text())
    for neighbour in ("SPEC.md", "SPEC_ARCHIVE.md", "ROADMAP.md", "ROADMAP_ARCHIVE.md"):
        assert f"]({neighbour})" not in bullet, (
            f"the DIRECTIONS.md slice leaked into the {neighbour} bullet, so this census "
            "would grade a neighbour's wording: " + repr(bullet)
        )

    # -- Behavior 1: the live bullet claims none of the shapes the log cannot carry.
    live = directions_overclaims(bullet)
    assert live == [], (
        f"the DIRECTIONS.md bullet claims {live}, which the log does not deliver: it is "
        "regenerated wholesale by the harness from notes outside this checkout, so "
        "per-iteration coverage and a rejection field cannot be produced in-repo. Fix the "
        f"README claim: {bullet!r}"
    )

    # -- Behavior 3: every field label the bullet quotes exists in the log it describes.
    log = DIRECTIONS.read_text(encoding="utf-8")
    labels = backticked_labels(bullet)
    assert len(labels) >= MIN_DIRECTIONS_LABELS, (
        f"the bullet must quote at least {MIN_DIRECTIONS_LABELS} of the log's own "
        f"`field:` labels so the description is bound to the artifact; it quotes {labels}"
    )
    absent = [label for label in labels if f"{label}:" not in log]
    assert absent == [], (
        f"the bullet promises {absent} that DIRECTIONS.md does not contain. The in-repo "
        "fix is to correct the README claim -- never to edit DIRECTIONS.md, which the "
        "harness rewrites wholesale from state outside this checkout, so an edit there is "
        "gone next iteration."
    )

    # -- Behavior 4: per-iteration coverage is measurably false, which is WHY the bullet
    # says "most of the commit history" and not "every iteration".
    blocks = sorted(int(label) for label in directions_blocks(log))
    assert len(blocks) >= MIN_DIRECTIONS_BLOCKS, (
        f"only {len(blocks)} iter-NNN blocks parsed out of DIRECTIONS.md, below the "
        f"{MIN_DIRECTIONS_BLOCKS} floor: the non-contiguity check below would then hold "
        "arithmetically without proving anything about the log"
    )
    span = blocks[-1] - blocks[0] + 1
    assert len(blocks) < span, (
        f"DIRECTIONS.md now holds {len(blocks)} blocks across a span of {span} "
        f"(iter-{blocks[0]}..iter-{blocks[-1]}), i.e. it has become contiguous. That is "
        "not a failure of the log: it means the README claim MAY now be widened to "
        "per-iteration coverage, and this assertion re-keyed with it"
    )

    # -- Behavior 5: the rewrite stayed below the human-owned marker and kept its link.
    readme = _readme_text()
    assert readme.find("- **[DIRECTIONS.md](") > readme.find(MARKER), (
        "the DIRECTIONS.md bullet must stay BELOW the human-owned portfolio marker"
    )
    assert "](DIRECTIONS.md)" in bullet, (
        "the rewrite must keep the Markdown link, or behavior 2's unlinked_companions "
        "audit goes red on a bullet that only mentions the file"
    )

    # ======================================================================
    # INDEPENDENT TESTER PASS -- factory iter 306. Four checks the authoring round
    # does not make (T1-T4). They live INSIDE this item, not in a module of their
    # own, because the collected-item window is CLOSED: ``make readme-headroom``
    # reports ``live=5992 binding_at=5999 binding_headroom=6`` against
    # ``tests/test_iter263_behavior.py``'s ``MIN_BINDING_HEADROOM = 6``, so one new
    # ``test_`` def ANYWHERE reds a shipped assertion on a public build.
    # ======================================================================

    # -- T1: the phrase tuple cannot be emptied. Behavior 1 asserts ``census == []``,
    # which an EMPTY ``DIRECTIONS_OVERCLAIMS`` satisfies for any wording at all, so the
    # five phrases the spec names are pinned here rather than assumed.
    for phrase in (
        "one block per iteration",
        "every iteration",
        "what was rejected",
        "rejected and why",
        "why it was rejected",
    ):
        assert phrase in DIRECTIONS_OVERCLAIMS, (
            f"{phrase!r} left DIRECTIONS_OVERCLAIMS, so the live census would go green on "
            f"a bullet making that claim again; the tuple holds {DIRECTIONS_OVERCLAIMS}"
        )

    # -- T2: the ban is case-INSENSITIVE, as the spec requires. An editor who re-introduces
    # the deleted claim in title case must still be caught.
    shouted = was.replace("one block per iteration", "One Block Per Iteration")
    shouted_hits = directions_overclaims(directions_bullet(shouted))
    assert "one block per iteration" in shouted_hits, (
        "the census missed a title-cased over-claim, so the ban is spelling-sensitive "
        f"and trivially evaded; on that text it returned {shouted_hits}"
    )

    # -- T3: the bullet SCOPING is load-bearing, not an optimisation. The same census run
    # over the whole section really does fire today, because the ``SPEC_ARCHIVE.md``
    # neighbour says "every iteration" about a file that IS rewritten every iteration.
    section_hits = directions_overclaims(_project_documents_section(_readme_text()))
    assert section_hits != [], (
        "no bullet in the Project documents section carries a banned phrase any more, so "
        "the live file no longer proves that scoping this census to ONE bullet is "
        "necessary. That is not a README failure: widen the census to the section, or "
        "re-key this assertion, the day the neighbouring wording changes"
    )

    # -- T4: every label the bullet quotes is a per-block FIELD of the log, not a word that
    # happens to occur once. Measured at factory iter 306: ``lenses:`` 193, ``winner:``
    # 193, ``ship:`` 195, against 193 parsed blocks.
    frequency = {label: log.count(f"{label}:") for label in labels}
    assert min(frequency.values()) >= MIN_DIRECTIONS_BLOCKS, (
        f"a label the bullet quotes occurs fewer than {MIN_DIRECTIONS_BLOCKS} times in "
        f"DIRECTIONS.md ({frequency}), so the description is bound to a one-off word "
        "rather than to a field every block carries. The in-repo fix is the README "
        "claim, never the harness-authored log."
    )


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
