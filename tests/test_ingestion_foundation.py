from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.normalizers import safe_read_csv, safe_write_csv, validate_rows
from app.ingestion.provenance import (
    append_data_quality_issues,
    append_ingestion_run,
    create_ingestion_run,
    load_data_quality_issues,
    load_ingestion_runs,
)
from app.ingestion.schemas import DataQualitySeverity, IngestionStatus, SourceRecord, SourceType
from app.ingestion.source_registry import load_source_registry, upsert_source
from app.ingestion.normalizers import make_data_quality_issue


class IngestionFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def source(self, source_id: str = "manual_test") -> SourceRecord:
        return SourceRecord(
            source_id=source_id,
            source_name="Manual test source",
            source_type=SourceType.MANUAL_CSV,
            reliability_score=0.7,
            requires_api_key=False,
            enabled=True,
        )

    def test_source_registry_is_atomic_unique_and_explicit_to_replace(self) -> None:
        path = self.root / "source_registry.csv"

        first = upsert_source(self.source(), path=path)
        duplicate = upsert_source(self.source(), path=path)
        replacement = upsert_source(
            self.source().model_copy(update={"reliability_score": 0.8}),
            replace=True,
            path=path,
        )
        loaded = load_source_registry(path)

        self.assertTrue(first.ok)
        self.assertFalse(duplicate.ok)
        self.assertTrue(replacement.ok)
        self.assertEqual(len(loaded.valid_records), 1)
        self.assertEqual(loaded.valid_records[0].reliability_score, 0.8)

    def test_source_registry_refuses_to_overwrite_invalid_existing_data(self) -> None:
        path = self.root / "source_registry.csv"
        path.write_text("wrong,header\nbad,row\n", encoding="utf-8")
        original = path.read_text(encoding="utf-8")

        result = upsert_source(self.source(), path=path)

        self.assertFalse(result.ok)
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_safe_csv_read_reports_missing_header_and_extra_values(self) -> None:
        missing_header = self.root / "missing_header.csv"
        missing_header.write_text("", encoding="utf-8")
        malformed = self.root / "malformed.csv"
        malformed.write_text("name,value\nFrance,1,extra\n", encoding="utf-8")

        empty_result = safe_read_csv(missing_header, {"name"})
        malformed_result = safe_read_csv(malformed, {"name", "value"})

        self.assertFalse(empty_result.ok)
        self.assertEqual(empty_result.issues[0].severity, DataQualitySeverity.CRITICAL)
        self.assertEqual(malformed_result.rows[0], {"name": "France", "value": "1"})
        self.assertEqual(malformed_result.issues[0].severity, DataQualitySeverity.WARNING)

    def test_safe_append_refuses_schema_mismatch(self) -> None:
        path = self.root / "audit.csv"
        self.assertTrue(safe_write_csv(path, [{"a": 1}], ["a"], append=True).ok)

        result = safe_write_csv(path, [{"b": 2}], ["b"], append=True)

        self.assertFalse(result.ok)
        self.assertEqual(path.read_text(encoding="utf-8"), "a\n1\n")

    def test_row_validation_keeps_valid_records_and_reports_bad_rows(self) -> None:
        rows = [
            {
                "source_id": "valid",
                "source_name": "Valid",
                "source_type": "manual_csv",
                "reliability_score": 0.8,
                "requires_api_key": False,
                "enabled": True,
            },
            {
                "source_id": "Broken ID",
                "source_name": "",
                "source_type": "manual_csv",
                "reliability_score": 2,
                "requires_api_key": False,
                "enabled": True,
            },
        ]

        result = validate_rows(rows, SourceRecord, file="source.csv")

        self.assertEqual(len(result.valid_records), 1)
        self.assertGreaterEqual(len(result.issues), 3)
        self.assertTrue(all(issue.row_number == 3 for issue in result.issues))

    def test_provenance_logs_are_append_only_and_reload_as_typed_records(self) -> None:
        runs_path = self.root / "ingestion_runs.csv"
        issues_path = self.root / "data_quality_report.csv"
        started = datetime(2026, 6, 11, 12, tzinfo=timezone.utc)
        finished = datetime(2026, 6, 11, 12, 1, tzinfo=timezone.utc)
        run = create_ingestion_run(
            source_id="manual_test",
            script="scripts/test.py",
            status=IngestionStatus.PARTIAL,
            rows_raw=2,
            rows_normalized=1,
            rows_failed=1,
            started_at=started,
            finished_at=finished,
            run_id="run_test",
        )
        issue = make_data_quality_issue(
            file="input.csv",
            run_id=run.run_id,
            row_number=3,
            severity=DataQualitySeverity.ERROR,
            field_name="player_id",
            problem="missing player_id",
        )

        self.assertTrue(append_ingestion_run(run, runs_path).ok)
        self.assertTrue(append_ingestion_run(run.model_copy(update={"run_id": "run_test_2"}), runs_path).ok)
        self.assertTrue(append_data_quality_issues([issue], issues_path).ok)
        self.assertEqual(len(load_ingestion_runs(runs_path).valid_records), 2)
        self.assertEqual(len(load_data_quality_issues(issues_path).valid_records), 1)

    def test_project_source_registry_is_valid(self) -> None:
        loaded = load_source_registry()

        self.assertTrue(loaded.ok)
        source_ids = {record.source_id for record in loaded.valid_records}
        self.assertTrue({"manual_csv", "project_repository", "statsbomb_open_data"}.issubset(source_ids))


if __name__ == "__main__":
    unittest.main()
