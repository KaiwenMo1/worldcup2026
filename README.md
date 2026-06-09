# 2026 World Cup Predictor
# make website, adapt to other leagues/ sports
A lightweight, self-contained Python model for simulating the FIFA World Cup 2026 with the expanded 48-team format.

The predictor uses:

- The confirmed 48-team field.
- The 12 groups of four teams.
- A calibrated ensemble of Random Forest, Dixon-Coles, and Elo result probabilities.
- Leakage-safe historical features built only from information available before each match.
- Current squad, tactical, venue, weather, travel, and fatigue inputs as forecast-time scenario adjustments.
- The 2026 qualification rule: top two in every group plus the eight best third-place teams advance to a Round of 32.
- A coherent exact-score distribution whose scores aggregate to the displayed win/draw/loss probabilities.

## Quick Start

```bash
python3 scripts/predict_worldcup.py --sims 20000 --seed 26
```

Useful options:

```bash
python3 scripts/predict_worldcup.py --sims 50000 --team "USA"
python3 scripts/predict_worldcup.py --sims 50000 --save outputs/predictions.csv
python3 scripts/predict_worldcup.py --single
python3 scripts/predict_worldcup.py --match "France" "Brazil"
python3 scripts/predict_worldcup.py --sims 100000 --model models/worldcup_random_forest.joblib
```

For a more stable run, use more simulations:

```bash
python3 scripts/predict_worldcup.py --sims 100000 --seed 26 --save outputs/predictions.csv
```

## Website App

Start the local website:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

The app includes:

- Run Simulation button.
- Forecast ensemble / baseline toggle.
- Champion odds table.
- Full bracket-style tournament path with flags and scores.
- Fixture-aware 104-match schedule layer with match-specific venues, kickoff times, bronze final, and final as match 104.
- Match score predictor.
- Integrated forecast stack showing which inputs actively changed the score prediction.
- Exact-score probability heatmap with score-derived win/draw/loss aggregation.
- Public chronological Model Report with component comparison and calibration chart.
- Final-squad explorer with projected XI, formation, caps, clubs, and market-value depth.
- Normal-time player trait layer with preferred foot, weak-foot usage, tactical role, formation role, shooting, passing, chance creation, progression, dribbling, crossing, pressing, tackling, aerials, discipline, scoring-window, and goalkeeper distribution/dive/sweeper stats.
- Advanced signal layer that feeds availability, confirmed XI, market probability, tactical matchup, set pieces, post-shot goalkeeper quality, referee tendencies, live Bayesian updates, historical weather effects, and 360/freeze-frame shot context into expected goals.
- Shot-level xG lab with location, distance, angle, body part, assist type, pressure, and game-state features.
- Shootout matchup lab with kicker placement preferences, past left/center/right split, goal/save/miss rates, keeper dive tendencies, and score/save/miss probabilities.
- Match confidence, goal-shape insights, and model-driver explanations.
- Champion odds with simulation confidence ranges.
- Automatic match context: venue weather from Open-Meteo when in forecast range, venue climatology fallback, team travel load, rest days, fatigue, and crowd/host support.
- Venue map powered by MapLibre.
- ECharts heatmap and EV charts.
- Agentic RAG Intelligence Desk with local evidence retrieval, tool routing, source citations, and an inspectable agent trace.
- Analyst Brief panel that combines exact-score forecast, squad context, xG danger zones, weather, penalties, evidence, and market disagreement into one traceable matchup read.
- Optional OpenAI-compatible or local-model synthesis for Intelligence Desk answers.
- Group viewer.
- BALLDONTLIE live-state / odds refresh endpoint.
- Optional The Odds API one-time bookmaker snapshot for Market Edge and Analyst Brief.

API routes:

```text
GET  /api/teams
GET  /api/groups
GET  /api/venues
GET  /api/fixtures
GET  /api/venue-weather
GET  /api/advanced-signals
GET  /api/intelligence/status
GET  /api/status
GET  /api/model-report
GET  /api/xg/status
GET  /api/xg/danger
GET  /api/penalties/status
GET  /api/penalties/options
GET  /api/squads
GET  /api/player-match-stats
GET  /api/lineup-status
GET  /api/live-state
POST /api/simulate
POST /api/match
POST /api/xg/predict
POST /api/penalties/matchup
POST /api/intelligence
POST /api/analyst-brief
POST /api/refresh-lineups
POST /api/refresh-odds-snapshot
POST /api/betting-edges
POST /api/live-state/match
POST /api/live-state/elimination
POST /api/refresh-live-data
```

