"""Small accountable update agent for World Cup tournament state.

The agent follows an observe-plan-act-verify-report loop. It intentionally
uses explicit allowed tools instead of free-form shell/LLM actions.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.agentic_update.schemas import (
    AgentToolPlan,
    AgentToolResult,
    AgenticUpdateConfig,
    AgenticUpdateReport,
    UpdateObservation,
)
from app.ingestion.event_data_ingestion import MATCH_EVENTS_NORMALIZED_PATH, MATCH_SUMMARY_SIGNALS_PATH
from app.ingestion.lineup_ingestion import ACTUAL_LINEUPS_PATH, LINEUP_DELTA_SIGNALS_PATH
from app.tournament_autopilot import (
    FIFA_SNAPSHOT_PATH,
    LIVE_STATE_PATH,
    run_tournament_autopilot,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AGENT_REPORT_PATH = ROOT / "data" / "agentic_update" / "latest_report.json"
DEFAULT_AGENT_RUNS_PATH = ROOT / "data" / "agentic_update" / "update_runs.csv"
RUN_FIELDS = [
    "run_id",
    "created_at",
    "mode",
    "completed_before",
    "completed_after",
    "current_after",
    "live_after",
    "tools_success",
    "tools_failed",
    "warnings",
]
CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env_present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _count_csv_records(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except OSError:
        return 0


def _is_knockout_assignment(row: dict[str, Any]) -> bool:
    stage = str(row.get("stage") or "").strip().casefold()
    return bool(row.get("team_a") and row.get("team_b") and stage not in {"", "group", "first stage", "group stage"})


def observe_tournament_state() -> UpdateObservation:
    live_state = _read_json(LIVE_STATE_PATH)
    completed = live_state.get("completed_matches") or []
    current = live_state.get("current_matches") or []
    snapshot = _read_json(FIFA_SNAPSHOT_PATH)
    snapshot_rows = snapshot.get("Results") if isinstance(snapshot.get("Results"), list) else []
    return UpdateObservation(
        live_state_exists=LIVE_STATE_PATH.exists(),
        live_state_updated_at=live_state.get("updated_at"),
        completed_matches=len(completed),
        current_matches=len(current),
        live_matches=sum(1 for row in current if isinstance(row, dict) and row.get("status") == "live"),
        official_knockout_assignments=sum(1 for row in current if isinstance(row, dict) and _is_knockout_assignment(row)),
        event_rows=_count_csv_records(MATCH_EVENTS_NORMALIZED_PATH),
        match_summary_signals=_count_csv_records(MATCH_SUMMARY_SIGNALS_PATH),
        actual_lineup_rows=_count_csv_records(ACTUAL_LINEUPS_PATH),
        lineup_delta_signals=_count_csv_records(LINEUP_DELTA_SIGNALS_PATH),
        official_snapshot_exists=FIFA_SNAPSHOT_PATH.exists(),
        official_snapshot_match_count=len(snapshot_rows),
        provider_key_configured=_env_present("BALLDONTLIE_API_KEY"),
        event_feed_configured=_env_present("WORLD_CUP_EVENT_FEED_URL"),
        sportmonks_configured=_env_present("SPORTMONKS_API_TOKEN"),
        generated_at=_now(),
    )


def build_update_plan(config: AgenticUpdateConfig, observation: UpdateObservation) -> list[AgentToolPlan]:
    provider_will_run = config.include_provider and observation.provider_key_configured
    event_will_run = config.include_event_feed and observation.event_feed_configured and config.allow_subprocess
    lineup_will_run = config.include_lineups and config.allow_subprocess
    verify_will_run = config.verify and config.allow_subprocess
    return [
        AgentToolPlan(
            tool_id="official_fifa_scores",
            description="Fetch official FIFA calendar scores, persist final results, and refresh live-state outputs.",
            will_run=config.refresh_official,
            requires_network=True,
            reason="Official score refresh is the safest primary source for completed World Cup matches.",
            command_preview=[
                "python",
                "scripts/run_tournament_autopilot.py",
                "--refresh-official",
                *(("--run-arena",) if config.run_arena else ()),
            ],
        ),
        AgentToolPlan(
            tool_id="provider_scores",
            description="Layer optional provider data on top of official results when an API key is configured.",
            will_run=provider_will_run,
            requires_network=True,
            requires_secret=True,
            reason=(
                "BALLDONTLIE_API_KEY is configured."
                if provider_will_run
                else "Skipped unless include_provider is enabled and BALLDONTLIE_API_KEY is configured."
            ),
        ),
        AgentToolPlan(
            tool_id="live_event_feed",
            description="Normalize provider-independent live event rows into match summary signals.",
            will_run=event_will_run,
            requires_network=True,
            requires_secret=_env_present("WORLD_CUP_EVENT_FEED_API_KEY"),
            reason=(
                "WORLD_CUP_EVENT_FEED_URL is configured."
                if event_will_run
                else "Skipped unless a live event feed URL is configured."
            ),
            command_preview=["python", "scripts/sync_live_events.py", "--optional"],
        ),
        AgentToolPlan(
            tool_id="lineups_and_squads",
            description="Refresh observed lineups where possible and rebuild lineup delta signals.",
            will_run=lineup_will_run,
            requires_network=observation.sportmonks_configured,
            requires_secret=observation.sportmonks_configured,
            reason="Keeps confirmed starters and squad-derived availability signals in sync.",
            command_preview=[
                "python scripts/sync_lineups.py --optional --days 10 --max-fixtures 3",
                "python scripts/sync_squads.py --from-existing",
                "python scripts/ingest_lineups.py --from-confirmed-lineups",
            ],
        ),
        AgentToolPlan(
            tool_id="verification",
            description="Run compact project verification after update tools finish.",
            will_run=verify_will_run,
            reason="Verification is enabled for this run." if verify_will_run else "Skipped unless --verify is passed.",
            command_preview=["python", "-m", "unittest", "tests.test_tournament_autopilot", "-v"],
        ),
    ]


def _result(tool_id: str, status: str, started_at: datetime, message: str, metrics: dict[str, Any] | None = None) -> AgentToolResult:
    return AgentToolResult(
        tool_id=tool_id,
        status=status,  # type: ignore[arg-type]
        started_at=started_at,
        finished_at=_now(),
        message=message,
        metrics=metrics or {},
    )


def _run_command(command: list[str], command_runner: CommandRunner | None = None) -> subprocess.CompletedProcess[str]:
    runner = command_runner or (lambda cmd: subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False))
    return runner(command)


def _execute_event_feed(command_runner: CommandRunner | None = None) -> AgentToolResult:
    started = _now()
    completed = _run_command([sys.executable, "scripts/sync_live_events.py", "--optional"], command_runner)
    status = "success" if completed.returncode == 0 else "failed"
    message = (completed.stdout or completed.stderr or "").strip() or f"Exited with code {completed.returncode}"
    return _result("live_event_feed", status, started, message[:1200])


def _execute_lineups(command_runner: CommandRunner | None = None) -> AgentToolResult:
    started = _now()
    commands = [
        [sys.executable, "scripts/sync_lineups.py", "--optional", "--days", "10", "--max-fixtures", "3"],
        [sys.executable, "scripts/sync_squads.py", "--from-existing"],
        [sys.executable, "scripts/ingest_lineups.py", "--from-confirmed-lineups"],
    ]
    messages = []
    for command in commands:
        completed = _run_command(command, command_runner)
        messages.append((completed.stdout or completed.stderr or "").strip())
        if completed.returncode != 0:
            return _result("lineups_and_squads", "failed", started, "\n".join(messages)[-1200:])
    return _result("lineups_and_squads", "success", started, "\n".join(messages)[-1200:] or "Lineup tools completed.")


def _execute_verification(command_runner: CommandRunner | None = None) -> AgentToolResult:
    started = _now()
    completed = _run_command([sys.executable, "-m", "unittest", "tests.test_tournament_autopilot", "-v"], command_runner)
    status = "success" if completed.returncode == 0 else "failed"
    message = (completed.stdout + "\n" + completed.stderr).strip()
    return _result("verification", status, started, message[-1200:])


def _write_report(report: AgenticUpdateReport, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")


def _append_run(report: AgenticUpdateReport, runs_path: Path) -> None:
    runs_path.parent.mkdir(parents=True, exist_ok=True)
    exists = runs_path.exists()
    after = report.observations_after
    with runs_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_FIELDS, lineterminator="\n")
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "run_id": report.run_id,
                "created_at": report.created_at.isoformat(),
                "mode": report.mode,
                "completed_before": report.observations_before.completed_matches,
                "completed_after": after.completed_matches if after else "",
                "current_after": after.current_matches if after else "",
                "live_after": after.live_matches if after else "",
                "tools_success": sum(1 for item in report.results if item.status == "success"),
                "tools_failed": sum(1 for item in report.results if item.status == "failed"),
                "warnings": " | ".join(report.warnings),
            }
        )


def _next_actions(report: AgenticUpdateReport) -> list[str]:
    actions = []
    after = report.observations_after or report.observations_before
    if after.live_matches:
        actions.append("Run the update agent again after the live match finishes so it can become a permanent final result.")
    if not after.event_feed_configured:
        actions.append("Configure WORLD_CUP_EVENT_FEED_URL to let the agent ingest richer live match stats.")
    elif after.event_rows == 0:
        actions.append("The event feed is configured but has not produced normalized match-event rows yet.")
    if not after.sportmonks_configured:
        actions.append("Configure SPORTMONKS_API_TOKEN or keep using confirmed-lineup CSV fallbacks.")
    elif after.actual_lineup_rows == 0:
        actions.append("The lineup provider is configured but no confirmed starter rows have been normalized yet.")
    if any(result.status == "failed" for result in report.results):
        actions.append("Review failed tool output before trusting the latest live-state report.")
    return actions


def run_update_agent(
    config: AgenticUpdateConfig | None = None,
    *,
    command_runner: CommandRunner | None = None,
    write_report: bool = True,
) -> AgenticUpdateReport:
    config = config or AgenticUpdateConfig()
    before = observe_tournament_state()
    plan = build_update_plan(config, before)
    results: list[AgentToolResult] = []
    warnings: list[str] = []

    if not config.apply:
        started = _now()
        results = [_result(item.tool_id, "planned" if item.will_run else "skipped", started, item.reason) for item in plan]
        after = before
    else:
        official_plan = next(item for item in plan if item.tool_id == "official_fifa_scores")
        provider_plan = next(item for item in plan if item.tool_id == "provider_scores")
        started = _now()
        if official_plan.will_run or provider_plan.will_run:
            report = run_tournament_autopilot(
                refresh_official=official_plan.will_run,
                refresh_provider=provider_plan.will_run,
                run_arena=config.run_arena,
                settle_and_evaluate=True,
                hours_ahead=config.hours_ahead,
            )
            warnings.extend(report.warnings)
            results.append(
                _result(
                    "official_fifa_scores",
                    "success",
                    started,
                    "Tournament autopilot completed.",
                    report.as_dict(),
                )
            )
        else:
            results.append(_result("official_fifa_scores", "skipped", started, official_plan.reason))
        if not provider_plan.will_run:
            results.append(_result("provider_scores", "skipped", _now(), provider_plan.reason))
        if next(item for item in plan if item.tool_id == "live_event_feed").will_run:
            results.append(_execute_event_feed(command_runner))
        else:
            event_plan = next(item for item in plan if item.tool_id == "live_event_feed")
            results.append(_result("live_event_feed", "skipped", _now(), event_plan.reason))
        if next(item for item in plan if item.tool_id == "lineups_and_squads").will_run:
            results.append(_execute_lineups(command_runner))
        else:
            lineup_plan = next(item for item in plan if item.tool_id == "lineups_and_squads")
            results.append(_result("lineups_and_squads", "skipped", _now(), lineup_plan.reason))
        if next(item for item in plan if item.tool_id == "verification").will_run:
            results.append(_execute_verification(command_runner))
        else:
            verify_plan = next(item for item in plan if item.tool_id == "verification")
            results.append(_result("verification", "skipped", _now(), verify_plan.reason))
        after = observe_tournament_state()

    report = AgenticUpdateReport(
        run_id=uuid4().hex,
        mode="apply" if config.apply else "dry_run",
        created_at=_now(),
        observations_before=before,
        plan=plan,
        results=results,
        observations_after=after,
        warnings=warnings,
        next_actions=[],
    )
    report.next_actions = _next_actions(report)
    if write_report:
        _write_report(report, Path(config.report_path or DEFAULT_AGENT_REPORT_PATH))
        _append_run(report, Path(config.runs_path or DEFAULT_AGENT_RUNS_PATH))
    return report
