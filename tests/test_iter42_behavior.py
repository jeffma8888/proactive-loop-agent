"""Black-box behavior tests for iteration 42.

Feature under test: a new **L2 perception collector**, ``SecretFileCollector``
(``name == "secret_file"``, ``kind == "secret_file"``) -- the *security-hygiene*
companion to ``large_file`` (blob hygiene) and ``merge_conflict`` (VCS hygiene).
It walks a workspace and emits one ``kind="secret_file"`` signal per file whose
**case-folded basename** MATCHES a curated secret-shape (exact name in
``{.env, .envrc, credentials, .netrc, .npmrc, .pypirc, .git-credentials, id_rsa,
id_dsa, id_ecdsa, id_ed25519}``, OR starts with the ``.env.`` prefix, OR ends
with a key/cert suffix in ``{.pem, .key, .p12, .pfx, .keystore, .jks}``) and is
**not EXCLUDED** (case-folded basename ending in ``{.example, .sample,
.template, .dist, .md, .pub}``). The decision is **basename-only** -- the
collector NEVER opens file content -- so it is structurally binary-safe. Each
signal carries ``source="secret_file"``, ``kind="secret_file"``, ``detail=""``,
``weight=0.85`` (a fixed, high, non-decaying hazard fact above ``large_file``'s
0.6), the file's **absolute** path in ``path`` and ``timestamp=None``; its
``summary`` is exactly ``"<relpath>: secret-shaped file"`` where ``<relpath>``
is forward-slashed relative to the workspace root (no file size). Output is
ordered by **ascending** forward-slashed relpath, then capped at ``max_items``
(default 20). Unlike ``large_file``, hidden **files** ARE scanned (the flagship
``.env`` / ``.netrc`` / ``.env.*`` targets are hidden); only hidden/skip **dirs**
are pruned (reusing ``_SKIP_DIRS`` / ``_is_hidden`` for the DIR prune only).
Files only, never directories. Additive new ``kind`` -> no version bump; it flows
into synthesis via ``by_kind()`` with zero synthesizer change and surfaces
through the EXISTING ``pla signals`` inspector.

ISOLATION CONTRACT (honored): these tests are written strictly against the
public contract -- this iteration's spec "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` section 4.1 (the ``collectors`` module contract)
-- and drive ONLY the documented public surface: the PRIMARY black-box entry
point ``pla signals --workspace W [--kind secret_file] --json`` (and its human
form) via ``cli.main([...])`` (its observable stdout/stderr/exit code), and the
public collector API ``SecretFileCollector(...).collect(root)`` named by the
spec, plus the ``proactive_loop.collectors`` package import
(``SecretFileCollector``, ``all_collectors``), the
``proactive_loop.collectors.secret_file`` submodule import, the ``Collector``
protocol, the ``ContextSignal`` model, and ``proactive_loop.__version__`` /
``pla --version``. **No file under ``src/`` was read, no engineer/reviewer notes
were read, and no ``git diff`` was consulted.** Signal field names were taken
from the public spec + the existing published tests, never from the
implementation. Every test builds its own fresh ``tmp_path`` synthetic workspace
(no ``.git`` inside, so no git-based kinds leak); only Behavior 15 references
``examples/fixture_workspace`` (to assert it carries NO secret-shaped file).
Fully offline: zero network, zero API keys -- ``--provider scripted`` is passed
WITHOUT a ``--scripted-responses`` file precisely to prove the inspector builds
no ``LLMClient`` (it would fault if it did).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop.cli import main
from proactive_loop.collectors import SecretFileCollector, all_collectors
from proactive_loop.collectors.base import Collector
from proactive_loop.collectors.secret_file import (
    SecretFileCollector as SecretFileCollector_direct,
)
from proactive_loop.models import ContextSignal

DEFAULT_MAX_ITEMS = 20
FIXED_WEIGHT = 0.85

# The full match set (Behavior 2) and exclusion set (Behavior 3), stated here
# from the spec so the tester relies on the CONTRACT, not the implementation's
# module-level constants.
EXACT_NAMES = [
    ".env", ".envrc", "credentials", ".netrc", ".npmrc", ".pypirc",
    ".git-credentials", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
]
PREFIX_NAMES = [".env.local", ".env.production"]
SUFFIX_NAMES = ["cert.pem", "server.key", "bundle.p12", "store.pfx",
                "app.keystore", "release.jks"]
FLAGGED_NAMES = EXACT_NAMES + PREFIX_NAMES + SUFFIX_NAMES

EXCLUDED_NAMES = [
    ".env.example", ".env.sample", ".env.template", ".env.dist", ".env.md",
    "id_rsa.pub", "key.pem.example", "README.md", "credentials.md",
]


# ---------------------------------------------------------------------------
# Helpers -- all black-box: build synthetic tmp workspaces, drive the CLI / the
# public collector API, read back observable output.
# ---------------------------------------------------------------------------


def _mk(path: Path, content: bytes = b"") -> Path:
    """Create *path* (and parents) with *content* bytes (empty by default).

    The collector is name-only, so content is irrelevant except for the
    hostile-content behavior (non-UTF-8 / zero bytes must never make it raise)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _relpath(sig) -> str:
    """The forward-slashed relpath carried at the head of the summary
    (``"<relpath>: secret-shaped file"``)."""
    summary = sig["summary"] if isinstance(sig, dict) else sig.summary
    return summary.split(":", 1)[0]


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI and return (rc, stdout, stderr). Drains capsys first so
    setup output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _signals_json(workspace: Path, capsys, *, kind: str | None = "secret_file") -> list[dict]:
    """Run `pla signals --workspace W [--kind K] --json` and return the parsed
    `signals` array. `--provider scripted` WITHOUT `--scripted-responses` proves
    the inspector is LLM-free (it would fault building a client otherwise)."""
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


