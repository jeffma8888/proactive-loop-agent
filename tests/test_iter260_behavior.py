"""Iteration-291 black-box behavior suite (ISOLATED tester).

Module name DERIVED FROM THE REPO, not from the state dir: the highest shipped
``tests/test_iterNN_behavior.py`` is 259, so 260 is the free name, and
``git cat-file -e HEAD:tests/test_iter260_behavior.py`` FAILED ("does not exist
in 'HEAD'") before this file was written. The commit tag stays
``(foundry iter 291)``.

WHAT THIS ITERATION CHANGES.  ``src/proactive_loop/cli.py`` hand-copied the same
five-line ``--json``-or-human dispatch tail once per verb::

    if args.json:
        print(json.dumps(<X>_json_payload(...), indent=2))
    else:
        print(_render_<X>(...))

This iteration collapses SIX of those tails -- ``policy --check-goal``,
``policy`` (catalog), ``config``, ``tools``, ``collectors``, ``providers`` --
behind ONE ``_emit(*, as_json, payload, human)`` seam, so the published
"``--json`` stdout is exactly one JSON object with no human trailer" contract has
a single definition instead of six restatements.  Nothing about any payload
schema, key order, ``indent``, or any human renderer's text may move.

WHY THE ORACLE IS SHAPED THIS WAY.  A refactor whose whole promise is "zero
observable change" has two failure modes that a naive test cannot see.

* **Behavior drift.**  Reading the source diff proves the substrings moved, not
  that behavior survived, so byte-identity was proven against the HEAD blob at
  tester time (see ``HEAD_BLOB_SHA`` below) and is re-proven here in a form that
  is durable AFTER the commit lands, when ``HEAD`` and the worktree are the same
  tree and a HEAD-vs-worktree diff would pass VACUOUSLY.  The durable form is
  self-relative: ``--json`` stdout must round-trip through
  ``json.dumps(obj, indent=2) + "\n"`` EXACTLY (that single assertion pins one
  object, ``indent=2``, no trailer, no banner and no leading noise at once), and
  the human branch must stay non-JSON and deterministic.
* **Eager evaluation.**  A seam that takes already-computed VALUES instead of
  zero-argument CALLABLES builds both renderings on every call.  ``rc == 0`` is a
  weak probe for that -- it passes even if the seam swallowed an exception or
  emitted a truncated document -- so behaviors 4a/4b patch the DISCARDED side to
  raise and assert the surviving stdout is BYTE-IDENTICAL to the unpatched
  capture taken in the same test.

ISOLATION CONTRACT (honored).  Written from this iteration's PM spec (Expected
Behaviors 1-8) and the public CLI surface only.  Behaviors 1-4 drive
``proactive_loop.cli.main(argv)`` and assert on the exit code and captured
stdout; behaviors 5-8 read the SHIPPED ``cli.py`` as TEXT and reason over its
``ast`` (a structural census resolved by node shape and by name, never by line
number) plus ``pyproject.toml``.  No implementation source was read as prose by
the author, no engineer or reviewer note was read, and ``git diff`` was never
consulted.  Conventions -- the ``_run`` / ``capsys`` driver, the
``clear_pla_env`` autouse guard, the ``REPO = Path(__file__).resolve().parents[1]``
source locator, an ``ast`` census over the shipped module -- mirror the shipped
suites ``tests/test_iter{95,219,258,259}_behavior.py``.

NO AMBIENT STATE.  Every assertion here reads either captured stdout from an
in-process ``main()`` call or a TRACKED repo file (``cli.py``, ``pyproject.toml``).
Nothing touches ``mtime``, no gitignored path, no ``examples/`` fixture, no
network, no provider and no LLM client -- so a throwaway fresh clone (the preship
gate) exercises exactly what this working tree does.
"""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest

from proactive_loop import cli
from proactive_loop.cli import main
from tests.test_iter125_behavior import clear_pla_env

REPO: Final[Path] = Path(__file__).resolve().parents[1]
CLI_SRC: Final[Path] = REPO / "src" / "proactive_loop" / "cli.py"
PYPROJECT: Final[Path] = REPO / "pyproject.toml"

#: The HEAD blob this iteration's output was diffed against at tester time.
#: All 16 invocations below (6 verbs x {--json, human} + 2 kinds x {--json, human})
#: were captured twice -- once with ``sys.path`` pointed at a
#: ``git archive c91e5ff src`` extraction, once at the worktree -- and compared as
#: ``(rc, stdout, stderr)`` triples: 16/16 byte-identical, 0 diffs.
HEAD_BLOB_SHA: Final[str] = "c91e5ff"

