# WorldCup2026 Upgrade Roadmap: Kevin Agent, Model Arena, Prediction Ledger, and Anti-Hallucination Forecasting

## Purpose

This document adds an upgrade layer to the existing WorldCup2026 project.

Do not repeat or rebuild the existing MVP components:

* tournament simulator
* ML match predictor
* manager skills
* player profiles
* matchup engine
* tactical brief
* injury/player/lineup roadmap
* post-match event evaluation roadmap

This upgrade focuses only on the mechanism inspired by the video/site:

1. Multi-model prediction arena.
2. Kevin Agent: bold football intuition agent.
3. Expert-vs-Kevin-vs-Skeptic comparison.
4. Prediction target separation: 90 minutes, extra time, penalties, qualification.
5. Public pre-match prediction ledger.
6. Virtual-pick scoreboard for entertainment only.
7. Anti-hallucination and anti-cascade rules.
8. Scoreline/upset calibration.
9. Fun, readable match reports that improve viewing experience.

Important guardrail:

The system must clearly label outputs as technical/entertainment predictions. It must not present anything as betting advice, financial advice, guaranteed picks, or real-money betting strategy.

---

# 1. Upgrade Architecture

Add these new modules:

```text
app/
  prediction_arena/
    __init__.py
    schemas.py
    model_clients.py
    prompt_contracts.py
    prediction_runner.py
    arena_aggregator.py
    public_ledger.py
    virtual_scoreboard.py
    risk_guardrails.py

  agents/
    __init__.py
    schemas.py
    expert_agent.py
    kevin_agent.py
    upset_agent.py
    skeptic_agent.py
    final_forecast_agent.py

  calibration/
    __init__.py
    scoreline_calibration.py
    upset_calibration.py
    prediction_target_calibration.py
    agent_performance_tracker.py

  simulation/
    __init__.py
    hypothetical_event_quarantine.py
    game_state_branching.py

data/
  prediction_arena/
    prompts/
      expert_agent_prompt.md
      kevin_agent_prompt.md
      upset_agent_prompt.md
      skeptic_agent_prompt.md
      final_forecast_prompt.md

    ledgers/
      pre_match_predictions.csv
      model_predictions.csv
      public_prediction_cards.csv
      virtual_pick_results.csv

    calibration/
      scoreline_bias_report.csv
      upset_bias_report.csv
      agent_performance.csv

scripts/
  run_prediction_arena.py
  publish_prediction_card.py
  settle_virtual_results.py
  evaluate_arena_predictions.py
  test_prediction_arena.py
```

Core flow:

```text
Existing match forecast + tactical brief
        ↓
Expert Agent
        ↓
Kevin Agent
        ↓
Upset Agent
        ↓
Skeptic Agent
        ↓
Final Forecast Agent
        ↓
Prediction Ledger
        ↓
Virtual Scoreboard
        ↓
Post-match evaluation
```

---

# 2. Prediction Target Separation

Every prediction must distinguish:

```text
1. 90-minute result
2. after-extra-time result
3. qualification / who advances
4. penalty shootout probability
5. exact-score candidates
```

This is mandatory because knockout football can have different meanings of “win.”

Example output:

```json
{
  "match": "France vs Brazil",
  "prediction_target": {
    "regular_time_90": {
      "pick": "Draw",
      "score": "1-1",
      "confidence": 0.42
    },
    "after_extra_time": {
      "pick": "France",
      "score": "2-1",
      "confidence": 0.36
    },
    "qualification": {
      "pick": "France advance",
      "confidence": 0.58
    },
    "penalty_shootout_probability": 0.22
  }
}
```

Rules:

```text
- Never output only “Team A wins.”
- Always clarify whether the prediction refers to 90 minutes or qualification.
- For group-stage matches, extra time and penalties should be null.
- For knockout matches, qualification must be included.
```

---

# 3. Kevin Agent

## Goal

Kevin Agent is the bold intuition agent.

It should avoid over-explaining. It should identify the one or two decisive variables that could define the match.

Kevin Agent is not a fake expert. It is a high-conviction football intuition layer.

## Kevin Agent output schema

```json
{
  "agent_name": "Kevin Agent",
  "bold_pick": "France 2-1 Brazil",
  "core_reason": "France can repeatedly attack Brazil's right side in transition.",
  "one_decisive_matchup": "France LW vs Brazil RB",
  "upset_path": "Brazil wins if France cannot escape midfield pressure and concedes first.",
  "most_fragile_assumption": "France's left winger must start and be fully fit.",
  "what_would_make_me_wrong": [
    "Brazil starts a defensive right back",
    "France winger is minutes-limited",
    "Brazil scores first from a set piece"
  ],
  "confidence": 0.61,
  "tone": "bold_but_uncertain"
}
```

## Kevin Agent rules

```text
- Make a clear call.
- Do not list more than 3 main reasons.
- Must include one decisive matchup.
- Must include what would make the prediction wrong.
- Must include fragile assumptions.
- Must not use betting language.
- Must not pretend uncertainty is gone.
```

Bad Kevin Agent:

```text
France has better xG, better players, better coach, better form, better possession, better passing, better defense...
```

