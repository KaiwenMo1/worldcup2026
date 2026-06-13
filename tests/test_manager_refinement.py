from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.ingestion.tactical_article_ingestion import (
    ContentOrigin,
    ManagerSkillUpdate,
    ManualCsvTacticalEvidenceAdapter,
    TacticalEvidenceRecord,
    TacticalEvidenceType,
    TacticalTopic,
    UpdateReviewStatus,
    apply_manager_skill_updates,
    ingest_tactical_evidence,
    load_manager_skill_updates,
    load_normalized_tactical_evidence,
    normalize_evidence_type,
    normalize_tactical_topic,
    suggest_manager_skill_updates,
    write_manager_skill_updates,
    write_normalized_tactical_evidence,
)
from app.tactics.schemas import ManagerSkill


ROOT = Path(__file__).resolve().parents[1]


def evidence(
    evidence_id: str,
    *,
    topic: TacticalTopic = TacticalTopic.BUILD_UP,
    proposed_value: str = "first_line_spare",
    source_id: str = "source_a",
    match_id: str = "match_a",
    origin: ContentOrigin = ContentOrigin.MANUAL,
    reviewed: bool = True,
) -> TacticalEvidenceRecord:
    return TacticalEvidenceRecord(
        evidence_id=evidence_id,
        manager_id="france_deschamps",
        manager_name="Didier Deschamps",
        team="France",
        evidence_type=TacticalEvidenceType.MATCH_REPORT,
        tactical_topic=topic,
        claim_text=f"Evidence for {proposed_value}.",
        proposed_value=proposed_value,
        source_id=source_id,
        source_title=f"Source {source_id}",
        source_kind="match_report",
        published_at=date(2026, 5, 10),
        match_id=match_id,
        source_quality=0.8,
        confidence=0.75,
        content_origin=origin,
        reviewed_by_human=reviewed,
        recurrence_key=f"recurrence_{topic.value}",
        data_quality="manual_curated_evidence",
    )