#: A valid ``CandidateGoal`` literal for ``policy --check-goal``.  ``id`` is always
#: supplied because ``CandidateGoal.id`` is auto-generated when omitted, which
#: would make stdout nondeterministic (the ``tests/test_iter219_behavior.py`` idiom).
GOAL: Final[str] = (
    '{"id":"g3","title":"t","impact":5,"urgency":4,"confidence":1.0,"effort_weight":1.0}'
)

#: The SIX call sites this iteration consolidates, as argv PREFIXES.  ``policy``
#: pays for it twice: once for ``--check-goal``, once for the standing catalog.
SIX_SITES: Final[tuple[tuple[str, list[str]], ...]] = (
    ("policy_check_goal", ["policy", "--check-goal", GOAL]),
    ("policy_catalog", ["policy"]),
    ("config", ["config"]),
    ("tools", ["tools"]),
    ("collectors", ["collectors"]),
    ("providers", ["providers"]),
)

#: Two distinct valid ``--kind`` values, from ``pla collectors --json`` itself.
KINDS: Final[tuple[str, str]] = ("broken_link", "license")

#: The new seam's name and the exact number of places that may call it.
EMITTER: Final[str] = "_emit"
EXPECTED_EMIT_CALL_SITES: Final[int] = 6

#: Behavior 5.  The five renderers whose open-coded dispatch tail must be GONE.
#: (``_render_explain`` is deliberately absent: HEAD had TWO explain tails -- the
#: ``explain`` verb's and ``policy --check-goal``'s -- and only the latter is in
#: scope, so exactly one must survive.)
CONSOLIDATED_RENDERERS: Final[frozenset[str]] = frozenset(
    {"_render_policy", "_render_config", "_render_tools", "_render_collectors",
     "_render_providers"}
)

#: Behavior 6, "no collateral consolidation".  The dispatch tails that are OUT OF
#: SCOPE and must therefore still be open-coded, one each.  ``prune``/``runs``/
#: ``verify``/``diff``/``trend`` are not in five-line correspondence, and
#: ``explain``'s own tail is the survivor described above.
SURVIVING_RENDERERS: Final[frozenset[str]] = frozenset(
    {"_render_prune", "_render_runs", "_render_explain", "_render_verify",
     "_render_diff", "_render_trend"}
)

#: Behavior 6.  ``cli.py`` carried 21 ``print(json.dumps(`` occurrences at
#: ``HEAD_BLOB_SHA``; exactly six become ``_emit`` calls, so 15 remain.  A ratchet:
#: a later iteration that consolidates more must move this number deliberately.
EXPECTED_PRINT_JSON_DUMPS: Final[int] = 15

#: Behavior 6.  The three ``_cmd_run`` sites that write to ``result_stream``
#: instead of stdout are NOT in correspondence and must be untouched, verbatim.
RESULT_STREAM_SITE: Final[str] = "print(json.dumps(payload, indent=2), file=result_stream)"
EXPECTED_RESULT_STREAM_SITES: Final[int] = 3

#: Behavior 7.  The seam's exact signature, in order.
EMITTER_PARAMS: Final[tuple[tuple[str, str], ...]] = (
    ("as_json", "bool"),
    ("payload", "Callable[[], object]"),
    ("human", "Callable[[], str]"),
)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clean_pla_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every ``PLA_*`` override cleared: these tests assert DOCUMENTED DEFAULTS."""
    clear_pla_env(monkeypatch)


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Drive ``main(argv)`` and return ``(rc, stdout, stderr)``."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _cli_text() -> str:
    return CLI_SRC.read_text(encoding="utf-8")


def _cli_tree() -> ast.Module:
    return ast.parse(_cli_text())


def _print_arg(stmts: list[ast.stmt]) -> ast.expr | None:
    """The single argument of a lone ``print(<x>)`` statement, else ``None``."""
    if len(stmts) != 1:
        return None
    stmt = stmts[0]
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return None
    call = stmt.value
    if not (isinstance(call.func, ast.Name) and call.func.id == "print"):
        return None
    if len(call.args) != 1 or call.keywords:
        return None
    return call.args[0]


def _dispatch_tail_census(tree: ast.Module) -> list[tuple[int, str]]:
    """Every OPEN-CODED ``--json``-or-human dispatch tail, as ``(lineno, renderer)``.

    Structural, so indentation and line wrapping cannot hide a hit: an ``if``
    whose test is ``args.json``, whose body is exactly ``print(json.dumps(<p>,
    indent=2))`` and whose ``else`` is exactly ``print(_render_*(...))``.
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (
            isinstance(test, ast.Attribute)
            and test.attr == "json"
            and isinstance(test.value, ast.Name)
            and test.value.id == "args"
        ):
            continue
        json_arg = _print_arg(node.body)
        human_arg = _print_arg(node.orelse)
        if json_arg is None or human_arg is None:
            continue
        if not (
            isinstance(json_arg, ast.Call)
            and isinstance(json_arg.func, ast.Attribute)
            and json_arg.func.attr == "dumps"
            and isinstance(json_arg.func.value, ast.Name)
            and json_arg.func.value.id == "json"
            and any(
                kw.arg == "indent" and getattr(kw.value, "value", None) == 2
                for kw in json_arg.keywords
            )
        ):
            continue
        if not (
            isinstance(human_arg, ast.Call)
            and isinstance(human_arg.func, ast.Name)
            and human_arg.func.id.startswith("_render_")
        ):
            continue
        hits.append((node.lineno, human_arg.func.id))
    return hits


