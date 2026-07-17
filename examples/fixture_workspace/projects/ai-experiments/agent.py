"""A tiny plan-act-check agent sketch I'm using to learn agentic loops.

This is a personal learning project: I want to understand how a bounded
reasoning loop behaves before I trust one to run unattended.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class AgentState:
    """Everything one loop needs to remember between steps."""

    goal: str
    transcript: list[str] = field(default_factory=list)
    steps_taken: int = 0
    done: bool = False


class TinyAgent:
    """Loop a goal through plan -> act -> check until done or out of steps."""

    def __init__(self, max_steps: int = 5) -> None:
        self.max_steps = max_steps

    def plan(self, state: AgentState) -> dict:
        """Decide the next action from the current state.

        TODO: replace this hand-rolled heuristic with a real model call once
        the offline scripted client is wired up.
        """
        return {"tool": "noop", "args": {}}

    def act(self, action: dict) -> str:
        # FIXME: no sandbox yet -- a real tool call must not touch the filesystem
        # outside a dedicated artifacts directory.
        return f"executed {action.get('tool', 'noop')}"

    def check(self, state: AgentState, observation: str) -> bool:
        """Return True when the goal looks satisfied. XXX: needs real criteria."""
        return state.steps_taken >= 1

    def run(self, goal: str) -> AgentState:
        state = AgentState(goal=goal)
        while not state.done and state.steps_taken < self.max_steps:
            action = self.plan(state)
            observation = self.act(action)
            state.transcript.append(observation)
            state.steps_taken += 1
            state.done = self.check(state, observation)
        return state


if __name__ == "__main__":
    result = TinyAgent().run("summarize a document")
    print(json.dumps({"steps": result.steps_taken, "done": result.done}))
