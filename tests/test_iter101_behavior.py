"""Black-box behavior tests for factory iteration 101 --- the new L2 perception
collector ``LicenseCollector`` (``kind="license"``): a deterministic, offline,
content-blind repo-health collector that surfaces the open-source-hygiene gap
"this workspace ships source code but has no recognized root LICENSE file". It
is the license sibling of ``secret_file`` (credential hygiene) and ``ci_config``
(automation hygiene): root-anchored (at most one signal), presence-only (never
opens file content), and GAP-ONLY + source-gated (fires only when there is code
to license), mirroring ``CiConfigCollector``'s established shape.

NOTE ON FILE NAMING: the spec (pm.md) named this file ``test_iter94_behavior.py``,
but a *tracked* ``tests/test_iter94_behavior.py`` already exists for an earlier
iteration (it tests ``pla signals --collector NAME`` -- an unrelated feature).
Reusing that name would clobber legitimate committed coverage, so this file is
named for the FACTORY iteration number (101), matching the convention the last
several ships used (``test_iter98/99/100_behavior.py``). The naming collision is
flagged as PM feedback in ``tester.md``.

ISOLATION CONTRACT (honored): these tests are written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and the public test conventions already under ``tests/``
(``test_iter63_behavior.py`` for the ``ci_config`` collect() shape). They drive
ONLY documented public surfaces: the public collector API
``proactive_loop.collectors.LicenseCollector().collect(root)``, the public
``ContextSignal`` model, the public registry accessor
``proactive_loop.collectors.all_collectors()``, and the ``pla`` CLI entry
``proactive_loop.cli.main(argv) -> int`` (observable stdout / exit code).
**No file under ``src/`` was read, no engineer or reviewer note was read, and no
``git diff`` was consulted.** Every test is fully offline / deterministic: no
LLM, no network, no API keys, no subprocess; every case is built in ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.collectors import LicenseCollector, all_collectors
from proactive_loop.models import ContextSignal

REPO = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# Spec-declared field contract for the single gap signal (pm.md, Behavior 1).
# Encoded here as ground facts, NOT imported from the implementation.
# --------------------------------------------------------------------------

GAP_SUMMARY = "no license file"
GAP_WEIGHT = 0.7
GAP_SOURCE = "license"
GAP_KIND = "license"


# --------------------------------------------------------------------------
# Helpers -- black-box: build synthetic tmp workspaces, drive the public API.
# --------------------------------------------------------------------------


def _write(path: Path, content: str = "print('hi')\n") -> Path:
    """Create *path* (and parents) with trivial text content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _assert_gap(sigs: list, root: Path) -> None:
    """Assert *sigs* is EXACTLY the one spec-mandated gap signal for *root*."""
    assert isinstance(sigs, list)
    assert len(sigs) == 1, f"exactly one license gap signal expected; got {sigs!r}"
    s = sigs[0]
    assert isinstance(s, ContextSignal)
    assert s.source == GAP_SOURCE
    assert s.kind == GAP_KIND
    assert s.summary == GAP_SUMMARY
    assert s.weight == GAP_WEIGHT
    assert s.path == str(root)
    assert s.detail == ""
    assert s.timestamp is None


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI, return (rc, stdout, stderr). Drains capsys first."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ===========================================================================
# Behavior 1 -- Missing-license gap fires: source file present + NO recognized
#   license file -> EXACTLY ONE gap signal with the full fixed field contract.
# ===========================================================================


def test_b01_missing_license_gap_fires(tmp_path: Path) -> None:
    _write(tmp_path / "app.py")
    _assert_gap(LicenseCollector().collect(tmp_path), tmp_path)


# ===========================================================================
# Behavior 2 -- License present -> no gap: source file + a root file named
#   exactly ``LICENSE`` -> [].
# ===========================================================================


def test_b02_license_present_no_gap(tmp_path: Path) -> None:
    _write(tmp_path / "app.py")
    _write(tmp_path / "LICENSE", "MIT License\n")
    assert LicenseCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 3 -- Case-insensitive, basename-only match: with a source file
#   present, each of these root-level files independently suppresses the gap.
# ===========================================================================


