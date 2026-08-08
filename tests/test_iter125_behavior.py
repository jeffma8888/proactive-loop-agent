"""Black-box oracle for factory iteration 125 (foundry iteration 118).

This iteration's feature is a *drift guard* over the README's
``## Configuration (environment variables)`` section: the 14 published ``PLA_*``
rows, their documented defaults and their "flag equivalent" column must agree
with the live ``Settings`` / ``RetryPolicy`` field defaults and the live
``build_parser()``.

Written under the tester isolation contract: the only seams used here are the
public ones -- ``proactive_loop.config.Settings`` / ``RetryPolicy``,
``proactive_loop.config.ENV_PREFIX`` / ``_RETRY_ENV_VARS``,
``proactive_loop.cli.build_parser()`` -- plus the shipped ``README.md`` text.
The live env-name set is DERIVED (``ast`` over the source object of
``Settings.from_env``, i.e. the same call sites the runtime uses) rather than
grepped, because ``PLA_MODEL``, ``PLA_PROVIDER``, ``PLA_STATE_DIR``,
``PLA_WORKSPACE_ROOT`` and ``PLA_MAX_LLM_CALLS`` exist nowhere in ``src/`` as
literals.

Every check is a pure function over ``(readme_text, live_values)`` so the
two-sided tests can run it against a MUTATED COPY of the README string; no test
here writes to ``README.md``. Offline and deterministic: no network, no
subprocess, no clock and no randomness.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import textwrap
from pathlib import Path

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.config import ENV_PREFIX, RetryPolicy, Settings, _RETRY_ENV_VARS

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"

CONFIG_HEADING = "## Configuration (environment variables)"
EXPECTED_ROW_COUNT = 14
ENV_ONLY_CELL = "*(env-only)*"
NONE_CELL = "*(none)*"


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# pure helpers over the README text (behaviors 1, 2, 6)
# --------------------------------------------------------------------------
def config_section(text: str) -> str:
    """Return the Configuration section: its heading up to the next ``## ``.

    Mirrors ``cli_section()`` in ``tests/test_readme_and_ci_contract.py``: it
    ASSERTS rather than returning empty when the heading is missing or
    duplicated, so a restructured README can never make the guard vacuous.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == CONFIG_HEADING]
    assert len(starts) == 1, (
        f"README.md must contain exactly one {CONFIG_HEADING!r} heading, "
        f"found {len(starts)}"
    )
    start = starts[0]
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[start:end])


def parse_rows(section: str) -> list[tuple[str, str, str]]:
    """Parse ``(name, flag_cell, default_cell)`` for every ``PLA_*`` table row.

    Header, separator, prose and fenced-code lines never parse as rows: a row
    must be a pipe-delimited line whose first cell is a single backticked
    ``PLA_*`` token.
    """
    rows: list[tuple[str, str, str]] = []
    in_fence = False
    for raw in section.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        m = re.fullmatch(r"`(PLA_[A-Z0-9_]+)`", cells[0])
        if m is None:
            continue
        rows.append((m.group(1), cells[1], cells[2]))
    return rows


# --------------------------------------------------------------------------
# behavior 1 -- section isolation
# --------------------------------------------------------------------------
def test_b1_config_section_is_unique_and_bounded() -> None:
    text = readme_text()
    section = config_section(text)
    assert section.splitlines()[0].strip() == CONFIG_HEADING
    body = section.split("\n", 1)[1]
    assert "\n## " not in body and not body.startswith("## ")
    for sub in ("**Core**", "**Scout budget**", "**L0 resilience"):
        assert sub in section, f"missing sub-table marker {sub!r}"
    # neighbouring sections' text must be excluded on both sides
    assert "py.typed" not in section
    assert "How the offline scripted provider works" not in section


def test_b1_helper_asserts_when_heading_missing_or_duplicated() -> None:
    with pytest.raises(AssertionError):
        config_section("# README\n\nno configuration section here\n")
    text = readme_text()
    with pytest.raises(AssertionError):
        config_section(text + "\n" + CONFIG_HEADING + "\n")


