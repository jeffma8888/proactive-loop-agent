"""Black-box behavior tests for iteration 51.

Feature under test: the DOCSTRING of ``parse_json_block`` -- the single choke
point where free-form model text becomes structured data for BOTH the L2
synthesizer (a JSON array of goals) and the L1 goal loop (PLAN/CHECK objects).
``SPEC.md`` §3 names it a load-bearing foundation contract. Its
"Strategy, in order of preference" numbered list previously LED with the fenced
```` ```json ```` block and named ``raw_decode`` second -- the reverse of what
the code (and its own inline ``1. Primary`` / ``2. Fallback`` / ``3. Last resort``
comments) actually does. This iteration corrects the docstring so its ordering
matches the code: junk-tolerant ``raw_decode`` from the earliest opener FIRST,
the fenced block SECOND, the whole-stripped-string last resort THIRD. This is a
docstring correction + drift guard ONLY; no runtime path changes.

ISOLATION STATEMENT: these tests were written strictly against the PUBLIC
contract -- this iteration's Expected Behaviors (``pm.md``), ``README.md``, and
``SPEC.md`` §3 -- and exercise ONLY the documented public function
``parse_json_block`` (imported from BOTH documented paths) plus the package's
public ``__version__``. No file under ``src/`` was read, no engineer/reviewer
notes for this iteration were consulted, and no ``git diff`` was inspected. This
is an INDEPENDENT, spec-derived encoding of the contract. The docstring index
assertions are robust to rewording: any correct description leads with the
``raw_decode`` strategy, so ordering -- not exact phrasing -- is pinned.
Everything runs fully offline: NO network, NO API keys, NO CLI subprocess, NO
filesystem.
"""

from __future__ import annotations

import json

import pytest

# Documented public surface, imported from BOTH paths named in the spec.
from proactive_loop import __version__
from proactive_loop.llm import parse_json_block as parse_json_block_pkg
from proactive_loop.llm.client import parse_json_block


def _doc() -> str:
    """The public docstring, asserted non-empty (Expected Behavior 1 precondition)."""
    doc = parse_json_block.__doc__
    assert isinstance(doc, str) and doc, "parse_json_block must have a non-empty docstring"
    return doc


# ---------------------------------------------------------------------------
# Behavior 1 -- docstring names raw_decode before the fenced block.
#   The corrected ordering: case-insensitively, "raw_decode" appears at a LOWER
#   index than the first "fence"/"fenced". RED on the old buggy docstring
#   (fence-before-raw_decode), GREEN after the fix.
# ---------------------------------------------------------------------------
def test_docstring_names_raw_decode_before_fence() -> None:
    low = _doc().lower()
    raw_idx = low.find("raw_decode")
    fence_idx = low.find("fence")  # matches both "fence" and "fenced"
    assert raw_idx != -1, "docstring must mention the raw_decode strategy"
    assert fence_idx != -1, "docstring must mention the fenced-block strategy"
    assert raw_idx < fence_idx, (
        f"raw_decode ({raw_idx}) must be named BEFORE fence ({fence_idx}) -- "
        "step 1 is junk-tolerant raw_decode, step 2 is the fenced block"
    )


# ---------------------------------------------------------------------------
# Behavior 2 -- the docstring still documents all three strategies in a
#   preference-ordered list (guards against the reorder deleting the list or
#   the step-3 last-resort description).
# ---------------------------------------------------------------------------
def test_docstring_still_lists_ordered_strategies_including_last_resort() -> None:
    low = _doc().lower()
    assert "in order of preference" in low, (
        "docstring must still frame the strategies as an ordered preference list"
    )
    assert "last resort" in low, (
        "docstring must still describe the whole-string last-resort (step 3) strategy"
    )


# ---------------------------------------------------------------------------
# Behavior 1 (corollary) -- both documented import paths are the SAME object,
#   so they necessarily share the corrected docstring.
# ---------------------------------------------------------------------------
def test_both_documented_paths_are_the_same_object() -> None:
    assert parse_json_block is parse_json_block_pkg
    assert parse_json_block.__doc__ == parse_json_block_pkg.__doc__


# ---------------------------------------------------------------------------
# Behavior 3 -- raw_decode-first precedence holds at runtime (one confirming
#   case, doc-anchored). A single valid JSON object whose string VALUE embeds a
#   ```json fenced block containing a DIFFERENT object: raw_decode consumes the
#   whole outer value at step 1, so the OUTER object is returned -- NOT the
#   inner object the fence regex would have extracted had the fence branch run
#   first. This is the direct behavioral corollary of the corrected step-1
#   rationale; kept to THIS ONE case (iter-50 already pins the full matrix).
# ---------------------------------------------------------------------------
def test_raw_decode_first_precedence_returns_outer_object_not_inner() -> None:
    text = json.dumps(
        {"tool": "write_file", "args": {"content": "```json\n{\"tool\": \"INNER\"}\n```"}}
    )
    assert parse_json_block(text) == {
        "tool": "write_file",
        "args": {"content": "```json\n{\"tool\": \"INNER\"}\n```"},
    }
    assert parse_json_block(text) != {"tool": "INNER"}


# ---------------------------------------------------------------------------
# Behavior 4 -- zero behavior change / no version bump. This is a docstring
#   correction, not a versioned contract change.
# ---------------------------------------------------------------------------
def test_version_is_unchanged_no_bump() -> None:
    assert __version__ == "0.1.1"
