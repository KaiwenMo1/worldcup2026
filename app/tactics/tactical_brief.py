"""Compose transparent tactical explanations around an existing match forecast."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from app.tactics.data_coverage import team_data_coverage
from app.tactics.manager_skills import (
    generate_manager_plan,
    list_manager_registry,
    list_manager_skills,
    load_team_manager_record,
    load_team_manager_skill,
)
from app.tactics.matchup_engine import build_matchup_edges
from app.tactics.player_profiles import load_player_availability, load_projected_lineup
from app.tactics.schemas import (
    AvailabilityRisk,
    ManagerPlan,
    MatchContext,
    MatchupEdge,
    PlanConfidence,
    TacticalBrief,
    TacticalForecastSnapshot,
)

ROOT = Path(__file__).resolve().parents[2]
MANAGER_CURATION_COVERAGE_PATH = ROOT / "data" / "derived" / "manager_curation_coverage.csv"


def manager_curation_summary(path: Path = MANAGER_CURATION_COVERAGE_PATH) -> dict[str, Any]:
    """Summarize the auditable manager-skill curation ledger."""
    if not path.exists():
        return {
            "observed_managers": 0,
            "observed_matches": 0,
            "evidence_backed": 0,
            "limited_observed": 0,
            "research_gaps": 0,
            "source": str(path.relative_to(ROOT)),
        }
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    statuses = Counter(row.get("curation_status", "") for row in rows)
    return {
        "observed_managers": sum(int(row.get("observed_matches") or 0) > 0 for row in rows),
        "observed_matches": sum(int(row.get("observed_matches") or 0) for row in rows),
        "evidence_backed": statuses["evidence_backed"],
        "limited_observed": statuses["limited_observed"],
        "research_gaps": statuses["research_gap"],
        "source": str(path.relative_to(ROOT)),
    }


def _forecast_snapshot(forecast: dict[str, Any] | None) -> TacticalForecastSnapshot:
    if not forecast:
        return TacticalForecastSnapshot(
            available=False,
            source="none",
            data_quality="fallback",
            fallback_note="No existing match forecast was supplied; tactical analysis is shown without probabilities.",
        )

    expected = forecast.get("expected_score")
    expected_score = None
    if isinstance(expected, dict) and {"team_a", "team_b"}.issubset(expected):
        expected_score = {
            "team_a": float(expected["team_a"]),
            "team_b": float(expected["team_b"]),
        }

    probabilities = {
        str(key): float(value)
        for key, value in (forecast.get("probabilities") or {}).items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    scorelines = [row for row in (forecast.get("scorelines") or []) if isinstance(row, dict)]
    most_likely = max(scorelines, key=lambda row: float(row.get("probability", 0)), default=None)
    available = expected_score is not None or bool(probabilities)
    return TacticalForecastSnapshot(
        available=available,
        expected_score=expected_score,
        probabilities=probabilities,
        most_likely_score=most_likely,
        source="existing_match_forecast",
        data_quality="existing_api_forecast" if available else "partial_fallback",
        fallback_note=None if available else "The supplied forecast did not contain expected score or probabilities.",
    )


def _availability_risks(team: str, match_id: str | None) -> tuple[list[AvailabilityRisk], list[str]]:
    lineup = load_projected_lineup(team, match_id)
    availability = load_player_availability()
    notes: list[str] = []
    if not lineup:
        notes.append(f"No projected or confirmed lineup is available for {team}; availability risk could not be ranked.")
        return [], notes

    risks: list[AvailabilityRisk] = []
    covered = 0
    for player in lineup:
        status = availability.get(player.player_id)
        if status is None:
            continue
        covered += 1
        availability_loss = 1 - status.availability
        minutes_loss = 1 - min(status.minutes_limit / 90, 1)
        status_penalty = 0.15 if status.status.casefold() not in {"available", "fit", "confirmed"} else 0.0
        impact_weight = min(max(status.impact_score / 100, 0.35), 1.25)
        risk_score = min(
            1.0,
            player.starter_probability
            * ((0.65 * availability_loss) + (0.25 * minutes_loss) + status_penalty)
            * impact_weight,
        )
        if risk_score <= 0.02 and status_penalty == 0:
            continue
        reasons = []
        if status.status:
            reasons.append(f"status is {status.status}")
        if status.availability < 1:
            reasons.append(f"availability is {status.availability:.0%}")
        if status.minutes_limit < 90:
            reasons.append(f"minutes limit is {status.minutes_limit}")
        risks.append(
            AvailabilityRisk(
                player_id=player.player_id,
                player=player.player,
                team=team,
                projected_role=player.position_slot,
                starter_probability=player.starter_probability,
                status=status.status,
                availability=status.availability,
                minutes_limit=status.minutes_limit,
                impact_score=status.impact_score,
                risk_score=round(risk_score, 3),
                reason="; ".join(reasons) or "availability entry is present but carries little projected risk",
                source=status.source,
                data_quality=player.data_quality,
            )
        )

    if covered == 0:
        notes.append(f"No availability entries matched the projected {team} lineup.")
    risks.sort(key=lambda risk: risk.risk_score, reverse=True)
    return risks, notes


def _brief_confidence(
    plan_a: ManagerPlan,
    plan_b: ManagerPlan,
    edges: list[MatchupEdge],
    fallback_notes: list[str],
) -> PlanConfidence:
    scores = [plan_a.confidence.score, plan_b.confidence.score]
    scores.extend(
        float(edge.relevant_features.get("lineup_reliability"))
        for edge in edges
        if isinstance(edge.relevant_features.get("lineup_reliability"), (int, float))
    )
    score = sum(scores) / len(scores) if scores else 0.0
    if fallback_notes:
        score = max(0.0, score - min(0.25, len(fallback_notes) * 0.05))
    level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
    return PlanConfidence(
        level=level,
        score=round(score, 3),
        meaning=(
            "coverage confidence in the manager, lineup, matchup, and availability evidence used by this brief; "
            "not match-outcome probability or model calibration"
        ),
    )


def _summary(
    team_a: str,
    team_b: str,
    forecast: TacticalForecastSnapshot,
    plan_a: ManagerPlan,
    plan_b: ManagerPlan,
    edges: list[MatchupEdge],
    risks: list[AvailabilityRisk],
) -> str:
    parts = []
    if forecast.available and forecast.probabilities:
        labels = {
            "team_a_win": team_a,
            "draw": "draw",
            "team_b_win": team_b,
        }
        leading_key = max(forecast.probabilities, key=forecast.probabilities.get)
        parts.append(f"The existing forecast leans toward {labels.get(leading_key, leading_key)}.")
    else:
        parts.append("No match forecast is available, so this brief ranks tactical evidence only.")

    parts.append(
        f"{team_a} projects a {plan_a.base_plan} approach; {team_b} projects a {plan_b.base_plan} approach."
    )
    decisive = next((edge for edge in edges if edge.favored_team), None)
    if decisive:
        parts.append(
            f"The strongest ranked matchup is {decisive.matchup_type.replace('_', ' ')}, favoring "
            f"{decisive.favored_team} ({decisive.edge_label})."
        )
    if risks:
        parts.append(f"The highest availability risk is {risks[0].player} for {risks[0].team}.")
    return " ".join(parts)


def _sources(
    forecast: TacticalForecastSnapshot,
    plans: list[ManagerPlan],
    edges: list[MatchupEdge],
    risks: list[AvailabilityRisk],
) -> list[str]:
    values = {forecast.source}
    for plan in plans:
        if plan.manager_id:
            values.add(f"manager_skill:{plan.manager_id}")
        values.update(f"evidence:{reference.source_id}" for reference in plan.source_refs)
    values.update(edge.source for edge in edges)
    values.update(risk.source for risk in risks)
    return sorted(value for value in values if value and value != "none")


def _data_quality(
    forecast: TacticalForecastSnapshot,
    plans: list[ManagerPlan],
    edges: list[MatchupEdge],
    fallback_notes: list[str],
) -> str:
    if fallback_notes:
        return "mixed_with_fallback"
    qualities = {forecast.data_quality}
    qualities.update(plan.data_quality for plan in plans)
    qualities.update(edge.data_quality for edge in edges)
    return next(iter(qualities)) if len(qualities) == 1 else "mixed_sources"


def list_manager_catalog() -> dict[str, Any]:
    """Return the full registry separately from evidence-backed tactical skills."""
    registry = list_manager_registry()
    skills = list_manager_skills()
    return {
        "managers": registry,
        "skills": [manager.model_dump(mode="json") for manager in skills],
        "count": len(registry),
        "skills_count": len(skills),
        "curation": manager_curation_summary(),
        "source": "data/managers.csv + data/manager_skills/*.json",
        "data_quality": "mixed_registry_and_skill_evidence",
        "fallback_notes": [] if skills else ["No manager skill files are available."],
    }


def get_team_manager_overview(team: str) -> dict[str, Any]:
    """Return one team's manager skill and a safe neutral plan when it is missing."""
    skill = load_team_manager_skill(team)
    registry = load_team_manager_record(team)
    plan = generate_manager_plan(team, "unspecified opponent")
    return {
        "team": team,
        "registry": registry,
        "manager": skill.model_dump(mode="json") if skill else None,
        "plan": plan.model_dump(mode="json"),
        "source": f"manager_skill:{skill.manager_id}" if skill else "neutral_manager_fallback",
        "data_quality": plan.data_quality,
        "fallback_notes": [plan.fallback_note] if plan.fallback_note else [],
    }


