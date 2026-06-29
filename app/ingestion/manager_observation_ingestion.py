"""Derive manager and formation observations from completed matches."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ingestion.event_data_ingestion import MATCH_EVENTS_NORMALIZED_PATH, MATCH_SUMMARY_SIGNALS_PATH
from app.ingestion.lineup_ingestion import ACTUAL_LINEUPS_PATH
from app.ingestion.normalizers import safe_read_csv, safe_write_csv


ROOT = Path(__file__).resolve().parents[2]
OBSERVED_MATCHES_PATH = ROOT / "data" / "observed_matches.csv"
MANAGERS_PATH = ROOT / "data" / "managers.csv"
MANAGER_MATCH_OBSERVATIONS_PATH = ROOT / "data" / "derived" / "manager_match_observations.csv"
FORMATION_PREDICTION_SIGNALS_PATH = ROOT / "data" / "derived" / "formation_prediction_signals.csv"

MANAGER_OBSERVATION_FIELDS = [
    "match_id",
    "team",
    "opponent",
    "manager_id",
    "manager_name",
    "stage",
    "match_date",
    "actual_formation",
    "goals_for",
    "goals_against",
    "xg_for",
    "xg_against",
    "shots",
    "field_tilt",
    "box_entries",
    "set_piece_xg",
    "counterattack_xg",
    "pressing_proxy",
    "substitutions",
    "data_quality",
    "source",
    "updated_at",
]

FORMATION_SIGNAL_FIELDS = [
    "team",
    "manager_id",
    "manager_name",
    "matches_observed",
    "confirmed_lineup_matches",
    "last_confirmed_formation",
    "most_common_formation",
    "formation_confidence",
    "avg_pressing_proxy",
    "avg_counterattack_xg",
    "avg_set_piece_xg",
    "avg_field_tilt",
    "source",
    "data_quality",
    "updated_at",
]


def _float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) or default)
    except (TypeError, ValueError):
        return default


def _read_rows(path: Path, required: set[str] | None = None) -> list[dict[str, str]]:
    return safe_read_csv(path, required or set()).rows


def _manager_by_team(path: Path = MANAGERS_PATH) -> dict[str, dict[str, str]]:
    return {row.get("team", ""): row for row in _read_rows(path, {"team", "manager_id", "manager_name"}) if row.get("team")}


def _summary_by_match_team(path: Path = MATCH_SUMMARY_SIGNALS_PATH) -> dict[tuple[str, str], dict[str, str]]:
    return {
        (row.get("match_id", ""), row.get("team", "").casefold()): row
        for row in _read_rows(path, {"match_id", "team"})
        if row.get("match_id") and row.get("team")
    }


def _formation_by_match_team(path: Path = ACTUAL_LINEUPS_PATH) -> dict[tuple[str, str], str]:
    formations: dict[tuple[str, str], str] = {}
    for row in _read_rows(path, {"match_id", "team"}):
        match_id = row.get("match_id", "")
        team = row.get("team", "")
        formation = row.get("formation", "")
        if match_id and team and formation:
            formations[(match_id, team.casefold())] = formation
    return formations


def _substitutions_by_match_team(path: Path = MATCH_EVENTS_NORMALIZED_PATH) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for row in _read_rows(path, {"match_id", "team", "event_type"}):
        if row.get("event_type") == "substitution" and row.get("match_id") and row.get("team"):
            counts[(row["match_id"], row["team"].casefold())] += 1
    return counts


def build_manager_match_observations(
    *,
    observed_matches_path: Path = OBSERVED_MATCHES_PATH,
    managers_path: Path = MANAGERS_PATH,
    summaries_path: Path = MATCH_SUMMARY_SIGNALS_PATH,
    lineups_path: Path = ACTUAL_LINEUPS_PATH,
    events_path: Path = MATCH_EVENTS_NORMALIZED_PATH,
) -> list[dict[str, Any]]:
    managers = _manager_by_team(managers_path)
    summaries = _summary_by_match_team(summaries_path)
    formations = _formation_by_match_team(lineups_path)
    substitutions = _substitutions_by_match_team(events_path)
    updated_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for match in _read_rows(observed_matches_path, {"match_id", "team_a", "team_b"}):
        match_id = match.get("match_id", "")
        if not match_id:
            continue
        pair = (
            (match.get("team_a", ""), match.get("team_b", ""), match.get("team_a_score", ""), match.get("team_b_score", "")),
            (match.get("team_b", ""), match.get("team_a", ""), match.get("team_b_score", ""), match.get("team_a_score", "")),
        )
        for team, opponent, goals_for, goals_against in pair:
            if not team or not opponent:
                continue
            manager = managers.get(team, {})
            summary = summaries.get((match_id, team.casefold()), {})
            opponent_summary = summaries.get((match_id, opponent.casefold()), {})
            formation = formations.get((match_id, team.casefold()), "")
            has_events = bool(summary)
            has_formation = bool(formation)
            if has_events and has_formation:
                quality = "observed_events_and_confirmed_lineup"
            elif has_events:
                quality = "observed_events_only"
            elif has_formation:
                quality = "confirmed_lineup_only"
            else:
                quality = "score_only"
            rows.append(
                {
                    "match_id": match_id,
                    "team": team,
                    "opponent": opponent,
                    "manager_id": manager.get("manager_id", ""),
                    "manager_name": manager.get("manager_name", ""),
                    "stage": match.get("stage", ""),
                    "match_date": (match.get("kickoff_utc", "") or "")[:10],
                    "actual_formation": formation,
                    "goals_for": goals_for,
                    "goals_against": goals_against,
                    "xg_for": summary.get("xg", ""),
                    "xg_against": opponent_summary.get("xg", ""),
                    "shots": summary.get("shots", ""),
                    "field_tilt": summary.get("field_tilt", ""),
                    "box_entries": summary.get("box_entries", ""),
                    "set_piece_xg": summary.get("set_piece_xg", ""),
                    "counterattack_xg": summary.get("counterattack_xg", ""),
                    "pressing_proxy": summary.get("pressing_proxy", ""),
                    "substitutions": substitutions.get((match_id, team.casefold()), 0),
                    "data_quality": quality,
                    "source": "observed_matches + actual_lineups + match_summary_signals",
                    "updated_at": updated_at,
                }
            )
    return rows


def build_formation_prediction_signals(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_team: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        if row.get("team"):
            by_team[str(row["team"])].append(row)
    updated_at = datetime.now(timezone.utc).isoformat()
    signals = []
    for team, rows in sorted(by_team.items()):
        rows = sorted(rows, key=lambda row: (row.get("match_date", ""), row.get("match_id", "")))
        formations = [str(row.get("actual_formation") or "") for row in rows if row.get("actual_formation")]
        formation_counts = Counter(formations)
        most_common, common_count = formation_counts.most_common(1)[0] if formation_counts else ("", 0)
        confirmed_count = len(formations)
        last_formation = formations[-1] if formations else ""
        confidence = 0.0
        if rows:
            confidence = min(0.92, (confirmed_count / max(len(rows), 1) * 0.58) + (common_count / max(confirmed_count, 1) * 0.34))
        with_events = [row for row in rows if row.get("data_quality") in {"observed_events_only", "observed_events_and_confirmed_lineup"}]

        def avg(field: str) -> float:
            values = [_float(row, field) for row in with_events if row.get(field) not in {"", None}]
            return sum(values) / len(values) if values else 0.0

        manager = next((row for row in reversed(rows) if row.get("manager_id")), {})
        data_quality = "observed_lineup_trend" if confirmed_count else "score_or_event_only"
        signals.append(
            {
                "team": team,
                "manager_id": manager.get("manager_id", ""),
                "manager_name": manager.get("manager_name", ""),
                "matches_observed": len(rows),
                "confirmed_lineup_matches": confirmed_count,
                "last_confirmed_formation": last_formation,
                "most_common_formation": most_common,
                "formation_confidence": round(confidence, 3),
                "avg_pressing_proxy": round(avg("pressing_proxy"), 3),
                "avg_counterattack_xg": round(avg("counterattack_xg"), 3),
                "avg_set_piece_xg": round(avg("set_piece_xg"), 3),
                "avg_field_tilt": round(avg("field_tilt"), 3),
                "source": "manager_match_observations.csv",
                "data_quality": data_quality,
                "updated_at": updated_at,
            }
        )
    return signals


def write_manager_match_observations(
    rows: list[dict[str, Any]],
    path: Path = MANAGER_MATCH_OBSERVATIONS_PATH,
) -> None:
    result = safe_write_csv(path, rows, MANAGER_OBSERVATION_FIELDS)
    if not result.ok:
        raise ValueError("; ".join(issue.problem for issue in result.issues))


def write_formation_prediction_signals(
    rows: list[dict[str, Any]],
    path: Path = FORMATION_PREDICTION_SIGNALS_PATH,
) -> None:
    result = safe_write_csv(path, rows, FORMATION_SIGNAL_FIELDS)
    if not result.ok:
        raise ValueError("; ".join(issue.problem for issue in result.issues))


def rebuild_manager_observation_outputs() -> tuple[int, int]:
    observations = build_manager_match_observations()
    signals = build_formation_prediction_signals(observations)
    write_manager_match_observations(observations)
    write_formation_prediction_signals(signals)
    return len(observations), len(signals)


def load_formation_prediction_signals(
    path: Path = FORMATION_PREDICTION_SIGNALS_PATH,
) -> dict[str, dict[str, str]]:
    return {row.get("team", ""): row for row in _read_rows(path, {"team"}) if row.get("team")}


__all__ = [
    "FORMATION_PREDICTION_SIGNALS_PATH",
    "MANAGER_MATCH_OBSERVATIONS_PATH",
    "build_formation_prediction_signals",
    "build_manager_match_observations",
    "load_formation_prediction_signals",
    "rebuild_manager_observation_outputs",
    "write_formation_prediction_signals",
    "write_manager_match_observations",
]
