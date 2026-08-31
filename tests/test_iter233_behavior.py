"""Black-box behavior tests for foundry iteration 255 --- ONE atomic-write primitive.

Feature under test: the product's L0 promise ("atomic JSON checkpoints ->
resumable runs") rests on ONE invariant --- a SIBLING temp file in the
destination's own directory, ONE ``os.replace`` onto the target, and a
``finally`` best-effort unlink so a failed swap strands no ``<name>.tmp`` and
never masks the PRIMARY error. That invariant used to be hand-copied at FOUR
sites (the checkpoint writer plus the CLI's slate, snapshot-document and meta
writers). This iteration gives it ONE home, ``proactive_loop.models
.atomic_write_text``, has all four writers delegate, and adds two AST censuses
so a fifth private copy cannot regrow. Success bytes, schemas, stdout, exit
codes and the four site-specific WHY docstrings are unchanged.

ISOLATION CONTRACT (honored): every assertion below is written against THIS
iteration's spec (``pm.md`` "Expected Behaviors" 1-10) and drives only public or
spec-authorized surfaces --- ``proactive_loop.models.atomic_write_text``, the
public ``proactive_loop.loop.Checkpoint`` persistence seam, the ``pla`` CLI
through ``proactive_loop.cli.main(argv) -> int`` (its exit codes and on-disk
artifacts), the ``__doc__`` attributes the spec names, and the private CLI
writers this iteration's spec EXPLICITLY authorizes (``from proactive_loop.cli
import _write_meta, _write_slate, _write_snapshot_document``; in-tree precedent:
``tests/test_iter122_behavior.py`` imports ``_write_slate``,
``tests/test_iter134_behavior.py`` imports ``_write_meta``). The two censuses
(behaviors 6/7) parse tracked source with ``ast`` as a MACHINE domain --- no
file under ``src/`` was read by a human, no engineer or reviewer notes were
read, and no ``git diff`` was consulted.

Fully offline and deterministic: zero network, zero API keys, the scripted
provider seam only, no sleeps. Every writer under test is pointed at a
``tmp_path`` directory; the only in-repo path read at runtime is the bundled
``examples/scripted_responses.json`` fixture that ``make demo`` itself uses.

Failure injection is NARROW BY CONSTRUCTION (spec handoff note 1): ``os.replace``
is swapped on the ``os`` MODULE OBJECT, because the product resolves
``os.replace`` at call time; and every swap happens inside a ``try``/``finally``
context manager that ALWAYS restores the attribute, because a ``Path.unlink``
left raising past the call under test breaks pytest's own ``tmp_path``
housekeeping (the ``tests/test_iter134_behavior.py`` convention, reused).

AMBIGUITY NOTES (PM feedback):
* Behavior 5 says "the temp unlink patched to raise" without naming the call.
  Cleanup may route through ``Path.unlink``, ``os.unlink`` or ``os.remove``, so
  all three are patched and the test asserts only that AT LEAST ONE fired --- the
  iter-134 convention the spec itself cites, since pinning the syscall would
  encode an implementation choice.
* Behavior 10 requires each writer's ``__doc__`` to carry "a same-filesystem
  phrase (``same filesystem`` or ``one filesystem``)". ``Checkpoint.save`` says
  "single filesystem" --- a third spelling of the same claim, in a docstring this
  iteration's Acceptance Criteria forbid rewriting. Testing only the two
  enumerated spellings would red a docstring the engineer was told not to touch,
  so the assertion accepts ANY of the three and reports which one it found.
  Recommend the spec say "a same-filesystem phrase" and enumerate three.
* Behavior 9 names ``_SIGNAL_IDENTITY_KEYS`` (a private constant). Asserting
  against the constant would let a rename of BOTH sides pass vacuously, so the
  six keys are spelled out here as the black-box expectation and the count is
  pinned at six.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from proactive_loop.cli import _write_meta, _write_slate, _write_snapshot_document, main
from proactive_loop.loop import Checkpoint
from proactive_loop.models import (
    CandidateGoal,
    ContextSignal,
    GoalSlate,
    LoopStep,
    RunState,
    RunStatus,
    StepKind,
    WorkspaceSnapshot,
    atomic_write_text,
)

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"

_TMP_SUFFIX = ".tmp"
_SRC_PKG = "src/proactive_loop"

#: Behavior 6 --- the ONLY two ``(relpath, qualname)`` pairs allowed to call
#: ``os.replace``. ``loop/tools.py::_move_file`` is an allowlisted NAMED
#: exception, and the reason is recorded here so the allowlist can never grow
#: silently: it renames an ALREADY-WRITTEN file INTO the artifacts sandbox --- a
#: move between two real paths, not a temp-sibling text write --- and this
#: iteration's spec puts it explicitly Out of Scope.
_REPLACE_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        (f"{_SRC_PKG}/models.py", "atomic_write_text"),
        # Qualified name, measured: the mover is a METHOD, so the AST attributes
        # the call to ``ToolRegistry._move_file``. The spec names it unqualified
        # (``loop/tools.py::_move_file``); the qualified form is the same site,
        # spelled the way this census reports it.
        (f"{_SRC_PKG}/loop/tools.py", "ToolRegistry._move_file"),
    }
)

#: Behavior 7 --- the ONE tracked module allowed to hold a ``".tmp"`` string
#: CONSTANT (constant-level, not text-level: ``.tmp`` legitimately appears in
#: prose and docstrings).
_TMP_CONSTANT_HOME = f"{_SRC_PKG}/models.py"

#: Behavior 9 --- the snapshot document's per-signal identity keys, spelled out.
_EXPECTED_SIGNAL_KEYS = frozenset({"source", "kind", "summary", "detail", "path", "weight"})
_BANNED_SIGNAL_KEYS = ("timestamp", "collected_at")

#: Behavior 10 --- tokens ``atomic_write_text.__doc__`` must NOT contain (the
#: iter-122 over-claim convention, which bans the TOKENS, so even a disclaimer
#: reds).
_OVERCLAIM_TOKENS = ("fsync", "power", "lock", "concurren", "durab")

#: Behavior 10 --- accepted spellings of the same-filesystem claim. See the
#: AMBIGUITY NOTE in this module's docstring.
_SAME_FS_PHRASES = ("same filesystem", "one filesystem", "single filesystem")


# ---------------------------------------------------------------------------
# Helpers --- public models in, observable disk state / exit codes / __doc__ out.
# ---------------------------------------------------------------------------


@contextmanager
def _patched(target: Any, name: str, value: Any) -> Iterator[None]:
    """Swap one attribute for the duration of the block, ALWAYS restoring it."""
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


def _raiser(message: str) -> Callable[..., None]:
    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError(message)

    return _boom


@contextmanager
def _replace_raises(message: str = "boom") -> Iterator[None]:
    with _patched(os, "replace", _raiser(message)):
        yield


@contextmanager
def _unlink_raises(message: str = "cleanup") -> Iterator[list[str]]:
    """Every plausible temp-removal route raises; yields the call log."""
    calls: list[str] = []

    def _boom_path(self: Path, *args: object, **kwargs: object) -> None:
        calls.append(str(self))
        raise OSError(message)

    def _boom_os(path: object, *args: object, **kwargs: object) -> None:
        calls.append(str(path))
        raise OSError(message)

    with _patched(Path, "unlink", _boom_path):
        with _patched(os, "unlink", _boom_os):
            with _patched(os, "remove", _boom_os):
                yield calls


@contextmanager
def _replace_recorder() -> Iterator[list[tuple[Path, Path]]]:
    """Record every ``(src, dst)`` pair, then perform the REAL replace."""
    real = os.replace
    seen: list[tuple[Path, Path]] = []

    def _spy(src: Any, dst: Any, *args: object, **kwargs: object) -> None:
        seen.append((Path(os.fspath(src)), Path(os.fspath(dst))))
        real(src, dst, *args, **kwargs)

    with _patched(os, "replace", _spy):
        yield seen


def _names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def _tmp_residue(directory: Path) -> list[str]:
    return [n for n in _names(directory) if n.endswith(_TMP_SUFFIX)]


def _normalized(text: str) -> str:
    """Whitespace-collapsed text, so a WRAPPED phrase is still one phrase."""
    return " ".join(text.split())


def _goal(title: str = "Audit the atomic-write primitive") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="black-box atomic-write probe",
        suggested_first_steps=["drive the writer"],
    )


def _state(title: str = "Audit the atomic-write primitive") -> RunState:
    return RunState(
        goal=_goal(title),
        status=RunStatus.DONE,
        steps=[
            LoopStep(index=0, kind=StepKind.PLAN, output="thought: probe the writer"),
            LoopStep(index=1, kind=StepKind.CHECK, output="reason: complete", done=True),
        ],
        iterations_used=2,
        llm_calls_used=2,
    )


def _slate(root: Path) -> GoalSlate:
    return GoalSlate(workspace_root=str(root), goals=[_goal()])


def _snapshot(root: Path) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        root=str(root),
        signals=[
            ContextSignal(
                source="notes",
                kind="todo",
                summary="one open TODO",
                detail="TODO: ship the thing",
                path=str(root / "notes" / "todo.md"),
                weight=1.0,
            )
        ],
    )


def _workspace(tmp_path: Path) -> Path:
    """A synthetic workspace the shipped collectors find signals in."""
    ws = tmp_path / "ws"
    (ws / "notes").mkdir(parents=True)
    (ws / "notes" / "todo.md").write_text("TODO: ship the thing\n", encoding="utf-8")
    (ws / "README.md").write_text("# probe workspace\n", encoding="utf-8")
    return ws


# --- the four writers under test, each as (label, target-factory, call) -----


def _writer_cases(tmp_path: Path) -> list[tuple[str, Path, Callable[[], None]]]:
    """``(label, target_path, thunk)`` for all four temp-sibling JSON writers.

    Each writer gets its OWN directory so one case's residue can never be read
    as another's.
    """
    ck_dir = tmp_path / "w_checkpoint"
    sl_dir = tmp_path / "w_slate"
    sn_dir = tmp_path / "w_snapshot"
    mt_dir = tmp_path / "w_meta"
    for directory in (ck_dir, sl_dir, sn_dir, mt_dir):
        directory.mkdir(parents=True)

    ck_path = ck_dir / "checkpoint.json"
    sl_path = sl_dir / "slate.json"
    sn_path = sn_dir / "snap.json"
    mt_path = mt_dir / "meta.json"

    return [
        ("Checkpoint.save", ck_path, lambda: Checkpoint(ck_path).save(_state())),
        ("cli._write_slate", sl_path, lambda: _write_slate(_slate(tmp_path), sl_path)),
        (
            "cli._write_snapshot_document",
            sn_path,
            lambda: _write_snapshot_document(_snapshot(tmp_path), sn_path),
        ),
        (
            "cli._write_meta",
            mt_path,
            lambda: _write_meta(mt_dir, tmp_path / "ws", mt_dir / "artifacts"),
        ),
    ]


# --- census helpers (behaviors 6/7) ----------------------------------------


def _tracked_src_modules() -> dict[str, str]:
    """``relpath -> source`` for every tracked ``*.py`` under ``src/proactive_loop``.

    The domain is ``git ls-files`` --- the SHIPPING tree --- because a fresh clone
    is what CI and a recruiter get, and an untracked scratch module must not be
    able to hide a fifth copy of the invariant from this census.
    """
    listed = subprocess.run(
        ["git", "ls-files", _SRC_PKG],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert listed.returncode == 0, (
        f"git ls-files exited {listed.returncode}; the census domain is unknown, "
        "so this oracle would pass vacuously"
    )
    rels = sorted(
        line.strip()
        for line in listed.stdout.splitlines()
        if line.strip().endswith(".py")
    )
    assert len(rels) >= 30, (
        f"the census listed only {len(rels)} module(s) under {_SRC_PKG} -- the "
        "domain collapsed, so this oracle would pass vacuously"
    )
    assert _TMP_CONSTANT_HOME in rels, (
        f"{_TMP_CONSTANT_HOME} is not in the census domain; got {rels[:5]}..."
    )
    return {rel: (REPO / rel).read_text(encoding="utf-8") for rel in rels}


def _is_os_replace_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "replace"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
    )


def _os_replace_sites(source: str) -> set[str]:
    """Qualified names of the functions whose OWN body calls ``os.replace``.

    A call is attributed to the INNERMOST enclosing ``def`` (module-level calls
    become ``<module>``), so a helper nested inside a writer is reported as
    itself rather than silently credited to its parent.
    """
    sites: set[str] = set()

    def _walk(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                _walk(child, scope + (child.name,))
                continue
            if _is_os_replace_call(child):
                sites.add(".".join(scope) if scope else "<module>")
            _walk(child, scope)

    _walk(ast.parse(source), ())
    return sites


def _tmp_constant_sites(source: str) -> int:
    """How many times ``".tmp"`` appears as a string CONSTANT in one module."""
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value == _TMP_SUFFIX
    )


# ---------------------------------------------------------------------------
# Behavior 1 -- the primitive exists and writes
# ---------------------------------------------------------------------------


def test_b01_primitive_creates_the_parent_chain_and_writes_exactly_the_text(
    tmp_path: Path,
) -> None:
    target = tmp_path / "deep" / "deeper" / "state.json"
    assert not target.parent.exists(), "precondition: the parent chain must be absent"

    assert atomic_write_text(target, '{"k": 1}') is None, "the primitive returns None"

    assert target.read_text() == '{"k": 1}', (
        f"the target must hold exactly the text; got {target.read_text()!r}"
    )
    assert _names(target.parent) == [target.name], (
        f"no other entry may survive in the destination dir; got {_names(target.parent)}"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- one rename, from a same-directory sibling
# ---------------------------------------------------------------------------


def test_b02_exactly_one_replace_from_a_same_directory_sibling(tmp_path: Path) -> None:
    target = tmp_path / "out" / "state.json"

    with _replace_recorder() as calls:
        atomic_write_text(target, "payload")

    assert len(calls) == 1, f"exactly one os.replace expected; got {calls}"
    src, dst = calls[0]
    assert dst == target, f"the rename destination must be the target; got {dst}"
    assert src.parent == target.parent, (
        "the temp must be a SIBLING so the rename stays on one filesystem; "
        f"src.parent={src.parent} target.parent={target.parent}"
    )
    assert src.name != target.name, (
        f"the temp must not already be the target name; got {src.name!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 3 -- a failed swap leaves the previous bytes byte-for-byte intact
# ---------------------------------------------------------------------------


def test_b03_failed_swap_preserves_the_previous_bytes_and_propagates_unwrapped(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state.json"
    previous = b'{"generation": 1}'
    target.write_bytes(previous)

    with _replace_raises("boom"):
        with pytest.raises(OSError) as excinfo:
            atomic_write_text(target, '{"generation": 2}')

    assert type(excinfo.value) is OSError, (
        f"the primary OSError must propagate UNWRAPPED; got {type(excinfo.value).__name__}"
    )
    assert str(excinfo.value) == "boom", (
        f"the primary message must survive; got {str(excinfo.value)!r}"
    )
    assert target.read_bytes() == previous, (
        f"the previous bytes must be byte-for-byte intact; got {target.read_bytes()!r}"
    )


# ---------------------------------------------------------------------------
# Behavior 4 -- a failed swap leaves no temp file
# ---------------------------------------------------------------------------


def test_b04_failed_swap_strands_no_temp_and_leaves_the_dir_list_unchanged(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state.json"
    target.write_bytes(b"previous")
    before = _names(tmp_path)

    with _replace_raises("boom"):
        with pytest.raises(OSError):
            atomic_write_text(target, "next")

    assert _tmp_residue(tmp_path) == [], (
        f"a failed swap must strand no *.tmp; got {_tmp_residue(tmp_path)}"
    )
    assert _names(tmp_path) == before, (
        f"the directory listing must be unchanged; before={before} after={_names(tmp_path)}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 -- cleanup never masks the primary error
# ---------------------------------------------------------------------------


def test_b05_cleanup_failure_never_masks_the_primary_error(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_bytes(b"previous")

    with _replace_raises("boom"):
        with _unlink_raises("cleanup") as unlink_calls:
            with pytest.raises(OSError) as excinfo:
                atomic_write_text(target, "next")

    assert str(excinfo.value) == "boom", (
        "the PRIMARY failure must reach the caller, never the cleanup error; "
        f"got {str(excinfo.value)!r}"
    )
    assert unlink_calls, (
        "cleanup must be ATTEMPTED (Path.unlink / os.unlink / os.remove); none fired"
    )
    assert target.read_bytes() == b"previous", "the previous bytes must still be intact"


# ---------------------------------------------------------------------------
# Behavior 6 -- regrowth census A: one os.replace writer
# ---------------------------------------------------------------------------


#: A module shaped like the PRE-change tree: one hand-copied temp-sibling swap
#: inside a plain function, one inside a method. Both censuses are asserted
#: against this first, because a census that cannot SEE the thing it forbids
#: passes vacuously forever -- the fail-open shape this module exists to prevent.
_PRE_CHANGE_SHAPE = """
import os

