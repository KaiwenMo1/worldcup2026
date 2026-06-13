"""Thin application service for future ingestion and evaluation API surfaces."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any
import unicodedata

from pydantic import BaseModel, Field, model_validator

from app.evaluation import (
    CompletedMatch,
    evaluate_completed_match,
    load_analyst_evaluations,
    load_completed_matches,
    load_manager_skill_evaluations,
    load_matchup_evaluations,
    load_model_evaluations,
    write_completed_evaluations,
)
from app.ingestion.event_data_ingestion import (
    MANUAL_MATCH_EVENTS_SAMPLE_PATH,
    ManualCsvEventAdapter,
    build_match_summary_signals,
    ingest_event_data,
    write_match_summary_signals,
    write_normalized_events,
)
from app.ingestion.injury_news_ingestion import (
    MANUAL_INJURY_NEWS_SAMPLE_PATH,
    ManualCsvInjuryNewsAdapter,
    build_injury_risk_signals,
    conflict_quality_issues,
    ingest_injury_news,
    load_injury_risk_signals,
    write_injury_risk_signals,
    write_normalized_injury_news,
)
from app.ingestion.lineup_ingestion import (
    ACTUAL_LINEUPS_PATH,
    LINEUP_DELTA_SIGNALS_PATH,
    CsvLineupAdapter,
    build_lineup_delta_signals,
    get_lineup_delta_signal,
    ingest_lineups,
    load_actual_lineups,
    write_actual_lineups,
    write_lineup_delta_signals,
)
from app.ingestion.normalizers import safe_read_csv, validate_rows
from app.ingestion.player_stats_ingestion import (
    FORM_SIGNAL_FIELDS,
    FORM_SIGNALS_PATH,
    MANUAL_SAMPLE_PATH,
    ROLE_VECTOR_FIELDS,
    ROLE_VECTORS_PATH,
    ManualCsvPlayerStatsAdapter,
    PlayerFormSignal,
    PlayerRoleVector,
    build_form_signals,
    build_role_vectors,
    ingest_player_stats,
    write_derived_outputs,
    write_normalized_stats,
)
from app.ingestion.provenance import append_data_quality_issues, append_ingestion_run, create_ingestion_run
from app.ingestion.schemas import DataQualityIssue, DataQualitySeverity, IngestionStatus
from app.ingestion.tactical_article_ingestion import (
    MANUAL_TACTICAL_EVIDENCE_SAMPLE_PATH,
    ManualCsvTacticalEvidenceAdapter,
    ingest_tactical_evidence,
    load_manager_skill_updates,
    load_normalized_tactical_evidence,
    suggest_manager_skill_updates,
    write_manager_skill_updates,
    write_normalized_tactical_evidence,
    apply_manager_skill_updates,
)
from app.tactics.player_profiles import get_team_role_depth, load_player_availability


ROOT = Path(__file__).resolve().parents[1]
PROJECTED_LINEUPS_PATH = ROOT / "data" / "projected_lineups.csv"
CONFIRMED_LINEUPS_PATH = ROOT / "data" / "confirmed_lineups.csv"


class RefreshRequest(BaseModel):
    source: str = "manual_csv"


class EvaluateMatchRequest(BaseModel):
    match_id: str = Field(min_length=1)
    team_a: str | None = None
    team_b: str | None = None
    team_a_score: int | None = Field(default=None, ge=0, le=30)
    team_b_score: int | None = Field(default=None, ge=0, le=30)
    team_a_formation: str | None = None
    team_b_formation: str | None = None
    use_model: bool = True

    @model_validator(mode="after")
    def validate_manual_result(self) -> "EvaluateMatchRequest":
        supplied = [self.team_a, self.team_b, self.team_a_score, self.team_b_score]
        if any(value is not None for value in supplied) and not all(value is not None for value in supplied):
            raise ValueError("manual evaluation requires both teams and both scores")
        return self


class ManagerSkillApplyRequest(BaseModel):
    manager_id: str | None = None
    apply: bool = False


def _dump(records: list[BaseModel]) -> list[dict[str, Any]]:
    return [record.model_dump(mode="json") for record in records]


def _issue_payload(issues: list[DataQualityIssue]) -> list[dict[str, Any]]:
    return _dump(issues)


def _log_refresh(
    *,
    script: str,
    rows_raw: int,
    rows_normalized: int,
    issues: list[DataQualityIssue],
) -> dict[str, Any]:
    serious = [issue for issue in issues if issue.severity in {DataQualitySeverity.ERROR, DataQualitySeverity.CRITICAL}]
    status = IngestionStatus.FAILED if rows_normalized == 0 and serious else IngestionStatus.PARTIAL if serious else IngestionStatus.SUCCEEDED
    run = create_ingestion_run(
        source_id="manual_csv",
        script=script,
        status=status,
        rows_raw=rows_raw,
        rows_normalized=min(rows_raw, rows_normalized),
        rows_failed=max(0, rows_raw - min(rows_raw, rows_normalized)),
        error_message=serious[0].problem if status == IngestionStatus.FAILED else None,
    )
    tagged = [issue.model_copy(update={"run_id": run.run_id}) for issue in issues]
    append_ingestion_run(run)
    if tagged:
        append_data_quality_issues(tagged)
    return {
        "ok": status != IngestionStatus.FAILED,
        "run": run.model_dump(mode="json"),
        "issue_count": len(tagged),
        "issues": _issue_payload(tagged[:25]),
    }


def _require_manual_source(request: RefreshRequest) -> None:
    if request.source != "manual_csv":
        raise ValueError("Only the manual_csv adapter is available in this phase.")


def refresh_player_stats(request: RefreshRequest) -> dict[str, Any]:
    _require_manual_source(request)
    result = ingest_player_stats(ManualCsvPlayerStatsAdapter(MANUAL_SAMPLE_PATH))
    issues = [*result.issues, *write_normalized_stats(result)]
    forms = build_form_signals(result.match_stats, result.season_stats)
    vectors, vector_issues = build_role_vectors(result.season_stats, forms)
    issues.extend(vector_issues)
    issues.extend(write_derived_outputs(vectors, forms))
    return {
        **_log_refresh(
            script="api.refresh_player_stats",
            rows_raw=result.rows_raw,
            rows_normalized=len(result.season_stats) + len(result.match_stats),
            issues=issues,
        ),
        "season_stats": len(result.season_stats),
        "match_stats": len(result.match_stats),
        "role_vectors": len(vectors),
        "form_signals": len(forms),
    }


def refresh_injury_news(request: RefreshRequest) -> dict[str, Any]:
    _require_manual_source(request)
    result = ingest_injury_news(ManualCsvInjuryNewsAdapter(MANUAL_INJURY_NEWS_SAMPLE_PATH))
    signals = build_injury_risk_signals(result.records)
    issues = [
        *result.issues,
        *write_normalized_injury_news(result.records),
        *write_injury_risk_signals(signals),
        *conflict_quality_issues(signals),
    ]
    return {
        **_log_refresh(
            script="api.refresh_injury_news",
            rows_raw=result.rows_raw,
            rows_normalized=len(result.records),
            issues=issues,
        ),
        "records": len(result.records),
        "risk_signals": len(signals),
        "manual_reviews": sum(signal.needs_manual_review for signal in signals),
    }


def refresh_tactical_evidence(request: RefreshRequest) -> dict[str, Any]:
    _require_manual_source(request)
    result = ingest_tactical_evidence(ManualCsvTacticalEvidenceAdapter(MANUAL_TACTICAL_EVIDENCE_SAMPLE_PATH))
    updates = suggest_manager_skill_updates(result.records)
    issues = [
        *result.issues,
        *write_normalized_tactical_evidence(result.records),
        *write_manager_skill_updates(updates),
    ]
    return {
        **_log_refresh(
            script="api.refresh_tactical_evidence",
            rows_raw=result.rows_raw,
            rows_normalized=len(result.records),
            issues=issues,
        ),
        "evidence_records": len(result.records),
        "suggested_updates": len(updates),
        "applied_updates": 0,
        "note": "Refresh only rebuilds the evidence-backed review queue; it never applies manager-skill updates.",
    }


def refresh_event_data(request: RefreshRequest) -> dict[str, Any]:
    _require_manual_source(request)
    result = ingest_event_data(ManualCsvEventAdapter(MANUAL_MATCH_EVENTS_SAMPLE_PATH))
    summaries = build_match_summary_signals(result.events)
    issues = [*result.issues, *write_normalized_events(result.events), *write_match_summary_signals(summaries)]
    return {
        **_log_refresh(
            script="api.refresh_event_data",
            rows_raw=result.rows_raw,
            rows_normalized=len(result.events),
            issues=issues,
        ),
        "events": len(result.events),
        "match_summary_signals": len(summaries),
        "matches": len({event.match_id for event in result.events}),
    }


def refresh_actual_lineups(source: Path = CONFIRMED_LINEUPS_PATH) -> dict[str, Any]:
    result = ingest_lineups(CsvLineupAdapter(source, require_confirmed=True))
    signals, signal_issues = build_lineup_delta_signals(result.records)
    issues = [
        *result.issues,
        *signal_issues,
        *write_actual_lineups(result.records),
        *write_lineup_delta_signals(signals),
    ]
    return {
        **_log_refresh(
            script="api.refresh_actual_lineups",
            rows_raw=result.rows_raw,
            rows_normalized=len(result.records),
            issues=issues,
        ),
        "actual_starters": len(result.records),
        "lineup_delta_signals": len(signals),
        "actual_lineups_path": str(ACTUAL_LINEUPS_PATH),
        "lineup_delta_path": str(LINEUP_DELTA_SIGNALS_PATH),
    }


def _load_derived(path: Path, fields: list[str], model: type[BaseModel]) -> tuple[list[BaseModel], list[DataQualityIssue]]:
    read = safe_read_csv(path, fields)
    validated = validate_rows(read.rows, model, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def get_player_role_vector(player_id: str) -> dict[str, Any]:
    vectors, vector_issues = _load_derived(ROLE_VECTORS_PATH, ROLE_VECTOR_FIELDS, PlayerRoleVector)
    forms, form_issues = _load_derived(FORM_SIGNALS_PATH, FORM_SIGNAL_FIELDS, PlayerFormSignal)
    selected = [vector for vector in vectors if vector.player_id.casefold() == player_id.casefold()]
    form = next((item for item in forms if item.player_id.casefold() == player_id.casefold()), None)
    return {
        "found": bool(selected or form),
        "player_id": player_id,
        "player": selected[0].player if selected else form.player if form else None,
        "team": selected[0].team if selected else form.team if form else None,
        "roles": _dump(selected),
        "form": form.model_dump(mode="json") if form else None,
        "issues": _issue_payload([*vector_issues, *form_issues]),
        "fallback_note": None if selected or form else "No derived role vector or form signal is available for this player.",
    }


def get_player_availability(player_id: str) -> dict[str, Any]:
    item = load_player_availability().get(player_id)
    return {
        "found": item is not None,
        "player_id": player_id,
        "availability": item.model_dump(mode="json") if item else None,
        "fallback_note": None if item else "No current availability record exists for this player.",
    }


def get_role_depth(team: str) -> dict[str, Any]:
    result = get_team_role_depth(team)
    return {
        **result,
        "found": bool(result.get("players")),
        "fallback_note": None if result.get("players") else "No tactical player profiles exist for this team.",
    }


def get_injury_status(team: str | None = None, match_id: str | None = None) -> dict[str, Any]:
    signals, issues = load_injury_risk_signals()
    if team:
        signals = [signal for signal in signals if signal.team.casefold() == team.casefold()]
    if match_id:
        signals = [signal for signal in signals if signal.match_id in {None, match_id}]
    teams = sorted({signal.team for signal in signals})
    return {
        "available": bool(signals),
        "team": team,
        "match_id": match_id,
        "teams": teams,
        "signals": _dump(signals),
        "manual_review_count": sum(signal.needs_manual_review for signal in signals),
        "issues": _issue_payload(issues),
        "fallback_note": None if signals else "No injury/news signals match this filter.",
    }


def get_manager_evidence(manager_id: str) -> dict[str, Any]:
    evidence, evidence_issues = load_normalized_tactical_evidence()
    updates, update_issues = load_manager_skill_updates()
    selected_evidence = [item for item in evidence if item.manager_id.casefold() == manager_id.casefold()]
    selected_updates = [item for item in updates if item.manager_id.casefold() == manager_id.casefold()]
    return {
        "found": bool(selected_evidence or selected_updates),
        "manager_id": manager_id,
        "manager_name": selected_evidence[0].manager_name if selected_evidence else selected_updates[0].manager_name if selected_updates else None,
        "team": selected_evidence[0].team if selected_evidence else selected_updates[0].team if selected_updates else None,
        "evidence": _dump(selected_evidence),
        "suggested_updates": _dump(selected_updates),
        "issues": _issue_payload([*evidence_issues, *update_issues]),
        "fallback_note": None if selected_evidence or selected_updates else "No normalized tactical evidence exists for this manager.",
    }


def refine_manager_skills_dry_run(manager_id: str | None = None) -> dict[str, Any]:
    evidence, evidence_issues = load_normalized_tactical_evidence()
    if manager_id:
        evidence = [row for row in evidence if row.manager_id.casefold() == manager_id.casefold()]
    updates = suggest_manager_skill_updates(evidence)
    return {
        "manager_id": manager_id,
        "evidence_records": len(evidence),
        "suggested_updates": _dump(updates),
        "issues": _issue_payload(evidence_issues),
        "note": "Dry run only. No manager skill was changed.",
    }


def apply_manager_skill_review(request: ManagerSkillApplyRequest) -> dict[str, Any]:
    if not request.apply:
        raise ValueError("Set apply=true to explicitly apply eligible human-reviewed manager updates.")
    evidence, evidence_issues = load_normalized_tactical_evidence()
    updates, update_issues = load_manager_skill_updates()
    if request.manager_id:
        evidence = [row for row in evidence if row.manager_id.casefold() == request.manager_id.casefold()]
        updates = [row for row in updates if row.manager_id.casefold() == request.manager_id.casefold()]
    result = apply_manager_skill_updates(updates, evidence, apply=True)
    return {
        "manager_id": request.manager_id,
        "applied_update_ids": result.applied_update_ids,
        "written_files": [str(path) for path in result.written_files],
        "issues": _issue_payload([*evidence_issues, *update_issues, *result.issues]),
    }


def _name_key(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    ).casefold().strip()


def _truthy(value: Any) -> bool:
    return str(value or "").casefold() in {"1", "true", "yes", "y"}


def get_lineup_delta(team: str | None = None, match_id: str | None = None) -> dict[str, Any]:
    if team:
        derived = get_lineup_delta_signal(team, match_id)
        if derived is not None:
            return {
                "available": True,
                "team": team,
                "match_id": derived.match_id,
                "projected_formation": derived.projected_formation,
                "confirmed_formation": derived.actual_formation,
                "formation_changed": derived.formation_changed,
                "projected_starters": [],
                "confirmed_starters": [],
                "unchanged_starters": derived.unchanged_starters,
                "missing_projected_starters": derived.missing_projected_starters,
                "unexpected_starters": derived.unexpected_starters,
                "impact_deltas": {
                    "lineup_strength": derived.lineup_strength_delta,
                    "pressing": derived.pressing_delta,
                    "creation": derived.creation_delta,
                    "set_piece": derived.set_piece_delta,
                    "defensive": derived.defensive_delta,
                    "goalkeeper": derived.goalkeeper_delta,
                },
                "confidence": derived.confidence,
                "data_quality": derived.data_quality,
                "issues": [],
                "fallback_note": None,
            }
    projected = safe_read_csv(PROJECTED_LINEUPS_PATH)
    confirmed = safe_read_csv(CONFIRMED_LINEUPS_PATH)
    projected_candidates = [
        row
        for row in projected.rows
        if (not team or row.get("team", "").casefold() == team.casefold())
    ]
    confirmed_candidates = [
        row
        for row in confirmed.rows
        if (not team or row.get("team", "").casefold() == team.casefold())
        and _truthy(row.get("confirmed"))
        and _truthy(row.get("starter"))
    ]
    selected_match_id = match_id
    if selected_match_id is None and confirmed_candidates:
        selected_match_id = max(
            confirmed_candidates,
            key=lambda row: (row.get("updated_at", ""), row.get("match_id", "")),
        ).get("match_id") or None
    projected_rows = [
        row
        for row in projected_candidates
        if not selected_match_id or row.get("match_id") in {"", selected_match_id}
    ]
    confirmed_rows = [
        row
        for row in confirmed_candidates
        if (selected_match_id is None and not row.get("match_id")) or row.get("match_id") == selected_match_id
    ]
    teams = sorted({row.get("team", "") for row in projected_rows if row.get("team")})
    projected_starters = [row for row in projected_rows if float(row.get("starter_probability") or 0) >= 0.5]
    projected_names = {_name_key(row.get("player", "")): row for row in projected_starters}
    confirmed_names = {_name_key(row.get("player", "")): row for row in confirmed_rows}
    unchanged = sorted(set(projected_names) & set(confirmed_names))
    missing = sorted(set(projected_names) - set(confirmed_names)) if confirmed_rows else []
    unexpected = sorted(set(confirmed_names) - set(projected_names))
    return {
        "available": bool(confirmed_rows),
        "team": team,
        "match_id": selected_match_id,
        "teams": teams,
        "projected_formation": next((row.get("formation") for row in projected_rows if row.get("formation")), None),
        "confirmed_formation": next((row.get("formation") for row in confirmed_rows if row.get("formation")), None),
        "projected_starters": projected_starters,
        "confirmed_starters": confirmed_rows,
        "unchanged_starters": [projected_names[name].get("player") for name in unchanged],
        "missing_projected_starters": [projected_names[name].get("player") for name in missing],
        "unexpected_starters": [confirmed_names[name].get("player") for name in unexpected],
        "issues": _issue_payload([*projected.issues, *confirmed.issues]),
        "fallback_note": None if confirmed_rows else "No confirmed starting XI is available yet; projected lineup remains active.",
    }


def evaluate_match(request: EvaluateMatchRequest) -> dict[str, Any]:
    completed = next((item for item in load_completed_matches() if item.match_id == request.match_id), None)
    if completed is None and request.team_a is not None:
        completed = CompletedMatch(
            match_id=request.match_id,
            team_a=request.team_a,
            team_b=request.team_b or "",
            team_a_score=request.team_a_score if request.team_a_score is not None else 0,
            team_b_score=request.team_b_score if request.team_b_score is not None else 0,
            source="api_manual_result",
        )
    if completed is None:
        raise LookupError("Match is not present in live_state.json; supply both teams and both scores to evaluate it.")
    formations = {
        team: formation
        for team, formation in (
            (completed.team_a, request.team_a_formation),
            (completed.team_b, request.team_b_formation),
        )
        if formation
    }
    result = evaluate_completed_match(completed, actual_formations=formations, use_model=request.use_model)
    issues = write_completed_evaluations(result)
    return {
        "ok": not any(issue.severity in {DataQualitySeverity.ERROR, DataQualitySeverity.CRITICAL} for issue in issues),
        "evaluation": result.model_dump(mode="json"),
        "issues": _issue_payload(issues),
    }


def get_match_evaluation(match_id: str) -> dict[str, Any]:
    models, model_issues = load_model_evaluations()
    managers, manager_issues = load_manager_skill_evaluations()
    matchups, matchup_issues = load_matchup_evaluations()
    analysts, analyst_issues = load_analyst_evaluations()
    selected_models = [item for item in models if item.match_id == match_id]
    selected_managers = [item for item in managers if item.match_id == match_id]
    selected_matchups = [item for item in matchups if item.match_id == match_id]
    selected_analysts = [item for item in analysts if item.match_id == match_id]
    return {
        "found": bool(selected_models or selected_managers or selected_matchups or selected_analysts),
        "match_id": match_id,
        "model": _dump(selected_models),
        "managers": _dump(selected_managers),
        "matchups": _dump(selected_matchups),
        "analysts": _dump(selected_analysts),
        "issues": _issue_payload([*model_issues, *manager_issues, *matchup_issues, *analyst_issues]),
    }


def get_manager_evaluation(manager_id: str) -> dict[str, Any]:
    rows, issues = load_manager_skill_evaluations()
    selected = [row for row in rows if (row.manager_id or "").casefold() == manager_id.casefold()]
    scores = [row.component_score for row in selected if row.component_score is not None]
    return {
        "found": bool(selected),
        "manager_id": manager_id,
        "evaluations": _dump(selected),
        "summary": {
            "matches": len({row.match_id for row in selected}),
            "average_component_score": round(mean(scores), 3) if scores else None,
            "status_counts": dict(Counter(row.status.value for row in selected)),
        },
        "issues": _issue_payload(issues),
    }


def get_analyst_evaluation(analyst: str) -> dict[str, Any]:
    rows, issues = load_analyst_evaluations()
    selected = [row for row in rows if row.analyst.casefold() == analyst.casefold()]
    return {
        "found": bool(selected),
        "analyst": analyst,
        "evaluations": _dump(selected),
        "summary": {
            "predictions": len(selected),
            "winner_accuracy": round(mean(row.winner_hit for row in selected), 3) if selected else None,
            "exact_score_accuracy": round(mean(row.exact_score_hit for row in selected), 3) if selected else None,
            "average_confidence": round(mean(row.confidence for row in selected), 3) if selected else None,
        },
        "issues": _issue_payload(issues),
    }


def get_model_evaluation() -> dict[str, Any]:
    rows, issues = load_model_evaluations()
    brier = [row.brier_score for row in rows]
    return {
        "found": bool(rows),
        "evaluations": _dump(rows),
        "summary": {
            "matches": len({row.match_id for row in rows}),
            "winner_accuracy": round(mean(row.winner_hit for row in rows), 3) if rows else None,
            "exact_score_accuracy": round(mean(row.exact_score_hit for row in rows), 3) if rows else None,
            "average_brier_score": round(mean(brier), 4) if brier else None,
        },
        "issues": _issue_payload(issues),
    }


def enrich_forecast_with_lineups(forecast: dict[str, Any], team_a: str, team_b: str, match_id: str | None = None) -> dict[str, Any]:
    """Attach a bounded, transparent lineup-only xG sensitivity view."""
    signal_a = get_lineup_delta_signal(team_a, match_id)
    signal_b = get_lineup_delta_signal(team_b, match_id)

    def attack_delta(own: Any, opponent: Any) -> float:
        if own is None and opponent is None:
            return 0.0
        own = own or type("Neutral", (), {
            "lineup_strength_delta": 0.0,
            "creation_delta": 0.0,
            "pressing_delta": 0.0,
            "set_piece_delta": 0.0,
        })()
        opponent = opponent or type("Neutral", (), {
            "defensive_delta": 0.0,
            "goalkeeper_delta": 0.0,
        })()
        raw = (
            own.lineup_strength_delta * 0.002
            + own.creation_delta * 0.0025
            + own.pressing_delta * 0.001
            + own.set_piece_delta * 0.001
            - opponent.defensive_delta * 0.0015
            - opponent.goalkeeper_delta * 0.001
        )
        return round(max(-0.3, min(0.3, raw)), 3)

    adjustment_a = attack_delta(signal_a, signal_b)
    adjustment_b = attack_delta(signal_b, signal_a)
    expected = forecast.get("expected_score") or {}
    expected_a = float(expected.get("team_a") or 0)
    expected_b = float(expected.get("team_b") or 0)
    return {
        **forecast,
        "lineup_adjustment": {
            "team_a_xg_delta": adjustment_a,
            "team_b_xg_delta": adjustment_b,
            "lineup_adjusted_expected_score": {
                "team_a": round(max(0.05, expected_a + adjustment_a), 3),
                "team_b": round(max(0.05, expected_b + adjustment_b), 3),
            },
            "team_a_signal": signal_a.model_dump(mode="json") if signal_a else None,
            "team_b_signal": signal_b.model_dump(mode="json") if signal_b else None,
            "note": (
                "This is a bounded sensitivity view derived from confirmed-vs-projected lineup role vectors. "
                "It does not retrain or silently overwrite the base match model."
            ),
        },
    }
