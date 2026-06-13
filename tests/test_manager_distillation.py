from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.manager_distillation import (
    ClaimType,
    EvidenceCategory,
    EvidenceRecord,
    build_manager_skill,
    export_tactical_json,
    load_evidence_directory,
    to_tactical_manager_skill,
    validate_manager_skill,
    write_generated_skill,
)


def evidence(
    claim_id: str,
    claim_type: ClaimType,
    claim_text: str,
    *,
    index: int,
    condition_code: str | None = None,
    parameters: dict | None = None,
    normalized_value: str | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f"{claim_id}_{index}",
        manager_id="test_manager",
        category=EvidenceCategory.DECISION_RECORDS,
        source_id=f"source_{index}",
        title=f"Observed source {index}",
        observed_at=date(2026, 5, index),
        match_id=f"match_{index}",
        claim_id=claim_id,
        claim_type=claim_type,
        claim_text=claim_text,
        normalized_value=normalized_value,
        condition_code=condition_code,
        parameters=parameters or {},
        reliability_score=0.8,
        predictive_power=True,
        distinctive=True,
    )


def passing_records() -> list[EvidenceRecord]:
    claims = [
        ("identity", ClaimType.TACTICAL_IDENTITY, "Uses controlled aggression around selected triggers.", None, {}, "controlled_aggression"),
        ("formation", ClaimType.PREFERRED_FORMATION, "Frequently starts from a 4-3-3.", None, {}, "4-3-3"),
        ("build_up", ClaimType.BUILD_UP_RULE, "Creates a spare player in the first build-up line.", None, {}, "first_line_spare"),
        ("lead", ClaimType.GAME_STATE_RULE, "Protects central zones when leading after 65.", "leading_after_minute", {"minute": 65}, None),
        ("trail", ClaimType.GAME_STATE_RULE, "Adds an attacking runner when trailing after 55.", "trailing_after_minute", {"minute": 55}, None),
        ("tie", ClaimType.GAME_STATE_RULE, "Introduces a fresh creator when tied after 70.", "tied_after_minute", {"minute": 70}, None),
        ("press", ClaimType.GAME_STATE_RULE, "Uses a first-line spare against a high press.", "opponent_high_press", {}, None),
        ("knockout", ClaimType.GAME_STATE_RULE, "Preserves rest defense in knockout matches.", "knockout_match", {}, None),
    ]
    return [
        evidence(claim_id, claim_type, text, index=index, condition_code=condition, parameters=params, normalized_value=value)
        for claim_id, claim_type, text, condition, params, value in claims
        for index in (1, 2)
    ]


class ManagerDistillationTests(unittest.TestCase):
    def test_builder_promotes_only_triple_validated_recurring_claims(self) -> None:
        records = passing_records()
        records.append(
            EvidenceRecord(
                **{
                    **evidence("weak", ClaimType.TRANSITION_RULE, "One-off transition idea.", index=1).model_dump(),
                    "predictive_power": False,
                }
            )
        )

        skill = build_manager_skill(
            manager_id="test_manager",
            manager_name="Test Manager",
            team="Test Team",
            records=records,
        )

        self.assertEqual(len(skill.core_tactical_models), 3)
        self.assertEqual(len(skill.decision_heuristics), 5)
        self.assertEqual([claim.claim_id for claim in skill.low_confidence_heuristics], ["weak"])
        self.assertIn("predictive power", skill.low_confidence_heuristics[0].validation.reason)

    def test_conflicting_repeated_claim_is_downgraded(self) -> None:
        records = [
            evidence("conflict", ClaimType.TRANSITION_RULE, "Attack quickly after regains.", index=1),
            evidence("conflict", ClaimType.TRANSITION_RULE, "Slow the match after regains.", index=2),
        ]

        skill = build_manager_skill(
            manager_id="test_manager",
            manager_name="Test Manager",
            team="Test Team",
            records=records,
        )

        self.assertEqual(len(skill.core_tactical_models), 0)
        self.assertIn("claim consistency", skill.low_confidence_heuristics[0].validation.reason)

    def test_passing_draft_exports_to_existing_tactical_contract(self) -> None:
        skill = build_manager_skill(
            manager_id="test_manager",
            manager_name="Test Manager",
            team="Test Team",
            records=passing_records(),
        )
        report = validate_manager_skill(skill)
        tactical = to_tactical_manager_skill(skill, report)

        self.assertEqual(report.status, "PASS")
        self.assertEqual(tactical.status, "evidence_backed")
        self.assertEqual(len(tactical.decision_rules), 5)
        self.assertTrue(tactical.source_refs)

    def test_export_does_not_overwrite_existing_skill_without_apply(self) -> None:
        skill = build_manager_skill(
            manager_id="test_manager",
            manager_name="Test Manager",
            team="Test Team",
            records=passing_records(),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_dir = root / "manager_skills"
            generated = root / "generated"
            target_dir.mkdir()
            existing = target_dir / "test_manager.json"
            existing.write_text('{"existing": true}\n', encoding="utf-8")

            preview = export_tactical_json(skill, target_dir=target_dir, generated_root=generated)

            self.assertEqual(existing.read_text(encoding="utf-8"), '{"existing": true}\n')
            self.assertEqual(preview.name, "manager_skill.preview.json")
            self.assertTrue(preview.exists())

    def test_generated_skill_contains_skill_and_validation_artifacts(self) -> None:
        skill = build_manager_skill(
            manager_id="test_manager",
            manager_name="Test Manager",
            team="Test Team",
            records=passing_records(),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = write_generated_skill(skill, output_root=Path(directory))

            self.assertTrue((output / "SKILL.md").exists())
            self.assertTrue((output / "manager_skill_draft.json").exists())
            self.assertIn("Status: **PASS**", (output / "validation_report.md").read_text(encoding="utf-8"))

    def test_evidence_loader_reads_csv_and_markdown_and_reports_bad_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "evidence.csv"
            fields = [
                "evidence_id",
                "manager_id",
                "category",
                "source_id",
                "title",
                "claim_id",
                "claim_type",
                "claim_text",
                "reliability_score",
                "predictive_power",
                "distinctive",
                "parameters_json",
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "evidence_id": "good_1",
                        "manager_id": "test_manager",
                        "category": "tactical_reports",
                        "source_id": "source_1",
                        "title": "Good source",
                        "claim_id": "good",
                        "claim_type": "tactical_identity",
                        "claim_text": "A valid claim.",
                        "reliability_score": "0.8",
                        "predictive_power": "true",
                        "distinctive": "true",
                        "parameters_json": "{}",
                    }
                )
                writer.writerow(
                    {
                        "evidence_id": "bad_1",
                        "manager_id": "test_manager",
                        "category": "tactical_reports",
                        "source_id": "source_2",
                        "title": "Bad source",
                        "claim_id": "bad",
                        "claim_type": "tactical_identity",
                        "claim_text": "Invalid parameters.",
                        "reliability_score": "0.8",
                        "predictive_power": "true",
                        "distinctive": "true",
                        "parameters_json": "not-json",
                    }
                )
            (root / "tactical_reports_notes.md").write_text("# Match Notes\n\nObserved tactical context.", encoding="utf-8")
            (root / "README.md").write_text("# Folder Instructions\n\nNot manager evidence.", encoding="utf-8")

            loaded = load_evidence_directory(root, "test_manager")

            self.assertEqual(len(loaded.records), 1)
            self.assertEqual(len(loaded.documents), 1)
            self.assertEqual(len(loaded.issues), 1)


if __name__ == "__main__":
    unittest.main()
