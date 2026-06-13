"""Compose forecasts, tactical hypotheses, player comparisons, RAG, and live state."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ai_forecast.player_intelligence import build_player_matchup_intelligence
from app.intelligence import get_intelligence_index, optional_llm_answer
from app.tactics.tactical_brief import build_tactical_brief


ROOT = Path(__file__).resolve().parents[2]
FIXTURES_PATH = ROOT / "data" / "fixtures.csv"


def _fixtures() -> list[dict[str, str]]:
    if not FIXTURES_PATH.exists():
        return []
    with FIXTURES_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _completed_key(row: dict[str, Any]) -> frozenset[str]:
    return frozenset((str(row.get("team_a", "")), str(row.get("team_b", ""))))


def live_match_board(live_state: dict[str, Any], limit: int = 12) -> dict[str, Any]:
    completed = live_state.get("completed_matches", [])
    completed_by_pair = {_completed_key(row): row for row in completed}
    rows = []
    now = datetime.now(timezone.utc)
    for fixture in _fixtures():
        result = completed_by_pair.get(_completed_key(fixture))
        status = "completed" if result else "upcoming"
        try:
            kickoff = datetime.fromisoformat(fixture["kickoff_utc"])
            if not result and kickoff <= now:
                status = "awaiting_result"
        except (TypeError, ValueError):
            pass
        rows.append(
            {
                **fixture,
                "status": status,
                "team_a_score": result.get("team_a_score") if result else None,
                "team_b_score": result.get("team_b_score") if result else None,
                "result_updated_at": result.get("updated_at") if result else None,
            }
        )
    priority = {"awaiting_result": 0, "upcoming": 1, "completed": 2}
    ordered = sorted(rows, key=lambda row: (priority[row["status"]], row.get("kickoff_utc", "")))
    recent_completed = sorted(
        [row for row in rows if row["status"] == "completed"],
        key=lambda row: row.get("kickoff_utc", ""),
        reverse=True,
    )
    upcoming = [row for row in ordered if row["status"] != "completed"][:limit]
    return {
        "source": live_state.get("source", "manual"),
        "updated_at": live_state.get("updated_at"),
        "completed_count": len(completed),
        "awaiting_result_count": sum(row["status"] == "awaiting_result" for row in rows),
        "recent_completed": recent_completed[:limit],
        "upcoming": upcoming,
        "freshness_note": "Live results use the configured provider when available and otherwise retain the local manual state.",
    }


def _deductions(
    forecast: dict[str, Any],
    tactical: dict[str, Any],
    players: dict[str, Any],
) -> list[dict[str, Any]]:
    team_a = forecast["team_a"]["name"]
    team_b = forecast["team_b"]["name"]
    deductions = []
    for advantage in sorted(players["position_advantages"], key=lambda row: row["edge"], reverse=True)[:3]:
        favored = advantage["favored_team"]
        if not favored:
            continue
        deductions.append(
            {
                "title": f"{advantage['position']} comparison favors {favored}",
                "conclusion": (
                    f"{favored} has the stronger projected starter group in this position, led by "
                    f"{advantage['team_a_leader'] if favored == team_a else advantage['team_b_leader']}."
                ),
                "basis": f"Same-position impact-score edge: {advantage['edge']:.2f}.",
                "confidence": "medium" if advantage["edge"] >= 8 else "low",
                "data_quality": "mixed_player_stats",
                "direction": favored,
            }
        )
    for edge in tactical.get("top_matchup_edges", [])[:3]:
        deductions.append(
            {
                "title": edge["matchup_type"].replace("_", " ").title(),
                "conclusion": edge["reason"],
                "basis": f"Transparent matchup ranking score {edge['edge_score']:.3f}; not a probability.",
                "confidence": "medium" if edge["edge_score"] >= 0.15 else "low",
                "data_quality": edge["data_quality"],
                "direction": edge.get("favored_team"),
            }
        )
    for risk in players["availability_risks"][:2]:
        deductions.append(
            {
                "title": f"Availability watch: {risk['player']}",
                "conclusion": (
                    f"{risk['player']} is currently projected for {risk['expected_minutes']} minutes "
                    f"with {risk['availability_probability']:.0%} availability."
                ),
                "basis": f"Current status: {risk['availability_status']}; position percentile {risk['position_percentile']}.",
                "confidence": "medium" if risk["data_quality"] == "observed" else "low",
                "data_quality": risk["data_quality"],
                "direction": risk["team"],
            }
        )
    return deductions[:7]


def _score_reason(forecast: dict[str, Any], tactical: dict[str, Any], players: dict[str, Any]) -> str:
    a = forecast["team_a"]["name"]
    b = forecast["team_b"]["name"]
    top = forecast["scorelines"][0]
    a_scorer = players["scorer_watch"].get(a, [{}])[0]
    b_scorer = players["scorer_watch"].get(b, [{}])[0]
    return (
        f"The {top['team_a_score']}-{top['team_b_score']} mode comes from expected goals of "
        f"{forecast['expected_score']['team_a']:.2f} for {a} and {forecast['expected_score']['team_b']:.2f} for {b}. "
        f"The tactical layer's strongest edge is "
        f"{tactical['top_matchup_edges'][0]['reason'] if tactical.get('top_matchup_edges') else 'not available'}. "
        f"Leading scorer watches are {a_scorer.get('player', 'unavailable')} for {a} and "
        f"{b_scorer.get('player', 'unavailable')} for {b}."
    )


def _result_pick(forecast: dict[str, Any]) -> tuple[str, float]:
    team_a = forecast["team_a"]["name"]
    team_b = forecast["team_b"]["name"]
    probabilities = forecast.get("score_aggregate_probabilities") or forecast.get("probabilities") or {}
    choices = {
        team_a: float(probabilities.get("team_a_win", 0.0)),
        "Draw": float(probabilities.get("draw", 0.0)),
        team_b: float(probabilities.get("team_b_win", 0.0)),
    }
    return max(choices.items(), key=lambda item: item[1])


def _compact_team(team: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": team.get("name"),
        "flag": team.get("flag"),
        "flag_code": team.get("flag_code"),
        "flag_image": team.get("flag_image"),
    }


def _humanize(value: Any, fallback: str = "flexible") -> str:
    text = str(value or fallback).replace("_", " ").strip()
    for prefix in ("observed ", "derived ", "manual "):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    return text[:1].upper() + text[1:]


def _plain_tactical_rule(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip().rstrip(".")
    replacements = {
        "progress through the strongest available player-role combinations": "build through its strongest player combinations",
        "use a low press derived from the current team profile": "defend in a lower block",
        "use a high press derived from the current team profile": "press high",
        "use a selective press derived from the current team profile": "press selectively",
        "hold an aggressive line": "hold a high defensive line",
        "attack quickly after regains": "attack quickly after winning the ball",
    }
    return replacements.get(text.lower(), text)


def _edge_read(edge: dict[str, Any] | None) -> str:
    if not edge:
        return "No single tactical matchup dominates the current projection."
    matchup = str(edge.get("matchup_type", "matchup")).replace("_", " ")
    favored = edge.get("favored_team") or "neither team"
    player_a = edge.get("team_a_player")
    player_b = edge.get("team_b_player")
    if player_a and player_b:
        return f"The clearest {matchup} edge pits {player_a} against {player_b} and favors {favored}."
    return f"The clearest style clash is {matchup}, currently favoring {favored}."


def _manager_read(tactical: dict[str, Any], pick: str, team_a: str, team_b: str) -> tuple[str, str]:
    plan_a = tactical.get("manager_plan_a") or {}
    plan_b = tactical.get("manager_plan_b") or {}
    formation_a = plan_a.get("expected_formation") or "flexible shape"
    formation_b = plan_b.get("expected_formation") or "flexible shape"
    style_a = _humanize(plan_a.get("base_plan")).lower()
    style_b = _humanize(plan_b.get("base_plan")).lower()
    if pick == team_b:
        attack_team, attack_plan, attack_style, attack_formation = team_b, plan_b, style_b, formation_b
        defend_team, defend_plan, defend_style, defend_formation = team_a, plan_a, style_a, formation_a
    else:
        attack_team, attack_plan, attack_style, attack_formation = team_a, plan_a, style_a, formation_a
        defend_team, defend_plan, defend_style, defend_formation = team_b, plan_b, style_b, formation_b
    attack_rule = _plain_tactical_rule(
        (attack_plan.get("in_possession") or [None])[0],
        "build through its strongest roles",
    )
    defend_rule = _plain_tactical_rule(
        (defend_plan.get("out_of_possession") or [None])[0],
        "protect its defensive shape",
    )
    script = (
        f"{attack_team}'s {attack_style} {attack_formation} will try to {attack_rule} against "
        f"{defend_team}'s {defend_style} {defend_formation}, which is projected to {defend_rule}. "
        f"{_edge_read((tactical.get('top_matchup_edges') or [None])[0])}"
    )

    selected_plan = plan_a if pick in {team_a, "Draw"} else plan_b
    manager_name = selected_plan.get("manager_name") or f"{pick} manager"
    rules = selected_plan.get("contingent_rules") or []
    late_rule = next(
        (rule for rule in rules if rule.get("condition_code") == "leading_after_minute"),
        rules[0] if rules else None,
    )
    if late_rule:
        manager_move = (
            f"If the game follows the forecast, {manager_name}'s likely adjustment is to "
            f"{str(late_rule.get('recommendation', 'protect the current match shape')).rstrip('.')}."
        )
    else:
        manager_move = f"{manager_name} is projected to preserve the base {selected_plan.get('expected_formation') or 'shape'}."
    return script, manager_move


def _player_read(players: dict[str, Any], pick: str, team_a: str, team_b: str) -> tuple[str, str]:
    scorer_rows = [
        row
        for team in (team_a, team_b)
        for row in (players.get("scorer_watch", {}).get(team) or [])[:2]
    ]
    preferred = [row for row in scorer_rows if row.get("team") == pick] if pick != "Draw" else scorer_rows
    watch = max(preferred or scorer_rows or [{}], key=lambda row: float(row.get("score_probability", 0.0)))
    if watch.get("player"):
        player_watch = (
            f"{watch['player']} is the main scorer watch: {watch.get('score_probability', 0):.1f}% to score, "
            f"most likely in minutes {watch.get('likely_scoring_window', 'unknown')}, "
            f"with about {watch.get('expected_minutes', 0)} expected minutes."
        )
    else:
        player_watch = "No reliable individual scorer projection is available."

    risks = players.get("availability_risks") or []
    if risks:
        risk = risks[0]
        swing = (
            f"{risk['player']}'s {risk.get('availability_status', 'uncertain')} status is the biggest lineup swing; "
            f"the current projection gives them {risk.get('expected_minutes', 0)} minutes."
        )
    else:
        opposing_edges = [
            row
            for row in players.get("position_advantages", [])
            if row.get("favored_team") and row.get("favored_team") != pick
        ]
        if opposing_edges:
            edge = max(opposing_edges, key=lambda row: float(row.get("edge", 0.0)))
            leader = edge.get("team_a_leader") if edge.get("favored_team") == team_a else edge.get("team_b_leader")
            swing = (
                f"The forecast becomes fragile if {edge['favored_team']}'s {edge['position']} edge, led by {leader}, "
                "decides the match."
            )
        else:
            swing = "The forecast is most fragile if the projected formations or starting players change."
    return player_watch, swing


def _score_read(forecast: dict[str, Any], pick: str) -> tuple[str, str]:
    scoreline = (forecast.get("scorelines") or [{}])[0]
    expected = forecast.get("expected_score") or {}
    goals_a = float(expected.get("team_a", 0.0))
    goals_b = float(expected.get("team_b", 0.0))
    total = goals_a + goals_b
    margin = abs(goals_a - goals_b)
    if total < 2.15:
        character = "low-scoring"
    elif margin >= 0.8:
        character = "controlled"
    elif total < 2.85:
        character = "fine-margin"
    else:
        character = "open"
    score = f"{scoreline.get('team_a_score', '?')}-{scoreline.get('team_b_score', '?')}"
    if pick == "Draw":
        headline = f"A fine-margin {score} is the clearest path"
    else:
        headline = f"{pick} has the edge in a {character} {score}"
    why_score = (
        f"The score call is {score} because the model projects {goals_a:.2f} to {goals_b:.2f} expected goals, "
        f"which points to a {character} game rather than a runaway result."
    )
    return headline, why_score


def build_match_story(
    fixture: dict[str, Any],
    forecast: dict[str, Any],
    live_state: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact editorial explanation without changing the forecast."""
    team_a = forecast["team_a"]["name"]
    team_b = forecast["team_b"]["name"]
    scoreline = (forecast.get("scorelines") or [{}])[0]
    pick, pick_probability = _result_pick(forecast)
    model_driver = (forecast.get("model_drivers") or [{}])[0]
    scenario_driver = (forecast.get("scenario_drivers") or [{}])[0]
    confidence = forecast.get("confidence") or {}
    probabilities = forecast.get("score_aggregate_probabilities") or forecast.get("probabilities") or {}
    expected = forecast.get("expected_score") or {}
    players = build_player_matchup_intelligence(team_a, team_b, expected.get("team_a", 0.0), expected.get("team_b", 0.0))
    tactical = build_tactical_brief(
        team_a,
        team_b,
        match_id=str(fixture.get("match_id") or fixture.get("id") or "") or None,
        forecast=forecast,
    ).model_dump(mode="json")
    completed = next(
        (
            row for row in live_state.get("completed_matches", [])
            if {row.get("team_a"), row.get("team_b")} == {team_a, team_b}
        ),
        None,
    )

    headline, why_score = _score_read(forecast, pick)
    match_script, manager_move = _manager_read(tactical, pick, team_a, team_b)
    player_watch, fragile_assumption = _player_read(players, pick, team_a, team_b)
    tactical_edges = tactical.get("top_matchup_edges") or []
    counter_edge = next((edge for edge in tactical_edges if edge.get("favored_team") != pick), None)
    upset_path = _edge_read(counter_edge) if counter_edge else fragile_assumption

    strongest_edge = model_driver.get("label", "No dominant model edge")
    edge_team = model_driver.get("favored_team") or "neither side"
    context_edge = scenario_driver.get("label", "No strong situational edge")
    context_team = scenario_driver.get("favored_team") or "neither side"
    score_reason = (
        f"The score mode follows {expected.get('team_a', 0):.2f} to {expected.get('team_b', 0):.2f} expected goals. "
        f"{strongest_edge} is the strongest weighted edge and favors {edge_team}; "
        f"{context_edge.lower()} is the leading situational signal and favors {context_team}."
    )

    return {
        "match_id": str(fixture.get("match_id") or fixture.get("id") or ""),
        "stage": fixture.get("stage") or fixture.get("round") or "Match",
        "group": fixture.get("group"),
        "status": fixture.get("status", "upcoming"),
        "kickoff_local": fixture.get("kickoff_local"),
        "kickoff_utc": fixture.get("kickoff_utc"),
        "venue": fixture.get("venue"),
        "team_a": _compact_team(forecast["team_a"]),
        "team_b": _compact_team(forecast["team_b"]),
        "predicted_score": {
            "team_a": scoreline.get("team_a_score"),
            "team_b": scoreline.get("team_b_score"),
            "probability": scoreline.get("probability"),
        },
        "observed_score": (
            {"team_a": completed.get("team_a_score"), "team_b": completed.get("team_b_score")}
            if completed else None
        ),
        "pick": pick,
        "pick_probability": round(pick_probability, 1),
        "probabilities": probabilities,
        "expected_score": expected,
        "confidence": {
            "label": confidence.get("label", "Unknown"),
            "uncertainty_pct": confidence.get("uncertainty_pct"),
        },
        "headline": headline,
        "reason": match_script,
        "deduction": {
            "likely_script": match_script,
            "why_this_score": why_score,
            "decisive_clash": _edge_read(tactical_edges[0] if tactical_edges else None),
            "manager_move": manager_move,
            "player_watch": player_watch,
            "what_changes_it": fragile_assumption,
            "opponent_path": upset_path,
        },
        "managers": [
            {
                "team": team_a,
                "name": tactical.get("manager_plan_a", {}).get("manager_name"),
                "formation": tactical.get("manager_plan_a", {}).get("expected_formation"),
                "style": _humanize(tactical.get("manager_plan_a", {}).get("base_plan")),
                "data_quality": tactical.get("manager_plan_a", {}).get("data_quality"),
            },
            {
                "team": team_b,
                "name": tactical.get("manager_plan_b", {}).get("manager_name"),
                "formation": tactical.get("manager_plan_b", {}).get("expected_formation"),
                "style": _humanize(tactical.get("manager_plan_b", {}).get("base_plan")),
                "data_quality": tactical.get("manager_plan_b", {}).get("data_quality"),
            },
        ],
        "signals": [
            {
                "label": model_driver.get("label", "Model edge unavailable"),
                "favored_team": model_driver.get("favored_team"),
                "impact": model_driver.get("impact"),
                "kind": "model",
            },
            {
                "label": scenario_driver.get("label", "Context edge unavailable"),
                "favored_team": scenario_driver.get("favored_team"),
                "impact": scenario_driver.get("impact"),
                "kind": "context",
            },
        ],
        "data_quality": {
            "forecast": (forecast.get("advanced_signals") or {}).get("quality", {}),
            "tactical": tactical.get("data_quality", "unknown"),
            "player": players.get("data_quality", "unknown"),
        },
        "detail_available": True,
        "reasoning_boundary": "This story summarizes the existing forecast; it does not alter it.",
    }


