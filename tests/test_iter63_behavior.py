"""Black-box behavior tests for iteration 63.

Feature under test: a new **L2 perception collector**, ``CiConfigCollector``
(``name == "ci_config"``, ``kind == "ci_config"``). It reports the scanned
workspace's continuous-integration posture as ONE context signal, completing the
automation-posture triad alongside ``dependencies`` (deps) and ``test_posture``
(tests). Detection is **root-anchored** (CI config is a repo-root concept) and
**presence-only** (``pathlib`` ``is_dir``/``is_file``/``iterdir``, never opening
file content). It emits at most one signal: a recognized CI marker (checked in a
fixed order, first match names the ``<system>``) yields
``summary="CI configured (<system>)"`` / ``weight=0.5``; otherwise, if the tree
has any source file, ``summary="no CI configured"`` / ``weight=0.8`` (the
actionable gap); otherwise ``[]``. Like every collector, it degrades to ``[]``
rather than raising on any missing / hostile input.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.1 (the ``collectors`` module contract)
-- and drive ONLY the documented public surface: the public collector API
``proactive_loop.collectors.CiConfigCollector().collect(root)``, the
``proactive_loop.collectors.ci_config`` submodule import, the
``all_collectors()`` registry, the ``Collector`` protocol from
``proactive_loop.collectors.base``, the ``ContextSignal`` domain model from
``proactive_loop.models``, ``proactive_loop.__version__``, and the end-to-end
CLI entry points ``pla signals --workspace W --kind ci_config --json`` and
``pla collectors [--json]`` via ``cli.main([...])`` (their observable stdout /
exit code). **No file under ``src/`` was read, no engineer/reviewer notes were
read, and no ``git diff`` was consulted.** Signal field names
(``source``/``kind``/``summary``/``detail``/``path``/``weight``/``timestamp``)
were taken from this iteration's spec and the existing published tests, never
from the implementation.

Every test builds its own synthetic ``tmp_path`` workspace (NO real git repo, NO
``subprocess``, NO network, NO API keys). No test asserts against
``examples/fixture_workspace`` (per the iter-15/16 env-stability lesson). The CLI
tests pass ``--provider scripted`` WITHOUT a ``--scripted-responses`` file
precisely to prove the ``signals`` inspector builds no ``LLMClient`` (it would
fault if it did).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop.cli import main
from proactive_loop.collectors import CiConfigCollector, all_collectors
from proactive_loop.collectors.base import Collector
from proactive_loop.collectors.ci_config import (
    CiConfigCollector as CiConfigCollector_direct,
)
from proactive_loop.models import ContextSignal

# ---------------------------------------------------------------------------
# Helpers -- all black-box: build synthetic tmp workspaces, drive the public
# collector API / the CLI, read back observable output.
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = "print('hi')\n") -> Path:
    """Create *path* (and parents) with trivial text content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _mk_marker(root: Path, relpath: str) -> Path:
    """Create a CI-marker FILE at ``root/relpath`` (parents made as needed)."""
    return _write(root / relpath, "on: push\n")


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI, return (rc, stdout, stderr). Drains capsys first so setup
    output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _signals_json(workspace: Path, capsys, *, kind: str | None = "ci_config") -> list[dict]:
    """Run ``pla signals --workspace W [--kind K] --json`` and return the parsed
    ``signals`` array. ``--provider scripted`` WITHOUT ``--scripted-responses``
    proves the inspector is LLM-free (it would fault building a client)."""
    argv = ["signals", "--workspace", str(workspace), "--provider", "scripted", "--json"]
    if kind is not None:
        argv += ["--kind", kind]
    rc, out, err = _run(argv, capsys)
    assert rc == 0, f"signals must exit 0; stderr={err!r}"
    doc = json.loads(out)  # the ENTIRE stdout must parse as one clean JSON object
    assert isinstance(doc, dict)
    assert set(doc.keys()) == {"workspace_root", "signals"}, doc.keys()
    assert isinstance(doc["signals"], list)
    return doc["signals"]