def _emitter_def(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == EMITTER
    ]


def _emitter_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == EMITTER
    ]


def _is_json_document(text: str) -> bool:
    try:
        json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    return True


# --------------------------------------------------------------------------- #
# Behavior 1 -- `--json` stdout is exactly ONE JSON object, no trailer, rc 0
# --------------------------------------------------------------------------- #


def test_b01_json_stdout_is_one_object_with_no_trailer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`json.loads` accepts the FULL stdout, and it is `indent=2` with no extras.

    Round-tripping through ``json.dumps(obj, indent=2) + "\\n"`` pins four things
    in one assertion that a "starts with {" check would miss: one object (not a
    stream), ``indent=2`` (not ``indent=4`` and not compact), no human trailer
    appended after the document, and no banner printed before it.
    """
    for _name, prefix in SIX_SITES:
        rc, out, err = _run([*prefix, "--json"], capsys)
        assert rc == 0, f"`pla {' '.join(prefix)} --json` must exit 0; stderr={err!r}"
        obj: Any = json.loads(out)
        assert isinstance(obj, dict), (
            f"`pla {' '.join(prefix)} --json` must emit ONE JSON object; "
            f"got {type(obj).__name__}"
        )
        assert out == json.dumps(obj, indent=2) + "\n", (
            f"`pla {' '.join(prefix)} --json` stdout must be exactly the indent=2 document "
            f"plus one newline -- a human trailer, a banner or a changed indent breaks the "
            f"published machine contract.\nstdout={out!r}"
        )


def test_b01b_json_stdout_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    """Two identical invocations produce identical bytes (offline determinism)."""
    for _name, prefix in SIX_SITES:
        first = _run([*prefix, "--json"], capsys)
        second = _run([*prefix, "--json"], capsys)
        assert first == second, f"`pla {' '.join(prefix)} --json` is nondeterministic"


# --------------------------------------------------------------------------- #
# Behavior 2 -- the human branch is untouched
# --------------------------------------------------------------------------- #


def test_b02_human_branch_exits_zero_and_is_not_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without ``--json`` the verb prints human text, exits 0, and is NOT JSON.

    "Not JSON" is the load-bearing half: a seam that ignored ``as_json`` and always
    took the payload branch would still exit 0 with valid output.
    """
    for _name, prefix in SIX_SITES:
        rc, out, err = _run(list(prefix), capsys)
        assert rc == 0, f"`pla {' '.join(prefix)}` must exit 0; stderr={err!r}"
        assert out.strip(), f"`pla {' '.join(prefix)}` must print something"
        assert not _is_json_document(out), (
            f"`pla {' '.join(prefix)}` (no --json) must print the HUMAN rendering, but "
            f"its stdout parses as JSON -- the seam took the wrong branch.\nstdout={out!r}"
        )
        assert out.endswith("\n"), f"`pla {' '.join(prefix)}` must end with a newline"


def test_b02b_human_and_json_branches_differ(capsys: pytest.CaptureFixture[str]) -> None:
    """The two branches are genuinely different renderings for all six sites."""
    for _name, prefix in SIX_SITES:
        _rc_h, human, _e1 = _run(list(prefix), capsys)
        _rc_j, as_json, _e2 = _run([*prefix, "--json"], capsys)
        assert human != as_json, (
            f"`pla {' '.join(prefix)}` and `... --json` must not be identical"
        )