For live World Cup updates, copy `.env.example` to `.env` and add an API key:

```bash
cp .env.example .env
```

```text
BALLDONTLIE_API_KEY=your_api_key_here
WORLD_CUP_API_BASE_URL=https://api.balldontlie.io/fifa/worldcup/v1
THE_ODDS_API_KEY=your_api_key_here
THE_ODDS_SPORT=soccer_fifa_world_cup
THE_ODDS_REGIONS=us,uk,eu
```

The live refresh stores provider state in `data/live_state.json`. During the tournament, completed matches and eliminated teams can be written there so future simulations lock known scores and prevent eliminated teams from advancing. The website also has manual controls for locking a completed score and marking/restoring eliminated teams.

Completed-match updates also rebuild `data/live_team_state.csv`, which is the forecast-time Bayesian update table used by later matches.

BALLDONTLIE refresh can also write provider odds to `data/bookmaker_odds.csv` when your API tier exposes odds/futures endpoints.

The Odds API snapshot uses the official `/v4/sports/{sport}/odds/` endpoint with the `h2h` market. It overwrites `data/bookmaker_odds.csv` only when fetched events match the current World Cup team list. You can trigger it from the Analyst Brief checkbox or directly:

```bash
curl -X POST http://127.0.0.1:8000/api/refresh-odds-snapshot \
  -H "Content-Type: application/json" \
  -d '{}'
```

Open-Meteo weather does not need an API key. Choose `Auto from venue` in the website. Tournament simulations automatically use each fixture's venue and kickoff; the match lab uses the selected venue. If the kickoff is outside the weather forecast horizon or Open-Meteo is unavailable, the app falls back to venue climatology.

## Fixture-Aware Context

The app now uses `data/fixtures.csv` as the tournament schedule context table. It contains all 104 match ids, team/slot labels, venue-local kickoff timestamps, venues, and a `venue_source` column.

Rebuild it with:

```bash
python3 scripts/build_fixture_schedule.py
```

Rows marked `published-schedule` are applied automatically by the simulator. That means tournament simulations do not use one fixed venue: group matches, knockouts, the bronze final, and the final each pull their own venue and kickoff from the fixture table.

During simulation, every fixture automatically applies:

- Venue-specific weather or climatology.
- Team-specific travel load from the previous match venue.
- Rest days between matches.
- Fatigue load from travel, rest, squad depth, and lineup uncertainty.
- Crowd/host support based on host country, confederation, and broad fan-base priors.

Known live results in `data/live_state.json` still override predictions, so the app can move from pre-tournament forecast to during-tournament tracker.

## Advanced Signal Layer

The match model has a second forecast-time context layer on top of the trained RF + Dixon-Coles + Elo ensemble. Run the full refresh with any provider access you have:

```bash
python3 scripts/sync_full_advanced_context.py \
  --lineups \
  --odds \
  --statsbomb \
  --weather \
  --fetch-weather \
  --optional-providers
```

Provider flags are optional:

- `--lineups`: pulls Sportmonks observed lineups, formations, and sidelined players when `SPORTMONKS_API_TOKEN` is configured.
- `--odds`: pulls a one-time The Odds API snapshot when `THE_ODDS_API_KEY` is configured.
- `--statsbomb`: pulls StatsBomb Open Data events and builds event-derived tactics, set pieces, freeze-frame, goalkeeper, shots, and xG inputs.
- `--weather --fetch-weather`: trains weather effects from `data/weather_match_history.csv`, filling hourly weather with Open-Meteo archive data when latitude/longitude and kickoff time are available.

To only rebuild from local files/projections:

```bash
python3 scripts/build_advanced_context.py
```

That writes:

- `data/player_availability.csv`: player injury/suspension/minutes-limit style rows. Provider rows can replace the generated projection.
- `data/confirmed_lineups.csv`: match-specific confirmed XI shape, with projected XI rows as the fallback.
- `data/market_signals.csv`: no-vig match probabilities and line movement derived from `data/bookmaker_odds.csv`.
- `data/tactical_profiles.csv`: formation, pressing, build-up, transition, defensive line, and width.
- `data/set_piece_profiles.csv`: corner/free-kick xG priors, aerial threat, delivery quality, and concede risk.
- `data/goalkeeper_profiles.csv`: save rate, post-shot xG prevention proxy, claims, and sweeper profile.
- `data/referee_profiles.csv`: cards, penalties, fouls, VAR rate, and bias priors. Add assigned referee rows when known.
- `data/weather_effects.csv`: historically inspired weather multipliers for goals, pressing, set pieces, and keeper handling.
- `data/live_team_state.csv`: live posterior/momentum rows rebuilt from completed results.
- `data/freeze_frame_signals.csv`: 360/freeze-frame proxy signals for box density, shot lanes, compactness, and keeper positioning.

These are not separate dashboard decorations. `/api/match` uses them inside expected goals before building the exact-score matrix, and `/api/advanced-signals?team_a=Mexico&team_b=South%20Africa` exposes the per-source xG deltas for auditing or RAG analysis.

Provider rows are preserved. The builder only fills missing teams with local projections, so confirmed lineups, injury reports, licensed referee assignments, bookmaker lines, event data, and weather-trained effects will override starter priors without changing the app.

Full-version scripts:

```bash
python3 scripts/sync_lineups.py --optional
python3 scripts/sync_odds_snapshot.py --optional
python3 scripts/sync_statsbomb_advanced.py --competition-id 43 --season-id 106
python3 scripts/xg_model.py
python3 scripts/train_weather_effects.py --fetch-open-meteo
python3 scripts/build_advanced_context.py
```

For weather training, create `data/weather_match_history.csv` with match date/kickoff, latitude, longitude, total goals, and optional weather variables. The trainer writes `data/weather_effects.csv`; if the sample is too small for a weather class, that class keeps a conservative prior and marks the source accordingly.

## Agentic RAG Intelligence Desk

The Intelligence Desk is a local-first analysis agent. It does not need an LLM key to work.

For each question it:

1. Identifies mentioned teams and venues.
2. Routes the question to relevant tools such as team profiles, historical head-to-head, the current match model, venue weather, or live state.
3. Retrieves relevant evidence chunks from the project datasets and documentation using a local TF-IDF bigram index.
4. Produces an answer with sources and exposes the agent trace in the UI.

Example API request:

```bash
curl -X POST http://127.0.0.1:8000/api/intelligence \
  -H "Content-Type: application/json" \
  -d '{"question":"Why does France have an edge over Brazil?","use_llm":false}'
```

To optionally use an OpenAI-compatible model only for final answer synthesis, configure:

```text
WORLD_CUP_AI_BASE_URL=http://127.0.0.1:11434/v1
WORLD_CUP_AI_MODEL=your-model-name
WORLD_CUP_AI_API_KEY=
```

This works with providers exposing an OpenAI-compatible `/chat/completions` endpoint. Retrieval, model forecasts, tool routing, citations, and fallback synthesis continue to work when no model is configured or the model endpoint is unavailable.

Run the deterministic agent routing/retrieval eval:

```bash
python3 scripts/evaluate_intelligence.py
python3 scripts/evaluate_intelligence.py --output outputs/intelligence_eval.json
```

Run the model backtest report:

```bash
.venv/bin/python scripts/backtest_models.py
.venv/bin/python scripts/backtest_models.py --by-year
```

The `--by-year` view uses saved holdout predictions from `scripts/train_model.py` and groups accuracy, log loss, and favorite confidence by year and tournament.

## Analyst Brief

The Analyst Brief is the more opinionated matchup screen. It is not just a chatbot response: the backend calls the exact-score model, squad projection, shot-quality zones, penalty-strength signal, venue weather, bookmaker edge screen, and local evidence retriever, then returns a compact brief plus an agent trace.

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/analyst-brief \
  -H "Content-Type: application/json" \
  -d '{"team_a":"France","team_b":"Brazil","weather":"auto","venue":"New York New Jersey","refresh_odds":false}'