Good Kevin Agent:

```text
This match probably turns on France's left-side isolation. If Brazil's RB gets no help, France can create the best chances. If Brazil protects that side and forces France central, the game becomes much closer.
```

---

# 4. Expert Agent

## Goal

Expert Agent is the rigorous tactical analyst.

It should use existing project outputs:

* match model forecast
* tactical brief
* manager skills
* player matchup edges
* lineup status
* injury/fatigue/weather/travel context if available

## Expert Agent output schema

```json
{
  "agent_name": "Expert Agent",
  "expected_match_shape": "France lower possession but higher transition threat",
  "tactical_forecast": {
    "team_a_plan": "...",
    "team_b_plan": "..."
  },
  "key_matchups": [
    {
      "matchup": "France LW vs Brazil RB",
      "favored_team": "France",
      "edge_score": 0.67,
      "reason": "..."
    }
  ],
  "risk_factors": [
    "France's transition plan weakens if Brazil scores first."
  ],
  "score_prediction_90": "1-1",
  "qualification_prediction": "France advance",
  "confidence": 0.56
}
```

## Expert Agent rules

```text
- Be rigorous but do not assume every tactical plan works.
- Must include execution risk.
- Must not turn possible events into facts.
- Must include uncertainty.
- Must separate 90-minute result from qualification.
```

---

# 5. Upset Agent

## Goal

The Upset Agent prevents strong-team bias.

It must explicitly search for the underdog win/draw path.

## Upset Agent output schema

```json
{
  "agent_name": "Upset Agent",
  "underdog": "Brazil",
  "upset_path": "Brazil slows the game, survives early pressure, wins through set pieces or transition.",
  "required_conditions": [
    "Brazil does not concede first",
    "Brazil's RB survives isolation",
    "Brazil creates at least 0.4 xG from set pieces"
  ],
  "upset_probability_adjustment": 0.07,
  "warning_signs": [
    "Favorite missing starting fullback",
    "Favorite overcommits both fullbacks",
    "Underdog starts extra defensive midfielder"
  ],
  "confidence": 0.48
}
```

## Upset Agent rules

```text
- Always create a plausible underdog path.
- Do not force an upset if the evidence is weak.
- Focus on football mechanisms: set pieces, injuries, weak fullbacks, goalkeeper variance, cards, fatigue, low block, counterattack.
- Must say what must happen for the upset.
```

---

# 6. Skeptic Agent

## Goal

Skeptic Agent attacks weak assumptions.

It should prevent the system from becoming overconfident, self-confirming, or fake precise.

## Skeptic Agent output schema

```json
{
  "agent_name": "Skeptic Agent",
  "unsupported_assumptions": [
    "Assumes Brazil RB will start without confirmed lineup."
  ],
  "fake_precision_warnings": [
    "Exact 2-1 score has low certainty; should present alternatives."
  ],
  "cascade_warnings": [
    "A possible yellow card was treated as if already observed."
  ],
  "target_confusion_warnings": [
    "Expert Agent predicted France win but did not clarify 90-min vs qualification."
  ],
  "missing_data": [
    "Confirmed lineup unavailable",
    "Recent injury status unavailable"
  ],
  "recommended_downgrades": [
    {
      "field": "France left-side edge",
      "old_confidence": 0.72,
      "new_confidence": 0.58,
      "reason": "depends on unconfirmed opponent RB"
    }
  ],
  "overall_risk_level": "medium"
}
```

## Skeptic Agent rules

```text
- Never produce the final prediction.
- Only critique.
- Identify hallucination risk.
- Identify target ambiguity.
- Identify missing data.
- Identify simulated-event cascade errors.
```

---

# 7. Hypothetical Event Quarantine

## Goal

Prevent the most dangerous simulation failure:

```text
The model imagines an event.
Then it treats that imagined event as real.
Then the entire second-half prediction cascades from it.
```

## Required schema

```python
class SimulatedEvent:
    event_type: str
    team: str | None
    player: str | None
    minute_range: str | None
    probability: float
    is_observed: bool
    allowed_to_cascade: bool
    impact_if_occurs: str
    reasoning_note: str
```

## Rule

```text
If is_observed is false, allowed_to_cascade must default to false.
```

Example:

```json
{
  "event_type": "yellow_card",
  "player": "Opponent LB",
  "minute_range": "0-30",
  "probability": 0.24,
  "is_observed": false,
  "allowed_to_cascade": false,
  "impact_if_occurs": "If it happens, winger isolation edge increases.",
  "reasoning_note": "This is a branch, not a fact."
}
```

The Final Forecast Agent may say:

```text
If the LB gets an early yellow, France's left-side edge rises.
```

It must not say:

```text
The LB gets a yellow, so France will dominate that side.
```

---

# 8. Final Forecast Agent

## Goal

Aggregate all views into one clear public prediction.

Inputs:

* base ML forecast
* existing tactical brief
* Expert Agent output
* Kevin Agent output
* Upset Agent output
* Skeptic Agent critique
* calibration reports

Output:

```json
{
  "match": "France vs Brazil",
  "final_prediction": {
    "regular_time_90": {
      "pick": "Draw",
      "score": "1-1",
      "confidence": 0.41
    },
    "qualification": {
      "pick": "France advance",
      "confidence": 0.57
    },
    "penalty_shootout_probability": 0.22
  },
  "top_reasons": [
    "France has the clearer transition path.",
    "Brazil's upset path is real if they protect the right side and create from set pieces.",
    "Confirmed lineups could materially change the left-side matchup."
  ],
  "fragile_assumptions": [
    "France's starting LW is fully fit.",
    "Brazil starts an attack-minded RB.",
    "No early red card or penalty swings the match."
  ],
  "what_to_watch": [
    "France LW vs Brazil RB",
    "Brazil set pieces",
    "First 20 minutes of France's transition defense"
  ],
  "entertainment_disclaimer": "This is a technical/entertainment prediction, not betting advice."
}
```

Rules:

```text
- Must include entertainment disclaimer.
- Must include fragile assumptions.
- Must include what-to-watch list.
- Must include 90-min vs qualification distinction.
- Must not use real-money betting recommendations.
```

---

# 9. Prediction Ledger

## Goal

Every prediction must be saved before the match.

This prevents retroactive editing and makes evaluation meaningful.

## File: `data/prediction_arena/ledgers/pre_match_predictions.csv`

Schema:

```csv
prediction_id,match_id,created_at,team_a,team_b,stage,agent_name,regular_time_pick,regular_time_score,qualification_pick,penalty_probability,confidence,core_reason,fragile_assumptions,public_card_path,status
```

Status values:

```text
draft
locked
published
settled
evaluated
```

Rules:

```text
- Once status is locked or published, do not overwrite.
- Corrections must create a new version.
- Actual lineup updates should create a new prediction version labeled post_lineup.
```

---

# 10. Public Prediction Card

## Goal

Create a readable prediction card for fans.

Do not expose huge JSON by default.

Public card should show:

```text
Match
90-min prediction
Qualification prediction
Kevin Agent bold take
Expert Agent tactical reason
Upset path
Fragile assumptions
What to watch
Entertainment disclaimer
```

Example markdown:

```markdown
# France vs Brazil Prediction Card

## Final Call
90 minutes: 1-1 draw  
Qualification: France advance  
Penalty chance: 22%

## Kevin Agent
This game probably turns on France's left-side isolation. If Brazil's RB gets no help, France can create the best chances.

## Expert View
France's transition threat is stronger, but Brazil can reduce it by slowing tempo and protecting wide zones.

## Upset Path
Brazil wins if they survive the first 25 minutes, win set pieces, and force France into slow possession.

## Fragile Assumptions
- France LW starts and is fit.
- Brazil starts an attack-minded RB.
- No early red card changes the game.

This is a technical/entertainment prediction, not betting advice.
```

---

# 11. Virtual Scoreboard

## Goal

Build a fun model battle without real-money betting.

Track virtual points only.

## File: `data/prediction_arena/ledgers/virtual_pick_results.csv`

Schema:

```csv
result_id,prediction_id,match_id,agent_name,regular_time_pick,actual_regular_time_result,qualification_pick,actual_qualification_result,score_pick,actual_score,winner_points,score_points,qualification_points,total_points,settled_at
```

Suggested scoring:

```text
Correct 90-min W/D/L: +3
Correct exact 90-min score: +5
Correct qualification: +2
Correct upset call: +2 bonus
Wrong high-confidence pick: -1
```

Rules:

```text
- Use points, not money.
- Do not call this betting.
- Do not include stake, odds, profit, ROI, bankroll, or payout.
```

Frontend leaderboard:

```text
Agent              Points
Kevin Agent        18
Expert Agent       15
Base ML Model      13
Upset Agent        10
Final Forecast     21
```

---

# 12. Scoreline and Upset Calibration

## Goal

Avoid these common failure modes:

```text
- Always picking strong teams.
- Always predicting 1-0, 1-1, 2-1.
- Missing blowouts.
- Missing underdog paths.
- Being overconfident in exact scores.
```

## File: `app/calibration/scoreline_calibration.py`

Outputs:

```json
{
  "overpredicted_scores": ["1-1", "1-0"],
  "underpredicted_patterns": ["3+ goal favorite wins", "underdog wins"],
  "agent_biases": {
    "Expert Agent": ["too conservative", "too many draws"],
    "Kevin Agent": ["higher upset sensitivity"],
    "Final Forecast": ["well calibrated"]
  }
}
```

## Calibration rules

```text
- Track predicted vs actual after every match.
- Warn if an agent predicts too many draws.
- Warn if an agent never picks underdogs.
- Warn if an agent's confidence is not correlated with accuracy.
```

---

# 13. API Additions

Add these endpoints:

```text
POST /api/prediction-arena/run
GET  /api/prediction-arena/match/{match_id}
POST /api/prediction-arena/lock
POST /api/prediction-arena/publish-card
POST /api/prediction-arena/settle
GET  /api/prediction-arena/leaderboard
GET  /api/prediction-arena/calibration
```

## `/api/prediction-arena/run`

