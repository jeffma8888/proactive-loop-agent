"""Black-box behavior tests for factory iteration 283 -- the two POSITION-KEYED roadmap
fixtures retire, so an iteration's own ``ROADMAP.md`` edit can no longer red a gate that
every pre-commit stage is structurally blind to.

MODULE NAME, derived from the repo and never from the state-dir counter. This is
state-dir iteration 283, while ``git ls-files tests`` tops out at
``test_iter250_behavior.py``, so the free name is ``iter251``. Proved free before writing:
``git cat-file -e HEAD:tests/test_iter251_behavior.py`` returned
``fatal: path ... does not exist in 'HEAD'``.

WHAT THIS ITERATION CLAIMS (restated from the spec so this file stands alone):

* ``tests/test_iter245_behavior.py``'s ``HISTORY_LINES`` selects its five protected
  history lines by unique CONTENT ANCHOR instead of by absolute line number, and every
  anchor's uniqueness and history-marker status is ASSERTED rather than assumed.
* ``tests/test_iter250_behavior.py``'s ``max(ids)`` newest-ledger-row pin is deleted --
  the same defect class, since it made one row's position in the ledger tail
  load-bearing and therefore reddened on the very next append.
* The re-key is behavior-preserving today and shift-immune tomorrow, and the retired
  selector is proven to BREAK on a shifted document -- an oracle proven green but never
  proven to fire is fail-open.

WHY THIS MODULE PLANTS NO ADDRESSES OF ITS OWN. The defect under test is an absolute
address into a tracked file, read at ``HEAD``. A verifier that pinned the retired
numbers in order to prove equivalence would BE the next instance of that defect, and
would red the very next iteration that retires an index row. So every claim here is
keyed to a row IDENTITY (a ledger id, an iteration tag, a marker), the equivalence with
the retired numbers was measured once by the tester and recorded in the report rather
than in a constant, and ``test_b6c`` turns the detector on this module's own source.

Black-box contract honored: this module drives file text, ``git show``, and the public
constants of the guard and of the two TEST modules under test. It reads nothing under
``src/``, no engineer or reviewer note, and no content diff.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from tests import test_iter245_behavior as subject
from tests import test_iter250_behavior as second_subject
from tests import test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parents[1]
ROADMAP = REPO / "ROADMAP.md"
ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"

SUBJECT_REL = "tests/test_iter245_behavior.py"
SECOND_SUBJECT_REL = "tests/test_iter250_behavior.py"

#: This iteration's ledger row id and iteration tag.
LEDGER_ID = "#268"
ITERATION_TAG = "(foundry iter 283)"

#: How many history fixtures each protected file must contribute, unchanged by the
#: re-key. Keyed by path, never by position in the tuple.
EXPECTED_MULTIPLICITY: dict[str, int] = {
    "ROADMAP.md": 2,
    "tests/test_iter143_behavior.py": 2,
    "tests/test_iter171_behavior.py": 1,
}

#: The IDENTITY of each protected row: a token that names the row itself, so the claim
#: "the re-key still covers the same five subjects" survives any later shift. Derived
#: from the rows the retired line numbers selected, measured once against
#: ``git show HEAD:<rel>`` at the time of the re-key.
EXPECTED_IDENTITIES: dict[str, tuple[str, ...]] = {
    "ROADMAP.md": ("- #260 ", "- #261 "),
    "tests/test_iter143_behavior.py": ("factory iter 260", "factory iter 263"),
    "tests/test_iter171_behavior.py": ("factory iter 255",),
}


def _git(*args: str) -> str:
    proc = subprocess.run(
        ("git", *args), cwd=str(REPO), capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr}"
    return proc.stdout


def _head_text(rel: str) -> str:
    return _git("show", f"HEAD:{rel}")


def _unique_line(text: str, rel: str, anchor: str) -> str:
    """The one line of ``text`` carrying ``anchor``, uniqueness ASSERTED by name."""
    hits = [line for line in text.splitlines() if anchor in line]
    assert len(hits) == 1, (
        f"the anchor {anchor!r} matches {len(hits)} line(s) of {rel}, not exactly one"
    )
    return hits[0]


def _is_history(line: str) -> bool:
    return any(marker in line for marker in guard.FLOOR_HISTORY_MARKERS)


def _ledger_rows(text: str) -> list[str]:
    """Every Done-ledger row, in document order: a top-level ``- #NNN `` bullet."""
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- #") and stripped[3:4].isdigit():
            rows.append(stripped)
    return rows


