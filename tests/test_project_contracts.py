from __future__ import annotations

import csv
import unittest
from pathlib import Path

from app.intelligence import canonical_team, compact_text
from scripts.predict_worldcup import (
    Standing,
    Team,
    align_score_to_outcome,
    match_probabilities,
    scoreline_distribution,
    select_knockout_teams,
)


ROOT = Path(__file__).resolve().parents[1]


def read_csv(name: str) -> list[dict[str, str]]:
    with (ROOT / "data" / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def team(name: str, rank: int = 50) -> Team:
    return Team(
        name=name,
        confederation="UEFA",
        rank=rank,
        host=False,
        world_cup_pedigree=3,
    )


class DataContractTests(unittest.TestCase):
    def test_field_contains_48_unique_teams_in_12_groups(self) -> None:
        teams = read_csv("teams.csv")
        groups = read_csv("groups.csv")
        team_names = {row["team"] for row in teams}

        self.assertEqual(len(teams), 48)
        self.assertEqual(len(team_names), 48)
        self.assertEqual({row["team"] for row in groups}, team_names)

        grouped: dict[str, list[str]] = {}
        for row in groups:
            grouped.setdefault(row["group"], []).append(row["team"])

        self.assertEqual(set(grouped), set("ABCDEFGHIJKL"))
        self.assertTrue(all(len(group) == 4 for group in grouped.values()))

    def test_fixture_schedule_has_the_104_match_contract_when_present(self) -> None:
        fixture_path = ROOT / "data" / "fixtures.csv"
        if not fixture_path.exists():
            self.skipTest("Fixture schedule is optional in the baseline checkout.")

        fixtures = read_csv("fixtures.csv")
        ids = [int(row["match_id"]) for row in fixtures]
        final = fixtures[-1]

        self.assertEqual(ids, list(range(1, 105)))
        self.assertEqual(final["stage"], "Final")
        self.assertEqual(final["source_a"], "W101")
        self.assertEqual(final["source_b"], "W102")


class PredictionContractTests(unittest.TestCase):
    def test_score_distribution_is_normalized(self) -> None:
        scorelines = scoreline_distribution(team("Alpha"), team("Beta"), max_goals=9)

        self.assertAlmostEqual(sum(probability for _, _, probability in scorelines), 1.0, places=9)
        self.assertTrue(all(probability >= 0 for _, _, probability in scorelines))

    def test_identical_teams_have_symmetric_win_probabilities(self) -> None:
        probabilities = match_probabilities(team("Alpha"), team("Beta"))

        self.assertAlmostEqual(sum(probabilities.values()), 1.0, places=9)
        self.assertAlmostEqual(probabilities["team_a_win"], probabilities["team_b_win"], places=9)

    def test_qualification_selects_24_automatic_and_8_best_thirds(self) -> None:
        group_tables: dict[str, list[Standing]] = {}
        expected_best_thirds: set[str] = set()

        for index, group in enumerate("ABCDEFGHIJKL"):
            third = Standing(team(f"{group} third", rank=30 + index), points=index)
            group_tables[group] = [
                Standing(team(f"{group} winner", rank=1 + index), points=12),
                Standing(team(f"{group} runner-up", rank=13 + index), points=10),
                third,
                Standing(team(f"{group} fourth", rank=80 + index), points=0),
            ]
            if index >= 4:
                expected_best_thirds.add(third.team.name)

        qualified = select_knockout_teams(group_tables)
        qualified_names = {item.name for item in qualified}

        self.assertEqual(len(qualified), 32)
        self.assertTrue(expected_best_thirds.issubset(qualified_names))
        self.assertTrue(all(f"{group} third" not in qualified_names for group in "ABCD"))

    def test_score_alignment_respects_sampled_outcome(self) -> None:
        self.assertEqual(align_score_to_outcome(0, 2, "team_a_win"), (3, 2))
        self.assertEqual(align_score_to_outcome(2, 0, "team_b_win"), (2, 3))
        self.assertEqual(align_score_to_outcome(3, 1, "draw"), (2, 2))


class IntelligenceContractTests(unittest.TestCase):
    def test_common_team_aliases_are_canonicalized(self) -> None:
        self.assertEqual(canonical_team("South Korea"), "Korea Republic")
        self.assertEqual(canonical_team("Ivory Coast"), "Cote d'Ivoire")
        self.assertEqual(canonical_team("Brazil"), "Brazil")

    def test_retrieval_text_is_compacted_to_requested_limit(self) -> None:
        result = compact_text("World Cup " * 20, limit=40)

        self.assertLessEqual(len(result), 40)
        self.assertTrue(result.endswith("..."))


if __name__ == "__main__":
    unittest.main()