Request:

```json
{
  "match_id": "M001",
  "team_a": "France",
  "team_b": "Brazil",
  "stage": "knockout",
  "include_public_card": true
}
```

Response:

```json
{
  "base_model": {},
  "expert_agent": {},
  "kevin_agent": {},
  "upset_agent": {},
  "skeptic_agent": {},
  "final_forecast": {},
  "public_card": {}
}
```

---

# 14. Frontend Additions

Add a new tab:

```text
Prediction Arena
```

Sections:

```text
1. Match selector
2. Run Prediction Arena button
3. Agent Battle panel
4. Final Forecast card
5. Fragile assumptions panel
6. What to watch panel
7. Public prediction ledger
8. Virtual leaderboard
9. Calibration/bias report
```

Agent Battle layout:

```text
Base ML Model       probability table
Expert Agent        tactical forecast
Kevin Agent         bold intuition call
Upset Agent         underdog path
Skeptic Agent       warnings
Final Forecast      final public prediction
```

---

# 15. Codex Prompt 1: Add Prediction Arena Skeleton

```text
You are working in the existing KaiwenMo1/worldcup2026 repository.

Add the Prediction Arena skeleton only. Do not modify the existing match predictor, tournament simulator, manager skills, player profiles, or tactical brief logic.

Create:

app/prediction_arena/
  __init__.py
  schemas.py
  risk_guardrails.py
  public_ledger.py
  virtual_scoreboard.py

app/agents/
  __init__.py
  schemas.py

data/prediction_arena/
  ledgers/
    pre_match_predictions.csv
    model_predictions.csv
    public_prediction_cards.csv
    virtual_pick_results.csv

scripts/
  test_prediction_arena_skeleton.py

Requirements:

1. Define schemas for:
   - PredictionTarget
   - AgentPrediction
   - KevinAgentPrediction
   - ExpertAgentPrediction
   - UpsetAgentPrediction
   - SkepticReview
   - FinalForecast
   - PublicPredictionCard
   - VirtualPickResult

2. PredictionTarget must distinguish:
   - regular_time_90
   - after_extra_time
   - qualification
   - penalty_shootout_probability

3. Add guardrail helper:
   - ensure_entertainment_disclaimer(text_or_obj)
   - reject_betting_advice_language(text_or_obj)

4. Disallowed terms in recommendation contexts:
   - stake
   - bankroll
   - guaranteed profit
   - risk-free
   - lock bet
   - arbitrage
   - sure bet

5. Ledger functions:
   - append_prediction_record()
   - load_predictions()
   - lock_prediction()
   - prevent_overwrite_locked_prediction()

6. Virtual scoreboard functions:
   - settle_virtual_pick()
   - compute_leaderboard()

7. Use CSV storage only.
8. Missing files should be created automatically.
9. Ensure python -m compileall app scripts passes.
```

---

# 16. Codex Prompt 2: Implement Kevin Agent, Expert Agent, Upset Agent, Skeptic Agent

```text
Continue the Prediction Arena upgrade.

Create:

app/agents/
  expert_agent.py
  kevin_agent.py
  upset_agent.py
  skeptic_agent.py

data/prediction_arena/prompts/
  expert_agent_prompt.md
  kevin_agent_prompt.md
  upset_agent_prompt.md
  skeptic_agent_prompt.md

scripts/
  test_agents.py

Requirements:

1. Expert Agent:
   - consumes existing match forecast and tactical brief if available
   - outputs tactical forecast, key matchups, execution risks, score prediction, confidence
   - must separate 90-minute result from qualification

2. Kevin Agent:
   - produces a bold, simple, decisive football intuition call
   - output fields:
     bold_pick
     core_reason
     one_decisive_matchup
     upset_path
     most_fragile_assumption
     what_would_make_me_wrong
     confidence
   - must not list more than 3 main reasons
   - must include uncertainty

3. Upset Agent:
   - explicitly searches for the underdog path
   - considers injuries, weak fullbacks, set pieces, goalkeeper variance, low block, counterattack, fatigue, weather, knockout pressure
   - outputs required_conditions and warning_signs

4. Skeptic Agent:
   - critiques Expert, Kevin, and Upset outputs
   - flags unsupported assumptions, fake precision, target confusion, missing data, and cascade risk
   - does not produce final prediction

5. No external LLM API calls yet.
   Implement deterministic/template-based outputs from available structured inputs.
   Leave clear adapter interfaces for future LLM providers.

6. Every output must include entertainment/technical disclaimer metadata.

7. Add script that runs all four agents on a sample match and prints their outputs.

8. Ensure python -m compileall app scripts passes.
```

---

# 17. Codex Prompt 3: Add Hypothetical Event Quarantine

