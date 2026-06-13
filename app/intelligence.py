from __future__ import annotations

import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


TEAM_ALIASES = {
    "Iran": "IR Iran",
    "South Korea": "Korea Republic",
    "United States": "USA",
    "United States of America": "USA",
    "Ivory Coast": "Cote d'Ivoire",
    "Cape Verde": "Cabo Verde",
    "Czech Republic": "Czechia",
    "Democratic Republic of the Congo": "Congo DR",
    "DR Congo": "Congo DR",
    "Turkey": "Turkiye",
}

PROFILE_FIELDS = [
    "attack",
    "midfield",
    "defense",
    "goalkeeper",
    "bench",
    "recent_form",
    "fitness",
    "chemistry",
    "manager",
    "set_piece_attack",
    "set_piece_defense",
    "penalty_strength",
    "discipline",
    "tactical_flexibility",
    "injury_resilience",
    "pressing_intensity",
    "transition_speed",
    "big_match_composure",
    "roster_value_score",
    "projected_xi_score",
    "bench_value_score",
    "squad_experience",
    "squad_balance",
    "squad_availability",
    "formation_fit",
    "lineup_continuity",
    "lineup_confidence",
    "observed_lineups_count",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def canonical_team(name: str) -> str:
    return TEAM_ALIASES.get(name, name)


def compact_text(text: str, limit: int = 520) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    if limit <= 3:
        return "." * max(limit, 0)
    return clean[: limit - 3].rstrip() + "..."


class WorldCupIntelligenceIndex:
    def __init__(self, root: Path):
        self.root = root
        self.data_dir = root / "data"
        self.documents: list[dict[str, Any]] = []
        self.teams: dict[str, dict[str, Any]] = {}
        self.venues: dict[str, dict[str, Any]] = {}
        self.groups: dict[str, str] = {}
        self.players: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.matches: list[dict[str, Any]] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix: Any = None
        self.built_at: str | None = None
        self.signature: tuple[tuple[str, float], ...] | None = None

    def source_paths(self) -> list[Path]:
        paths = [
            self.data_dir / "teams.csv",
            self.data_dir / "groups.csv",
            self.data_dir / "team_features.csv",
            self.data_dir / "team_advanced_features.csv",
            self.data_dir / "squad_features.csv",
            self.data_dir / "worldcup_squads.csv",
            self.data_dir / "lineup_observations.csv",
            self.data_dir / "player_availability.csv",
            self.data_dir / "confirmed_lineups.csv",
            self.data_dir / "derived" / "lineup_delta_signals.csv",
            self.data_dir / "derived" / "player_role_vectors.csv",
            self.data_dir / "derived" / "postmatch_model_evaluation.csv",
            self.data_dir / "normalized" / "tactical_evidence_normalized.csv",
            self.data_dir / "market_signals.csv",
            self.data_dir / "tactical_profiles.csv",
            self.data_dir / "set_piece_profiles.csv",
            self.data_dir / "goalkeeper_profiles.csv",
            self.data_dir / "referee_profiles.csv",
            self.data_dir / "weather_effects.csv",
            self.data_dir / "live_team_state.csv",
            self.data_dir / "freeze_frame_signals.csv",
            self.data_dir / "lineup_sync_status.json",
            self.data_dir / "player_candidates.csv",
            self.data_dir / "player_match_stats.csv",
            self.data_dir / "derived" / "player_role_vectors.csv",
            self.data_dir / "derived" / "player_form_signals.csv",
            self.data_dir / "derived" / "injury_risk_signals.csv",
            self.data_dir / "derived" / "match_summary_signals.csv",
            self.data_dir / "shot_events.csv",
            self.data_dir / "xg_team_zones.csv",
            self.data_dir / "penalty_kicks.csv",
            self.data_dir / "historical_matches.csv",
            self.data_dir / "venues.csv",
            self.data_dir / "live_state.json",
            self.root / "README.md",
            self.root / "PROJECT_SUMMARY.md",
        ]
        paths.extend(sorted((self.data_dir / "manager_skills").glob("*.json")))
        return paths

    def current_signature(self) -> tuple[tuple[str, float], ...]:
        return tuple(
            (str(path.relative_to(self.root)), path.stat().st_mtime if path.exists() else 0.0)
            for path in self.source_paths()
        )

    def ensure_ready(self) -> None:
        signature = self.current_signature()
        if signature != self.signature:
            self.build(signature)

    def build(self, signature: tuple[tuple[str, float], ...] | None = None) -> None:
        base_rows = {row["team"]: row for row in read_csv(self.data_dir / "teams.csv")}
        feature_rows = {row["team"]: row for row in read_csv(self.data_dir / "team_features.csv")}
        advanced_rows = {row["team"]: row for row in read_csv(self.data_dir / "team_advanced_features.csv")}
        squad_feature_rows = {row["team"]: row for row in read_csv(self.data_dir / "squad_features.csv")}
        self.groups = {row["team"]: row["group"] for row in read_csv(self.data_dir / "groups.csv")}
        self.venues = {row["venue"]: row for row in read_csv(self.data_dir / "venues.csv")}
        self.players = defaultdict(list)
        player_rows = read_csv(self.data_dir / "worldcup_squads.csv") or read_csv(self.data_dir / "player_candidates.csv")
        for row in player_rows:
            self.players[row["team"]].append(row)

        self.teams = {}
        for team, row in base_rows.items():
            self.teams[team] = {
                **row,
                **feature_rows.get(team, {}),
                **advanced_rows.get(team, {}),
                **squad_feature_rows.get(team, {}),
                "group": self.groups.get(team),
                "players": self.players.get(team, []),
            }

        self.matches = []
        for row in read_csv(self.data_dir / "historical_matches.csv"):
            try:
                score_a = int(float(row["team_a_score"]))
                score_b = int(float(row["team_b_score"]))
            except (TypeError, ValueError):
                continue
            self.matches.append(
                {
                    **row,
                    "team_a": canonical_team(row["team_a"]),
                    "team_b": canonical_team(row["team_b"]),
                    "team_a_score": score_a,
                    "team_b_score": score_b,
                }
            )

        documents: list[dict[str, Any]] = []
        for team in sorted(self.teams):
            snapshot = self.team_snapshot(team)
            profile = snapshot["profile"]
            recent = snapshot["recent"]
            projected = [player for player in snapshot["players"] if player.get("projected_starter") == "1"]
            players = ", ".join(player["player"] for player in projected[:11] or snapshot["players"][:5]) or "No squad loaded"
            field_text = ", ".join(f"{field.replace('_', ' ')} {profile.get(field, '-')}" for field in PROFILE_FIELDS)
            documents.append(
                {
                    "id": f"team:{team}",
                    "kind": "team",
                    "title": f"{team} team profile",
                    "source": "data/teams.csv + team feature files",
                    "tags": [team, profile.get("confederation", ""), f"Group {profile.get('group', '')}"],
                    "text": (
                        f"{team} is in Group {profile.get('group', '-')}, ranked {profile.get('rank', '-')}, "
                        f"from {profile.get('confederation', '-')}. Host status: {profile.get('host', '0')}. "
                        f"World Cup pedigree: {profile.get('world_cup_pedigree', '-')}. "
                        f"Recent record across {recent['matches']} matches: {recent['wins']} wins, "
                        f"{recent['draws']} draws, {recent['losses']} losses, {recent['goals_for']} scored, "
                        f"{recent['goals_against']} conceded. Projected XI: {players}. Inputs: {field_text}."
                    ),
                }
            )

        for venue, row in sorted(self.venues.items()):
            documents.append(
                {
                    "id": f"venue:{venue}",
                    "kind": "venue",
                    "title": f"{venue} venue profile",
                    "source": "data/venues.csv",
                    "tags": [venue, row["city"], row["country"]],
                    "text": (
                        f"{venue} is a World Cup host venue in {row['city']}, {row['country']}. "
                        f"Its coordinates are {row['latitude']}, {row['longitude']} and altitude is "
                        f"{row['altitude_m']} meters. Altitude and live weather can affect fatigue and scoring."
                    ),
                }
            )

        live_path = self.data_dir / "live_state.json"
        if live_path.exists():
            live_state = json.loads(live_path.read_text(encoding="utf-8"))
            documents.append(
                {
                    "id": "live:state",
                    "kind": "live",
                    "title": "Current tournament live state",
                    "source": "data/live_state.json",
                    "tags": ["live", "eliminated", "completed matches"],
                    "text": (
                        f"Live source is {live_state.get('source', 'manual')}. "
                        f"Eliminated teams: {', '.join(live_state.get('eliminated_teams', [])) or 'none'}. "
                        f"Completed matches stored: {len(live_state.get('completed_matches', []))}."
                    ),
                }
            )

        xg_rows = read_csv(self.data_dir / "xg_team_zones.csv")
        if xg_rows:
            top_zones = sorted(xg_rows, key=lambda row: float(row.get("avg_xg") or 0), reverse=True)[:8]
            documents.append(
                {
                    "id": "model:xg_zones",
                    "kind": "model",
                    "title": "Shot-level xG dangerous positions",
                    "source": "data/xg_team_zones.csv",
                    "tags": ["xg", "shot quality", "dangerous positions"],
                    "text": "Top xG zones: "
                    + "; ".join(
                        f"{row['team']} {row['x_zone']} {row['y_zone']} avg xG {row['avg_xg']} "
                        f"with {row['predicted_goals']} predicted goals and {row['actual_goals']} actual goals"
                        for row in top_zones
                    ),
                }
            )

        penalty_rows = read_csv(self.data_dir / "penalty_kicks.csv")
        if penalty_rows:
            documents.append(
                {
                    "id": "model:penalties",
                    "kind": "model",
                    "title": "Penalty shootout kick-level model data",
                    "source": "data/penalty_kicks.csv",
                    "tags": ["penalties", "shootout", "keeper dive", "shot placement"],
                    "text": (
                        f"Penalty model data contains {len(penalty_rows)} kicks with kicker foot, "
                        "shot placement, keeper dive, outcome, pressure score, score state, and knockout round. "
                        "The dashboard predicts placement, score probability, save probability, and keeper dive read."
                    ),
                }
            )

        manager_dir = self.data_dir / "manager_skills"
        for path in sorted(manager_dir.glob("*.json")):
            try:
                skill = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            identity = skill.get("tactical_identity") or {}
            rules = skill.get("decision_rules") or []
            substitutions = skill.get("substitution_patterns") or []
            documents.append(
                {
                    "id": f"manager:{skill.get('manager_id', path.stem)}",
                    "kind": "manager",
                    "title": f"{skill.get('manager_name', path.stem)} tactical skill",
                    "source": str(path.relative_to(self.root)),
                    "tags": [skill.get("team", ""), skill.get("manager_name", ""), "manager", "tactics"],
                    "text": (
                        f"{skill.get('manager_name')} manages {skill.get('team')}. "
                        f"Evidence status is {skill.get('status')} and version is {skill.get('version')}. "
                        f"Primary style: {identity.get('primary_style')}; preferred formations: "
                        f"{', '.join(identity.get('preferred_formations') or [])}; build up: {identity.get('build_up')}; "
                        f"defensive shape: {identity.get('defensive_shape')}; pressing: {identity.get('pressing')}; "
                        f"transition: {identity.get('transition')}; set pieces: {identity.get('set_pieces')}. "
                        f"Decision rules: {'; '.join(rule.get('recommendation', '') for rule in rules)}. "
                        f"Substitution hypotheses: {'; '.join(item.get('likely_sub_type', '') + ' ' + item.get('minute_window', '') for item in substitutions)}. "
                        f"Boundaries: {'; '.join(skill.get('evidence_notes') or [])}"
                    ),
                }
            )

        player_stat_rows = read_csv(self.data_dir / "player_match_stats.csv")
        players_by_team: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in player_stat_rows:
            players_by_team[row.get("team", "")].append(row)
        for team, rows in sorted(players_by_team.items()):
            if not team:
                continue
            leaders = sorted(
                rows,
                key=lambda row: (
                    float(row.get("xg_per90") or 0) * 5
                    + float(row.get("xa_per90") or 0) * 4
                    + float(row.get("key_passes_per90") or 0)
                    + float(row.get("progressive_passes_per90") or 0) * 0.2
                    + float(row.get("tackles_interceptions_per90") or 0) * 0.4
                ),
                reverse=True,
            )[:10]
            documents.append(
                {
                    "id": f"players:{team}",
                    "kind": "players",
                    "title": f"{team} player comparison and scoring profile",
                    "source": "data/player_match_stats.csv",
                    "tags": [team, "players", "scorers", "stamina", "position comparison"],
                    "text": (
                        f"{team} player evidence quality is "
                        f"{'observed or mixed' if any('estimated' not in row.get('source', '') for row in rows) else 'estimated fallback'}. "
                        + "; ".join(
                            f"{row.get('player')} {row.get('detailed_position')}, xG/90 {row.get('xg_per90')}, "
                            f"xA/90 {row.get('xa_per90')}, pass completion {row.get('pass_completion_pct')}%, "
                            f"pressure success {row.get('pressure_success_pct')}%, likely scoring window {row.get('likely_scoring_window')}"
                            for row in leaders
                        )
                    ),
                }
            )

        injury_rows = read_csv(self.data_dir / "derived" / "injury_risk_signals.csv")
        injury_by_team: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in injury_rows:
            injury_by_team[row.get("team", "")].append(row)
        for team, rows in sorted(injury_by_team.items()):
            if not team:
                continue
            documents.append(
                {
                    "id": f"injuries:{team}",
                    "kind": "injury",
                    "title": f"{team} current availability reports",
                    "source": "data/derived/injury_risk_signals.csv",
                    "tags": [team, "injury", "availability", "minutes"],
                    "text": "; ".join(
                        f"{row.get('player')} status {row.get('status')}, availability {row.get('availability_probability')}, "
                        f"expected minutes {row.get('expected_minutes')}, risk {row.get('risk_score')}, "
                        f"manual review {row.get('needs_manual_review')}"
                        for row in rows
                    ),
                }
            )

        for path, kind, tags in (
            (self.data_dir / "derived" / "lineup_delta_signals.csv", "lineup_delta", ["lineup", "formation", "confirmed"]),
            (self.data_dir / "derived" / "postmatch_model_evaluation.csv", "postmatch_evaluation", ["evaluation", "calibration", "accuracy"]),
            (self.data_dir / "normalized" / "tactical_evidence_normalized.csv", "manager_evidence", ["manager", "tactics", "evidence"]),
            (self.data_dir / "derived" / "player_role_vectors.csv", "player_stats", ["player", "form", "role", "comparison"]),
        ):
            for index, row in enumerate(read_csv(path)):
                team = row.get("team", "")
                documents.append(
                    {
                        "id": f"{kind}:{index}:{team or row.get('match_id', '')}",
                        "kind": kind,
                        "title": f"{kind.replace('_', ' ').title()} {team or row.get('match_id', '')}".strip(),
                        "source": str(path.relative_to(self.root)),
                        "tags": [team, *tags],
                        "text": "; ".join(f"{key} {value}" for key, value in row.items() if value),
                    }
                )

        for path in (self.root / "README.md", self.root / "PROJECT_SUMMARY.md"):
            documents.extend(self.markdown_documents(path))

        self.documents = documents
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=12000)
        self.matrix = self.vectorizer.fit_transform([document["text"] for document in documents])
        self.built_at = datetime.now(timezone.utc).isoformat()
        self.signature = signature or self.current_signature()

    def markdown_documents(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        sections: list[dict[str, Any]] = []
        title = path.name
        lines: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                if lines:
                    sections.append(self.markdown_section(path, title, lines))
                title = line.lstrip("#").strip()
                lines = []
            else:
                lines.append(line)
        if lines:
            sections.append(self.markdown_section(path, title, lines))
        return [section for section in sections if len(section["text"]) >= 45]

    def markdown_section(self, path: Path, title: str, lines: list[str]) -> dict[str, Any]:
        return {
            "id": f"doc:{path.name}:{title}",
            "kind": "documentation",
            "title": title,
            "source": path.name,
            "tags": ["model", "methodology", "project"],
            "text": compact_text(" ".join(lines), 900),
        }

    def identify_entities(self, question: str) -> dict[str, list[str]]:
        lowered = question.lower()
        venue_hits = []
        for venue in sorted(self.venues, key=len, reverse=True):
            match = re.search(rf"(?<!\w){re.escape(venue.lower())}(?!\w)", lowered)
            if match:
                venue_hits.append((match.start(), venue))
        venues = [venue for _, venue in sorted(venue_hits)]

        team_hits = []
        for team in sorted(self.teams, key=len, reverse=True):
            match = re.search(rf"(?<!\w){re.escape(team.lower())}(?!\w)", lowered)
            if match:
                team_hits.append((match.start(), team))
        for alias, team in TEAM_ALIASES.items():
            match = re.search(rf"(?<!\w){re.escape(alias.lower())}(?!\w)", lowered)
            if match:
                team_hits.append((match.start(), team))
        teams = []
        for _, team in sorted(team_hits):
            if team not in teams:
                teams.append(team)
        for venue in venues:
            teams = [
                team
                for team in teams
                if not (
                    team.lower() in venue.lower()
                    and lowered.count(team.lower()) == lowered.count(venue.lower())
                )
            ]
        return {"teams": teams[:4], "venues": venues[:3]}

    def route(self, question: str, entities: dict[str, list[str]]) -> list[str]:
        lowered = question.lower()
        tools = ["retrieve_knowledge"]
        if entities["teams"]:
            tools.append("team_profile")
        if len(entities["teams"]) >= 2:
            tools.extend(["head_to_head", "match_forecast"])
        if entities["venues"] or any(word in lowered for word in ("weather", "rain", "heat", "altitude", "venue")):
            tools.append("venue_weather")
        if any(word in lowered for word in ("live", "eliminated", "qualified", "completed", "latest", "update")):
            tools.append("live_state")
        if any(
            phrase in lowered
            for phrase in ("underrated", "overrated", "dark horse", "sleeper", "favorite", "favourite", "strongest", "best team")
        ):
            tools.append("team_shortlist")
        if any(word in lowered for word in ("player", "form", "role", "starter", "scorer", "passing", "shooting")):
            tools.append("player_stats")
        if any(word in lowered for word in ("injury", "injured", "availability", "suspended", "fitness")):
            tools.append("injury_news")
        if any(word in lowered for word in ("manager", "coach", "tactic", "formation", "pressing")):
            tools.append("manager_evidence")
        if any(word in lowered for word in ("lineup", "starting xi", "confirmed xi", "unexpected starter")):
            tools.append("lineup_delta")
        if any(word in lowered for word in ("evaluation", "accuracy", "brier", "calibration", "what was wrong")):
            tools.append("postmatch_evaluation")
        return list(dict.fromkeys(tools))

    def retrieve(self, question: str, top_k: int = 6, preferred_tags: list[str] | None = None) -> list[dict[str, Any]]:
        self.ensure_ready()
        if self.vectorizer is None or self.matrix is None:
            return []
        query = self.vectorizer.transform([question])
        scores = cosine_similarity(query, self.matrix)[0]
        preferred = {tag.lower() for tag in (preferred_tags or [])}
        ranked = []
        for index, score in enumerate(scores):
            document = self.documents[index]
            boost = 0.08 if preferred.intersection(tag.lower() for tag in document["tags"]) else 0.0
            ranked.append((float(score) + boost, document))
        return [
            {
                "id": document["id"],
                "kind": document["kind"],
                "title": document["title"],
                "source": document["source"],
                "excerpt": compact_text(document["text"]),
                "relevance": round(score, 3),
            }
            for score, document in sorted(ranked, key=lambda item: item[0], reverse=True)[:top_k]
            if score > 0
        ]

    def team_snapshot(self, team: str) -> dict[str, Any]:
        profile = self.teams.get(team, {})
        recent_matches = [
            match for match in self.matches if team in {match["team_a"], match["team_b"]}
        ][-10:]
        wins = draws = losses = goals_for = goals_against = 0
        for match in recent_matches:
            is_a = match["team_a"] == team
            scored = match["team_a_score"] if is_a else match["team_b_score"]
            conceded = match["team_b_score"] if is_a else match["team_a_score"]
            goals_for += scored
            goals_against += conceded
            if scored > conceded:
                wins += 1
            elif scored == conceded:
                draws += 1
            else:
                losses += 1
        return {
            "team": team,
            "profile": {key: value for key, value in profile.items() if key != "players"},
            "players": profile.get("players", []),
            "recent": {
                "matches": len(recent_matches),
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "goals_for": goals_for,
                "goals_against": goals_against,
                "latest_date": recent_matches[-1]["date"] if recent_matches else None,
            },
        }

    def head_to_head(self, team_a: str, team_b: str) -> dict[str, Any]:
        matches = [
            match
            for match in self.matches
            if {match["team_a"], match["team_b"]} == {team_a, team_b}
        ]
        wins_a = wins_b = draws = 0
        for match in matches:
            score_a = match["team_a_score"] if match["team_a"] == team_a else match["team_b_score"]
            score_b = match["team_b_score"] if match["team_a"] == team_a else match["team_a_score"]
            if score_a > score_b:
                wins_a += 1
            elif score_b > score_a:
                wins_b += 1
            else:
                draws += 1
        recent = []
        for match in matches[-5:]:
            if match["team_a"] == team_a:
                score_a, score_b = match["team_a_score"], match["team_b_score"]
            else:
                score_a, score_b = match["team_b_score"], match["team_a_score"]
            recent.append(
                {
                    "date": match["date"],
                    "team_a_score": score_a,
                    "team_b_score": score_b,
                    "tournament": match.get("tournament"),
                }
            )
        return {
            "team_a": team_a,
            "team_b": team_b,
            "matches": len(matches),
            "team_a_wins": wins_a,
            "draws": draws,
            "team_b_wins": wins_b,
            "recent": recent,
        }

    def team_shortlist(self, question: str, limit: int = 8) -> dict[str, Any]:
        lowered = question.lower()
        if "overrated" in lowered:
            mode = "overrated"
        elif any(word in lowered for word in ("favorite", "favourite", "strongest", "best team")):
            mode = "favorites"
        elif any(word in lowered for word in ("dark horse", "sleeper")):
            mode = "dark_horses"
        else:
            mode = "underrated"

        rows = []
        for team, profile in self.teams.items():
            quality = (
                float(profile.get("attack", 70)) * 0.22
                + float(profile.get("midfield", 70)) * 0.19
                + float(profile.get("defense", 70)) * 0.17
                + float(profile.get("goalkeeper", 70)) * 0.10
                + float(profile.get("bench", 70)) * 0.09
                + float(profile.get("recent_form", 70)) * 0.08
                + float(profile.get("fitness", 70)) * 0.04
                + float(profile.get("tactical_flexibility", 70)) * 0.05
                + float(profile.get("transition_speed", 70)) * 0.03
                + float(profile.get("big_match_composure", 70)) * 0.03
            )
            rows.append(
                {
                    "team": team,
                    "fifa_rank": int(profile.get("rank", 99)),
                    "quality_score": round(quality, 2),
                    "group": profile.get("group"),
                }
            )
        for index, row in enumerate(sorted(rows, key=lambda item: item["quality_score"], reverse=True), start=1):
            row["model_quality_rank"] = index
            row["rank_gap"] = row["fifa_rank"] - index

        if mode == "favorites":
            selected = sorted(rows, key=lambda item: item["quality_score"], reverse=True)
        elif mode == "overrated":
            selected = sorted(rows, key=lambda item: item["rank_gap"])
        elif mode == "dark_horses":
            selected = sorted(
                (row for row in rows if row["fifa_rank"] > 10),
                key=lambda item: (item["quality_score"], item["rank_gap"]),
                reverse=True,
            )
        else:
            selected = sorted(
                (row for row in rows if row["quality_score"] >= 76 and row["rank_gap"] > 0),
                key=lambda item: (item["rank_gap"], item["quality_score"]),
                reverse=True,
            )
        return {"mode": mode, "teams": selected[:limit]}

    def status(self) -> dict[str, Any]:
        self.ensure_ready()
        return {
            "ready": bool(self.documents),
            "retriever": "local-tfidf-bigram",
            "documents": len(self.documents),
            "teams": len(self.teams),
            "venues": len(self.venues),
            "historical_matches": len(self.matches),
            "built_at": self.built_at,
            "llm": llm_status(),
        }


def local_answer(
    question: str,
    snapshots: list[dict[str, Any]],
    head_to_head: dict[str, Any] | None,
    forecast: dict[str, Any] | None,
    live_state: dict[str, Any] | None,
    venue_weather: dict[str, Any] | None,
    shortlist: dict[str, Any] | None,
    evidence: list[dict[str, Any]],
) -> str:
    paragraphs = []
    if forecast:
        team_a = forecast["team_a"]["name"]
        team_b = forecast["team_b"]["name"]
        aggregate = forecast["score_aggregate_probabilities"]
        outcomes = [(team_a, aggregate["team_a_win"]), ("draw", aggregate["draw"]), (team_b, aggregate["team_b_win"])]
        favorite, probability = max(outcomes, key=lambda item: item[1])
        expected = forecast["expected_score"]
        likely = forecast["score_insights"]["most_likely_score"]
        paragraphs.append(
            f"The model leans {favorite} at {probability:.1f}%. Expected goals are {team_a} {expected['team_a']:.2f} "
            f"to {expected['team_b']:.2f} {team_b}, with {likely['team_a_score']}-{likely['team_b_score']} the most "
            f"likely exact score. Confidence is {forecast['confidence']['label'].lower()} because the outcome margin "
            f"is {forecast['confidence']['margin_pct']:.1f} percentage points."
        )
        drivers = forecast.get("shap_drivers", {}).get("drivers") or forecast.get("model_drivers", [])
        if drivers:
            driver_text = ", ".join(f"{driver['label']} toward {driver['favored_team']}" for driver in drivers[:3])
            paragraphs.append(f"The strongest model signals are {driver_text}.")

    if head_to_head and head_to_head["matches"]:
        paragraphs.append(
            f"The historical file contains {head_to_head['matches']} meetings: {head_to_head['team_a']} "
            f"{head_to_head['team_a_wins']} wins, {head_to_head['draws']} draws, and "
            f"{head_to_head['team_b']} {head_to_head['team_b_wins']} wins."
        )

    if not forecast and snapshots:
        for snapshot in snapshots[:2]:
            profile = snapshot["profile"]
            recent = snapshot["recent"]
            paragraphs.append(
                f"{snapshot['team']} is ranked {profile.get('rank', '-')}, sits in Group {profile.get('group', '-')}, "
                f"and has a recent loaded-data record of {recent['wins']}-{recent['draws']}-{recent['losses']}."
            )

    if live_state is not None:
        eliminated = live_state.get("eliminated_teams", [])
        paragraphs.append(
            f"The live state source is {live_state.get('source', 'manual')}; "
            f"{len(eliminated)} teams are marked eliminated and {len(live_state.get('completed_matches', []))} "
            f"completed matches are locked."
        )

    if venue_weather is not None:
        venue = venue_weather.get("venue") or {}
        current = venue_weather.get("current") or {}
        weather = venue_weather.get("weather", "normal")
        temperature = current.get("temperature_2m")
        wind = current.get("wind_speed_10m")
        paragraphs.append(
            f"{venue.get('venue', 'The selected venue')} is currently classified as {weather} for the model. "
            f"Temperature is {temperature if temperature is not None else 'unavailable'} C and wind is "
            f"{wind if wind is not None else 'unavailable'} km/h; the prediction engine falls back to venue altitude "
            f"when live weather cannot be reached."
        )

    if shortlist is not None:
        leaders = ", ".join(
            f"{row['team']} (quality #{row['model_quality_rank']}, FIFA #{row['fifa_rank']})"
            for row in shortlist["teams"][:5]
        )
        paragraphs.append(
            f"The {shortlist['mode'].replace('_', ' ')} screen highlights {leaders}. "
            "This screen compares the loaded squad-feature composite with FIFA rank; it is a scouting signal, not a tournament probability."
        )

    if not paragraphs and evidence:
        paragraphs.append(f"Based on the local knowledge index: {evidence[0]['excerpt']} [1]")
        if len(evidence) > 1:
            paragraphs.append(f"Additional relevant context: {evidence[1]['excerpt']} [2]")

    if evidence:
        sources = ", ".join(f"[{index + 1}] {item['title']}" for index, item in enumerate(evidence[:3]))
        paragraphs.append(f"Most relevant supporting context: {sources}.")

    if not paragraphs:
        paragraphs.append(
            "I could not route that question to a specific team or model tool yet. Ask about a matchup, team profile, "
            "venue, weather, live state, or how the prediction model works."
        )
    return "\n\n".join(paragraphs)


def llm_status() -> dict[str, Any]:
    model = os.getenv("WORLD_CUP_AI_MODEL")
    base_url = os.getenv("WORLD_CUP_AI_BASE_URL")
    return {
        "configured": bool(model and base_url),
        "model": model,
        "base_url": base_url,
    }


def optional_llm_answer(question: str, context: dict[str, Any]) -> str | None:
    model = os.getenv("WORLD_CUP_AI_MODEL")
    base_url = os.getenv("WORLD_CUP_AI_BASE_URL")
    if not model or not base_url:
        return None
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("WORLD_CUP_AI_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a cautious football intelligence analyst. Use only the supplied tools and evidence. "
                    "Separate model forecasts from historical facts, cite evidence as [1], [2], and never imply certainty."
                ),
            },
            {
                "role": "user",
                "content": f"Question: {question}\n\nContext:\n{json.dumps(context, ensure_ascii=True)}",
            },
        ],
    }
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=25)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
        return None


_INDEXES: dict[str, WorldCupIntelligenceIndex] = {}


def get_intelligence_index(root: Path) -> WorldCupIntelligenceIndex:
    key = str(root.resolve())
    if key not in _INDEXES:
        _INDEXES[key] = WorldCupIntelligenceIndex(root)
    return _INDEXES[key]