def build_match_reasoning(
    team_a: str,
    team_b: str,
    forecast: dict[str, Any],
    live_state: dict[str, Any],
    *,
    match_id: str | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    expected = forecast["expected_score"]
    players = build_player_matchup_intelligence(team_a, team_b, expected["team_a"], expected["team_b"])
    tactical = build_tactical_brief(team_a, team_b, match_id=match_id, forecast=forecast).model_dump(mode="json")
    index = get_intelligence_index(ROOT)
    index.ensure_ready()
    evidence = index.retrieve(
        f"{team_a} vs {team_b} manager tactics player comparison injuries stamina scoring time World Cup",
        8,
        [team_a, team_b],
    )
    deductions = _deductions(forecast, tactical, players)
    score_reason = _score_reason(forecast, tactical, players)
    context = {
        "forecast": forecast,
        "tactical_brief": tactical,
        "player_intelligence": players,
        "deductions": deductions,
        "score_reason": score_reason,
        "live_state": live_state,
        "evidence": evidence,
    }
    llm = optional_llm_answer(
        f"Explain and critically assess the predicted score for {team_a} vs {team_b}.",
        context,
    ) if use_llm else None
    completed = next(
        (
            row for row in live_state.get("completed_matches", [])
            if {row.get("team_a"), row.get("team_b")} == {team_a, team_b}
        ),
        None,
    )
    return {
        "team_a": forecast["team_a"],
        "team_b": forecast["team_b"],
        "forecast": forecast,
        "score_reason": score_reason,
        "analysis": llm or tactical["tactical_summary"],
        "analysis_mode": "llm_assisted_rag" if llm else "deterministic_evidence_reasoning",
        "deductions": deductions,
        "players": players,
        "manager_duel": {
            team_a: tactical["manager_plan_a"],
            team_b: tactical["manager_plan_b"],
        },
        "availability_risks": tactical["availability_risks"],
        "evidence": evidence,
        "sources": tactical["sources"],
        "data_quality": tactical["data_quality"],
        "fallback_notes": tactical["fallback_notes"],
        "completed_result": completed,
        "reasoning_boundary": (
            "Reasoning explains model outputs and evidence. Derived manager baselines and estimated player rows "
            "remain lower-confidence hypotheses until observed provider data is ingested and backtested."
        ),
    }


def build_tournament_reasoning(simulation: dict[str, Any], live_state: dict[str, Any]) -> dict[str, Any]:
    odds_payload = simulation.get("odds") or {}
    odds = odds_payload.get("odds", []) if isinstance(odds_payload, dict) else []
    top = odds[:8] if isinstance(odds, list) else []
    bracket_payload = simulation.get("bracket") or {}
    knockout = bracket_payload.get("bracket", {}) if isinstance(bracket_payload, dict) else {}
    champion = knockout.get("champion") if isinstance(knockout, dict) else None
    group_payloads = bracket_payload.get("groups", {}) if isinstance(bracket_payload, dict) else {}
    match_collections = [
        *(group.get("matches", []) for group in group_payloads.values()),
        *(round_payload.get("matches", []) for round_payload in knockout.get("rounds", [])),
    ]
    for matches in match_collections:
        for match in matches:
            if match.get("reasoning_summary"):
                continue
            team_a = (match.get("team_a") or {}).get("name", "Team A")
            team_b = (match.get("team_b") or {}).get("name", "Team B")
            score_a = match.get("score_a", "?")
            score_b = match.get("score_b", "?")
            if match.get("locked"):
                summary = "Observed result locked from the live tournament state."
            elif score_a == score_b:
                summary = (
                    f"This sampled path keeps {team_a} and {team_b} level after a fine-margin score draw."
                )
            else:
                winner = match.get("winner") or (team_a if score_a > score_b else team_b)
                summary = (
                    f"This sampled path favors {winner} {score_a}-{score_b}; open the match for the modal score, "
                    "tactical edges, player risks, travel, rest, and weather."
                )
            match["reasoning_summary"] = summary
    board = live_match_board(live_state)
    return {
        "simulation": simulation,
        "champion": champion,
        "contenders": top,
        "live_board": board,
        "analysis": (
            f"The single-run champion is {champion.get('name') if isinstance(champion, dict) else champion or 'unavailable'}. "
            f"The tournament state currently contains {board['completed_count']} completed matches, and every rerun "
            "locks those results before simulating the remaining path."
        ),
        "deductions": [
            "Champion probability should be read across many simulations; the displayed bracket is one coherent path.",
            "Completed live-state results are locked before future fixtures are simulated.",
            "Fixture venue, weather, travel, rest, fatigue, fan support, availability, lineups, and live posterior signals are applied when available.",
        ],
        "reasoning_boundary": "Tournament odds are simulation frequencies, not guarantees.",
    }
