# WorldCup2026 Future Roadmap: Real Stats, News/Injury, Manager Refinement, Live Lineups, and Post-Match Evaluation

## Purpose

This document extends the WorldCup2026 tactical-agent roadmap after the MVP.

The MVP adds:

1. Manager skills.
2. Player profiles.
3. Matchup engine.
4. Tactical brief.
5. Human analyst prediction logs.

This future roadmap upgrades the system from a manually curated tactical demo into a living tournament intelligence system that can ingest real player statistics, injury/news updates, tactical writing, actual lineups, and post-match event data.

Do not rewrite the existing World Cup predictor. The current repo already has a working simulator, match predictor, advanced signal layer, lineup status, live-state refresh, odds snapshot, Intelligence Desk, and web app. These future features should plug into the existing architecture.

---

# 0. Core Future Architecture

Add a unified ingestion/evaluation layer:

```text id="2440ca"
app/
  ingestion/
    __init__.py
    schemas.py
    source_registry.py
    normalizers.py
    provenance.py
    player_stats_ingestion.py
    injury_news_ingestion.py
    tactical_article_ingestion.py
    lineup_ingestion.py
    event_data_ingestion.py

  evaluation/
    __init__.py
    schemas.py
    postmatch_evaluator.py
    manager_skill_evaluator.py
    matchup_evaluator.py
    analyst_evaluator.py

data/
  raw/
    player_stats/
    injury_news/
    tactical_articles/
    lineups/
    event_data/

  normalized/
    player_match_stats_normalized.csv
    player_season_stats_normalized.csv
    injury_news_normalized.csv
    tactical_evidence_normalized.csv
    actual_lineups_normalized.csv
    match_events_normalized.csv

  derived/
    player_role_vectors.csv
    player_form_signals.csv
    injury_risk_signals.csv
    manager_skill_updates.csv
    matchup_evaluation_results.csv
    postmatch_model_evaluation.csv

  provenance/
    source_registry.csv
    ingestion_runs.csv
    data_quality_report.csv

scripts/
  ingest_player_stats.py
  ingest_injury_news.py
  ingest_tactical_articles.py
  ingest_lineups.py
  ingest_event_data.py
  rebuild_player_role_vectors.py
  evaluate_completed_match.py
  evaluate_all_completed_matches.py
  sync_tactical_context.py
```

Core principle:

```text id="42zhrb"
Raw data -> normalized data -> derived tactical signals -> model/brief/evaluation outputs
```

Every external or manual input must have:

* source
* timestamp
* confidence
* raw value
* normalized value
* update method
* data-quality status

---

# 1. Future Direction 1: Real Player Stats Ingestion

## Goal

Replace or augment manually curated player traits with real statistics.

The current player layer may already include projected XI, formation role, shooting, passing, chance creation, progression, dribbling, crossing, pressing, tackling, aerials, discipline, and goalkeeper traits. This future module should ingest real player statistics and convert them into standardized role vectors.

## New files

```text id="umv2as"
app/ingestion/player_stats_ingestion.py
app/ingestion/normalizers.py
scripts/ingest_player_stats.py
scripts/rebuild_player_role_vectors.py
data/raw/player_stats/
data/normalized/player_season_stats_normalized.csv
data/normalized/player_match_stats_normalized.csv
data/derived/player_role_vectors.csv
data/derived/player_form_signals.csv
```

## Normalized schema: `player_season_stats_normalized.csv`

```csv id="8saw83"
player_id,player,team,national_team,club,season,competition,position,minutes,goals,assists,shots,shots_on_target,xg,xa,key_passes,progressive_passes,progressive_carries,passes_completed,passes_attempted,pass_completion,dribbles_completed,dribbles_attempted,tackles,interceptions,pressures,aerials_won,aerials_lost,yellow_cards,red_cards,source,source_confidence,updated_at
```

## Normalized schema: `player_match_stats_normalized.csv`

```csv id="kyh4yi"
match_id,player_id,player,team,opponent,date,competition,position,started,minutes,goals,assists,xg,xa,shots,key_passes,progressive_passes,progressive_carries,duels_won,duels_lost,pressures,tackles,interceptions,aerials_won,aerials_lost,source,source_confidence,updated_at
```

## Derived schema: `player_role_vectors.csv`

```csv id="qx8vds"
player_id,player,team,role_archetype,role_fit_score,shooting_score,creation_score,progression_score,ball_retention_score,pressing_score,defending_score,aerial_score,transition_score,set_piece_score,form_score,confidence,updated_at
```

## Role archetypes

Start with these role archetypes:

```text id="trhffv"
inverted_winger
touchline_winger
direct_transition_winger
pressing_winger
target_striker
false_nine
poacher
box_to_box_midfielder
deep_lying_playmaker
ball_winning_midfielder
attacking_midfielder
overlapping_fullback
inverted_fullback
defensive_fullback
ball_playing_centerback
stopper_centerback
sweeper_keeper
shot_stopper
```

