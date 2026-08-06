"""Black-box behavior tests for state-dir iteration 104 (ships as commit-seq
**factory iter 111**): ``pla collectors`` publishes the signal ``kind`` each
collector emits, gains a fail-closed ``--kind K`` reverse lookup, and the
published name->kind mapping is guarded as a source-derived BIJECTION onto the
live signal-kind registry (ROADMAP #113).

Why that mattered: ``collectors`` is the documented front door of the
transparency arc (``collectors`` -> ``signals`` -> ``scan`` -> ``explain`` ->
``trace``), but it published only ``{name, description}``. Since iter-108 made an
unknown ``signals --kind`` a parse-time usage error, copying a collector NAME out
of the front door into the next command exited 2 for five of sixteen collectors
(``dependencies``, ``git_activity``, ``notes``, ``recent_files``, ``todos``) --
two individually-correct features that were jointly misleading. Publishing the
kind closes the arc's first joint without relaxing iter-108's validation.

ISOLATION CONTRACT (honored): every assertion here is written from THIS
iteration's spec (``pm.md`` Expected Behaviors), ``README.md`` and the product's
own observable output obtained by RUNNING it -- the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int`` (stdout / stderr / exit code) and the
public registry API ``proactive_loop.collectors.all_collectors()`` /
``SIGNAL_KINDS``. **No file under ``src/`` was read by the author, no
engineer/reviewer note was consulted, and no ``git diff`` was inspected.** The
published mapping under test is read back out of ``pla collectors --json`` (the
public wire), never imported from any private catalog, so a drift between the
published mapping and the code that emits the signals goes RED. Behaviors 7/8 DO
parse the shipped collector modules, but MECHANICALLY at runtime (``ast``): that
is the oracle the spec mandates, and it is implemented here independently of any
shipped guard so behavior 8 can prove it fail-closed on planted known-bad
samples AND silent on known-good ones.

Fully offline and cap-cheap: zero network, zero API keys, zero subprocesses; the
only filesystem work is reading ``README.md`` / the collector modules and a
``tmp_path`` empty workspace for behavior 3 (16 in-process ``signals`` runs,
measured at ~0.5s total).
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import re
import sys
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser, main
from proactive_loop.collectors import SIGNAL_KINDS, all_collectors

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
COLLECTORS_DIR = REPO / "src" / "proactive_loop" / "collectors"

# --------------------------------------------------------------------------
# Tester's ground facts --- the spec-declared contract (pm.md). Encoded here as
# constants, NOT imported from the implementation's private catalog, so these
# tests encode the CONTRACT and catch a silent drift in either direction.
# --------------------------------------------------------------------------

CANONICAL_COLLECTORS = {
    "ci_config",
    "dependencies",
    "git_activity",
    "git_stash",
    "git_state",
    "large_file",
    "license",
    "lockfile_drift",
    "merge_conflict",
    "notes",
    "recent_files",
    "secret_file",
    "syntax_error",
    "test_posture",
    "todos",
    "working_tree",
}

# The four name->kind pairs the spec pins by hand (behaviors 1, 2 and 4). Two of
# them are the divergent cases that motivated the row; two are identities.
SPEC_PINNED_KINDS = {
    "todos": "todo",
    "git_activity": "git_commit",
    "ci_config": "ci_config",
    "notes": "note",
    "recent_files": "recent_file",
}

# The exactly-three keys of every element of the --json `collectors` list.
COLLECTOR_OBJ_KEYS = {"name", "kind", "description"}

# The single top-level key of the --json payload (behaviors 2 and 6).
JSON_TOP_LEVEL_KEYS = {"collectors"}

# Values that must be rejected by `collectors --kind` at parse time (behavior 5):
# a plainly bogus token, plus the five COLLECTOR NAMES that are not kinds -- the
# natural typo this feature exists to make impossible to make silently.
# A plainly bogus token, routed through a NAMED variable at every call site:
# iter-108's corpus scan (test_iter108_behavior.py::test_b05_no_test_passes_an
# _impossible_kind_through_the_cli) rejects any quoted non-kind value written
# directly after a quoted long-form kind option anywhere under tests/, because
# that is the shape a dead test hides in. The scan is a raw per-LINE regex, so
# even a comment illustrating the forbidden pair would trip it.
_BOGUS = "bogus_kind"

NON_KIND_VALUES = (
    _BOGUS,
    "todos",
    "git_activity",
    "notes",
    "recent_files",
    "dependencies",
)


# --------------------------------------------------------------------------
# Helpers --- black-box: drive main(), read back exit code + stdout/stderr.
# --------------------------------------------------------------------------
def _run(argv: list[str]) -> tuple[int, str, str]:
    """Drive ``main(argv)``, normalizing argparse's ``SystemExit(2)`` to a code."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
    except SystemExit as exc:  # argparse usage error
        code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


