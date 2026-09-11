"""Iteration-259 black-box behavior suite (ISOLATED tester).

This iteration collapses the artifacts-dir WRITE guard that
``src/proactive_loop/loop/tools.py`` hand-copies six times into ONE private
``ToolRegistry`` helper (join + resolved-``_within`` containment gate +
verb-blamed refusal), leaving every ``_reject_unsafe`` call, every refusal
STRING and every refusal PRECEDENCE exactly where HEAD has them.

The whole risk of that change is ORDER, not wording: the ACT sandbox is the only
place in ``src/`` where a model-proposed tool call touches the filesystem, and
three of its refusal precedences are load-bearing and un-obvious ---

* ``replace_in_file`` runs its textual reject, THEN its ``old``-is-empty arg
  check, THEN the containment gate (so a bad path outranks an empty ``old``,
  but an empty ``old`` outranks a symlink escape), and
* ``move_file`` runs BOTH textual rejects before EITHER containment gate (so an
  absolute ``dst`` outranks an escaping ``src``), and blames ``src`` first when
  both sides escape.

A helper cut one line too greedily --- one that also absorbed
``_reject_unsafe`` --- keeps every refusal string byte-identical while silently
reordering those precedences, and every message-only oracle in the suite stays
green. Behaviors 4 and 5 below exist to make that specific regression a RED
build; behaviors 6 and 7 make a future open-coded seventh copy red as well.

ISOLATION CONTRACT (honored): written from this iteration's PM spec (Expected
Behaviors 1-7) plus the PUBLIC surface only. Behaviors 1-5 drive
``ToolRegistry.execute(...)`` / ``ToolRegistry.artifacts()`` and assert on
returned observation strings and on-disk state; behaviors 6-7 read the SHIPPED
module as text and reason over its ``ast`` (a census, resolved by name, never by
line number). No implementation source was read by the author, no
engineer/reviewer note was read, no ``git diff`` was consulted, nothing is
monkeypatched, and no network / provider / LLM client is constructed anywhere.
Conventions (``tmp_path`` sandboxes, the portable symlink-skip idiom, the
``REPO = Path(__file__).resolve().parents[1]`` source locator) mirror the
shipped suites ``tests/test_iter{33,35,45,66}_behavior.py`` and
``tests/test_iter233_behavior.py``.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from proactive_loop.loop.tools import ToolRegistry

REPO = Path(__file__).resolve().parents[1]
TOOLS_SRC = REPO / "src" / "proactive_loop" / "loop" / "tools.py"

#: The five handlers the spec says may consult the new write-target helper, and
#: the blame word each one must keep. ``append_file`` deliberately blames
#: ``write`` (not ``append``) and ``replace_in_file`` blames ``edit`` --- those
#: are the shipped strings, pinned by iters 33/35/45/66.
_WRITE_HANDLERS: frozenset[str] = frozenset(
    {"_write_file", "_append_file", "_remove_file", "_move_file", "_replace_in_file"}
)

#: Behavior 6 --- the write guard must not leak into the READ side, so the
#: read-side ``_within`` call count is pinned exactly: 9
#: ``self._within(candidate, root)`` plus 2 ``self._within(full, base_root)``.
#: It was 12 when this suite shipped; factory iter 296 collapsed the resolver
#: ``head_file`` and ``tail_file`` hand-copied into ONE shared private peek
#: helper, retiring one of those three copies -- the two handlers now have zero
#: ``_within`` calls of their own and the helper has one.
_READ_SIDE_WITHIN_CALLS = 11

#: Behavior 7 --- ``_move_file`` gates two paths, so five handlers make six calls.
_EXPECTED_HELPER_CALL_SITES = 6

_requires_symlink = pytest.mark.skipif(
    not hasattr(os, "symlink"),
    reason="os.symlink unavailable on this platform",
)


# --------------------------------------------------------------------------- #
# Fixtures / helpers (public surface only)                                    #
# --------------------------------------------------------------------------- #
def _sandbox(tmp_path: Path) -> tuple[ToolRegistry, Path]:
    """A ``ToolRegistry`` over two separate, existing dirs under ``tmp_path``.

    Escape targets live under ``tmp_path`` ITSELF (never under either root), so
    a symlink pointing at one genuinely resolves outside the sandbox and the
    containment gate really has to refuse it.
    """
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    workspace.mkdir()
    artifacts.mkdir()
    return ToolRegistry(workspace_root=workspace, artifacts_dir=artifacts), artifacts


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    return outside


def _link_or_skip(target: Path, link: Path) -> None:
    """``os.symlink(target, link)`` or skip cleanly if the host forbids it."""
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:  # unprivileged / unsupported
        pytest.skip(f"symlink creation not permitted on this host: {exc}")


def _snapshot(root: Path) -> dict[str, bytes | None]:
    """Recursive ``relpath -> bytes`` census of ``root`` (``None`` for dirs).

    Behavior 3 compares two of these across a batch of refusals: it catches a
    mutated byte, a created file AND a deleted one, which three separate
    ``exists()`` assertions would not.
    """
    out: dict[str, bytes | None] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        out[rel] = None if p.is_dir() else p.read_bytes()
    return out


# --------------------------------------------------------------------------- #
# Behavior 1 --- the four escape refusals keep their exact wording.            #
# --------------------------------------------------------------------------- #
@_requires_symlink
def test_b1a_write_and_append_escape_refusals_both_blame_write(tmp_path: Path) -> None:
    tools, artifacts = _sandbox(tmp_path)
    outside = _outside(tmp_path)
    (outside / "w.txt").write_bytes(b"do-not-touch\n")
    (outside / "a.txt").write_bytes(b"original\n")
    _link_or_skip(outside / "w.txt", artifacts / "wlink.txt")
    _link_or_skip(outside / "a.txt", artifacts / "alink.txt")

    obs_w = tools.execute("write_file", {"path": "wlink.txt", "content": "PWNED"})
    obs_a = tools.execute("append_file", {"path": "alink.txt", "content": "PWNED"})

    assert obs_w == "error: refusing to write outside artifacts dir: 'wlink.txt'", obs_w
    # The SAME blame word `write`, not `append` --- shipped wording, iter-35 EB3.
    assert obs_a == "error: refusing to write outside artifacts dir: 'alink.txt'", obs_a


@_requires_symlink
def test_b1b_remove_escape_refusal_blames_remove(tmp_path: Path) -> None:
    tools, artifacts = _sandbox(tmp_path)
    outside = _outside(tmp_path)
    (outside / "r.txt").write_bytes(b"keep-me\n")
    _link_or_skip(outside / "r.txt", artifacts / "rlink.txt")

    obs = tools.execute("remove_file", {"path": "rlink.txt"})

    assert obs == "error: refusing to remove outside artifacts dir: 'rlink.txt'", obs


@_requires_symlink
def test_b1c_replace_escape_refusal_blames_edit(tmp_path: Path) -> None:
    tools, artifacts = _sandbox(tmp_path)
    outside = _outside(tmp_path)
    (outside / "e.txt").write_bytes(b"alpha beta\n")
    _link_or_skip(outside / "e.txt", artifacts / "elink.txt")

    obs = tools.execute("replace_in_file", {"path": "elink.txt", "old": "alpha", "new": "PWNED"})

    assert obs == "error: refusing to edit outside artifacts dir: 'elink.txt'", obs


@_requires_symlink
def test_b1d_refusals_name_the_callers_original_relpath_not_the_resolved_one(
    tmp_path: Path,
) -> None:
    """``<path!r>`` is the ORIGINAL relative path, ``repr``-quoted.

    A refactor that blamed the RESOLVED path would leak an absolute
    out-of-sandbox filename into a model-visible observation --- a disclosure
    bug that a substring assertion on ``refusing to write`` would not notice.
    """
    tools, artifacts = _sandbox(tmp_path)
    outside = _outside(tmp_path)
    secret = outside / "outside_secret_marker.txt"
    secret.write_bytes(b"x\n")
    _link_or_skip(outside, artifacts / "dlink")  # symlinked DIR inside sandbox

    obs = tools.execute("write_file", {"path": "dlink/deep/evil.txt", "content": "PWNED"})

    assert obs == "error: refusing to write outside artifacts dir: 'dlink/deep/evil.txt'", obs
    assert "outside_secret_marker" not in obs, obs
    assert str(outside) not in obs, obs


# --------------------------------------------------------------------------- #
# Behavior 2 --- move_file blames the offending side, src before dst.          #
# --------------------------------------------------------------------------- #
@_requires_symlink
def test_b2_move_file_blames_the_offending_side_src_before_dst(tmp_path: Path) -> None:
    tools, artifacts = _sandbox(tmp_path)
    outside = _outside(tmp_path)
    (outside / "src_target.txt").write_bytes(b"src-side\n")
    (outside / "dst_target.txt").write_bytes(b"dst-side\n")
    _link_or_skip(outside / "src_target.txt", artifacts / "srclink.txt")
    _link_or_skip(outside / "dst_target.txt", artifacts / "dstlink.txt")
    # A legal, EXISTING in-sandbox src for arm (b), created through the public API.
    tools.execute("write_file", {"path": "real.txt", "content": "legal\n"})
    assert (artifacts / "real.txt").is_file(), "fixture: the legal src was not created"

    # (a) escaping src, legal (non-existent, in-sandbox) dst -> src is blamed.
    obs_src = tools.execute("move_file", {"src": "srclink.txt", "dst": "moved.txt"})
    assert obs_src == "error: refusing to move outside artifacts dir: 'srclink.txt'", obs_src

    # (b) legal EXISTING src, escaping dst -> dst is blamed.
    obs_dst = tools.execute("move_file", {"src": "real.txt", "dst": "dstlink.txt"})
    assert obs_dst == "error: refusing to move outside artifacts dir: 'dstlink.txt'", obs_dst
    assert (artifacts / "real.txt").exists(), "a refused move consumed the legal src"

    # (c) BOTH sides escape -> src is named (src's gate runs first).
    obs_both = tools.execute("move_file", {"src": "srclink.txt", "dst": "dstlink.txt"})
    assert obs_both == "error: refusing to move outside artifacts dir: 'srclink.txt'", obs_both


# --------------------------------------------------------------------------- #
# Behavior 3 --- refusal is TOTAL: nothing outside the sandbox moves.          #
# --------------------------------------------------------------------------- #
@_requires_symlink
def test_b3_every_escape_refusal_leaves_the_outside_tree_byte_identical(
    tmp_path: Path,
) -> None:
    tools, artifacts = _sandbox(tmp_path)
    outside = _outside(tmp_path)
    (outside / "w.txt").write_bytes(b"do-not-touch\n")
    (outside / "a.txt").write_bytes(b"original\n")
    (outside / "r.txt").write_bytes(b"keep-me\n")
    (outside / "e.txt").write_bytes(b"alpha beta\n")
    (outside / "mv_src.txt").write_bytes(b"src-side\n")
    (outside / "mv_dst.txt").write_bytes(b"dst-side\n")
    for name, link in (
        ("w.txt", "wlink.txt"),
        ("a.txt", "alink.txt"),
        ("r.txt", "rlink.txt"),
        ("e.txt", "elink.txt"),
        ("mv_src.txt", "srclink.txt"),
        ("mv_dst.txt", "dstlink.txt"),
    ):
        _link_or_skip(outside / name, artifacts / link)
    _link_or_skip(outside, artifacts / "dlink")  # escaping intermediate DIR
    tools.execute("write_file", {"path": "real.txt", "content": "legal\n"})

    before = _snapshot(outside)
    assert "absent.txt" not in before, before

    refusals = {
        "wlink.txt": tools.execute("write_file", {"path": "wlink.txt", "content": "PWNED"}),
        "alink.txt": tools.execute("append_file", {"path": "alink.txt", "content": "PWNED"}),
        "rlink.txt": tools.execute("remove_file", {"path": "rlink.txt"}),
        "elink.txt": tools.execute(
            "replace_in_file", {"path": "elink.txt", "old": "alpha", "new": "PWNED"}
        ),
        "dlink/absent.txt": tools.execute(
            "write_file", {"path": "dlink/absent.txt", "content": "PWNED"}
        ),
        "srclink.txt": tools.execute("move_file", {"src": "srclink.txt", "dst": "moved.txt"}),
        "dstlink.txt": tools.execute("move_file", {"src": "real.txt", "dst": "dstlink.txt"}),
    }

    for relpath, obs in refusals.items():
        assert obs.startswith("error: refusing to "), (relpath, obs)
        assert relpath not in tools.artifacts(), (relpath, tools.artifacts())

    # Same bytes if it existed, still absent if it did not --- one comparison.
    assert _snapshot(outside) == before, "the outside-the-sandbox tree changed"
    assert not (outside / "absent.txt").exists(), "a file was created outside the sandbox"


# --------------------------------------------------------------------------- #
# Behavior 4 --- replace_in_file precedence is unchanged.                      #
# --------------------------------------------------------------------------- #
def test_b4a_replace_traversal_path_outranks_the_empty_old_check(tmp_path: Path) -> None:
    tools, _artifacts = _sandbox(tmp_path)

    obs = tools.execute("replace_in_file", {"path": "../x", "old": "", "new": "y"})

    assert obs == "error: path traversal ('..') is not allowed: '../x'", obs


@_requires_symlink
def test_b4b_replace_empty_old_outranks_the_containment_gate(tmp_path: Path) -> None:
    """The ``old`` check sits BETWEEN the textual reject and the containment
    gate. A helper that absorbed ``_reject_unsafe`` would move the gate ahead of
    it and this assertion would flip to the containment message."""
    tools, artifacts = _sandbox(tmp_path)
    outside = _outside(tmp_path)
    (outside / "e.txt").write_bytes(b"alpha\n")
    _link_or_skip(outside / "e.txt", artifacts / "elink.txt")

    obs = tools.execute("replace_in_file", {"path": "elink.txt", "old": "", "new": "y"})

    assert obs == "error: replace_in_file 'old' must be non-empty", obs
    assert (outside / "e.txt").read_bytes() == b"alpha\n", "external target bytes were mutated"


# --------------------------------------------------------------------------- #
# Behavior 5 --- move_file precedence is unchanged.                            #
# --------------------------------------------------------------------------- #
@_requires_symlink
def test_b5_move_absolute_dst_outranks_an_escaping_src(tmp_path: Path) -> None:
    """BOTH textual rejects run before EITHER containment gate, so the DST's
    textual refusal outranks the SRC's containment refusal."""
    tools, artifacts = _sandbox(tmp_path)
    outside = _outside(tmp_path)
    (outside / "src_target.txt").write_bytes(b"src-side\n")
    _link_or_skip(outside / "src_target.txt", artifacts / "srclink.txt")
    abs_dst = str(tmp_path / "abs_dst.txt")

    obs = tools.execute("move_file", {"src": "srclink.txt", "dst": abs_dst})

    assert obs == f"error: absolute paths are not allowed: {abs_dst!r}", obs
    assert not Path(abs_dst).exists(), "the refused move created the absolute dst"