## Implementation notes

The ingestion system should support multiple sources, but the internal model should not care where the data came from. Use adapters.

Example adapter interface:

```python id="89kn6j"
class PlayerStatsAdapter:
    name: str

    def fetch(self, team: str | None = None) -> list[dict]:
        ...

    def normalize(self, raw_rows: list[dict]) -> list[PlayerSeasonStat]:
        ...
```

## Data quality rules

Add validation:

```text id="dxsyfy"
- minutes must be >= 0
- pass_completion must be between 0 and 1
- goals, assists, shots must be nonnegative
- player_id must not be empty
- source must not be empty
- updated_at must not be empty
```

If a row fails validation:

* do not crash
* log it to `data/provenance/data_quality_report.csv`
* continue with valid rows

## Acceptance criteria

```text id="il4g9n"
python scripts/ingest_player_stats.py --source manual_csv
python scripts/rebuild_player_role_vectors.py
```

Expected output:

* normalized player stats file exists
* role vector file exists
* each player has at least one role archetype
* missing stats fall back to existing manual player traits
* existing match predictor still runs

---

# 2. Future Direction 2: Injury and News Feed Ingestion

## Goal

Track injuries, suspensions, minutes limits, uncertain availability, and news-driven tactical changes.

This should feed:

* player availability
* lineup confidence
* fatigue risk
* tactical brief
* matchup engine
* match probability adjustment
* Intelligence Desk answers

## New files

```text id="chgbwb"
app/ingestion/injury_news_ingestion.py
scripts/ingest_injury_news.py
data/raw/injury_news/
data/normalized/injury_news_normalized.csv
data/derived/injury_risk_signals.csv
```

## Normalized schema: `injury_news_normalized.csv`

```csv id="hobwvk"
news_id,player_id,player,team,date_published,source,headline,summary,status,injury_type,severity,expected_return,availability_probability,minutes_limit,confidence,needs_manual_review,raw_url_or_ref,updated_at
```

## Status categories

Use these exact normalized status values:

```text id="abfski"
fit
minor_doubt
major_doubt
injured
suspended
rested
minutes_limited
unknown
```

## Derived schema: `injury_risk_signals.csv`

```csv id="em1t45"
player_id,player,team,status,availability_probability,expected_minutes,injury_risk_score,lineup_risk_score,source_count,last_update,confidence
```

## News confidence logic

Do not treat all news equally.

Basic scoring:

```text id="1wg7lp"
official_team_report: 0.95
press_conference_quote: 0.85
major_reporter: 0.75
local_reporter: 0.65
aggregator: 0.50
social_media_unclear: 0.35
unknown_source: 0.25
```

If multiple sources agree, increase confidence.
If sources conflict, mark `needs_manual_review = true`.

## Example output

```json id="651pw3"
{
  "player": "Player Name",
  "team": "France",
  "status": "minor_doubt",
  "availability_probability": 0.68,
  "minutes_limit": 60,
  "confidence": 0.72,
  "reason": "Two sources report training limitation; no official exclusion."
}
```

## Intelligence Desk upgrade

The Intelligence Desk should answer:

```text id="pjtaez"
Is this player likely to start?
How does this injury affect the tactical brief?
Which matchup changes if this player is out?
How much does this reduce the team's chance?
```

## Acceptance criteria

```text id="vmo5s1"
python scripts/ingest_injury_news.py --source manual_csv
```

Expected:

* normalized injury/news file exists
* injury risk signal file exists
* tactical brief includes availability risks
* matchups exclude or downgrade injured/minutes-limited players
* system logs source confidence

---

# 3. Future Direction 3: Manager Skill Refinement from Tactical Articles and Match Reports

## Goal

Upgrade manager skills from manually written rules into evidence-backed tactical profiles.

The system should ingest public tactical articles, match reports, press-conference summaries, and post-match analysis, then extract manager behavior patterns.

This does not mean blindly trusting articles. It means creating a structured evidence layer that supports manager-skill updates.

## New files

```text id="1pd1a6"
app/ingestion/tactical_article_ingestion.py
scripts/ingest_tactical_articles.py
scripts/refine_manager_skills.py
data/raw/tactical_articles/
data/normalized/tactical_evidence_normalized.csv
data/derived/manager_skill_updates.csv
```

## Normalized schema: `tactical_evidence_normalized.csv`

```csv id="k7hbay"
evidence_id,manager_id,manager_name,team,match_id,date,source,title,evidence_type,tactical_topic,claim,formation,game_state,confidence,source_quality,needs_manual_review,raw_url_or_ref,updated_at
```

## Evidence types

Use these values:

```text id="bmhcwu"
formation_choice
pressing_behavior
build_up_pattern
defensive_shape
transition_pattern
substitution_pattern
set_piece_pattern
player_role_usage
game_state_adjustment
weakness_exploited
weakness_exposed
```

## Tactical topics

Use tags like:

```text id="dtu5h2"
high_press
mid_block
low_block
counterattack
positional_play
wide_overload
central_overload
inverted_fullback
overlapping_fullback
false_nine
target_forward
double_pivot
back_three
rest_defense
set_piece_attack
set_piece_defense
late_game_management
```

## Manager skill update schema: `manager_skill_updates.csv`

```csv id="yngs8i"
update_id,manager_id,team,tactical_topic,old_weight,new_weight,evidence_count,positive_examples,negative_examples,confidence,updated_at,notes
```

## Refinement logic

Manager skills should have weighted tactical tendencies.

Example:

```json id="th9pmx"
{
  "manager_id": "france_deschamps",
  "tendencies": {
    "compact_mid_block": 0.82,
    "high_press": 0.41,
    "direct_transition": 0.78,
    "positional_play": 0.45,
    "late_defensive_substitution": 0.76
  }
}
```

Refinement rule:

```text id="ck5wiv"
new_weight = old_weight * 0.75 + evidence_score * 0.25
```

Where `evidence_score` depends on:

* source quality
* match relevance
* recency
* consistency with other reports
* whether actual event data supports the claim

## Important safety rule

Do not let an LLM directly overwrite manager skills.

Correct flow:

```text id="x7i5fh"
article/report -> extracted tactical claim -> normalized evidence -> manual/reviewable manager_skill_update -> optional apply
```

## Acceptance criteria

```text id="4rqgy9"
python scripts/ingest_tactical_articles.py --source manual_csv
python scripts/refine_manager_skills.py --manager france_deschamps --dry-run
```

Expected:

* tactical evidence file exists
* manager skill update file exists
* dry-run shows suggested changes
* original manager skill JSON is not overwritten unless `--apply` is passed
* every update includes evidence IDs

---

# 4. Future Direction 4: Actual Lineup Updates During the Tournament

## Goal

During the tournament, update match predictions and tactical briefs when actual lineups are announced.

This is one of the most valuable live features because the difference between projected XI and actual XI can change:

* win probability
* expected goals
* matchup edges
* set-piece strength
* pressing ability
* substitution expectations
* player scorer odds

## New files

```text id="a7mhbp"
app/ingestion/lineup_ingestion.py
scripts/ingest_lineups.py
data/raw/lineups/
data/normalized/actual_lineups_normalized.csv
data/derived/lineup_delta_signals.csv
```

## Normalized schema: `actual_lineups_normalized.csv`

```csv id="4lx6lp"
match_id,team,opponent,player_id,player,position_slot,role,starter,is_captain,is_goalkeeper,shirt_number,formation,source,confirmed,confidence,updated_at
```

## Derived schema: `lineup_delta_signals.csv`

```csv id="3c42c4"
match_id,team,projected_formation,actual_formation,formation_changed,missing_projected_starters,new_unexpected_starters,lineup_strength_delta,pressing_delta,creation_delta,set_piece_delta,defensive_delta,goalkeeper_delta,confidence,updated_at
```

## Core lineup delta logic

Compare projected lineup vs actual lineup.

Questions to answer:

```text id="jggvm8"
Who unexpectedly starts?
Who unexpectedly misses out?
Did the formation change?
Did the team lose chance creation?
Did the team gain defensive stability?
Did set-piece strength change?
Did penalty/shootout strength change?
Which matchups changed?
```

## Integration with match predictor

Add a lightweight forecast-time adjustment:

```text id="ugz0ps"
lineup_strength_delta
pressing_delta
creation_delta
defensive_delta
goalkeeper_delta
set_piece_delta
```

These should feed the existing advanced-signal layer, not retrain the model.

## API additions

```text id="tmv25y"
POST /api/refresh-lineups
GET  /api/lineup-delta?match_id=...
POST /api/match-with-lineups
POST /api/tactics/brief-with-lineups
```

## Frontend additions

In the Match Lab / Tactical Lab:

```text id="3ej21b"
Projected XI vs Actual XI
Formation changed badge
Unexpected starter badge
Unavailable starter badge
Lineup impact summary
Recalculate forecast button
Recalculate tactical brief button
```

## Acceptance criteria

```text id="9n3ph7"
python scripts/ingest_lineups.py --source manual_csv --match-id 1
```

Expected:

* actual lineup file exists
* lineup delta file exists
* tactical brief updates key matchups
* match prediction can show pre-lineup vs post-lineup forecast
* system clearly labels whether lineup is projected or confirmed

---

# 5. Future Direction 5: Post-Match Automatic Evaluation Using Event Data