```text
Continue the Prediction Arena upgrade.

Create:

app/simulation/
  __init__.py
  hypothetical_event_quarantine.py
  game_state_branching.py

scripts/
  test_hypothetical_event_quarantine.py

Requirements:

1. Define SimulatedEvent schema:
   - event_type
   - team
   - player
   - minute_range
   - probability
   - is_observed
   - allowed_to_cascade
   - impact_if_occurs
   - reasoning_note

2. Default rule:
   If is_observed is false, allowed_to_cascade must be false.

3. Define GameStatePath:
   - path_id
   - description
   - probability
   - simulated_events
   - tactical_implications
   - score_implications

4. Add validation function:
   validate_no_unobserved_event_cascade(prediction_obj)

5. If an agent treats an unobserved simulated event as fact, return a Skeptic warning.

6. Add examples:
   - early yellow card branch
   - red card branch
   - penalty branch
   - goalkeeper mistake branch

7. Do not let simulated events modify the main prediction unless explicitly represented as a branch.

8. Ensure python -m compileall app scripts passes.
```

---

# 18. Codex Prompt 4: Implement Final Forecast Aggregator

```text
Continue the Prediction Arena upgrade.

Create:

app/agents/final_forecast_agent.py
app/prediction_arena/arena_aggregator.py
scripts/test_final_forecast.py

Requirements:

1. Final Forecast Agent consumes:
   - base model forecast if available
   - existing tactical brief if available
   - Expert Agent output
   - Kevin Agent output
   - Upset Agent output
   - Skeptic Agent output
   - calibration warnings if available

2. Output:
   - regular_time_90 pick
   - regular_time_90 score candidates
   - qualification pick
   - after_extra_time pick if knockout
   - penalty_shootout_probability if knockout
   - final confidence
   - top reasons
   - fragile assumptions
   - what to watch
   - entertainment disclaimer

3. Aggregation logic:
   - start from base model probability
   - adjust slightly if Expert and Kevin agree
   - increase upset warning if Upset Agent has strong required_conditions and Skeptic does not reject them
   - reduce confidence if Skeptic flags target confusion, missing lineups, injury uncertainty, or unobserved-event cascade
   - never output certainty above 0.75 for football match prediction unless actual result is already known

4. Must separate 90-minute result from qualification.

5. Must not use betting advice language.

6. Add tests for:
   - group-stage match
   - knockout match
   - missing lineup data
   - Kevin and Expert disagree
   - Skeptic downgrades confidence

7. Ensure python -m compileall app scripts passes.
```

---

# 19. Codex Prompt 5: Prediction Ledger and Public Cards

```text
Continue the Prediction Arena upgrade.

Create:

app/prediction_arena/prediction_runner.py
app/prediction_arena/public_card_renderer.py
scripts/run_prediction_arena.py
scripts/publish_prediction_card.py

Requirements:

1. run_prediction_arena.py should accept:
   --match-id
   --team-a
   --team-b
   --stage group|knockout
   --lock
   --publish-card

2. It should run:
   - base model forecast if available
   - tactical brief if available
   - Expert Agent
   - Kevin Agent
   - Upset Agent
   - Skeptic Agent
   - Final Forecast Agent

3. Save all outputs to:
   data/prediction_arena/ledgers/pre_match_predictions.csv
   data/prediction_arena/ledgers/model_predictions.csv

4. Public card renderer should create markdown cards under:
   data/prediction_arena/cards/{match_id}.md

5. Public card must include:
   - match
   - final 90-min prediction
   - qualification prediction if knockout
   - Kevin Agent bold take
   - Expert Agent view
   - Upset path
   - fragile assumptions
   - what to watch
   - entertainment disclaimer

6. If --lock is passed, prediction cannot be overwritten.
   A new version must be created instead.

7. Ensure python -m compileall app scripts passes.
```

---

# 20. Codex Prompt 6: Virtual Scoreboard and Agent Battle

```text
Continue the Prediction Arena upgrade.

Implement virtual entertainment-only scoring.

Create or update:

app/prediction_arena/virtual_scoreboard.py
scripts/settle_virtual_results.py
scripts/evaluate_arena_predictions.py

Requirements:

1. settle_virtual_results.py accepts:
   --match-id
   --actual-score
   --regular-time-result
   --qualification-result optional

2. Scoring:
   - correct 90-min W/D/L: +3
   - correct exact 90-min score: +5
   - correct qualification: +2
   - correct upset call: +2 bonus
   - wrong high-confidence pick above 0.65: -1

3. Store results in:
   data/prediction_arena/ledgers/virtual_pick_results.csv

4. compute_leaderboard() returns:
   - agent name
   - matches predicted
   - total points
   - winner accuracy
   - exact score hits
   - qualification accuracy
   - average confidence
   - calibration warning

5. Must not use money, stake, odds, payout, bankroll, profit, ROI, or betting terminology.

6. Add test data and a test script.

7. Ensure python -m compileall app scripts passes.
```

---

# 21. Codex Prompt 7: Scoreline and Upset Calibration

