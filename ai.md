# WorldCup2026 Tactical Agent Roadmap: Manager Skills + Player Matchup Intelligence

## Project Goal

Upgrade the existing `worldcup2026` repository from a tournament ML predictor into a tactical football intelligence system.

The current repo already predicts match outcomes, expected scores, champion odds, bracket paths, top scorers, weather/travel/fatigue effects, betting edges, and local RAG answers. Do not rewrite the existing predictor. Instead, add a new tactical layer that plugs into the current FastAPI app, simulation model, Intelligence Desk, and player/squad data.

The new system should support:

1. Manager-skill distillation.
2. Player role profiles.
3. Matchup analysis such as RW vs LB, CF vs CBs, midfield overloads, set-piece mismatches, and transition risk.
4. Human analyst prediction logs from Kevin/friends.
5. Post-game evaluation so the system learns which human/manager/model assumptions were right or wrong.
6. A Codex-friendly, testable architecture that can later expand to other leagues or sports.

Manager skills in this roadmap are versioned tactical hypotheses, not claims of objective truth. They describe patterns that the system can explain and later evaluate against observed matches. During the first phases, manager plans are analysis-only and must not modify the existing model probabilities or expected goals.

---

# 1. Current Repository Foundation

The repo already has these useful foundations:

## 1.1 Tournament simulation

Existing files:

* `scripts/predict_worldcup.py`
* `scripts/train_model.py`
* `models/worldcup_random_forest.joblib`
* `data/teams.csv`
* `data/groups.csv`
* `data/historical_matches.csv`
* `data/team_features.csv`
* `data/team_advanced_features.csv`

Current capabilities:

* 48-team World Cup simulation.
* Group stage and knockout prediction.
* Exact-score probability distribution.
* Random Forest match outcome classifier.
* Random Forest goal regressors.
* Baseline Poisson expected-goals model.
* Elo/recent-form features.
* Tournament sample weighting and recency weighting.

Do not break this pipeline.

## 1.2 Existing tactical signals

The repo already has team-level tactical features:

* manager rating
* tactical flexibility
* pressing intensity
* transition speed
* set-piece attack
* set-piece defense
* penalty strength
* discipline
* injury resilience
* big-match composure

These are useful, but they are scalar team features. The upgrade should make them richer and more explainable.

## 1.3 Existing RAG / Intelligence Desk

Existing file:

* `app/intelligence.py`

Current capabilities:

* Local TF-IDF retrieval over teams, venues, player candidates, historical matches, README, and project docs.
* Entity detection for teams and venues.
* Tool routing for team profiles, head-to-head, match forecast, venue weather, live state, and team shortlists.
* Optional LLM synthesis.

This is the right place to add tactical routes.

## 1.4 Existing web app / API

Existing file:

* `app/main.py`

Current capabilities:

* `/api/simulate`
* `/api/match`
* `/api/intelligence`
* `/api/analyst-brief`
* `/api/teams`
* `/api/groups`
* `/api/fixtures`
* `/api/squads`
* `/api/player-match-stats`
* `/api/lineup-status`
* `/api/advanced-signals`

The tactical layer should expose new APIs without breaking these.

---

# 2. Main Architecture

Add a new tactical subsystem:

```text
app/
  tactics/
    __init__.py
    schemas.py
    manager_skills.py
    player_profiles.py
    matchup_engine.py
    tactical_brief.py
    analyst_journal.py
    evaluation.py

data/
  managers.csv
  manager_skills/
    argentina_scaloni.json
    france_deschamps.json
    england_southgate_or_current.json
    spain_manager.json
    brazil_manager.json
  player_profiles.csv
  player_role_percentiles.csv
  player_availability.csv
  projected_lineups.csv
  matchup_edges.csv
  analyst_prediction_logs.csv
  postgame_reviews.csv

scripts/
  build_player_profiles.py
  build_manager_skills.py
  build_matchup_edges.py
  evaluate_analyst_logs.py
  evaluate_tactical_predictions.py
```

Core idea:

```text
Current ML predictor = What is likely to happen?
Manager skill layer = Which evidence-backed plan would this manager plausibly choose?
Player profile layer = Which players create matchup advantages?
Matchup engine = Where is the game likely to be decided?
Human analyst journal = What did Kevin/friends think before the match?
Post-game evaluator = Which assumptions were correct?
```

Subsystem boundary:

* The current predictor remains the source of match probabilities and expected scores.
* The tactical subsystem initially produces structured hypotheses, explanations, and evaluation records only.
* Existing `data/tactical_profiles.csv`, squad features, player-match stats, and advanced signals should be reused where possible rather than duplicated.
* A tactical hypothesis may influence model probabilities only in a later phase after it has a measurable feature definition, historical evaluation, and calibration evidence.

---

# 3. Data Layer Design

## 3.1 `data/managers.csv`

Purpose: basic manager metadata.

Columns:

```csv
manager_id,manager_name,team,active_from,active_to,status,preferred_formations,default_style,pressing_level,build_up_style,transition_style,set_piece_emphasis,substitution_aggression,big_game_risk_tolerance,source,last_verified,notes
```

Example:

```csv
france_deschamps,Didier Deschamps,France,2012,,unverified,4-2-3-1|4-3-3,compact_transition,medium,direct_or_mixed,fast_counter,medium,medium,low,manual_prototype,,Pragmatic tournament-manager hypothesis; verify against current public evidence before treating as observed
```

## 3.2 `data/manager_skills/*.json`

Purpose: manager-skill distillation.

Each manager skill should encode inspectable tactical hypotheses and decision rules, not personality fluff. Every rule should identify its evidence quality and the context in which it applies.

Example schema:

```json
{
  "manager_id": "france_deschamps",
  "team": "France",
  "skill_name": "Deschamps compact transition manager skill",
  "version": "0.1",
  "status": "manual_prototype",
  "last_verified": null,
  "source_refs": [],
  "tactical_identity": {
    "primary_style": "compact_transition",
    "preferred_formations": ["4-2-3-1", "4-3-3"],
    "build_up": "mixed/direct when pressed",
    "defensive_shape": "mid_block_or_compact_low_block",
    "pressing": "selective",
    "transition": "elite fast attack",
    "set_pieces": "important but not sole identity"
  },
  "decision_rules": [
    {
      "condition_code": "opponent_high_line",
      "parameters": {
        "recovery_defender_score_max": 65
      },
      "recommendation": "prioritize direct runs behind fullbacks and early vertical passes",
      "evidence_confidence": 0.55,
      "source_refs": [],
      "last_verified": null,
      "sample_size": null
    },
    {
      "condition_code": "leading_after_minute",
      "parameters": {
        "minute": 60
      },
      "recommendation": "protect central zones, reduce fullback risk, use transition outlet",
      "evidence_confidence": 0.55,
      "source_refs": [],
      "last_verified": null,
      "sample_size": null
    },
    {
      "condition_code": "opponent_midfield_control",
      "parameters": {
        "possession_share_min": 0.58
      },
      "recommendation": "accept lower possession, maintain compactness, attack wide transition channels",
      "evidence_confidence": 0.45,
      "source_refs": [],
      "last_verified": null,
      "sample_size": null
    }
  ],
  "substitution_patterns": [
    {
      "match_state": "leading",
      "likely_sub_type": "defensive_midfielder_or_fresh_winger",
      "minute_window": "60-75"
    },
    {
      "match_state": "trailing",
      "likely_sub_type": "extra_attacker_or_creative_midfielder",
      "minute_window": "55-70"
    }
  ],
  "evidence_notes": [
    "Use public match reports, tactical articles, and historical lineups later.",
    "For MVP, manually curate 5-10 high-level rules per manager.",
    "Manual prototype confidence is author confidence, not a calibrated probability that the plan will occur or succeed."
  ]
}
```

Decision-rule requirements:

* `condition_code` must come from a small supported vocabulary that the rule engine can evaluate.
* `parameters` contains the thresholds needed to evaluate the condition.
* `evidence_confidence` means confidence that the manager tends to follow the rule in the stated context. It is not the probability that the tactic will succeed.
* Rules without verified sources must be labeled `manual_prototype`.
* Missing evidence should reduce data quality and confidence rather than being silently invented.

Do not overbuild this at first. Start with 5 managers:

* France
* Argentina
* England
* Spain
* Brazil

Then expand.

## 3.3 `data/player_profiles.csv`

Current `player_candidates.csv` is too shallow. Keep it for top-scorer projection, but add a richer player profile table.

Columns:

```csv
player_id,player,team,club,primary_position,secondary_positions,preferred_foot,role_archetypes,starter_probability,minutes_projection,injury_status,fatigue_risk,pace,shooting,passing,chance_creation,progression,dribbling,crossing,pressing,tackling,aerial,discipline,weak_foot_usage,big_match_score,notes
```