def test_b02c_human_branch_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    for _name, prefix in SIX_SITES:
        assert _run(list(prefix), capsys) == _run(list(prefix), capsys), (
            f"`pla {' '.join(prefix)}` is nondeterministic"
        )


# --------------------------------------------------------------------------- #
# Behavior 3 -- `args.kind` is still threaded to BOTH sides
# --------------------------------------------------------------------------- #


def test_b03_kind_filter_reaches_the_json_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``collectors --json --kind K`` is a non-empty STRICT subset, all of kind K.

    The whole risk of a seam that forgets an argument is that ``args.kind`` stops
    reaching the payload builder and the filter silently becomes a no-op, which a
    "valid JSON" check cannot see.
    """
    _rc_all, all_out, _e = _run(["collectors", "--json"], capsys)
    every = json.loads(all_out)["collectors"]
    for kind in KINDS:
        rc, out, err = _run(["collectors", "--json", "--kind", kind], capsys)
        assert rc == 0, f"`pla collectors --json --kind {kind}` must exit 0; stderr={err!r}"
        some = json.loads(out)["collectors"]
        assert some, f"--kind {kind} must match at least one collector"
        assert len(some) < len(every), (
            f"--kind {kind} must FILTER: got all {len(every)} collectors back, so the "
            f"kind never reached the payload builder"
        )
        assert {entry["kind"] for entry in some} == {kind}, (
            f"every entry must be of kind {kind!r}; got {[e['kind'] for e in some]}"
        )


def test_b03b_kind_filter_reaches_the_human_renderer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``collectors --kind K`` filters the HUMAN catalog too, and names ``K``."""
    _rc_all, all_out, _e = _run(["collectors"], capsys)
    for kind in KINDS:
        rc, out, err = _run(["collectors", "--kind", kind], capsys)
        assert rc == 0, f"`pla collectors --kind {kind}` must exit 0; stderr={err!r}"
        assert out.strip(), "the filtered human catalog must not be empty"
        assert len(out) < len(all_out), (
            f"`pla collectors --kind {kind}` must be SHORTER than the full catalog "
            f"({len(out)} vs {len(all_out)} chars) -- the kind never reached the renderer"
        )
        assert kind in out, f"the filtered human catalog must name {kind!r}; got {out!r}"


# --------------------------------------------------------------------------- #
# Behavior 4 -- the branch NOT taken does NO work (lazy callables)
# --------------------------------------------------------------------------- #

#: Three of the six sites, each with the payload builder and renderer name whose
#: EVALUATION must be skipped when the other branch wins.  ``policy`` is excluded
#: only because it routes two different payload builders through one verb.
LAZY_SITES: Final[tuple[tuple[str, list[str], str, str], ...]] = (
    ("collectors", ["collectors"], "_collectors_json_payload", "_render_collectors"),
    ("tools", ["tools"], "_tools_json_payload", "_render_tools"),
    ("providers", ["providers"], "_providers_json_payload", "_render_providers"),
)


def _boom(*_args: object, **_kwargs: object) -> Any:
    raise AssertionError("the discarded branch was EVALUATED -- the seam is not lazy")