# ===========================================================================
# Behavior 1 -- Flag a secret-shaped file end-to-end via the `pla signals` CLI.
#               `.env` alone at root -> exactly one secret_file signal; ditto
#               `id_rsa` and `config/server.key` in a normal subdir.
# ===========================================================================


def test_b01_env_at_root_one_signal_via_cli(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / ".env")

    sigs = _signals_json(tmp_path, capsys)

    assert len(sigs) == 1, f"exactly one secret_file signal expected; got {sigs!r}"
    assert sigs[0]["source"] == "secret_file"
    assert sigs[0]["kind"] == "secret_file"


def test_b01_id_rsa_at_root_via_cli(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / "id_rsa")
    sigs = _signals_json(tmp_path, capsys)
    assert len(sigs) == 1
    assert sigs[0]["kind"] == "secret_file"


def test_b01_key_in_normal_subdir_via_cli(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / "config" / "server.key")
    sigs = _signals_json(tmp_path, capsys)
    assert len(sigs) == 1
    assert sigs[0]["kind"] == "secret_file"
    assert _relpath(sigs[0]) == "config/server.key"


# ===========================================================================
# Behavior 2 -- Full match set is flagged (via the public collector API). Each
#               matching basename placed ALONE at root -> exactly one signal.
# ===========================================================================


@pytest.mark.parametrize("name", FLAGGED_NAMES)
def test_b02_full_match_set_flagged(tmp_path: Path, name: str) -> None:
    _mk(tmp_path / name)
    sigs = SecretFileCollector().collect(tmp_path)
    assert len(sigs) == 1, f"{name!r} must be flagged (exactly one signal); got {sigs!r}"
    assert sigs[0].kind == "secret_file"
    assert _relpath(sigs[0]) == name


# ===========================================================================
# Behavior 3 -- Exclusion set is NOT flagged (excluded even if it matched).
#               Each placed alone at root -> []. A workspace of only
#               excluded/non-matching files -> [].
# ===========================================================================


@pytest.mark.parametrize("name", EXCLUDED_NAMES)
def test_b03_exclusion_set_not_flagged(tmp_path: Path, name: str) -> None:
    _mk(tmp_path / name)
    assert SecretFileCollector().collect(tmp_path) == [], (
        f"{name!r} matches but is EXCLUDED -> no signal"
    )


def test_b03_only_excluded_or_nonmatching_yields_empty(tmp_path: Path) -> None:
    for n in [".env.example", "id_rsa.pub", "README.md", "notes.txt", "main.py"]:
        _mk(tmp_path / n)
    assert SecretFileCollector().collect(tmp_path) == []


# ===========================================================================
# Behavior 4 -- Case-insensitive: compared on the case-folded basename.
# ===========================================================================


@pytest.mark.parametrize(
    "name", ["ID_RSA", ".ENV", "CREDENTIALS", "Server.KEY", "Cert.PEM"]
)
def test_b04_case_insensitive_flagged(tmp_path: Path, name: str) -> None:
    _mk(tmp_path / name)
    sigs = SecretFileCollector().collect(tmp_path)
    assert len(sigs) == 1, f"{name!r} must be flagged case-insensitively; got {sigs!r}"
    assert _relpath(sigs[0]) == name  # relpath preserves the ORIGINAL casing