```text
Continue the Prediction Arena upgrade.

Create:

app/calibration/
  __init__.py
  scoreline_calibration.py
  upset_calibration.py
  prediction_target_calibration.py
  agent_performance_tracker.py

scripts/test_prediction_calibration.py

Requirements:

1. Scoreline calibration:
   - detect if an agent overpredicts 0-0, 1-0, 1-1, 2-1
   - detect if an agent underpredicts 3+ goal games
   - detect if exact score confidence is too high

2. Upset calibration:
   - detect if an agent never picks underdogs
   - detect if an agent overpicks underdogs
   - track underdog-path quality separately from actual upset outcome

3. Prediction target calibration:
   - detect confusion between 90-min result and qualification result
   - flag knockout predictions missing penalty probability

4. Agent performance tracker:
   - aggregate points and accuracy from virtual scoreboard
   - produce warnings:
     too_conservative
     too_favorite_biased
     too_upset_happy
     overconfident
     target_confusion

5. Write reports to:
   data/prediction_arena/calibration/scoreline_bias_report.csv
   data/prediction_arena/calibration/upset_bias_report.csv
   data/prediction_arena/calibration/agent_performance.csv

6. Ensure python -m compileall app scripts passes.
```

---

# 22. Codex Prompt 8: FastAPI and Frontend Integration

```text
Expose the Prediction Arena through FastAPI and the frontend.

Backend endpoints:

POST /api/prediction-arena/run
GET  /api/prediction-arena/match/{match_id}
POST /api/prediction-arena/lock
POST /api/prediction-arena/publish-card
POST /api/prediction-arena/settle
GET  /api/prediction-arena/leaderboard
GET  /api/prediction-arena/calibration

Frontend:

Add a new tab called Prediction Arena.

Sections:
1. Match selector
2. Run Prediction Arena button
3. Agent Battle panel:
   - Base ML Model
   - Expert Agent
   - Kevin Agent
   - Upset Agent
   - Skeptic Agent
   - Final Forecast
4. Public Prediction Card
5. Fragile Assumptions
6. What To Watch
7. Virtual Leaderboard
8. Calibration Warnings

Rules:
- Keep endpoint code thin.
- Put logic inside app/prediction_arena and app/agents.
- Do not break existing pages.
- If data is missing, show warnings instead of crashing.
- Show entertainment disclaimer near every public forecast.
- Do not include real-money betting terminology.
```

---

# 23. Final Upgrade Positioning

After this upgrade, the project becomes:

```text
A World Cup AI Prediction Arena that compares a statistical model, a tactical expert agent, a bold Kevin intuition agent, an upset-hunting agent, and a skeptic judge — then publishes locked pre-match prediction cards and tracks virtual entertainment-only performance.
```

The strongest selling point is not “AI predicts football perfectly.”

The strongest selling point is:

```text
The system shows how different AI reasoning styles disagree, what assumptions each one depends on, and whether those assumptions survived the actual match.
```

This makes the project more fun, more transparent, and much more impressive than a normal match predictor.


Here's the caption from the video, for your comprehension: here is the video that inspires me,i got all its subtitle, based on that, see how i can further improve my ai: ## 口播逐字稿

### ⚽ 挑战不可能：构建AI预测系统的初衷
我搞的足球比赛预测AI成功猜对了欧冠决赛 接下来呢我还会让他继续预测 世界杯期间的每一场比赛 结果全部公开
事情是这样的 去年我们公司内部呢组织了一场AI炒股比赛 我靠着坚定不移的梭哈策略 成功取得了倒数第二的好成绩
但是AI呢也功不可没 而世界杯临近 公司里关于哪个队伍能夺冠的争论也多了起来 甚至说要再搞一次内部的预测比赛
而我呢决定再相信AI一次 看看能不能逆风翻盘 我本人呢只能说是4年一届的伪球迷了 上一场看的比赛还是阿根廷大战法国
那叫一个跌宕起伏 看得我是心潮澎湃 但其实呢也只能看个热闹 球员都认不清
更别提规则和战术了 对足球的理解呢只是停留在哎呦 这个球员跑的真快 但现在不一样了呀
我有了个顶级外挂大语言模型 我不行 他肯定行啊 不过现在世界杯还没开始呢
在世界杯开始之前呢 我先用今年欧冠已经结束了的比赛 摸了摸大模型的底 为了避免网页版对话AI直接调用联网搜索作弊
我选择直接拿API 而不是网页端调用模型 看看他们的真实力 方法呢自然也是简单得很
你是一个超级无敌足球比赛预测AI帮我猜一下 2026年欧冠 巴黎圣日耳曼对切尔西这场比赛的最终比分 16场比赛呢我就这么循环往复
用cloud Gemini g b t 还有deep sick都问了个遍 结果呢很有意思 这几个模型的预测结果几乎没区别
都是16场中十场 为啥呢 因为他们只会预测出传统意义的强队胜出 像加拉塔萨雷战胜利物浦
博德闪耀打爆葡萄牙体育 这种弱队爆冷的比赛呢是一场都没猜对 可赌强队赢谁不会啊 只有爆冷的赔率才高啊
所以我对这个结果呢是相当的不满意 但这其实是我的问题 啥提示词都不设计 啥数据也没有
还不让开联网搜索 那可不就只能靠瞎猜吗 没办法 为了在世界杯一雪前耻
我跟公司的同事们呢说要去法国出差 躲在家里捧着懂球帝和虎扑硬啃了一周 还从我好几个T的学习资料里 翻出了珍藏多年的大数据分析技术
我觉得我强的可怕 于是呢我决定搞一个我专属的AI预测系统 林毅足球专家 足球足球核心呢还是踢球的人

