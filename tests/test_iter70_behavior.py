"""Black-box behavior tests for iteration 70.

Feature under test: a new **L2 perception collector**, ``LockfileDriftCollector``
(``name == "lockfile_drift"``, ``kind == "lockfile_drift"``) -- the first
*relational* collector. It pairs each dependency manifest with its sibling
lockfile (checked in the SAME directory, in a fixed candidate order, first
present wins) and emits ONE ``ContextSignal`` per drifting manifest when the
lockfile is **missing** or **stale** (manifest ``st_mtime`` strictly greater than
the lockfile's). Recognized pairings:
    pyproject.toml -> [uv.lock, poetry.lock, Pipfile.lock]
    package.json   -> [package-lock.json, pnpm-lock.yaml, yarn.lock]
``requirements.txt`` is intentionally never paired (it is itself the pin). Every
signal carries ``source == kind == "lockfile_drift"``, ``detail == ""``,
``weight == 0.6``, ``timestamp is None``, and ``path`` = the manifest's path.
Like every collector it degrades to ``[]`` rather than raising on hostile input,
honors the shared ``_SKIP_DIRS`` / hidden-dir pruning, forward-slashes the
reported ``rel`` path, and returns results ordered by ``rel`` ascending, capped
to ``max_items`` (default 30).

ISOLATION CONTRACT (honored): these tests are written strictly against the public
contract -- this iteration's spec "Expected Behaviors" (``pm.md``), ``README.md``,
and ``SPEC.md`` section 4.1 -- and drive ONLY the documented public surface: the
collector API ``proactive_loop.collectors.LockfileDriftCollector().collect(root)``,
the ``proactive_loop.collectors.lockfile_drift`` submodule (whose ``os.walk`` seam
the spec's Behavior 10 explicitly names as a monkeypatch target), the
``all_collectors()`` registry, the ``ContextSignal`` domain model from
``proactive_loop.models``, and the end-to-end CLI entry points
``pla signals --workspace W [--kind K]`` and ``pla collectors [--json]`` via
``cli.main([...])`` (observable stdout / exit code). **No file under ``src/`` was
read, no engineer/reviewer notes were read, and no ``git diff`` was consulted.**
Signal field names and the exact summary strings were taken from this iteration's
spec (``pm.md``) and the existing published tests, never from the implementation.

Every test builds its own synthetic ``tmp_path`` workspace and controls mtimes
with ``os.utime`` (NO real git repo, NO ``subprocess``, NO network, NO API keys).
No test asserts against the live repo's mutable mtimes or against
``examples/fixture_workspace`` (per the iter-15/16 env-stability lesson). The CLI
``signals`` tests pass ``--provider scripted`` WITHOUT a ``--scripted-responses``
file precisely to prove the ``signals`` inspector builds no ``LLMClient`` (it
would fault if it did): ``signals`` is LLM-free.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.collectors import LockfileDriftCollector, all_collectors
from proactive_loop.collectors import lockfile_drift as lockfile_drift_mod
from proactive_loop.collectors.lockfile_drift import (
    LockfileDriftCollector as LockfileDriftCollector_direct,
)
from proactive_loop.models import ContextSignal

# ---------------------------------------------------------------------------
# Helpers -- all black-box: build synthetic tmp workspaces, drive the public
# collector API / the CLI, read back observable output.
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = "x\n") -> Path:
    """Create *path* (and parents) with trivial text content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _set_older(newer: Path, older: Path) -> None:
    """Force ``older`` strictly OLDER than ``newer`` via ``os.utime`` (mtimes are
    the only thing the collector's stale-check reads, so we pin them explicitly
    rather than relying on filesystem write ordering)."""
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI, return (rc, stdout, stderr). Drains capsys first so setup
    output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _assert_drift_signal(s: ContextSignal, *, summary: str, path_endswith: str) -> None:
    """Assert the full fixed field contract shared by every lockfile_drift signal."""
    assert isinstance(s, ContextSignal)
    assert s.source == "lockfile_drift"
    assert s.kind == "lockfile_drift"
    assert s.summary == summary
    assert s.detail == ""
    assert s.weight == 0.6
    assert s.timestamp is None
    assert isinstance(s.path, str) and s.path.endswith(path_endswith)