def _ledger_ids(text: str) -> list[str]:
    return [row.split()[1] for row in _ledger_rows(text)]


def _index_rows(text: str) -> list[str]:
    """Every row of the queued-work table: ``| <id> | ... |``."""
    out = []
    for line in text.splitlines():
        fields = line.split("|")
        if line.startswith("|") and len(fields) > 2 and fields[1].strip().isdigit():
            out.append(line)
    return out


def _retire_one_index_row(text: str, which: int) -> str:
    """``text`` with index row number ``which`` (0-based) deleted -- a synthetic ship.

    Pure and in-memory: the real repo is never written. This reproduces the ONE edit
    that reverted iteration 282, which no pre-commit stage can otherwise observe,
    because ``ROADMAP.md``'s index header drops a queued row once it ships.
    """
    lines = text.splitlines()
    ledger_at = next((i for i, line in enumerate(lines) if line.startswith("- #")), None)
    assert ledger_at is not None, "ROADMAP.md has no Done-ledger row"
    addresses = [
        i
        for i, line in enumerate(lines[:ledger_at])
        if line.startswith("|")
        and len(line.split("|")) > 2
        and line.split("|")[1].strip().isdigit()
    ]
    assert addresses, "ROADMAP.md has no index row above the ledger"
    at = addresses[which]
    return "\n".join(lines[:at] + lines[at + 1 :]) + "\n"


# --------------------------------------------------------------------------- AST
# The detector for the defect under test: an absolute address into a tracked file,
# read at HEAD. Pure -- it takes source TEXT, so pointing it at the live tree is the
# caller's choice rather than the instrument's dependency.