### 📊 深度拆解：球员能力值与战术建模
所以我准备先做个球员能力值的评估系统 这个呢倒是不难 我抓了4万场足球比赛 把这里面每个球员的传球数
传球成功率 射门数 进球数等等45项数据全部清洗出来 放到数据库里
然后呢再根据每个球员最近十场比赛的数据 分别求平均值 得出他近期的竞技状态 每个球员只要把它和数据库里
所有相同位置的球员横向对比 观察每个指标的排名如何 就能大概绘制出它的综合实力分布 拿梅西举例
他的场均进球呢是1.03个 超过了99%的前锋 所以进球这个指标拿到了满分 但他的传球成功率是80%
分数是五分 再看林皇 虽然他黄牌和越位特别多 但他过人和进球少啊
这么一分呢 谁是隐藏SSR 谁又只能是R清清楚楚搞定球员 我又把各个球队的战术风格
教练倾向 还有赛前新闻全抓了个遍 依次拆成独立模块 让AI分别分析和总结
通过这些信息呢 咱们就可以整理出球队赛前的战术倾向 人员伤停 甚至包括更衣室氛围这样的细节
毕竟前段时间呢 皇马巴尔韦德被楚阿梅尼牌桌角一拳 打晕的事还历历在目 接着呢两位模拟双方球队教练的智能体
会 结合这些信息安排各自的首发名单和比赛战术 最后呢我又搞了个专门推演比赛过程的智能体 他会基于比赛的场地天气
教练战术 球员对位信息和他们的个人能力差距 分左右路前中后场竹片区域进行推理 把哪里最有可能被打爆
哪里最有可能会进球全给跑出来 中场休息的时候呢 系统还会给教练一次 基于上半场表现调整战术的机会
虽然整了这么多步骤 看起来挺厉害 但这个专家输出的报告对我来说呢 就有点太专业了
什么高位压迫边路爆破啊 看不懂呢 所以呢我又给专家找了个对照组 给他们的比赛数据都是一样的

### 🤖 专家 vs 直觉：两套AI系统的博弈
但这个对照组的猜测逻辑呢就非常简单了 我就让他用最直白最易懂的词稳稳的接住 我 不需要教练排兵布阵
也不用整什么比赛推演 只需要凭着高深的足球直觉 一口气推测出完整的比赛结果 用最简单的大白话给我讲明白
虽然技术含量要低得多 但第一次运行呢 这个简化版就语出惊人 都说同一个数据集交给无聊的足球专家
他们只会对着数字瑟瑟发抖 一切的客观数据不过都是表象 比赛的结果 从第一脚触球之前就已被我看穿
看完呢我立刻给这个睿智的AI赐名足球加豪 虽然嘉豪弟弟呢只能图一乐 但多个视角终归不是坏事 开发完成
我前后脚把这俩推测模型跑了起来 看着数据收集比赛推理的代码顺利运行 我开始畅享体彩 把把赢一夜暴富之后的人生
可是呢梦境很快破碎了 专家的回测结果出来了 16场居然只对了七场 加上了这么详细的数据
这么专业的流程 这结果怎么比之前纯瞎猜还差呢 我仔细一场场一条条翻了一遍 这16场比赛的推演报告
发现我这个足球专家呢有两个大毛病 首先呢是他特别保守 总觉得哎呀45分钟太短了 比不出来的呀
最后呢就全是小比分 根本拉不开差距 让中国队跟西班牙踢十场 他也觉得五五开
另一个问题呢就是AI常犯的这个讨好型人格 我的推演流程设计的非常详细 结果AI呢就经常自己引导着自己越走越偏 比如巴萨打纽卡的首回合
足球专家上半场推演出刘易斯霍尔会吃黄牌 下半场呢他就觉得哎呀 他吃了黄牌肯定硬不起来了呀 再加上推演里面刘易斯霍尔对位的呢
又是巴萨非常强势的亚马尔 最终结果呢就变成了纽卡被巴萨三比一打爆 可实际上这场比赛刘易斯霍尔不仅没拿黄牌 踢的呢也是相当不错
甚至踢出了五次关键传球 全场最高 纽卡呢也一比一守住了这场比赛 AI呢就因为太爱迎合了
所以稍微一点误判呢 就会像蝴蝶像一样越来越离谱 但就在我心灰意冷的时候呢 电脑右下角弹窗跳了出来