def build_matchup_report(team_a: str, team_b: str, match_id: str | None = None, top_n: int = 8) -> dict[str, Any]:
    """Return a ranked matchup report with visible missing-lineup fallbacks."""
    edges = build_matchup_edges(team_a, team_b, match_id)
    fallback_notes = []
    if not load_projected_lineup(team_a, match_id):
        fallback_notes.append(f"No projected or confirmed lineup is available for {team_a}.")
    if not load_projected_lineup(team_b, match_id):
        fallback_notes.append(f"No projected or confirmed lineup is available for {team_b}.")
    return {
        "team_a": team_a,
        "team_b": team_b,
        "match_id": match_id,
        "edges": [edge.model_dump(mode="json") for edge in edges[:top_n]],
        "edge_score_meaning": "transparent ranking strength from 0 to 1; not a calibrated probability",
        "source": "transparent_rule_engine",
        "data_quality": "partial_fallback" if fallback_notes else "mixed_sources",
        "fallback_notes": fallback_notes,
    }


def build_tactical_brief(
    team_a: str,
    team_b: str,
    *,
    match_id: str | None = None,
    forecast: dict[str, Any] | None = None,
    match_context_a: MatchContext | None = None,
    match_context_b: MatchContext | None = None,
    top_matchups: int = 5,
) -> TacticalBrief:
    """Explain an existing forecast without changing any forecast values."""
    forecast_snapshot = _forecast_snapshot(forecast)
    plan_a = generate_manager_plan(team_a, team_b, match_context_a)
    plan_b = generate_manager_plan(team_b, team_a, match_context_b)
    edges = build_matchup_edges(team_a, team_b, match_id)[:top_matchups]
    risks_a, notes_a = _availability_risks(team_a, match_id)
    risks_b, notes_b = _availability_risks(team_b, match_id)
    risks = sorted(risks_a + risks_b, key=lambda risk: risk.risk_score, reverse=True)

    fallback_notes = [*notes_a, *notes_b]
    if forecast_snapshot.fallback_note:
        fallback_notes.append(forecast_snapshot.fallback_note)
    for plan in (plan_a, plan_b):
        if plan.fallback_note:
            fallback_notes.append(plan.fallback_note)
    if not edges:
        fallback_notes.append("No tactical matchup edges could be built from the available data.")

    return TacticalBrief(
        team_a=team_a,
        team_b=team_b,
        forecast=forecast_snapshot,
        manager_plan_a=plan_a,
        manager_plan_b=plan_b,
        top_matchup_edges=edges,
        availability_risks=risks,
        tactical_summary=_summary(team_a, team_b, forecast_snapshot, plan_a, plan_b, edges, risks),
        data_coverage={
            team_a: team_data_coverage(team_a, match_id),
            team_b: team_data_coverage(team_b, match_id),
        },
        sources=_sources(forecast_snapshot, [plan_a, plan_b], edges, risks),
        evidence_confidence=_brief_confidence(plan_a, plan_b, edges, fallback_notes),
        data_quality=_data_quality(forecast_snapshot, [plan_a, plan_b], edges, fallback_notes),
        fallback_notes=fallback_notes,
    )