def _catalog_rows(out: str) -> list[list[str]]:
    """Whitespace-split fields of every line whose LEADING token is a collector
    name -- the human catalog rows, ignoring header/footer prose."""
    rows: list[list[str]] = []
    for line in out.splitlines():
        fields = line.split()
        if fields and fields[0] in CANONICAL_COLLECTORS and line[:1].isspace():
            rows.append(fields)
    return rows


def _published_mapping() -> dict[str, str]:
    """The name->kind mapping as PUBLISHED on the ``--json`` wire (not imported)."""
    code, out, _err = _run(["collectors", "--json"])
    assert code == 0, f"collectors --json must exit 0; got {code}"
    payload = json.loads(out)
    return {obj["name"]: obj["kind"] for obj in payload["collectors"]}


def _readme_halves() -> tuple[str, str]:
    """(above-marker intro, below-marker reference) -- the marker text is matched
    on its punctuation-free part because the file uses an em-dash."""
    text = README.read_text(encoding="utf-8")
    idx = text.find("PORTFOLIO INTRO")
    assert idx > 0, "README must still carry the human-owned PORTFOLIO INTRO marker"
    return text[:idx], text[idx:]


# --------------------------------------------------------------------------
# The behavior-7 drift-guard mechanism, re-implemented here from the spec so
# behavior 8 can prove it against known-bad AND known-good samples.
# --------------------------------------------------------------------------
class KindGuardError(AssertionError):
    """Raised whenever the source-derived kind cannot be established EXACTLY.

    Subclasses ``AssertionError`` so any fail-closed condition fails the build
    rather than skipping a collector.
    """


def _kind_kwargs(node: ast.AST) -> tuple[set[str], list[str]]:
    """``(plain string-literal kind= values, descriptions of non-literal ones)``
    anywhere under ``node``. Fail-closed by construction: a computed kind lands
    in the second list instead of silently vanishing."""
    literals: set[str] = set()
    non_literals: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.keyword) and sub.arg == "kind":
            value = sub.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                literals.add(value.value)
            else:
                non_literals.append(
                    f"line {getattr(value, 'lineno', '?')}: {type(value).__name__}"
                )
    return literals, non_literals


def _kind_from_source(
    source: str, class_name: str, *, sibling_collector_classes: int = 1, where: str = "<synthetic>"
) -> str:
    """The single ``kind=`` string literal the named collector class emits.

    Joined to the registry by CLASS NAME inside the class's own defining module.
    Signals built in a module-level HELPER (rather than inside the class body)
    are attributed to the class via a module-scope fallback, which is only taken
    when that module defines exactly ONE registered collector class -- otherwise
    the attribution would be ambiguous and the guard fails instead of guessing.

    Raises ``KindGuardError`` (an ``AssertionError``) on: a missing class, a
    non-literal ``kind=``, zero derivable kinds, or more than one distinct kind.
    """
    tree = ast.parse(source)
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    own = next((n for n in classes if n.name == class_name), None)
    if own is None:
        raise KindGuardError(f"{where}: no class {class_name!r} found in its own module")

    literals, non_literals = _kind_kwargs(own)
    if non_literals:
        raise KindGuardError(
            f"{where}: {class_name} passes a non-literal kind= ({non_literals}); a computed "
            "kind cannot be published or guarded"
        )

    if not literals:
        # Module-level helper: attribute the module's own top-level kinds to the
        # single collector class it defines.
        if sibling_collector_classes != 1:
            raise KindGuardError(
                f"{where}: {class_name} emits no kind= inside its class body and its module "
                f"defines {sibling_collector_classes} registered collector classes -- the "
                "module-scope fallback would be ambiguous"
            )
        module_scope = ast.Module(
            body=[n for n in tree.body if not isinstance(n, ast.ClassDef)], type_ignores=[]
        )
        literals, non_literals = _kind_kwargs(module_scope)
        if non_literals:
            raise KindGuardError(
                f"{where}: module-level helper for {class_name} passes a non-literal kind= "
                f"({non_literals})"
            )

    if not literals:
        raise KindGuardError(
            f"{where}: derived ZERO kinds for {class_name} -- the guard would pass vacuously"
        )
    if len(literals) > 1:
        raise KindGuardError(
            f"{where}: {class_name} emits {len(literals)} distinct kinds {sorted(literals)} -- "
            "the published mapping assumes exactly one per collector"
        )
    return next(iter(literals))


