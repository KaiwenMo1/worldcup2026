# Tactical Data Pipeline

The tactical subsystem turns manager and player evidence into inspectable analysis without letting weak or incomplete data silently alter the forecast.

## Design Rules

1. Registration is not evidence. `data/managers.csv` records the current coach for each tournament team; it does not claim a tactical profile is validated.
2. Observed and estimated data remain distinguishable. Every tactical brief reports coverage and fallback status.
3. Provider data is normalized behind local CSV contracts so the rest of the app is provider-independent.
4. Manager and player context may explain a forecast immediately, but it may influence probabilities only after chronological backtesting improves calibration.

## Manager Pipeline

| File | Purpose |
|---|---|
| `data/managers.csv` | Current 48-team manager registry with source and verification date |
| `data/manager_skills/*.json` | Versioned, transparent tactical hypotheses |
| `data/manager_match_history.csv` | Observed match-level manager behavior contract |
| `data/manager_features.csv` | Recency-weighted features distilled from observed manager history |

Validate the registry with `python scripts/sync_managers.py`. A network refresh with `--refresh` updates names from the configured public source, but changed rows still require manual review before a tactical skill is considered validated.

Normalize an observed manager-match export before distillation:

```bash
python scripts/sync_manager_match_history.py \
  --provider-csv path/to/provider_manager_matches.csv \
  --provider provider-name
```

Historical attribution must include a known `manager_id` or an exact `team` plus `manager_name`. The adapter intentionally refuses to assume that the current manager coached an older match.

`python scripts/distill_manager_profiles.py` calculates sample size, recency-weighted results, preferred formation, pressing, defensive line, build-up, possession, transition, set-piece, and substitution features. Empty history produces an explicit `no_observed_history` row rather than invented values.

The repository also includes a reproducible public-data adapter:

```bash
python scripts/sync_statsbomb_manager_history.py --max-matches-per-manager 12
python scripts/curate_manager_skills_from_history.py --apply
```

The adapter matches managers only when a normalized registry name is a unique subset of the provider manager name. The curation step writes `data/derived/manager_curation_coverage.csv`, promotes profiles only after the observed-sample threshold is met, and leaves conditional decision rules labeled as hypotheses.

## Player Pipeline

| File | Purpose |
|---|---|
| `data/worldcup_squads.csv` | Canonical tournament squad identities |
| `data/player_identity_map.csv` | Stable local IDs and optional provider IDs |
| `data/observed_player_stats.csv` | Provider-normalized observed seasonal stats |
| `data/player_match_stats.csv` | Player features consumed by matchup/context builders |
| `data/player_match_team_features.csv` | Team aggregates produced from player features |

Build identities with:

```bash
python scripts/build_player_identity_map.py \
  --provider-csv path/to/provider_players.csv \
  --provider provider-name
```

Normalize and apply an observed provider export with:

```bash
python scripts/sync_observed_player_stats.py \
  --provider-csv path/to/provider_player_stats.csv \
  --provider provider-name \
  --apply
```

The adapter accepts the project field names and common aliases such as `minutes_played` and `pass_accuracy`. Provider exports must include `team` and `player`; a stable `provider_player_id` is strongly recommended.

## Coverage And Activation

`GET /api/tactics/coverage/{team}` and every tactical brief report:

- manager registration, skill availability, observed-history sample, and data quality
- observed versus estimated player profile counts
- projected lineup and availability coverage
- squad identities and provider-linked identity counts
- whether context features are allowed to influence the forecast

Historical context belongs in `data/historical_context_features.csv`. Run:

```bash
python scripts/backtest_context_features.py
```

The gate compares the existing feature set with a candidate that adds observed manager edge, player-quality edge, and lineup-continuity edge. It remains disabled unless:

- chronological test coverage is at least `60%`
- log loss improves by at least `0.005`
- multiclass Brier score improves by at least `0.002`
- the chronological train and test samples are large enough

The resulting decision is written to `data/context_feature_gate.json`. Until that file records `enabled: true`, tactical context is explanation-only and the existing predictor behavior remains unchanged.

## Current Coverage

As of June 12, 2026:

- manager registry: `48/48` teams
- manager skills: `48/48`
- managers with observed match history: `30/48`
- observed manager-match rows: `236`
- evidence-backed manager profiles: `10`
- limited-observed manager profiles: `20`
- explicit manager research gaps: `18`
- canonical squad identities: `1,246`
- provider-linked player identities: `0`
- observed provider player profiles: `0`
- forecast context gate: disabled

The unresolved gaps are useful: they make the next evidence-acquisition work measurable and prevent projected values from being presented as observed behavior.