## Goal

After each completed match, evaluate whether the model, manager skill, matchup engine, and human analyst predictions were actually right.

This is the most important future direction because it turns the project from a prediction toy into a learning system.

## New files

```text id="y0fo47"
app/ingestion/event_data_ingestion.py
app/evaluation/postmatch_evaluator.py
app/evaluation/manager_skill_evaluator.py
app/evaluation/matchup_evaluator.py
app/evaluation/analyst_evaluator.py

scripts/ingest_event_data.py
scripts/evaluate_completed_match.py
scripts/evaluate_all_completed_matches.py

data/raw/event_data/
data/normalized/match_events_normalized.csv
data/derived/match_summary_signals.csv
data/derived/matchup_evaluation_results.csv
data/derived/manager_skill_evaluation_results.csv
data/derived/postmatch_model_evaluation.csv
```

## Normalized schema: `match_events_normalized.csv`

```csv id="ex2vya"
event_id,match_id,minute,second,team,player_id,player,event_type,x,y,end_x,end_y,outcome,body_part,under_pressure,assist_type,shot_xg,pass_progression,carry_progression,duel_type,duel_won,source,confidence,updated_at
```

## Event types

Start with:

```text id="cl5w18"
shot
goal
pass
key_pass
progressive_pass
carry
progressive_carry
cross
tackle
interception
duel
aerial_duel
foul
yellow_card
red_card
substitution
set_piece
corner
penalty
save
```

## Derived schema: `match_summary_signals.csv`

```csv id="5a6qnj"
match_id,team,opponent,goals,xg,shots,shots_on_target,big_chances,field_tilt,deep_touches,progressive_passes,progressive_carries,pressures,high_turnovers,set_piece_xg,counterattack_xg,box_entries,final_third_entries,defensive_actions,keeper_psxg_delta,updated_at
```

## Matchup evaluation schema: `matchup_evaluation_results.csv`

```csv id="ps678t"
match_id,matchup_id,matchup_type,predicted_favored_team,predicted_edge_score,actual_winner,actual_impact_score,was_prediction_correct,evidence_metrics,notes,updated_at
```

## Manager skill evaluation schema

```csv id="pkmcou"
match_id,manager_id,team,predicted_plan,actual_formation,predicted_formation,formation_correct,predicted_pressing,actual_pressing_proxy,pressing_correct,predicted_transition_plan,actual_transition_xg,transition_correct,predicted_substitution_pattern,actual_substitutions,substitution_correct,overall_skill_accuracy,notes,updated_at
```

## Model evaluation schema

```csv id="j3g56p"
match_id,team_a,team_b,predicted_winner,actual_winner,predicted_score_a,predicted_score_b,actual_score_a,actual_score_b,prob_team_a,prob_draw,prob_team_b,brier_score,log_loss,exact_score_hit,winner_hit,calibration_bucket,updated_at
```

## Evaluation questions

The evaluator should answer:

```text id="to6xus"
Did the match model predict the winner?
Was the predicted score shape close?
Did the expected tactical advantage actually appear?
Did the key matchup matter?
Did the manager behave according to the manager skill?
Did actual lineup changes explain forecast error?
Did injury/news signals matter?
Did Kevin/friends outperform the model in any category?
```

## Example: matchup evaluation

If the pre-game brief said:

```text id="m4q2uq"
England RW has edge against opponent LB.
```

The evaluator should check:

```text id="czvbzb"
- Did England attack that side?
- Did the RW complete progressive carries?
- Did the RW create shots/chances?
- Did the LB commit fouls/cards?
- Did the matchup produce xG or key passes?
```

Then output:

```json id="o4or7b"
{
  "matchup_type": "winger_vs_fullback",
  "predicted_favored_team": "England",
  "actual_winner": "England",
  "actual_impact_score": 0.71,
  "was_prediction_correct": true,
  "evidence": [
    "RW created 3 chances",
    "RW completed 5 progressive carries",
    "Opponent LB received yellow card"
  ]
}
```

## Example: manager skill evaluation

If the manager skill predicted:

```text id="pvfl6s"
France will sit in compact mid-block and attack in transition.
```

The evaluator should check proxies:

```text id="q0cydl"
- possession share
- pass directness
- counterattack xG
- high turnovers
- defensive action height
- average possession sequence length
```

Then output:

```json id="39kh6o"
{
  "manager_id": "france_deschamps",
  "predicted_plan": "compact transition",
  "actual_pattern": "compact transition",
  "overall_skill_accuracy": 0.78,
  "notes": "Low possession, high transition xG, and limited pressing matched pre-game skill."
}
```

## Acceptance criteria

```text id="oe2vrk"
python scripts/ingest_event_data.py --source manual_csv --match-id 1
python scripts/evaluate_completed_match.py --match-id 1
```

