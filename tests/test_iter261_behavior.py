"""Black-box behavior oracle for the factory iteration that completes ``SPEC.md``
``## 2. Layout`` and retires roadmap row #231.

Feature under test (independent of the guard that ships with it): section 2's fence is
the repo's orientation map, and it published a project with no CI, no commit hook, no
decision log and no lockfile -- 9 of 16 tracked top-level entries -- one line under a
``Makefile`` comment that named 4 of 10 real recipes and hid ``typecheck`` and
``check-matrix``, the two recipes that ARE this repo's published quality bar. This
module re-derives BOTH rosters from their live sources and re-checks the fence against
them, so it fails whether the fence rots or the sibling guard stops looking.

Why ONE test function rather than one per behavior: the collected-suite window
(``published_floor() + 98``) had four items of room when this landed and the increment's
own guard cases took two, so this oracle spends ONE item and orders its assertions
load-bearing first. Each block is labelled with the spec behavior it grades and carries
its own message, so a failure names the behavior without a second case.

Everything asserted here is DERIVED at run time -- from ``git ls-files``, from
``Makefile``'s target lines, from ``git show HEAD:<file>`` and from the fence itself --
never from a literal roster, and no suite-size token is spelled anywhere in this file
(a module that wrote one would flag itself in the floor-carrier census).

Pre-commit and post-commit are BOTH green by construction: every HEAD-relative
assertion is guarded by a committed/uncommitted discriminator (does ``HEAD``'s
``ROADMAP.md`` already carry this row's ledger line), because an oracle that compares
the worktree against ``git show HEAD:`` inverts the moment the commit lands and is then
red in every fresh clone -- the failure mode that reverted a green iteration once.

ISOLATION CONTRACT (honored): written strictly from this iteration's spec (``pm.md``
Expected Behaviors 1-12 and its Acceptance Criteria) plus the conventions of the
existing modules under ``tests/``. **No file under ``src/`` was read, no engineer /
reviewer / fix note was opened, and no ``git diff`` CONTENT was consulted** -- the one
``git diff`` invocation below is ``--name-only`` and is asserted EMPTY, i.e. it is a
no-runtime-change probe that reveals nothing about any implementation.

Offline and deterministic: reads three tracked text files, runs read-only ``git``
commands in this repo, and touches no mtime, no network and no ``tmp_path`` tree, so it
behaves identically in a fresh clone.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Final

import tests.test_spec_layout_contract as layout_guard

REPO: Final[Path] = Path(__file__).resolve().parents[1]
SPEC: Final[Path] = REPO / "SPEC.md"
MAKEFILE: Final[Path] = REPO / "Makefile"
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"
README: Final[Path] = REPO / "README.md"

#: The roadmap row this increment retires.
ROW: Final[str] = "231"

LAYOUT_HEADING: Final[str] = "## 2. Layout"

#: Wall-clock ceiling on each read-only ``git`` call: a hang under ``-n auto`` costs the
#: whole suite, not one case.
GIT_TIMEOUT: Final[int] = 60

#: The ``(foundry iter N)`` tag shape the Done ledger and the commit subject share.
TAG_RE: Final[re.Pattern[str]] = re.compile(r"\(foundry iter (\d+)\)")

#: The pre-fix ``Makefile`` fence line, as the negative control for behavior 5(b). Kept
#: as a literal on purpose: its return must be a RED build, not a matter of memory.
PRE_FIX_MAKEFILE_LINE: Final[str] = "Makefile                  # setup / test / demo / clean targets"

#: The false purity claim the same commit had to correct (behavior 11). Matched as a
#: PATTERN so the docstring may still QUOTE the retracted words while retracting them.
FALSE_PURITY_CLAIM: Final[re.Pattern[str]] = re.compile(r"no\s+network,\s*no\s+subprocess", re.I)


def _git(*args: str) -> str:
    """Run one read-only ``git`` command in the repo and return its stdout.

    Fails closed with a NAMED message: a guard that cannot read the index must red
    rather than pass over an empty answer.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except OSError as exc:  # git absent or REPO unreadable
        raise AssertionError(f"could not run `git {' '.join(args)}` in {REPO}: {exc}") from exc
    assert proc.returncode == 0, (
        f"`git {' '.join(args)}` exited {proc.returncode}; every roster below is derived "
        f"from git, so an unreadable index must fail rather than pass vacuously. "
        f"stderr tail: {proc.stderr.strip()[-200:]!r}"
    )
    return proc.stdout


def _head_text(path: str) -> str:
    """The parent commit's copy of *path*."""
    return _git("show", f"HEAD:{path}")


