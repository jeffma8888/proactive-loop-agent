"""Scout package (L2): synthesize a ranked goal slate and gate it for autonomy.

Public surface:
- ``GoalSynthesizer`` / ``SYNTHESIZE_TAG`` — signals -> LLM -> GoalSlate.
- ``gate`` / ``gate_slate`` — the autonomy-contract policy gate.
"""

from __future__ import annotations

from proactive_loop.scout.policy import gate, gate_slate
from proactive_loop.scout.synthesizer import SYNTHESIZE_TAG, GoalSynthesizer

__all__ = [
    "GoalSynthesizer",
    "SYNTHESIZE_TAG",
    "gate",
    "gate_slate",
]