Expected:

* event data normalized
* match summary signals generated
* matchup predictions evaluated
* manager skill evaluated
* model prediction evaluated
* analyst logs evaluated if available

---

# 6. Global Provenance System

## Goal

Every data point should be traceable.

Add:

```text id="uqd1c0"
app/ingestion/provenance.py
data/provenance/source_registry.csv
data/provenance/ingestion_runs.csv
data/provenance/data_quality_report.csv
```

## `source_registry.csv`

```csv id="l6pv40"
source_id,source_name,source_type,reliability_score,requires_api_key,terms_note,enabled,last_checked,notes
```

## `ingestion_runs.csv`

```csv id="njm8mn"
run_id,source_id,script,started_at,finished_at,status,rows_raw,rows_normalized,rows_failed,error_message
```

## `data_quality_report.csv`

```csv id="y20fuw"
issue_id,run_id,file,row_number,severity,field,problem,raw_value,suggested_fix,created_at
```

## Data quality severity

```text id="vooumk"
info
warning
error
critical
```

Critical errors should stop derived-signal generation.
Warnings should not stop the pipeline.

---

# 7. Integration with Existing Advanced Signal Layer

The repo already has advanced forecast-time concepts. Future derived signals should plug into those rather than creating a separate prediction system.

Add these derived signal categories:

```text id="6snd16"
real_player_form_delta
injury_availability_delta
confirmed_lineup_delta
manager_skill_confidence_delta
matchup_edge_delta
postmatch_learning_delta
```

Expected integration:

```text id="ib1bug"
base ensemble prediction
+ existing venue/weather/travel/fatigue context
+ existing advanced signals
+ new player form signals
+ new injury/news signals
+ new confirmed lineup signals
+ new tactical matchup signals
= updated match forecast and tactical brief
```

Important:

Do not retrain the Random Forest every time news changes.
Use forecast-time adjustments and clear labels.

---

# 8. New API Endpoints

Add future endpoints gradually.

## Player stats

```text id="lulldu"
POST /api/refresh-player-stats
GET  /api/player-role-vector/{player_id}
GET  /api/team-role-depth/{team}
```

## Injury/news

```text id="wjympv"
POST /api/refresh-injury-news
GET  /api/injury-status?team=...
GET  /api/player-availability/{player_id}
```

## Manager refinement

```text id="o1qz3x"
POST /api/refresh-tactical-evidence
GET  /api/manager-evidence/{manager_id}
POST /api/manager-skill/refine-dry-run
POST /api/manager-skill/apply-update
```

## Lineups

```text id="8uqaie"
POST /api/refresh-lineups
GET  /api/lineup-delta?match_id=...
POST /api/tactics/brief-with-lineups
```

## Post-match evaluation

```text id="9yrf98"
POST /api/refresh-event-data
POST /api/evaluate-match
GET  /api/evaluation/match/{match_id}
GET  /api/evaluation/manager/{manager_id}
GET  /api/evaluation/analyst/{analyst}
GET  /api/evaluation/model
```

---

# 9. Intelligence Desk Upgrade

The Intelligence Desk should gain new tool routes.

## New tool route types

```text id="nvnck4"
player_stats
injury_news
manager_evidence
lineup_delta
postmatch_evaluation
```

## Example questions it should answer

```text id="mzmbv3"
How has Mbappe's current form changed France's forecast?
Is Argentina's starting XI confirmed?
What injuries affect England's tactical plan?
Did Deschamps actually follow the manager skill last match?
Which pre-game matchup prediction was wrong?
Did Kevin outperform the model on tactical predictions?
Why did the model miss this match?
```

## Response rule

Every Intelligence Desk answer should separate:

```text id="74quog"
Model forecast
Tactical evidence
Player/injury evidence
Lineup evidence
Post-match evaluation
Uncertainty / missing data
```

---

# 10. Frontend Roadmap

Add panels in this order.

## 10.1 Player Form Center

Shows:

* player role vector
* season stats
* recent form
* role percentile
* confidence/source

## 10.2 Injury & News Board

Shows:

* team availability
* doubtful players
* minutes limits
* source confidence
* tactical impact

## 10.3 Manager Evidence View

Shows:

* manager skill
* evidence claims
* tactical tendencies
* suggested refinements
* apply/dry-run update button

## 10.4 Confirmed Lineup Delta View

Shows:

* projected XI vs actual XI
* formation delta
* strength delta
* changed matchup edges
* pre-lineup vs post-lineup forecast

## 10.5 Post-Match Review Center

Shows:

* predicted vs actual score
* model calibration
* manager skill accuracy
* matchup accuracy
* analyst accuracy
* what should be updated

---

# 11. Implementation Phases for Codex

## Phase F1: Data ingestion foundation

