from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agentic_update import AgenticUpdateConfig, build_update_plan, observe_tournament_state, run_update_agent


class AgenticUpdateTests(unittest.TestCase):
    def test_dry_run_builds_accountable_plan_without_running_tools(self) -> None:
        observation = observe_tournament_state()
        plan = build_update_plan(AgenticUpdateConfig(), observation)

        self.assertIn("official_fifa_scores", {item.tool_id for item in plan})
        self.assertTrue(next(item for item in plan if item.tool_id == "official_fifa_scores").will_run)

        report = run_update_agent(AgenticUpdateConfig(), write_report=False)
        self.assertEqual(report.mode, "dry_run")
        self.assertTrue(all(result.status in {"planned", "skipped"} for result in report.results))
        self.assertEqual(report.observations_before.completed_matches, report.observations_after.completed_matches)

    def test_apply_mode_can_run_allowed_subprocess_tools_with_audit_report(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "latest_report.json"
            runs_path = Path(directory) / "runs.csv"
            with patch.dict("os.environ", {"WORLD_CUP_EVENT_FEED_URL": "https://example.com/events"}, clear=False):
                report = run_update_agent(
                    AgenticUpdateConfig(
                        apply=True,
                        refresh_official=False,
                        include_event_feed=True,
                        include_lineups=True,
                        verify=True,
                        report_path=str(report_path),
                        runs_path=str(runs_path),
                    ),
                    command_runner=fake_runner,
                )

            self.assertEqual(report.mode, "apply")
            self.assertTrue(any("sync_live_events.py" in " ".join(command) for command in calls))
            self.assertTrue(any("sync_lineups.py" in " ".join(command) for command in calls))
            self.assertTrue(report_path.exists())
            self.assertTrue(runs_path.exists())
            persisted = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["run_id"], report.run_id)

    def test_provider_tool_requires_explicit_flag_and_key(self) -> None:
        observation = observe_tournament_state()
        with patch.dict("os.environ", {"BALLDONTLIE_API_KEY": "token"}, clear=False):
            without_flag = build_update_plan(AgenticUpdateConfig(include_provider=False), observation)
            with_flag = build_update_plan(AgenticUpdateConfig(include_provider=True), observe_tournament_state())

        self.assertFalse(next(item for item in without_flag if item.tool_id == "provider_scores").will_run)
        self.assertTrue(next(item for item in with_flag if item.tool_id == "provider_scores").will_run)


if __name__ == "__main__":
    unittest.main()