# ===========================================================================
# Behavior 1 -- Registry membership: exactly one "lockfile_drift" instance in
#   all_collectors(); the class is importable from proactive_loop.collectors.
# ===========================================================================


def test_b01_registry_membership_exactly_one() -> None:
    matches = [c for c in all_collectors() if getattr(c, "name", None) == "lockfile_drift"]
    assert len(matches) == 1, f"expected exactly one lockfile_drift collector; got {matches!r}"
    assert isinstance(matches[0], LockfileDriftCollector)


def test_b01_class_importable_and_same_object() -> None:
    # Both import paths resolve to the same class object (package re-export).
    assert LockfileDriftCollector is LockfileDriftCollector_direct


# ===========================================================================
# Behavior 2 -- Constructable with no args + overridable knobs.
# ===========================================================================


def test_b02_defaults() -> None:
    c = LockfileDriftCollector()
    assert c.name == "lockfile_drift"
    assert c.max_items == 30


def test_b02_overridable_knobs() -> None:
    c = LockfileDriftCollector(max_items=1)
    assert c.max_items == 1
    assert c.name == "lockfile_drift"


# ===========================================================================
# Behavior 3 -- Lock-missing (pyproject): pyproject.toml, no sibling lock ->
#   ONE signal, full field contract, summary "... manifest has no lockfile".
# ===========================================================================