Status: implemented on June 11, 2026. Later phases should reuse `app/ingestion/` rather than creating new CSV or provenance helpers.

Prompt:

```text id="s26661"
You are working in the existing KaiwenMo1/worldcup2026 repository. Do not rewrite the simulator, FastAPI app, or existing advanced signal layer.

Implement the shared ingestion foundation only.

Create:
- app/ingestion/__init__.py
- app/ingestion/schemas.py
- app/ingestion/source_registry.py
- app/ingestion/provenance.py
- app/ingestion/normalizers.py
- data/provenance/source_registry.csv
- data/provenance/ingestion_runs.csv
- data/provenance/data_quality_report.csv

Requirements:
1. Define schemas for SourceRecord, IngestionRun, DataQualityIssue.
2. Treat ingestion_runs.csv and data_quality_report.csv as append-only audit logs.
3. Use atomic replacement writes for mutable registry files and schema-checked appends for audit logs.
4. Store timezone-aware UTC timestamps and stable generated IDs.
5. Implement safe CSV read/write utilities that return structured results and issues instead of silently dropping bad rows.
6. Implement generic row validation that returns valid typed records plus DataQualityIssue objects without crashing on malformed rows.
7. Source registry records must have unique source_id values and explicit reliability, API-key, terms, enabled, and last-checked metadata.
8. Add focused tests in tests/test_ingestion_foundation.py and a smoke script scripts/test_ingestion_foundation.py.
9. Ensure:
   - python -m unittest discover -s tests -v passes
   - python -m compileall app scripts tests passes

Do not add external API calls yet.
Do not modify existing prediction behavior.
Do not make later ingestion modules invent their own CSV/provenance utilities; they should reuse this foundation.
```

## Phase F2: Real player stats ingestion

Status: implemented on June 12, 2026. The manual adapter reuses `app/ingestion/`, preserves curated player profiles as lower-confidence fallbacks, and does not alter prediction behavior.

Prompt:

```text id="xsmcws"
Continue the future ingestion layer. Implement real player stats ingestion with a manual CSV adapter first.

Create:
- app/ingestion/player_stats_ingestion.py
- scripts/ingest_player_stats.py
- scripts/rebuild_player_role_vectors.py
- data/raw/player_stats/manual_player_stats_sample.csv
- data/normalized/player_season_stats_normalized.csv
- data/normalized/player_match_stats_normalized.csv
- data/derived/player_role_vectors.csv
- data/derived/player_form_signals.csv

Requirements:
1. Ingest player stats from manual CSV.
2. Normalize to the shared player stat schema.
3. Validate rows and log bad rows to data/provenance/data_quality_report.csv.
4. Build role vectors using transparent scoring.
5. Support role archetypes such as inverted_winger, target_striker, deep_lying_playmaker, ball_winning_midfielder, overlapping_fullback, ball_playing_centerback, and shot_stopper.
6. Existing manually curated player traits should remain a fallback.
7. Add scripts/test_player_stats_ingestion.py.

Do not call external APIs.
Do not retrain the match model.
```

## Phase F3: Injury/news ingestion

Status: implemented on June 12, 2026. The manual adapter produces separate evidence and derived risk files, logs conflicting reports for review, and does not overwrite forecast availability or change prediction behavior.

Prompt:

```text id="n9r0mi"
Continue the future ingestion layer. Implement injury and news ingestion with a manual CSV adapter first.

Create:
- app/ingestion/injury_news_ingestion.py
- scripts/ingest_injury_news.py
- data/raw/injury_news/manual_injury_news_sample.csv
- data/normalized/injury_news_normalized.csv
- data/derived/injury_risk_signals.csv

Requirements:
1. Normalize injury/news rows into statuses:
   fit, minor_doubt, major_doubt, injured, suspended, rested, minutes_limited, unknown.
2. Compute availability_probability and expected_minutes.
3. Use source confidence scoring.
4. If sources conflict, mark needs_manual_review = true.
5. Export derived injury_risk_signals.csv.
6. Add a helper that tactical briefs can call to get availability by team.
7. Add scripts/test_injury_news_ingestion.py.

Do not use external APIs yet.
Do not change existing prediction behavior.
```

## Phase F4: Manager skill refinement from tactical evidence

Status: implemented on June 12, 2026. Refinement is dry-run by default; only recurring, supported, human-reviewed evidence can be explicitly applied after full `ManagerSkill` validation.

Prompt:

```text id="qibndm"
Continue the future ingestion layer. Implement tactical article and match-report evidence ingestion for manager-skill refinement.

Create:
- app/ingestion/tactical_article_ingestion.py
- scripts/ingest_tactical_articles.py
- scripts/refine_manager_skills.py
- data/raw/tactical_articles/manual_tactical_evidence_sample.csv
- data/normalized/tactical_evidence_normalized.csv
- data/derived/manager_skill_updates.csv

Requirements:
1. Ingest manually curated tactical evidence rows.
2. Normalize evidence_type and tactical_topic.
3. Compute source_quality and confidence.
4. Suggest manager-skill updates as a dry run.
5. Do not overwrite manager skill JSON files unless --apply is passed.
6. Every suggested update must reference evidence_id values.
7. Add scripts/test_manager_refinement.py.

Important:
Do not let LLM-generated text directly overwrite manager skills.
All changes must be evidence-backed and reviewable.
```

## Phase F5: Actual lineup updates

Status: implemented on June 13, 2026. Verified starter rows are normalized separately from projections, and transparent lineup-delta signals quantify formation, strength, pressing, creation, set-piece, defensive, and goalkeeper changes. Provider refresh remains optional and only confirmed rows become observed facts.

Prompt:

```text id="k2v09b"
Continue the future ingestion layer. Implement actual lineup ingestion and lineup delta signals.

Create:
- app/ingestion/lineup_ingestion.py
- scripts/ingest_lineups.py
- data/raw/lineups/manual_lineups_sample.csv
- data/normalized/actual_lineups_normalized.csv
- data/derived/lineup_delta_signals.csv

Requirements:
1. Normalize actual lineups by match_id and team.
2. Compare actual lineups with projected_lineups.csv if available.
3. Compute:
   - formation_changed
   - missing_projected_starters
   - unexpected_starters
   - lineup_strength_delta
   - pressing_delta
   - creation_delta
   - set_piece_delta
   - defensive_delta
   - goalkeeper_delta
4. Add helper functions for the tactical brief and advanced signal layer.
5. Add scripts/test_lineup_ingestion.py.

Do not break existing /api/refresh-lineups.
If existing lineup refresh code exists, wrap or reuse it instead of duplicating behavior.
```

## Phase F6: Post-match event ingestion

Status: implemented on June 12, 2026. The manual adapter maps provider-style columns and labels into a typed event stream, logs missing optional details as informational issues, derives transparent match-team summaries, and does not alter prediction behavior.

Prompt:

```text id="v9htwe"
Continue the future ingestion layer. Implement post-match event data ingestion with manual CSV first.

Create:
- app/ingestion/event_data_ingestion.py
- scripts/ingest_event_data.py
- data/raw/event_data/manual_match_events_sample.csv
- data/normalized/match_events_normalized.csv
- data/derived/match_summary_signals.csv

Requirements:
1. Normalize event data into the match_events schema.
2. Support event types:
   shot, goal, pass, key_pass, progressive_pass, carry, progressive_carry, cross, tackle, interception, duel, aerial_duel, foul, card, substitution, set_piece, corner, penalty, save.
3. Build match_summary_signals.csv with xG, shots, field tilt, box entries, set-piece xG, counterattack xG, pressing proxies, and goalkeeper impact if available.
4. Log missing optional fields but do not crash.
5. Add scripts/test_event_data_ingestion.py.

Do not assume one provider format.
Use adapter-style parsing.
```

## Phase F7: Post-match automatic evaluation

Status: implemented on June 12, 2026. The explainable feedback loop evaluates model forecasts, manager hypotheses, matchup edges, and analyst logs; missing evidence remains visible, and derived CSV rows are idempotently upserted.

Prompt:

```text id="uie6tm"
Implement the post-match evaluation subsystem.

Create:
- app/evaluation/__init__.py
- app/evaluation/schemas.py
- app/evaluation/postmatch_evaluator.py
- app/evaluation/manager_skill_evaluator.py
- app/evaluation/matchup_evaluator.py
- app/evaluation/analyst_evaluator.py
- scripts/evaluate_completed_match.py
- scripts/evaluate_all_completed_matches.py
- data/derived/matchup_evaluation_results.csv
- data/derived/manager_skill_evaluation_results.csv
- data/derived/postmatch_model_evaluation.csv

Requirements:
1. Evaluate model prediction vs actual result.
2. Evaluate exact-score hit, winner hit, Brier score, and calibration bucket.
3. Evaluate manager skill prediction against actual formation, pressing proxy, transition xG, and substitutions.
4. Evaluate matchup predictions against event-derived evidence.
5. Evaluate analyst prediction logs if they exist.
6. Output all evaluation results to CSV.
7. Add scripts/test_postmatch_evaluation.py.

This is the core feedback loop. Keep all evaluation logic transparent and explainable.
```

## Phase F8: API and frontend integration

Prompt:

```text id="vpafz3"
Expose future ingestion and evaluation outputs through the FastAPI app and frontend.

Add backend endpoints:
- POST /api/refresh-player-stats
- GET /api/player-role-vector/{player_id}
- POST /api/refresh-injury-news
- GET /api/injury-status
- POST /api/refresh-tactical-evidence
- GET /api/manager-evidence/{manager_id}
- POST /api/refresh-lineups
- GET /api/lineup-delta
- POST /api/refresh-event-data
- POST /api/evaluate-match
- GET /api/evaluation/match/{match_id}
- GET /api/evaluation/manager/{manager_id}
- GET /api/evaluation/analyst/{analyst}

Frontend:
1. Add Player Form Center.
2. Add Injury & News Board.
3. Add Manager Evidence View.
4. Add Confirmed Lineup Delta View.
5. Add Post-Match Review Center.

Rules:
- Keep endpoint code thin.
- Reuse app/ingestion and app/evaluation modules.
- Do not break existing routes.
- All new UI should degrade gracefully if files are missing.
```

---

# 12. Final Product Vision

After these future phases, the project becomes:

A live World Cup tactical intelligence system that combines:
- ML match prediction
- real player form/stat ingestion
- injury and news uncertainty
- manager-skill distillation
- confirmed lineup updates
- matchup analysis
- human analyst journals
- post-match automatic evaluation
```

The key differentiator is not just predicting matches.

The key differentiator is:

The system can explain why it believed something before the match, check whether that belief was right after the match, and update future tactical reasoning based on evidence.
```

That is what makes it more impressive than a normal World Cup predictor.


You are working in the existing KaiwenMo1/worldcup2026 repository.

We want to add a Nuwa-inspired manager skill distillation pipeline. Do not add alchaincyf/nuwa-skill as a runtime dependency for the FastAPI app. Instead, adapt its methodology into this repo as a local manager-skill builder.

Status: framework implemented on June 11, 2026. It requires manually curated evidence before any of the 48 registered managers can be promoted to an evidence-backed generated skill.

Goal:
Create a framework that distills football managers into reusable tactical skills using public evidence, then exports both:
1. A human-readable SKILL.md for Codex/LLM reasoning.
2. A structured manager_skill.json for the app's tactical engine.

Create:

skills/
  manager-skill-builder/
    SKILL.md
    references/
      manager-extraction-framework.md
      manager-skill-template.md

app/
  manager_distillation/
    __init__.py
    schemas.py
    evidence_loader.py
    skill_builder.py
    skill_exporter.py
    validation.py

data/
  manager_distillation/
    raw_evidence/
    normalized_evidence/
    generated_skills/

scripts/
  create_manager_skill.py
  validate_manager_skill.py
  export_manager_skill_json.py

The manager extraction framework should adapt Nuwa's six-research-agent structure to football:

1. tactical_reports
   - match analysis, tactical previews, tactical breakdowns

2. press_conferences
   - manager interviews, press conferences, direct explanations

3. expression_dna
   - tone, certainty, public priorities, repeated phrases

4. external_views
   - analyst views, opposition comments, journalist interpretations

5. decision_records
   - lineups, substitutions, formation switches, knockout-game decisions

6. timeline
   - career evolution, recent 12-month tactical changes, tournament history

The manager skill should extract:

- tactical identity
- preferred formations
- in-possession rules
- out-of-possession rules
- transition rules
- pressing triggers
- set-piece tendencies
- substitution patterns
- game-state rules
- player archetype preferences
- anti-patterns
- honest boundaries
- evidence sources

Validation rules:

A tactical rule should only become a core manager rule if it passes:

1. Cross-match recurrence:
   The pattern appears across multiple matches or multiple reliable sources.

2. Predictive power:
   The rule can predict what the manager may do in a future match state.

3. Distinctiveness:
   The rule is specific to this manager, not generic football common sense.

If a claim fails validation:
- downgrade it to a low-confidence heuristic
- keep it in evidence notes
- do not put it in core rules

Honest boundaries must always include:
- public information may be incomplete
- press conferences may be strategic
- tactical articles may be secondhand interpretation
- private fitness and training data are unavailable
- recent injuries or camp dynamics may override historical patterns

Implement scripts:

1. scripts/create_manager_skill.py
   Input:
   --manager-id
   --manager-name
   --team
   --evidence-dir

   Output:
   data/manager_distillation/generated_skills/{manager_id}/SKILL.md
   data/manager_distillation/generated_skills/{manager_id}/validation_report.md

2. scripts/validate_manager_skill.py
   Checks:
   - at least 3 core tactical models
   - at least 5 decision heuristics
   - every core rule has evidence IDs
   - honest boundaries exist
   - source list exists
   - validation status is PASS/WARN/FAIL

3. scripts/export_manager_skill_json.py
   Converts SKILL.md or intermediate schema into:
   data/manager_skills/{manager_id}.json

Do not use external APIs yet.
Use manually curated markdown/CSV evidence files first.
Do not overwrite existing manager_skill JSON unless --apply is passed.
Make everything additive.
Ensure python -m compileall app scripts passes.