def _folded_int(node: ast.expr) -> int | None:
    """The int a constant-foldable literal expression denotes, else ``None``.

    ``106 - 1`` is a ``BinOp`` of two literals, not a bare ``Constant``, and that is
    exactly the spelling the retired selector used -- so folding is required or the
    detector reads clean on the very code it exists to catch.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, int) and not isinstance(node.value, bool) else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        inner = _folded_int(node.operand)
        if inner is None:
            return None
        return inner if isinstance(node.op, ast.UAdd) else -inner
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        left, right = _folded_int(node.left), _folded_int(node.right)
        if left is None or right is None:
            return None
        return left + right if isinstance(node.op, ast.Add) else left - right
    return None


def _reads_head(node: ast.AST) -> bool:
    """True if the expression calls ``_head_text`` (bare or attribute-qualified)."""
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            func = inner.func
            if isinstance(func, ast.Name) and func.id.endswith("_head_text"):
                return True
            if isinstance(func, ast.Attribute) and func.attr.endswith("_head_text"):
                return True
    return False


_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _scope_nodes(scope: ast.AST) -> list[ast.AST]:
    """Every node belonging to ``scope`` itself, not descending into nested scopes.

    Scoping matters: a module-wide taint set makes a local ``hits[0]`` look like an
    absolute HEAD address because some unrelated function bound the same name, and a
    detector that cries wolf gets deleted instead of obeyed.
    """
    out: list[ast.AST] = []
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(node, _NESTED_SCOPES):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


def _tainted_names(nodes: list[ast.AST], seed: set[str]) -> set[str]:
    """Names bound, transitively, to something derived from a ``_head_text`` read."""
    tainted = set(seed)
    for _ in range(8):
        grew = False
        for node in nodes:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            names = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
            if not (_reads_head(node.value) or names & tainted):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and name.id not in tainted:
                        tainted.add(name.id)
                        grew = True
        if not grew:
            break
    return tainted


def head_line_number_selectors(module_source: str) -> tuple[tuple[int, int], ...]:
    """``(lineno, index)`` for every absolute-address read of a file's HEAD text.

    A subscript of a tainted name -- or of a ``_head_text`` call chain -- by a
    constant-foldable int literal IS the retired selector, wherever it is spelled.
    """
    tree = ast.parse(module_source)
    module_nodes = _scope_nodes(tree)
    module_taint = _tainted_names(module_nodes, set())
    scopes: list[tuple[ast.AST, set[str]]] = [(tree, set())]
    scopes.extend(
        (node, module_taint)
        for node in ast.walk(tree)
        if isinstance(node, _NESTED_SCOPES)
    )
    found: set[tuple[int, int]] = set()
    for scope, seed in scopes:
        nodes = module_nodes if scope is tree else _scope_nodes(scope)
        tainted = _tainted_names(nodes, seed)
        for node in nodes:
            if not isinstance(node, ast.Subscript):
                continue
            index = _folded_int(node.slice)
            if index is None:
                continue
            value = node.value
            if (isinstance(value, ast.Name) and value.id in tainted) or _reads_head(value):
                found.add((node.lineno, index))
    return tuple(sorted(found))


def _history_lines_assignment(module_source: str) -> ast.expr:
    tree = ast.parse(module_source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "HISTORY_LINES" and node.value is not None:
                return node.value
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "HISTORY_LINES" for t in node.targets
        ):
            assert node.value is not None
            return node.value
    raise AssertionError(f"{SUBJECT_REL} no longer defines HISTORY_LINES at module level")


def _ints_in(node: ast.AST) -> list[int]:
    return [
        inner.value
        for inner in ast.walk(node)
        if isinstance(inner, ast.Constant)
        and isinstance(inner.value, int)
        and not isinstance(inner.value, bool)
    ]


def _function_source(module_source: str, name_fragment: str) -> str:
    tree = ast.parse(module_source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and name_fragment in node.name:
            segment = ast.get_source_segment(module_source, node)
            assert segment, f"could not recover the source of {node.name}"
            return segment
    raise AssertionError(f"no function whose name contains {name_fragment!r}")


def _selected(text_of: dict[str, str]) -> dict[str, list[str]]:
    """The line each fixture selects, grouped by path, uniqueness asserted per entry."""
    out: dict[str, list[str]] = {}
    for rel, anchor in subject.HISTORY_LINES:
        out.setdefault(rel, []).append(_unique_line(text_of[rel], rel, anchor))
    return out


# --------------------------------------------------------------------------- b1


def test_b1a_the_fixture_holds_five_entries_over_the_same_three_files() -> None:
    """Behavior 1: shape and multiplicity are preserved by the re-key."""
    fixture = subject.HISTORY_LINES
    assert isinstance(fixture, tuple)
    assert len(fixture) == 5, f"HISTORY_LINES holds {len(fixture)} entries, expected 5"
    census: dict[str, int] = {}
    for entry in fixture:
        assert isinstance(entry, tuple) and len(entry) == 2, f"malformed entry: {entry!r}"
        census[entry[0]] = census.get(entry[0], 0) + 1
    assert census == EXPECTED_MULTIPLICITY, (
        f"the re-key changed which files are protected: {census} != {EXPECTED_MULTIPLICITY}"
    )


def test_b1b_no_element_of_any_entry_is_an_int() -> None:
    """Behavior 1: the second element of every pair is a ``str``, never a number."""
    for rel, anchor in subject.HISTORY_LINES:
        assert isinstance(rel, str), f"the path element {rel!r} is not a str"
        assert isinstance(anchor, str), (
            f"the selector for {rel} is {type(anchor).__name__} {anchor!r}, not a str; "
            "a history fixture must name its line, never its address"
        )
        assert anchor.strip(), f"the anchor for {rel} is blank"


def test_b1c_the_fixture_source_contains_no_int_literal() -> None:
    """Behavior 1 and 6, read off the shipping source rather than the imported value."""
    source = _head_text(SUBJECT_REL) if _subject_is_committed() else _worktree(SUBJECT_REL)
    ints = _ints_in(_history_lines_assignment(source))
    assert ints == [], f"HISTORY_LINES still spells the line number(s) {ints}"


def _worktree(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _subject_is_committed() -> bool:
    """True once the re-key is in ``HEAD`` -- in a fresh clone at the shipping commit."""
    return "HISTORY_LINES: tuple[tuple[str, str], ...]" in _head_text(SUBJECT_REL)


# --------------------------------------------------------------------------- b2


@pytest.mark.parametrize(("rel", "anchor"), subject.HISTORY_LINES)
def test_b2a_every_anchor_selects_exactly_one_line_of_its_file_at_head(
    rel: str, anchor: str
) -> None:
    """Behavior 2: measured independently of the subject's own selector."""
    hits = [line for line in _head_text(rel).splitlines() if anchor in line]
    assert len(hits) == 1, (
        f"the anchor {anchor!r} matches {len(hits)} line(s) of {rel} at HEAD; a history "
        "fixture must name its line unambiguously"
    )