def test_b04_case_insensitive_exclusion(tmp_path: Path) -> None:
    _mk(tmp_path / ".ENV.EXAMPLE")
    assert SecretFileCollector().collect(tmp_path) == [], (
        ".ENV.EXAMPLE is excluded (case-folded ends in .example)"
    )


# ===========================================================================
# Behavior 5 -- Fixed signal fields: source/kind == "secret_file", detail == "",
#               weight == 0.85, timestamp is None. Asserted via BOTH API + CLI.
# ===========================================================================


def test_b05_fixed_fields_via_api(tmp_path: Path) -> None:
    _mk(tmp_path / ".env")
    sigs = SecretFileCollector().collect(tmp_path)
    assert len(sigs) == 1
    s = sigs[0]
    assert isinstance(s, ContextSignal)
    assert s.source == "secret_file"
    assert s.kind == "secret_file"
    assert s.detail == ""
    assert s.weight == FIXED_WEIGHT
    assert s.timestamp is None, f"timestamp must be None; got {s.timestamp!r}"


def test_b05_fixed_fields_via_cli(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / ".env")
    s = _signals_json(tmp_path, capsys)[0]
    assert s["source"] == "secret_file"
    assert s["kind"] == "secret_file"
    assert s["detail"] == ""
    assert s["weight"] == FIXED_WEIGHT


def test_b05_weight_above_large_file(tmp_path: Path) -> None:
    # The spec fixes secret_file's weight ABOVE large_file's 0.6.
    _mk(tmp_path / "id_rsa")
    assert SecretFileCollector().collect(tmp_path)[0].weight > 0.6


# ===========================================================================
# Behavior 6 -- Deterministic summary "<relpath>: secret-shaped file" with a
#               forward-slashed relpath and no size.
# ===========================================================================


def test_b06_summary_anchor_root(tmp_path: Path) -> None:
    _mk(tmp_path / ".env")
    sigs = SecretFileCollector().collect(tmp_path)
    assert len(sigs) == 1
    assert sigs[0].summary == ".env: secret-shaped file"


def test_b06_summary_anchor_nested_forward_slashed(tmp_path: Path) -> None:
    _mk(tmp_path / "config" / "id_rsa")
    sigs = SecretFileCollector().collect(tmp_path)
    assert len(sigs) == 1
    assert sigs[0].summary == "config/id_rsa: secret-shaped file"
    # Belt-and-suspenders: never a backslash in the relpath portion.
    assert "\\" not in _relpath(sigs[0])


def test_b06_summary_has_no_file_size(tmp_path: Path) -> None:
    _mk(tmp_path / "server.key", content=b"x" * 12345)
    sigs = SecretFileCollector().collect(tmp_path)
    assert sigs[0].summary == "server.key: secret-shaped file"
    # No byte/KB/MB size marker leaks into the summary.
    for marker in (" B", "KB", "MB", "12345"):
        assert marker not in sigs[0].summary.replace("secret-shaped file", ""), (
            f"summary must carry no size; got {sigs[0].summary!r}"
        )


# ===========================================================================
# Behavior 7 -- `path` is the file's ABSOLUTE path (non-empty string); the
#               forward-slashed relpath lives only in `summary`.
# ===========================================================================


def test_b07_path_absolute_relpath_in_summary(tmp_path: Path) -> None:
    f = _mk(tmp_path / "config" / "id_rsa")
    sigs = SecretFileCollector().collect(tmp_path)
    assert len(sigs) == 1
    s = sigs[0]
    assert isinstance(s.path, str) and s.path, f"path must be a non-empty string: {s.path!r}"
    assert os.path.isabs(s.path), f"path must be absolute: {s.path!r}"
    assert Path(s.path).resolve() == f.resolve(), "path must point at the source file"
    assert s.summary.startswith("config/id_rsa:"), s.summary


def test_b07_path_absolute_via_cli(tmp_path: Path, capsys) -> None:
    f = _mk(tmp_path / ".env")
    s = _signals_json(tmp_path, capsys)[0]
    assert os.path.isabs(s["path"]) and Path(s["path"]).resolve() == f.resolve()
    assert s["summary"] == ".env: secret-shaped file"


# ===========================================================================
# Behavior 8 -- Ordering by ascending forward-slashed relpath, then capped at
#               max_items (default 20).
# ===========================================================================


def test_b08_order_ascending_relpath(tmp_path: Path) -> None:
    # ASCII: "." (0x2E) < "a" (0x61) < "z" (0x7a) -> ".env" < "a.pem" < "z.key".
    _mk(tmp_path / "z.key")
    _mk(tmp_path / "a.pem")
    _mk(tmp_path / ".env")

    order = [_relpath(s) for s in SecretFileCollector().collect(tmp_path)]
    assert order == [".env", "a.pem", "z.key"], order