# --------------------------------------------------------------------------
# behavior 2 -- row parsing
# --------------------------------------------------------------------------
def test_b2_section_parses_exactly_fourteen_rows() -> None:
    rows = parse_rows(config_section(readme_text()))
    assert len(rows) == EXPECTED_ROW_COUNT
    names = [name for name, _flag, _default in rows]
    assert len(set(names)) == EXPECTED_ROW_COUNT, "duplicate documented variable"
    for _name, flag, default in rows:
        assert flag and default


def test_b2_prose_and_fenced_code_never_parse_as_rows() -> None:
    section = config_section(readme_text())
    assert "PLA_RETRY_MAX_ATTEMPTS=8" in section, "fenced bash example moved"
    parsed = {name for name, _f, _d in parse_rows(section)}
    noise = textwrap.dedent(
        """\
        ## Configuration (environment variables)

        | Variable | Flag equivalent | Default | Meaning |
        |----------|-----------------|---------|---------|
        | `PLA_REAL_ROW` | *(env-only)* | `1` | a real row. |

        Prose mentioning `PLA_FAKE_PROSE` must not parse.

        ```bash
        export PLA_FAKE_FENCED=8
        ```
        """
    )
    assert {n for n, _f, _d in parse_rows(config_section(noise))} == {"PLA_REAL_ROW"}
    assert "PLA_RETRY_MAX_ATTEMPTS" in parsed


# --------------------------------------------------------------------------
# live-value derivation (behavior 3) and the declared rendering rule (behavior 4)
# --------------------------------------------------------------------------
def derive_env_names() -> set[str]:
    """Derive the live ``PLA_*`` name set from the runtime's own call sites.

    ``ENV_PREFIX`` joined to every single string-literal first argument of the
    ``_get(...)`` calls inside ``Settings.from_env`` (via ``ast``, not grep),
    plus ``ENV_PREFIX`` joined to each suffix in ``_RETRY_ENV_VARS``.
    """
    source = textwrap.dedent(inspect.getsource(Settings.from_env))
    tree = ast.parse(source)
    suffixes: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            suffixes.add(node.args[0].value)
    assert suffixes, "derivation found zero _get(...) call sites -- would pass vacuously"
    retry = {entry[0] for entry in _RETRY_ENV_VARS}
    assert retry, "_RETRY_ENV_VARS is empty -- would pass vacuously"
    return {ENV_PREFIX + s for s in suffixes | retry}


#: env name -> the live field default it documents. Keys are asserted to equal
#: the derived name set, so this table cannot silently drift out of coverage.
def live_defaults() -> dict[str, object]:
    settings = Settings()
    values: dict[str, object] = {
        "PLA_PROVIDER": settings.provider,
        "PLA_MODEL": settings.model,
        "PLA_SCRIPTED_RESPONSES": settings.scripted_responses_path,
        "PLA_WORKSPACE_ROOT": settings.workspace_root,
        "PLA_STATE_DIR": settings.state_dir,
        "PLA_AUTO_DISPATCH_MIN_SCORE": settings.auto_dispatch_min_score,
        "PLA_SENSITIVE_CATEGORIES": settings.sensitive_categories,
        "PLA_MAX_ITERATIONS": settings.max_iterations,
        "PLA_MAX_LLM_CALLS": settings.max_llm_calls,
    }
    for env_suffix, field, _coerce in _RETRY_ENV_VARS:
        values[ENV_PREFIX + env_suffix] = getattr(settings.retry, field)
    return values


def render_default(value: object) -> tuple[str, str]:
    """Return ``(rendered_cell, branch_name)`` under the rule declared here.

    One branch per type: ``None`` -> ``*(none)*``; ``Path`` -> backticked
    ``str()``; ``str`` -> backticked; ``int`` -> backticked decimal; ``float``
    -> backticked ``repr`` (so ``4.0``, ``1.0``, ``2.0``, ``60.0``, ``0.1``).
    Sets are handled separately, order-insensitively.
    """
    if value is None:
        return NONE_CELL, "none"
    if isinstance(value, Path):
        return f"`{value}`", "path"
    if isinstance(value, str):
        return f"`{value}`", "str"
    if isinstance(value, bool):  # pragma: no cover - no bool setting today
        raise AssertionError("bool default is undeclared in the rendering rule")
    if isinstance(value, int):
        return f"`{value:d}`", "int"
    if isinstance(value, float):
        return f"`{value!r}`", "float"
    if isinstance(value, (set, frozenset)):
        return "", "set"
    raise AssertionError(f"no declared rendering branch for {type(value).__name__}")


