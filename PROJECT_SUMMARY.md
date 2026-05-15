# World Cup Predictor Project Summary

## Purpose

This project predicts the FIFA World Cup 2026 using:

- 48-team tournament simulation.
- Confirmed group-stage data.
- Historical international match training data.
- Random Forest match-result probabilities.
- Poisson-style exact score simulation.
- Website UI with bracket path, champion odds, match predictor, and top scorer projections.

## Core Commands

```bash
source .venv/bin/activate
python scripts/train_model.py
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
- Saves `models/worldcup_random_forest.joblib`.

`scripts/convert_results_csv.py`

- Converts Kaggle/GitHub `results.csv` into `data/historical_matches.csv`.
- Skips rows without final scores.

`app/main.py`

- FastAPI backend for the website.
- Exposes `/api/teams`, `/api/groups`, `/api/status`, `/api/simulate`, `/api/match`, and `/api/refresh-live-data`.
- Uses FIFA-style match-number knockout path.
- Adds scenario context: weather, travel, fatigue, and host edge.
- Generates champion odds, bracket path, match predictions, and top scorer projections.

`app/static/index.html`

- Main website page.

`app/static/app.js`

- Browser logic for running simulations, rendering bracket, odds, groups, match predictions, and top scorers.

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