### 🏆 欧冠决战：AI预测与真实的竞技冲突
卧槽差点把嘉豪给忘了 虽然没抱啥希望 但点开一看 卧槽16场中了13场
我直接一个原地起立 当时呢是晚上七点 距离欧冠决赛呢还有五个小时 我也顾不上分析了
马上让嘉豪哥哥帮我推演欧冠决赛三比一 嘉豪断定巴黎会三比一拉爆阿森纳 没有一丝犹豫啊 我飞身下楼找到最近的体彩店
人生第一次买了100块大巴黎圣搞定 回来 比赛还没开始 我把气儿喘匀了之后呢
就开始翻嘉豪的推演记录 嘉豪的思路比较松垮 但AI的优柔寡断 随风倒呢
刚好又弥补了这一部分 就说加拉塔萨雷爆冷利物浦的这场比赛 足球专家这套系统的两个教练智能体 各自准备了一大堆技战术
专业严谨详实 而推演智能体呢 真就认定了这些策略全都能完美实现 这边完美进攻
那边完美防御 破不了招啊 嘉豪这边呢就懒得管那么多 他看完赛前信息
拍脑袋就咬定利物浦的防线缺兵少将 说呢利物浦的右后卫是个雷萨内 就算只剩半条命 也能踩萨内
欧冠大场面经验丰富 就等着抓边后卫前压之后的空档 一字长传就能打穿 虽然松松垮垮
但至少拨开迷雾 大胆下了判断 收获了16中13的恐怖战果 当晚呐4年没看球的我久违的熬夜看了场球
谁想得到啊 开幕雷击阿森纳5分钟就进了一球 那我心态可太稳健了 这不就是三比一的一吗
但大巴黎的帽子戏法呢并没有马上到来 在阿森纳禁区外围一直蹭啊蹭 就是进不去 反倒是阿森纳打了几波快速反击比赛
65分钟 阿森纳的莫斯科拉在禁区铲倒了K77 巴黎获得点球 登贝莱也顺利踢进比分
来到一比一 但后面俩球呢左等右等就是不来 我承认呢 我一度对家好弟弟啊
是有点失望了 最后呢就磨进点球了 结果呢大巴黎还真赢了 卧槽我家豪哥哥真牛逼呀
比赛呢是凌晨三点结束的 觉是一分钟没睡的 天一亮我就冲到体彩店 结果呢他妈的不给兑奖
我说我买的巴黎赢巴黎是不是赢了呀 结果人家店员呢非常耐心 人家就告诉我呢 我买的这个呀是看常规赛90分钟的胜平负
巴黎是点球赢的 这个不算 那我呢那就也没啥可说的了 我不懂规则
这不我该的吗 但是人家嘉豪哥哥猜的也真是大差不差呀 是我执行的问题 回去呢我又仔细看了一遍嘉豪的推演
首发名单几乎完美预判 大巴黎全中只有阿森纳的梅里诺和哲凯赖什 猜错了 比赛事件的预测呢也都八九不离十
嘉豪觉得阿森纳主力右后卫廷贝尔受伤 休养了两个月 替补本怀特又赛季报销 只能拿中后卫出身的青训小孩
莫斯科拉客串右后卫 嘉豪就说呢 莫斯科拉就是这场决赛的祭品 会被反复针对和突破
一个21岁对抗成功率偏低的小将 要打近十场状态火热的K77克瓦拉茨赫利亚 这不虐待吗 结果呢还真是
虽然莫斯科拉也已经非常尽力了 但还是送了个点球 又拿了个黄牌 不然巴黎呢还真可能零比一被阿森纳送走
嘉豪呢还给自己列了个最容易打脸的情况说 如果莫斯科拉超常发挥 或者教练阿尔特塔压根不用他 那K77的单点爆破优势呢就会大打折扣
又或者阿森纳的定位球都超常发挥 效率比预测的高 那比赛走势那就全变了 所以嘉豪虽然看起来狂得很
但心里呢也知道他的那些直觉呀 其实也都依赖几个关键变量的判断 莫斯科拉能不能顶住定位球 进不进黄牌
红牌会不会出这些事 在没发生之前呢 答案永远是未知的 这也正是足球最让人着迷的地方
球赛呢远不是什么大数据分析 AI预测就能说准的 数据和情报呢只能分析出走向 却无法预测临场意外占优的一方呢
可能发挥失常 不被看好的一方呢也有可能爆冷 更别说是欧冠决赛这种强强对决了 大巴黎全场压着打
射门是对手的三倍 控球率是对手的三倍 但90分钟就是赢不下来 而阿森纳摆了120分钟
大巴硬是把比赛拖进了点球 最终呢却又攻功亏一篑 在最不该失误的人身上 我也是啊
输了又赢了 赢了却输了 而这些呢恰恰是足球最迷人的地方 所以结论是啥呢

### 💡 总结反思：理性享受竞技的魅力
嘉豪牛逼呀 为了喜迎今年世界杯 我们打算搞个网站 就用嘉豪这套策略
我们会拿不同的大模型预测每场比赛的结果 下注足彩虚拟盘 搞一波实时大模型大乱斗 这个视频发出来的时候呢
网站上第一轮小组赛的预测结果 应该已经出来了 但是呢大家可千万别跟着买啊 这玩意纯娱乐虚拟盘呢
只是为了让乐子更大一点 我真买了一把 毛都不剩了 别沾钱啊
心态放轻松享受观赛 这才快乐 大家呢可以关注一下GPT加豪 deep sk加豪
cloud加豪 这一个个加豪门的大胆判断 输赢不重要 跟着激情加豪的激情视角
是真的能把观赛体验提升169% 

here is their website take a look and see what mechanism: https://worldcup.lyihub.com/