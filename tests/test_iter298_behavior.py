"""Black-box behavior oracle for foundry iter 549: content memos key on sha256[:16].

Module name DERIVED FROM THE REPO, not from the state dir: the highest tracked
``tests/test_iterNN_behavior.py`` was 297, and ``git cat-file -e
HEAD:tests/test_iter298_behavior.py`` FAILED before this file was written.

Feature under test: the todos, merge_conflict, syntax_error and broken_link
content memos key on ``hashlib.sha256(text.encode("utf-8")).digest()[:16]``
instead of ``hashlib.blake2b(..., digest_size=16)``. Signal output must not move.

TWO collected items, on purpose: ``make readme-headroom`` read
``binding_headroom=6`` and the spec caps this module at two items.

* ``test_memo_keys_are_sha256_prefix`` covers EB1-3 as an in-function loop over
  the four modules; every assert message names its module.
* ``test_census_no_blake2b_call_one_sha256_call`` covers EB4 on code, not prose
  (an ``ast`` walk over each collector source, so a docstring mentioning blake2b
  as history cannot trip it).

No timing assertion: durations are nondeterministic (spec Out of Scope).
"""

from __future__ import annotations

import ast
import hashlib
import importlib
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parents[1] / "src" / "proactive_loop" / "collectors"

# (module, memo attr, clear fn, stats fn, collector class, file name, file text)
CASES: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    ("todos", "_TODO_MEMO", "clear_todo_memo", "todo_memo_stats",
     "TodoCollector", "a.py", "# TODO: x\n"),
    ("merge_conflict", "_MARKER_MEMO", "clear_merge_conflict_memo",
     "merge_conflict_memo_stats", "MergeConflictCollector", "a.txt", "hello\n"),
    ("syntax_error", "_PARSE_MEMO", "clear_parse_memo", "parse_memo_stats",
     "SyntaxErrorCollector", "a.py", "x = 1\n"),
    ("broken_link", "_BROKEN_LINK_MEMO", "clear_broken_link_memo",
     "broken_link_memo_stats", "BrokenDocLinkCollector", "a.md",
     "see [x](missing.md)\n"),
)


def _dump(signals: Any) -> list[dict[str, Any]]:
    return [s.model_dump() for s in signals]


def test_memo_keys_are_sha256_prefix(tmp_path: Path) -> None:
    for name, memo_attr, clear_fn, stats_fn, cls_name, fname, text in CASES:
        mod = importlib.import_module(f"proactive_loop.collectors.{name}")
        root = tmp_path / name
        root.mkdir()
        (root / fname).write_text(text, encoding="utf-8")
        getattr(mod, clear_fn)()
        memo = getattr(mod, memo_attr)
        assert len(memo) == 0, f"{name}: memo not empty after {clear_fn}()"

        collector = getattr(mod, cls_name)()
        s1 = _dump(collector.collect(root))
        hits1 = getattr(mod, stats_fn)()["hits"]

        sha_key = hashlib.sha256(text.encode("utf-8")).digest()[:16]
        b2_key = hashlib.blake2b(text.encode("utf-8"), digest_size=16).digest()
        keys = list(memo.keys())
        # EB1: sha256[:16] key present, 16 bytes long
        assert len(sha_key) == 16
        assert sha_key in memo, f"{name}: sha256[:16] key missing; keys={keys!r}"
        assert all(isinstance(k, bytes) and len(k) == 16 for k in keys), (
            f"{name}: memo keys are not all 16-byte digests: {keys!r}"
        )
        # EB2: the old blake2b key is gone (non-vacuous key change)
        assert b2_key not in memo, f"{name}: blake2b key still present"

        # EB3: second collect over unchanged workspace is identical and hits
        s2 = _dump(getattr(mod, cls_name)().collect(root))
        hits2 = getattr(mod, stats_fn)()["hits"]
        assert s2 == s1, f"{name}: signals moved between warm collects"
        assert hits2 >= hits1 + 1, f"{name}: no memo hit ({hits1} -> {hits2})"
        if name == "todos":
            assert s1, "todos: '# TODO: x' produced no signal"
        if name == "broken_link":
            assert s1, "broken_link: relative missing link produced no signal"
        getattr(mod, clear_fn)()


def _calls(tree: ast.AST, attr: str) -> int:
    n = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "hashlib"
        ):
            n += 1
    return n


def test_census_no_blake2b_call_one_sha256_call() -> None:
    for name, *_ in CASES:
        path = SRC / f"{name}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert _calls(tree, "blake2b") == 0, f"{name}.py still calls hashlib.blake2b("
        assert _calls(tree, "sha256") == 1, (
            f"{name}.py: expected exactly one hashlib.sha256( call, got "
            f"{_calls(tree, 'sha256')}"
        )
