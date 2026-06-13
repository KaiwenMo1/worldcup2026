#!/usr/bin/env python3
"""Rebuild transparent player role vectors and recent-form signals."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion import (  # noqa: E402
    IngestionStatus,
    append_data_quality_issues,
    append_ingestion_run,
    build_form_signals,
    build_role_vectors,
    create_ingestion_run,
    load_normalized_match_stats,
    load_normalized_season_stats,
    write_derived_outputs,
)
from app.ingestion.player_stats_ingestion import (  # noqa: E402
    CURATED_PROFILES_PATH,
    FORM_SIGNALS_PATH,
    MATCH_STATS_PATH,
    ROLE_VECTORS_PATH,
    SEASON_STATS_PATH,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build player role vectors and form signals.")
    parser.add_argument("--season-input", type=Path, default=SEASON_STATS_PATH)
    parser.add_argument("--match-input", type=Path, default=MATCH_STATS_PATH)
    parser.add_argument("--curated-profiles", type=Path, default=CURATED_PROFILES_PATH)
    parser.add_argument("--role-output", type=Path, default=ROLE_VECTORS_PATH)
    parser.add_argument("--form-output", type=Path, default=FORM_SIGNALS_PATH)
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    season, season_issues = load_normalized_season_stats(args.season_input)
    matches, match_issues = load_normalized_match_stats(args.match_input)
    signals = build_form_signals(matches, season)
    vectors, fallback_issues = build_role_vectors(season, signals, curated_profiles_path=args.curated_profiles)
    write_issues = write_derived_outputs(vectors, signals, args.role_output, args.form_output)
    issues = [*season_issues, *match_issues, *fallback_issues, *write_issues]
    critical = any(issue.severity.value == "critical" for issue in issues)
    status = IngestionStatus.FAILED if critical else IngestionStatus.PARTIAL if issues else IngestionStatus.SUCCEEDED
    run = create_ingestion_run(
        source_id="project_repository",
        script="scripts/rebuild_player_role_vectors.py",
        status=status,
        rows_raw=len(season) + len(matches),
        rows_normalized=len(season) + len(matches),
        rows_failed=0,
        error_message="Role-vector rebuild failed due to a critical input or output issue." if critical else None,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
    )
    append_ingestion_run(run)
    if issues:
        append_data_quality_issues([issue.model_copy(update={"run_id": run.run_id}) for issue in issues])
    observed_vectors = sum(vector.data_quality == "observed_season_stats" for vector in vectors)
    print(
        f"Saved {len(vectors)} role vectors ({observed_vectors} observed, {len(vectors) - observed_vectors} fallback) "
        f"and {len(signals)} form signals."
    )
    raise SystemExit(1 if critical else 0)


if __name__ == "__main__":
    main()