def test_b2b_a_two_match_anchor_is_reported_by_name_not_silently_accepted() -> None:
    """Behavior 2: the count is ASSERTED. Driven on a synthetic duplicated document."""
    rel, anchor = subject.HISTORY_LINES[0]
    line = _unique_line(_head_text(rel), rel, anchor)
    doubled = f"{line}\n{line}\n"
    with pytest.raises(AssertionError) as caught:
        subject._select_history_line(doubled, rel, anchor)
    message = str(caught.value)
    assert anchor in message and rel in message, (
        f"the 2-match failure names neither the file nor the anchor: {message!r}"
    )


def test_b2c_a_zero_match_anchor_is_reported_by_name() -> None:
    """Behavior 2: the other side of the count, also asserted rather than assumed."""
    rel = "ROADMAP.md"
    anchor = "an anchor that occurs in no document"
    with pytest.raises(AssertionError) as caught:
        subject._select_history_line("nothing to see here\n", rel, anchor)
    message = str(caught.value)
    assert anchor in message and rel in message


# --------------------------------------------------------------------------- b3


@pytest.mark.parametrize(("rel", "anchor"), subject.HISTORY_LINES)
def test_b3a_every_anchored_line_still_reads_as_bump_history(rel: str, anchor: str) -> None:
    """Behavior 3: the fixture-sanity check that caught iteration 282 is retained."""
    line = _unique_line(_head_text(rel), rel, anchor)
    assert _is_history(line), (
        f"{rel}: the line anchored by {anchor!r} carries none of "
        f"{guard.FLOOR_HISTORY_MARKERS}, so the fixture points at the wrong row: {line!r}"
    )


def test_b3b_an_anchor_landing_on_a_marker_free_line_fails() -> None:
    """Behavior 3: the sanity check FIRES, so it is not decoration."""
    rel, anchor = "ROADMAP.md", "a marker free row"
    with pytest.raises(AssertionError) as caught:
        subject._select_history_line(f"- #999 {anchor} (foundry iter 1)\n", rel, anchor)
    assert "history marker" in str(caught.value)


# --------------------------------------------------------------------------- b4


@pytest.mark.parametrize(("rel", "anchor"), subject.HISTORY_LINES)
def test_b4a_the_head_line_survives_verbatim_in_the_worktree(rel: str, anchor: str) -> None:
    """Behavior 4: the protective half of the retired test is unchanged in effect."""
    expected = _unique_line(_head_text(rel), rel, anchor)
    assert expected in _worktree(rel).splitlines(), (
        f"the history line in {rel} anchored by {anchor!r} was re-keyed or deleted; it "
        f"reads {expected!r} at HEAD and no line matches it in the worktree"
    )


