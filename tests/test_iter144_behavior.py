"""Black-box behavior tests for factory iteration 144 (foundry state iter-137) ---
the 17th context collector, ``BrokenDocLinkCollector`` (``kind="broken_link"``):
for every Markdown file in the workspace it emits one signal per inline link whose
relative target does not exist on disk.

This is only the SECOND *relational* collector (after ``lockfile_drift``): it
reports a contradiction BETWEEN two artifacts --- a relative Markdown link and the
filesystem that disproves it --- where 15 of the 16 prior collectors report a fact
about ONE artifact.  The two things these tests pin hardest are the ones that would
void the feature on a stranger's repo, because this kind is destined for a PUBLIC
CI gate where a FALSE POSITIVE reddens someone else's build: (a) every
non-filesystem target shape stays silent (generic URL scheme, protocol-relative,
bare anchor), and (b) code context is not prose --- a link inside a fence or an
inline-code span is not a claim about the filesystem.  Both are asserted WITH a
same-file positive control, so no test here can pass merely because the collector
found nothing at all.

ISOLATION CONTRACT (honored): every assertion below is written against THIS
iteration's spec (``pm.md`` "Expected Behaviors" 1-14) and drives only public
surfaces --- ``BrokenDocLinkCollector().collect(root)``, the registry seam
``all_collectors()`` / ``SIGNAL_KINDS``, the ``pla`` CLI through
``cli.main(argv) -> int``, and the parsed text of the two human-facing documents
the spec names (``README.md``, ``SPEC.md``).  **No file under ``src/`` was read, no
engineer / reviewer / fix note was read, and no ``git diff`` was consulted.**
Where a constructor signature was needed it was taken from the RUNNING product
(``inspect.signature`` on the public class), which is the same "read the product's
own help/output by running it" affordance the role grants.

Fully offline and deterministic: no network, every writable fixture under
``tmp_path``, and the only reads outside ``tmp_path`` are of this repository's own
tree (behavior 12's dogfood case plus behavior 14's two document parses), which is
never mutated.

FRESH-CLONE SAFETY (deliberate, see the iter-154 ``_platform`` post-release break):
behavior 12 keys its dogfood assertion on the git-TRACKED Markdown set, never on
the ambient working tree.  Two gitignored root Markdown files exist on the author's
box; asserting "this tree emits zero" would encode local state that does not exist
in a throwaway clone.

AMBIGUITY NOTES (PM feedback, see ``tester.md``):

* Behavior 10 asks for an order "byte-identical across repeated ``collect()``
  calls".  ``ContextSignal`` carries a ``timestamp`` field, so the durable oracle
  used here is the full field tuple of every signal in sequence
  (``source/kind/summary/detail/path/weight``) plus a measured check that
  ``timestamp`` is itself stable; a raw ``repr`` comparison would have been an
  implementation detail, not the ordering claim.
* Behavior 11 says an undecodable ``*.md`` file "contributes no signal and does not
  raise".  The load-bearing half is "does not raise" (the behavior's own title);
  the no-signal half is asserted as written and held.
* Behavior 5 says a fragment is "stripped before the existence test" yet the
  summary must show the target "as written".  Both halves are asserted separately
  so a regression cannot satisfy one by breaking the other.
"""

from __future__ import annotations

import inspect
import json
import pathlib
import re
import subprocess

import pytest

from proactive_loop.cli import main
from proactive_loop.collectors import SIGNAL_KINDS, all_collectors
from proactive_loop.collectors.base import ContextSignal
from proactive_loop.collectors.broken_link import BrokenDocLinkCollector

# The registry size this iteration ships.  Bumped, never derived: a derived
# `len(all_collectors())` would make the assertion vacuous, which is the whole
# point of the count tripwire recorded at test_iter106_behavior.py:33.
EXPECTED_COLLECTOR_COUNT = 17

REPO = pathlib.Path(__file__).resolve().parents[1]
KIND = "broken_link"