Example:

```csv
england_saka,Bukayo Saka,England,Arsenal,RW,LW,left,inverted_creator|high_press_winger,0.92,78,fit,medium,84,82,86,89,88,87,74,81,61,54,80,medium,87,High-value RW who can attack LB inside or outside
```

## 3.4 `data/player_role_percentiles.csv`

Purpose: compare players to same-position and same-role peers.

Columns:

```csv
player_id,role_archetype,metric,percentile,source,updated_at
```

Example:

```csv
england_saka,inverted_creator,progressive_carries,91,manual_projection,2026-06-11
england_saka,inverted_creator,chance_creation,88,manual_projection,2026-06-11
england_saka,high_press_winger,pressing,79,manual_projection,2026-06-11
```

Important rule:

Compare players by role, not just position.

Bad:

```text
Saka vs all RWs
```

Good:

```text
Saka vs inverted right-wing creators
Saka vs high-press wingers
Saka vs direct transition wingers
```

## 3.5 `data/projected_lineups.csv`

Purpose: match-specific or team-default projected XI.

Columns:

```csv
match_id,team,formation,player_id,player,position_slot,role,starter_probability,source,updated_at
```

Example:

```csv
1,England,4-2-3-1,england_saka,Bukayo Saka,RW,inverted_creator,0.92,manual_projection,2026-06-11
```

## 3.6 `data/player_availability.csv`

Purpose: injuries, suspensions, minutes limits, fitness.

Columns:

```csv
player_id,player,team,status,injury_type,expected_minutes_limit,return_probability,source,updated_at,notes
```

Example:

```csv
england_saka,Bukayo Saka,England,fit,,90,0.98,manual_projection,2026-06-11,
```

## 3.7 `data/matchup_edges.csv`

Purpose: cache generated matchup analysis.

Columns:

```csv
match_id,team_a,team_b,team_a_slot,team_a_player_id,team_b_slot,team_b_player_id,matchup_type,edge_score,favored_team,reason,source,updated_at
```

Example:

```csv
1,England,Croatia,RW,england_saka,LB,croatia_lb_placeholder,winger_vs_fullback,0.67,England,Saka's progressive carrying and inside-cut profile tests Croatia LB recovery speed,computed,2026-06-11
```

## 3.8 `data/analyst_prediction_logs.csv`

Purpose: structured pre-game predictions from Kevin/friends.

Columns:

```csv
log_id,match_id,analyst,created_at,kickoff_at,model_version,data_snapshot_id,team_a,team_b,predicted_score_a,predicted_score_b,predicted_winner,confidence,confidence_meaning,expected_lineup_a,expected_lineup_b,key_matchup,team_a_plan,team_b_plan,weakness_a,weakness_b,if_team_a_scores_first,if_team_b_scores_first,substitution_prediction,what_would_change_my_mind,free_text
```

This should be filled before matches. Prediction logs are append-only: post-game review must never overwrite the original pre-game claim. Store the model version and data snapshot identifier so later evaluation can reproduce what the analyst and system knew at prediction time.

## 3.9 `data/postgame_reviews.csv`

Purpose: evaluate predictions after matches.

Columns:

```csv
review_id,log_id,match_id,actual_score_a,actual_score_b,actual_winner,lineup_accuracy,tactical_accuracy,key_matchup_accuracy,score_accuracy,what_was_right,what_was_wrong,why_wrong,updated_rule
```

This lets the system distill Kevin/friends later.

---

# 4. New Python Modules

## 4.1 `app/tactics/schemas.py`

Create Pydantic schemas for:

```python
EvidenceReference
MatchContext
ManagerSkill
DecisionRule
PlayerProfile
PlayerAvailability
ProjectedLineupPlayer
PlayerRolePercentile
MatchupEdge
TacticalBrief
AnalystPredictionLog
PostGameReview
```

Do this first because the repo already uses FastAPI/Pydantic.

Required design:

* Keep schemas simple.
* Use standard Python types.
* Make CSV loading easy.
* Avoid adding a database yet.
* Keep `MatchContext` intentionally small during Phase 1: match state, minute, knockout flag, opponent tactical flags, and optional notes.
* Validate existing files clearly. A missing optional file can use a fallback, but malformed data should fail loudly in tests instead of being silently ignored.

## 4.2 `app/tactics/manager_skills.py`

Functions:

```python
load_manager_skill(manager_id: str) -> ManagerSkill | None
load_team_manager_skill(team: str) -> ManagerSkill | None
list_manager_skills() -> list[ManagerSkill]
evaluate_decision_rules(manager_skill: ManagerSkill, match_context: MatchContext) -> dict
generate_manager_plan(team: str, opponent: str, match_context: MatchContext | None = None) -> ManagerPlan
```

Fallback contract:

* Loader functions return `None` when a manager or file is missing. They should not fabricate a fake manager skill.
* `generate_manager_plan()` always returns a valid `ManagerPlan`.
* If no manager skill is available, the plan clearly sets `fallback_used=true`, uses a neutral plan, and explains that manager-specific evidence was unavailable.
* If `match_context` is missing, return the base plan and mark decision rules as contingent rather than pretending they were triggered.

The manager plan should output:

```json
{
  "team": "France",
  "manager_id": "france_deschamps",
  "base_plan": "compact transition",
  "expected_formation": "4-2-3-1",
  "in_possession": ["attack left channel", "early vertical passes"],
  "out_of_possession": ["compact mid block", "protect center"],
  "transition": ["release LW/RW early"],
  "set_pieces": ["target near-post aerials"],
  "applied_rules": [
    {
      "condition_code": "opponent_high_line",
      "recommendation": "prioritize direct runs behind fullbacks and early vertical passes",
      "reason": "match context reports an opponent high line",
      "evidence_confidence": 0.55,
      "source_refs": []
    }
  ],
  "contingent_rules": [
    {
      "condition_code": "leading_after_minute",
      "recommendation": "protect central zones, reduce fullback risk, use transition outlet"
    }
  ],
  "confidence": {
    "level": "medium",
    "meaning": "confidence that the manager tends to use this plan in the supplied context"
  },
  "data_quality": "manual_prototype",
  "fallback_used": false,
  "fallback_note": null
}
```

## 4.3 `app/tactics/player_profiles.py`

Functions:

```python
load_player_profiles() -> dict[str, PlayerProfile]
load_projected_lineup(team: str, match_id: str | None = None) -> list[ProjectedLineupPlayer]
load_player_availability() -> dict[str, PlayerAvailability]
get_team_role_depth(team: str) -> dict
compare_player_to_role(player_id: str, role: str) -> dict
```

Outputs should support:

* role fit
* injury/fatigue status
* likely minutes
* same-role comparison
* team depth

## 4.4 `app/tactics/matchup_engine.py`

This is the core.

Functions:

```python
build_matchup_edges(team_a: str, team_b: str, match_id: str | None = None) -> list[MatchupEdge]
score_winger_vs_fullback(attacker, defender) -> float
score_striker_vs_centerbacks(striker, centerbacks) -> float
score_midfield_control(midfield_a, midfield_b) -> float
score_set_piece_edge(team_a, team_b) -> float
score_transition_risk(team_a, team_b) -> float
```

Initial MVP matchup types:

1. `winger_vs_fullback`
2. `striker_vs_centerbacks`
3. `midfield_control`
4. `set_piece_edge`
5. `press_vs_build_up`
6. `transition_defense_risk`

Example output:

```json
{
  "matchup_type": "winger_vs_fullback",
  "team_a_player": "Bukayo Saka",
  "team_b_player": "Opponent LB",
  "favored_team": "England",
  "edge_score": 0.67,
  "reason": "England's RW has high progression and chance creation while opponent LB profile has lower recovery/defensive score."
}
```

Keep the scoring transparent. Do not make it a black box yet.

Until matchup scores are evaluated against observed events, treat `edge_score` as a deterministic ranking score rather than a calibrated probability. The UI should pair it with a qualitative label such as slight, moderate, or strong and expose the feature values and lineup assumptions used.

## 4.5 `app/tactics/tactical_brief.py`

This module combines:

* current `/api/match` prediction
* manager skills
* player profiles
* matchup edges
* venue/weather/fatigue context
* human analyst prediction logs if available

Function:

```python
generate_tactical_brief(team_a: str, team_b: str, match_id: str | None = None, use_model: bool = True) -> dict
```

Output:

```json
{
  "match": "France vs Brazil",
  "model_forecast": {
    "favorite": "France",
    "win_probability": 0.54,
    "expected_score": "1.62 - 1.31"
  },
  "manager_plans": {
    "France": {...},
    "Brazil": {...}
  },
  "key_matchups": [
    {...},
    {...},
    {...}
  ],
  "tactical_summary": [
    "France has transition advantage if Brazil's fullbacks push high.",
    "Brazil can create danger if their LW isolates France's RB.",
    "Set pieces are close, but France has a slight aerial edge."
  ],
  "risks": [
    "If France's midfield cannot progress under pressure, the transition plan becomes too passive."
  ],
  "confidence": "medium"
}
```

