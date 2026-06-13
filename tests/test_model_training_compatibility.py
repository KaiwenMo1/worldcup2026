from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_PATH = str(ROOT / "scripts")
sys.path.insert(0, SCRIPTS_PATH)
try:
    import train_model
finally:
    sys.path.remove(SCRIPTS_PATH)


class ReadOnlyDixonColesModel:
    def __init__(
        self,
        goals_home,
        goals_away,
        teams_home,
        teams_away,
        weights=None,
        neutral_venue=None,
    ) -> None:
        self.goals_home = np.asarray(goals_home)
        self.goals_away = np.asarray(goals_away)
        self.teams_home = np.asarray(teams_home)
        self.teams_away = np.asarray(teams_away)
        self.weights = np.asarray(weights)
        self.neutral_venue = np.asarray(neutral_venue)
        self.home_idx = np.arange(len(self.goals_home), dtype=np.int64)
        self.away_idx = np.arange(len(self.goals_home), dtype=np.int64)
        self._params = np.ones(4, dtype=float)

        for values in (
            self.goals_home,
            self.goals_away,
            self.weights,
            self.neutral_venue,
            self.home_idx,
            self.away_idx,
            self._params,
        ):
            values.flags.writeable = False

    def fit(self) -> None:
        for values in (
            self.goals_home,
            self.goals_away,
            self.weights,
            self.neutral_venue,
            self.home_idx,
            self.away_idx,
            self._params,
        ):
            if not values.flags.writeable or not values.flags.c_contiguous:
                raise ValueError("buffer source array is read-only")


class DixonColesCompatibilityTests(unittest.TestCase):
    def test_fit_converts_read_only_library_arrays_to_writable_memory(self) -> None:
        frame = pd.DataFrame(
            {
                "team_a_goals": [2, 1],
                "team_b_goals": [0, 1],
                "team_a": ["France", "Brazil"],
                "team_b": ["Brazil", "France"],
                "sample_weight": [1.0, 0.9],
                "neutral": [1, 1],
            }
        )

        with patch.object(train_model.pb.models, "DixonColesGoalModel", ReadOnlyDixonColesModel):
            model = train_model.fit_dixon_coles(frame)

        self.assertTrue(model.goals_home.flags.writeable)
        self.assertTrue(model.goals_away.flags.writeable)
        self.assertTrue(model.weights.flags.writeable)
        self.assertTrue(model.neutral_venue.flags.writeable)
        self.assertTrue(model.home_idx.flags.writeable)
        self.assertTrue(model.away_idx.flags.writeable)
        self.assertTrue(model._params.flags.writeable)


if __name__ == "__main__":
    unittest.main()