# The seven recognized CI systems, in the SPEC-pinned detection order. Each entry
# is (marker relpath to create, expected reported <system> label).
CI_SYSTEMS = [
    (".github/workflows/deploy.yaml", "GitHub Actions"),   # note .yaml extension
    (".gitlab-ci.yml", "GitLab CI"),
    (".circleci/config.yml", "CircleCI"),
    ("azure-pipelines.yml", "Azure Pipelines"),
    ("Jenkinsfile", "Jenkins"),
    (".travis.yml", "Travis CI"),
    ("bitbucket-pipelines.yml", "Bitbucket Pipelines"),
]


# ===========================================================================
# Behavior 1 -- CI configured (GitHub Actions): a workspace with
#   `.github/workflows/ci.yml` AND a source file -> EXACTLY ONE signal with the
#   full fixed field contract.
# ===========================================================================


def test_b01_github_actions_configured_full_field_contract(tmp_path: Path) -> None:
    _mk_marker(tmp_path, ".github/workflows/ci.yml")
    _write(tmp_path / "main.py")

    sigs = CiConfigCollector().collect(tmp_path)

    assert len(sigs) == 1, f"exactly one ci_config signal expected; got {sigs!r}"
    s = sigs[0]
    assert isinstance(s, ContextSignal)
    assert s.kind == "ci_config"
    assert s.source == "ci_config"
    assert s.summary == "CI configured (GitHub Actions)"
    assert s.weight == 0.5
    assert s.path == str(tmp_path)
    assert s.detail == ""
    assert s.timestamp is None


# ===========================================================================
# Behavior 2 -- No CI, has source (the actionable case): a source file and NO
#   recognized CI marker -> EXACTLY ONE "no CI configured" signal, weight 0.8.
# ===========================================================================


def test_b02_no_ci_has_source_actionable(tmp_path: Path) -> None:
    _write(tmp_path / "app.py")

    sigs = CiConfigCollector().collect(tmp_path)

    assert len(sigs) == 1, f"exactly one ci_config signal expected; got {sigs!r}"
    s = sigs[0]
    assert s.kind == "ci_config"
    assert s.source == "ci_config"
    assert s.summary == "no CI configured"
    assert s.weight == 0.8
    assert s.path == str(tmp_path)
    assert s.detail == ""
    assert s.timestamp is None


# ===========================================================================
# Behavior 3 -- No CI, no source: neither a CI marker nor any source-extension
#   file -> collect(root) returns [].
# ===========================================================================


def test_b03_no_ci_no_source_readme_only_empty(tmp_path: Path) -> None:
    # A workspace that holds only a non-source file.
    _write(tmp_path / "README.md", "# hi\n")
    assert CiConfigCollector().collect(tmp_path) == []


def test_b03_completely_empty_workspace_empty(tmp_path: Path) -> None:
    # An empty directory -> no source, no CI -> [].
    assert CiConfigCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 4 -- Each supported CI system detected with the correct label
#   (parametrized; each in a workspace that also has a source file).
# ===========================================================================


@pytest.mark.parametrize("relpath,system", CI_SYSTEMS, ids=[s for _, s in CI_SYSTEMS])
def test_b04_each_ci_system_labeled_correctly(tmp_path: Path, relpath: str, system: str) -> None:
    _mk_marker(tmp_path, relpath)
    _write(tmp_path / "main.py")  # source present so the marker branch is reached

    sigs = CiConfigCollector().collect(tmp_path)

    assert len(sigs) == 1, f"{relpath} -> exactly one signal; got {sigs!r}"
    s = sigs[0]
    assert s.summary == f"CI configured ({system})"
    assert s.weight == 0.5
    assert s.kind == "ci_config"


# ===========================================================================
# Behavior 5 -- Empty `.github/workflows/` is NOT CI: a `.github/workflows/`
#   directory with NO *.yml/*.yaml file (empty, or holding only a README.md)
#   plus a source file -> "no CI configured", weight 0.8.
# ===========================================================================


def test_b05_empty_workflows_dir_is_not_ci(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)  # empty dir
    _write(tmp_path / "app.py")

    sigs = CiConfigCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].summary == "no CI configured"
    assert sigs[0].weight == 0.8


def test_b05_workflows_dir_with_only_readme_is_not_ci(tmp_path: Path) -> None:
    _write(tmp_path / ".github" / "workflows" / "README.md", "docs\n")  # no yml/yaml
    _write(tmp_path / "app.py")

    sigs = CiConfigCollector().collect(tmp_path)

    assert len(sigs) == 1
    assert sigs[0].summary == "no CI configured"
    assert sigs[0].weight == 0.8