def cell_tokens(cell: str) -> set[str]:
    return {t.strip() for t in cell.strip("`").split(",") if t.strip()}


def long_options() -> set[str]:
    """Every long option the live parser accepts, including subcommands."""
    universe: set[str] = set()

    def walk(parser: object) -> None:
        for action in parser._actions:  # type: ignore[attr-defined]
            universe.update(o for o in action.option_strings if o.startswith("--"))
            choices = getattr(action, "choices", None)
            if action.__class__.__name__ == "_SubParsersAction" and choices:
                for sub in choices.values():
                    walk(sub)

    walk(build_parser())
    assert universe, "derived an empty flag universe -- would pass vacuously"
    return universe


def prose_flag_sentence(section: str) -> str:
    for chunk in section.split("."):
        if "direct CLI flag" in chunk:
            return chunk
    raise AssertionError("the sentence naming the flag-equipped settings is gone")


# --------------------------------------------------------------------------
# the composite check used two-sidedly by behavior 8
# --------------------------------------------------------------------------
def check_readme(text: str) -> list[str]:
    """Pure check over a README STRING; returns human-readable failures."""
    failures: list[str] = []
    try:
        section = config_section(text)
    except AssertionError as exc:
        return [f"section: {exc}"]

    rows = parse_rows(section)
    if len(rows) != EXPECTED_ROW_COUNT:
        failures.append(f"row count {len(rows)} != {EXPECTED_ROW_COUNT}")

    documented = {name for name, _f, _d in rows}
    live = derive_env_names()
    if documented != live:
        failures.append(
            f"name drift: undocumented={sorted(live - documented)} "
            f"invented={sorted(documented - live)}"
        )

    defaults = live_defaults()
    for name, _flag, default_cell in rows:
        if name not in defaults:
            continue
        value = defaults[name]
        if isinstance(value, (set, frozenset)):
            expected = {getattr(c, "value", c) for c in value}
            if cell_tokens(default_cell) != expected:
                failures.append(
                    f"{name}: documented {default_cell!r} != live set {sorted(expected)}"
                )
            continue
        rendered, _branch = render_default(value)
        if default_cell != rendered:
            failures.append(f"{name}: documented {default_cell!r} != live {rendered!r}")

    universe = long_options()
    flagged: set[str] = set()
    env_only = 0
    for name, flag_cell, _d in rows:
        if flag_cell == ENV_ONLY_CELL:
            env_only += 1
            derived = "--" + name[len(ENV_PREFIX) :].lower().replace("_", "-")
            if derived in universe:
                failures.append(
                    f"{name}: marked env-only but {derived} is a live long option"
                )
            continue
        match = re.fullmatch(r"`(--[a-z0-9-]+)`", flag_cell)
        if match is None:
            failures.append(f"{name}: unparsable flag cell {flag_cell!r}")
            continue
        flagged.add(match.group(1))
        if match.group(1) not in universe:
            failures.append(
                f"{name}: flag {match.group(1)} is not accepted by build_parser()"
            )

    if len(flagged) + env_only != len(rows):
        failures.append(
            f"{len(flagged)} flagged + {env_only} env-only != {len(rows)} rows"
        )

    try:
        sentence = prose_flag_sentence(section)
    except AssertionError as exc:
        failures.append(str(exc))
    else:
        in_prose = set(re.findall(r"`(--[a-z0-9-]+)`", sentence))
        if in_prose != flagged:
            failures.append(f"prose flags {sorted(in_prose)} != table {sorted(flagged)}")

    return failures