def _layout_fence(text: str) -> str:
    """The body of the single fenced block inside ``## 2. Layout``, extracted here.

    Deliberately a SECOND implementation rather than a call into the shipping guard: an
    oracle that borrows the extractor it is grading cannot detect a broken slice.
    """
    start = text.index(LAYOUT_HEADING)
    rest = text[start + len(LAYOUT_HEADING) :]
    end = rest.find("\n## ")
    section = rest if end < 0 else rest[:end]
    parts = section.split("```")
    assert len(parts) >= 3, f"{LAYOUT_HEADING} holds no closed fenced block"
    fence = parts[1]
    assert len(fence) > 1_000, f"suspiciously short {LAYOUT_HEADING} fence: {len(fence)} chars"
    return fence


def _tracked_top_level() -> dict[str, bool]:
    """Every tracked top-level entry mapped to whether it is a directory.

    Derived from the git index, so untracked and gitignored paths are invisible by
    construction -- no ambient local state, identical in a fresh clone.
    """
    roster: dict[str, bool] = {}
    for line in _git("ls-files").splitlines():
        if not line:
            continue
        head, _, rest = line.partition("/")
        roster[head] = roster.get(head, False) or bool(rest)
    assert len(roster) > 1, "`git ls-files` yielded no usable roster; fix the oracle"
    return roster


def _tracked_children(prefix: str) -> dict[str, bool]:
    """The tracked children of ``<prefix>/`` mapped to whether each is a directory."""
    children: dict[str, bool] = {}
    for line in _git("ls-files", "--", prefix).splitlines():
        tail = line[len(prefix) + 1 :]
        name, _, rest = tail.partition("/")
        if name:
            children[name] = children.get(name, False) or bool(rest)
    assert children, f"no tracked child under {prefix}/; fix the oracle"
    return children


def _spelling(entry: str, is_dir: bool) -> str:
    """How the tree must name *entry*: ``name/`` for a directory, else ``name``."""
    return f"{entry}/" if is_dir else entry


def _missing(fence: str, roster: dict[str, bool]) -> list[str]:
    """Every roster member the fence fails to name, in sorted order."""
    return sorted(
        _spelling(name, is_dir)
        for name, is_dir in roster.items()
        if _spelling(name, is_dir) not in fence
    )


def _top_level_only(fence: str) -> str:
    """*fence* with every indented line dropped: the top level and nothing else."""
    return "\n".join(
        line for line in fence.splitlines() if not line.startswith((" ", "\u2502"))
    )


def _live_recipes() -> set[str]:
    """Every recipe name declared by a target line in ``Makefile``."""
    names = set(
        re.findall(r"^([A-Za-z][\w-]*):", MAKEFILE.read_text(encoding="utf-8"), re.M)
    )
    assert len(names) > 1, "parsed no recipe roster out of Makefile; fix the oracle"
    return names


def _named_recipes(line: str, recipes: set[str]) -> set[str]:
    """The recipes *line* names as WHOLE tokens (``check`` is a prefix of ``check-matrix``)."""
    return recipes & set(re.findall(r"[A-Za-z][\w-]*", line))


def _sole_line(fence: str, needle: str) -> str:
    """The one fence line containing *needle*."""
    hits = [line for line in fence.splitlines() if needle in line]
    assert len(hits) == 1, f"expected exactly one fence line naming {needle!r}, got {len(hits)}"
    return hits[0]


def _nonblank_lines(text: str) -> list[str]:
    """The non-blank lines of *text*: the unit the archive-conservation check uses."""
    return [line for line in text.splitlines() if line.strip()]


def _test_defs(text: str) -> int:
    return len(re.findall(r"^def test_", text, re.M))


