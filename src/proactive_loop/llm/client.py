"""LLM boundary: a minimal protocol plus a fully-offline scripted client.

Design decision: the ENTIRE system talks to models through `LLMClient.complete`
with a `tag` naming the call site ("synthesize", "plan", "check"). That single
seam is what makes the project offline-testable end to end -- tests and the
bundled demo inject a ScriptedLLMClient and never touch a network or SDK.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class LLMError(Exception):
    """Base class for LLM-boundary failures."""


class LLMThrottleError(LLMError):
    """Provider rate limit / 429 / too-many-tokens. Retryable with backoff."""


class LLMTimeoutError(LLMError):
    """Provider or transport timeout. Retryable with backoff."""


class ScriptExhaustedError(LLMError):
    """ScriptedLLMClient ran out of matching responses (test/demo script bug)."""


@dataclass
class LLMResponse:
    text: str
    model: str = "scripted"
    usage: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class LLMClient(Protocol):
    """The one seam between this system and any model provider."""

    def complete(self, *, system: str, prompt: str, tag: str = "") -> LLMResponse: ...


class ScriptedLLMClient:
    """Deterministic, offline LLM double driven by a list of scripted entries.

    Script entry shape (dicts):
        {"tag": "synthesize", "text": "..."}          -> returned as LLMResponse
        {"tag": "plan", "raise": "throttle"}          -> raises LLMThrottleError
        {"tag": "",     "raise": "timeout"}           -> raises LLMTimeoutError

    Matching: entries are consumed IN ORDER. `complete(tag=X)` takes the first
    remaining entry whose tag == X, or whose tag == "" (wildcard). No match ->
    ScriptExhaustedError. This keeps multi-call flows (plan/check interleaving)
    both strict and easy to author.
    """

    _RAISES: dict[str, type[LLMError]] = {
        "throttle": LLMThrottleError,
        "timeout": LLMTimeoutError,
    }

    def __init__(self, entries: list[dict[str, Any]]):
        self._entries: list[dict[str, Any]] = list(entries)
        self.calls: list[str] = []  # tags seen, for test assertions

    @classmethod
    def from_file(cls, path: Path) -> "ScriptedLLMClient":
        data = json.loads(Path(path).read_text())
        entries = data["responses"] if isinstance(data, dict) else data
        if not isinstance(entries, list):
            raise ValueError(f"scripted responses file {path} must be a list or {{'responses': [...]}}")
        return cls(entries)

    def remaining(self) -> int:
        return len(self._entries)

    def complete(self, *, system: str, prompt: str, tag: str = "") -> LLMResponse:
        self.calls.append(tag)
        for i, entry in enumerate(self._entries):
            entry_tag = entry.get("tag", "")
            if entry_tag == tag or entry_tag == "":
                self._entries.pop(i)
                if "raise" in entry:
                    exc = self._RAISES.get(str(entry["raise"]))
                    if exc is None:
                        raise ValueError(f"unknown scripted raise kind: {entry['raise']!r}")
                    raise exc(f"scripted {entry['raise']} for tag {tag!r}")
                return LLMResponse(text=str(entry.get("text", "")))
        raise ScriptExhaustedError(
            f"no scripted response left for tag {tag!r} ({len(self._entries)} entries remain)"
        )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _first_json_start(text: str) -> int | None:
    """Index of the earliest ``{`` or ``[`` in *text*, or None if neither.

    Whichever opener appears FIRST wins, so a top-level array ``[{...}]`` is
    decoded as the array -- not as the first object nested inside it.
    """
    positions = [p for p in (text.find("{"), text.find("[")) if p != -1]
    return min(positions) if positions else None


def parse_json_block(text: str) -> Any:
    """Extract and parse JSON from model output, tolerating fences and junk.

    Strategy, in order of preference:
      1. A fenced ```json block, if present.
      2. ``raw_decode`` from the first ``{`` or ``[``: this parses exactly ONE
         complete JSON value and IGNORES any trailing junk. That tolerance is
         the point -- live models occasionally append a stray brace or a
         sentence after an otherwise-valid object (observed in a live run:
         ``...}}} }``), which a naive "first-brace to last-brace" slice would
         turn into unbalanced, unparseable input.
      3. The whole stripped string, as a last resort.

    Raises ValueError if nothing parses -- callers decide whether that is fatal
    (synthesizer skips, loop feeds the error back to the model as an observation).
    """
    stripped = text.strip()
    decoder = json.JSONDecoder()

    def _raw_decode(s: str) -> Any:
        start = _first_json_start(s)
        if start is None:
            raise ValueError("no JSON opener found")
        return decoder.raw_decode(s[start:])[0]

    # 1. Primary: junk-tolerant decode from the earliest opener. This also
    #    handles fenced output, because the JSON inside a ```json fence still
    #    starts with { or [ and raw_decode simply ignores the trailing ``` .
    #    Doing this FIRST (before any fence regex) keeps a code fence embedded
    #    in a string value -- e.g. a write_file whose content is a markdown doc
    #    containing ```python ... ``` -- from being mistaken for the wrapper.
    try:
        return _raw_decode(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Fallback: an explicit fenced block, for when the earliest opener is a
    #    non-JSON brace in prose and the real JSON is only inside the fence.
    match = _FENCE_RE.search(text)
    if match:
        fenced = match.group(1).strip()
        for attempt in (lambda: json.loads(fenced), lambda: _raw_decode(fenced)):
            try:
                return attempt()
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

    # 3. Last resort: parse the whole stripped string.
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        pass

    raise ValueError(f"no parseable JSON found in model output: {text[:200]!r}")
