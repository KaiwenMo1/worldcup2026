"""Agent-facing schema exports for the Prediction Arena."""

from typing import Any, Protocol

from app.prediction_arena.schemas import (
    AgentPrediction,
    ExpertAgentPrediction,
    ExpertMatchup,
    FinalForecast,
    KevinAgentPrediction,
    SkepticReview,
    UpsetAgentPrediction,
)


class AgentNarrativeAdapter(Protocol):
    """Future adapter seam for optional LLM narration over validated structured output."""

    def synthesize(self, agent_name: str, structured_output: dict[str, Any]) -> str:
        """Return narration without mutating the validated structured output."""


__all__ = [
    "AgentNarrativeAdapter",
    "AgentPrediction",
    "ExpertAgentPrediction",
    "ExpertMatchup",
    "FinalForecast",
    "KevinAgentPrediction",
    "SkepticReview",
    "UpsetAgentPrediction",
]