def test_b01_layout_rosters_are_complete_and_row_231_retires() -> None:
    """Spec behaviors 1-12: both rosters complete, both controls fire, row #231 retired."""
    spec_text = SPEC.read_text(encoding="utf-8")
    fence = _layout_fence(spec_text)
    roster = _tracked_top_level()

    # Behavior 1 -- zero omissions from the tracked top-level roster.
    missing = _missing(fence, roster)
    assert not missing, (
        f"{LAYOUT_HEADING} names {len(roster) - len(missing)} of {len(roster)} tracked "
        f"top-level entries; missing {missing}. The fence is the orientation map, so an "
        f"omission publishes a project that does not have the thing."
    )

    # Behavior 2 -- the exempt set is declared, EMPTY, and documented as needing no
    # `.gitignore`-class carve-out.
    exempt = getattr(layout_guard, "TOP_LEVEL_EXEMPT", None)
    assert exempt is not None, "the guard must DECLARE its top-level exemption container"
    assert set(exempt) == set(), f"the roster contract must ship with no carve-out; got {sorted(exempt)}"
    guard_doc = layout_guard.__doc__ or ""
    assert ".gitignore" in guard_doc and "TOP_LEVEL_EXEMPT" in guard_doc, (
        "the guard docstring must say why no `.gitignore` carve-out exists"
    )

    # Behavior 3 -- depth scoping: emptying every sub-tree leaves behavior 1 green, which
    # is what licenses `src/proactive_loop/` to elide its modules behind the 4.1 pointer.
    assert not _missing(_top_level_only(fence), roster), (
        "the top-level contract must hold with every sub-tree emptied, or it is silently "
        "asserting depth it declared out of scope"
    )

    # Behavior 4 -- the Makefile fence line is EMPTY-or-COMPLETE against the live roster.
    recipes = _live_recipes()
    make_line = _sole_line(fence, "Makefile")
    hidden = recipes - _named_recipes(make_line, recipes)
    assert not hidden, (
        f"the fence's Makefile line names {len(recipes) - len(hidden)} of {len(recipes)} "
        f"live recipes and hides {sorted(hidden)}; a strict non-empty subset reads as the "
        f"whole roster, so it must name every recipe or none beyond a `make help` pointer"
    )

    # Behavior 5(a) -- one surgical deletion from the live fence reds behavior 1, and the
    # verdict names the deleted entry.
    control_entry = ".github/"
    doctored = fence.replace(_sole_line(fence, control_entry), "")
    assert control_entry in _missing(doctored, roster), (
        f"deleting the {control_entry} line must red the roster contract"
    )
    # Behavior 5(b) -- the exact shipped line is caught hiding the quality-bar recipes.
    pre_fix_hidden = recipes - _named_recipes(PRE_FIX_MAKEFILE_LINE, recipes)
    assert {"typecheck", "check-matrix"} <= pre_fix_hidden, (
        f"the pre-fix Makefile line must be caught hiding the quality bar; got {sorted(pre_fix_hidden)}"
    )

    # Behavior 6 -- fail-closed, never skipped: no skip machinery anywhere in the guard.
    guard_text = (REPO / "tests" / "test_spec_layout_contract.py").read_text(encoding="utf-8")
    for banned in ("pytest.skip", "skipif", "importorskip"):
        assert banned not in guard_text, f"the roster guard must never {banned}: it must fail closed"

    # Behavior 7 -- examples/ is completed too (prose only, declared unguarded by depth).
    for child, is_dir in _tracked_children("examples").items():
        assert _spelling(child, is_dir) in fence, (
            f"the fence omits tracked examples/{_spelling(child, is_dir)}, which row #{ROW} names"
        )

    # Behavior 8 -- the roadmap record: index row gone, ONE archive retirement bullet,
    # ONE Done-ledger line whose tag is the shipping commit's own tag.
    roadmap = ROADMAP.read_text(encoding="utf-8")
    archive = ARCHIVE.read_text(encoding="utf-8")
    assert not re.search(rf"(?m)^\| {ROW} \|", roadmap), f"row #{ROW} must leave the queued index"
    bullets = re.findall(rf"(?m)^- \*\*#{ROW} -- .*$", archive)
    assert len(bullets) == 1, f"expected exactly one `- **#{ROW} -- ` retirement bullet, got {len(bullets)}"
    assert "|" not in bullets[0], "the retirement bullet must replace pipes with field labels"
    for label in ("LAYER:", "VALUE:", "RISK:", "SOURCE:", "STATUS:"):
        assert label in bullets[0], f"the retirement bullet must carry the {label} field label"
    ledger = re.findall(rf"(?m)^- #{ROW} .*$", roadmap)
    assert len(ledger) == 1, f"expected exactly one `- #{ROW} ` Done-ledger record, got {len(ledger)}"

    head_roadmap = _head_text("ROADMAP.md")
    head_tag = TAG_RE.search(_git("log", "-1", "--format=%s"))
    assert head_tag is not None, "HEAD's commit subject must carry a `(foundry iter N)` tag"
    committed = re.search(rf"(?m)^- #{ROW} ", head_roadmap) is not None
    expected_tag = f"(foundry iter {int(head_tag.group(1)) + (0 if committed else 1)})"
    assert expected_tag in ledger[0], (
        f"the Done-ledger record must be tagged {expected_tag} -- the tag the shipping "
        f"commit's subject carries, never a second private counter; got {ledger[0]!r}"
    )
    archived_at_head = _nonblank_lines(_head_text("ROADMAP_ARCHIVE.md"))
    assert archived_at_head, "the archive is never empty at HEAD; fix the oracle"
    lost = [line for line in archived_at_head if line not in archive]
    assert not lost, f"the archive lost {len(lost)} line(s) it held at HEAD: {lost[0][:100]!r}"

    # Behavior 9 -- the increment BUYS ratchet room, measured in the ratchet's own unit
    # (``len()`` over DECODED text: the file holds multibyte characters, so a shell byte
    # count reads higher and would call a passing file red). The baseline is DERIVED from
    # the parent commit rather than spelled as a literal, for two independent reasons:
    # a literal would (i) freeze a number that every future retirement moves, and (ii) red
    # `tests/test_iter172_behavior.py`'s size-bound census, which lets only its enumerated
    # allowlist bound `len(ROADMAP.md)` and only at a sanctioned integer.
    baseline_chars = len(head_roadmap)
    if committed:
        # The shipping commit has landed, so `HEAD` IS this tree: equality is the only
        # truthful reading, and asserting the reduction again here would invert the case
        # in every fresh clone. The permanent ceiling is owned elsewhere, not here.
        assert len(roadmap) == baseline_chars, (
            f"ROADMAP.md is {len(roadmap)} chars in the worktree but {baseline_chars} at "
            f"HEAD, which already carries row #{ROW}'s ship record: the file moved after "
            f"the commit that was graded"
        )
    else:
        assert len(roadmap) < baseline_chars, (
            f"ROADMAP.md is {len(roadmap)} chars; retiring row #{ROW} must leave it "
            f"strictly under the {baseline_chars} it holds at the parent commit, i.e. the "
            f"increment must BUY ratchet room rather than borrow against it"
        )

    # Behavior 10 -- the suite window and every published number hold: at most 3 new test
    # functions in the guard, no parametrize, README byte-unchanged.
    new_cases = _test_defs(guard_text) - _test_defs(_head_text("tests/test_spec_layout_contract.py"))
    assert new_cases <= 3, f"the guard added {new_cases} collected items; the window allows 3"
    assert "parametrize" not in guard_text, "no parametrize on the new cases (it multiplies items)"
    assert README.read_text(encoding="utf-8") == _head_text("README.md"), (
        "no README number changes in this increment"
    )

    # Behavior 11 -- the guard's own docstring stays true now that it shells out to git.
    assert FALSE_PURITY_CLAIM.search(guard_doc) is None, (
        "the guard docstring still claims `no network, no subprocess` while deriving the "
        "roster from `git ls-files`"
    )
    assert "git ls-files" in guard_doc, "the docstring must name the read-only git call it makes"

    # Behavior 12 -- no runtime change (names only, asserted empty; never diff content).
    changed_src = _git("diff", "--name-only", "HEAD", "--", "src").split()
    assert not changed_src, f"this increment must not touch src/; changed {changed_src}"

    # Behavior 8, durable arm -- retiring an index row moves the retirement-census total in
    # ``tests/test_iter214_behavior.py`` by exactly +1, a literal that module's own comment
    # and failure message DESIGN to move ("bump this literal by one and say which row").
    # A sibling guard that quotes the PRE-retirement value as a STRING therefore reds every
    # future sanctioned retirement, whichever iteration performs it -- the same class of
    # defect as the ledger-id pin whose return ``tests/test_iter258_behavior.py::test_ac1``
    # forbids. So: the census assertion must EXIST, and no other module may quote a total
    # other than the live one. Both halves are derived; no total is spelled in this file.
    iter214_text = (REPO / "tests" / "test_iter214_behavior.py").read_text(encoding="utf-8")
    census = re.search(r"sum\(counts\.values\(\)\) == (\d+)", iter214_text)
    assert census is not None, (
        "tests/test_iter214_behavior.py no longer asserts a retirement-bullet total, which "
        f"is the census proving row #{ROW}'s archive retirement bullet landed at all"
    )
    live_total = census.group(1)
    stale_pins: list[str] = []
    for module in sorted((REPO / "tests").glob("test_*.py")):
        if module.name == Path(__file__).name:
            continue
        text = module.read_text(encoding="utf-8")
        if "tests/test_iter214_behavior.py" not in text:
            continue
        stale_pins += [
            f"{module.name} quotes '== {quoted}'"
            for quoted in re.findall(r'"== (\d+)"', text)
            if quoted != live_total
        ]
    assert not stale_pins, (
        f"the live retirement-census total is {live_total}, but these modules freeze an "
        f"older one and so red every future row retirement: {stale_pins}"
    )