def _source_kinds() -> dict[str, str]:
    """name -> kind, derived from the SHIPPED collector modules by ``ast``."""
    registry = list(all_collectors())
    per_module: dict[str, int] = {}
    for collector in registry:
        module = type(collector).__module__
        per_module[module] = per_module.get(module, 0) + 1

    derived: dict[str, str] = {}
    for collector in registry:
        cls = type(collector)
        module = sys.modules[cls.__module__]
        raw_file = getattr(module, "__file__", None)
        if raw_file is None:
            raise KindGuardError(f"{cls.__name__}: its module has no __file__ to parse")
        path = Path(raw_file).resolve()
        if path.parent != COLLECTORS_DIR.resolve():
            raise KindGuardError(
                f"{cls.__name__} is defined outside {COLLECTORS_DIR} ({path}) -- the guard's "
                "source scope no longer covers every collector"
            )
        derived[collector.name] = _kind_from_source(
            path.read_text(encoding="utf-8"),
            cls.__name__,
            sibling_collector_classes=per_module[cls.__module__],
            where=path.name,
        )
    return derived


# ===========================================================================
# Behavior 1 -- human output carries a kind column.
# ===========================================================================
def test_b01_human_collectors_exits_0_with_a_row_per_collector() -> None:
    code, out, err = _run(["collectors"])
    assert code == 0, f"collectors must exit 0; got {code} (stderr={err!r})"
    assert err == "", f"collectors must not write to stderr; got {err!r}"
    rows = _catalog_rows(out)
    assert len(rows) == len(CANONICAL_COLLECTORS), (
        f"expected {len(CANONICAL_COLLECTORS)} catalog rows, got {len(rows)}: "
        f"{[r[0] for r in rows]}"
    )
    assert {r[0] for r in rows} == CANONICAL_COLLECTORS


def test_b01_human_rows_are_name_ascending() -> None:
    _code, out, _err = _run(["collectors"])
    names = [r[0] for r in _catalog_rows(out)]
    assert names == sorted(names), f"catalog must be name-ascending; got {names}"


def test_b01_second_field_is_the_kind_and_a_description_follows() -> None:
    _code, out, _err = _run(["collectors"])
    published = _published_mapping()
    for fields in _catalog_rows(out):
        name = fields[0]
        assert len(fields) >= 3, f"row {name!r} lacks name/kind/description fields: {fields}"
        assert fields[1] == published[name], (
            f"row {name!r} second field is {fields[1]!r}, but the published kind is "
            f"{published[name]!r} -- human and --json views disagree"
        )
        assert " ".join(fields[2:]).strip(), f"row {name!r} has an empty description"


@pytest.mark.parametrize(("name", "kind"), sorted(SPEC_PINNED_KINDS.items()))
def test_b01_spec_pinned_kinds_appear_in_the_human_row(name: str, kind: str) -> None:
    _code, out, _err = _run(["collectors"])
    row = next((r for r in _catalog_rows(out) if r[0] == name), None)
    assert row is not None, f"collector {name!r} missing from the human catalog"
    assert row[1] == kind, f"{name}: human kind column is {row[1]!r}, spec pins {kind!r}"


# ===========================================================================
# Behavior 2 -- the --json wire shape.
# ===========================================================================
def test_b02_json_is_one_object_with_exactly_one_top_level_key() -> None:
    code, out, err = _run(["collectors", "--json"])
    assert code == 0, f"collectors --json must exit 0; got {code} (stderr={err!r})"
    payload = json.loads(out)  # ENTIRE stdout must parse
    assert isinstance(payload, dict), f"payload must be a JSON object, got {type(payload)}"
    assert set(payload) == JSON_TOP_LEVEL_KEYS, f"top-level keys drifted: {sorted(payload)}"


def test_b02_every_element_has_exactly_the_three_keys() -> None:
    _code, out, _err = _run(["collectors", "--json"])
    objs = json.loads(out)["collectors"]
    assert len(objs) == len(CANONICAL_COLLECTORS)
    for obj in objs:
        assert set(obj) == COLLECTOR_OBJ_KEYS, (
            f"element {obj.get('name')!r} keys drifted: {sorted(obj)} "
            f"(extra={sorted(set(obj) - COLLECTOR_OBJ_KEYS)}, "
            f"missing={sorted(COLLECTOR_OBJ_KEYS - set(obj))})"
        )
        assert all(isinstance(v, str) and v for v in obj.values()), obj


