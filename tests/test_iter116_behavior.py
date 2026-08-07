"""Behavior tests for state-dir iteration 109 (ships as commit-seq ``factory iter 116``).

Feature under test: every ``pla`` command the README publishes is runnable AS
PRINTED, the zero-config LLM-free first run on the reader's own checkout is
advertised, and both facts are locked by a guard that DERIVES the LLM-free verb
set from ``cli.py`` instead of hardcoding it.

Why this file is the oracle
The defect this iteration fixes was invisible to a green suite for eight
iterations: ``README.md`` published ``pla run --workspace .`` inside a fenced
bash block -- the single command aimed at the READER's own repo -- and that
command exits 1, because the default provider is ``scripted`` and there is no
default script. It PARSED perfectly the whole time. "Parses" and "runs" are
different claims, so these tests assert the second one: a published command must
either use a verb that never constructs an LLM client, or configure a provider
completely enough to synthesize.

Why the LLM-free set is DERIVED and not written down here
A hardcoded list of ten verbs would be a second copy of the truth, and the copy
would rot the first time a handler grows or loses a ``create_client`` call --
silently, in the safe direction, which is the worst kind. Behavior 3 therefore
partitions the ``_cmd_<verb>`` handlers with ``ast`` and treats an
UNCLASSIFIABLE live verb as a FAILURE: no allowlist, no silent skip. The
membership assertions in behavior 3 are checks ON that derivation, not a
substitute for it.

Why the two derived sets are kept apart on purpose
Today the ten LLM-free verbs are exactly the ten verbs that own ``--json``. That
is a coincidence, not a rule: giving ``scan`` a ``--json`` alias (a queued idea)
would instantly turn a true guard into a false failure in unrelated work. So
nothing here derives one set from the other.

Isolation: black-box. The seams used are (a) reading ``README.md`` as text --
it is the artifact under test, (b) the public ``build_parser()`` /
``main(argv)`` entry points, and (c) parsing ``src/proactive_loop/cli.py`` with
``ast``, which spec behavior 3 REQUIRES and which reads only ``def`` names and
call names, never logic. No implementation source was read while writing this
file; no engineer, reviewer or fix note was opened.

Offline: file reads and in-process CLI calls only. Behavior 7 is the only test
that EXECUTES a verb; it runs ``signals`` (which never builds a client) plus one
fast, deliberately failing ``scan``, inside ``tmp_path``, with every ``PLA_*``
environment variable stripped. No network, no API keys, no writes outside
``tmp_path``.

Every reader here is fail-CLOSED, and each is fired on a known-bad sample in the
same test that uses it: an extractor that silently yielded nothing, a parse
check that could not reject a ghost flag, or an ``ast`` sweep that walked zero
functions would each make these guards pass vacuously, which is strictly worse
than having no guard at all.
"""

from __future__ import annotations

import ast
import contextlib
import io
import os
import shlex
from pathlib import Path
from typing import NamedTuple

import pytest

from proactive_loop.cli import build_parser, main

# --------------------------------------------------------------------------
# Paths and the tester's ground facts -- transcribed from the spec (pm.md),
# never imported from the implementation, so drift in either direction is caught.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
CLI_SOURCE = REPO / "src" / "proactive_loop" / "cli.py"

# The live marker line reads "PORTFOLIO INTRO <em-dash> human-owned"; the spec quotes
# it with ASCII dashes. Match on the stable ASCII prefix only -- the same substring
# tests/test_readme_and_ci_contract.py uses -- so a dash-style edit cannot silently
# disarm this guard.
HUMAN_OWNED_MARKER = "PORTFOLIO INTRO"

# Spec behavior 3: these MUST come out of the derivation on the stated side.
# They are an assertion about the derived partition, not the source of truth.
EXPECTED_LLM_FREE = {
    "signals",
    "collectors",
    "policy",
    "config",
    "tools",
    "providers",
    "runs",
    "explain",
    "trace",
    "diff",
}
EXPECTED_NEEDS_CLIENT = {"scan", "run", "dispatch", "resume", "watch"}

