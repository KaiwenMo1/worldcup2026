#!/usr/bin/env python3
"""Smoke-test manual injury/news ingestion and conflict-aware risk derivation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion import (  # noqa: E402
    MANUAL_INJURY_NEWS_SAMPLE_PATH,
    ManualCsvInjuryNewsAdapter,
    build_injury_risk_signals,
    get_team_injury_risk_signals,
    ingest_injury_news,
    write_injury_risk_signals,
    write_normalized_injury_news,
)


def main() -> None:
    result = ingest_injury_news(ManualCsvInjuryNewsAdapter(MANUAL_INJURY_NEWS_SAMPLE_PATH))
    assert result.records and not result.issues
    signals = build_injury_risk_signals(result.records)
    assert signals and any(signal.needs_manual_review for signal in signals)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        assert not write_normalized_injury_news(result.records, root / "normalized.csv")
        assert not write_injury_risk_signals(signals, root / "risks.csv")
        france = get_team_injury_risk_signals("France", "FRA-BRA-TEST", path=root / "risks.csv")
        assert france
    print(
        f"Injury/news smoke test passed: evidence={len(result.records)}, "
        f"signals={len(signals)}, conflicts={sum(signal.needs_manual_review for signal in signals)}"
    )


if __name__ == "__main__":
    main()