def test_b02_json_is_name_ascending_and_matches_the_registry() -> None:
    _code, out, _err = _run(["collectors", "--json"])
    names = [obj["name"] for obj in json.loads(out)["collectors"]]
    assert names == sorted(names), f"--json must be name-ascending; got {names}"
    assert set(names) == {c.name for c in all_collectors()}


@pytest.mark.parametrize(("name", "kind"), sorted(SPEC_PINNED_KINDS.items()))
def test_b02_json_publishes_the_spec_pinned_kind(name: str, kind: str) -> None:
    assert _published_mapping()[name] == kind


# ===========================================================================
# Behavior 3 -- every published kind is accepted by `signals --kind`.
# ===========================================================================
def test_b03_published_kinds_are_all_members_of_signal_kinds() -> None:
    published = _published_mapping()
    unknown = {n: k for n, k in published.items() if k not in set(SIGNAL_KINDS)}
    assert unknown == {}, (
        "collectors publishes kinds that `signals --kind` would reject at parse time: "
        f"{unknown}"
    )


@pytest.mark.parametrize("kind", sorted(set(SIGNAL_KINDS)))
def test_b03_signals_accepts_every_published_kind(kind: str, tmp_path: Path) -> None:
    """The defect this row closes, asserted end to end: copy a kind out of the
    front door into the next command and it must never be a usage error."""
    code, _out, err = _run(["signals", "--kind", kind, "--workspace", str(tmp_path)])
    assert code == 0, (
        f"`signals --kind {kind}` (a kind PUBLISHED by `collectors`) exited {code}; "
        f"stderr={err!r}"
    )


# ===========================================================================
# Behavior 4 -- --kind K is the reverse lookup.
# ===========================================================================
def test_b04_kind_filter_prints_exactly_the_one_emitting_collector() -> None:
    code, out, err = _run(["collectors", "--kind", "todo"])
    assert code == 0, f"`collectors --kind todo` must exit 0; got {code} (stderr={err!r})"
    rows = _catalog_rows(out)
    assert [r[0] for r in rows] == ["todos"], f"expected only `todos`; got {[r[0] for r in rows]}"
    assert rows[0][1] == "todo"


def test_b04_the_other_fifteen_names_do_not_appear() -> None:
    _code, out, _err = _run(["collectors", "--kind", "todo"])
    leaked = [
        name
        for name in sorted(CANONICAL_COLLECTORS - {"todos"})
        if re.search(rf"\b{re.escape(name)}\b", out)
    ]
    assert leaked == [], f"filtered output leaked other collector names: {leaked}"


@pytest.mark.parametrize(("name", "kind"), sorted(SPEC_PINNED_KINDS.items()))
def test_b04_reverse_lookup_round_trips_for_every_pinned_pair(name: str, kind: str) -> None:
    _code, out, _err = _run(["collectors", "--kind", kind])
    assert [r[0] for r in _catalog_rows(out)] == [name]


def test_b04_reverse_lookup_round_trips_for_all_sixteen() -> None:
    published = _published_mapping()
    for name, kind in sorted(published.items()):
        code, out, _err = _run(["collectors", "--kind", kind, "--json"])
        assert code == 0, f"--kind {kind} exited {code}"
        objs = json.loads(out)["collectors"]
        assert [o["name"] for o in objs] == [name], (
            f"kind {kind!r} must resolve to exactly {name!r}; got {[o['name'] for o in objs]}"
        )


# ===========================================================================
# Behavior 5 -- an unknown --kind is a parse-time usage error (exit 2).
# ===========================================================================
@pytest.mark.parametrize("bad", NON_KIND_VALUES)
def test_b05_non_kind_value_exits_2_with_empty_stdout(bad: str) -> None:
    code, out, err = _run(["collectors", "--kind", bad])
    assert code == 2, f"`collectors --kind {bad}` must exit 2; got {code} (stdout={out!r})"
    assert out == "", f"a usage error must print no catalog; got {out!r}"
    assert "--kind" in err, f"stderr must name the offending option; got {err!r}"
    assert "invalid choice" in err, f"stderr must report an invalid choice; got {err!r}"


def test_b05_usage_error_names_the_accepted_kinds() -> None:
    _code, _out, err = _run(["collectors", "--kind", _BOGUS])
    missing = [k for k in SIGNAL_KINDS if k not in err]
    assert missing == [], f"usage error must enumerate every accepted kind; missing={missing}"