## 4.6 `app/tactics/analyst_journal.py`

Functions:

```python
create_prediction_log(log: AnalystPredictionLog) -> dict
load_prediction_logs(match_id: str | None = None, analyst: str | None = None) -> list
load_postgame_reviews(match_id: str | None = None) -> list
summarize_analyst_profile(analyst: str) -> dict
```

Analyst profile output:

```json
{
  "analyst": "Kevin",
  "prediction_count": 18,
  "strengths": ["key matchup calls", "winger/fullback dynamics"],
  "biases": ["overweights star attackers", "underweights set pieces"],
  "score_accuracy": 0.22,
  "winner_accuracy": 0.61,
  "key_matchup_accuracy": 0.67,
  "tactical_accuracy": 0.58
}
```

## 4.7 `app/tactics/evaluation.py`

Functions:

```python
evaluate_prediction_log(log_id: str, actual_match_data: dict) -> PostGameReview
evaluate_manager_skill(manager_id: str, match_id: str) -> dict
evaluate_matchup_edges(match_id: str) -> dict
```

This is what prevents the project from becoming fake LLM roleplay.

The evaluator should answer:

* Did predicted lineup match actual lineup?
* Did predicted formation match actual formation?
* Did the key matchup actually matter?
* Did the player advantage show up in shot creation, progressive carries, xG, goals, or defensive events?
* Did the manager follow the expected skill rules?
* Did the model/human overestimate or underestimate something?

---

# 5. API Additions

Add new endpoints to `app/main.py`.

## 5.1 Manager skill endpoints

```text
GET /api/tactics/managers
GET /api/tactics/manager/{team}
GET /api/tactics/manager-plan?team=France&opponent=Brazil
```

## 5.2 Player profile endpoints

```text
GET /api/tactics/players?team=England
GET /api/tactics/player/{player_id}
GET /api/tactics/lineup?team=England&match_id=1
```

## 5.3 Matchup endpoints

```text
POST /api/tactics/matchups
POST /api/tactics/brief
```

Request:

```json
{
  "team_a": "France",
  "team_b": "Brazil",
  "match_id": "optional",
  "use_model": true
}
```

Response should include:

* model forecast
* manager plans
* player matchup edges
* tactical summary
* confidence
* evidence/source labels

## 5.4 Human analyst endpoints

```text
POST /api/analyst/log
GET /api/analyst/logs?match_id=1
POST /api/analyst/postgame-review
GET /api/analyst/profile/{analyst}
```

For MVP, write to CSV. No database yet.

---

# 6. Intelligence Desk Upgrade

Update `app/intelligence.py`.

Current routing handles:

* team profile
* head-to-head
* match forecast
* venue weather
* live state
* team shortlist

Add new routing keywords:

```python
if any(word in lowered for word in ("manager", "coach", "tactic", "formation", "press", "build up", "low block", "counter")):
    tools.append("manager_skill")

if any(word in lowered for word in ("matchup", "vs", "winger", "fullback", "midfield", "duel", "overload")):
    tools.append("matchup_analysis")

if any(word in lowered for word in ("player", "injury", "availability", "starter", "lineup", "role")):
    tools.append("player_profile")

if any(word in lowered for word in ("kevin", "analyst", "prediction log", "my prediction", "friend")):
    tools.append("analyst_journal")
```

Add new tool handlers:

* `manager_skill`
* `player_profile`
* `matchup_analysis`
* `analyst_journal`

The Intelligence Desk should be able to answer:

```text
Why does France have a tactical edge over Brazil?
What would Deschamps likely do if France leads after 60?
Which matchup matters most in England vs Croatia?
Is Saka favored against the opponent LB?
What did Kevin predict before the match?
How accurate has Kevin been on key matchup calls?
```

---

# 7. Frontend Upgrade

Update `app/static/index.html`, `app/static/app.js`, and `app/static/styles.css`.

Add a new page/panel:

```text
Tactical Lab
```

Sections:

1. Select Match
2. Manager Plan A vs Manager Plan B
3. Projected Lineups
4. Key Matchups
5. Tactical Brief
6. Human Prediction Log
7. Post-Game Review

