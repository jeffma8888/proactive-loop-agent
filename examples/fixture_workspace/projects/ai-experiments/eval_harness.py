"""Offline evaluation harness for the tiny agent.

Goal of this file: score a batch of scripted scenarios without any network so I
can iterate on the loop's stopping logic quickly.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent import TinyAgent


@dataclass
class Scenario:
    """One fixed evaluation case with an expected step budget."""

    name: str
    goal: str
    max_expected_steps: int


SCENARIOS = [
    Scenario("trivial", "say hello", 1),
    Scenario("bounded", "write a short note", 3),
]


def evaluate(scenario: Scenario) -> dict:
    """Run one scenario and report whether it stayed within budget."""
    state = TinyAgent().run(scenario.goal)
    return {
        "name": scenario.name,
        "steps": state.steps_taken,
        "within_budget": state.steps_taken <= scenario.max_expected_steps,
    }


def main() -> None:
    # TODO: emit a JSON report and track pass-rate over time so regressions in
    # the stopping logic are visible across runs.
    for scenario in SCENARIOS:
        print(evaluate(scenario))


if __name__ == "__main__":
    main()
