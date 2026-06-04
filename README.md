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
- Exact-score probability heatmap with score-derived win/draw/loss aggregation.
- Match confidence, goal-shape insights, and model-driver explanations.
- Champion odds with simulation confidence ranges.
- Auto venue weather from Open-Meteo.
- Venue map powered by MapLibre.
- ECharts heatmap and EV charts.
- Agentic RAG Intelligence Desk with local evidence retrieval, tool routing, source citations, and an inspectable agent trace.
- Optional OpenAI-compatible or local-model synthesis for Intelligence Desk answers.
- Group viewer.
- BALLDONTLIE live-state / odds refresh endpoint.

API routes:

```text
GET  /api/teams
GET  /api/groups
GET  /api/venues
GET  /api/venue-weather
GET  /api/intelligence/status
GET  /api/status
GET  /api/live-state
POST /api/simulate
POST /api/match
POST /api/intelligence
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
```

The live refresh stores provider state in `data/live_state.json`. During the tournament, completed matches and eliminated teams can be written there so future simulations lock known scores and prevent eliminated teams from advancing. The website also has manual controls for locking a completed score and marking/restoring eliminated teams.

BALLDONTLIE refresh can also write provider odds to `data/bookmaker_odds.csv` when your API tier exposes odds/futures endpoints.

Open-Meteo weather does not need an API key. Choose `Auto from venue` in the website and select a host venue to apply live temperature/rain/wind/altitude context to match predictions.

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

Track a training run with MLflow:

```bash
python3 scripts/train_model.py --mlflow
mlflow ui
```

Tune Random Forest hyperparameters with Optuna:

```bash
python3 scripts/tune_model.py --trials 30
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
- Recency-weighted training, so newer matches matter more than older matches.
- Probability shrinkage toward weighted class priors, so small-sample or noisy matchups are less overconfident.
- Feature-importance metadata, used by the website to show the biggest prediction drivers for a matchup.
- Optional SHAP explanations when `shap` is installed.
- Optional MLflow tracking when `--mlflow` is passed.
- Optional Optuna tuning through `scripts/tune_model.py`.

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

This is for analysis, not guaranteed profit. Use it to track whether the model consistently beats closing odds before risking real money.

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
