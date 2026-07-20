"""Goal synthesis: turn a workspace snapshot into a ranked slate of goals.

This is the L2 "scout" brain. It compresses the raw context signals into a
compact prompt, asks the LLM to propose candidate goals, and validates the
reply into typed :class:`~proactive_loop.models.CandidateGoal` objects.

WHY skip-not-fail on bad entries: an LLM will occasionally emit a
half-formed goal (wrong category string, out-of-range number). One bad apple
must not sink the whole scan, so invalid entries are dropped silently and the
good ones still surface. WHY dedupe by normalized title: the same underlying
signal (a stale TODO, say) can inspire near-identical goals; collapsing them
keeps the slate short and the ranking honest.

LLM JSON contract (the model MUST return exactly this shape)::

    [
      {
        "title": str,                 # short imperative goal name
        "rationale": str,             # WHY this goal, grounded in the signals
        "category": str,              # one of GoalCategory values
        "impact": float,              # 0..5
        "urgency": float,             # 0..5
        "confidence": float,          # 0..1
        "effort_weight": float,       # >= 0.5 (bigger == more effort)
        "appropriate_now": bool,      # false == defer / needs a better moment
        "sources": [str, ...],        # signal summaries / refs that justify it
        "suggested_first_steps": [str, ...]
      },
      ...
    ]

The model MUST NOT send a "score" field: score is a computed field on
CandidateGoal (impact * urgency * confidence / effort_weight) so ranking can
never drift from its inputs. Any extra keys are ignored.
"""

from __future__ import annotations

from pydantic import ValidationError

from proactive_loop.config import Settings
from proactive_loop.llm.client import LLMClient, parse_json_block
from proactive_loop.models import CandidateGoal, GoalCategory, GoalSlate, WorkspaceSnapshot

#: Call-site tag so scripted clients and providers can route synthesis calls.
SYNTHESIZE_TAG = "synthesize"

# Prompt caps keep token cost bounded and the signal list scannable. These are
# deliberately small: the goal is a representative sample per kind, not a dump.
_MAX_SIGNALS_PER_KIND = 8
_MAX_SUMMARY_CHARS = 200


def _build_prompt(snapshot: WorkspaceSnapshot) -> str:
    """Render the snapshot as a compact, kind-grouped context brief.

    WHY group by kind and cap: the synthesizer reasons better over a tidy,
    sectioned digest than a flat firehose, and capping per kind stops one noisy
    collector (e.g. hundreds of recent files) from crowding out the rest.
    """
    lines: list[str] = [f"Workspace root: {snapshot.root}", ""]
    grouped = snapshot.by_kind()
    if not grouped:
        lines.append("(no signals collected)")
    for kind, signals in grouped.items():
        lines.append(f"## {kind} ({len(signals)} signal(s))")
        for signal in signals[:_MAX_SIGNALS_PER_KIND]:
            summary = signal.summary.strip()[:_MAX_SUMMARY_CHARS]
            lines.append(f"- {summary}")
        extra = len(signals) - _MAX_SIGNALS_PER_KIND
        if extra > 0:
            lines.append(f"- (+{extra} more)")
        lines.append("")
    return "\n".join(lines).strip()


def _validate_entry(entry: object) -> CandidateGoal | None:
    """Coerce one raw LLM dict into a CandidateGoal, or None if it is invalid.

    WHY swallow the error: a malformed entry is expected occasionally and must
    not abort the scan (see module docstring).
    """
    if not isinstance(entry, dict):
        return None
    try:
        return CandidateGoal.model_validate(entry)
    except ValidationError:
        return None


class GoalSynthesizer:
    """Synthesize a ranked goal slate from a workspace snapshot via the LLM."""

    def __init__(self, client: LLMClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    def synthesize(self, snapshot: WorkspaceSnapshot) -> GoalSlate:
        """Scan signals -> LLM -> validated, deduped GoalSlate.

        The returned slate is unsorted storage; callers use ``slate.ranked()``
        for display order. Scores are never computed here — they live on
        CandidateGoal as a computed field.
        """
        prompt = _build_prompt(snapshot)
        response = self._client.complete(
            system=self._system_prompt(),
            prompt=prompt,
            tag=SYNTHESIZE_TAG,
        )
        goals = self._parse_goals(response.text)
        return GoalSlate(workspace_root=snapshot.root, goals=goals)

    def _system_prompt(self) -> str:
        """Instruct the model on role and output contract.

        WHY name the sensitive categories from settings: the model still
        proposes them (the policy gate decides autonomy downstream), but
        telling it which ones require human approval yields better-calibrated
        ``appropriate_now`` and ``confidence`` values.
        """
        categories = ", ".join(c.value for c in GoalCategory)
        sensitive = ", ".join(
            sorted(c.value for c in self._settings.sensitive_categories)
        )
        return (
            "You are a proactivity scout. Given signals about a person's "
            "working context, propose a short slate of candidate goals worth "
            "pursuing next. Respond with ONLY a JSON array of goal objects.\n"
            "Each goal is executed by a downstream agent whose ONLY tools are "
            "writing, reading, and listing files in a sandboxed workspace. So "
            "propose goals that can be MEANINGFULLY ADVANCED by producing a "
            "written artifact -- a plan, design doc, checklist, analysis, or "
            "index. Do NOT propose goals whose completion needs running "
            "commands, executing tests, publishing, network access, or editing "
            "source code, because the agent cannot do those and will stall. "
            "Prefer 'Draft a release checklist for X' over 'Publish X'; prefer "
            "'Write a triage plan for the open TODOs' over 'Fix all the TODOs'. "
            "Frame each title as the artifact to produce.\n"
            f"Valid categories: {categories}.\n"
            f"Categories that always require human approval: {sensitive}.\n"
            "Each object has keys: title, rationale, category, impact (0-5), "
            "urgency (0-5), confidence (0-1), effort_weight (>=0.5), "
            "appropriate_now (bool), sources (list of strings), "
            "suggested_first_steps (list of strings). Do NOT include a score "
            "field; it is computed downstream from the numeric fields."
        )

    def _parse_goals(self, text: str) -> list[CandidateGoal]:
        """Parse the JSON array, validate entries, and dedupe by title.

        Unparseable output or a non-array payload yields an empty list rather
        than raising: a scan that finds no usable goals is a valid outcome.
        """
        try:
            raw = parse_json_block(text)
        except ValueError:
            return []
        if not isinstance(raw, list):
            return []

        goals: list[CandidateGoal] = []
        seen: set[str] = set()
        for entry in raw:
            goal = _validate_entry(entry)
            if goal is None:
                continue
            key = goal.title.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            goals.append(goal)
        return goals
