"""Black-box behavior tests for state-dir iteration 133 (ships as commit-seq
**factory iter 140**): the opt-in, offline ``hooks/pre-commit`` git gate.

Feature under test (``pm.md``): the README sells exit ``5`` twice as "the channel a
**pre-commit hook** or a CI step branches on". Iteration 128 built the CI half; the
pre-commit half had no artifact at all -- no ``hooks/`` dir, no hook script -- so half
of a twice-published claim had never been demonstrated on a public portfolio repo. This
iteration ships the hook itself: a plain POSIX-sh script that runs the product's own
armed ``pla signals`` gate over the working tree and lets git abort the commit when the
gate trips, installed by one copyable ``git config core.hooksPath hooks`` line.

The two things these tests pin hardest are the ones that would silently void the
feature. (a) **The git file mode.** A hook committed ``100644`` is ignored by git for
every reader while every other assertion here still passes, so behavior 1 reads the mode
out of the INDEX (``git ls-files --stage``), not just off the filesystem. (b) **Armed-set
parity with CI.** Behavior 2 derives the kind list from BOTH ``hooks/pre-commit`` and
``.github/workflows/ci.yml`` by parsing each file, so arming a kind in one place and not
the other goes red -- a one-sided hardcode would have proved nothing.

ISOLATION CONTRACT (honored): every assertion below is written from THIS iteration's
spec (``pm.md`` Expected Behaviors) driving only the surfaces the spec designates -- the
shipped ``hooks/pre-commit`` executed as a program with a stub CLI first on ``PATH``, the
parsed text of the hook / ``ci.yml`` / ``README.md``, and ``git``'s own view of the index.
**No file under ``src/`` was read, no engineer or reviewer note was read, and no
``git diff`` was consulted by the author.** The armed kind set, the argv contract, the
exit-code contract and the README boundary are encoded here as the spec's ground facts,
never copied out of an implementation.

Offline + cap-safe: behaviors 1, 2, 3 and 9 are file reads plus two cheap ``git``
invocations. Behaviors 4-8 execute the hook itself, but every one of them resolves the
"CLI" to a 3-line stub shell script on a synthetic ``PATH`` (built under ``tmp_path``),
so no real scan, no ``uv`` resolve, no nested pytest and no network can occur -- the stub
records its ``argv`` to a log file and exits with the status the test chose.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# Tester's ground facts -- the spec-declared contract constants (pm.md).
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks" / "pre-commit"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
README = REPO / "README.md"

# Behavior 2: the state-independent, must-never-appear subset, in CI's order.
# `broken_link` was armed as the 4th kind in factory iter 147.
EXPECTED_ARMED_KINDS = ["merge_conflict", "syntax_error", "secret_file", "broken_link"]

# Behavior 1: git's mode for an executable blob.
EXPECTED_INDEX_MODE = "100755"

# Behavior 3: an offline POSIX-sh script contains none of these.
FORBIDDEN_TOKENS = ("curl", "wget", "pip ", "http://", "https://", "[[")

# Behavior 9: the human-owned intro block closes with this line.
MARKER_CLOSE = "============ -->"
INSTALL_COMMAND = "git config core.hooksPath hooks"
BYPASS = "--no-verify"

_FAIL_ON_KIND = re.compile(r"--fail-on-kind[=\s]+([A-Za-z_][A-Za-z0-9_]*)")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _hook_text() -> str:
    return HOOK.read_text(encoding="utf-8")


def _armed_from_hook() -> list[str]:
    """The kinds the SHIPPED HOOK arms, parsed out of the hook script itself."""
    return _FAIL_ON_KIND.findall(_hook_text())


def _armed_from_ci() -> list[str]:
    """The kinds the CI self-scan step arms, parsed out of the workflow itself."""
    lines = [
        line.strip()
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "--fail-on-kind" in line and not line.strip().startswith("#")
    ]
    assert len(lines) == 1, (
        "expected exactly one non-comment armed gate line in ci.yml so parity has an "
        f"unambiguous other side; found {len(lines)}: {lines}"
    )
    return _FAIL_ON_KIND.findall(lines[0])


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _write_stub(
    bindir: Path,
    name: str,
    *,
    log: Path,
    exit_code: int,
    stdout: str = "",
) -> Path:
    """A 3-line stub CLI: record argv to ``log``, optionally print, exit ``exit_code``."""
    bindir.mkdir(parents=True, exist_ok=True)
    body = ["#!/bin/sh", 'printf "%s\\n" "$*" >> ' + shlex.quote(str(log))]
    if stdout:
        body.append("printf %s " + shlex.quote(stdout))
    body.append(f"exit {exit_code}")
    path = bindir / name
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _run_hook(*path_dirs: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Execute the hook as a PROGRAM (so the exec bit + shebang are exercised)."""
    env = {
        "PATH": os.pathsep.join(str(p) for p in path_dirs),
        "HOME": str(cwd),
        "LC_ALL": "C",
    }
    return subprocess.run(
        [str(HOOK)],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _recorded_calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [line.split() for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _index_of(tokens: list[str], needle: list[str]) -> int:
    for start in range(len(tokens) - len(needle) + 1):
        if tokens[start : start + len(needle)] == needle:
            return start
    return -1


def _assert_gate_argv(tokens: list[str], *, offset: int) -> None:
    """The shared argv tail of behaviors 4 and 6: ``signals --workspace .`` + the armed set."""
    assert tokens[offset : offset + 3] == ["signals", "--workspace", "."], (
        f"expected the gate invocation to start at argv[{offset}] with "
        f"'signals --workspace .'; got {tokens!r}"
    )
    armed: list[str] = []
    for kind in EXPECTED_ARMED_KINDS:
        armed += ["--fail-on-kind", kind]
    at = _index_of(tokens, armed)
    assert at > offset, (
        f"expected all {len(EXPECTED_ARMED_KINDS)} --fail-on-kind arguments contiguously "
        f"and in order after 'signals --workspace .'; got {tokens!r}"
    )


# --------------------------------------------------------------------------
# Behavior 1 -- the hook exists and is runnable (incl. git's own index mode).
# --------------------------------------------------------------------------


def test_b1_hook_is_a_regular_executable_posix_sh_file() -> None:
    assert HOOK.is_file(), f"expected a git pre-commit hook at {HOOK}"
    first_line = _hook_text().splitlines()[0]
    assert first_line == "#!/bin/sh", (
        f"expected the shebang to be exactly '#!/bin/sh' (POSIX sh, no bashism); got {first_line!r}"
    )
    mode = HOOK.stat().st_mode
    assert mode & 0o100, (
        f"owner-execute bit missing on {HOOK} (mode {mode & 0o777:o}); git will not run it"
    )


def test_b1_hook_is_tracked_by_git_as_executable() -> None:
    listed = _git("ls-files", "--stage", "hooks/pre-commit")
    if listed.returncode != 0:
        pytest.skip("not a git checkout; index mode is unverifiable here")
    assert listed.stdout.strip(), "hooks/pre-commit is not tracked by git"
    assert listed.stdout.split()[0] == EXPECTED_INDEX_MODE, (
        "hooks/pre-commit must be tracked with mode 100755 -- a hook committed 100644 is "
        f"SILENTLY IGNORED by git for every reader, making the feature inert. Got: {listed.stdout.strip()!r}"
    )


# --------------------------------------------------------------------------
# Behavior 2 -- armed-set parity with CI (drift guard, both sides parsed).
# --------------------------------------------------------------------------


def test_b2_hook_arms_exactly_the_kinds_ci_arms_in_the_same_order() -> None:
    from_hook = _armed_from_hook()
    from_ci = _armed_from_ci()
    assert from_hook == from_ci, (
        "the local pre-commit gate and the CI self-scan must arm the SAME kinds in the "
        f"same order, or the two gates drift apart. hooks/pre-commit={from_hook!r} "
        f"ci.yml={from_ci!r}"
    )


def test_b2_the_armed_set_is_the_state_independent_subset() -> None:
    assert _armed_from_ci() == EXPECTED_ARMED_KINDS
    assert _armed_from_hook() == EXPECTED_ARMED_KINDS, (
        "the hook arms the four must-never-appear, state-independent kinds "
        "(broken_link joined in factory iter 147); only kinds measured to be zero "
        "AND independent of local state may gate a commit."
    )


# --------------------------------------------------------------------------
# Behavior 3 -- offline, POSIX-sh only, no dependency beyond the product's CLI.
# --------------------------------------------------------------------------


def test_b3_hook_is_offline_and_posix_sh_only() -> None:
    text = _hook_text()
    present = [token for token in FORBIDDEN_TOKENS if token in text]
    assert not present, (
        f"hooks/pre-commit must be offline POSIX sh; found forbidden token(s) {present!r}"
    )


def test_b3_no_hook_framework_config_was_introduced() -> None:
    # The `pre-commit` FRAMEWORK installs hook environments from remote repos, which
    # breaks offline-first outright; the spec keeps this a plain git hook.
    assert not (REPO / ".pre-commit-config.yaml").exists()
    assert not (REPO / ".pre-commit-config.yml").exists()


def test_b3_hook_names_only_the_products_own_cli() -> None:
    assert "pla" in _hook_text(), "the hook must drive the product's own CLI"


# --------------------------------------------------------------------------
# Behavior 4 -- direct invocation when `pla` is on PATH.
# --------------------------------------------------------------------------


def test_b4_direct_invocation_calls_pla_once_with_the_gate_argv(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    log = tmp_path / "argv.log"
    _write_stub(bindir, "pla", log=log, exit_code=0)

    result = _run_hook(bindir, cwd=tmp_path)

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    calls = _recorded_calls(log)
    assert len(calls) == 1, f"expected exactly one CLI invocation, got {calls!r}"
    _assert_gate_argv(calls[0], offset=0)


# --------------------------------------------------------------------------
# Behavior 5 -- exit status passes through unchanged on the direct path.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code", [0, 5, 2])
def test_b5_direct_path_passes_the_cli_exit_status_through(tmp_path: Path, code: int) -> None:
    bindir = tmp_path / "bin"
    log = tmp_path / "argv.log"
    _write_stub(bindir, "pla", log=log, exit_code=code)

    result = _run_hook(bindir, cwd=tmp_path)

    assert result.returncode == code, (
        "the published exit-code contract must pass through unremapped (5 = gate tripped, "
        f"2 = usage); expected {code}, got {result.returncode}, stderr={result.stderr!r}"
    )


# --------------------------------------------------------------------------
# Behavior 6 -- `uv run` fallback when `pla` is not on PATH.
# --------------------------------------------------------------------------


def test_b6_uv_fallback_invokes_uv_run_pla_with_the_same_gate_argv(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    log = tmp_path / "argv.log"
    _write_stub(bindir, "uv", log=log, exit_code=0)
    assert not (bindir / "pla").exists()

    result = _run_hook(bindir, cwd=tmp_path)

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    calls = _recorded_calls(log)
    assert len(calls) == 1, f"expected exactly one uv invocation, got {calls!r}"
    assert calls[0][:2] == ["run", "pla"], (
        f"expected the fallback argv to begin 'run pla'; got {calls[0]!r}"
    )
    _assert_gate_argv(calls[0], offset=2)


def test_b6_uv_fallback_passes_a_tripped_gate_through(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    log = tmp_path / "argv.log"
    _write_stub(bindir, "uv", log=log, exit_code=5)

    result = _run_hook(bindir, cwd=tmp_path)

    assert result.returncode == 5, f"stderr={result.stderr!r}"


# --------------------------------------------------------------------------
# Behavior 7 -- fail CLOSED when the CLI cannot be resolved.
# --------------------------------------------------------------------------


def test_b7_fails_closed_when_neither_pla_nor_uv_is_resolvable(tmp_path: Path) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir()

    result = _run_hook(empty, cwd=tmp_path)

    assert result.returncode == 1, (
        "a gate that silently passes because the tool is missing is worse than a noisy "
        f"one; expected exit 1, got {result.returncode}"
    )
    for needle in ("pla", "uv", BYPASS):
        assert needle in result.stderr, (
            f"expected stderr to name {needle!r} when the CLI cannot be resolved; "
            f"got {result.stderr!r}"
        )
    assert result.stdout == "", (
        f"the hook must add nothing to stdout on any path; got {result.stdout!r}"
    )


# --------------------------------------------------------------------------
# Behavior 8 -- a trip is explained on stderr; stdout is never disturbed.
# --------------------------------------------------------------------------


def test_b8_a_tripped_gate_is_explained_on_stderr(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    log = tmp_path / "argv.log"
    payload = "gate: merge_conflict=1\nsignal listing line\n"
    _write_stub(bindir, "pla", log=log, exit_code=5, stdout=payload)

    result = _run_hook(bindir, cwd=tmp_path)

    assert result.returncode == 5
    explained = [line for line in result.stderr.splitlines() if "pre-commit" in line]
    assert explained, (
        f"expected one stderr line identifying the pre-commit gate; got {result.stderr!r}"
    )
    assert f"git commit {BYPASS}" in result.stderr, (
        f"expected the documented bypass 'git commit {BYPASS}' on stderr; got {result.stderr!r}"
    )


def test_b8_cli_stdout_is_reproduced_byte_identically(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    log = tmp_path / "argv.log"
    payload = "listing line one\nlisting line two\n"

    for code in (0, 5):
        _write_stub(bindir, "pla", log=log, exit_code=code, stdout=payload)
        result = _run_hook(bindir, cwd=tmp_path)
        assert result.returncode == code
        assert result.stdout == payload, (
            "the hook must add nothing to stdout on any path -- whatever the CLI printed "
            f"is reproduced byte-identically. exit={code} got {result.stdout!r}"
        )


# --------------------------------------------------------------------------
# Behavior 9 -- README documents it, BELOW the human-owned marker only.
# --------------------------------------------------------------------------


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _protected_slice(text: str) -> str:
    """Everything from the start of the file THROUGH the marker block's closing line."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.rstrip("\n").endswith(MARKER_CLOSE):
            return "".join(lines[: index + 1])
    raise AssertionError(f"human-owned marker block close ({MARKER_CLOSE!r}) not found in README")


# The README marker's carve-out REQUIRES an automated contributor to correct exactly
# three numbers INSIDE this human-owned block -- the collector count, the CLI-verb
# count and the "N,N00+ tests" floor -- and tests/test_readme_and_ci_contract.py fails
# the build when one goes stale. So a RAW byte-identity assertion over the slice is not
# merely strict, it is a DEADLOCK: it forbids the only edit the loop is obliged to make,
# and because it compares against HEAD it can only ever fire on UNCOMMITTED work -- i.e.
# at the tester stage, whose failure REVERTS the engineer's finished diff.
# Measured at factory iter 143, on the 2,700+ -> 3,300+ bump this test rejected.
# Neutralize those three numbers in both slices; every other byte above the marker
# stays frozen (a reworded sentence or a deleted bullet still fails -- verified).
# DIVISION OF LABOUR: this guard decides only WHICH tokens may move. Whether a
# carve-out number is CORRECT stays the sole business of
# tests/test_readme_and_ci_contract.py.
_CARVE_OUT_NUMBERS = (
    re.compile(r"\*\*[\d,]+\+? (?:passing )?tests\*\*"),
    re.compile(r"[\d,]+ context collectors"),
    re.compile(r"[\d,]+ CLI verbs"),
)


def _carve_out_normalized(text: str) -> str:
    """Replace the digits of the three PERMITTED carve-out numbers with ``N``.

    Only the digits inside a matched claim are touched, so every other byte -- prose,
    bullets, badges, ordering -- is still compared byte-for-byte by the caller.
    """
    for pattern in _CARVE_OUT_NUMBERS:
        text = pattern.sub(lambda m: re.sub(r"[\d,]+", "N", m.group(0)), text)
    return text


def test_b9_readme_documents_the_hook_below_the_marker() -> None:
    text = _readme_text()
    protected = _protected_slice(text)
    body = text[len(protected) :]

    assert INSTALL_COMMAND in body, (
        f"expected the literal install command {INSTALL_COMMAND!r} BELOW the marker"
    )
    assert INSTALL_COMMAND not in protected, (
        "the hook documentation must live below the human-owned portfolio intro"
    )
    assert "hooks/pre-commit" in body
    assert BYPASS in body, f"expected the documented bypass {BYPASS!r} in the hook section"
    # "arms the same kinds as CI" -- stated, and the kinds themselves named.
    assert re.search(r"same[^.\n]{0,60}\bCI\b", body), (
        "expected the README to state that the hook arms the same kinds as CI"
    )
    for kind in EXPECTED_ARMED_KINDS:
        assert kind in body, f"expected the armed kind {kind!r} to be named in the README"


def test_b9_human_owned_portfolio_intro_is_byte_identical_to_head() -> None:
    committed = _git("show", "HEAD:README.md")
    if committed.returncode != 0:
        pytest.skip("not a git checkout; the intro slice is unverifiable here")
    head_slice = _protected_slice(committed.stdout)
    # Non-vacuity: if a claim is ever reworded, the normalizer silently degrades to a
    # no-op and this guard re-creates the carve-out deadlock with a mystifying diff.
    unmatched = [p.pattern for p in _CARVE_OUT_NUMBERS if not p.search(head_slice)]
    assert not unmatched, (
        "a carve-out claim was reworded, so this guard has silently stopped permitting "
        f"the number it must permit -- re-derive the pattern(s): {unmatched}"
    )
    assert _carve_out_normalized(_protected_slice(_readme_text())) == _carve_out_normalized(
        head_slice
    ), (
        "the human-owned PORTFOLIO INTRO block (start of file through the marker's "
        "closing line) must never be rewritten by an automated contributor -- only "
        "the three carve-out NUMBERS may change"
    )
