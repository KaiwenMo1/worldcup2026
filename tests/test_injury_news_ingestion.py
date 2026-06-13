from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.injury_news_ingestion import (
    INJURY_NEWS_FIELDS,
    AvailabilityStatus,
    InjuryNewsRecord,
    ManualCsvInjuryNewsAdapter,
    build_injury_risk_signals,
    compute_availability,
    get_team_injury_risk_signals,
    ingest_injury_news,
    load_injury_risk_signals,
    load_normalized_injury_news,
    normalize_availability_status,
    write_injury_risk_signals,
    write_normalized_injury_news,
)
from scripts.predict_worldcup import load_teams, match_probabilities


UPDATED = datetime(2026, 6, 11, 12, tzinfo=timezone.utc)


def evidence(
    evidence_id: str,
    status: AvailabilityStatus,
    *,
    confidence: float = 0.8,
    match_id: str | None = None,
    player_id: str = "france_test_player",
) -> InjuryNewsRecord:
    availability, minutes = compute_availability(status, confidence)
    return InjuryNewsRecord(
        evidence_id=evidence_id,
        match_id=match_id,
        player_id=player_id,
        player="Test Player",
        team="France",
        reported_status=status.value,
        status=status,
        detail="Test evidence",
        availability_probability=availability,
        expected_minutes=minutes,
        source=f"source_{evidence_id}",
        source_confidence=confidence,
        reported_at=UPDATED,
        data_quality="manual_evidence",
    )


class InjuryNewsIngestionTests(unittest.TestCase):
    def test_status_vocabulary_normalizes_common_language(self) -> None:
        expected = {
            "full training": AvailabilityStatus.FIT,
            "minor knock": AvailabilityStatus.MINOR_DOUBT,
            "very doubtful": AvailabilityStatus.MAJOR_DOUBT,
            "ruled out with injury": AvailabilityStatus.INJURED,
            "one-match suspension": AvailabilityStatus.SUSPENDED,
            "rotation rest": AvailabilityStatus.RESTED,
            "restricted minutes": AvailabilityStatus.MINUTES_LIMITED,
            "no useful update": AvailabilityStatus.UNKNOWN,
        }

        self.assertEqual({value: normalize_availability_status(value) for value in expected}, expected)

    def test_low_confidence_report_is_shrunk_toward_uncertainty(self) -> None:
        high_probability, high_minutes = compute_availability(AvailabilityStatus.INJURED, 1.0)
        low_probability, low_minutes = compute_availability(AvailabilityStatus.INJURED, 0.2)

        self.assertLess(high_probability, low_probability)
        self.assertLess(high_minutes, low_minutes)
        self.assertLess(low_probability, 0.5)

    def test_manual_adapter_keeps_valid_rows_and_reports_invalid_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "injury.csv"
            fields = [
                "evidence_id",
                "match_id",
                "player_id",
                "player",
                "team",
                "reported_status",
                "detail",
                "expected_return",
                "source",
                "source_confidence",
                "reported_at",
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "player": "Valid Player",
                        "team": "France",
                        "reported_status": "fit",
                        "source": "team_report",
                        "source_confidence": "0.8",
                        "reported_at": UPDATED.isoformat(),
                    }
                )
                writer.writerow(
                    {
                        "player": "Invalid Player",
                        "team": "France",
                        "reported_status": "injured",
                        "source": "rumor",
                        "source_confidence": "not-a-number",
                        "reported_at": UPDATED.isoformat(),
                    }
                )

            result = ingest_injury_news(ManualCsvInjuryNewsAdapter(path))

            self.assertEqual(len(result.records), 1)
            self.assertGreaterEqual(len(result.issues), 1)
            self.assertTrue(all(issue.row_number == 3 for issue in result.issues))

    def test_conflicting_sources_are_preserved_and_require_review(self) -> None:
        records = [
            evidence("a", AvailabilityStatus.MINOR_DOUBT, confidence=0.85),
            evidence("b", AvailabilityStatus.FIT, confidence=0.7),
        ]

        signal = build_injury_risk_signals(records, updated_at=UPDATED)[0]

        self.assertTrue(signal.needs_manual_review)
        self.assertEqual(signal.status, AvailabilityStatus.MINOR_DOUBT)
        self.assertEqual(signal.conflicting_statuses, "fit|minor_doubt")
        self.assertEqual(signal.evidence_count, 2)
        self.assertGreater(signal.availability_probability, 0.5)
        self.assertLess(signal.availability_probability, 1.0)

    def test_normalized_and_derived_outputs_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = [evidence("a", AvailabilityStatus.MINUTES_LIMITED)]
            signals = build_injury_risk_signals(records, updated_at=UPDATED)

            write_issues = [
                *write_normalized_injury_news(records, root / "normalized.csv"),
                *write_injury_risk_signals(signals, root / "risks.csv"),
            ]
            loaded_records, record_issues = load_normalized_injury_news(root / "normalized.csv")
            loaded_signals, signal_issues = load_injury_risk_signals(root / "risks.csv")

            self.assertFalse(write_issues or record_issues or signal_issues)
            self.assertEqual(loaded_records[0].status, AvailabilityStatus.MINUTES_LIMITED)
            self.assertEqual(loaded_signals[0].player_id, "france_test_player")

    def test_team_helper_prefers_match_specific_signal_over_global(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "risks.csv"
            records = [
                evidence("global", AvailabilityStatus.FIT),
                evidence("match", AvailabilityStatus.INJURED, match_id="FRA-BRA"),
            ]
            signals = build_injury_risk_signals(records, updated_at=UPDATED)
            write_injury_risk_signals(signals, path)

            global_signal = get_team_injury_risk_signals("France", path=path)[0]
            match_signal = get_team_injury_risk_signals("France", "FRA-BRA", path=path)[0]

            self.assertEqual(global_signal.status, AvailabilityStatus.FIT)
            self.assertEqual(match_signal.status, AvailabilityStatus.INJURED)

    def test_normalized_schema_has_explicit_confidence_and_computed_fields(self) -> None:
        self.assertTrue(
            {"status", "availability_probability", "expected_minutes", "source_confidence"}.issubset(INJURY_NEWS_FIELDS)
        )

    def test_injury_news_derivation_does_not_change_match_probabilities(self) -> None:
        teams = load_teams()
        before = match_probabilities(teams["France"], teams["Brazil"])

        build_injury_risk_signals([evidence("a", AvailabilityStatus.INJURED)], updated_at=UPDATED)
        after = match_probabilities(teams["France"], teams["Brazil"])

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
