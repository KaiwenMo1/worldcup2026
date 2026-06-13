from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.tactics import manager_skills
from app.tactics.manager_skills import (
    ManagerSkillDataError,
    generate_manager_plan,
    list_manager_registry,
    list_manager_skills,
    load_manager_skill,
    load_team_manager_record,
    load_team_manager_skill,
)
from app.tactics.schemas import ConditionCode, MatchContext
from scripts.predict_worldcup import load_teams, match_probabilities


class ManagerSkillTests(unittest.TestCase):
    def test_all_manager_files_validate_and_derived_baselines_stay_prototypes(self) -> None:
        skills = list_manager_skills()
        derived = [skill for skill in skills if skill.version == "0.1-derived"]
        observed = [skill for skill in skills if skill.version == "0.2-statsbomb-observed"]

        self.assertEqual(len(skills), 48)
        self.assertEqual(len({skill.team for skill in skills}), 48)
        self.assertEqual(len(derived), 18)
        self.assertEqual(len(observed), 30)
        self.assertTrue(all(skill.status == "manual_prototype" for skill in derived))
        self.assertTrue(
            all(any("not observed manager behavior" in note for note in skill.evidence_notes) for skill in derived)
        )
        self.assertTrue(all(any("StatsBomb" in note for note in skill.evidence_notes) for skill in observed))

    def test_france_manager_lookup(self) -> None:
        skill = load_team_manager_skill("France")

        self.assertIsNotNone(skill)
        self.assertEqual(skill.manager_id, "france_deschamps")
        self.assertEqual(skill.team, "France")

    def test_current_manager_registry_covers_all_tournament_teams(self) -> None:
        registry = list_manager_registry()

        self.assertEqual(len(registry), 48)
        self.assertEqual(len({row["team"] for row in registry}), 48)
        self.assertEqual(load_team_manager_record("Brazil")["manager_name"], "Carlo Ancelotti")
        self.assertTrue(all(row["source"] and row["last_verified"] for row in registry))

    def test_match_context_triggers_only_matching_rules(self) -> None:
        context = MatchContext(
            match_state="leading",
            minute=70,
            opponent_high_line=True,
            opponent_recovery_defender_score=62,
            opponent_midfield_control=False,
            opponent_possession_share=0.51,
        )

        plan = generate_manager_plan("France", "Brazil", context)
        applied_codes = {rule.condition_code for rule in plan.applied_rules}
        contingent_codes = {rule.condition_code for rule in plan.contingent_rules}

        self.assertEqual(
            applied_codes,
            {ConditionCode.OPPONENT_HIGH_LINE, ConditionCode.LEADING_AFTER_MINUTE},
        )
        self.assertEqual(contingent_codes, {ConditionCode.OPPONENT_MIDFIELD_CONTROL})
        self.assertFalse(plan.fallback_used)
        self.assertEqual(plan.data_quality, "evidence_backed")

    def test_missing_manager_returns_neutral_fallback_plan(self) -> None:
        self.assertIsNone(load_team_manager_skill("Unknown FC"))

        plan = generate_manager_plan("Unknown FC", "France")

        self.assertTrue(plan.fallback_used)
        self.assertEqual(plan.base_plan, "neutral_balanced_plan")
        self.assertEqual(plan.confidence.level, "low")
        self.assertIn("No manager skill is available", plan.fallback_note)

    def test_missing_manager_skill_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(manager_skills, "MANAGER_SKILLS_DIR", Path(directory)):
                self.assertIsNone(load_manager_skill("missing_manager"))

    def test_malformed_manager_file_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken_manager.json"
            path.write_text(json.dumps({"manager_id": "broken_manager", "team": "Broken"}), encoding="utf-8")

            with patch.object(manager_skills, "MANAGER_SKILLS_DIR", Path(directory)):
                with self.assertRaisesRegex(ManagerSkillDataError, "Invalid manager skill file"):
                    load_manager_skill("broken_manager")

    def test_manager_plan_does_not_change_existing_match_probabilities(self) -> None:
        teams = load_teams()
        before = match_probabilities(teams["France"], teams["Brazil"])

        generate_manager_plan(
            "France",
            "Brazil",
            MatchContext(opponent_high_line=True, opponent_recovery_defender_score=60),
        )
        after = match_probabilities(teams["France"], teams["Brazil"])

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
