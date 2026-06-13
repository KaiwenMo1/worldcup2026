"""Prediction Arena agent contracts."""

from app.agents.schemas import (
    AgentNarrativeAdapter,
    AgentPrediction,
    ExpertAgentPrediction,
    ExpertMatchup,
    FinalForecast,
    KevinAgentPrediction,
    SkepticReview,
    UpsetAgentPrediction,
)
from app.agents.expert_agent import run_expert_agent
from app.agents.final_forecast_agent import run_final_forecast_agent
from app.agents.kevin_agent import run_kevin_agent
from app.agents.skeptic_agent import run_skeptic_agent
from app.agents.upset_agent import run_upset_agent

__all__ = [
    "AgentNarrativeAdapter",
    "AgentPrediction",
    "ExpertAgentPrediction",
    "ExpertMatchup",
    "FinalForecast",
    "KevinAgentPrediction",
    "SkepticReview",
    "UpsetAgentPrediction",
    "run_expert_agent",
    "run_final_forecast_agent",
    "run_kevin_agent",
    "run_skeptic_agent",
    "run_upset_agent",
]
