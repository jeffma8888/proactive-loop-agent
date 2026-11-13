"""Black-box oracle for iteration 320 (foundry iter 573).

Feature under test: ``ToolRegistry._list_files`` / ``_search_files`` / ``_find_files``
resolve their sandbox directory through ONE private ``_resolve_dir_root(path)`` helper
(workspace root first, then artifacts dir; ``None`` when neither holds an in-root
directory). The change is behaviour-preserving: every tool observation stays
byte-identical to HEAD 09ead4c.

ISOLATION CONTRACT (honored): written against this iteration's spec "Expected
Behaviors" only. Behaviours 1-2 are TEXT-COUNT contracts the spec states verbatim, so
the oracle counts two literal needles in tools.py without reading its logic. Every
other assertion drives the public ``ToolRegistry.execute`` interface (plus the spec-
named ``_resolve_dir_root``). The expected strings were captured by running the SAME
fixture against a ``git archive 09ead4c`` tree (``hasattr(ToolRegistry,
"_resolve_dir_root")`` was False there) and are pinned here as literals, so the oracle
does not need git and never compares the tree against itself.

ONE collected item on purpose: the README suite-size gauge read
``binding_headroom=8`` before this module, and ``test_iter263::test_b6`` pins >= 6.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from proactive_loop.loop.tools import ToolRegistry

REPO: Final = Path(__file__).resolve().parents[1]
TOOLS_PY: Final = REPO / "src" / "proactive_loop" / "loop" / "tools.py"
ROOT_LOOP: Final = "for root in (self.workspace_root, self.artifacts_dir)"

NF: Final = "error: directory not found: {!r}"
TRAV: Final = "error: path traversal ('..') is not allowed: {!r}"

# path -> (list_files, search hit "needle", search miss, find hit "*.txt", find miss)
# Captured from HEAD 09ead4c on the fixture built by ``_fixture``.
HEAD_OBS: Final[dict[str, tuple[str, str, str, str, str]]] = {
    ".": (
        "afile.txt\nboth\nempty\nesc\ninlink\nsub\ntop.txt",
        "both/w.txt:1: needle in ws\nsub/deep/b.txt:2: needle deep",
        "(no matches for 'zzzq')",
        "afile.txt\nboth/w.txt\nsub/deep/b.txt\ntop.txt",
        "(no files matching '*.nope')",
    ),
    "both": ("w.txt", "w.txt:1: needle in ws", "(no matches for 'zzzq')", "w.txt",
             "(no files matching '*.nope')"),
    "both/": ("w.txt", "w.txt:1: needle in ws", "(no matches for 'zzzq')", "w.txt",
              "(no files matching '*.nope')"),
    "empty": ("(empty)", "(no matches for 'needle')", "(no matches for 'zzzq')",
              "(no files matching '*.txt')", "(no files matching '*.nope')"),
    "sub": ("deep", "deep/b.txt:2: needle deep", "(no matches for 'zzzq')", "deep/b.txt",
            "(no files matching '*.nope')"),
    "sub/deep": ("b.txt", "b.txt:2: needle deep", "(no matches for 'zzzq')", "b.txt",
                 "(no files matching '*.nope')"),
    "inlink": ("deep", "deep/b.txt:2: needle deep", "(no matches for 'zzzq')", "deep/b.txt",
               "(no files matching '*.nope')"),
    "artonly": ("x.md", "x.md:1: needle art only", "(no matches for 'zzzq')",
                "(no files matching '*.txt')", "(no files matching '*.nope')"),
    "missing": (NF.format("missing"),) * 5,
    "esc": (NF.format("esc"),) * 5,
    "afile.txt": (NF.format("afile.txt"),) * 5,
    "../outside": (TRAV.format("../outside"),) * 5,
    "sub/../both": (TRAV.format("sub/../both"),) * 5,
    "": ("error: empty path is not allowed",) * 5,
}


def _fixture(base: Path) -> tuple[Path, Path, Path]:
    ws, art, out = base / "workspace", base / "artifacts", base / "outside"
    for d in (ws / "both", ws / "empty", ws / "sub" / "deep", art / "both",
              art / "artonly", out):
        d.mkdir(parents=True, exist_ok=True)
    (ws / "both" / "w.txt").write_text("needle in ws\n")
    (art / "both" / "a.txt").write_text("needle in art\n")
    (art / "artonly" / "x.md").write_text("needle art only\n")
    (ws / "sub" / "deep" / "b.txt").write_text("hay\nneedle deep\n")
    (ws / "top.txt").write_text("top\n")
    (out / "secret.txt").write_text("needle secret\n")
    (ws / "esc").symlink_to(out, target_is_directory=True)  # escapes the sandbox
    (ws / "inlink").symlink_to(ws / "sub", target_is_directory=True)  # stays inside
    (ws / "afile.txt").write_text("f\n")
    return ws, art, out


def _observe(tools: ToolRegistry, path: str) -> tuple[str, str, str, str, str]:
    return (
        str(tools.execute("list_files", {"path": path})),
        str(tools.execute("search_files", {"query": "needle", "path": path})),
        str(tools.execute("search_files", {"query": "zzzq", "path": path})),
        str(tools.execute("find_files", {"pattern": "*.txt", "path": path})),
        str(tools.execute("find_files", {"pattern": "*.nope", "path": path})),
    )


def _b1_b2_structure() -> None:
    text = TOOLS_PY.read_text(encoding="utf-8")
    # B1: the root loop is owned once, inside ToolRegistry._resolve_dir_root.
    assert text.count(ROOT_LOOP) == 1, text.count(ROOT_LOOP)
    assert hasattr(ToolRegistry, "_resolve_dir_root")
    helper_at = text.index("def _resolve_dir_root(")
    next_def = text.find("\n    def ", helper_at + 1)
    body = text[helper_at:] if next_def == -1 else text[helper_at:next_def]
    assert ROOT_LOOP in body, "the root loop must live inside _resolve_dir_root"
    # B2: the pasted WHY comment survives exactly once.
    assert text.count("self-evidently correct") == 1, text.count("self-evidently correct")


def _b3_helper(tools: ToolRegistry, ws: Path, art: Path) -> None:
    assert tools._resolve_dir_root("sub") == (ws / "sub", ws)
    assert tools._resolve_dir_root("artonly") == (art / "artonly", art)
    assert tools._resolve_dir_root("both") == (ws / "both", ws), "workspace must win"
    for miss in ("missing", "afile.txt", "esc"):
        assert tools._resolve_dir_root(miss) is None, miss


def _iter578_record_artifact(base: Path) -> None:
    """Foundry iter 578 oracle (folded here: oracle budget was 0 collected items).

    ``ToolRegistry._record_artifact(rel)`` is the ONE owner of the artifact list's
    order-preserving-set rule; every mutating tool's observable return string and
    the resulting ``artifacts()`` order are unchanged. Black-box per the iter-578
    spec Expected Behaviors 1-7 (B2 is a spec-stated text census).
    """
    text = TOOLS_PY.read_text(encoding="utf-8")
    # B2: one append site, inside _record_artifact; two removals stay open-coded.
    assert text.count("self._artifacts.append(") == 1, text.count("self._artifacts.append(")
    at = text.index("def _record_artifact(")
    nxt = text.find("\n    def ", at + 1)
    assert "self._artifacts.append(" in (text[at:] if nxt == -1 else text[at:nxt])
    assert text.count("self._artifacts.remove(") == 2, text.count("self._artifacts.remove(")
    assert "mirrors write_file's dedupe" not in text

    def fresh(name: str) -> tuple[ToolRegistry, Path]:
        ws, art = base / name / "ws", base / name / "art"
        ws.mkdir(parents=True)
        art.mkdir(parents=True)
        return ToolRegistry(workspace_root=ws, artifacts_dir=art), art

    # B1: the helper dedupes in first-seen order, returns None, touches no disk.
    t1, art1 = fresh("b1")
    assert [t1._record_artifact(r) for r in ("a.txt", "b.txt", "a.txt")] == [None] * 3
    assert t1.artifacts() == ["a.txt", "b.txt"]
    assert list(art1.iterdir()) == []
    # B3/B4: write twice, append to tracked + new; return strings unchanged.
    t3, art3 = fresh("b3")
    w = {"path": "x.txt", "content": "hello"}
    assert [str(t3.execute("write_file", w)) for _ in "12"] == [
        "wrote 5 chars to artifacts/x.txt"] * 2
    assert t3.artifacts() == ["x.txt"]
    assert str(t3.execute("append_file", {"path": "x.txt", "content": "!!"})) == (
        "appended 2 chars to artifacts/x.txt")
    assert str(t3.execute("append_file", {"path": "y.txt", "content": "abc"})) == (
        "appended 3 chars to artifacts/y.txt")
    assert t3.artifacts() == ["x.txt", "y.txt"]
    # B5: tracked move drops src, records dst at the end; untracked move only appends.
    t5, art5 = fresh("b5")
    for rel in ("a.txt", "b.txt"):
        t5.execute("write_file", {"path": rel, "content": rel})
    assert str(t5.execute("move_file", {"src": "a.txt", "dst": "c.txt"})) == (
        "moved artifacts/a.txt -> artifacts/c.txt")
    assert t5.artifacts() == ["b.txt", "c.txt"]
    (art5 / "loose.txt").write_text("loose")
    t5.execute("move_file", {"src": "loose.txt", "dst": "d.txt"})
    assert t5.artifacts() == ["b.txt", "c.txt", "d.txt"]
    # B6: replace on tracked keeps count 1; on untracked on-disk file appends once.
    t6, art6 = fresh("b6")
    t6.execute("write_file", {"path": "r.txt", "content": "aa"})
    assert str(t6.execute("replace_in_file", {"path": "r.txt", "old": "a", "new": "b"})) == (
        "replaced 2 occurrence(s) in artifacts/r.txt")
    (art6 / "u.txt").write_text("zz")
    assert str(t6.execute("replace_in_file", {"path": "u.txt", "old": "z", "new": "q"})) == (
        "replaced 2 occurrence(s) in artifacts/u.txt")
    t6.execute("replace_in_file", {"path": "u.txt", "old": "q", "new": "z"})
    assert t6.artifacts() == ["r.txt", "u.txt"]
    # B7: adopt keeps tracked first, adds the rest in sorted POSIX order, idempotent.
    t7, art7 = fresh("b7")
    t7.execute("write_file", {"path": "b.txt", "content": "b"})
    (art7 / "a").mkdir()
    (art7 / "a" / "c.txt").write_text("c")
    for _ in "12":
        t7.adopt_existing_artifacts()
        assert t7.artifacts() == ["b.txt", "a/c.txt"]


def test_iter320_resolve_dir_root_contract(tmp_path: Path) -> None:
    _b1_b2_structure()
    _iter578_record_artifact(tmp_path / "iter578")
    ws, art, out = _fixture(tmp_path)
    tools = ToolRegistry(workspace_root=ws, artifacts_dir=art)
    _b3_helper(tools, ws, art)
    # B4-B7: every observation is byte-identical to HEAD 09ead4c.
    for path, expected in HEAD_OBS.items():
        assert _observe(tools, path) == expected, path
    # B6: an absolute path is rejected with HEAD's exact string by all five calls.
    absolute = str(out)
    assert _observe(tools, absolute) == (
        f"error: absolute paths are not allowed: {absolute!r}",
    ) * 5
    # B5: the same-named dir in BOTH roots lists only the workspace copy.
    assert "a.txt" not in _observe(tools, "both")[0]
    # B6: the outside-pointing symlink never leaks the outside file.
    assert all("secret" not in obs for obs in _observe(tools, "."))
