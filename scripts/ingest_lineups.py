#!/usr/bin/env python3
"""Normalize actual lineups and rebuild transparent lineup-delta signals."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.lineup_ingestion import (  # noqa: E402
    CONFIRMED_LINEUPS_PATH,
    MANUAL_LINEUPS_SAMPLE_PATH,
    CsvLineupAdapter,
    build_lineup_delta_signals,
    ingest_lineups,
    write_actual_lineups,
    write_lineup_delta_signals,
)
from app.ingestion.provenance import append_data_quality_issues  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest verified actual lineups and derive lineup-impact deltas.")
    parser.add_argument("--input", type=Path, default=MANUAL_LINEUPS_SAMPLE_PATH)
    parser.add_argument(
        "--from-confirmed-lineups",
        action="store_true",
        help="Read data/confirmed_lineups.csv and retain only confirmed starters.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = CONFIRMED_LINEUPS_PATH if args.from_confirmed_lineups else args.input
    result = ingest_lineups(CsvLineupAdapter(source, require_confirmed=True))
    signals, issues = build_lineup_delta_signals(result.records)
    all_issues = [*result.issues, *issues, *write_actual_lineups(result.records), *write_lineup_delta_signals(signals)]
    if all_issues:
        append_data_quality_issues(all_issues)
    print(f"Normalized actual lineup starters: {len(result.records)}")
    print(f"Derived lineup delta signals: {len(signals)}")
    print(f"Data-quality issues: {len(all_issues)}")


if __name__ == "__main__":
    main()
