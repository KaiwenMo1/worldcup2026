#!/usr/bin/env python3
"""Smoke-test tactical evidence normalization and manager refinement dry-run."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion import (  # noqa: E402
    MANUAL_TACTICAL_EVIDENCE_SAMPLE_PATH,
    ManualCsvTacticalEvidenceAdapter,
    apply_manager_skill_updates,
    ingest_tactical_evidence,
    suggest_manager_skill_updates,
    write_manager_skill_updates,
    write_normalized_tactical_evidence,
)


def main() -> None:
    result = ingest_tactical_evidence(ManualCsvTacticalEvidenceAdapter(MANUAL_TACTICAL_EVIDENCE_SAMPLE_PATH))
    assert result.records and not result.issues
    updates = suggest_manager_skill_updates(result.records)
    assert updates and all(update.evidence_ids for update in updates)
    assert any(update.review_status.value == "ready_for_review" for update in updates)
    assert any(update.review_status.value == "needs_human_review" for update in updates)
    assert not apply_manager_skill_updates(updates, result.records).written_files
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        assert not write_normalized_tactical_evidence(result.records, root / "evidence.csv")
        assert not write_manager_skill_updates(updates, root / "updates.csv")
    print(
        f"Manager refinement smoke test passed: evidence={len(result.records)}, "
        f"suggestions={len(updates)}, ready={sum(update.review_status.value == 'ready_for_review' for update in updates)}"
    )


if __name__ == "__main__":
    main()
