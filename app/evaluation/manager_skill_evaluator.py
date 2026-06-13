"""Compare transparent manager hypotheses with observed match evidence."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.postmatch_evaluator import stable_evaluation_id
from app.evaluation.schemas import CompletedMatch, EvaluationStatus, ManagerSkillEvaluation
from app.evaluation.storage import load_records, upsert_records
from app.ingestion.event_data_ingestion import MatchEvent, MatchEventType, MatchSummarySignal
from app.tactics.manager_skills import generate_manager_plan, load_team_manager_skill


ROOT = Path(__file__).resolve().parents[2]
CONFIRMED_LINEUPS_PATH = ROOT / "data" / "confirmed_lineups.csv"
MANAGER_SKILL_EVALUATION_PATH = ROOT / "data" / "derived" / "manager_skill_evaluation_results.csv"
MANAGER_SKILL_EVALUATION_FIELDS = list(ManagerSkillEvaluation.model_fields)


def _normalized_formation(value: str | None) -> str | None:
    return value.replace(" ", "").replace("–", "-") if value else None


def load_actual_formation(match_id: str, team: str, path: Path = CONFIRMED_LINEUPS_PATH) -> str | None:
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row.get("match_id") == match_id
            and row.get("team", "").casefold() == team.casefold()
            and row.get("confirmed", "").casefold() in {"1", "true", "yes"}
        ]
    return next((row.get("formation") for row in rows if row.get("formation")), None)


def _pressing_range(expectation: str) -> tuple[float, float] | None:
    value = expectation.casefold()
    if any(token in value for token in ("high", "aggressive", "intense")):
        return 55.0, 100.0
    if any(token in value for token in ("low", "passive", "deep")):
        return 0.0, 40.0
    if any(token in value for token in ("selective", "situational", "medium", "mid")):
        return 25.0, 75.0
    return None


def _substitution_hit(patterns: list, events: list[MatchEvent]) -> bool | None:
    substitutions = [event for event in events if event.event_type == MatchEventType.SUBSTITUTION]
    if not events:
        return None
    if not patterns:
        return None
    windows = [tuple(int(value) for value in pattern.minute_window.split("-")) for pattern in patterns]
    return any(start <= event.minute <= end for event in substitutions for start, end in windows)


def evaluate_manager_skill(
    completed: CompletedMatch,
    team: str,
    opponent: str,
    summary: MatchSummarySignal | None,
    events: list[MatchEvent],
    *,
    actual_formation: str | None = None,
    evaluated_at: datetime | None = None,
) -> ManagerSkillEvaluation:
    plan = generate_manager_plan(team, opponent)
    skill = load_team_manager_skill(team)
    formation = actual_formation or load_actual_formation(completed.match_id, team)
    formation_hit = (
        _normalized_formation(plan.expected_formation) == _normalized_formation(formation)
        if plan.expected_formation and formation
        else None
    )
    pressing_expectation = skill.tactical_identity.pressing if skill else None
    pressing_range = _pressing_range(pressing_expectation) if pressing_expectation else None
    pressing_hit = (
        pressing_range[0] <= summary.pressing_proxy <= pressing_range[1]
        if summary is not None and pressing_range is not None
        else None
    )
    transition_expected = bool(plan.transition) if not plan.fallback_used else None
    transition_hit = (
        (summary.counterattack_xg >= 0.20) == transition_expected
        if summary is not None and transition_expected is not None
        else None
    )
    team_events = [event for event in events if event.team.casefold() == team.casefold()]
    substitutions = [event for event in team_events if event.event_type == MatchEventType.SUBSTITUTION]
    substitution_hit = _substitution_hit(plan.substitution_patterns, team_events)
    components = [formation_hit, pressing_hit, transition_hit, substitution_hit]
    scored = [item for item in components if item is not None]
    status = (
        EvaluationStatus.NOT_EVALUABLE
        if plan.fallback_used or not scored
        else EvaluationStatus.EVALUATED
        if len(scored) == 4
        else EvaluationStatus.PARTIAL
    )
    notes = [
        f"formation exact-match={'hit' if formation_hit else 'miss' if formation_hit is False else 'missing'}",
        (
            f"pressing proxy {summary.pressing_proxy:.1f} in expected range {pressing_range[0]:.0f}-{pressing_range[1]:.0f}"
            if summary is not None and pressing_range is not None
            else "pressing comparison=missing"
        ),
        (
            f"transition xG {summary.counterattack_xg:.2f} compared with 0.20 active-transition threshold"
            if summary is not None and transition_expected is not None
            else "transition comparison=missing"
        ),
        (
            f"substitution timing {'matched' if substitution_hit else 'missed'} at least one expected minute window; "
            "match-state timing is not inferred"
            if substitution_hit is not None
            else "substitution comparison=missing"
        ),
    ]
    return ManagerSkillEvaluation(
        evaluation_id=stable_evaluation_id("manager", completed.match_id, team, plan.manager_id or "fallback"),
        match_id=completed.match_id,
        team=team,
        opponent=opponent,
        manager_id=plan.manager_id,
        manager_name=plan.manager_name,
        expected_formation=plan.expected_formation,
        actual_formation=formation,
        formation_hit=formation_hit,
        pressing_expectation=pressing_expectation,
        actual_pressing_proxy=summary.pressing_proxy if summary else None,
        pressing_hit=pressing_hit,
        transition_expected=transition_expected,
        actual_transition_xg=summary.counterattack_xg if summary else None,
        transition_hit=transition_hit,
        substitution_patterns_expected=len(plan.substitution_patterns),
        actual_substitution_count=len(substitutions) if team_events else None,
        substitution_hit=substitution_hit,
        component_score=round(sum(scored) / len(scored), 3) if scored else None,
        evaluated_components=len(scored),
        status=status,
        evidence_confidence=plan.confidence.score,
        data_quality=plan.data_quality,
        explanation="; ".join(notes) + ". Missing evidence is excluded from the component score.",
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
    )


def evaluate_manager_skills(
    completed: CompletedMatch,
    summaries: list[MatchSummarySignal],
    events: list[MatchEvent],
    *,
    actual_formations: dict[str, str] | None = None,
    evaluated_at: datetime | None = None,
) -> list[ManagerSkillEvaluation]:
    by_team = {summary.team.casefold(): summary for summary in summaries}
    formations = actual_formations or {}
    return [
        evaluate_manager_skill(
            completed,
            team,
            opponent,
            by_team.get(team.casefold()),
            events,
            actual_formation=formations.get(team),
            evaluated_at=evaluated_at,
        )
        for team, opponent in ((completed.team_a, completed.team_b), (completed.team_b, completed.team_a))
    ]


def write_manager_skill_evaluations(
    records: list[ManagerSkillEvaluation],
    path: Path = MANAGER_SKILL_EVALUATION_PATH,
) -> list:
    return upsert_records(path, records, ManagerSkillEvaluation, MANAGER_SKILL_EVALUATION_FIELDS)


def load_manager_skill_evaluations(path: Path = MANAGER_SKILL_EVALUATION_PATH) -> tuple[list[ManagerSkillEvaluation], list]:
    return load_records(path, ManagerSkillEvaluation, MANAGER_SKILL_EVALUATION_FIELDS)
