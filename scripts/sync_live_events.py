#!/usr/bin/env python3
"""Fetch a provider-independent JSON event feed and rebuild live match summaries."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.event_data_ingestion import (  # noqa: E402
    MATCH_EVENTS_NORMALIZED_PATH,
    MATCH_SUMMARY_SIGNALS_PATH,
    ManualCsvEventAdapter,
    build_match_summary_signals,
    write_match_summary_signals,
    write_normalized_events,
)
from app.tournament_autopilot import load_observed_matches, sync_live_team_state  # noqa: E402


RAW_SNAPSHOT_PATH = ROOT / "data" / "raw" / "live" / "provider_events_latest.json"


def event_rows(payload: Any) -> list[dict[str, str]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("events") or payload.get("data") or []
    else:
        rows = []
    return [
        {str(key): "" if value is None else str(value) for key, value in row.items()}
        for row in rows
        if isinstance(row, dict)
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync a JSON football event feed into the normalized event contract.")
    parser.add_argument("--url", default=os.getenv("WORLD_CUP_EVENT_FEED_URL", ""))
    parser.add_argument("--api-key", default=os.getenv("WORLD_CUP_EVENT_FEED_API_KEY", ""))
    parser.add_argument("--optional", action="store_true")
    return parser.parse_args()


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    if not args.url:
        if args.optional:
            print("Skipped: WORLD_CUP_EVENT_FEED_URL is not configured.")
            return
        raise SystemExit("Set WORLD_CUP_EVENT_FEED_URL to a JSON event endpoint.")
    headers = {"Authorization": args.api_key} if args.api_key else {}
    response = requests.get(args.url, headers=headers, timeout=45)
    response.raise_for_status()
    payload = response.json()
    RAW_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    adapter = ManualCsvEventAdapter(RAW_SNAPSHOT_PATH, source_confidence=0.85)
    result = adapter.normalize(event_rows(payload))
    summaries = build_match_summary_signals(result.events)
    write_normalized_events(result.events, MATCH_EVENTS_NORMALIZED_PATH)
    write_match_summary_signals(summaries, MATCH_SUMMARY_SIGNALS_PATH)
    sync_live_team_state(load_observed_matches())
    print(f"Normalized live events: {len(result.events)}")
    print(f"Derived match-team summaries: {len(summaries)}")
    print(f"Data-quality issues: {len(result.issues)}")


if __name__ == "__main__":
    main()