def test_b05_collector_names_are_never_accepted_as_kinds() -> None:
    """The closed vocabulary is identical to `signals --kind`: this is the hole
    iter-108 closed, and widening it here would re-open it."""
    published = _published_mapping()
    name_only = sorted(set(published) - set(published.values()))
    assert name_only, "fixture assumption: some collector names are not kinds"
    for name in name_only:
        code, _out, _err = _run(["collectors", "--kind", name])
        assert code == 2, f"collector NAME {name!r} must not be an accepted --kind value"


# ===========================================================================
# Behavior 6 -- --kind composes with --json.
# ===========================================================================
def test_b06_filtered_json_keeps_the_same_envelope_and_one_element() -> None:
    code, out, err = _run(["collectors", "--kind", "todo", "--json"])
    assert code == 0, f"must exit 0; got {code} (stderr={err!r})"
    payload = json.loads(out)
    assert set(payload) == JSON_TOP_LEVEL_KEYS, f"top-level keys drifted: {sorted(payload)}"
    objs = payload["collectors"]
    assert len(objs) == 1, f"expected exactly one element; got {[o['name'] for o in objs]}"
    assert set(objs[0]) == COLLECTOR_OBJ_KEYS
    assert objs[0]["name"] == "todos"
    assert objs[0]["kind"] == "todo"


def test_b06_filtered_element_is_byte_identical_to_the_unfiltered_one() -> None:
    _code, full, _err = _run(["collectors", "--json"])
    unfiltered = next(o for o in json.loads(full)["collectors"] if o["name"] == "todos")
    _code, one, _err = _run(["collectors", "--kind", "todo", "--json"])
    assert json.loads(one)["collectors"][0] == unfiltered, (
        "the filtered view must publish the SAME object as the full listing"
    )
    assert unfiltered["description"].strip(), "the todos description must be non-empty"


# ===========================================================================
# Behavior 7 -- source-derived bijection guard (all four sub-claims).
# ===========================================================================
def test_b07a_published_names_equal_the_live_registry() -> None:
    assert set(_published_mapping()) == {c.name for c in all_collectors()}


def test_b07b_published_values_equal_the_signal_kind_registry() -> None:
    values = set(_published_mapping().values())
    assert values == set(SIGNAL_KINDS), (
        "published kinds have drifted from SIGNAL_KINDS; "
        f"published-only={sorted(values - set(SIGNAL_KINDS))} "
        f"registry-only={sorted(set(SIGNAL_KINDS) - values)}"
    )


def test_b07c_published_values_are_pairwise_distinct() -> None:
    published = _published_mapping()
    values = list(published.values())
    dupes = sorted({v for v in values if values.count(v) > 1})
    assert dupes == [], f"kind published by more than one collector: {dupes}"
    # (a) + (b) + (c) == bijection.
    assert len(published) == len(set(values)) == len(SIGNAL_KINDS) == 16


def test_b07d_published_kind_equals_the_kind_the_collector_actually_emits() -> None:
    published = _published_mapping()
    derived = _source_kinds()
    assert derived, "the ast scan derived NOTHING -- the guard would pass vacuously"
    assert set(derived) == set(published), (
        f"source scan covered {sorted(derived)} but the wire publishes {sorted(published)}"
    )
    mismatches = {n: (published[n], derived[n]) for n in derived if published[n] != derived[n]}
    assert mismatches == {}, (
        "published kind disagrees with the kind= literal the collector emits "
        f"(name: published != source): {mismatches}"
    )


# ===========================================================================
# Behavior 8 -- the guard is PROVEN fail-closed, both ways, on synthetic source.
# ===========================================================================
_GOOD_SAMPLE = (
    "class TodoCollector:\n"
    "    name = 'todos'\n"
    "    def collect(self, snap):\n"
    "        return [ContextSignal(source='s', kind='todo', summary='x')]\n"
)


def test_b08_known_good_sample_does_not_fire() -> None:
    """Two-sided self-test: a guard that fires on legitimate source is a
    permanently-red check nobody can satisfy."""
    assert _kind_from_source(_GOOD_SAMPLE, "TodoCollector") == "todo"


def test_b08_module_level_helper_sample_still_resolves() -> None:
    helper = (
        "def _extract(text):\n"
        "    return ContextSignal(source='s', kind='note', summary='y')\n"
        "class NotesCollector:\n"
        "    name = 'notes'\n"
        "    def collect(self, snap):\n"
        "        return _extract('x')\n"
    )
    assert _kind_from_source(helper, "NotesCollector") == "note"