def test_b03_lock_missing_pyproject_full_field_contract(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml")

    sigs = LockfileDriftCollector().collect(tmp_path)

    assert len(sigs) == 1, f"exactly one lockfile_drift signal expected; got {sigs!r}"
    _assert_drift_signal(
        sigs[0],
        summary="pyproject.toml: manifest has no lockfile",
        path_endswith="pyproject.toml",
    )


# ===========================================================================
# Behavior 4 -- Lock-missing (package.json): same conventions as Behavior 3.
# ===========================================================================


def test_b04_lock_missing_package_json_full_field_contract(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", "{}\n")

    sigs = LockfileDriftCollector().collect(tmp_path)

    assert len(sigs) == 1, f"exactly one lockfile_drift signal expected; got {sigs!r}"
    _assert_drift_signal(
        sigs[0],
        summary="package.json: manifest has no lockfile",
        path_endswith="package.json",
    )


# ===========================================================================
# Behavior 5 -- Lock-stale: pyproject.toml newer than uv.lock -> ONE signal
#   "... manifest newer than uv.lock", weight 0.6.
# ===========================================================================


def test_b05_lock_stale_pyproject_uvlock(tmp_path: Path) -> None:
    manifest = _write(tmp_path / "pyproject.toml")
    lock = _write(tmp_path / "uv.lock", "lock\n")
    _set_older(manifest, lock)  # manifest strictly newer than lock

    sigs = LockfileDriftCollector().collect(tmp_path)

    assert len(sigs) == 1, f"exactly one signal expected; got {sigs!r}"
    _assert_drift_signal(
        sigs[0],
        summary="pyproject.toml: manifest newer than uv.lock",
        path_endswith="pyproject.toml",
    )


# ===========================================================================
# Behavior 6 -- Lock-fresh -> no signal. lock mtime >= manifest mtime -> [].
#   Equal mtimes count as fresh (never nag a freshly-regenerated lock).
# ===========================================================================


def test_b06_lock_fresh_no_signal(tmp_path: Path) -> None:
    manifest = _write(tmp_path / "pyproject.toml")
    lock = _write(tmp_path / "uv.lock", "lock\n")
    _set_older(lock, manifest)  # lock strictly newer than manifest -> fresh

    assert LockfileDriftCollector().collect(tmp_path) == []


def test_b06_equal_mtime_counts_as_fresh(tmp_path: Path) -> None:
    manifest = _write(tmp_path / "pyproject.toml")
    lock = _write(tmp_path / "uv.lock", "lock\n")
    os.utime(manifest, (1_500_000, 1_500_000))
    os.utime(lock, (1_500_000, 1_500_000))  # exactly equal

    assert LockfileDriftCollector().collect(tmp_path) == [], (
        "equal mtimes must be treated as fresh (strict > only)"
    )


# ===========================================================================
# Behavior 7 -- First-present-lockfile-wins / lockrel naming: pyproject.toml +
#   poetry.lock (no uv.lock), manifest newer -> summary names poetry.lock.
# ===========================================================================


def test_b07_first_present_lock_wins_names_poetry(tmp_path: Path) -> None:
    manifest = _write(tmp_path / "pyproject.toml")
    poetry = _write(tmp_path / "poetry.lock", "lock\n")  # uv.lock ABSENT
    _set_older(manifest, poetry)

    sigs = LockfileDriftCollector().collect(tmp_path)

    assert len(sigs) == 1, f"exactly one signal expected; got {sigs!r}"
    _assert_drift_signal(
        sigs[0],
        summary="pyproject.toml: manifest newer than poetry.lock",
        path_endswith="pyproject.toml",
    )


# ===========================================================================
# Behavior 8 -- requirements.txt is never paired -> [], with or without a lock.
# ===========================================================================


def test_b08_requirements_txt_never_paired_alone(tmp_path: Path) -> None:
    _write(tmp_path / "requirements.txt", "flask==1.0\n")
    assert LockfileDriftCollector().collect(tmp_path) == []


def test_b08_requirements_txt_never_paired_even_with_a_lock(tmp_path: Path) -> None:
    # A stray lock beside requirements.txt (no recognized manifest) still -> [].
    req = _write(tmp_path / "requirements.txt", "flask==1.0\n")
    lock = _write(tmp_path / "uv.lock", "lock\n")
    _set_older(req, lock)  # even if "req newer than lock", requirements is unrecognized
    assert LockfileDriftCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 9 -- Non-directory / empty root -> [].
# ===========================================================================


def test_b09_nonexistent_root_empty() -> None:
    assert LockfileDriftCollector().collect(Path("/does/not/exist")) == []


def test_b09_empty_dir_empty(tmp_path: Path) -> None:
    assert LockfileDriftCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 10 -- Never raises (degrades to []): os.walk raising -> []; a single
#   unreadable manifest is skipped while sibling manifests still emit.
# ===========================================================================


def test_b10_oswalk_raises_degrades_to_empty(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path / "pyproject.toml")

    def _boom(*_a, **_k):
        raise OSError("simulated os.walk failure")

    # The spec (Behavior 10) names lockfile_drift.os.walk as the monkeypatch seam.
    monkeypatch.setattr(lockfile_drift_mod.os, "walk", _boom)

    assert LockfileDriftCollector().collect(tmp_path) == []


def test_b10_one_unreadable_manifest_skipped_sibling_survives(tmp_path: Path, monkeypatch) -> None:
    # The failing manifest carries a PRESENT lock so the stale-check must stat it
    # (the lock-missing path needs no manifest stat, so it would never exercise
    # the per-manifest guard). Patching that stat to raise must skip ONLY that
    # manifest; the readable, lock-missing sibling must still emit.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a_manifest = _write(tmp_path / "a" / "pyproject.toml")   # stat() will raise
    a_lock = _write(tmp_path / "a" / "uv.lock", "lock\n")
    _set_older(a_manifest, a_lock)  # would be a "stale" signal if readable
    _write(tmp_path / "b" / "package.json", "{}\n")  # lock-missing; must still emit

    real_stat = Path.stat

    def _selective_stat(self: Path, *args, **kwargs):
        if self.name == "pyproject.toml":
            raise OSError("unreadable manifest")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _selective_stat)

    sigs = LockfileDriftCollector().collect(tmp_path)

    summaries = [s.summary for s in sigs]
    assert summaries == ["b/package.json: manifest has no lockfile"], (
        f"the readable sibling must still emit; got {summaries!r}"
    )


# ===========================================================================
# Behavior 11 -- Skip rules honored: manifests inside hidden dirs or inside
#   node_modules/.venv/__pycache__/.git/.tox/dist/build are INVISIBLE.
# ===========================================================================


_SKIP_DIR_NAMES = [
    "node_modules",
    ".venv",
    "__pycache__",
    ".git",
    ".tox",
    "dist",
    "build",
    ".hidden",  # arbitrary hidden dir (name starts with ".")
]


@pytest.mark.parametrize("skip_dir", _SKIP_DIR_NAMES)
def test_b11_manifest_in_skipped_dir_is_invisible(tmp_path: Path, skip_dir: str) -> None:
    d = tmp_path / skip_dir
    d.mkdir()
    _write(d / "pyproject.toml")  # lock-missing, but pruned -> no signal
    assert LockfileDriftCollector().collect(tmp_path) == [], (
        f"a manifest inside {skip_dir!r} must be pruned"
    )


def test_b11_visible_sibling_still_emits_next_to_skipped(tmp_path: Path) -> None:
    # A pruned dir does not suppress a legitimate top-level manifest.
    (tmp_path / "node_modules").mkdir()
    _write(tmp_path / "node_modules" / "pyproject.toml")
    _write(tmp_path / "pyproject.toml")

    sigs = LockfileDriftCollector().collect(tmp_path)

    assert [s.summary for s in sigs] == ["pyproject.toml: manifest has no lockfile"]


# ===========================================================================
# Behavior 12 -- Nested rel path is forward-slashed on every OS.
# ===========================================================================


def test_b12_nested_rel_is_forward_slashed(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "pkg" / "pyproject.toml"
    _write(nested)

    sigs = LockfileDriftCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].summary == "sub/pkg/pyproject.toml: manifest has no lockfile"
    # And the reported path is the manifest's own path.
    assert sigs[0].path.endswith("pyproject.toml")


# ===========================================================================
# Behavior 13 -- Deterministic ordering (rel ascending) + cap (max_items).
# ===========================================================================


def test_b13_ordered_by_rel_ascending(tmp_path: Path) -> None:
    (tmp_path / "zeta").mkdir()
    (tmp_path / "alpha").mkdir()
    _write(tmp_path / "zeta" / "pyproject.toml")
    _write(tmp_path / "alpha" / "package.json", "{}\n")

    sigs = LockfileDriftCollector().collect(tmp_path)

    summaries = [s.summary for s in sigs]
    assert summaries == [
        "alpha/package.json: manifest has no lockfile",
        "zeta/pyproject.toml: manifest has no lockfile",
    ], f"results must be ordered by rel ascending; got {summaries!r}"


def test_b13_capped_to_max_items_keeps_first_by_rel(tmp_path: Path) -> None:
    (tmp_path / "zeta").mkdir()
    (tmp_path / "alpha").mkdir()
    _write(tmp_path / "zeta" / "pyproject.toml")
    _write(tmp_path / "alpha" / "package.json", "{}\n")

    sigs = LockfileDriftCollector(max_items=1).collect(tmp_path)

    assert len(sigs) == 1, f"max_items=1 must truncate to one; got {sigs!r}"
    assert sigs[0].summary == "alpha/package.json: manifest has no lockfile", (
        "the retained signal must be the first by rel order"
    )


# ===========================================================================
# Behavior 14 -- CLI end-to-end (`pla signals`): a lock-missing pyproject in the
#   workspace, filtered by --kind lockfile_drift, exits 0 and prints "no
#   lockfile"; filtering by an unrelated kind does NOT surface it.
# ===========================================================================


def test_b14_cli_signals_kind_lockfile_drift_surfaces_no_lockfile(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "pyproject.toml")

    rc, out, err = _run(
        ["signals", "--workspace", str(tmp_path), "--provider", "scripted", "--kind", "lockfile_drift"],
        capsys,
    )
    assert rc == 0, f"pla signals must exit 0; stderr={err!r}"
    assert "no lockfile" in out, f"expected 'no lockfile' in output; got:\n{out}"


def test_b14_cli_signals_unrelated_kind_excludes_lockfile_drift(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "pyproject.toml")

    rc, out, err = _run(
        ["signals", "--workspace", str(tmp_path), "--provider", "scripted", "--kind", "todo"],
        capsys,
    )
    assert rc == 0, f"pla signals must exit 0; stderr={err!r}"
    assert "lockfile_drift" not in out, f"todo filter must not surface lockfile_drift; got:\n{out}"
    assert "no lockfile" not in out, f"todo filter must not surface the drift summary; got:\n{out}"


def test_b14_cli_signals_json_surfaces_lockfile_drift(tmp_path: Path, capsys) -> None:
    # The JSON channel carries the same fact with the full field contract.
    _write(tmp_path / "pyproject.toml")

    rc, out, err = _run(
        ["signals", "--workspace", str(tmp_path), "--provider", "scripted", "--kind", "lockfile_drift", "--json"],
        capsys,
    )
    assert rc == 0, f"pla signals --json must exit 0; stderr={err!r}"
    doc = json.loads(out)
    assert isinstance(doc, dict) and isinstance(doc.get("signals"), list)
    drift = [s for s in doc["signals"] if s.get("kind") == "lockfile_drift"]
    assert len(drift) == 1, f"expected one lockfile_drift signal in JSON; got {doc['signals']!r}"
    assert drift[0]["summary"] == "pyproject.toml: manifest has no lockfile"
    assert drift[0]["weight"] == 0.6


# ===========================================================================
# Behavior 15 -- CLI catalog (`pla collectors`): human output lists
#   lockfile_drift; --json emits 14 {name, description} objects including
#   lockfile_drift, name-ascending, name-set == registry name-set.
# ===========================================================================


def test_b15_collectors_human_lists_lockfile_drift(capsys) -> None:
    rc, out, err = _run(["collectors"], capsys)
    assert rc == 0, f"pla collectors (human) must exit 0; stderr={err!r}"

    lines = [ln for ln in out.splitlines() if ln.strip().startswith("lockfile_drift")]
    assert lines, f"human output must list lockfile_drift; got:\n{out}"
    desc = lines[0].strip()[len("lockfile_drift"):].strip()
    assert desc, f"lockfile_drift must have a non-empty description; line={lines[0]!r}"


def test_b15_collectors_json_14_objects_includes_lockfile_drift(capsys) -> None:
    rc, out, err = _run(["collectors", "--json"], capsys)
    assert rc == 0, f"pla collectors --json must exit 0; stderr={err!r}"

    doc = json.loads(out)
    assert isinstance(doc, dict) and "collectors" in doc
    entries = doc["collectors"]
    assert isinstance(entries, list)
    assert len(entries) == 16, f"catalog must list 16 collectors; got {len(entries)}"

    for e in entries:
        assert isinstance(e.get("name"), str) and e["name"]
        assert isinstance(e.get("description"), str) and e["description"].strip()

    names = [e["name"] for e in entries]
    assert "lockfile_drift" in names, "lockfile_drift must be catalogued"
    assert names == sorted(names), f"catalog must be name-ascending; got {names}"

    registry_names = {c.name for c in all_collectors()}
    assert set(names) == registry_names, (
        f"catalog name-set must equal registry name-set; "
        f"catalog={set(names)} registry={registry_names}"
    )
    assert len(registry_names) == 16, f"registry must now list 16 collectors; got {len(registry_names)}"