class Writer:
    def save(self, path, text):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, path)

def _write_slate(slate, out):
    tmp = out.with_name(out.name + ".tmp")
    try:
        tmp.write_text(slate)
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)

def innocent(path):
    return path.replace("a", "b")
"""


def test_b06_precondition_the_replace_census_detects_a_hand_copied_swap() -> None:
    """The detector is two-sided: it FIRES on pre-change-shaped source ..."""
    assert _os_replace_sites(_PRE_CHANGE_SHAPE) == {"Writer.save", "_write_slate"}, (
        "the os.replace census must attribute each call to its innermost enclosing "
        f"def; got {_os_replace_sites(_PRE_CHANGE_SHAPE)}"
    )


def test_b06_precondition_the_replace_census_is_silent_on_a_delegating_module() -> None:
    """... and STAYS SILENT on source that delegates, so it can discriminate."""
    delegating = "from proactive_loop.models import atomic_write_text\n\ndef save(p, t):\n    atomic_write_text(p, t)\n"
    assert _os_replace_sites(delegating) == set(), (
        f"a delegating module must produce no site; got {_os_replace_sites(delegating)}"
    )


def test_b07_precondition_the_tmp_census_counts_constants_not_prose() -> None:
    """Constant-level, both sides: two real constants seen, prose ignored."""
    assert _tmp_constant_sites(_PRE_CHANGE_SHAPE) == 2, (
        f"two hand-copied \".tmp\" constants expected; got {_tmp_constant_sites(_PRE_CHANGE_SHAPE)}"
    )
    prose_only = '"""A docstring mentioning .tmp residue in prose."""\n# and a .tmp comment\n'
    assert _tmp_constant_sites(prose_only) == 0, (
        "prose and comments must NOT count as constant sites; got "
        f"{_tmp_constant_sites(prose_only)}"
    )



def test_b06_only_the_primitive_and_the_allowlisted_mover_call_os_replace() -> None:
    corpus = _tracked_src_modules()
    found: set[tuple[str, str]] = set()
    for rel, source in corpus.items():
        for qualname in _os_replace_sites(source):
            found.add((rel, qualname))

    unexpected = sorted(found - _REPLACE_ALLOWLIST)
    missing = sorted(_REPLACE_ALLOWLIST - found)

    assert not unexpected, (
        "a NEW private copy of the temp-sibling swap has regrown -- delegate to "
        "proactive_loop.models.atomic_write_text instead. Offending "
        "(file, function): "
        + "; ".join(f"{rel}::{qual}" for rel, qual in unexpected)
    )
    assert not missing, (
        "an allowlisted os.replace site vanished, so this census no longer proves "
        "anything: " + "; ".join(f"{rel}::{qual}" for rel, qual in missing)
    )


# ---------------------------------------------------------------------------
# Behavior 7 -- regrowth census B: one ".tmp" constant site
# ---------------------------------------------------------------------------


def test_b07_the_tmp_suffix_constant_lives_at_exactly_one_site() -> None:
    corpus = _tracked_src_modules()
    counts = {rel: _tmp_constant_sites(source) for rel, source in corpus.items()}
    offenders = sorted(rel for rel, n in counts.items() if n and rel != _TMP_CONSTANT_HOME)

    assert not offenders, (
        f'the "{_TMP_SUFFIX}" suffix must be spelled ONCE, inside '
        f"{_TMP_CONSTANT_HOME}; also found in: " + "; ".join(offenders)
    )
    assert counts[_TMP_CONSTANT_HOME] == 1, (
        f'{_TMP_CONSTANT_HOME} must hold exactly ONE "{_TMP_SUFFIX}" constant; '
        f"got {counts[_TMP_CONSTANT_HOME]}"
    )


# ---------------------------------------------------------------------------
# Behavior 8 -- all four writers still honour the invariant end-to-end
# ---------------------------------------------------------------------------


def test_b08a_every_writer_preserves_previous_bytes_and_strands_no_temp_on_a_failed_swap(
    tmp_path: Path,
) -> None:
    previous = b'{"previous": true}'
    for label, target, call in _writer_cases(tmp_path):
        target.write_bytes(previous)
        before = _names(target.parent)

        with _replace_raises("boom"):
            with pytest.raises(OSError) as excinfo:
                call()

        assert str(excinfo.value) == "boom", (
            f"{label}: the primary OSError must propagate; got {str(excinfo.value)!r}"
        )
        assert target.read_bytes() == previous, (
            f"{label}: the previous bytes must be byte-for-byte intact; "
            f"got {target.read_bytes()!r}"
        )
        assert _tmp_residue(target.parent) == [], (
            f"{label}: a failed swap stranded {_tmp_residue(target.parent)}"
        )
        assert _names(target.parent) == before, (
            f"{label}: the directory listing changed; before={before} "
            f"after={_names(target.parent)}"
        )


def test_b08b_every_writer_causes_exactly_one_same_directory_replace(
    tmp_path: Path,
) -> None:
    for label, target, call in _writer_cases(tmp_path):
        with _replace_recorder() as calls:
            call()

        assert len(calls) == 1, f"{label}: exactly one os.replace expected; got {calls}"
        src, dst = calls[0]
        assert dst == target, f"{label}: the rename destination must be {target}; got {dst}"
        assert src.parent == dst.parent, (
            f"{label}: the temp must be a SIBLING of its destination; "
            f"src.parent={src.parent} dst.parent={dst.parent}"
        )
        assert target.exists(), f"{label}: the target must exist after a successful write"


# ---------------------------------------------------------------------------
# Behavior 9 -- success bytes unchanged for the two user-visible documents
# ---------------------------------------------------------------------------


def test_b09_scan_writes_a_byte_identical_slate_and_a_leak_free_round_tripping_snapshot(
    tmp_path: Path,
) -> None:
    ws = _workspace(tmp_path)
    out_dir = tmp_path / "artifacts"
    slate_path = out_dir / "slate.json"
    snap_path = out_dir / "snap.json"

    rc = main(
        [
            "scan",
            "--workspace",
            str(ws),
            "--provider",
            "scripted",
            "--scripted-responses",
            str(SCRIPT),
            "--out",
            str(slate_path),
            "--snapshot",
            str(snap_path),
        ]
    )
    assert rc == 0, f"pla scan must exit 0; got {rc}"
    assert _tmp_residue(out_dir) == [], f"scan left residue: {_tmp_residue(out_dir)}"

    # 9a -- the slate is byte-identical to a re-dump of what it parses back to.
    slate_text = slate_path.read_text(encoding="utf-8")
    reparsed = GoalSlate.model_validate_json(slate_text)
    assert slate_text == reparsed.model_dump_json(indent=2), (
        "the slate document must stay a 2-space-indented model dump across the refactor"
    )

    # 9b -- the snapshot document leaks no schema (the iter-08 discipline).
    document = json.loads(snap_path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"snap.json must be a mapping; got {type(document)}"
    assert set(document) == {"workspace_root", "signals"}, (
        f"snap.json keys must be exactly workspace_root+signals; got {sorted(document)}"
    )
    assert document["signals"], "the synthetic workspace must yield at least one signal"
    for index, row in enumerate(document["signals"]):
        assert set(row) == _EXPECTED_SIGNAL_KEYS, (
            f"signal[{index}] keys must be exactly {sorted(_EXPECTED_SIGNAL_KEYS)}; "
            f"got {sorted(row)}"
        )
        for banned in _BANNED_SIGNAL_KEYS:
            assert banned not in row, f"signal[{index}] leaks {banned!r}"

    # 9c -- and the document a shipped verb consumes still round-trips.
    rc_signals = main(["signals", "--workspace", str(ws), "--baseline", str(snap_path)])
    assert rc_signals == 0, f"pla signals --baseline must accept it verbatim; got {rc_signals}"


# ---------------------------------------------------------------------------
# Behavior 10 -- the four WHYs survive, and the primitive does not over-claim
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "obj", "reason"),
    [
        ("Checkpoint.save", Checkpoint.save, "highest-frequency writer"),
        ("cli._write_slate", _write_slate, "PER-TICK writer"),
        ("cli._write_snapshot_document", _write_snapshot_document, "--baseline"),
        ("cli._write_meta", _write_meta, "ONLY record of ``workspace_root``"),
    ],
)
def test_b10a_each_writer_keeps_its_mechanism_and_its_own_site_specific_reason(
    label: str, obj: Any, reason: str
) -> None:
    doc = _normalized(obj.__doc__ or "")
    assert doc, f"{label}: the WHY docstring must survive the refactor"

    lowered = doc.lower()
    assert "os.replace" in lowered, f"{label}: __doc__ must name os.replace; got {doc!r}"
    assert "atomic" in lowered, f"{label}: __doc__ must still claim atomicity; got {doc!r}"
    assert any(phrase in lowered for phrase in _SAME_FS_PHRASES), (
        f"{label}: __doc__ must carry a same-filesystem phrase "
        f"(one of {_SAME_FS_PHRASES}); got {doc!r}"
    )
    assert reason.lower() in lowered, (
        f"{label}: its OWN site-specific reason {reason!r} must survive -- four "
        f"different reasons for one mechanism is the point; got {doc!r}"
    )
    assert "atomic_write_text" in lowered, (
        f"{label}: __doc__ must name the delegation target; got {doc!r}"
    )


def test_b10b_the_primitive_documents_the_mechanism_without_over_claiming() -> None:
    doc = _normalized(atomic_write_text.__doc__ or "")
    assert doc, "the primitive must be documented"

    lowered = doc.lower()
    assert "os.replace" in lowered, f"__doc__ must name os.replace; got {doc!r}"
    assert "sibling" in lowered, f"__doc__ must name the SIBLING temp; got {doc!r}"
    assert "finally" in lowered, f"__doc__ must name the finally cleanup; got {doc!r}"

    overclaims = [token for token in _OVERCLAIM_TOKENS if token in lowered]
    assert not overclaims, (
        "positive claims only -- the docstring must not reach for guarantees the "
        f"mechanism does not make (banned tokens found: {overclaims}); got {doc!r}"
    )
