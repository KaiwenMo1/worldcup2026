# 2026 World Cup Predictor
# make website, adapt to other leagues/ sports
A lightweight, self-contained Python model for simulating the FIFA World Cup 2026 with the expanded 48-team format.

The model uses:

- The confirmed 48-team field.
- The 12 groups of four teams.
- A probabilistic match model based on FIFA ranking, host boost, confederation, World Cup pedigree, squad units, recent form, fitness, chemistry, and manager rating.
- The 2026 qualification rule: top two in every group plus the eight best third-place teams advance to a Round of 32.
- Scoreline prediction using expected goals and a Poisson score distribution.

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
- Random Forest / baseline toggle.
- Champion odds table.
- Full bracket-style tournament path with flags and scores.
- Match score predictor.
- Group viewer.
- Live-state refresh endpoint.

API routes:

```text
GET  /api/teams
GET  /api/groups
GET  /api/status
POST /api/simulate
POST /api/match
POST /api/refresh-live-data
```

For live World Cup updates, copy `.env.example` to `.env` and add an API key:

```bash
cp .env.example .env
```

```text
BALLDONTLIE_API_KEY=your_api_key_here
WORLD_CUP_API_BASE_URL=https://fifa.balldontlie.io
```

The live refresh currently stores provider state in `data/live_state.json`. During the tournament, completed matches and eliminated teams can be written there so future simulations lock known scores and prevent eliminated teams from advancing.

## Data Sources

The qualified teams and competition format were checked against FIFA pages available on May 11, 2026:

- [FIFA qualified teams page](https://www.fifa.com/en/articles/world-cup-2026-who-has-qualified), published March 31, 2026.
- [FIFA 2026 groups / qualification rules page](https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/groups-how-teams-qualify-tie-breakers), published April 19, 2026.
- [FIFA/Coca-Cola Men's World Ranking](https://inside.fifa.com/fifa-world-ranking/men), official update date: April 1, 2026, with the next update listed for June 10, 2026.
- [ESPN April 2026 ranking list](https://www.espn.com/soccer/story/_/id/46664763/fifa-mens-top-50-world-rankings), used as a readable cross-check for the rank numbers in `data/teams.csv`.
- [Kaggle: International football results from 1872 to 2026](https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2017), a useful full training dataset for historical matches.
- [GitHub mirror: martj42/international_results](https://github.com/martj42/international_results), useful if you prefer downloading `results.csv` directly from GitHub.

Ranking numbers in `data/teams.csv` are the April 2026 ranks used as model input. The model is intentionally transparent and easy to edit; update that CSV after the June 10 ranking release to refresh the baseline.

## Model Notes

This is not claiming to know the future. It is a simulation model:

1. Convert ranking, squad, form, fitness, chemistry, and manager features into a strength rating.
2. Estimate each team's expected goals from attack-vs-defense, midfield, goalkeeper, form, and overall strength.
3. Simulate each group match with Poisson goals.
4. Rank groups using points, goal difference, goals scored, then ranking.
5. Advance 24 top-two teams plus the eight best third-place teams.
6. Simulate a Round of 32 through the final.

The current advanced feature file is `data/team_features.csv`. Those values are transparent placeholders for now: they approximate squad quality and team condition without using a live player API yet. Once an API is added, this file can be generated from likely starting XI, bench, injuries, club minutes, player ratings, xG, and recent availability.

The match predictor can estimate scorelines directly:

```bash
python3 scripts/predict_worldcup.py --match "Argentina" "England" --top-scores 10
```

The output includes expected score, win/draw/loss probabilities, and the most likely exact scores.

## Random Forest Model

Install dependencies in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Train the starter Random Forest model:

```bash
python3 scripts/train_model.py
```

That creates:

```bash
models/worldcup_random_forest.joblib
```

Once that file exists, `predict_worldcup.py` uses the Random Forest automatically:

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

The Random Forest currently uses these high-impact feature groups:

- Elo difference from historical match results.
- Recent form over the last 10 matches.
- Recent attacking and defensive goal rates.
- Recent clean-sheet rate.
- Squad context from attack, midfield, defense, goalkeeper, bench, fitness, chemistry, manager, rank, confederation, and host/neutral setting.

## Next Accuracy Upgrades

- Replace estimated squad features with player-level data from an API.
- Generate likely starting XI and bench ratings by position.
- Add injuries, suspensions, fatigue, minutes played, and club workload.
- Add xG and xGA instead of only goals for/against.
- Add player-level club minutes, player market value, and age curve.
- Add penalty shootout strength for knockout tiebreakers.
- Add travel distance, venue altitude/climate, and rest days.
- Add lineup rotation logic for group-stage match three.
- Compare Random Forest against XGBoost or LightGBM and calibrate probabilities.
- Add official bracket mapping when all third-place advancement paths are locked down.

The exact FIFA Round-of-32 bracket depends on third-place combinations. This project uses a deterministic reseeding bracket after the group stage so the expanded format is represented without pretending to have every official third-place path encoded.
