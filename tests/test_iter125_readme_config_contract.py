"""Drift guard for the README's ``## Configuration (environment variables)`` table.

Why this file exists
--------------------
Configuration is the whole surface of the product's "tune it without editing
source" promise, and that README section makes the strongest machine-checkable
claim in the document:

    "Every default listed below is the single source of truth (the field default
    on ``Settings`` / ``RetryPolicy``), so ``Settings.from_env()`` with none of
    these set is identical to a bare ``Settings()``."

Until this file existed, that sentence, 14 published default values and 14
flag-equivalence claims were UNGUARDED PROSE on a public portfolio repo: a
one-character edit to a field default was enough to publish a lie with a green
build.

The exclusion was structural rather than accidental. All four README-vs-parser
guards in ``tests/test_readme_and_ci_contract.py`` route through its
``cli_section()`` helper, which slices ``## CLI`` up to the next ``## `` heading
-- so ``## Configuration (environment variables)`` is provably outside every one
of them. :func:`config_section` is the counterpart seam for this section, and it
asserts (rather than returning ``""``) when the heading is missing or duplicated,
for the same reason ``cli_section`` does: a silently empty section makes the
forward check scream about all 14 rows while the reverse check goes blind.

Derivation, not grepping
------------------------
The live env-var NAME set is derived from the code that reads it:

* the single string-literal argument of every ``_get("...")`` call inside
  ``Settings.from_env`` (obtained by ``ast``-parsing that function's source), and
* every suffix in the module-level ``_RETRY_ENV_VARS`` tuple,

each joined to ``ENV_PREFIX``. A grep over ``src/`` could not do this: 5 of the
14 names (``PLA_MODEL``, ``PLA_PROVIDER``, ``PLA_STATE_DIR``,
``PLA_WORKSPACE_ROOT``, ``PLA_MAX_LLM_CALLS``) exist NOWHERE as literals, because
``from_env`` calls ``_get("PROVIDER")`` and prepends the prefix -- the literals
that do grep are docstrings and error messages. A grep-derived guard would report
5 phantom undocumented rows while being fail-open on the rest. The same AST pass
also yields the ``env_values["field"]`` key each call site assigns, so the
documented DEFAULT is compared against the live field default without this file
hardcoding a name-to-field map.

Two-sided by construction: every check is a pure function over
``(readme_text, live_values)`` returning a list of problem strings, so the same
functions run against the shipped ``README.md`` (must be empty) and against
MUTATED COPIES of its text (must be non-empty). No test here writes to
``README.md``.

Known limitations, recorded on purpose
--------------------------------------
* The env-only check derives a flag spelling from the variable name
  (``PLA_MAX_ITERATIONS`` -> ``--max-iterations``). A new flag added under a
  spelling unrelated to its env name would not be caught.
* The 14-row count and the prose's own number words are PINNED. Shipping a 15th
  ``PLA_*`` variable is meant to fail here until the table and that sentence
  document it.

Fully offline and deterministic: reads one file, imports the package, parses
source text. No network, no subprocess, no clock, no randomness.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Final

import pytest

from proactive_loop.cli import build_parser
from proactive_loop.config import ENV_PREFIX, Settings, _RETRY_ENV_VARS
from proactive_loop.models import GoalCategory
from tests.test_readme_and_ci_contract import flag_universe

REPO: Final = Path(__file__).resolve().parents[1]
README: Final = REPO / "README.md"
CONFIG_HEADING: Final = "## Configuration (environment variables)"

#: The cell text a row uses to say "this setting has no CLI flag".
ENV_ONLY_CELL: Final = "*(env-only)*"
#: The cell text a row uses to render a ``None`` default.
NONE_CELL: Final = "*(none)*"

#: Pinned row count. Derived equality against the live name set is the real
#: check (:func:`name_problems`); this pin is what makes a 15th variable fail
#: loudly here instead of quietly widening the derived set on both sides.
EXPECTED_ROWS: Final = 14

#: A backticked long option, e.g. ``` `--provider` ``` -> ``--provider``.
BACKTICKED_FLAG: Final = re.compile(r"`(--[A-Za-z][A-Za-z0-9-]*)`")
#: A row's first cell: a backticked ``PLA_*`` token and nothing else.
ROW_NAME: Final = re.compile(r"^`(PLA_[A-Z0-9_]+)`$")

#: Number words the section's prose uses to count its own rows.
NUMBER_WORDS: Final[dict[str, int]] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14,
}
#: The two self-counting claims in the section's opening paragraph, each mapped
#: to the row group it counts ("flag" = rows naming a flag, "env" = env-only).
PROSE_COUNTS: Final[tuple[tuple[str, str], ...]] = (
    (r"([A-Za-z]+) settings also have a direct CLI flag", "flag"),
    (r"the remaining ([A-Za-z]+) are environment-only", "env"),
)


# --------------------------------------------------------------------------
# Section / row parsing (pure text)
# --------------------------------------------------------------------------


def config_section(text: str) -> str:
    """Return the configuration block: its heading up to the next ``## `` heading.

    Asserts instead of returning ``""`` when the heading is absent or repeated --
    an empty section would make every check below pass vacuously, which is the
    one failure mode a drift guard must never have.
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\n") == CONFIG_HEADING]
    assert len(starts) == 1, (
        f"README.md must contain exactly one {CONFIG_HEADING!r} heading, found "
        f"{len(starts)} -- the configuration guards have no section to check"
    )
    start = starts[0]
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
        len(lines),
    )
    return "".join(lines[start:end])


