"""Black-box oracle for factory iteration 314 (foundry state iter-566) -- the
``--collector`` usage error no longer varies by CPython patch.

CPython gh-117766 (3.12.8+/3.13.1+/3.14) prints argparse's ``choices=`` list
UNQUOTED, so the product's own ``invalid choice`` line used to drift with the
interpreter patch and the public CI build went red. The contract pinned here is
the 3.12.7 wording: every live collector name single-quoted, joined by ``, ``.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``),
``README.md`` and the conventions under ``tests/``. It drives ONLY the public
``proactive_loop.cli.main(argv)`` entry in a subprocess (observable rc / stdout /
stderr on the bundled ``examples/fixture_workspace``) and the public registry
accessor ``all_collectors`` (to derive expected names, never a hardcoded list).
The one structural check (behavior 6) is a substring COUNT over ``cli.py`` that
the spec itself names; no implementation logic was read.

ONE collected item on purpose: binding_headroom is pinned ``>= 6`` by
test_iter263 / test_iter270, so each behavior is a private ``_bN`` half.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from proactive_loop.collectors import all_collectors

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "fixture_workspace"
CLI = REPO / "src" / "proactive_loop" / "cli.py"
_ENTRY = "import sys; from proactive_loop.cli import main; sys.exit(main(sys.argv[1:]))"
_VERBS = ("scan", "run", "signals")


def _pla(*argv: str) -> tuple[int, str, str]:
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    proc = subprocess.run(
        [sys.executable, "-c", _ENTRY, *argv],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        timeout=120,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _expected_line(bad: str) -> str:
    names = sorted(c.name for c in all_collectors())
    assert len(names) >= 2, names
    quoted = ", ".join(f"'{n}'" for n in names)
    return f"argument --collector: invalid choice: '{bad}' (choose from {quoted})"


def _b1_b2_quoted_error_on_every_verb() -> None:
    expected = _expected_line("bogus")
    seen: set[str] = set()
    for verb in _VERBS:
        rc, out, err = _pla(verb, "--workspace", str(FIXTURE), "--collector", "bogus")
        assert rc == 2, (verb, rc, err)
        assert out == "", (verb, out)
        lines = [ln for ln in err.splitlines() if "--collector: invalid choice" in ln]
        assert len(lines) == 1, (verb, err)
        assert lines[0] == f"pla {verb}: error: {expected}", (verb, lines[0])
        seen.add(lines[0].split(": error: ", 1)[1])
    # The tail of the line is the SAME bytes on every verb.
    assert seen == {expected}, seen


def _b3_valid_use_unchanged() -> None:
    rc, out, err = _pla(
        "signals", "--workspace", str(FIXTURE), "--collector", "todos", "--collector", "git_state"
    )
    assert rc == 0, err
    rows = [ln.split()[0] for ln in out.splitlines() if ln.startswith("  ")]
    assert rows, out
    assert set(rows) <= {"todos", "git_state"}, sorted(set(rows))
    assert "todos" in rows, rows
    rc_all, out_all, err_all = _pla("signals", "--workspace", str(FIXTURE))
    assert rc_all == 0, err_all
    rows_all = {ln.split()[0] for ln in out_all.splitlines() if ln.startswith("  ")}
    # Absent flag = all collectors: strictly more sources than the narrowed view.
    assert rows_all > set(rows), (sorted(rows_all), sorted(set(rows)))
    for verb in _VERBS:
        # Repeatable on every verb: parse succeeds past --collector (no exit-2 on it).
        rc_v, _o, err_v = _pla(
            verb, "--workspace", str(FIXTURE), "--collector", "todos",
            "--collector", "git_state", "--help",
        )
        assert rc_v == 0, (verb, err_v)


def _b4_watch_rejects_collector() -> None:
    rc, out, err = _pla("watch", "--workspace", str(FIXTURE), "--collector", "todos")
    assert rc == 2, (rc, out, err)
    assert "unrecognized arguments: --collector todos" in err, err


def _b5_help_preserved() -> None:
    for verb in _VERBS:
        rc, out, err = _pla(verb, "--help")
        assert rc == 0, (verb, err)
        assert "[--collector NAME]" in out, (verb, out)
        assert "  --collector NAME" in out, (verb, out)
        assert "invalid choice" not in out, verb


def _b6_single_registration_site() -> None:
    text = CLI.read_text(encoding="utf-8")
    assert text.count("choices=sorted(c.name for c in all_collectors())") == 0
    assert text.count('"--collector",') == 1, text.count('"--collector",')
    assert "def _add_collector_flag" in text


def test_collector_error_is_patch_independent() -> None:
    _b1_b2_quoted_error_on_every_verb()
    _b3_valid_use_unchanged()
    _b4_watch_rejects_collector()
    _b5_help_preserved()
    _b6_single_registration_site()
