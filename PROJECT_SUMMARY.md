# World Cup Predictor Project Summary

## Purpose

This project predicts the FIFA World Cup 2026 using:

- 48-team tournament simulation.
- Confirmed group-stage data.
- Historical international match training data.
- Random Forest match-result probabilities.
- Poisson-style exact score simulation.
- Website UI with bracket path, champion odds, match predictor, venue weather, market-edge screen, top scorer projections, and an agentic RAG Intelligence Desk.

## Core Commands

```bash
source .venv/bin/activate
python scripts/train_model.py
python scripts/train_model.py --mlflow
python scripts/tune_model.py --trials 30
python scripts/predict_worldcup.py --sims 10000 --seed 26 --save outputs/predictions.csv
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Website:

```text
http://127.0.0.1:8000
```

## Main Files

`scripts/predict_worldcup.py`

- Command-line tournament simulator.
- Loads teams, groups, team features, and trained Random Forest model.
- Simulates group stage, knockout matches, exact scores, and tournament odds.
- Contains the baseline expected-goals model.

`scripts/train_model.py`

- Trains Random Forest classifier for match outcome.
- Trains Random Forest regressors for expected goals.
- Uses historical match data plus team feature differences.
- Can log metrics/artifacts to MLflow with `--mlflow`.
- Saves `models/worldcup_random_forest.joblib`.

`scripts/tune_model.py`

- Uses Optuna to tune Random Forest hyperparameters.
- Saves best tuning output to `models/optuna_best_params.json`.

`scripts/evaluate_intelligence.py`

- Tests Intelligence Desk entity detection, tool routing, and local evidence retrieval.
- Can save a JSON evaluation report for tracking regressions.

`scripts/convert_results_csv.py`

- Converts Kaggle/GitHub `results.csv` into `data/historical_matches.csv`.
- Skips rows without final scores.

`app/main.py`

- FastAPI backend for the website.
- Exposes `/api/teams`, `/api/groups`, `/api/status`, `/api/simulate`, `/api/match`, `/api/intelligence`, and `/api/refresh-live-data`.
- Uses FIFA-style match-number knockout path.
- Adds scenario context: weather, travel, fatigue, and host edge.
- Generates champion odds, bracket path, match predictions, and top scorer projections.
- Pulls Open-Meteo venue weather for auto weather context.
- Pulls BALLDONTLIE matches/odds/futures when API key and tier allow it.
- Provides betting edge analysis from `data/bookmaker_odds.csv`.
- Provides optional SHAP model explanations when installed.

`app/intelligence.py`

- Builds a local TF-IDF bigram retrieval index from project data and documentation.
- Identifies teams and venues mentioned in user questions.
- Routes questions to team profile, head-to-head, match forecast, venue weather, and live-state tools.
- Produces local evidence-backed answers and supports optional OpenAI-compatible LLM synthesis.
- Returns inspectable agent traces and evidence citations to the website.

`app/static/index.html`

- Main website page.

`app/static/app.js`

- Browser logic for running simulations, rendering bracket, odds, groups, match predictions, and top scorers.
- Runs and renders Intelligence Desk queries, evidence, and agent traces.
- Renders ECharts score/EV charts.
- Renders a MapLibre venue map.

`app/static/styles.css`

- Sports-dashboard visual styling.

## Data Files

`data/teams.csv`

- Qualified teams, confederation, FIFA rank, host flag, and World Cup pedigree.

`data/groups.csv`

- 12 World Cup groups of four teams.

`data/team_features.csv`

- Team-level football strength inputs:
  attack, midfield, defense, goalkeeper, bench, recent form, fitness, chemistry, manager.

`data/team_advanced_features.csv`

- Advanced team parameters:
  set-piece attack/defense, penalty strength, discipline, tactical flexibility, injury resilience, pressing, transition speed, big-match composure.

`data/player_candidates.csv`

- Candidate top scorers by team.
- Includes scoring weight, starter flag, and penalty-taker flag.

`data/historical_matches.csv`

- Training data converted from Kaggle/GitHub international football results.

`data/live_state.json`

- Placeholder for live tournament state.
- Can lock completed matches and mark teams eliminated.

`data/venues.csv`

- World Cup 2026 host venues with coordinates and altitude.
- Powers Open-Meteo weather and MapLibre venue map.

`data/bookmaker_odds.csv`

- Match/futures odds input for the market-edge analyzer.
- Can be manually edited or refreshed from BALLDONTLIE odds endpoints.

`models/worldcup_random_forest.joblib`

- Trained Random Forest model artifact.

`outputs/predictions.csv`

- Exported command-line prediction results.

## Current Model Features

The model uses:

- FIFA rank difference.
- Squad rating difference.
- Attack vs defense edge.
- Midfield edge.
- Goalkeeper edge.
- Bench depth.
- Recent form.
- Fitness.
- Chemistry.
- Manager rating.
- Elo difference from historical matches.
- Recent points over last 10 matches.
- Recent goal difference.
- Recent goals for/against.
- Recent clean sheet rate.
- Host/neutral context.
- Confederation strength.
- Set-piece edge.
- Penalty strength.
- Discipline.
- Tactical flexibility.
- Injury resilience.
- Pressing intensity.
- Transition speed.
- Big-match composure.
- Weather/travel/fatigue scenario adjustments in the website.
- Auto venue weather from Open-Meteo.
- SHAP explanations when optional dependency is installed.
- MLflow model tracking and Optuna tuning support.
- Local agentic RAG retrieval over team profiles, historical data, venues, live state, and project documentation.

## Current Technology Direction

- Pydantic AI is the preferred future agent framework because the backend already uses FastAPI and Pydantic.
- LangGraph becomes useful if agent runs need durable state, approval steps, or long-running workflows.
- Qdrant or LanceDB should replace local TF-IDF only after live news, reports, and player documents make the corpus meaningfully larger.
- Pathway is a candidate for continuously updating RAG from live feeds.
- StatsBomb Open Data is the highest-value football-specific data integration for future xG, lineup, and event features.

## Best Next Upgrades

- Full FIFA third-place bracket scenario mapping.
- Venue/date weather API integration.
- Rest-days and travel-distance calculation between venues.
- Injury and suspension feed.
- Likely starting XI and minutes-based player fatigue.
- Betting odds as market-prior input.
- Backtesting dashboard for 2018/2022/qualifiers.
- Team detail pages with model explainability.
- Shareable bracket links and exported bracket images.