# Spec behavior 8: the advertised own-repo first run, verbatim.
ADVERTISED_FIRST_RUN = "pla signals --workspace ."

# Buckets of behavior 4.
LLM_FREE = "llm_free"
PROVIDER_CONFIGURED = "provider_configured"
NEITHER = "neither"


class Published(NamedTuple):
    """One logical CLI command line published in a fenced README block."""

    lineno: int  # 1-based line of the command's FIRST physical line
    line: str  # backslash-continuations already joined into one line


# --------------------------------------------------------------------------
# Behavior 1 helpers -- fenced-block extraction and continuation joining
# --------------------------------------------------------------------------


def _fence_line_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("```"))


def _fenced_regions(text: str) -> list[list[tuple[int, str]]]:
    """Return the fenced code blocks as lists of ``(lineno, raw_line)``.

    Only FENCED content is returned: inline single-backtick command mentions use
    ``...`` ellipses deliberately and are out of scope for this guard.
    """
    regions: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    inside = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if raw.lstrip().startswith("```"):
            if inside:
                regions.append(current)
                current = []
            inside = not inside
            continue
        if inside:
            current.append((lineno, raw))
    return regions


def _logical_lines(region: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Join trailing-backslash continuations into ONE logical line."""
    out: list[tuple[int, str]] = []
    buffered = ""
    start = 0
    for lineno, raw in region:
        stripped = raw.rstrip()
        if not buffered:
            start = lineno
        if stripped.endswith("\\"):
            buffered = f"{buffered}{stripped[:-1].strip()} "
            continue
        out.append((start, f"{buffered}{stripped.strip()}".strip()))
        buffered = ""
    if buffered:
        out.append((start, buffered.strip()))
    return out


def published_commands(text: str) -> list[Published]:
    """Every logical line in a fenced block that invokes this project's CLI.

    A line qualifies when its FIRST token is ``pla``, or when it starts with
    ``uv run pla``. A ``#`` comment line therefore never qualifies -- which is
    why the README keeps its comments on their own lines, since a trailing
    comment would land in argv and make the parser exit.
    """
    found: list[Published] = []
    for region in _fenced_regions(text):
        for lineno, logical in _logical_lines(region):
            tokens = logical.split()
            if not tokens:
                continue
            if tokens[0] == "pla" or tokens[:3] == ["uv", "run", "pla"]:
                found.append(Published(lineno, logical))
    return found


def argv_of(published: str) -> list[str]:
    """The argv a shell would hand ``pla``, with ``uv run`` and ``pla`` dropped."""
    tokens = shlex.split(published)
    if tokens[:2] == ["uv", "run"]:
        tokens = tokens[2:]
    assert tokens and tokens[0] == "pla", f"not a pla command line: {published!r}"
    return tokens[1:]


def parse_published(published: str) -> object:
    """Parse a published line with the LIVE parser; ``SystemExit`` propagates."""
    parser = build_parser()
    with (
        contextlib.redirect_stderr(io.StringIO()),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        return parser.parse_args(argv_of(published))


def live_verbs() -> set[str]:
    """The subcommand names the live parser actually exposes."""
    parser = build_parser()
    subparser_actions = [
        action
        for action in parser._subparsers._group_actions  # type: ignore[union-attr]
        if hasattr(action, "choices")
    ]
    assert len(subparser_actions) == 1, (
        f"expected exactly one subparsers action, got {len(subparser_actions)}"
    )
    return set(subparser_actions[0].choices)


# --------------------------------------------------------------------------
# Behavior 3 helpers -- derive the LLM-free verb set from cli.py with ast
# --------------------------------------------------------------------------


def _calls_create_client(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Name) and callee.id == "create_client":
            return True
        if isinstance(callee, ast.Attribute) and callee.attr == "create_client":
            return True
    return False


def derive_handler_partition() -> dict[str, bool]:
    """Map ``verb -> handler constructs an LLM client``, derived from cli.py."""
    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"))
    partition: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_cmd_"):
            continue
        verb = node.name[len("_cmd_") :]
        assert verb not in partition, f"duplicate handler for verb {verb!r}"
        partition[verb] = _calls_create_client(node)
    return partition


def derive_llm_free_verbs() -> set[str]:
    return {verb for verb, uses_client in derive_handler_partition().items() if not uses_client}


# --------------------------------------------------------------------------
# Behavior 4 helper -- classify a command line into exactly one bucket
# --------------------------------------------------------------------------


def classify(published: str, llm_free: set[str]) -> str:
    """Bucket a published command: ``llm_free`` / ``provider_configured`` / ``neither``.

    Classification reads the PARSED argparse namespace, never a resolved
    ``Settings``: at parser level ``--provider`` defaults to ``None``, which is
    exactly what makes the pre-fix ``pla run --workspace .`` classify as
    ``neither``. Resolving settings would read ambient ``PLA_PROVIDER`` or a
    config file and could green-wash this guard on a developer's machine.
    """
    namespace = parse_published(published)
    verb = getattr(namespace, "command", None)
    if verb in llm_free:
        return LLM_FREE
    provider = getattr(namespace, "provider", None)
    if not provider:
        return NEITHER
    if provider == "scripted" and not getattr(namespace, "scripted_responses", None):
        return NEITHER
    return PROVIDER_CONFIGURED


# --------------------------------------------------------------------------
# Behavior 6 helper -- values a command line explicitly gives to an option
# --------------------------------------------------------------------------


def explicit_option_values(published: str, option: str) -> list[str]:
    """Values the LINE ITSELF passes to ``option`` (``--x V`` and ``--x=V``).

    Read from argv, not from the namespace, so an option's DEFAULT is never
    mistaken for something the README published.
    """
    argv = argv_of(published)
    values: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == option and index + 1 < len(argv):
            values.append(argv[index + 1])
            index += 2
            continue
        if token.startswith(f"{option}="):
            values.append(token.split("=", 1)[1])
        index += 1
    return values


def _is_placeholder(value: str) -> bool:
    return any(ch in value for ch in "<>$") or value.isupper()


def _is_repo_relative(value: str) -> bool:
    if value in {".", ".."} or _is_placeholder(value):
        return False
    if os.path.isabs(value) or value.startswith("~"):
        return False
    return True


# --------------------------------------------------------------------------
# Behavior 1 -- the extractor really extracts, and joins continuations
# --------------------------------------------------------------------------


def test_behavior1_extractor_yields_joined_single_line_pla_commands() -> None:
    text = README.read_text(encoding="utf-8")

    assert _fence_line_count(text) % 2 == 0, (
        "odd number of ``` fences in README.md -- an unterminated fence would make "
        "this whole guard silently skip content"
    )

    commands = published_commands(text)
    assert len(commands) >= 3, (
        f"expected at least 3 published pla command lines, got {len(commands)}: "
        f"{[c.line for c in commands]}"
    )
    for command in commands:
        assert "\n" not in command.line, f"unjoined continuation in {command!r}"
        assert command.line.startswith("pla ") or command.line.startswith("uv run pla "), (
            f"yielded a non-CLI line: {command!r}"
        )
        assert "\\" not in command.line, (
            f"a trailing backslash survived joining in {command!r}"
        )

    # Fail-closed: joining must actually happen. At least one published command
    # is written across several physical lines, so at least one logical line has
    # to be longer than any single physical line of the README.
    multiline = [c for c in commands if len(c.line.split()) >= 6]
    assert multiline, (
        "no published command has 6+ tokens -- continuation joining is not working, "
        f"got {[c.line for c in commands]}"
    )

    # Fire the helper on a known-bad/known-good synthetic sample: a comment line
    # must NOT be yielded, and a 3-physical-line command MUST come back as one.
    synthetic = "\n".join(
        [
            "prose is ignored",
            "```bash",
            "# pla run is only a comment here",
            "pla run \\",
            "  --workspace examples/fixture_workspace \\",
            "  --provider scripted",
            "```",
            "`pla scan ...` inline mentions are out of scope",
        ]
    )
    synthetic_commands = published_commands(synthetic)
    assert [c.line for c in synthetic_commands] == [
        "pla run --workspace examples/fixture_workspace --provider scripted"
    ], synthetic_commands


# --------------------------------------------------------------------------
# Behavior 2 -- every published command parses against the live parser
# --------------------------------------------------------------------------


def test_behavior2_every_published_command_parses_and_names_a_live_verb() -> None:
    verbs = live_verbs()
    assert len(verbs) >= 10, f"live parser exposes suspiciously few verbs: {sorted(verbs)}"

    for command in published_commands(README.read_text(encoding="utf-8")):
        try:
            namespace = parse_published(command.line)
        except SystemExit as exc:  # pragma: no cover - only on a broken README
            pytest.fail(
                f"README.md:{command.lineno} does not parse against the live parser "
                f"(SystemExit {exc.code}): {command.line!r}"
            )
        verb = getattr(namespace, "command", None)
        assert verb in verbs, (
            f"README.md:{command.lineno} names verb {verb!r}, which the live parser "
            f"does not expose: {sorted(verbs)}"
        )

    # Fail-closed: the same helper must REJECT a ghost flag, or "it parses" is
    # not evidence of anything.
    with pytest.raises(SystemExit):
        parse_published("pla signals --nope")


# --------------------------------------------------------------------------
# Behavior 3 -- the LLM-free verb set is DERIVED from cli.py, fail-closed
# --------------------------------------------------------------------------


def test_behavior3_llm_free_verb_set_is_derived_from_cli_and_fails_closed() -> None:
    partition = derive_handler_partition()
    assert len(partition) >= 10, (
        f"ast sweep found only {len(partition)} _cmd_* handlers in {CLI_SOURCE} -- "
        "a sweep that walks (almost) nothing would pass every membership check "
        "below vacuously"
    )

    llm_free = derive_llm_free_verbs()
    needs_client = {verb for verb, uses in partition.items() if uses}

    missing_free = sorted(EXPECTED_LLM_FREE - llm_free)
    assert not missing_free, (
        f"these verbs are advertised as needing no provider but their handlers "
        f"construct an LLM client: {missing_free}"
    )
    leaked = sorted(EXPECTED_NEEDS_CLIENT & llm_free)
    assert not leaked, (
        f"these synthesis verbs were derived as LLM-free, so the derivation is "
        f"broken: {leaked}"
    )
    missing_client = sorted(EXPECTED_NEEDS_CLIENT - needs_client)
    assert not missing_client, (
        f"these verbs no longer call create_client; the README's split between "
        f"perception and synthesis is stale: {missing_client}"
    )

    # Every live verb must resolve to exactly one classified handler. No silent
    # skip and no allowlist: an unclassifiable verb is a FAILURE, because it is
    # precisely the verb whose runnability nobody would be checking.
    unclassified = sorted(
        verb for verb in live_verbs() if verb.replace("-", "_") not in partition
    )
    assert not unclassified, (
        f"live verbs with no _cmd_* handler found by the ast sweep: {unclassified}"
    )


# --------------------------------------------------------------------------
# Behavior 4 -- no published command is unrunnable
# --------------------------------------------------------------------------


def test_behavior4_no_published_command_falls_into_the_unrunnable_bucket() -> None:
    llm_free = derive_llm_free_verbs()
    commands = published_commands(README.read_text(encoding="utf-8"))
    buckets: dict[str, list[str]] = {LLM_FREE: [], PROVIDER_CONFIGURED: [], NEITHER: []}

    for command in commands:
        bucket = classify(command.line, llm_free)
        assert bucket in buckets, f"unknown bucket {bucket!r}"
        buckets[bucket].append(f"README.md:{command.lineno} {command.line}")

    assert not buckets[NEITHER], (
        "the README publishes commands that cannot run as printed -- they use a "
        "synthesis verb without a usable provider:\n  " + "\n  ".join(buckets[NEITHER])
    )
    classified = sum(len(v) for v in buckets.values())
    assert classified == len(commands), (
        f"{len(commands) - classified} published command(s) were left unclassified"
    )
    assert buckets[LLM_FREE] and buckets[PROVIDER_CONFIGURED], (
        "expected the README to publish BOTH an LLM-free command and a "
        f"provider-configured one; got {buckets}"
    )


# --------------------------------------------------------------------------
# Behavior 5 -- the guard demonstrably fires on the defect it was written for
# --------------------------------------------------------------------------


def test_behavior5_classifier_fires_on_the_pre_fix_command() -> None:
    llm_free = derive_llm_free_verbs()

    # The literal string README.md published for eight iterations. It PARSES,
    # and it exits 1 at runtime.
    assert classify("pla run --workspace .", llm_free) == NEITHER

    # Naming the scripted provider without a script is the same defect wearing
    # a flag: the CLI still stops with "no scripted_responses_path".
    assert classify("pla run --workspace . --provider scripted", llm_free) == NEITHER

    # And the advertised replacement is recognised as free.
    assert classify(ADVERTISED_FIRST_RUN, llm_free) == LLM_FREE

    # A fully configured scripted run is the other passing shape.
    assert (
        classify(
            "pla run --workspace examples/fixture_workspace --provider scripted "
            "--scripted-responses examples/scripted_responses.json",
            llm_free,
        )
        == PROVIDER_CONFIGURED
    )


# --------------------------------------------------------------------------
# Behavior 6 -- repo-relative paths named in published commands exist
# --------------------------------------------------------------------------


def test_behavior6_repo_relative_paths_in_published_commands_exist() -> None:
    commands = published_commands(README.read_text(encoding="utf-8"))
    checked = 0

    for command in commands:
        for value in explicit_option_values(command.line, "--scripted-responses"):
            if _is_placeholder(value):
                continue
            checked += 1
            assert (REPO / value).is_file(), (
                f"README.md:{command.lineno} passes --scripted-responses {value!r}, "
                "which does not exist in the repo, so the command is not runnable "
                "as printed"
            )
        for value in explicit_option_values(command.line, "--workspace"):
            if not _is_repo_relative(value):
                continue
            checked += 1
            assert (REPO / value).is_dir(), (
                f"README.md:{command.lineno} passes --workspace {value!r}, which is "
                "not a directory in the repo"
            )

    # Fail-closed: if the extractor or the option reader silently returned
    # nothing, every assertion above would be skipped and this test would be a
    # no-op that reads as green.
    assert checked >= 2, (
        f"only {checked} repo-relative path(s) checked across {len(commands)} "
        "published commands -- the option reader is not seeing the published values"
    )

    # NOTE (deliberate non-generalization): --state-dir is NOT checked. The demo
    # line names `.pla_runs`, a gitignored OUTPUT directory that does not exist
    # in a fresh clone, and CI runs `uv run pytest` BEFORE `make demo`. A guard
    # over --state-dir would pass locally and go red in CI.


# --------------------------------------------------------------------------
# Behavior 7 -- the advertised zero-config path really is zero-config
# --------------------------------------------------------------------------


def test_behavior7_signals_runs_with_zero_config_while_scan_demands_a_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "someones_repo"
    workspace.mkdir()
    (workspace / "app.py").write_text(
        '"""A stranger\'s module."""\n\n\n'
        "def handler() -> None:\n"
        "    # TODO: wire this up to the real backend\n"
        "    return None\n",
        encoding="utf-8",
    )

    # Zero config means zero config: no PLA_* environment, and a cwd with no
    # project config file for the CLI to discover.
    for name in [key for key in os.environ if key.startswith("PLA_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    signals_rc = main(["signals", "--workspace", str(workspace)])
    signals_out = capsys.readouterr()
    assert signals_rc == 0, (
        f"`pla signals` is advertised as needing no provider, key or config, but it "
        f"exited {signals_rc}. stderr:\n{signals_out.err}"
    )
    signal_lines = [line for line in signals_out.out.splitlines() if line.strip()]
    assert signal_lines, "`pla signals` exited 0 but printed no signal lines"
    assert "todo" in signals_out.out.lower(), (
        "the throwaway workspace has a TODO comment, so at least one perceived "
        f"signal should mention it; stdout was:\n{signals_out.out}"
    )

    scan_rc = main(["scan", "--workspace", str(workspace)])
    scan_out = capsys.readouterr()
    assert scan_rc != 0, (
        "`pla scan` synthesizes goals, so with no provider configured it must fail "
        f"loudly; it exited {scan_rc}. stdout:\n{scan_out.out}"
    )
    assert "provider" in scan_out.err.lower(), (
        "the failure must name `provider` so a reader knows what to supply; stderr "
        f"was:\n{scan_out.err}"
    )


# --------------------------------------------------------------------------
# Behavior 8 -- the README says both halves, below the human-owned marker
# --------------------------------------------------------------------------


def test_behavior8_readme_advertises_both_halves_below_the_human_owned_marker() -> None:
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()

    marker_lines = [i for i, line in enumerate(lines, start=1) if HUMAN_OWNED_MARKER in line]
    assert len(marker_lines) == 1, (
        f"expected exactly one {HUMAN_OWNED_MARKER!r} marker, found {marker_lines}"
    )
    marker = marker_lines[0]

    commands = published_commands(text)

    # (a) the advertised own-repo first run is published verbatim
    published_lines = [command.line for command in commands]
    assert ADVERTISED_FIRST_RUN in published_lines, (
        f"README.md does not publish {ADVERTISED_FIRST_RUN!r} in a fenced block; "
        f"published commands were {published_lines}"
    )

    # (b) every published `run` line configures a provider AND a script, so the
    #     retry-tuning example is runnable as printed
    run_commands = [c for c in commands if argv_of(c.line)[0] == "run"]
    assert run_commands, "README.md publishes no `pla run` command at all"
    for command in run_commands:
        assert "--provider" in command.line, (
            f"README.md:{command.lineno} publishes a `pla run` with no --provider: "
            f"{command.line!r}"
        )
        assert "--scripted-responses" in command.line, (
            f"README.md:{command.lineno} publishes a `pla run` with no "
            f"--scripted-responses: {command.line!r}"
        )

    # (c) the README states plainly that synthesis needs a provider
    below_marker = "\n".join(lines[marker:])
    assert "requires a provider" in below_marker or "require a provider" in below_marker, (
        "the README must say plainly that goal synthesis requires a provider"
    )
    for verb in sorted(EXPECTED_NEEDS_CLIENT):
        assert f"`{verb}`" in below_marker, (
            f"the synthesis verb {verb!r} is not named in the reference sections"
        )

    # (d) the human-owned intro is untouched in SHAPE: this iteration's change is
    #     entirely below the marker, and the intro still has its four elements.
    for command in commands:
        assert command.lineno > marker, (
            f"a published CLI command appears ABOVE the human-owned marker "
            f"(README.md:{command.lineno}) -- the portfolio intro must not be "
            "restructured by an automated contributor"
        )
    intro = "\n".join(lines[: marker - 1])
    assert intro.lstrip().startswith("# "), "the intro no longer starts with the title"
    assert "What this project demonstrates" in intro, (
        "the intro's 'What this project demonstrates' section is gone"
    )
    assert "img.shields.io" in intro, "the intro's badges are gone"
