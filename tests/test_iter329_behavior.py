"""Black-box oracle for foundry iter 592 (factory iter 329): every verb row of
the README ``## CLI`` table names each ``--flag`` its argparse subparser owns,
checked live against ``cli.build_parser()`` so a future flag is graded with no
edit here.

ISOLATION CONTRACT (honored): written only from the iteration spec (pm.md), the
README, the existing ``tests/`` tree and real ``pla <verb> --help`` runs. No
``src/`` implementation, no engineer/reviewer notes, no ``git diff``.

The module collects ZERO items: the suite-size census (test_iter263/270) holds a
6-item binding wall, so any new collected item reds the build.
``test_iter317_behavior.py::test_runs_older_than_filters_by_checkpoint_age``
calls ``iter592_readme_cli_census`` and asserts how many checks ran. Behaviour 8
(no src / SPEC / intro change) is a property of the diff, verified out-of-suite
by the tester; the ledger row count is owned by test_iter264.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

from proactive_loop import cli

REPO = Path(__file__).resolve().parents[1]

# Global/parent flags every subparser inherits; documented once, not per row.
EXEMPT = frozenset(
    {"--help", "--provider", "--scripted-responses", "--state-dir", "--verbose", "--workspace"}
)


def _subparsers() -> dict[str, argparse.ArgumentParser]:
    parser = cli.build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("build_parser() has no subcommands")


def _rows(readme: str, verb: str) -> list[str]:
    return re.findall(rf"^\| `{re.escape(verb)}` *\|.*$", readme, flags=re.MULTILINE)


def census(readme: str) -> tuple[int, int, list[tuple[str, str]]]:
    """Return (verbs inspected, flags inspected, undocumented (verb, flag) pairs).

    A flag is documented when the verb's row holds a backtick immediately followed
    by the flag and then a space, a backtick or ``=``."""
    subs = _subparsers()
    flags = 0
    missing: list[tuple[str, str]] = []
    for verb, sub in sorted(subs.items()):
        row = "\n".join(_rows(readme, verb))
        owned = sorted(
            {
                opt
                for action in sub._actions
                for opt in action.option_strings
                if opt.startswith("--") and opt not in EXEMPT
            }
        )
        for flag in owned:
            flags += 1
            if not re.search(rf"`{re.escape(flag)}(?=[ `=])", row):
                missing.append((verb, flag))
    return len(subs), flags, missing


def _readme() -> str:
    return (REPO / "README.md").read_text(encoding="utf-8")


def _clause(row: str, token: str) -> str:
    """The text from ``token`` up to the next ``; `` clause boundary (or row end)."""
    start = row.find(token)
    assert start >= 0, f"{token!r} not in row"
    end = row.find("; ", start + len(token))
    return row[start : end if end > 0 else len(row)]


def _one_row(verb: str) -> str:
    rows = _rows(_readme(), verb)
    assert len(rows) == 1, (verb, len(rows))
    return rows[0]


def _b1_run_baseline() -> None:
    clause = _clause(_one_row("run"), "`--baseline FILE`").lower()
    assert "snapshot" in clause and "hides" in clause, clause
    assert "new" in clause, clause


def _b2_run_exclude_path() -> None:
    clause = _clause(_one_row("run"), "`--exclude-path GLOB`").lower()
    assert "repeatable" in clause, clause
    assert "out of perception" in clause, clause


def _b3_signals_collector() -> None:
    row = _one_row("signals")
    clause = _clause(row, "`--collector NAME`").lower()
    assert "repeatable" in clause, clause
    assert "named collector" in clause, clause
    assert "unknown collector name" in clause and "exit 2" in clause, clause


def _b4_scan_and_watch_json() -> None:
    scan = _clause(_one_row("scan"), "`--json`")
    assert "alias for `--format json`" in scan, scan
    assert "mutually exclusive with `--format`" in scan, scan
    watch = _clause(_one_row("watch"), "`--json`")
    assert "one JSON object on stdout" in watch, watch
    assert "stderr" in watch and "tick header" in watch, watch


def _b5_b6_b7_live_census() -> None:
    readme = _readme()
    verbs, flags, missing = census(readme)
    assert missing == [], missing  # B5
    for verb in _subparsers():  # B6
        assert len(_rows(readme, verb)) == 1, verb
    assert verbs >= 17 and flags >= 72, (verbs, flags)  # B7: not vacuous
    # B7: a synthetic README whose watch row lacks `--json` is caught exactly.
    row = _one_row("watch")
    stripped = row.replace("`--json`", "json")
    assert stripped != row
    _, _, synthetic = census(readme.replace(row, stripped))
    assert synthetic == [("watch", "--json")], synthetic


def _zero_items() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    names = [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert names, "module parsed to nothing"
    assert not [n for n in names if n.startswith(("test", "Test"))], names


def _ledger_row() -> None:
    text = (REPO / "ROADMAP.md").read_text(encoding="utf-8")
    assert "- #379 README CLI rows name every verb flag (foundry iter 327)" in text
    assert text.count("#379 ") == 1


def iter592_readme_cli_census() -> int:
    """Run every iter-592 check; returns how many ran (asserted by the host)."""
    _b1_run_baseline()
    _b2_run_exclude_path()
    _b3_signals_collector()
    _b4_scan_and_watch_json()
    _b5_b6_b7_live_census()
    _zero_items()
    _ledger_row()
    return 7