# ===========================================================================
# Behavior 6 -- Detection precedence is deterministic: BOTH
#   `.github/workflows/ci.yml` AND `.gitlab-ci.yml` present -> GitHub Actions
#   (first in the fixed order) wins; exactly one signal.
# ===========================================================================


def test_b06_precedence_github_actions_wins(tmp_path: Path) -> None:
    _mk_marker(tmp_path, ".github/workflows/ci.yml")
    _mk_marker(tmp_path, ".gitlab-ci.yml")
    _write(tmp_path / "main.py")

    sigs = CiConfigCollector().collect(tmp_path)

    assert len(sigs) == 1, f"exactly one signal even with two markers; got {sigs!r}"
    assert sigs[0].summary == "CI configured (GitHub Actions)"
    assert sigs[0].weight == 0.5


# ===========================================================================
# Behavior 7 -- Missing / non-directory root never raises -> [].
# ===========================================================================


def test_b07_nonexistent_root_returns_empty(tmp_path: Path) -> None:
    assert CiConfigCollector().collect(tmp_path / "no" / "such" / "dir") == []


def test_b07_absolute_missing_root_returns_empty() -> None:
    assert CiConfigCollector().collect(Path("/no/such/dir")) == []


def test_b07_file_root_returns_empty(tmp_path: Path) -> None:
    a_file = _write(tmp_path / "afile.py")
    assert CiConfigCollector().collect(a_file) == []


# ===========================================================================
# Behavior 8 -- Presence-only: undecodable / binary content never breaks it.
#   A CI marker (`.gitlab-ci.yml`) alongside a binary file -> one GitLab CI
#   signal, raising nothing (the collector never opens file content).
# ===========================================================================


def test_b08_binary_file_never_breaks_presence_only(tmp_path: Path) -> None:
    _mk_marker(tmp_path, ".gitlab-ci.yml")
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00binary\x80\x81")

    sigs = CiConfigCollector().collect(tmp_path)  # must NOT raise

    assert isinstance(sigs, list)
    assert len(sigs) == 1
    assert sigs[0].summary == "CI configured (GitLab CI)"
    assert sigs[0].weight == 0.5


# ===========================================================================
# Behavior 9 -- Skip-dir isolation: a source file that exists ONLY inside a
#   pruned dir (node_modules / .venv) with no CI marker and no other source
#   -> [] (that dir is pruned, so it does not count as "has source").
# ===========================================================================


def test_b09_source_only_in_node_modules_is_pruned(tmp_path: Path) -> None:
    _write(tmp_path / "node_modules" / "pkg" / "index.js")
    assert CiConfigCollector().collect(tmp_path) == []


def test_b09_source_only_in_dot_venv_is_pruned(tmp_path: Path) -> None:
    _write(tmp_path / ".venv" / "lib" / "y.py")
    assert CiConfigCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 10 -- Determinism: two successive collect(root) calls on the same
#   unchanged workspace return equal results.
# ===========================================================================


def test_b10_deterministic_repeatable(tmp_path: Path) -> None:
    _mk_marker(tmp_path, ".circleci/config.yml")
    _write(tmp_path / "svc" / "server.py")

    def _proj(sigs: list[ContextSignal]) -> list[tuple]:
        return [(s.source, s.kind, s.summary, s.detail, s.path, s.weight, s.timestamp)
                for s in sigs]

    first = CiConfigCollector().collect(tmp_path)
    second = CiConfigCollector().collect(tmp_path)

    assert len(first) == len(second) == 1
    assert _proj(first) == _proj(second)
    assert first[0].summary == "CI configured (CircleCI)"


# ===========================================================================
# Behavior 11 -- Registry membership + shape: exactly one instance named
#   "ci_config" of type CiConfigCollector; it is a Collector; importable from
#   the package; additive => version unchanged.
# ===========================================================================