def test_b08_cap_keeps_first_by_ascending_relpath(tmp_path: Path) -> None:
    _mk(tmp_path / "z.key")
    _mk(tmp_path / "a.pem")
    _mk(tmp_path / ".env")

    sigs = SecretFileCollector(max_items=2).collect(tmp_path)
    assert len(sigs) == 2, f"cap must be exactly max_items=2; got {len(sigs)}"
    assert [_relpath(s) for s in sigs] == [".env", "a.pem"], (
        "the first two by ASCENDING relpath survive the cap"
    )


# ===========================================================================
# Behavior 9 -- Hidden FILES are scanned (the key departure from large_file):
#               a hidden secret-shaped file at root IS flagged.
# ===========================================================================


@pytest.mark.parametrize(
    "name",
    [".env", ".envrc", ".netrc", ".npmrc", ".pypirc", ".git-credentials",
     ".env.production"],
)
def test_b09_hidden_file_is_flagged(tmp_path: Path, name: str) -> None:
    # Every one of these is a HIDDEN file (basename starts with ".") yet is a
    # flagship target -- the collector must NOT skip hidden files.
    assert name.startswith("."), name
    _mk(tmp_path / name)
    sigs = SecretFileCollector().collect(tmp_path)
    assert len(sigs) == 1, f"hidden file {name!r} MUST be flagged; got {sigs!r}"
    assert _relpath(sigs[0]) == name


# ===========================================================================
# Behavior 10 -- Skip-dir + hidden-DIR pruning still applies; a sibling in a
#                normal subdir IS flagged.
# ===========================================================================


@pytest.mark.parametrize(
    "skipdir", ["node_modules", ".venv", "__pycache__", ".git", ".tox", "dist", "build"]
)
def test_b10_skipped_dir_pruned(tmp_path: Path, skipdir: str) -> None:
    _mk(tmp_path / skipdir / ".env")        # buried under a skip dir
    _mk(tmp_path / "config" / "id_rsa")     # normal-subdir sibling

    rels = {_relpath(s) for s in SecretFileCollector().collect(tmp_path)}
    assert rels == {"config/id_rsa"}, (
        f"only the normal-dir file may be flagged; got {rels!r}"
    )


def test_b10_hidden_dir_pruned(tmp_path: Path) -> None:
    _mk(tmp_path / ".config" / "credentials")  # under a HIDDEN dir -> pruned
    _mk(tmp_path / "config" / "id_rsa")         # normal dir -> flagged

    rels = {_relpath(s) for s in SecretFileCollector().collect(tmp_path)}
    assert rels == {"config/id_rsa"}, f"hidden dir must be pruned; got {rels!r}"


# ===========================================================================
# Behavior 11 -- Files only, never directories: a directory whose NAME would
#                match is NOT flagged.
# ===========================================================================


def test_b11_matching_named_directories_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "credentials").mkdir()      # dir name is an exact match
    (tmp_path / "secrets.pem").mkdir()      # dir name ends with a match suffix
    (tmp_path / "server.key").mkdir()       # dir name ends with a match suffix
    assert SecretFileCollector().collect(tmp_path) == [], (
        "directories must never be flagged, only regular files"
    )


def test_b11_matching_file_inside_matching_named_dir(tmp_path: Path) -> None:
    # A matching-named DIR is not flagged, but a matching FILE inside a normal
    # (non-skip, non-hidden) dir still is.
    (tmp_path / "credentials").mkdir()
    _mk(tmp_path / "credentials" / "id_rsa")   # a real file inside -> flagged
    rels = {_relpath(s) for s in SecretFileCollector().collect(tmp_path)}
    assert rels == {"credentials/id_rsa"}, rels


# ===========================================================================
# Behavior 12 -- Never raises -> []. Missing root, file-as-root, empty
#                workspace, and hostile (zero-byte / non-UTF-8) content.
# ===========================================================================


def test_b12_missing_root_returns_empty(tmp_path: Path) -> None:
    assert SecretFileCollector().collect(tmp_path / "no" / "such" / "dir") == []
    assert SecretFileCollector().collect(Path("/no/such/dir_xyz_qqq_zzz")) == []


def test_b12_file_as_root_returns_empty(tmp_path: Path) -> None:
    f = _mk(tmp_path / ".env")
    assert SecretFileCollector().collect(f) == []


def test_b12_no_secret_file_json_empty(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / "main.py", content=b"print('hi')\n")
    assert _signals_json(tmp_path, capsys) == [], "no secret-shaped file -> []"


