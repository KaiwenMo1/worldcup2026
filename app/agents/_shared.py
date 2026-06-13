"""Shared deterministic input normalization for Prediction Arena agents."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.prediction_arena.schemas import PredictionStage, PredictionTarget, TargetPick


def as_dict(value: BaseModel | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value or {})


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def outcome_probabilities(forecast: dict[str, Any] | None) -> dict[str, float]:
    raw = as_dict(forecast).get("probabilities") or {}
    values = {
        key: float(raw.get(key) or 0)
        for key in ("team_a_win", "draw", "team_b_win")
    }
    if max(values.values(), default=0) > 1:
        values = {key: value / 100 for key, value in values.items()}
    total = sum(values.values())
    if total <= 0:
        return {"team_a_win": 1 / 3, "draw": 1 / 3, "team_b_win": 1 / 3}
    return {key: value / total for key, value in values.items()}


def score_candidates(forecast: dict[str, Any] | None) -> list[TargetPick]:
    payload = as_dict(forecast)
    rows = [row for row in payload.get("scorelines", []) if isinstance(row, dict)]
    candidates = []
    for row in rows[:5]:
        probability = float(row.get("probability") or 0)
        if probability > 1:
            probability /= 100
        candidates.append(
            TargetPick(
                pick=f"{row.get('team_a_score', 0)}-{row.get('team_b_score', 0)}",
                score=f"{row.get('team_a_score', 0)}-{row.get('team_b_score', 0)}",
                confidence=round(clamp(probability), 3),
            )
        )
    if candidates:
        return candidates
    expected = payload.get("expected_score") or {}
    score_a = max(0, round(float(expected.get("team_a") or 1)))
    score_b = max(0, round(float(expected.get("team_b") or 1)))
    return [TargetPick(pick=f"{score_a}-{score_b}", score=f"{score_a}-{score_b}", confidence=0.1)]


def favorite_and_underdog(
    team_a: str,
    team_b: str,
    forecast: dict[str, Any] | None,
) -> tuple[str, str, float, float]:
    probabilities = outcome_probabilities(forecast)
    if probabilities["team_a_win"] >= probabilities["team_b_win"]:
        return team_a, team_b, probabilities["team_a_win"], probabilities["team_b_win"]
    return team_b, team_a, probabilities["team_b_win"], probabilities["team_a_win"]


def build_prediction_target(
    team_a: str,
    team_b: str,
    stage: PredictionStage,
    forecast: dict[str, Any] | None,
    *,
    regular_pick: str | None = None,
    regular_score: str | None = None,
    regular_confidence: float | None = None,
    qualification_pick: str | None = None,
    qualification_confidence: float | None = None,
) -> PredictionTarget:
    probabilities = outcome_probabilities(forecast)
    labels = {"team_a_win": team_a, "draw": "Draw", "team_b_win": team_b}
    leading_key = max(probabilities, key=probabilities.get)
    candidates = score_candidates(forecast)
    pick = regular_pick or labels[leading_key]
    score = regular_score or next(
        (
            candidate.score
            for candidate in candidates
            if candidate.score and score_matches_pick(candidate.score, pick, team_a, team_b)
        ),
        scenario_score_for_pick(team_a, team_b, pick),
    )
    confidence = regular_confidence if regular_confidence is not None else probabilities[leading_key]
    if stage == PredictionStage.GROUP:
        return PredictionTarget(
            regular_time_90=TargetPick(pick=pick, score=score, confidence=round(clamp(confidence), 3)),
            exact_score_candidates=candidates,
        )

    favorite, _, favorite_probability, _ = favorite_and_underdog(team_a, team_b, forecast)
    advance_pick = qualification_pick or f"{favorite} advance"
    advance_confidence = qualification_confidence
    if advance_confidence is None:
        advance_confidence = clamp(favorite_probability + probabilities["draw"] * 0.35, 0.35, 0.74)
    penalty_probability = clamp(probabilities["draw"] * 0.55, 0.08, 0.42)
    return PredictionTarget(
        regular_time_90=TargetPick(pick=pick, score=score, confidence=round(clamp(confidence), 3)),
        after_extra_time=TargetPick(pick=advance_pick, confidence=round(clamp(advance_confidence), 3)),
        qualification=TargetPick(pick=advance_pick, confidence=round(clamp(advance_confidence), 3)),
        penalty_shootout_probability=round(penalty_probability, 3),
        exact_score_candidates=candidates,
    )


def tactical_edges(tactical_brief: BaseModel | dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        dict(edge)
        for edge in as_dict(tactical_brief).get("top_matchup_edges", [])
        if isinstance(edge, dict)
    ]


def fallback_notes(tactical_brief: BaseModel | dict[str, Any] | None) -> list[str]:
    return [str(note) for note in as_dict(tactical_brief).get("fallback_notes", []) if note]


def availability_risks(tactical_brief: BaseModel | dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        dict(risk)
        for risk in as_dict(tactical_brief).get("availability_risks", [])
        if isinstance(risk, dict)
    ]


def scenario_score(team_a: str, underdog: str) -> str:
    return "0-1" if underdog != team_a else "1-0"


def score_matches_pick(score: str, pick: str, team_a: str, team_b: str) -> bool:
    score_a, score_b = (int(value) for value in score.split("-"))
    if pick.casefold() == "draw":
        return score_a == score_b
    if pick.casefold() == team_a.casefold():
        return score_a > score_b
    if pick.casefold() == team_b.casefold():
        return score_b > score_a
    return True


def scenario_score_for_pick(team_a: str, team_b: str, pick: str) -> str:
    if pick.casefold() == "draw":
        return "1-1"
    return "1-0" if pick.casefold() == team_a.casefold() else "0-1"