MVP UI does not need to be beautiful. It just needs to expose the new backend.

Frontend flow:

```text
User selects Team A and Team B
Click "Generate Tactical Brief"
Frontend calls POST /api/tactics/brief
Render:
- model favorite
- expected score
- manager plans
- top 5 matchup edges
- tactical summary
- risks
```

Add simple form for prediction logs:

* analyst name
* predicted score
* confidence
* key matchup
* team A plan
* team B plan
* free text

---

# 8. MVP Implementation Order for Codex

## Phase 1: Tactical schemas and manager data

Tasks:

1. Create `app/tactics/`.
2. Create `schemas.py` with manager-focused schemas, including a small typed `MatchContext`.
3. Create sample `data/managers.csv`.
4. Create 3 sample manager skills:

   * France
   * Argentina
   * England
5. Mark sample manager rules as manual prototypes unless evidence sources are supplied.

Acceptance criteria:

* `python -m compileall app scripts` passes.
* Manager CSV and JSON files validate through the Pydantic schemas.
* Missing manager files are represented honestly and do not crash plan generation.
* Malformed manager files fail clearly in automated tests.

## Phase 2: Manager skill loader

Tasks:

1. Implement `manager_skills.py`.
2. Load manager JSON files.
3. Map team to manager.
4. Evaluate a limited vocabulary of transparent condition codes.
5. Generate a basic manager plan with applied and contingent rules.
6. Add automated tests and a script-level smoke demonstration.

Acceptance criteria:

* `load_team_manager_skill("France")` returns a manager skill.
* `generate_manager_plan("France", "Brazil")` returns structured plan.
* A supplied `MatchContext` triggers only matching decision rules.
* Missing manager returns a clear neutral fallback plan.
* No manager plan changes the existing model prediction or expected goals.

## Phase 3: Player profile loader

Tasks:

1. Implement `player_profiles.py`.
2. Load player profiles.
3. Load projected lineups.
4. Load availability.
5. Add role-depth summary.

Acceptance criteria:

* `get_team_role_depth("England")` works.
* `load_projected_lineup("England")` returns players.
* injured/unavailable players are marked.

## Phase 4: Matchup engine

Tasks:

1. Implement transparent scoring functions.
2. Build top matchup edges.
3. Start with simple role-slot mapping:

   * LW vs RB
   * RW vs LB
   * CF vs CB
   * midfield trio vs midfield trio
4. Return ranked matchup edges.

Acceptance criteria:

* `build_matchup_edges("England", "France")` returns at least 3 edges.
* Each edge has favored team, ranking score, qualitative label, reason, relevant features, lineup assumptions, and data quality.
* No LLM required.

## Phase 5: Tactical brief

Tasks:

1. Implement `tactical_brief.py`.
2. Reuse existing match forecast logic from `predict_worldcup.py` or existing app helper.
3. Combine:

   * model probabilities
   * expected score
   * manager plans
   * matchup edges
   * player availability
4. Return structured JSON.

Acceptance criteria:

* `generate_tactical_brief("France", "Brazil")` returns one complete object.
* Brief still works if manager skill or player data is missing.
* Brief does not mutate existing model state.
* Brief explains the existing forecast but does not alter probabilities or expected goals.

## Phase 6: API endpoints

Tasks:

1. Add Pydantic request models to `app/main.py`.
2. Add:

   * `GET /api/tactics/managers`
   * `GET /api/tactics/manager/{team}`
   * `POST /api/tactics/matchups`
   * `POST /api/tactics/brief`
3. Keep endpoint code thin. Put logic in `app/tactics/`.

Acceptance criteria:

* FastAPI starts.
* API docs show new endpoints.
* `curl` examples work.

## Phase 7: Intelligence Desk routing

Tasks:

1. Update routing in `app/intelligence.py`.
2. Add tactical tools to local answer.
3. Let tactical evidence appear in the agent trace.

Acceptance criteria:

* Asking "What matchup matters most in France vs Brazil?" routes to matchup analysis.
* Asking "What would Deschamps do if France leads?" routes to manager skill.
* Existing Intelligence Desk behavior does not regress.

## Phase 8: Analyst journal

Tasks:

1. Implement `analyst_journal.py`.
2. Add CSV append/read helpers.
3. Add prediction-log API.
4. Add post-game-review API.
5. Add analyst profile summary.

Acceptance criteria:

* Kevin can submit a pre-game prediction.
* Prediction is saved append-only with timestamp and model/data version metadata when available.
* Post-game review can be attached.
* Post-game review does not overwrite the original prediction.
* Analyst profile computes simple accuracy metrics.

## Phase 9: Frontend Tactical Lab

Tasks:

1. Add Tactical Lab section.
2. Add team selectors.
3. Add "Generate Tactical Brief" button.
4. Render manager plans and matchup edges.
5. Add prediction log form.

Acceptance criteria:

* User can generate a tactical brief in browser.
* User can submit prediction log.
* Existing simulation UI still works.

---

# 9. Important Engineering Rules

## Rule 1: Do not rewrite the existing model

The current simulator and RF model are already useful. The tactical layer should call them.

## Rule 2: No fake 22-player LLM roleplay

Do not simulate a match by asking 22 LLM agents to roleplay. That will look cool but produce unreliable nonsense.

Correct architecture:

```text
LLM / RAG = explanation and synthesis
Rules/models = scoring and evaluation
CSV/data = source of truth
```

## Rule 3: Keep player profiles data-driven

Players are not "skills." Players are structured profiles.

Manager = skill.
Player = data object.
Matchup = computed relationship.

## Rule 4: Make everything inspectable

Every tactical recommendation should include:

* reason
* source
* confidence meaning
* relevant player/team features
* applied or contingent rule status
* fallback note if data is missing

## Rule 5: Evaluation matters

The most important differentiator is not the prediction itself. It is the feedback loop.

Every pre-game prediction should later be reviewed:

* right/wrong
* why
* what rule should change

This is how Kevin/friends can later be distilled into analyst agents.

## Rule 6: Model uncertainty honestly

Manager plans and player matchups are conditional hypotheses. Do not present a single plan or matchup edge as certain when lineups, formations, roles, or manager behavior are uncertain.

For manager plans:

* Separate base identity from rules triggered by the supplied match context.
* Keep untriggered rules visible as contingent possibilities.
* Treat manually curated confidence as evidence confidence, not outcome probability.

For future player matchups:

* Weight matchups by starter probability and projected role.
* Prefer qualitative labels such as slight, moderate, or strong until edge scores are evaluated.
* Preserve the features and assumptions that produced every edge.

---

# 10. Suggested First Codex Prompt

Use this as the first prompt to Codex:

```text
You are working in the existing KaiwenMo1/worldcup2026 repository. Do not rewrite the existing tournament simulator, Random Forest predictor, FastAPI app, or Intelligence Desk. Add a new tactical subsystem for manager-skill and player-matchup analysis.

Implement Phase 1 and Phase 2 only:

1. Create app/tactics/ with __init__.py, schemas.py, and manager_skills.py.
2. Create data/managers.csv.
3. Create data/manager_skills/ with three sample manager-skill JSON files for France, Argentina, and England.
4. In schemas.py, define simple Pydantic models for:
   - EvidenceReference
   - MatchContext
   - ManagerSkill
   - DecisionRule
   - SubstitutionPattern
   - ManagerPlan
   - TacticalIdentity
5. In manager_skills.py, implement:
   - load_manager_skill(manager_id) -> ManagerSkill | None
   - list_manager_skills()
   - load_team_manager_skill(team) -> ManagerSkill | None
   - evaluate_decision_rules(manager_skill, match_context)
   - generate_manager_plan(team, opponent, match_context=None) -> ManagerPlan
6. Use a small supported vocabulary of structured condition codes. Do not treat free-form condition text as executable logic.
7. Keep the manager plan rule-based and transparent. It must return:
   - base tactical identity
   - applied rules
   - contingent rules
   - evidence confidence and its meaning
   - source references
   - data-quality status
   - fallback status and note
8. Add tests/test_manager_skills.py covering:
   - manager JSON schema validation
   - France manager lookup
   - decision-rule triggering from MatchContext
   - missing manager fallback plan
   - malformed manager data failing clearly
9. Add a lightweight smoke script scripts/test_manager_skills.py that prints the France manager plan against Brazil.
10. Ensure:
   - python -m unittest discover -s tests -v passes
   - python -m compileall app scripts tests passes

Important:
- Keep all new code additive.
- Do not modify existing prediction behavior.
- Manager skills are versioned tactical hypotheses, not objective facts.
- Mark manually curated rules as manual_prototype unless evidence sources are supplied.
- Loader functions return None for missing manager data; generate_manager_plan returns a valid neutral fallback plan.
- Missing manager files should not crash.
- Existing malformed manager files should fail clearly during validation and tests.
- No external API calls and no LLM calls.
```

