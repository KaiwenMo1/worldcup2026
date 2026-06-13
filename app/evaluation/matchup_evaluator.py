"""Evaluate ranked matchup hypotheses against normalized event evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unicodedata

from app.evaluation.postmatch_evaluator import stable_evaluation_id
from app.evaluation.schemas import CompletedMatch, EvaluationStatus, MatchupEvaluation
from app.evaluation.storage import load_records, upsert_records
from app.ingestion.event_data_ingestion import MatchEvent, MatchEventType, MatchSummarySignal
from app.tactics.matchup_engine import build_matchup_edges
from app.tactics.schemas import MatchupEdge


ROOT = Path(__file__).resolve().parents[2]
MATCHUP_EVALUATION_PATH = ROOT / "data" / "derived" / "matchup_evaluation_results.csv"
MATCHUP_EVALUATION_FIELDS = list(MatchupEvaluation.model_fields)


def _name_key(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    ).casefold().strip()


def _player_names(value: str | None) -> set[str]:
    return {_name_key(name) for name in (value or "").split(",") if name.strip()}


def _player_impact(events: list[MatchEvent], names: set[str]) -> float:
    selected = [event for event in events if _name_key(event.player) in names]
    return sum(
        (2.0 * (event.xg or 0))
        + (0.30 if event.event_type in {MatchEventType.SHOT, MatchEventType.GOAL, MatchEventType.PENALTY} else 0)
        + (0.25 if event.event_type == MatchEventType.KEY_PASS else 0)
        + (0.15 if event.event_type in {MatchEventType.PROGRESSIVE_PASS, MatchEventType.PROGRESSIVE_CARRY} else 0)
        + (0.10 if event.event_type in {MatchEventType.TACKLE, MatchEventType.INTERCEPTION, MatchEventType.DUEL} else 0)
        for event in selected
    )


def _observed_values(
    edge: MatchupEdge,
    summaries: dict[str, MatchSummarySignal],
    events: list[MatchEvent],
) -> tuple[str, float | None, float | None]:
    team_a = summaries.get(edge.team_a.casefold())
    team_b = summaries.get(edge.team_b.casefold())
    if edge.matchup_type in {"winger_vs_fullback", "striker_vs_centerbacks"}:
        return (
            "named_player_event_impact",
            _player_impact(events, _player_names(edge.team_a_player)),
            _player_impact(events, _player_names(edge.team_b_player)),
        )
    if team_a is None or team_b is None:
        return "missing_match_summary", None, None
    if edge.matchup_type == "midfield_control":
        return "field_tilt", team_a.field_tilt, team_b.field_tilt
    if edge.matchup_type == "set_piece_edge":
        return "set_piece_xg", team_a.set_piece_xg, team_b.set_piece_xg
    if edge.matchup_type == "transition_defense_risk":
        return "counterattack_xg", team_a.counterattack_xg, team_b.counterattack_xg
    if edge.matchup_type == "press_vs_build_up":
        return "pressing_proxy", team_a.pressing_proxy, team_b.pressing_proxy
    return "unsupported_matchup_type", None, None


def evaluate_matchup_edge(
    completed: CompletedMatch,
    edge: MatchupEdge,
    summaries: dict[str, MatchSummarySignal],
    events: list[MatchEvent],
    *,
    evaluated_at: datetime | None = None,
) -> MatchupEvaluation:
    metric, team_a_value, team_b_value = _observed_values(edge, summaries, events)
    observed_edge = None
    observed_favored = None
    confirmed = None
    status = EvaluationStatus.NOT_EVALUABLE
    if team_a_value is not None and team_b_value is not None:
        scale = max(abs(team_a_value) + abs(team_b_value), 1.0)
        observed_edge = max(-1.0, min(1.0, (team_a_value - team_b_value) / scale))
        if abs(observed_edge) >= 0.05:
            observed_favored = edge.team_a if observed_edge > 0 else edge.team_b
        if edge.favored_team is not None and observed_favored is not None:
            confirmed = edge.favored_team.casefold() == observed_favored.casefold()
            status = EvaluationStatus.EVALUATED
        else:
            status = EvaluationStatus.PARTIAL
    explanation = (
        f"Prediction favored {edge.favored_team or 'neither team'}; observed {metric} "
        f"favored {observed_favored or 'neither team'}. Observed edge is "
        "(team A evidence - team B evidence) / max(total absolute evidence, 1). "
        "Edge scores remain ranking scores, not probabilities."
    )
    return MatchupEvaluation(
        evaluation_id=stable_evaluation_id(
            "matchup",
            completed.match_id,
            edge.matchup_type,
            edge.team_a_player or "",
            edge.team_b_player or "",
        ),
        match_id=completed.match_id,
        matchup_type=edge.matchup_type,
        team_a=edge.team_a,
        team_b=edge.team_b,
        team_a_player=edge.team_a_player,
        team_b_player=edge.team_b_player,
        predicted_favored_team=edge.favored_team,
        observed_favored_team=observed_favored,
        edge_score=edge.edge_score,
        observed_edge=round(observed_edge, 3) if observed_edge is not None else None,
        edge_confirmed=confirmed,
        evidence_metric=metric,
        team_a_evidence=round(team_a_value, 3) if team_a_value is not None else None,
        team_b_evidence=round(team_b_value, 3) if team_b_value is not None else None,
        status=status,
        explanation=explanation,
        data_quality=edge.data_quality,
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
    )


def evaluate_matchups(
    completed: CompletedMatch,
    summaries: list[MatchSummarySignal],
    events: list[MatchEvent],
    *,
    evaluated_at: datetime | None = None,
) -> list[MatchupEvaluation]:
    by_team = {summary.team.casefold(): summary for summary in summaries}
    return [
        evaluate_matchup_edge(completed, edge, by_team, events, evaluated_at=evaluated_at)
        for edge in build_matchup_edges(completed.team_a, completed.team_b, completed.match_id)
    ]


def write_matchup_evaluations(records: list[MatchupEvaluation], path: Path = MATCHUP_EVALUATION_PATH) -> list:
    return upsert_records(path, records, MatchupEvaluation, MATCHUP_EVALUATION_FIELDS)


def load_matchup_evaluations(path: Path = MATCHUP_EVALUATION_PATH) -> tuple[list[MatchupEvaluation], list]:
    return load_records(path, MatchupEvaluation, MATCHUP_EVALUATION_FIELDS)