@pytest.mark.parametrize(
    "license_name",
    ["license.txt", "LICENSE.md", "COPYING", "UNLICENSE", "licence", "License"],
)
def test_b03_case_insensitive_basename_match_suppresses(
    tmp_path: Path, license_name: str
) -> None:
    _write(tmp_path / "app.py")
    _write(tmp_path / license_name, "some license text\n")
    assert (
        LicenseCollector().collect(tmp_path) == []
    ), f"{license_name!r} should be recognized as a license file"


# ===========================================================================
# Behavior 4 -- Directories do not count as a license file: source file, NO
#   license FILE, but a SUBDIRECTORY named ``LICENSE/`` -> the one gap signal.
# ===========================================================================


def test_b04_directory_named_license_does_not_count(tmp_path: Path) -> None:
    _write(tmp_path / "app.py")
    (tmp_path / "LICENSE").mkdir()  # a DIR named like a license
    _assert_gap(LicenseCollector().collect(tmp_path), tmp_path)


# ===========================================================================
# Behavior 5 -- Source gate: no code -> no signal. NO recognized license file
#   AND NO source file (only ``notes.md``) -> [] (un-actionable dir).
# ===========================================================================


def test_b05_source_gate_no_code_no_signal(tmp_path: Path) -> None:
    _write(tmp_path / "notes.md", "# just docs\n")
    assert LicenseCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 6 -- License-file detection is root-anchored: a recognized license
#   file that exists ONLY in a subdirectory does NOT suppress a root-level gap.
# ===========================================================================


def test_b06_license_detection_is_root_anchored(tmp_path: Path) -> None:
    _write(tmp_path / "app.py")  # root-level source
    _write(tmp_path / "sub" / "LICENSE", "MIT\n")  # nested-only license
    _assert_gap(LicenseCollector().collect(tmp_path), tmp_path)


# ===========================================================================
# Behavior 7 -- Never raises; degrades to []: a non-existent path, or a path
#   that is a FILE (not a directory), returns [] and raises nothing.
# ===========================================================================


def test_b07a_nonexistent_path_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert LicenseCollector().collect(missing) == []


def test_b07b_file_path_returns_empty(tmp_path: Path) -> None:
    f = _write(tmp_path / "app.py")
    assert LicenseCollector().collect(f) == []


# ===========================================================================
# Behavior 8 -- Registered + catalogued (drift guards stay green): importable,
#   registered exactly once, registry size 16, catalog carries a non-empty
#   ``license`` description, the CLI ``collectors`` catalog lists a license row,
#   and the README intro states "17 context collectors".
# ===========================================================================


def test_b08a_importable_and_registered_once(tmp_path: Path) -> None:
    reg = all_collectors()
    assert len(reg) == 17, f"registry must list 17 collectors; got {len(reg)}"
    names = [c.name for c in reg]
    assert names.count("license") == 1, "license must appear exactly once"
    matches = [c for c in reg if c.name == "license"]
    assert len(matches) == 1
    assert isinstance(matches[0], LicenseCollector)


def test_b08b_cli_collectors_catalog_lists_license(capsys) -> None:
    # --json is the machine-readable catalog: a {collectors:[{name,description}]}
    # object whose name set is drift-guarded to equal the live registry.
    rc, out, err = _run(["collectors", "--json"], capsys)
    assert rc == 0, f"collectors --json must exit 0; stderr={err!r}"
    doc = json.loads(out)
    entries = doc["collectors"]
    assert len(entries) == 17, f"catalog must list 17 collectors; got {len(entries)}"
    by_name = {e["name"]: e for e in entries}
    assert "license" in by_name, "catalog missing the 'license' collector"
    desc = by_name["license"]["description"]
    assert isinstance(desc, str) and desc.strip(), "license needs a non-empty description"
    # Drift guard: catalog name set == live registry name set.
    assert set(by_name) == {c.name for c in all_collectors()}


def test_b08c_cli_collectors_text_lists_license_row(capsys) -> None:
    rc, out, err = _run(["collectors"], capsys)
    assert rc == 0, f"collectors must exit 0; stderr={err!r}"
    # A catalog line whose FIRST whitespace token is a collector name.
    leading = {ln.split()[0] for ln in out.splitlines() if ln.strip()}
    assert "license" in leading, f"'license' row missing from collectors output:\n{out}"


def test_b08d_readme_intro_states_16_collectors() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "17 context collectors" in readme, "README intro must say '17 context collectors'"