---

# 11. Suggested Second Codex Prompt

```text
Continue the tactical subsystem in KaiwenMo1/worldcup2026. Implement Phase 3 and Phase 4 only.

1. Create app/tactics/player_profiles.py and app/tactics/matchup_engine.py.
2. Create sample data/player_profiles.csv, data/projected_lineups.csv, and data/player_availability.csv.
3. Use simple transparent scoring, not ML yet.
4. Implement player loading functions:
   - load_player_profiles()
   - load_projected_lineup(team, match_id=None)
   - load_player_availability()
   - get_team_role_depth(team)
5. Implement matchup functions:
   - build_matchup_edges(team_a, team_b, match_id=None)
   - score_winger_vs_fullback(attacker, defender)
   - score_striker_vs_centerbacks(striker, centerbacks)
   - score_midfield_control(midfield_a, midfield_b)
   - score_set_piece_edge(team_a, team_b)
   - score_transition_risk(team_a, team_b)
6. Return matchup edges as structured objects with:
   - matchup_type
   - team_a_player
   - team_b_player
   - favored_team
   - edge_score
   - edge_label
   - reason
   - relevant_features
   - lineup_assumptions
   - data_quality
7. Add scripts/test_matchups.py that prints top matchup edges for France vs Brazil.
8. Do not change existing simulator behavior.

Important:
- Treat edge_score as a transparent ranking score, not a calibrated probability.
- Weight or label uncertain matchups using starter probability and projected role.
- Reuse existing player-match stats, projected lineups, availability, and tactical profiles where possible.
```

---

# 12. Suggested Third Codex Prompt

```text
Continue the tactical subsystem. Implement Phase 5 and Phase 6 only.

1. Create app/tactics/tactical_brief.py.
2. Add FastAPI endpoints in app/main.py:
   - GET /api/tactics/managers
   - GET /api/tactics/manager/{team}
   - POST /api/tactics/matchups
   - POST /api/tactics/brief
3. The tactical brief should combine:
   - existing match probability / expected score if available
   - manager plan for team A
   - manager plan for team B
   - top matchup edges
   - player availability risks
   - short tactical summary
4. Keep endpoint code thin and put logic in app/tactics/.
5. Add safe fallbacks if data is missing.
6. Add curl examples to README.md.
7. Ensure existing routes still work.

Important:
- The tactical brief may explain the existing forecast but must not alter match probabilities or expected goals in this phase.
- Include source, evidence-confidence meaning, data-quality status, and fallback notes.
- Keep endpoint code thin and preserve all existing API contracts.
```

---

# 13. Suggested Fourth Codex Prompt

```text
Continue the tactical subsystem. Implement the human analyst journal.

1. Create app/tactics/analyst_journal.py.
2. Create data/analyst_prediction_logs.csv and data/postgame_reviews.csv.
3. Add API endpoints:
   - POST /api/analyst/log
   - GET /api/analyst/logs
   - POST /api/analyst/postgame-review
   - GET /api/analyst/profile/{analyst}
4. For MVP, store logs in CSV.
5. Add functions:
   - create_prediction_log()
   - load_prediction_logs()
   - create_postgame_review()
   - summarize_analyst_profile()
6. Analyst profile should calculate:
   - number of predictions
   - winner accuracy
   - score exact accuracy
   - average confidence
   - key matchup accuracy if reviewed
   - tactical accuracy if reviewed
7. Do not require a database.
8. Add a simple frontend form later, but backend first.

Important:
- Prediction logs are append-only and must be created before kickoff.
- Store created_at, kickoff_at, model_version, and data_snapshot_id when available.
- Post-game reviews reference the original log and never rewrite the pre-game prediction.
```

---

# 14. Long-Term Vision

After MVP, expand toward:

1. Real player stats ingestion.
2. Injury/news feed ingestion.
3. Manager skill refinement from public tactical articles and match reports.
4. Actual lineup updates during the tournament.
5. Post-match automatic evaluation using event data.
6. Human analyst skill distillation.
7. Adapting from World Cup to Premier League, Champions League, NBA, or American football.

Final product positioning:

```text
A World Cup tactical intelligence system that combines machine-learning match prediction, manager-skill distillation, player role profiles, matchup analysis, and human analyst feedback loops.
```

This is much stronger than "a soccer chatbot" or "a basic match predictor."