# --------------------------------------------------------------------------
# behavior 3 -- name-set equality, both directions
# --------------------------------------------------------------------------
def test_b3_documented_names_equal_live_derived_names() -> None:
    documented = {n for n, _f, _d in parse_rows(config_section(readme_text()))}
    live = derive_env_names()
    assert documented, "no documented names parsed"
    assert live, "no live names derived"
    assert documented == live
    assert len(live) == EXPECTED_ROW_COUNT
    assert live_defaults().keys() == live, "the default map does not cover every live name"


# --------------------------------------------------------------------------
# behavior 4 -- documented defaults equal live field defaults
# --------------------------------------------------------------------------
def test_b4_every_documented_default_equals_the_live_default() -> None:
    assert Settings().retry == RetryPolicy(), (
        "the README claims every retry default IS the RetryPolicy field default, so a "
        "Settings-side override of the nested policy would make the table lie"
    )
    rows = parse_rows(config_section(readme_text()))
    defaults = live_defaults()
    branches: dict[str, int] = {}
    for name, _flag, cell in rows:
        value = defaults[name]
        _rendered, branch = render_default(value)
        branches[branch] = branches.get(branch, 0) + 1
        if branch == "set":
            expected = {getattr(c, "value", c) for c in value}  # type: ignore[union-attr]
            assert cell_tokens(cell) == expected, f"{name}: {cell!r} != {expected}"
        else:
            assert cell == _rendered, f"{name}: {cell!r} != {_rendered!r}"
    for branch in ("none", "path", "str", "int", "float", "set"):
        assert branches.get(branch, 0) >= 1, f"rendering branch {branch!r} never exercised"


def test_b4_sensitive_categories_compares_values_not_enum_reprs() -> None:
    live = Settings().sensitive_categories
    assert live, "the always-approve set must not be empty"
    member = next(iter(live))
    assert str(member).startswith("GoalCategory."), "str(member) changed shape"
    assert str(member) != member.value, "comparing without .value would be wrong"
    documented = [
        cell
        for name, _flag, cell in parse_rows(config_section(readme_text()))
        if name == "PLA_SENSITIVE_CATEGORIES"
    ]
    assert len(documented) == 1
    assert cell_tokens(documented[0]) == {c.value for c in live}


# --------------------------------------------------------------------------
# behavior 5 -- flag column agrees with the live parser
# --------------------------------------------------------------------------
def test_b5_flag_column_matches_live_parser() -> None:
    """Residual limitation: a new flag added under a spelling unrelated to its
    env name would not be caught by the env-only half of this check."""
    rows = parse_rows(config_section(readme_text()))
    universe = long_options()
    assert len(universe) >= 4
    flagged = [(n, f) for n, f, _d in rows if f != ENV_ONLY_CELL]
    assert len(flagged) == 4
    for name, cell in flagged:
        match = re.fullmatch(r"`(--[a-z0-9-]+)`", cell)
        assert match is not None, f"{name}: unparsable flag cell {cell!r}"
        assert match.group(1) in universe, f"{name}: {cell} not accepted by parser"
    env_only = [n for n, f, _d in rows if f == ENV_ONLY_CELL]
    assert len(env_only) == 10
    for name in env_only:
        derived = "--" + name[len(ENV_PREFIX) :].lower().replace("_", "-")
        assert derived not in universe, f"{name} is marked env-only but {derived} exists"


# --------------------------------------------------------------------------
# behavior 6 -- the section's prose agrees with its own table
# --------------------------------------------------------------------------
def test_b6_prose_agrees_with_the_table() -> None:
    section = config_section(readme_text())
    rows = parse_rows(section)
    flagged = {f.strip("`") for _n, f, _d in rows if f != ENV_ONLY_CELL}
    env_only = sum(1 for _n, f, _d in rows if f == ENV_ONLY_CELL)
    assert set(re.findall(r"`(--[a-z0-9-]+)`", prose_flag_sentence(section))) == flagged
    assert len(flagged) + env_only == EXPECTED_ROW_COUNT == len(rows)


def test_b6_prose_number_words_match_the_counts() -> None:
    section = config_section(readme_text())
    rows = parse_rows(section)
    flagged = sum(1 for _n, f, _d in rows if f != ENV_ONLY_CELL)
    env_only = sum(1 for _n, f, _d in rows if f == ENV_ONLY_CELL)
    words = {4: "Four", 10: "ten"}
    assert f"{words[flagged]} settings also have a direct CLI flag" in section
    assert f"the remaining {words[env_only]} are environment-only" in section