# A value that is deliberately NOT in SIGNAL_KINDS.  Routed through a named
# variable, never a literal at the call site: `test_iter108`'s fail-closed corpus
# scan rejects a hardcoded invalid `--kind` literal because it cannot tell one from
# an accidental typo, and naming it is self-documenting at the call site.
_UNKNOWN_KIND = "definitely-not-a-signal-kind"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke the CLI, return (rc, stdout, stderr).  Drains capsys first so setup
    output never leaks into the assertion window."""
    capsys.readouterr()
    rc = main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _collect(root: pathlib.Path, **kwargs: object) -> list[ContextSignal]:
    return BrokenDocLinkCollector(**kwargs).collect(root)  # type: ignore[arg-type]


def _fields(signals: list[ContextSignal]) -> list[tuple[object, ...]]:
    """The ordered, timestamp-free field tuple of a signal sequence."""
    return [
        (s.source, s.kind, s.summary, s.detail, s.path, s.weight) for s in signals
    ]


def _write(path: pathlib.Path, *lines: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assert_shape(s: ContextSignal, *, path: str) -> None:
    """The fixed field contract every broken_link signal shares."""
    assert s.kind == KIND, f"kind must be {KIND!r}; got {s.kind!r}"
    assert s.path == path, f"path must be the CONTAINING file {path!r}; got {s.path!r}"
    assert isinstance(s.summary, str) and s.summary.strip(), "summary must be non-empty"


# --------------------------------------------------------------------------
# Behavior 1 -- registry + closed vocabulary.
# --------------------------------------------------------------------------


def test_b01_registry_holds_seventeen_collectors_with_exactly_one_broken_link() -> None:
    collectors = all_collectors()
    assert len(collectors) == EXPECTED_COLLECTOR_COUNT, (
        f"all_collectors() must return {EXPECTED_COLLECTOR_COUNT}; got {len(collectors)}"
    )
    matches = [c for c in collectors if isinstance(c, BrokenDocLinkCollector)]
    assert len(matches) == 1, f"exactly one BrokenDocLinkCollector; got {len(matches)}"
    assert matches[0].name == KIND, (
        f"name must equal the kind so the bijection holds; got {matches[0].name!r}"
    )


def test_b01_signal_kinds_gained_broken_link_and_stays_sorted() -> None:
    assert KIND in SIGNAL_KINDS, f"{KIND!r} must join the closed vocabulary"
    assert len(SIGNAL_KINDS) == EXPECTED_COLLECTOR_COUNT, (
        f"SIGNAL_KINDS must hold {EXPECTED_COLLECTOR_COUNT}; got {len(SIGNAL_KINDS)}"
    )
    kinds = list(SIGNAL_KINDS)
    assert kinds == sorted(kinds), f"SIGNAL_KINDS must stay ascending; got {kinds}"


def test_b01_signals_accepts_the_new_kind_and_still_rejects_a_bogus_one(
    tmp_path: pathlib.Path, capsys
) -> None:
    rc, _out, err = _run(["signals", "--workspace", str(tmp_path), "--kind", KIND], capsys)
    assert rc == 0, f"pla signals --kind {KIND} must parse and exit 0; stderr={err!r}"

    assert _UNKNOWN_KIND not in SIGNAL_KINDS, "the negative fixture must stay invalid"
    with pytest.raises(SystemExit) as excinfo:
        main(["signals", "--workspace", str(tmp_path), "--kind", _UNKNOWN_KIND])
    assert excinfo.value.code == 2, (
        f"an unknown --kind must stay a usage error (exit 2); got {excinfo.value.code!r}"
    )


# --------------------------------------------------------------------------
# Behavior 2 -- a broken relative link is reported.
# --------------------------------------------------------------------------


def test_b02_broken_relative_link_yields_one_signal_naming_container_and_line(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "docs.md", "See [the design](missing.md).")
    signals = _collect(tmp_path)
    assert len(signals) == 1, f"exactly one signal expected; got {_fields(signals)}"
    sig = signals[0]
    _assert_shape(sig, path="docs.md")
    assert "missing.md" in sig.summary, (
        f"summary must name the target text; got {sig.summary!r}"
    )
    assert "1" in sig.summary, (
        f"summary must carry the 1-based line number; got {sig.summary!r}"
    )


def test_b02_path_is_workspace_relative_posix_of_the_containing_file(
    tmp_path: pathlib.Path,
) -> None:
    """The container, never the target -- and POSIX-separated even on Windows."""
    _write(tmp_path / "deep" / "nest" / "doc.md", "[a](missing.md)")
    signals = _collect(tmp_path)
    assert len(signals) == 1, f"one signal expected; got {_fields(signals)}"
    assert signals[0].path == "deep/nest/doc.md", (
        f"path must be the relative POSIX path of the container; got {signals[0].path!r}"
    )
    assert "\\" not in (signals[0].path or ""), "path must use POSIX separators"


def test_b02_line_number_is_one_based_and_points_at_the_right_line(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "docs.md", "# Title", "", "prose", "See [x](missing.md).")
    signals = _collect(tmp_path)
    assert len(signals) == 1, f"one signal expected; got {_fields(signals)}"
    assert "4" in signals[0].summary, (
        f"the link is on line 4 (1-based); got {signals[0].summary!r}"
    )


# --------------------------------------------------------------------------
# Behavior 3 -- an existing target is silent.
# --------------------------------------------------------------------------


def test_b03_existing_target_is_silent(tmp_path: pathlib.Path) -> None:
    _write(tmp_path / "real.md", "# real")
    _write(tmp_path / "docs.md", "See [the design](real.md).")
    assert _collect(tmp_path) == [], "a link whose target exists must be silent"


# --------------------------------------------------------------------------
# Behavior 4 -- non-filesystem targets are out of scope, always silent.
# --------------------------------------------------------------------------


def test_b04_urls_mailto_and_bare_anchors_are_never_reported(
    tmp_path: pathlib.Path,
) -> None:
    _write(
        tmp_path / "docs.md",
        "[a](https://example.invalid/x)",
        "[b](http://example.invalid/y)",
        "[c](mailto:x@example.invalid)",
        "[d](#a-heading)",
    )
    signals = _collect(tmp_path)
    assert signals == [], (
        "no non-filesystem target may be reported -- none exists as a file, and "
        f"reporting one would be a false positive on a public gate; got {_fields(signals)}"
    )


def test_b04_scheme_detection_is_generic_not_a_hardcoded_http_mailto_pair(
    tmp_path: pathlib.Path,
) -> None:
    """A hardcoded http/mailto pair would turn `ftp:`/`file:`/`//host` into
    phantom findings on a stranger's repo.  Positive control in the same file
    proves the collector is awake."""
    _write(
        tmp_path / "docs.md",
        "[a](ftp://example.invalid/x)",
        "[b](file:///etc/hosts)",
        "[c](//example.invalid/protocol-relative)",
        "[d](ssh://git@example.invalid/repo.git)",
        "[live](really-missing.md)",
    )
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        "only the relative target may be reported; every scheme-bearing and "
        f"protocol-relative target must stay silent; got {_fields(signals)}"
    )
    assert "really-missing.md" in signals[0].summary, (
        f"the one finding must be the relative link; got {signals[0].summary!r}"
    )


# --------------------------------------------------------------------------
# Behavior 5 -- a fragment or query is stripped before the existence test.
# --------------------------------------------------------------------------


def test_b05_fragment_is_stripped_before_the_existence_test(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "real.md", "# real")
    _write(tmp_path / "docs.md", "[a](real.md#heading)")
    assert _collect(tmp_path) == [], (
        "an existing target with a #fragment must be silent -- the fragment is not "
        "part of the path"
    )


def test_b05_query_is_stripped_before_the_existence_test(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "real.md", "# real")
    _write(tmp_path / "docs.md", "[a](real.md?v=2)")
    assert _collect(tmp_path) == [], (
        "an existing target with a ?query must be silent -- the query is not part "
        "of the path"
    )


def test_b05_broken_target_with_fragment_reports_the_target_as_written(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "docs.md", "[a](missing.md#heading)")
    signals = _collect(tmp_path)
    assert len(signals) == 1, f"one signal expected; got {_fields(signals)}"
    assert "missing.md#heading" in signals[0].summary, (
        "the summary must echo the target AS WRITTEN (fragment included) so the "
        f"reader can find the text to edit; got {signals[0].summary!r}"
    )


# --------------------------------------------------------------------------
# Behavior 6 -- code context is not prose (with same-file positive controls).
# --------------------------------------------------------------------------


def test_b06_backtick_fence_suppresses_but_prose_in_the_same_file_still_reports(
    tmp_path: pathlib.Path,
) -> None:
    _write(
        tmp_path / "docs.md",
        "Prose: [live](gone-prose.md)",
        "",
        "```",
        "[a](gone-in-fence.md)",
        "```",
        "",
        "Tail prose with `[b](gone-in-inline-code.md)` inside code.",
    )
    signals = _collect(tmp_path)
    summaries = [s.summary for s in signals]
    assert len(signals) == 1, (
        "only the prose link may be reported; a fenced link and an inline-code "
        f"link are code, not claims about the filesystem; got {summaries}"
    )
    assert "gone-prose.md" in signals[0].summary, (
        f"the positive control must be the reported one; got {signals[0].summary!r}"
    )


def test_b06_tilde_fence_suppresses_and_does_not_leak_past_its_close(
    tmp_path: pathlib.Path,
) -> None:
    _write(
        tmp_path / "docs.md",
        "~~~",
        "[a](gone-in-tilde-fence.md)",
        "~~~",
        "After the fence: [live](gone-after-tilde.md)",
    )
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        f"the ~~~ fence must suppress and then CLOSE; got {[s.summary for s in signals]}"
    )
    assert "gone-after-tilde.md" in signals[0].summary, (
        f"the post-fence prose link must report; got {signals[0].summary!r}"
    )


def test_b06_a_tilde_line_does_not_close_a_backtick_fence(
    tmp_path: pathlib.Path,
) -> None:
    """Same-delimiter semantics: only ``` closes a ``` fence."""
    _write(
        tmp_path / "docs.md",
        "```",
        "[a](gone-1.md)",
        "~~~",
        "[b](gone-2.md)",
        "```",
        "Now prose: [live](gone-3.md)",
    )
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        "a ~~~ line must NOT close a ``` fence, so both fenced links stay "
        f"suppressed; got {[s.summary for s in signals]}"
    )
    assert "gone-3.md" in signals[0].summary, (
        f"only the post-fence prose link may report; got {signals[0].summary!r}"
    )


def test_b06_unterminated_fence_runs_to_end_of_file(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path / "docs.md",
        "Prose first: [live](gone-prose.md)",
        "```",
        "[a](gone-1.md)",
        "[b](gone-2.md)",
    )
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        "an unterminated fence must swallow everything after it; got "
        f"{[s.summary for s in signals]}"
    )
    assert "gone-prose.md" in signals[0].summary, (
        f"only the pre-fence prose link may report; got {signals[0].summary!r}"
    )


# --------------------------------------------------------------------------
# Behavior 7 -- targets resolve against the containing file's directory.
# --------------------------------------------------------------------------


def test_b07_targets_resolve_against_the_containing_files_directory(
    tmp_path: pathlib.Path,
) -> None:
    _write(tmp_path / "root.md", "# root")
    _write(tmp_path / "sub" / "sibling.md", "# sibling")
    _write(
        tmp_path / "sub" / "doc.md",
        "[a](sibling.md)",
        "[b](../root.md)",
        "[d](./sibling.md)",
    )
    signals = _collect(tmp_path)
    assert signals == [], (
        "sibling, parent-relative and ./-prefixed targets all exist relative to "
        f"the CONTAINING dir, so all three must be silent; got {_fields(signals)}"
    )


def test_b07_parent_relative_miss_is_reported(tmp_path: pathlib.Path) -> None:
    _write(tmp_path / "root.md", "# root")
    _write(tmp_path / "sub" / "sibling.md", "# sibling")
    _write(tmp_path / "sub" / "doc.md", "[c](../nope.md)")
    signals = _collect(tmp_path)
    assert len(signals) == 1, f"one signal expected; got {_fields(signals)}"
    _assert_shape(signals[0], path="sub/doc.md")
    assert "../nope.md" in signals[0].summary, (
        f"summary must echo the target as written; got {signals[0].summary!r}"
    )


# --------------------------------------------------------------------------
# Behavior 8 -- image links count.
# --------------------------------------------------------------------------


def test_b08_image_link_counts(tmp_path: pathlib.Path) -> None:
    _write(tmp_path / "docs.md", "![diagram](missing.png)")
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        f"an image link is a filesystem claim too; got {_fields(signals)}"
    )
    assert "missing.png" in signals[0].summary, (
        f"summary must name the image target; got {signals[0].summary!r}"
    )


def test_b08_existing_image_target_is_silent(tmp_path: pathlib.Path) -> None:
    (tmp_path / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    _write(tmp_path / "docs.md", "![diagram](diagram.png)")
    assert _collect(tmp_path) == [], "an existing image target must be silent"


# --------------------------------------------------------------------------
# Behavior 9 -- noise subtrees are pruned.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("noise", ["node_modules", ".venv", ".hidden"])
def test_b09_noise_subtrees_are_pruned(tmp_path: pathlib.Path, noise: str) -> None:
    _write(tmp_path / noise / "docs.md", "[a](missing.md)")
    signals = _collect(tmp_path)
    assert signals == [], (
        f"a broken link under {noise}/ is vendored or generated noise and must be "
        f"pruned like the sibling filesystem collectors do; got {_fields(signals)}"
    )


def test_b09_pruning_does_not_suppress_the_rest_of_the_tree(
    tmp_path: pathlib.Path,
) -> None:
    """Anti-vacuity for behavior 9: the same workspace with a real doc reports it."""
    _write(tmp_path / "node_modules" / "docs.md", "[a](missing.md)")
    _write(tmp_path / ".venv" / "docs.md", "[b](missing.md)")
    _write(tmp_path / "docs.md", "[live](missing.md)")
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        f"exactly the non-noise doc must report; got {_fields(signals)}"
    )
    assert signals[0].path == "docs.md"


# --------------------------------------------------------------------------
# Behavior 10 -- deterministic order, and the cap is honored.
# --------------------------------------------------------------------------


_ORDER_FILES = {
    "a.md": ["[1](a-gone-1.md)", "[2](a-gone-2.md)"],
    "b.md": ["[3](b-gone-1.md)", "[4](b-gone-2.md)"],
}


def _build_order_workspace(
    root: pathlib.Path, names: list[str]
) -> pathlib.Path:
    """Create the same two-file corpus in a caller-chosen CREATION order, which is
    what drives raw directory enumeration order on many filesystems."""
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        _write(root / name, *_ORDER_FILES[name])
    return root


def test_b10_four_signals_and_the_order_is_stable_across_calls(
    tmp_path: pathlib.Path,
) -> None:
    ws = _build_order_workspace(tmp_path / "ws", ["a.md", "b.md"])
    first = _collect(ws)
    second = _collect(ws)
    assert len(first) == 4, f"two files x two broken links = 4; got {_fields(first)}"
    assert _fields(first) == _fields(second), (
        "repeated collect() must return a byte-identical sequence; got\n"
        f"{_fields(first)}\nvs\n{_fields(second)}"
    )
    assert [s.timestamp for s in first] == [s.timestamp for s in second], (
        "the timestamp field must be stable too, or the signal is not deterministic"
    )


def test_b10_order_is_independent_of_filesystem_enumeration_order(
    tmp_path: pathlib.Path,
) -> None:
    forward = _collect(_build_order_workspace(tmp_path / "fwd", ["a.md", "b.md"]))
    reverse = _collect(_build_order_workspace(tmp_path / "rev", ["b.md", "a.md"]))
    assert len(forward) == 4 and len(reverse) == 4, (
        f"both corpora hold 4 broken links; got {len(forward)} and {len(reverse)}"
    )
    def strip(sigs: list[ContextSignal]) -> list[tuple[object, ...]]:
        return [(s.path, s.summary.split(":", 1)[1], s.detail) for s in sigs]

    assert strip(forward) == strip(reverse), (
        "signal order must be sorted, not enumeration-dependent -- otherwise a "
        f"slate reshuffles per machine; got\n{strip(forward)}\nvs\n{strip(reverse)}"
    )
    assert [s.path for s in forward] == sorted(s.path or "" for s in forward), (
        f"paths must come out ascending; got {[s.path for s in forward]}"
    )


def test_b10_max_items_caps_and_keeps_the_head_of_the_same_total_order(
    tmp_path: pathlib.Path,
) -> None:
    ws = _build_order_workspace(tmp_path / "ws", ["a.md", "b.md"])
    full = _collect(ws)
    capped = _collect(ws, max_items=2)
    assert len(capped) == 2, f"max_items=2 must yield exactly 2; got {len(capped)}"
    assert _fields(capped) == _fields(full)[:2], (
        "the cap must take the HEAD of the same total order, not an arbitrary "
        f"subset; got\n{_fields(capped)}\nvs head\n{_fields(full)[:2]}"
    )


def test_b10_default_max_items_matches_the_sibling_collectors(tmp_path: pathlib.Path) -> None:
    assert BrokenDocLinkCollector().max_items == 30, (
        "the default cap must match the sibling collectors' 30 so one pathological "
        "doc corpus cannot flood a slate"
    )


# --------------------------------------------------------------------------
# Behavior 11 -- never raises.
# --------------------------------------------------------------------------


def test_b11_undecodable_markdown_contributes_nothing_and_does_not_raise(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "bad.md").write_bytes(b"# t\n[a](missing.md)\ntail \xff\xfe\n")
    signals = _collect(tmp_path)  # must not raise
    assert signals == [], (
        "a file whose bytes are not valid UTF-8 is not a decodable prose claim, so "
        f"it must contribute no signal; got {_fields(signals)}"
    )


def test_b11_undecodable_file_does_not_suppress_its_decodable_neighbours(
    tmp_path: pathlib.Path,
) -> None:
    """Anti-vacuity for behavior 11: one bad file must not abort the whole scan."""
    (tmp_path / "bad.md").write_bytes(b"[a](missing.md) \xff\xfe\n")
    _write(tmp_path / "good.md", "[live](also-missing.md)")
    signals = _collect(tmp_path)
    assert len(signals) == 1, (
        f"the decodable neighbour must still be scanned; got {_fields(signals)}"
    )
    assert signals[0].path == "good.md"


def test_b11_missing_workspace_root_yields_empty_list(tmp_path: pathlib.Path) -> None:
    assert _collect(tmp_path / "does-not-exist") == [], (
        "a workspace root that does not exist must yield [], not raise"
    )


def test_b11_a_file_passed_as_root_does_not_raise(tmp_path: pathlib.Path) -> None:
    """Defensive: `collect()` is documented never to raise, and the CLI can be
    pointed at anything."""
    target = tmp_path / "plain.md"
    _write(target, "[a](missing.md)")
    assert isinstance(_collect(target), list)


# --------------------------------------------------------------------------
# Behavior 12 -- dogfood, fresh-clone-safe.
# --------------------------------------------------------------------------


def _tracked_markdown() -> list[str]:
    listed = _git("ls-files", "*.md")
    if listed.returncode != 0:
        pytest.skip("not a git checkout; the tracked set is unknowable here")
    return [ln.strip() for ln in listed.stdout.splitlines() if ln.strip()]


def test_b12_no_tracked_markdown_file_holds_a_broken_link() -> None:
    tracked = set(_tracked_markdown())
    # Anti-vacuity FIRST: an empty or unrecognisable tracked set would make the
    # real assertion below pass for the wrong reason.
    assert tracked, "git ls-files '*.md' returned nothing -- the oracle is vacuous"
    for required in (
        "README.md",
        "ROADMAP.md",
        "ROADMAP_ARCHIVE.md",
        "SPEC.md",
        "DIRECTIONS.md",
    ):
        assert required in tracked, (
            f"{required} must be in the tracked Markdown set; got {sorted(tracked)}"
        )

    offenders = [
        (s.path, s.summary) for s in _collect(REPO) if (s.path or "") in tracked
    ]
    assert offenders == [], (
        "this repository's own tracked Markdown must hold zero broken relative "
        f"links -- the collector is dogfooded on its own docs; got {offenders}"
    )


# --------------------------------------------------------------------------
# Behavior 13 -- `pla collectors` publishes the new perceiver.
# --------------------------------------------------------------------------


def test_b13_collectors_human_lists_broken_link_with_a_description(capsys) -> None:
    rc, out, err = _run(["collectors"], capsys)
    assert rc == 0, f"pla collectors must exit 0; stderr={err!r}"
    lines = [ln for ln in out.splitlines() if ln.strip().startswith(KIND)]
    assert lines, f"human output must list {KIND}; got:\n{out}"
    desc = lines[0].strip()[len(KIND) :].strip()
    assert desc, f"{KIND} must carry a non-empty description; line={lines[0]!r}"


def test_b13_collectors_json_lists_seventeen_including_broken_link(capsys) -> None:
    rc, out, err = _run(["collectors", "--json"], capsys)
    assert rc == 0, f"pla collectors --json must exit 0; stderr={err!r}"
    doc = json.loads(out)
    entries = doc["collectors"]
    assert len(entries) == EXPECTED_COLLECTOR_COUNT, (
        f"catalog must list {EXPECTED_COLLECTOR_COUNT}; got {len(entries)}"
    )
    names = [e["name"] for e in entries]
    assert KIND in names, f"{KIND} must be catalogued; got {names}"
    assert names == sorted(names), f"catalog must stay name-ascending; got {names}"
    entry = next(e for e in entries if e["name"] == KIND)
    assert entry["kind"] == KIND, (
        f"the published kind must be the token `signals --kind` accepts; got {entry!r}"
    )
    assert entry["description"].strip(), "the description must not be empty"
    assert {c.name for c in all_collectors()} == set(names), (
        "the catalog name set must equal the live registry -- that drift guard is "
        "the point of the catalog"
    )


def test_b13_collectors_kind_reverse_lookup_prints_exactly_one(capsys) -> None:
    rc, out, err = _run(["collectors", "--kind", KIND], capsys)
    assert rc == 0, f"pla collectors --kind {KIND} must exit 0; stderr={err!r}"
    # Collector ROWS are the indented lines whose first token is a live collector
    # name; keying on the registry (not on line position) keeps this robust to the
    # human view's header/footer prose while staying non-vacuous.
    registry_names = {c.name for c in all_collectors()}
    listed = [
        ln.split()[0]
        for ln in out.splitlines()
        if ln.startswith("  ") and ln.split() and ln.split()[0] in registry_names
    ]
    assert listed == [KIND], (
        f"the reverse lookup must print exactly one collector, {KIND}; got "
        f"{listed} from:\n{out}"
    )


# --------------------------------------------------------------------------
# Behavior 14 -- every published count reads 17.
# --------------------------------------------------------------------------


def test_b14_readme_portfolio_intro_collector_count_matches_the_live_registry() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    found = re.findall(r"(\d+)\s+context collectors", text)
    assert found, "the README must publish an 'N context collectors' claim"
    for digits in found:
        assert int(digits) == EXPECTED_COLLECTOR_COUNT == len(all_collectors()), (
            f"README publishes {digits} context collectors but the live registry "
            f"holds {len(all_collectors())} -- a stale public claim"
        )


def test_b14_spec_catalog_shape_sentence_reads_seventeen() -> None:
    text = (REPO / "SPEC.md").read_text(encoding="utf-8")
    match = re.search(
        r"array of (\d+)\s*\n?\s*`\{name, description\}` objects", text
    )
    assert match, "SPEC.md must keep its `collectors` catalog-shape sentence"
    assert int(match.group(1)) == EXPECTED_COLLECTOR_COUNT == len(all_collectors()), (
        f"SPEC says 'array of {match.group(1)}' but the registry holds "
        f"{len(all_collectors())}"
    )


def test_b14_constructor_signature_is_the_documented_public_shape() -> None:
    """The collector is constructed by name in the registry and by tests with
    `max_items`; both must stay keyword-addressable."""
    params = inspect.signature(BrokenDocLinkCollector.__init__).parameters
    for expected in ("name", "max_items"):
        assert expected in params, (
            f"__init__ must accept {expected!r}; got {sorted(params)}"
        )