class ManagerRefinementTests(unittest.TestCase):
    def test_evidence_type_and_topic_aliases_are_normalized(self) -> None:
        self.assertEqual(normalize_evidence_type("post-match report"), TacticalEvidenceType.MATCH_REPORT)
        self.assertEqual(normalize_evidence_type("manager interview"), TacticalEvidenceType.PRESS_CONFERENCE)
        self.assertEqual(normalize_tactical_topic("build-up"), TacticalTopic.BUILD_UP)
        self.assertEqual(normalize_tactical_topic("defensive block"), TacticalTopic.DEFENSIVE_SHAPE)

    def test_manual_adapter_keeps_valid_rows_and_reports_bad_scores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.csv"
            fields = [
                "manager_id",
                "manager_name",
                "team",
                "evidence_type",
                "tactical_topic",
                "claim_text",
                "proposed_value",
                "source_id",
                "source_title",
                "source_reliability",
                "directness",
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "manager_id": "france_deschamps",
                        "manager_name": "Didier Deschamps",
                        "team": "France",
                        "evidence_type": "article",
                        "tactical_topic": "press",
                        "claim_text": "Selective pressure.",
                        "proposed_value": "selective",
                        "source_id": "valid",
                        "source_title": "Valid source",
                        "source_reliability": "0.8",
                        "directness": "0.8",
                    }
                )
                writer.writerow(
                    {
                        "manager_id": "france_deschamps",
                        "manager_name": "Didier Deschamps",
                        "team": "France",
                        "evidence_type": "article",
                        "tactical_topic": "press",
                        "claim_text": "Bad score.",
                        "proposed_value": "bad",
                        "source_id": "bad",
                        "source_title": "Bad source",
                        "source_reliability": "not-a-number",
                        "directness": "0.8",
                    }
                )

            result = ingest_tactical_evidence(ManualCsvTacticalEvidenceAdapter(path))

            self.assertEqual(len(result.records), 1)
            self.assertGreaterEqual(len(result.issues), 1)
            self.assertTrue(all(issue.row_number == 3 for issue in result.issues))

    def test_recurring_claim_is_ready_and_references_every_evidence_id(self) -> None:
        records = [
            evidence("build_1", source_id="source_a", match_id="match_a"),
            evidence("build_2", source_id="source_b", match_id="match_b"),
        ]

        update = suggest_manager_skill_updates(records)[0]

        self.assertEqual(update.review_status, UpdateReviewStatus.READY_FOR_REVIEW)
        self.assertEqual(update.evidence_ids, "build_1|build_2")
        self.assertEqual(update.target_path, "tactical_identity.build_up")

    def test_conflicts_and_llm_generated_claims_cannot_be_ready(self) -> None:
        conflicting = suggest_manager_skill_updates(
            [
                evidence("formation_a", topic=TacticalTopic.PREFERRED_FORMATION, proposed_value="3-4-2-1"),
                evidence(
                    "formation_b",
                    topic=TacticalTopic.PREFERRED_FORMATION,
                    proposed_value="4-2-3-1",
                    source_id="source_b",
                    match_id="match_b",
                ),
            ]
        )
        llm = suggest_manager_skill_updates(
            [
                evidence(
                    "llm_1",
                    topic=TacticalTopic.TRANSITION_ACTION,
                    origin=ContentOrigin.LLM_GENERATED,
                    reviewed=False,
                ),
                evidence(
                    "llm_2",
                    topic=TacticalTopic.TRANSITION_ACTION,
                    source_id="source_b",
                    match_id="match_b",
                    origin=ContentOrigin.LLM_GENERATED,
                    reviewed=False,
                ),
            ]
        )[0]

        self.assertTrue(all(update.review_status == UpdateReviewStatus.CONFLICTING_EVIDENCE for update in conflicting))
        self.assertEqual(llm.review_status, UpdateReviewStatus.NEEDS_HUMAN_REVIEW)

    def test_apply_rederives_eligibility_instead_of_trusting_forged_status(self) -> None:
        llm_record = evidence(
            "llm_1",
            topic=TacticalTopic.TRANSITION_ACTION,
            origin=ContentOrigin.LLM_GENERATED,
            reviewed=False,
        )
        suggested = suggest_manager_skill_updates([llm_record])[0]
        forged = suggested.model_copy(update={"review_status": UpdateReviewStatus.READY_FOR_REVIEW})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_path = root / "france_deschamps.json"
            original = (ROOT / "data" / "manager_skills" / "france_deschamps.json").read_text(encoding="utf-8")
            skill_path.write_text(original, encoding="utf-8")

            result = apply_manager_skill_updates([forged], [llm_record], apply=True, manager_skills_dir=root)

            self.assertFalse(result.written_files)
            self.assertEqual(skill_path.read_text(encoding="utf-8"), original)

    def test_dry_run_never_overwrites_and_apply_validates_evidence_backed_update(self) -> None:
        records = [
            evidence("build_1", source_id="source_a", match_id="match_a"),
            evidence("build_2", source_id="source_b", match_id="match_b"),
        ]
        updates = suggest_manager_skill_updates(records)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_path = root / "france_deschamps.json"
            original = (ROOT / "data" / "manager_skills" / "france_deschamps.json").read_text(encoding="utf-8")
            skill_path.write_text(original, encoding="utf-8")

            dry = apply_manager_skill_updates(updates, records, manager_skills_dir=root)
            self.assertFalse(dry.written_files)
            self.assertEqual(skill_path.read_text(encoding="utf-8"), original)

            applied = apply_manager_skill_updates(updates, records, apply=True, manager_skills_dir=root)
            payload = json.loads(skill_path.read_text(encoding="utf-8"))
            validated = ManagerSkill.model_validate(payload)

            self.assertFalse(applied.issues)
            self.assertEqual(validated.tactical_identity.build_up, "first_line_spare")
            self.assertTrue(any("evidence: build_1|build_2" in note for note in validated.evidence_notes))
            self.assertTrue({"source_a", "source_b"}.issubset({ref.source_id for ref in validated.source_refs}))

    def test_normalized_and_update_files_round_trip(self) -> None:
        records = [
            evidence("build_1", source_id="source_a", match_id="match_a"),
            evidence("build_2", source_id="source_b", match_id="match_b"),
        ]
        updates: list[ManagerSkillUpdate] = suggest_manager_skill_updates(records)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_issues = [
                *write_normalized_tactical_evidence(records, root / "evidence.csv"),
                *write_manager_skill_updates(updates, root / "updates.csv"),
            ]
            loaded_records, record_issues = load_normalized_tactical_evidence(root / "evidence.csv")
            loaded_updates, update_issues = load_manager_skill_updates(root / "updates.csv")

            self.assertFalse(write_issues or record_issues or update_issues)
            self.assertEqual(len(loaded_records), 2)
            self.assertEqual(loaded_updates[0].evidence_ids, "build_1|build_2")


if __name__ == "__main__":
    unittest.main()