# --------------------------------------------------------------------------
# behavior 7 -- from_env() with nothing set == a bare Settings()
# --------------------------------------------------------------------------
def test_b7_from_env_with_no_variables_set_equals_bare_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = derive_env_names()
    assert len(names) == EXPECTED_ROW_COUNT
    for name in names:
        monkeypatch.delenv(name, raising=False)
    for name in names:
        assert name not in os.environ
    assert Settings.from_env() == Settings()


def test_b7_covers_every_documented_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every documented name is cleared, so an exported PLA_* cannot skew b7."""
    documented = {n for n, _f, _d in parse_rows(config_section(readme_text()))}
    assert documented == derive_env_names()
    for name in documented:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    assert Settings.from_env() == Settings()


# --------------------------------------------------------------------------
# behavior 8 -- two-sided: green on the shipped text, fires on planted drift
# --------------------------------------------------------------------------
def test_b8_green_on_the_shipped_readme() -> None:
    assert check_readme(readme_text()) == []


def _mutate(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"mutation anchor not unique: {old!r}"
    return text.replace(old, new)


@pytest.mark.parametrize(
    ("label", "old", "new"),
    [
        (
            "default digit changed",
            "| `PLA_MAX_ITERATIONS` | *(env-only)* | `8` |",
            "| `PLA_MAX_ITERATIONS` | *(env-only)* | `9` |",
        ),
        (
            "env-only row claims a flag",
            "| `PLA_MAX_ITERATIONS` | *(env-only)* |",
            "| `PLA_MAX_ITERATIONS` | `--max-iterations` |",
        ),
        (
            "documented row deleted",
            "| `PLA_MODEL` | *(env-only)* | *(none)* |",
            "",
        ),
        (
            "invented row added",
            "| `PLA_MAX_LLM_CALLS` |",
            "| `PLA_NOT_A_SETTING` | *(env-only)* | `1` | invented. |\n| `PLA_MAX_LLM_CALLS` |",
        ),
        (
            "sensitive set gains a different member",
            "`health_admin,finance_legal`",
            "`health_admin,pets`",
        ),
    ],
)
def test_b8_fires_on_planted_drift(label: str, old: str, new: str) -> None:
    text = readme_text()
    mutated = _mutate(text, old, new)
    assert mutated != text
    failures = check_readme(mutated)
    assert failures, f"guard stayed green on planted drift: {label}"


def test_b8_reordering_the_sensitive_set_stays_green() -> None:
    mutated = _mutate(
        readme_text(), "`health_admin,finance_legal`", "`finance_legal,health_admin`"
    )
    assert check_readme(mutated) == [], "order-insensitive comparison is order-BLIND"


def test_b8_no_test_writes_to_the_readme() -> None:
    before = README.read_bytes()
    check_readme(readme_text())
    for old, new in [("`8`", "`9`")]:
        check_readme(readme_text().replace(old, new))
    assert README.read_bytes() == before


def test_b8_fires_when_the_code_side_drifts_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real-world scenario: a one-character edit to a field default.

    The README text is untouched; the LIVE side moves. ``check_readme`` resolves
    ``live_defaults`` / ``derive_env_names`` through module globals, so patching
    them simulates a source edit without touching ``src/``.
    """
    text = readme_text()
    assert check_readme(text) == []

    drifted = dict(live_defaults())
    drifted["PLA_MAX_ITERATIONS"] = 9
    monkeypatch.setitem(globals(), "live_defaults", lambda: drifted)
    failures = check_readme(text)
    assert failures, "guard stayed green when the live default changed"
    assert any("PLA_MAX_ITERATIONS" in f for f in failures)


def test_b8_fires_when_a_new_setting_is_added_but_undocumented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = derive_env_names()
    monkeypatch.setitem(
        globals(), "derive_env_names", lambda: real | {"PLA_BRAND_NEW_KNOB"}
    )
    failures = check_readme(readme_text())
    assert any("PLA_BRAND_NEW_KNOB" in f for f in failures), failures