def test_b11_registry_membership_and_shape() -> None:
    collectors = all_collectors()

    matches = [c for c in collectors if c.name == "ci_config"]
    assert len(matches) == 1, "exactly one ci_config collector in the registry"
    assert type(matches[0]) is CiConfigCollector

    fresh = CiConfigCollector()
    assert fresh.name == "ci_config"
    assert isinstance(fresh, Collector) or hasattr(fresh, "collect")

    # Package alias and direct-submodule import are the same class object.
    assert CiConfigCollector is CiConfigCollector_direct

    # Every registered collector still satisfies the Collector duck-type.
    for c in collectors:
        assert isinstance(c.name, str) and c.name
        assert callable(getattr(c, "collect", None))

    # Additive kind => NO version bump.
    assert proactive_loop.__version__ == "0.1.1", proactive_loop.__version__


def test_b11_importable_from_package_namespace() -> None:
    # Explicit `from proactive_loop.collectors import CiConfigCollector` works
    # (proven by the module-level import above succeeding) and is the same object.
    from proactive_loop.collectors import CiConfigCollector as _Imported

    assert _Imported is CiConfigCollector


# ===========================================================================
# Behavior 12 -- kind="ci_config" flows end-to-end through the CLI.
# ===========================================================================


def test_b12_cli_signals_json_surfaces_ci_config(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "app.py")  # source-bearing, no-CI workspace

    sigs = _signals_json(tmp_path, capsys)

    assert len(sigs) == 1
    s = sigs[0]
    assert s["kind"] == "ci_config"
    assert s["source"] == "ci_config"
    assert s["summary"] == "no CI configured"
    assert s["weight"] == 0.8
    # The workspace directory ITSELF, spelled `.`: `cli._collect` publishes every
    # path relative to the scanned workspace (iter 139). The collector still builds
    # `str(root)` -- asserted directly in test_b04/b05 above.
    assert s["path"] == ".", s["path"]
    # The --kind filter isolates ci_config: nothing of any other kind leaks.
    assert {x["kind"] for x in sigs} == {"ci_config"}


def test_b12_cli_signals_json_configured_ci(tmp_path: Path, capsys) -> None:
    _mk_marker(tmp_path, ".github/workflows/ci.yml")
    _write(tmp_path / "main.py")

    sigs = _signals_json(tmp_path, capsys)

    assert len(sigs) == 1
    assert sigs[0]["summary"] == "CI configured (GitHub Actions)"
    assert sigs[0]["weight"] == 0.5


# ===========================================================================
# Behavior 13 -- `pla collectors` catalogs ci_config; catalog stays in lockstep
#   with the live registry (now 15 collectors).
# ===========================================================================


def test_b13_collectors_json_lists_ci_config_and_matches_registry(capsys) -> None:
    rc, out, err = _run(["collectors", "--json"], capsys)
    assert rc == 0, f"pla collectors --json must exit 0; stderr={err!r}"

    doc = json.loads(out)
    assert isinstance(doc, dict) and "collectors" in doc
    entries = doc["collectors"]
    assert isinstance(entries, list) and entries

    # Every catalog entry has a name and a non-empty one-line description.
    for e in entries:
        assert isinstance(e.get("name"), str) and e["name"]
        assert isinstance(e.get("description"), str) and e["description"].strip()

    names = {e["name"] for e in entries}
    assert "ci_config" in names, "ci_config must be catalogued"

    # ci_config's description is non-empty.
    ci = next(e for e in entries if e["name"] == "ci_config")
    assert ci["description"].strip()

    # The emitted collector-name set equals the live registry -- lockstep.
    registry_names = {c.name for c in all_collectors()}
    assert names == registry_names, (
        f"catalog names must equal registry names; catalog={names} registry={registry_names}"
    )
    assert len(registry_names) == 17, f"registry must now list 17 collectors; got {len(registry_names)}"


def test_b13_collectors_human_lists_ci_config(capsys) -> None:
    rc, out, err = _run(["collectors"], capsys)
    assert rc == 0, f"pla collectors (human) must exit 0; stderr={err!r}"

    # A line names ci_config followed by a non-empty description.
    lines = [ln for ln in out.splitlines() if ln.strip().startswith("ci_config")]
    assert lines, f"human output must list ci_config; got:\n{out}"
    # After the name there is descriptive text on the same line.
    desc = lines[0].strip()[len("ci_config"):].strip()
    assert desc, f"ci_config must have a non-empty description; line={lines[0]!r}"