def test_b04a_json_branch_never_evaluates_the_human_renderer(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the renderer patched to raise, ``--json`` output is BYTE-IDENTICAL.

    ``rc == 0`` alone is a weak oracle: it also passes if the seam swallowed the
    exception or emitted a truncated document.  Comparing against the unpatched
    capture taken in this same test makes the probe decisive.
    """
    for _name, prefix, _payload_fn, render_fn in LAZY_SITES:
        _rc0, baseline, _e0 = _run([*prefix, "--json"], capsys)
        with monkeypatch.context() as patched:
            patched.setattr(cli, render_fn, _boom, raising=True)
            rc, out, err = _run([*prefix, "--json"], capsys)
        assert rc == 0, (
            f"`pla {' '.join(prefix)} --json` must not evaluate {render_fn}; "
            f"rc={rc}, stderr={err!r}"
        )
        assert out == baseline, (
            f"`pla {' '.join(prefix)} --json` changed when {render_fn} was patched "
            f"({len(out)} vs {len(baseline)} chars) -- the discarded branch is being "
            f"evaluated, or its failure is being swallowed"
        )
        assert json.loads(out), "the JSON document must still be complete"


def test_b04b_human_branch_never_evaluates_the_json_payload(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the payload builder patched to raise, human output is BYTE-IDENTICAL."""
    for _name, prefix, payload_fn, _render_fn in LAZY_SITES:
        _rc0, baseline, _e0 = _run(list(prefix), capsys)
        with monkeypatch.context() as patched:
            patched.setattr(cli, payload_fn, _boom, raising=True)
            rc, out, err = _run(list(prefix), capsys)
        assert rc == 0, (
            f"`pla {' '.join(prefix)}` must not evaluate {payload_fn}; "
            f"rc={rc}, stderr={err!r}"
        )
        assert out == baseline, (
            f"`pla {' '.join(prefix)}` changed when {payload_fn} was patched "
            f"({len(out)} vs {len(baseline)} chars) -- the discarded branch is evaluated"
        )


def test_b04c_the_patch_really_would_fire(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """NON-VACUITY: the same patch DOES break the branch that is supposed to run.

    Without this, behaviors 4a/4b could both pass against a CLI that had stopped
    calling either function at all.
    """
    monkeypatch.setattr(cli, "_render_collectors", _boom, raising=True)
    with pytest.raises(AssertionError, match="was EVALUATED"):
        _run(["collectors"], capsys)


# --------------------------------------------------------------------------- #
# Behavior 5 -- ONE definition, six call sites, zero surviving copies
# --------------------------------------------------------------------------- #


def test_b05a_emitter_is_defined_exactly_once() -> None:
    defs = _emitter_def(_cli_tree())
    assert len(defs) == 1, (
        f"`{EMITTER}` must be defined EXACTLY once in cli.py; found {len(defs)} at lines "
        f"{[d.lineno for d in defs]}"
    )


def test_b05b_emitter_has_exactly_six_call_sites() -> None:
    calls = _emitter_calls(_cli_tree())
    assert len(calls) == EXPECTED_EMIT_CALL_SITES, (
        f"`{EMITTER}` must be called at exactly {EXPECTED_EMIT_CALL_SITES} sites "
        f"(policy --check-goal, policy, config, tools, collectors, providers); found "
        f"{len(calls)} at lines {sorted(c.lineno for c in calls)}"
    )


def test_b05c_emitter_is_always_called_with_all_three_keywords_only() -> None:
    """Positional use would defeat the keyword-only contract, so pin the call shape."""
    for call in _emitter_calls(_cli_tree()):
        assert not call.args, (
            f"`{EMITTER}` call at line {call.lineno} passes a POSITIONAL argument; the "
            f"seam is keyword-only"
        )
        assert {kw.arg for kw in call.keywords} == {name for name, _ in EMITTER_PARAMS}, (
            f"`{EMITTER}` call at line {call.lineno} must pass exactly "
            f"{sorted(n for n, _ in EMITTER_PARAMS)}; got {sorted(str(kw.arg) for kw in call.keywords)}"
        )


def test_b05d_the_six_consolidated_dispatch_tails_are_gone() -> None:
    """No open-coded tail may remain for any of the five consolidated renderers."""
    renderers = {renderer for _line, renderer in _dispatch_tail_census(_cli_tree())}
    leftovers = sorted(renderers & CONSOLIDATED_RENDERERS)
    assert not leftovers, (
        f"these renderers still have a hand-copied `if args.json:` dispatch tail, so the "
        f"contract is still restated more than once: {leftovers}"
    )


def test_b05e_the_json_payload_arguments_are_still_threaded() -> None:
    """Each ``_emit`` site passes zero-arg callables, not pre-computed values.

    A ``lambda:``/``partial`` wrapper (or a nested ``def``) is what makes laziness
    possible at all; a bare call expression would be evaluated at the call site and
    behavior 4 would be unachievable.
    """
    lazy_shapes = (ast.Lambda, ast.Name, ast.Attribute)
    for call in _emitter_calls(_cli_tree()):
        for kw in call.keywords:
            if kw.arg in {"payload", "human"}:
                assert isinstance(kw.value, lazy_shapes) or (
                    isinstance(kw.value, ast.Call)
                    and isinstance(kw.value.func, ast.Attribute)
                    and kw.value.func.attr == "partial"
                ), (
                    f"`{EMITTER}(... {kw.arg}=...)` at line {call.lineno} must be a "
                    f"deferred zero-argument callable, not an already-evaluated value; "
                    f"got {ast.dump(kw.value)[:120]}"
                )


# --------------------------------------------------------------------------- #
# Behavior 6 -- no collateral consolidation
# --------------------------------------------------------------------------- #


def test_b06a_print_json_dumps_count_fell_by_exactly_six() -> None:
    text = _cli_text()
    found = text.count("print(json.dumps(")
    assert found == EXPECTED_PRINT_JSON_DUMPS, (
        f"cli.py must carry exactly {EXPECTED_PRINT_JSON_DUMPS} `print(json.dumps(` "
        f"occurrences after this iteration (21 at {HEAD_BLOB_SHA} minus the six "
        f"consolidated sites); found {found}. If a later iteration consolidates more, "
        f"move this ratchet deliberately."
    )


def test_b06b_the_three_result_stream_sites_are_untouched() -> None:
    """``_cmd_run`` writes to ``result_stream``, not stdout, so it is OUT OF SCOPE."""
    found = _cli_text().count(RESULT_STREAM_SITE)
    assert found == EXPECTED_RESULT_STREAM_SITES, (
        f"the {EXPECTED_RESULT_STREAM_SITES} `result_stream` json.dumps sites must be "
        f"untouched, verbatim as {RESULT_STREAM_SITE!r}; found {found}"
    )


def test_b06c_the_out_of_scope_dispatch_tails_all_survive() -> None:
    """Exactly the six out-of-scope tails remain open-coded -- one each, no more.

    This is the other half of "no collateral consolidation": the change must not
    have absorbed ``prune``/``runs``/``explain``/``verify``/``diff``/``trend``,
    which are NOT in five-line correspondence with the six in scope.
    """
    census = _dispatch_tail_census(_cli_tree())
    renderers = sorted(renderer for _line, renderer in census)
    assert renderers == sorted(SURVIVING_RENDERERS), (
        f"the open-coded dispatch tails must be exactly {sorted(SURVIVING_RENDERERS)} "
        f"(one each); found {renderers}"
    )


# --------------------------------------------------------------------------- #
# Behavior 7 -- fully annotated seam (this package ships a PEP 561 py.typed)
# --------------------------------------------------------------------------- #


def test_b07a_emitter_signature_is_keyword_only_and_fully_annotated() -> None:
    (node,) = _emitter_def(_cli_tree())
    assert not node.args.args and not node.args.posonlyargs, (
        f"`{EMITTER}` must take NO positional parameters; got "
        f"{[a.arg for a in node.args.posonlyargs + node.args.args]}"
    )
    kwonly = [(a.arg, ast.unparse(a.annotation) if a.annotation else None)
              for a in node.args.kwonlyargs]
    assert kwonly == list(EMITTER_PARAMS), (
        f"`{EMITTER}` must be `(*, as_json: bool, payload: Callable[[], object], "
        f"human: Callable[[], str])`; got {kwonly}"
    )
    assert node.returns is not None and ast.unparse(node.returns) == "None", (
        f"`{EMITTER}` must be annotated `-> None`; got "
        f"{ast.unparse(node.returns) if node.returns else None}"
    )


def test_b07b_emitter_documents_the_contract_exactly_once() -> None:
    """The contract sentence lives in ONE docstring now -- that is the whole point."""
    (node,) = _emitter_def(_cli_tree())
    doc = ast.get_docstring(node)
    assert doc, f"`{EMITTER}` must carry a docstring stating the --json stdout contract"
    lowered = doc.lower()
    assert "json" in lowered, f"`{EMITTER}`'s docstring must name the --json contract; got {doc!r}"


# --------------------------------------------------------------------------- #
# Behavior 8 -- no new runtime dependency, no new flag or verb
# --------------------------------------------------------------------------- #


def test_b08a_runtime_dependencies_are_still_pydantic_only() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = list(data["project"].get("dependencies", []))
    assert len(deps) == 1 and deps[0].lower().startswith("pydantic"), (
        f"this iteration adds NO runtime dependency; pyproject declares {deps}"
    )


def test_b08b_no_new_flag_appeared_on_the_six_verbs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--json`` and (for ``collectors``) ``--kind`` are the only flags in play.

    A refactor that grew a user-visible flag would be out of scope; the cheapest
    black-box proof is that an unknown flag is still rejected.
    """
    for _name, prefix in SIX_SITES:
        with pytest.raises(SystemExit) as excinfo:
            _run([*prefix, "--emit"], capsys)
        assert excinfo.value.code != 0, (
            f"`pla {' '.join(prefix)} --emit` must be rejected, not accepted"
        )