# --------------------------------------------------------------------------- #
# ast helpers for behaviors 6-7 (census over the SHIPPED module text)          #
# --------------------------------------------------------------------------- #
def _dotted(node: ast.AST) -> str | None:
    """``self.artifacts_dir`` -> ``"self.artifacts_dir"``; ``base_root`` ->
    ``"base_root"``; anything else -> ``None``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return None if head is None else f"{head}.{node.attr}"
    return None


def _tool_registry(source: str) -> ast.ClassDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == "ToolRegistry":
            return node
    raise AssertionError("class ToolRegistry not found in the parsed source")


def _methods(cls: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _artifacts_guard_sites(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[int, int, int]:
    """``(joins, artifacts_gates, read_gates)`` inside one method body.

    * a JOIN is ``self.artifacts_dir / <anything>``
    * an ARTIFACTS GATE is ``self._within(<x>, self.artifacts_dir)``
    * a READ GATE is any other ``self._within(<x>, <root>)``
    """
    joins = gates = reads = 0
    for node in ast.walk(method):
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and _dotted(node.left) == "self.artifacts_dir"
        ):
            joins += 1
        if isinstance(node, ast.Call) and _dotted(node.func) == "self._within":
            if len(node.args) >= 2 and _dotted(node.args[1]) == "self.artifacts_dir":
                gates += 1
            else:
                reads += 1
    return joins, gates, reads


def _calls_of(method: ast.FunctionDef | ast.AsyncFunctionDef, dotted: str) -> list[int]:
    """Sorted line numbers of every ``<dotted>(...)`` call in ``method``."""
    return sorted(
        node.lineno
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and _dotted(node.func) == dotted
    )


def _drift_census(source: str, helper: str) -> tuple[dict[str, int], tuple[str, ...]]:
    """``({handler: n_helper_calls}, (violations,))`` for one module source.

    A VIOLATION is a method that calls ``self.<helper>(...)`` without any
    ``self._reject_unsafe(...)`` call earlier in the same body --- i.e. a write
    handler that took the containment half of the two-part guard and skipped the
    textual half.
    """
    callers: dict[str, int] = {}
    violations: list[str] = []
    for method in _methods(_tool_registry(source)):
        helper_calls = _calls_of(method, f"self.{helper}")
        if not helper_calls:
            continue
        callers[method.name] = len(helper_calls)
        rejects = _calls_of(method, "self._reject_unsafe")
        if not rejects or min(rejects) > min(helper_calls):
            violations.append(method.name)
    return callers, tuple(sorted(violations))


def _the_helper(source: str) -> str:
    """Resolve, by ``ast`` and never by line number, the ONE method that owns
    the artifacts-dir join and the artifacts-dir containment gate."""
    owners = [
        m.name for m in _methods(_tool_registry(source)) if _artifacts_guard_sites(m)[:2] != (0, 0)
    ]
    assert len(owners) == 1, f"the artifacts-dir write guard lives in {owners!r}, want exactly 1"
    return owners[0]


# --------------------------------------------------------------------------- #
# Behavior 6 --- the guard has exactly ONE definition, and it is the helper's.  #
# --------------------------------------------------------------------------- #
def test_b6_the_artifacts_dir_write_guard_has_exactly_one_definition() -> None:
    source = TOOLS_SRC.read_text(encoding="utf-8")
    methods = _methods(_tool_registry(source))
    per_method = {m.name: _artifacts_guard_sites(m) for m in methods}

    total_joins = sum(v[0] for v in per_method.values())
    total_gates = sum(v[1] for v in per_method.values())
    assert total_joins == 1, f"`self.artifacts_dir / ...` joins: {total_joins}, want 1: {per_method}"
    assert total_gates == 1, (
        f"`self._within(_, self.artifacts_dir)` gates: {total_gates}, want 1: {per_method}"
    )

    owner = _the_helper(source)
    assert per_method[owner][:2] == (1, 1), (owner, per_method[owner])
    assert owner.startswith("_"), f"the write-target guard must be PRIVATE, got {owner!r}"
    assert owner not in _WRITE_HANDLERS, (
        f"the guard still lives inside handler {owner!r} instead of a shared helper"
    )

    # The READ side is Out of Scope: its count must not have moved.
    total_reads = sum(v[2] for v in per_method.values())
    assert total_reads == _READ_SIDE_WITHIN_CALLS, (
        f"read-side `_within` calls: {total_reads}, want {_READ_SIDE_WITHIN_CALLS} "
        f"(the dual-root READ resolver is Out of Scope this iteration)"
    )


# --------------------------------------------------------------------------- #
# Behavior 7 --- two-sided drift census.                                       #
# --------------------------------------------------------------------------- #
def test_b7a_every_helper_caller_still_runs_the_textual_reject_first() -> None:
    source = TOOLS_SRC.read_text(encoding="utf-8")
    helper = _the_helper(source)
    callers, violations = _drift_census(source, helper)

    assert violations == (), (
        f"{violations} call {helper!r} without an earlier `self._reject_unsafe(...)` "
        "--- the containment half of the guard was taken without the textual half"
    )
    assert set(callers) == _WRITE_HANDLERS, (
        f"{helper!r} is called from {sorted(callers)}, want {sorted(_WRITE_HANDLERS)}"
    )
    assert sum(callers.values()) == _EXPECTED_HELPER_CALL_SITES, (
        f"{helper!r} call sites: {callers} (total {sum(callers.values())}), "
        f"want {_EXPECTED_HELPER_CALL_SITES}"
    )
    assert callers["_move_file"] == 2, f"_move_file must gate BOTH paths, got {callers}"


def test_b7b_the_drift_census_has_teeth() -> None:
    """Prove the census in b7a can FAIL --- run it against a synthetic source
    whose second handler skips ``_reject_unsafe``. Without this, b7a passing is
    equally consistent with a census that reports nothing at all."""
    synthetic = '''
class ToolRegistry:
    def _resolve_write_target(self, path, *, verb):
        target = self.artifacts_dir / path
        if not self._within(target, self.artifacts_dir):
            return f"error: refusing to {verb} outside artifacts dir: {path!r}"
        return target

    def _good_file(self, args):
        bad = self._reject_unsafe(args["path"])
        if bad:
            return bad
        target = self._resolve_write_target(args["path"], verb="write")
        return str(target)

    def _drifted_file(self, args):
        target = self._resolve_write_target(args["path"], verb="write")
        return str(target)
'''
    assert _the_helper(synthetic) == "_resolve_write_target"
    callers, violations = _drift_census(synthetic, "_resolve_write_target")
    assert violations == ("_drifted_file",), violations
    assert set(callers) == {"_good_file", "_drifted_file"}, callers

    # And a reject that fires only AFTER the helper is still a violation.
    reordered = synthetic.replace(
        '        bad = self._reject_unsafe(args["path"])\n        if bad:\n            return bad\n'
        '        target = self._resolve_write_target(args["path"], verb="write")\n',
        '        target = self._resolve_write_target(args["path"], verb="write")\n'
        '        bad = self._reject_unsafe(args["path"])\n        if bad:\n            return bad\n',
    )
    assert reordered != synthetic, "the reorder fixture did not apply"
    _callers2, violations2 = _drift_census(reordered, "_resolve_write_target")
    assert violations2 == ("_drifted_file", "_good_file"), violations2