def test_b12_no_secret_file_human_marker(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / "main.py", content=b"print('hi')\n")
    rc, out, err = _run(
        ["signals", "--workspace", str(tmp_path), "--provider", "scripted",
         "--kind", "secret_file"],
        capsys,
    )
    assert rc == 0, err
    assert "(no signals collected)" in out, f"expected empty marker; got:\n{out}"


def test_b12_hostile_content_still_flagged_never_raises(tmp_path: Path) -> None:
    _mk(tmp_path / ".env")                                  # zero bytes
    _mk(tmp_path / "binary.key", content=b"\xff\xfe\x00\x01\x80\x81" * 50)  # non-UTF-8
    _mk(tmp_path / "empty.pem")                             # zero bytes, suffix match

    sigs = SecretFileCollector().collect(tmp_path)  # must NOT raise on any of these
    rels = {_relpath(s) for s in sigs}
    assert rels == {".env", "binary.key", "empty.pem"}, (
        f"name-only decision flags all three regardless of content; got {rels!r}"
    )


# ===========================================================================
# Behavior 13 -- Constructor knobs + registry: defaults, exactly one registered
#                instance, importable both ways, satisfies the Collector protocol.
# ===========================================================================


def test_b13_default_knobs() -> None:
    c = SecretFileCollector()
    assert c.name == "secret_file"
    assert c.max_items == DEFAULT_MAX_ITEMS


def test_b13_max_items_ctor_overridable(tmp_path: Path) -> None:
    for n in ["a.pem", "b.pem", "c.pem", "d.pem"]:
        _mk(tmp_path / n)
    assert len(SecretFileCollector(max_items=3).collect(tmp_path)) == 3


def test_b13_registry_exactly_one_with_defaults() -> None:
    matches = [c for c in all_collectors() if c.name == "secret_file"]
    assert len(matches) == 1, "exactly one secret_file collector in the registry"
    assert type(matches[0]) is SecretFileCollector
    assert matches[0].max_items == DEFAULT_MAX_ITEMS


def test_b13_importable_both_ways_and_is_collector() -> None:
    assert SecretFileCollector is SecretFileCollector_direct
    assert isinstance(SecretFileCollector(), Collector)


# ===========================================================================
# Behavior 14 -- Registered alongside the others: bare `pla signals --json`
#                includes secret_file ALONGSIDE >=1 other kind; the human form
#                prints the group header + summary line.
# ===========================================================================


def test_b14_bare_signals_includes_secret_file_alongside_others(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / ".env")                                       # -> secret_file
    _mk(tmp_path / "mod.py", content=b"def f():\n    return 1\n")  # -> recent_file/test_posture

    sigs = _signals_json(tmp_path, capsys, kind=None)  # NO --kind: all collectors

    kinds = {s["kind"] for s in sigs}
    assert "secret_file" in kinds, f"bare signals must include secret_file; kinds={kinds!r}"
    assert len(kinds) >= 2, f"secret_file must appear ALONGSIDE other kinds; kinds={kinds!r}"


def test_b14_human_render_surfaces_group_header_and_summary(tmp_path: Path, capsys) -> None:
    _mk(tmp_path / ".env")
    rc, out, err = _run(
        ["signals", "--workspace", str(tmp_path), "--provider", "scripted",
         "--kind", "secret_file"],
        capsys,
    )
    assert rc == 0, f"signals must exit 0; stderr={err!r}"
    assert "## secret_file (1)" in out, f"missing secret_file group header; got:\n{out}"
    assert ".env: secret-shaped file" in out, f"missing summary text; got:\n{out}"


# ===========================================================================
# Behavior 15 -- Backward compatible / byte-stable: the demo fixture carries NO
#                secret-shaped file, and the additive collector does NOT bump
#                __version__ / `pla --version`.
# ===========================================================================


def test_b15_demo_fixture_has_no_secret_file_signals(tmp_path: Path, capsys) -> None:
    fixture = Path(__file__).resolve().parents[1] / "examples" / "fixture_workspace"
    assert fixture.is_dir(), fixture
    sigs = _signals_json(fixture, capsys)
    assert sigs == [], f"demo fixture must have no secret-shaped file; got {sigs!r}"


def test_b15_no_version_bump(capsys) -> None:
    assert proactive_loop.__version__ == "0.1.1", proactive_loop.__version__
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0, "`pla --version` must exit 0"
    out = capsys.readouterr().out
    assert "pla 0.1.1" in out, f"`pla --version` must print 'pla 0.1.1'; got {out!r}"