@pytest.mark.parametrize(("rel", "anchor"), subject.HISTORY_LINES)
def test_b4b_an_edited_or_deleted_history_line_still_fails(
    rel: str, anchor: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behavior 4: the shipped oracle is driven against a TAMPERED worktree.

    ``HEAD`` is supplied from the real repo and only the worktree root is redirected,
    so the comparison under test is the real one; a tmp copy keeps the repo unmutated.
    """
    head_text = {r: _head_text(r) for r, _ in subject.HISTORY_LINES}
    victim = _unique_line(head_text[rel], rel, anchor)
    for other in {r for r, _ in subject.HISTORY_LINES}:
        target = tmp_path / other
        target.parent.mkdir(parents=True, exist_ok=True)
        text = _worktree(other)
        if other == rel:
            text = "\n".join(ln for ln in text.splitlines() if ln != victim) + "\n"
        target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(subject, "REPO", tmp_path)
    monkeypatch.setattr(subject, "_head_text", lambda r: head_text[r])
    with pytest.raises(AssertionError) as caught:
        subject.test_b8_bump_history_lines_are_not_re_keyed(rel, anchor)
    message = str(caught.value)
    assert rel in message and victim in message, (
        f"the deletion failure quotes neither the file nor the line: {message!r}"
    )


# --------------------------------------------------------------------------- b5


def test_b5a_the_anchor_selector_is_immune_to_a_retirement_above_it() -> None:
    """Behavior 5(a): the same row text, before and after a synthetic index-row ship."""
    head = _head_text("ROADMAP.md")
    shifted = _retire_one_index_row(head, 0)
    assert len(shifted.splitlines()) == len(head.splitlines()) - 1
    for rel, anchor in subject.HISTORY_LINES:
        if rel != "ROADMAP.md":
            continue
        assert _unique_line(shifted, rel, anchor) == _unique_line(head, rel, anchor), (
            f"the anchor {anchor!r} selects a different row once a row above it retires"
        )


def test_b5b_the_retired_absolute_selector_breaks_on_the_same_document() -> None:
    """Behavior 5(b): the address the old fixture held now lands on a NON-history line.

    The address is DERIVED from the row it used to select -- writing the number down
    here would make this proof the next instance of the defect it certifies.
    """
    head = _head_text("ROADMAP.md")
    head_lines = head.splitlines()
    shifted_lines = _retire_one_index_row(head, 0).splitlines()
    roadmap_anchors = [a for r, a in subject.HISTORY_LINES if r == "ROADMAP.md"]
    addresses = [head_lines.index(_unique_line(head, "ROADMAP.md", a)) for a in roadmap_anchors]
    victim_at = max(addresses)
    before, after = head_lines[victim_at], shifted_lines[victim_at]
    assert _is_history(before), (
        f"vacuous proof: ROADMAP.md line {victim_at + 1} is not a history line at HEAD"
    )
    assert after != before, "the synthetic retirement did not move the deepest fixture"
    assert not _is_history(after), (
        f"line {victim_at + 1} still reads as history after a one-row retirement, so "
        f"the retired selector would not have broken: {after!r}"
    )


def test_b5c_the_subjects_own_proof_passes_and_mutates_no_file() -> None:
    """Behavior 5: the shipped proof test runs green and leaves the tree clean."""
    before = _git("status", "--porcelain")
    subject.test_b8c_the_anchor_selector_is_shift_immune_where_the_line_number_was_not()
    assert _git("status", "--porcelain") == before, (
        "the shift-immunity proof mutated the working tree; it must be built in memory"
    )


def test_b5d_the_rekey_survives_every_future_index_row_retirement() -> None:
    """Behavior 5 and 10, swept forward: the fix is proven for the NEXT commits too.

    Every pre-commit stage reads ``HEAD``, where the retired fixture also passed, so
    green in-tree is not evidence. This drives the SHIPPED selector over one synthetic
    future per retirable index row -- including the row iteration 284's re-land retires
    -- plus this iteration's own appended ledger row.
    """
    head = _head_text("ROADMAP.md")
    expected = {
        anchor: subject._select_history_line(head, rel, anchor)
        for rel, anchor in subject.HISTORY_LINES
        if rel == "ROADMAP.md"
    }
    total = len(_index_rows(head))
    assert total > 1, "ROADMAP.md has no queued-work table to retire rows from"
    futures = 0
    for which in range(total):
        future = _retire_one_index_row(head, which)
        appended = future + "- #999 a later iteration records itself -> here (foundry iter 999)\n"
        for document in (future, appended):
            futures += 1
            for anchor, want in expected.items():
                got = subject._select_history_line(document, "ROADMAP.md", anchor)
                assert got == want, (
                    f"future document {futures}: the anchor {anchor!r} selected "
                    f"{got!r}, not the row it selects at HEAD"
                )
    assert futures == total * 2


def test_b5e_the_three_test_module_anchors_are_shift_immune_too() -> None:
    """Behavior 5, widened to the fixtures that do NOT live in ``ROADMAP.md``.

    ``b5a``, ``b5b`` and ``b5d`` all synthesise their shift inside ``ROADMAP.md``,
    so three of the five re-keyed fixtures were never actually shift-tested -- and
    an edit above a docstring line in a test module moves them exactly as invisibly
    as an index-row retirement moved the ledger. Three futures per fixture: a line
    inserted above it, a line deleted above it, and a line appended below it.
    """
    swept = 0
    for rel, anchor in subject.HISTORY_LINES:
        if rel == "ROADMAP.md":
            continue
        head = _head_text(rel)
        want = _unique_line(head, rel, anchor)
        assert _is_history(want), f"{rel}: the anchored line is not history at HEAD"
        lines = head.splitlines()
        at = lines.index(want)
        assert at > 0, f"{rel}: nothing can shift a fixture on the first line"
        futures = {
            "a line inserted above it": lines[:at] + ["# synthetic edit"] + lines[at:],
            "a line deleted above it": lines[: at - 1] + lines[at:],
            "a line appended below it": lines + ["# synthetic tail"],
        }
        for label, future in futures.items():
            got = _unique_line("\n".join(future) + "\n", rel, anchor)
            assert got == want, (
                f"{rel}: after {label} the anchor {anchor!r} selects {got!r} rather "
                f"than {want!r}, so the re-key did not survive the shift"
            )
            swept += 1
    assert swept == 9, f"expected three futures for each of three fixtures, swept {swept}"


# --------------------------------------------------------------------------- b6


def test_b6a_the_subject_holds_no_surviving_absolute_head_address() -> None:
    """Behavior 6: no expression indexes a HEAD text by an int literal."""
    source = _head_text(SUBJECT_REL) if _subject_is_committed() else _worktree(SUBJECT_REL)
    offenders = head_line_number_selectors(source)
    assert offenders == (), (
        f"{SUBJECT_REL} still reads a HEAD text by absolute address at "
        + "; ".join(f"line {lineno} index {index}" for lineno, index in offenders)
    )


def test_b6b_the_detector_fires_on_the_retired_spelling() -> None:
    """Behavior 6: the census is not vacuous -- it catches both retired spellings."""
    guilty = (
        "def f(rel):\n"
        "    head_lines = _head_text(rel).splitlines()\n"
        "    victim = head_lines[106 - 1]\n"
        "    direct = _head_text(rel).splitlines()[41]\n"
        "    return victim, direct\n"
    )
    offenders = head_line_number_selectors(guilty)
    assert sorted(index for _, index in offenders) == [41, 105], offenders


def test_b6c_this_verifier_plants_no_address_of_its_own() -> None:
    """The reviewer's lesson, self-applied: the fix for a position-keyed fixture must
    not smuggle a new one into its own proof."""
    own = Path(__file__).read_text(encoding="utf-8")
    assert head_line_number_selectors(own) == ()
    assert _ints_in(_history_lines_assignment(_worktree(SUBJECT_REL))) == []


def test_b6d_the_detector_ignores_an_int_that_is_not_an_address() -> None:
    """A byte SIZE or a tuple index is not the defect; over-reach would be a nuisance."""
    innocent = (
        "SIZES = ((\"big.py\", 4096),)\n"
        "def f(rel):\n"
        "    head_lines = _head_text(rel).splitlines()\n"
        "    return head_lines[head_lines.index(SIZES[0][0])]\n"
    )
    assert head_line_number_selectors(innocent) == ()


# --------------------------------------------------------------------------- b7


def test_b7a_the_newest_row_pin_is_gone_from_the_second_subject() -> None:
    """Behavior 7: no claim about the ledger TAIL survives, in text or in the AST."""
    source = _worktree(SECOND_SUBJECT_REL)
    assert "max(ids)" not in source, f"{SECOND_SUBJECT_REL} still pins the ledger tail"
    body = _function_source(source, "test_b10")
    calls = [
        node.func.id
        for node in ast.walk(ast.parse(body.strip()))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "max" not in calls, "test_b10 still calls max() on the ledger ids"


def test_b7b_every_other_assertion_of_that_test_survives() -> None:
    """Behavior 7: the enumerated claims are still made, not deleted with the pin."""
    body = _function_source(_worktree(SECOND_SUBJECT_REL), "test_b10")
    for claim in (
        "set(ids)",
        "(foundry iter 281)",
        "267",
        "->",
        "floor_claim_lines",
        "PUBLISHED_FLOOR_CARRIERS",
        "MIN_HEADROOM",
    ):
        assert claim in body, f"test_b10 no longer asserts {claim!r}"


def test_b7c_that_test_still_passes_as_written() -> None:
    """Behavior 7: driven, not read -- the surviving assertions are all green."""
    second_subject.test_b10_the_roadmap_records_the_raise_once_and_stays_inside_its_budget()


def test_b7d_the_row_is_selected_by_identity_so_a_later_append_cannot_move_it() -> None:
    """Behavior 7: the reason the pin had to go, asserted rather than described.

    Ledger ids are not monotonic here, so "newest" was never a property of the
    maximum, and this iteration's own append is what the retired pin would have red.
    """
    roadmap = _worktree("ROADMAP.md")
    ids = [int(row_id.lstrip("#")) for row_id in _ledger_ids(roadmap)]
    assert ids != sorted(ids), (
        "ledger ids are monotonic after all, so this rationale needs restating"
    )
    body = _function_source(_worktree(SECOND_SUBJECT_REL), "test_b10")
    tags = sorted(set(re.findall(r"\(foundry iter \d+\)", body)))
    assert len(tags) == 1, f"test_b10 pins {len(tags)} iteration tags: {tags}"
    pinned = [row for row in _ledger_rows(roadmap) if tags[0] in row]
    assert len(pinned) == 1, f"expected one row tagged {tags[0]}"
    pinned_id = int(pinned[0].split()[1].lstrip("#"))
    assert pinned_id != max(ids), (
        f"the row the surviving test selects is still the maximum id {pinned_id}, so "
        "the retired tail pin would pass by luck and its removal is unproven"
    )


def test_b7e_the_second_subject_plants_no_absolute_head_address_either() -> None:
    """Behaviors 6 and 7 are ONE defect class, so both subjects meet the detector.

    Behavior 6 names only ``test_iter245_behavior.py``, but ``max(ids)`` is the proof
    that position-keyed roadmap fixtures were never confined to that module. Measured
    on the SHIPPING text rather than on ``HEAD``: reading ``HEAD`` here would make the
    verifier blind to the very commit it certifies.
    """
    source = _worktree(SECOND_SUBJECT_REL)
    offenders = head_line_number_selectors(source)
    assert offenders == (), (
        f"{SECOND_SUBJECT_REL} indexes a HEAD text by an absolute address at "
        f"line(s) {[lineno for lineno, _ in offenders]}"
    )


# --------------------------------------------------------------------------- b8


def test_b8a_the_roadmap_records_this_iteration_exactly_once() -> None:
    """Behavior 8: one row, this id, this tag."""
    roadmap = _worktree("ROADMAP.md")
    rows = [row for row in _ledger_rows(roadmap) if row.startswith(f"- {LEDGER_ID} ")]
    assert len(rows) == 1, f"expected exactly one {LEDGER_ID} ledger row, found {len(rows)}"
    assert ITERATION_TAG in rows[0], f"the {LEDGER_ID} row does not cite {ITERATION_TAG}"
    tagged = [row for row in _ledger_rows(roadmap) if ITERATION_TAG in row]
    assert len(tagged) == 1, f"{ITERATION_TAG} appears on {len(tagged)} ledger rows"


def test_b8b_row_ids_stay_unique_across_the_document_pair() -> None:
    """Behavior 8: uniqueness spans the live roadmap and its archive."""
    live = _ledger_ids(_worktree("ROADMAP.md"))
    archived = _ledger_ids(_worktree("ROADMAP_ARCHIVE.md"))
    assert len(live) == len(set(live)), "a ledger id is used twice in ROADMAP.md"
    collisions = sorted(set(live) & set(archived))
    assert collisions == [], f"ids recorded in both documents: {collisions}"


def test_b8c_no_pre_existing_ledger_row_was_edited_reordered_or_deleted() -> None:
    """Behavior 8: the HEAD ledger is an unbroken PREFIX of the shipping one."""
    head_rows = _ledger_rows(_head_text("ROADMAP.md"))
    live_rows = _ledger_rows(_worktree("ROADMAP.md"))
    if any(row.startswith(f"- {LEDGER_ID} ") for row in head_rows):
        assert live_rows == head_rows, "running at the shipping commit: the ledger moved"
        return
    assert live_rows[: len(head_rows)] == head_rows, (
        "a pre-existing ledger row was edited, reordered or deleted"
    )
    assert len(live_rows) == len(head_rows) + 1, (
        f"the ledger went {len(head_rows)} -> {len(live_rows)}; one iteration is one row"
    )
    assert live_rows[-1].startswith(f"- {LEDGER_ID} "), "the new row is not appended last"


def test_b8d_no_index_row_was_retired_this_iteration() -> None:
    """Behavior 8: minimum shift -- the queued-work table is byte-for-byte the same."""
    assert _index_rows(_worktree("ROADMAP.md")) == _index_rows(_head_text("ROADMAP.md")), (
        "an index row was retired, which is the shift this iteration exists to survive"
    )


def test_b8e_the_archive_is_byte_unchanged() -> None:
    """Behavior 8: no relocation rode along with the append."""
    assert _worktree("ROADMAP_ARCHIVE.md") == _head_text("ROADMAP_ARCHIVE.md"), (
        "ROADMAP_ARCHIVE.md changed; this iteration relocates nothing"
    )
    assert f"- {LEDGER_ID} " not in _worktree("ROADMAP_ARCHIVE.md")
    assert ITERATION_TAG not in _worktree("ROADMAP_ARCHIVE.md")


# --------------------------------------------------------------------------- b9


def test_b9_the_append_leaves_the_mandated_headroom() -> None:
    """Behavior 9: measured with the owning modules' constants, never a re-typed bound.

    The ceiling is DERIVED because a second opinion on one document's size is exactly
    what ``tests/test_iter172_behavior.py`` censuses for.
    """
    from tests import test_iter214_behavior as headroom_owner
    from tests import test_roadmap_size_budget as budget_owner

    roadmap = _worktree("ROADMAP.md")
    verdict = budget_owner.check_char_budget(roadmap)
    assert verdict.ok, verdict.message
    headroom = headroom_owner.CHAR_LIMIT - len(roadmap)
    assert headroom >= headroom_owner.MIN_HEADROOM, (
        f"ROADMAP.md leaves {headroom} chars of headroom, under the floor "
        f"{headroom_owner.MIN_HEADROOM}; relocate at least what this iteration added "
        "into ROADMAP_ARCHIVE.md in the SAME commit"
    )


# -------------------------------------------------------------------------- b10


def test_b10a_the_rekey_covers_the_same_five_subjects_by_identity() -> None:
    """Behavior 10: behavior-preserving, expressed as row IDENTITY not row address."""
    text_of = {rel: _head_text(rel) for rel, _ in subject.HISTORY_LINES}
    selected = _selected(text_of)
    assert sorted(selected) == sorted(EXPECTED_MULTIPLICITY)
    for rel, expected_count in EXPECTED_MULTIPLICITY.items():
        lines = selected[rel]
        assert len(lines) == expected_count
        assert len(set(lines)) == expected_count, (
            f"{rel}: two fixtures collapsed onto the same line {lines}"
        )
        for identity in EXPECTED_IDENTITIES[rel]:
            carriers = [line for line in lines if identity in line]
            assert len(carriers) == 1, (
                f"{rel}: {len(carriers)} of the selected lines carry the identity "
                f"{identity!r}, expected exactly one; the re-key changed its subject"
            )


def test_b10b_this_iteration_touches_no_source_or_dependency_file() -> None:
    """Behavior 10 and the acceptance criteria: a tests-and-prose change only.

    Keyed on the iteration tag rather than on ``HEAD~1`` so it stays true in a later
    clone. No content diff is read -- only the shipping file list.
    """
    subjects = _git("log", "--format=%H %s", "-n", "200").splitlines()
    sha = next((line.split(" ", 1)[0] for line in subjects if ITERATION_TAG in line), None)
    if sha is None:
        names = [
            line[3:].strip() for line in _git("status", "--porcelain").splitlines() if line.strip()
        ]
        assert names, "no shipping commit and a clean tree: nothing to measure"
    else:
        names = _git("show", "--name-only", "--format=", sha).split()
    forbidden = [
        name
        for name in names
        if name.startswith("src/") or name in {"pyproject.toml", "uv.lock", "README.md", "Makefile"}
    ]
    assert forbidden == [], f"out-of-scope files in this iteration: {forbidden}"