@pytest.mark.parametrize(
    "bad_kind",
    [
        'f"git_{x}"',
        "SOME_CONST",
        '"a" if y else "b"',
        'prefix + "todo"',
        "KINDS[0]",
        "None",
    ],
)
def test_b08_non_literal_kind_fails_the_guard(bad_kind: str) -> None:
    source = (
        "class C:\n"
        "    def collect(self, snap):\n"
        f"        return [ContextSignal(source='s', kind={bad_kind}, summary='x')]\n"
    )
    with pytest.raises(AssertionError):
        _kind_from_source(source, "C")


def test_b08_zero_kinds_fails_the_guard() -> None:
    source = "class C:\n    def collect(self, snap):\n        return []\n"
    with pytest.raises(AssertionError):
        _kind_from_source(source, "C")


def test_b08_two_distinct_kinds_fails_the_guard() -> None:
    source = (
        "class C:\n"
        "    def collect(self, snap):\n"
        "        return [ContextSignal(kind='todo'), ContextSignal(kind='note')]\n"
    )
    with pytest.raises(AssertionError):
        _kind_from_source(source, "C")


def test_b08_missing_class_fails_the_guard() -> None:
    with pytest.raises(AssertionError):
        _kind_from_source(_GOOD_SAMPLE, "NotAClassInThisModule")


def test_b08_ambiguous_module_scope_fallback_fails_the_guard() -> None:
    """If a module ever hosts two registered collectors and one emits its kind
    from a module-level helper, attribution is ambiguous -- fail, never guess."""
    source = (
        "def _helper():\n"
        "    return ContextSignal(kind='todo')\n"
        "class A:\n    pass\n"
        "class B:\n    pass\n"
    )
    with pytest.raises(AssertionError):
        _kind_from_source(source, "A", sibling_collector_classes=2)


@pytest.mark.parametrize("collector_name", sorted(CANONICAL_COLLECTORS))
def test_b08_guard_notices_any_single_published_kind_being_wrong(collector_name: str) -> None:
    """Mutation proof: swapping one published kind for another must break the
    behavior-7d comparison, so the guard cannot pass a mangled mapping."""
    published = dict(_published_mapping())
    derived = _source_kinds()
    other = next(k for k in sorted(set(SIGNAL_KINDS)) if k != published[collector_name])
    published[collector_name] = other
    assert published != derived, (
        f"the guard would NOT notice {collector_name!r} being published as {other!r}"
    )


def test_b08_source_scan_covers_every_shipped_collector_module() -> None:
    modules = {type(c).__module__ for c in all_collectors()}
    assert len(modules) >= 16, f"only {len(modules)} distinct collector modules -- fail-open?"
    for module in sorted(modules):
        path = Path(sys.modules[module].__file__ or "")
        assert path.parent.resolve() == COLLECTORS_DIR.resolve(), path


# ===========================================================================
# Behavior 9 -- README documented BELOW the human-owned marker only.
# ===========================================================================
def test_b09_collectors_table_row_documents_the_new_option() -> None:
    _intro, reference = _readme_halves()
    rows = [ln for ln in reference.splitlines() if ln.lstrip().startswith("| `collectors`")]
    assert len(rows) == 1, f"expected exactly one `collectors` CLI-reference row; got {len(rows)}"
    row = rows[0]
    assert "--kind" in row, f"the collectors row must document --kind K; got {row!r}"
    assert "kind" in row and "--json" in row


def test_b09_json_shape_prose_names_all_three_keys() -> None:
    _intro, reference = _readme_halves()
    assert "{collectors[{name, kind, description}]}" in reference, (
        "the --json shape prose must publish the three-key element shape"
    )


def test_b09_portfolio_intro_carve_out_numbers_still_match_reality() -> None:
    intro, _reference = _readme_halves()
    verbs = len(build_parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
    assert f"{len(list(all_collectors()))} context collectors" in intro, (
        "the human-owned intro's collector count must match the live registry"
    )
    assert f"{verbs} CLI verbs" in intro, (
        f"the human-owned intro's CLI-verb count must match the live parser ({verbs})"
    )


def test_b09_intro_does_not_document_flags() -> None:
    """The CLI reference lives BELOW the marker; this feature must not have
    pushed option syntax up into the human-owned portfolio intro."""
    intro, _reference = _readme_halves()
    assert "--kind" not in intro, "the portfolio intro must not document --kind"