def split_cells(line: str) -> list[str]:
    """Split one markdown table line into stripped cell texts."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


class ConfigRow:
    """One parsed ``PLA_*`` table row: the three cells the guard binds to code."""

    __slots__ = ("name", "flag_cell", "default_cell", "cell_count", "line")

    def __init__(self, name: str, cells: list[str], line: str) -> None:
        self.name = name
        self.flag_cell = cells[1]
        self.default_cell = cells[2]
        self.cell_count = len(cells)
        self.line = line

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ConfigRow({self.name!r}, {self.flag_cell!r}, {self.default_cell!r})"


def parse_rows(section: str) -> list[ConfigRow]:
    """Every ``PLA_*`` row in ``section``, skipping headers, rules and code fences.

    Fenced blocks are tracked because the section ends with a runnable ``bash``
    example that exports ``PLA_RETRY_MAX_ATTEMPTS``; nothing inside a fence may
    ever be read as a documented row.
    """
    rows: list[ConfigRow] = []
    in_fence = False
    for raw in section.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped.startswith("|"):
            continue
        cells = split_cells(stripped)
        match = ROW_NAME.match(cells[0])
        if match is not None:
            rows.append(ConfigRow(match.group(1), cells, raw))
    return rows


def section_preamble(section: str) -> str:
    """The prose above the first table line -- where the section counts itself."""
    lines: list[str] = []
    for raw in section.splitlines():
        if raw.strip().startswith("|"):
            break
        lines.append(raw)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Live values, derived from the code that reads the environment
# --------------------------------------------------------------------------


def env_field_map() -> dict[str, str]:
    """``{env suffix: Settings field}`` for every ``_get("...")`` call in ``from_env``.

    Derived by AST rather than by grep, and one call site at a time: each
    enclosing ``if`` must contain exactly one literal ``_get`` name and exactly
    one ``env_values[...]`` assignment, so a refactor that split or merged those
    fails here loudly instead of silently dropping a variable from the guard.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(Settings.from_env)))
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        names = {
            call.args[0].value
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_get"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        }
        if not names:
            continue  # the retry loop (a non-literal arg) and the merge branch
        fields = {
            target.slice.value
            for assign in ast.walk(node)
            if isinstance(assign, ast.Assign)
            for target in assign.targets
            if isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "env_values"
            and isinstance(target.slice, ast.Constant)
            and isinstance(target.slice.value, str)
        }
        assert len(names) == 1 and len(fields) == 1, (
            f"Settings.from_env has a branch reading {sorted(names)} and writing "
            f"{sorted(fields)}; this guard derives one env var per branch"
        )
        mapping[names.pop()] = fields.pop()
    return mapping


def live_defaults() -> dict[str, object]:
    """``{PLA_NAME: live default value}`` for all 14 environment variables."""
    settings = Settings()
    values: dict[str, object] = {}
    for suffix, field in env_field_map().items():
        assert hasattr(settings, field), (
            f"Settings.from_env writes env_values[{field!r}] but Settings has no "
            f"such field -- the derivation is stale"
        )
        values[ENV_PREFIX + suffix] = getattr(settings, field)
    for suffix, field, _coerce in _RETRY_ENV_VARS:
        assert hasattr(settings.retry, field), (
            f"_RETRY_ENV_VARS maps {suffix} to RetryPolicy.{field}, which does not exist"
        )
        values[ENV_PREFIX + suffix] = getattr(settings.retry, field)
    return values


def render_default(value: object) -> str:
    """Render a live default the way the README publishes it.

    One branch per type actually present in the table, and NO permissive
    fallback: an unhandled type raises, so a newly added setting cannot slip in
    with its default silently "matching" by stringification. ``bool`` is
    rejected explicitly because it is an ``int`` subclass and would otherwise
    render as ``1``.
    """
    if value is None:
        return NONE_CELL
    if isinstance(value, bool):
        raise TypeError(
            "bool default: add an explicit rendering branch (and a row exercising it) "
            "rather than letting it render through the int branch"
        )
    if isinstance(value, Path):
        return f"`{value}`"
    if isinstance(value, str):
        return f"`{value}`"
    if isinstance(value, int):
        return f"`{value:d}`"
    if isinstance(value, float):
        return f"`{value!r}`"
    raise TypeError(
        f"no rendering rule for a {type(value).__name__} default; add a branch "
        "here so the README claim stays machine-checked"
    )


def parse_token_set(cell: str) -> set[str]:
    """Parse a backticked comma-separated cell into a SET of tokens.

    Used for ``PLA_SENSITIVE_CATEGORIES``, whose value is an unordered ``set``:
    comparing it as a string would make the guard fail on a harmless reordering
    (and ``str()`` on a ``GoalCategory`` member yields ``GoalCategory.HEALTH_ADMIN``,
    not ``health_admin``, so only the parsed-token form can be correct at all).
    """
    return {token.strip() for token in cell.strip().strip("`").split(",") if token.strip()}


# --------------------------------------------------------------------------
# The checks: pure functions returning problem strings
# --------------------------------------------------------------------------


def structure_problems(rows: Iterable[ConfigRow]) -> list[str]:
    """Rows whose shape the other checks depend on."""
    return [
        f"{row.name}: expected a 4-cell row (variable/flag/default/meaning), got "
        f"{row.cell_count}"
        for row in rows
        if row.cell_count != 4
    ]


def name_problems(rows: Iterable[ConfigRow], live: dict[str, object]) -> list[str]:
    """Documented name set vs live name set, BOTH directions and never vacuous."""
    documented = {row.name for row in rows}
    problems: list[str] = []
    if not documented:
        problems.append("the configuration section documents no PLA_* rows at all")
    if not live:
        problems.append("derived zero live PLA_* variables -- the derivation is broken")
    for name in sorted(live.keys() - documented):
        problems.append(f"{name} is read by the code but has no README row")
    for name in sorted(documented - live.keys()):
        problems.append(f"{name} is documented but no code reads it")
    return problems


def default_problems(rows: Iterable[ConfigRow], live: dict[str, object]) -> list[str]:
    """Every published default vs the live field default."""
    problems: list[str] = []
    for row in rows:
        if row.name not in live:
            continue  # reported by name_problems; nothing to compare against
        value = live[row.name]
        if isinstance(value, (set, frozenset)):
            expected_set = {getattr(item, "value", item) for item in value}
            if parse_token_set(row.default_cell) != expected_set:
                problems.append(
                    f"{row.name}: documented {row.default_cell} but the live default "
                    f"set is {sorted(map(str, expected_set))}"
                )
            continue
        expected = render_default(value)
        if row.default_cell != expected:
            problems.append(
                f"{row.name}: documented default {row.default_cell} but the live "
                f"field default renders as {expected}"
            )
    return problems


def derived_flag(name: str) -> str:
    """The flag spelling a reader would guess from an env var name."""
    return "--" + name.removeprefix(ENV_PREFIX).lower().replace("_", "-")


def flag_problems(rows: Iterable[ConfigRow], universe: Iterable[str]) -> list[str]:
    """The flag-equivalent column vs the live parser, both ways."""
    known = set(universe)
    problems: list[str] = []
    for row in rows:
        if row.flag_cell == ENV_ONLY_CELL:
            guess = derived_flag(row.name)
            if guess in known:
                problems.append(
                    f"{row.name} is documented as {ENV_ONLY_CELL} but the parser "
                    f"accepts {guess}"
                )
            continue
        flags = BACKTICKED_FLAG.findall(row.flag_cell)
        if len(flags) != 1:
            problems.append(
                f"{row.name}: flag cell {row.flag_cell!r} must be exactly one "
                f"backticked long option or {ENV_ONLY_CELL}"
            )
            continue
        if flags[0] not in known:
            problems.append(
                f"{row.name}: documented flag {flags[0]} exists on no parser -- a "
                "documented flag that exits 2 is worse than an undocumented one"
            )
    return problems


def prose_problems(section: str, rows: Iterable[ConfigRow]) -> list[str]:
    """The section's opening paragraph vs its own tables."""
    rows = list(rows)
    preamble = section_preamble(section)
    table_flags = {
        flag for row in rows for flag in BACKTICKED_FLAG.findall(row.flag_cell)
    }
    prose_flags = set(BACKTICKED_FLAG.findall(preamble))
    problems: list[str] = []
    if prose_flags != table_flags:
        problems.append(
            f"the section's prose names flags {sorted(prose_flags)} but its table "
            f"names {sorted(table_flags)}"
        )
    groups = {
        "flag": [row for row in rows if row.flag_cell != ENV_ONLY_CELL],
        "env": [row for row in rows if row.flag_cell == ENV_ONLY_CELL],
    }
    if len(groups["flag"]) + len(groups["env"]) != len(rows):
        problems.append("a row is neither flag-equipped nor env-only")
    for pattern, group in PROSE_COUNTS:
        match = re.search(pattern, preamble)
        if match is None:
            problems.append(f"the section no longer states its own count: /{pattern}/")
            continue
        claimed = NUMBER_WORDS.get(match.group(1).lower())
        if claimed is None:
            problems.append(f"unrecognized number word {match.group(1)!r} in the prose")
        elif claimed != len(groups[group]):
            problems.append(
                f"prose claims {match.group(1)} {group} rows but the table has "
                f"{len(groups[group])}"
            )
    return problems


def config_contract_problems(readme_text: str) -> list[str]:
    """Every check, for the shipped text or for a mutated copy of it."""
    section = config_section(readme_text)
    rows = parse_rows(section)
    live = live_defaults()
    universe = flag_universe(build_parser())
    return [
        *structure_problems(rows),
        *name_problems(rows, live),
        *default_problems(rows, live),
        *flag_problems(rows, universe),
        *prose_problems(section, rows),
    ]


# --------------------------------------------------------------------------
# In-memory mutation helpers (behavior 8). Nothing here writes to README.md.
# --------------------------------------------------------------------------


def _row_line(text: str, name: str) -> str:
    hits = [
        line
        for line in text.splitlines()
        if line.strip().startswith("|") and split_cells(line)[:1] == [f"`{name}`"]
    ]
    assert len(hits) == 1, f"expected exactly one {name} row, found {len(hits)}"
    return hits[0]


def with_cell(text: str, name: str, index: int, value: str) -> str:
    """A copy of ``text`` with one cell of one row replaced."""
    line = _row_line(text, name)
    cells = split_cells(line)
    cells[index] = value
    return text.replace(line, "| " + " | ".join(cells) + " |", 1)


def without_row(text: str, name: str) -> str:
    """A copy of ``text`` with one documented row deleted."""
    return text.replace(_row_line(text, name) + "\n", "", 1)


def with_extra_row(text: str, after: str, row: str) -> str:
    """A copy of ``text`` with an invented row inserted after an existing one."""
    anchor = _row_line(text, after)
    return text.replace(anchor + "\n", f"{anchor}\n{row}\n", 1)


@pytest.fixture(scope="module")
def readme_text() -> str:
    return README.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Behavior 1 -- section isolation
# --------------------------------------------------------------------------


def test_config_section_is_isolated_and_holds_all_three_sub_tables(
    readme_text: str,
) -> None:
    section = config_section(readme_text)
    assert section.startswith(CONFIG_HEADING)
    for label in ("**Core**", "**Scout budget**", "**L0 resilience (retry / backoff)**"):
        assert label in section, f"the configuration section lost its {label} table"
    # ...and stops at the next heading, so no neighbouring section's text leaks in.
    assert "## How the offline scripted provider works" not in section
    assert "## Use as a library" not in section
    assert section.count("## ") == 1


def test_config_section_extractor_fails_loudly_when_the_heading_is_absent() -> None:
    """A silently empty section is the one failure mode a guard must not have."""
    with pytest.raises(AssertionError, match="exactly one"):
        config_section("# Title\n\nno configuration heading here\n")
    with pytest.raises(AssertionError, match="exactly one"):
        config_section(f"{CONFIG_HEADING}\n\n{CONFIG_HEADING}\n")


# --------------------------------------------------------------------------
# Behavior 2 -- row parsing
# --------------------------------------------------------------------------


def test_parsing_yields_exactly_the_fourteen_documented_rows(readme_text: str) -> None:
    rows = parse_rows(config_section(readme_text))
    assert len(rows) == EXPECTED_ROWS, [row.name for row in rows]
    assert len({row.name for row in rows}) == EXPECTED_ROWS, "a row is duplicated"
    assert structure_problems(rows) == []
    assert all(row.name.startswith(ENV_PREFIX) for row in rows)


def test_row_parser_skips_headers_rules_prose_and_fenced_code() -> None:
    section = (
        f"{CONFIG_HEADING}\n"
        "Prose mentioning `PLA_MODEL` in passing.\n"
        "| Variable | Flag equivalent | Default | Meaning |\n"
        "|----------|-----------------|---------|---------|\n"
        "| `PLA_MODEL` | *(env-only)* | *(none)* | real row. |\n"
        "```bash\n"
        "| `PLA_FENCED` | *(env-only)* | `1` | inside a fence. |\n"
        "```\n"
    )
    assert [row.name for row in parse_rows(section)] == ["PLA_MODEL"]


# --------------------------------------------------------------------------
# Behavior 3 -- name-set equality, both directions
# --------------------------------------------------------------------------


def test_documented_names_equal_the_names_the_code_actually_reads(
    readme_text: str,
) -> None:
    live = live_defaults()
    assert len(live) == EXPECTED_ROWS, sorted(live)
    assert name_problems(parse_rows(config_section(readme_text)), live) == []


def test_the_live_name_set_is_derived_from_call_sites_not_from_grepped_literals() -> None:
    """The 5 names that exist nowhere as literals must still be derived."""
    live = live_defaults()
    source = Path(REPO / "src" / "proactive_loop" / "config.py").read_text(
        encoding="utf-8"
    )
    concatenated = {
        "PLA_MODEL",
        "PLA_PROVIDER",
        "PLA_STATE_DIR",
        "PLA_WORKSPACE_ROOT",
        "PLA_MAX_LLM_CALLS",
    }
    for name in concatenated:
        assert name not in source, (
            f"{name} is now a literal in config.py; the anti-grep rationale in this "
            "module's docstring needs updating (the derivation itself still holds)"
        )
        assert name in live, f"{name} was not derived from the _get(...) call sites"
    assert len(env_field_map()) == 9 and len(_RETRY_ENV_VARS) == 5


def test_name_problems_reports_both_directions_and_never_passes_vacuously() -> None:
    live = live_defaults()
    rows = parse_rows(config_section(README.read_text(encoding="utf-8")))
    assert name_problems([], live) != []
    assert name_problems(rows, {}) != []
    assert any("no code reads it" in p for p in name_problems(rows, {}))


# --------------------------------------------------------------------------
# Behavior 4 -- every documented default equals the live field default
# --------------------------------------------------------------------------


def test_every_documented_default_equals_the_live_field_default(
    readme_text: str,
) -> None:
    rows = parse_rows(config_section(readme_text))
    assert default_problems(rows, live_defaults()) == []


def test_every_rendering_branch_is_exercised_by_a_real_row() -> None:
    """A branch no row reaches is a branch that could be wrong forever."""
    values = list(live_defaults().values())
    assert any(value is None for value in values)
    assert any(isinstance(value, Path) for value in values)
    assert any(isinstance(value, str) for value in values)
    assert any(type(value) is int for value in values)
    assert any(type(value) is float for value in values)
    assert any(isinstance(value, (set, frozenset)) for value in values)


def test_rendering_rule_has_no_permissive_fallback() -> None:
    assert render_default(None) == NONE_CELL
    assert render_default(Path(".pla_runs")) == "`.pla_runs`"
    assert render_default("scripted") == "`scripted`"
    assert render_default(8) == "`8`"
    assert render_default(4.0) == "`4.0`"
    assert render_default(0.1) == "`0.1`"
    with pytest.raises(TypeError, match="bool"):
        render_default(True)
    with pytest.raises(TypeError, match="no rendering rule"):
        render_default(object())


def test_the_sensitive_categories_cell_is_compared_as_a_set_of_values() -> None:
    """``str()`` on a GoalCategory member yields ``GoalCategory.HEALTH_ADMIN``."""
    live = Settings().sensitive_categories
    assert isinstance(live, set)
    assert parse_token_set("`health_admin,finance_legal`") == {
        member.value for member in live
    }
    assert parse_token_set("` finance_legal , health_admin `") == {
        member.value for member in live
    }


# --------------------------------------------------------------------------
# Behavior 5 -- the flag column agrees with the live parser
# --------------------------------------------------------------------------


def test_flag_column_agrees_with_the_live_parser(readme_text: str) -> None:
    rows = parse_rows(config_section(readme_text))
    universe = flag_universe(build_parser())
    assert flag_problems(rows, universe) == []
    documented = {
        flag for row in rows for flag in BACKTICKED_FLAG.findall(row.flag_cell)
    }
    assert documented == {"--provider", "--scripted-responses", "--state-dir", "--workspace"}
    assert documented <= set(universe)
    env_only = [row.name for row in rows if row.flag_cell == ENV_ONLY_CELL]
    assert len(env_only) == 10
    assert all(derived_flag(name) not in universe for name in env_only)


def test_flag_problems_fires_on_a_ghost_flag_and_on_a_wrong_env_only_claim() -> None:
    universe = flag_universe(build_parser())
    ghost = ConfigRow("PLA_MODEL", ["`PLA_MODEL`", "`--no-such-flag`", "`1`", "m."], "")
    assert len(flag_problems([ghost], universe)) == 1
    lying = ConfigRow("PLA_PROVIDER", ["`PLA_PROVIDER`", ENV_ONLY_CELL, "`x`", "m."], "")
    assert len(flag_problems([lying], universe)) == 1
    ok = ConfigRow("PLA_PROVIDER", ["`PLA_PROVIDER`", "`--provider`", "`x`", "m."], "")
    assert flag_problems([ok], universe) == []


# --------------------------------------------------------------------------
# Behavior 6 -- the section's prose agrees with its own table
# --------------------------------------------------------------------------


def test_section_prose_agrees_with_its_own_table(readme_text: str) -> None:
    section = config_section(readme_text)
    rows = parse_rows(section)
    assert prose_problems(section, rows) == []
    preamble = section_preamble(section)
    assert set(BACKTICKED_FLAG.findall(preamble)) == {
        flag for row in rows for flag in BACKTICKED_FLAG.findall(row.flag_cell)
    }
    flagged = sum(1 for row in rows if row.flag_cell != ENV_ONLY_CELL)
    env_only = sum(1 for row in rows if row.flag_cell == ENV_ONLY_CELL)
    assert (flagged, env_only, flagged + env_only) == (4, 10, EXPECTED_ROWS)


def test_prose_problems_fires_when_the_prose_count_stops_matching() -> None:
    section = config_section(README.read_text(encoding="utf-8"))
    rows = parse_rows(section)
    reworded = section.replace(
        "Four settings also have a direct CLI flag", "Five settings also have a direct CLI flag"
    )
    assert reworded != section
    assert any("prose claims Five" in p for p in prose_problems(reworded, rows))


# --------------------------------------------------------------------------
# Behavior 7 -- the section's headline promise
# --------------------------------------------------------------------------


def test_from_env_with_none_of_the_documented_variables_set_equals_a_bare_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sentence the section leads with, asserted rather than trusted.

    Every one of the 14 names is removed from the environment first, so a
    developer's own exported ``PLA_*`` value can neither rescue nor break this.
    """
    names = sorted(live_defaults())
    assert len(names) == EXPECTED_ROWS
    for name in names:
        monkeypatch.delenv(name, raising=False)
    assert Settings.from_env() == Settings()


# --------------------------------------------------------------------------
# Behavior 8 -- two-sided: green on the shipped text, red on planted drift
# --------------------------------------------------------------------------


def test_the_shipped_readme_passes_every_check(readme_text: str) -> None:
    assert config_contract_problems(readme_text) == []


@pytest.mark.parametrize(
    ("label", "mutate", "expected_in_report"),
    [
        (
            "a default digit changed",
            lambda t: with_cell(t, "PLA_MAX_ITERATIONS", 2, "`9`"),
            "PLA_MAX_ITERATIONS",
        ),
        (
            "an env-only row claiming a flag that does not exist",
            lambda t: with_cell(t, "PLA_MAX_ITERATIONS", 1, "`--max-iterations`"),
            "exists on no parser",
        ),
        (
            "a documented row deleted",
            lambda t: without_row(t, "PLA_MAX_LLM_CALLS"),
            "PLA_MAX_LLM_CALLS is read by the code but has no README row",
        ),
        (
            "an invented row added",
            lambda t: with_extra_row(
                t,
                "PLA_MAX_LLM_CALLS",
                "| `PLA_NOT_A_SETTING` | *(env-only)* | `1` | invented. |",
            ),
            "PLA_NOT_A_SETTING is documented but no code reads it",
        ),
        (
            "the sensitive set changed to a different member",
            lambda t: with_cell(t, "PLA_SENSITIVE_CATEGORIES", 2, "`career,finance_legal`"),
            "PLA_SENSITIVE_CATEGORIES",
        ),
    ],
)
def test_the_guard_fires_on_planted_drift(
    readme_text: str,
    label: str,
    mutate: Callable[[str], str],
    expected_in_report: str,
) -> None:
    mutated = mutate(readme_text)
    assert mutated != readme_text, f"the {label} mutation changed nothing"
    problems = config_contract_problems(mutated)
    assert problems, f"the guard did not fire on {label}"
    assert any(expected_in_report in problem for problem in problems), problems


def test_the_guard_also_fires_when_the_code_side_drifts(readme_text: str) -> None:
    """The symmetric direction: the docs are right and a live field default moved.

    The mutation cases above edit the README; this one substitutes the derived
    LIVE value map, which is the direction that actually happens (a
    one-character edit to a field default on ``Settings``). Substituting the map
    rather than the field is deliberate: a pydantic field default cannot be
    monkeypatched per-test without rebuilding the model, and this still exercises
    the real comparator.
    """
    rows = parse_rows(config_section(readme_text))
    live = live_defaults()
    assert default_problems(rows, live) == []
    moved = {**live, "PLA_MAX_ITERATIONS": 9}
    problems = default_problems(rows, moved)
    assert len(problems) == 1 and "PLA_MAX_ITERATIONS" in problems[0], problems
    narrowed = {**live, "PLA_SENSITIVE_CATEGORIES": {GoalCategory.CAREER}}
    assert any(
        "PLA_SENSITIVE_CATEGORIES" in problem
        for problem in default_problems(rows, narrowed)
    )


def test_reordering_the_sensitive_set_stays_green(readme_text: str) -> None:
    """Order-INSENSITIVE, not order-blind: (e)'s sibling case must pass."""
    reordered = with_cell(
        readme_text, "PLA_SENSITIVE_CATEGORIES", 2, "`finance_legal,health_admin`"
    )
    assert reordered != readme_text
    assert config_contract_problems(reordered) == []


def test_no_test_here_wrote_to_the_readme(readme_text: str) -> None:
    """The mutation cases operate on strings; the file on disk is untouched."""
    assert README.read_text(encoding="utf-8") == readme_text
