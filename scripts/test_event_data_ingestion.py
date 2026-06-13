#!/usr/bin/env python3
"""Smoke-test provider-mapped event ingestion and match summary derivation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion import (  # noqa: E402
    MANUAL_MATCH_EVENTS_SAMPLE_PATH,
    ManualCsvEventAdapter,
    MatchEventType,
    build_match_summary_signals,
    ingest_event_data,
    write_match_summary_signals,
    write_normalized_events,
)


def main() -> None:
    result = ingest_event_data(ManualCsvEventAdapter(MANUAL_MATCH_EVENTS_SAMPLE_PATH))
    assert result.events
    assert {event.event_type for event in result.events} == set(MatchEventType)
    assert all(issue.severity.value == "info" for issue in result.issues)
    summaries = build_match_summary_signals(result.events)
    assert len(summaries) == 2
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        assert not write_normalized_events(result.events, root / "events.csv")
        assert not write_match_summary_signals(summaries, root / "summaries.csv")
    print(
        f"Event-data smoke test passed: events={len(result.events)}, summaries={len(summaries)}, "
        f"optional_notices={len(result.issues)}"
    )


if __name__ == "__main__":
    main()