```

Set `refresh_odds` to `true` only when `THE_ODDS_API_KEY` is configured and you want to spend one odds API call before the brief.

### GitHub Technology Radar

The June 2026 technology review identified these useful projects:

- [Pydantic AI](https://github.com/pydantic/pydantic-ai): the strongest future fit for typed tools, structured agent outputs, evals, and OpenTelemetry because this backend already uses FastAPI/Pydantic.
- [LangGraph](https://github.com/langchain-ai/langgraph): useful if Intelligence Desk workflows become long-running, stateful, or human-approved.
- [Qdrant](https://github.com/qdrant/qdrant) or [LanceDB](https://github.com/lancedb/lancedb): good replacements for the local TF-IDF retriever after the knowledge corpus grows to live articles, reports, and player documents.
- [Pathway](https://github.com/pathwaycom/pathway): useful later for continuously updating RAG from live feeds.
- [StatsBomb Open Data](https://github.com/statsbomb/open-data): the most useful next football-specific integration for event data, lineups, and xG-derived features.

The current implementation deliberately uses the existing scikit-learn dependency for retrieval. It is transparent, fast for the current corpus, and avoids operating a vector database before the project needs one.

## Data Sources

The qualified teams and competition format were checked against FIFA pages available on May 11, 2026:

- [FIFA qualified teams page](https://www.fifa.com/en/articles/world-cup-2026-who-has-qualified), published March 31, 2026.
- [FIFA 2026 groups / qualification rules page](https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/groups-how-teams-qualify-tie-breakers), published April 19, 2026.
- [FIFA match schedule media release](https://vod.fifa.com/organisation/media-releases/updated-world-cup-2026-match-schedule-venues-kick-off-times-104-matches), published December 6, 2025.
- [FIFA World Cup 2026 match schedule PDF](https://digitalhub.fifa.com/asset/4b5d4417-3343-4732-9cdf-14b6662af407/FWC26-Match-Schedule_English.pdf), schedule version dated April 10, 2026.
- [WorldCuply 2026 match schedule table](https://worldcuply.com/schedule.html), used as a readable structured cross-check for all 104 venue-local kickoff rows.
- [FIFA/Coca-Cola Men's World Ranking](https://inside.fifa.com/fifa-world-ranking/men), official update date: April 1, 2026, with the next update listed for June 10, 2026.
- [ESPN April 2026 ranking list](https://www.espn.com/soccer/story/_/id/46664763/fifa-mens-top-50-world-rankings), used as a readable cross-check for the rank numbers in `data/teams.csv`.
- [The Odds API v4 documentation](https://the-odds-api.com/liveapi/guides/v4/), used for the optional official odds snapshot adapter.
- [Kaggle: International football results from 1872 to 2026](https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2017), a useful full training dataset for historical matches.
- [GitHub mirror: martj42/international_results](https://github.com/martj42/international_results), useful if you prefer downloading `results.csv` directly from GitHub.
- [StatsBomb Open Data](https://github.com/statsbomb/open-data), used by `scripts/sync_statsbomb_shots.py` for event-level shot locations, body part, play pattern, pressure, and outcomes.
- [Kaggle penalty kick dataset](https://www.kaggle.com/datasets/rodrigoarede2003/penalty-kick-dataset-20202025/data), a public kick-level starter source with foot, direction, keeper action, score state, and outcome columns.

Ranking numbers in `data/teams.csv` are the April 2026 ranks used as model input. The model is intentionally transparent and easy to edit; update that CSV after the June 10 ranking release to refresh the baseline.

## Model Notes

This is not claiming to know the future. It is a simulation model:

1. Rebuild pre-match Elo, recent form, rest, and experience signals chronologically.
2. Blend calibrated Random Forest, Dixon-Coles, and Elo probabilities.
3. Build one exact-score distribution and sample scores directly from it.
4. Rank groups using points, goal difference, goals scored, then ranking.
5. Advance 24 top-two teams plus the eight best third-place teams.
6. Simulate a Round of 32 through the final.

The static tactical estimates remain transparent inputs in `data/team_features.csv` and `data/team_advanced_features.csv`. Current squad value, observed lineup continuity, formation frequency, and provider-reported availability are generated separately so they can update without leaking present-day information into historical training.

The match predictor can estimate scorelines directly:

```bash
python3 scripts/predict_worldcup.py --match "Argentina" "England" --top-scores 10
```

The output includes expected score, win/draw/loss probabilities, and the most likely exact scores.

## Forecast Ensemble

Install dependencies in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Train the leakage-safe RF + Dixon-Coles + Elo ensemble:

```bash
python3 scripts/train_model.py
```

Track a training run with MLflow:

```bash
python3 scripts/train_model.py --mlflow
mlflow ui
```

Tune Random Forest hyperparameters with a chronological holdout:

```bash
python3 scripts/tune_model.py --trials 30
```

That creates:

```bash
models/worldcup_random_forest.joblib
```

Inspect the saved chronological backtest:

```bash
python3 scripts/backtest_models.py
python3 scripts/backtest_models.py --output outputs/model_report.json
```

Once the model file exists, `predict_worldcup.py` uses the ensemble automatically:

```bash
python3 scripts/predict_worldcup.py --sims 100000 --seed 26 --save outputs/predictions.csv
python3 scripts/predict_worldcup.py --match "France" "Brazil"
```

To force the old baseline:

```bash
python3 scripts/predict_worldcup.py --no-model --sims 20000
```

The included `data/historical_matches.csv` is a starter training set. For a better model, download `results.csv` from the Kaggle/GitHub source above and convert it:

```bash
python3 scripts/convert_results_csv.py path/to/results.csv --since 2018-01-01
python3 scripts/train_model.py
```

Historical training currently uses these pre-match feature groups:

- Elo difference from historical match results.
- Recent points, win/draw rate, scoring, defending, clean sheets, and volatility over the last 10 matches.
- Rest-day and international-experience differences.
- Neutral venue and tournament importance.
- Recency-weighted training, so newer matches matter more than older matches.
- A chronological 60/20/20 train/calibrate/test backtest instead of a random split.
- A logistic calibration layer combining Random Forest, Dixon-Coles, and Elo probabilities.
- Feature-importance metadata, used by the website to show the biggest prediction drivers for a matchup.
- Optional SHAP explanations when `shap` is installed.
- Optional MLflow tracking when `--mlflow` is passed.
- Optional Optuna tuning through `scripts/tune_model.py`.

Current squad ratings and other present-day estimates are deliberately excluded from historical training to prevent leakage. They still influence forecasts through the scenario layer, where they belong.

## Event Models

Train the shot-level xG model:

```bash
python3 scripts/xg_model.py
```

That creates:

```text
data/shot_events.csv
data/xg_team_zones.csv
models/xg_shot_model.joblib
```

The xG trainer uses a gradient-boosted classifier over shot location, computed distance, computed angle, body part, assist type, defender pressure, game state, shot type, and minute. `data/xg_team_zones.csv` compares predicted goals against actual goals by team and shot zone. Those team danger-zone signals now make a conservative forecast-time expected-goals adjustment, while the xG lab remains an expandable audit tool.

To replace the starter sample with real event data from StatsBomb Open Data:

```bash
python3 scripts/sync_statsbomb_shots.py --competition-id 43 --season-id 106
python3 scripts/xg_model.py
```

Train the penalty placement and shootout outcome models:

```bash
python3 scripts/penalty_model.py
```

That creates:

```text
data/penalty_kicks.csv
models/penalty_shootout_model.joblib
```

The penalty trainer fits gradient-boosted models for shot placement and kick outcome using kicker foot, position, kick order, pressure, score state, knockout round, past kicker placement tendencies, and keeper dive tendencies. Team penalty strength is used as the knockout fallback after drawn knockout matches. The website also joins penalty-specific tendencies back to each player's normal-time profile, so the expandable kicker-vs-keeper lab can audit preferred foot, tactical role, xG/pass/dribble context, placement split, and keeper save/dive profile.

If you have Kaggle credentials configured in `kaggle.json`, you can pull the public penalty-kick dataset and retrain:

```bash
python3 scripts/sync_kaggle_penalties.py
python3 scripts/penalty_model.py
```

The penalty dataset is not a complete every-major-tournament archive. It is a public kick-level starter source. For production-quality World Cup shootout advice, replace `data/penalty_kicks.csv` with a licensed or manually coded major-tournament panel that includes placement, keeper dive, foot, pressure, and outcome.

## Final Squad Sync

FIFA published all 48 final World Cup squads on June 2, 2026. Refresh the player-level dataset and generated squad features with:

```bash
python3 scripts/sync_squads.py
```

To replace inferred lineups with observed recent starting XIs, add a Sportmonks token to `.env` and run:

```text
SPORTMONKS_API_TOKEN=your_token
```

```bash
python3 scripts/sync_lineups.py
python3 scripts/sync_squads.py --from-existing
```

This writes:

- `data/worldcup_squads.csv`: current listed players, positions, clubs, caps, international goals, optional market values, and projected-XI status.
- `data/squad_features.csv`: team-level roster value, projected XI, bench depth, experience, balance, availability, and formation-fit scores used at forecast time.
- `data/player_match_stats.csv`: normal-time and penalty player characteristics such as preferred foot, weak-foot usage, tactical role, formation role, tactic profile, shooting, xG, xA, key passes, pass completion, progressive passes/carries, dribble success, cross completion, pressure success, tackle success, aerials, cards/fouls/offsides, scoring-window shares, goalkeeper saves, post-shot xG prevention, claims, sweeper actions, long-pass completion, kicker placement preferences, penalty goal/save/miss rates, and keeper dive tendencies.
- `data/player_match_team_features.csv`: team aggregate scores from the player trait table, used as forecast-time expected-goals adjustments.
- `data/player_candidates.csv`: scorer simulation candidates generated from the current squads.
- `data/lineup_observations.csv`: confirmed recent starting XIs and formations from the configured provider.
- `data/player_availability.csv`: current provider-reported injuries and suspensions.

Final squads are sourced from the structured 2026 squad list, which cites each association announcement. Market values are optionally enriched from current Transfermarkt World Cup/team pages. Because market value is an estimate and not a performance statistic, it is only one part of the forecast-time squad layer.

The refresh preserves the current active list rather than forcing every team to 26 players. During the injury-replacement window, a team may temporarily show fewer than 26; the sync command reports those open roster slots so a later replacement appears on the next refresh.

When observed lineup history is available, the pipeline uses recency-weighted start rates, the most common formation, lineup continuity, and current sidelined players. Without provider coverage, it falls back to a clearly labeled position/value/caps projection. Sportmonks is optional because lineup and injury coverage varies by subscription.

Build or refresh just the normal-time player trait layer:

```bash
python3 scripts/sync_player_match_stats.py
```

To use real seasonal stats later, provide a CSV keyed by `team,player` with any matching stat columns. This can include provider fields such as preferred foot, pass completion, pressures, tackle success, dribble success, cross completion, aerial win rate, minutes, availability, penalty placement splits, and keeper penalty dive/save tendencies:

```bash
python3 scripts/sync_player_match_stats.py --provider-stats data/provider_player_season_stats.csv
```

The default player stats are not claimed as official seasonal event data. They are transparent starter estimates from current squad profile, projected role, caps, goals, position, market value, availability, and starter status. Replace them with licensed provider data for production analysis.

The `Refresh World Cup squads` GitHub Action runs daily and can also be triggered manually. It refreshes the generated squad, player-trait, and scorer files and commits changes, so a deployed app can pick up late replacements and updated player values.

The simulation output also reports confidence intervals for champion and finalist odds. These are not a claim that the model is perfect; they show Monte Carlo uncertainty from the number of simulations you ran.

## Betting Edge Screen

The website can compare model probabilities against bookmaker prices from:

```text
data/bookmaker_odds.csv
```

Supported starter markets:

- `match_winner`: three-way soccer market with team A, draw, team B.
- `champion`: tournament futures market.

The analyzer converts American or decimal odds into implied probability, removes the bookmaker margin within each event, compares that no-vig market probability to the model probability, then reports expected value and a capped fractional-Kelly paper stake.

To refresh prices from an official feed, set `THE_ODDS_API_KEY` and use `/api/refresh-odds-snapshot` or the `Pull odds once` checkbox in the Analyst Brief panel. This is for educational analysis and paper tracking, not guaranteed profit or betting advice.

## Next Accuracy Upgrades

- Add player club minutes, workload, and recovery estimates.
- Feed team xG/xGA aggregates from the shot model into the match ensemble.
- Replace estimated normal-time player traits with real FBref/StatsBomb/Wyscout/Opta-style seasonal feeds.
- Add player-level club minutes, player market value, and age curve.
- Use the penalty model inside knockout tiebreakers instead of the current aggregate penalty-strength edge.
- Add travel distance, venue altitude/climate, and rest days.
- Add lineup rotation logic for group-stage match three.
- Compare the current ensemble against XGBoost or LightGBM challengers in the same chronological backtest.
- Add official bracket mapping when all third-place advancement paths are locked down.

The exact FIFA Round-of-32 bracket depends on third-place combinations. This project uses a deterministic reseeding bracket after the group stage so the expanded format is represented without pretending to have every official third-place path encoded.
