"""Application service for exposing Prediction Arena workflows through FastAPI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.calibration import run_prediction_calibration
from app.prediction_arena.prediction_runner import MODEL_PREDICTIONS_PATH, run_prediction_arena
from app.prediction_arena.public_card_renderer import (
    CARDS_DIR,
    PUBLIC_CARDS_LEDGER_PATH,
    build_public_card_from_records,
    publish_public_prediction_card,
    render_public_card_markdown,
)
from app.prediction_arena.public_ledger import (
    PRE_MATCH_PREDICTIONS_PATH,
    load_predictions,
    lock_prediction,
)
from app.prediction_arena.schemas import ENTERTAINMENT_DISCLAIMER, PredictionRecord
from app.prediction_arena.virtual_scoreboard import (
    VIRTUAL_RESULTS_PATH,
    evaluate_arena_predictions,
    load_virtual_results,
    settle_match_predictions,
)


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    return value


def _records_for_match(match_id: str, paths: list[Path]) -> list[PredictionRecord]:
    return [
        record
        for path in paths
        for record in load_predictions(path)
        if record.match_id == match_id
    ]


def _latest_version(records: list[PredictionRecord]) -> int | None:
    return max((record.version for record in records), default=None)


def _public_card(match_id: str, *, cards_dir: Path) -> dict[str, Any]:
    filename = re.sub(r"[^a-zA-Z0-9_.-]+", "-", match_id.strip()).strip("-.") or "match"
    path = cards_dir / f"{filename}.md"
    if not path.exists():
        return {"available": False, "path": None, "markdown": None}
    return {
        "available": True,
        "path": str(path),
        "markdown": path.read_text(encoding="utf-8"),
    }


def get_arena_match(
    match_id: str,
    *,
    pre_match_path: Path = PRE_MATCH_PREDICTIONS_PATH,
    model_path: Path = MODEL_PREDICTIONS_PATH,
    results_path: Path = VIRTUAL_RESULTS_PATH,
    cards_dir: Path = CARDS_DIR,
) -> dict[str, Any]:
    """Return the latest persisted Arena view without requiring every artifact."""
    records = _records_for_match(match_id, [pre_match_path, model_path])
    version = _latest_version(records)
    latest = [record for record in records if record.version == version] if version else []
    settlements = [row for row in load_virtual_results(results_path) if row.match_id == match_id]
    warnings = []
    if not latest:
        warnings.append("No saved Prediction Arena run exists for this match.")
    if not any(record.agent_name == "Base Model" for record in latest):
        warnings.append("Base model output is unavailable for the latest run.")
    if not any(record.agent_name == "Final Forecast Agent" for record in latest):
        warnings.append("Final forecast output is unavailable for the latest run.")
    card = _public_card(match_id, cards_dir=cards_dir)
    if not card["available"]:
        warnings.append("No public prediction card has been published yet.")

    team_a = latest[0].team_a if latest else None
    team_b = latest[0].team_b if latest else None
    stage = latest[0].stage.value if latest else None
    return {
        "found": bool(latest),
        "match_id": match_id,
        "team_a": team_a,
        "team_b": team_b,
        "stage": stage,
        "version": version,
        "records": _dump(sorted(latest, key=lambda record: record.agent_name)),
        "settlements": _dump(settlements),
        "public_card": card,
        "warnings": warnings,
        "entertainment_disclaimer": ENTERTAINMENT_DISCLAIMER,
    }


def run_arena_match(
    match_id: str,
    team_a: str,
    team_b: str,
    stage: str,
    *,
    lock: bool = False,
    publish_card: bool = False,
    pre_match_path: Path = PRE_MATCH_PREDICTIONS_PATH,
    model_path: Path = MODEL_PREDICTIONS_PATH,
    results_path: Path = VIRTUAL_RESULTS_PATH,
    cards_dir: Path = CARDS_DIR,
    card_ledger_path: Path = PUBLIC_CARDS_LEDGER_PATH,
    forecast_provider: Any | None = None,
    tactical_brief_provider: Any | None = None,
) -> dict[str, Any]:
    """Run every Arena agent and return both the rich run and persisted view."""
    run = run_prediction_arena(
        match_id,
        team_a,
        team_b,
        stage,
        lock=lock,
        publish_card=publish_card,
        pre_match_path=pre_match_path,
        model_path=model_path,
        cards_dir=cards_dir,
        card_ledger_path=card_ledger_path,
        forecast_provider=forecast_provider,
        tactical_brief_provider=tactical_brief_provider,
    )
    return {
        "run": _dump(run),
        "match": get_arena_match(
            match_id,
            pre_match_path=pre_match_path,
            model_path=model_path,
            results_path=results_path,
            cards_dir=cards_dir,
        ),
        "entertainment_disclaimer": ENTERTAINMENT_DISCLAIMER,
    }


def lock_arena_match(
    match_id: str,
    *,
    pre_match_path: Path = PRE_MATCH_PREDICTIONS_PATH,
    model_path: Path = MODEL_PREDICTIONS_PATH,
    results_path: Path = VIRTUAL_RESULTS_PATH,
    cards_dir: Path = CARDS_DIR,
) -> dict[str, Any]:
    """Lock every record in the latest saved version of a match."""
    records = _records_for_match(match_id, [pre_match_path, model_path])
    version = _latest_version(records)
    if version is None:
        raise LookupError(f"No saved Prediction Arena run exists for match {match_id!r}.")
    locked = []
    for path in (pre_match_path, model_path):
        for record in load_predictions(path):
            if record.match_id == match_id and record.version == version:
                locked.append(lock_prediction(record.prediction_id, path))
    return {
        "locked_records": _dump(locked),
        "match": get_arena_match(
            match_id,
            pre_match_path=pre_match_path,
            model_path=model_path,
            results_path=results_path,
            cards_dir=cards_dir,
        ),
        "entertainment_disclaimer": ENTERTAINMENT_DISCLAIMER,
    }


def publish_arena_card(
    match_id: str,
    *,
    pre_match_path: Path = PRE_MATCH_PREDICTIONS_PATH,
    model_path: Path = MODEL_PREDICTIONS_PATH,
    results_path: Path = VIRTUAL_RESULTS_PATH,
    cards_dir: Path = CARDS_DIR,
    card_ledger_path: Path = PUBLIC_CARDS_LEDGER_PATH,
) -> dict[str, Any]:
    """Publish the latest saved Arena version as a public markdown card."""
    card = build_public_card_from_records(match_id, ledger_path=pre_match_path)
    path = publish_public_prediction_card(card, cards_dir=cards_dir, ledger_path=card_ledger_path)
    return {
        "card": _dump(card),
        "card_path": str(path),
        "markdown": render_public_card_markdown(card),
        "match": get_arena_match(
            match_id,
            pre_match_path=pre_match_path,
            model_path=model_path,
            results_path=results_path,
            cards_dir=cards_dir,
        ),
        "entertainment_disclaimer": ENTERTAINMENT_DISCLAIMER,
    }


def settle_arena_match(
    match_id: str,
    actual_score: str,
    regular_time_result: str,
    qualification_result: str | None = None,
    *,
    pre_match_path: Path = PRE_MATCH_PREDICTIONS_PATH,
    model_path: Path = MODEL_PREDICTIONS_PATH,
    results_path: Path = VIRTUAL_RESULTS_PATH,
    cards_dir: Path = CARDS_DIR,
) -> dict[str, Any]:
    """Settle a match and return the refreshed entertainment-only scoreboard."""
    results = settle_match_predictions(
        match_id,
        actual_score=actual_score,
        actual_regular_time_result=regular_time_result,
        actual_qualification_result=qualification_result,
        prediction_paths=[pre_match_path, model_path],
        results_path=results_path,
    )
    return {
        "results": _dump(results),
        "leaderboard": evaluate_arena_predictions(results_path),
        "match": get_arena_match(
            match_id,
            pre_match_path=pre_match_path,
            model_path=model_path,
            results_path=results_path,
            cards_dir=cards_dir,
        ),
        "entertainment_disclaimer": ENTERTAINMENT_DISCLAIMER,
    }


def get_arena_leaderboard(*, results_path: Path = VIRTUAL_RESULTS_PATH) -> dict[str, Any]:
    """Return the virtual scoreboard with its explicit entertainment-only contract."""
    return evaluate_arena_predictions(results_path)


def get_arena_calibration(
    *,
    prediction_paths: list[Path] | None = None,
    results_path: Path = VIRTUAL_RESULTS_PATH,
    scoreline_path: Path | None = None,
    upset_path: Path | None = None,
    performance_path: Path | None = None,
) -> dict[str, Any]:
    """Build and serialize current calibration reports, including empty reports."""
    kwargs: dict[str, Any] = {
        "prediction_paths": prediction_paths,
        "results_path": results_path,
    }
    if scoreline_path is not None:
        kwargs["scoreline_path"] = scoreline_path
    if upset_path is not None:
        kwargs["upset_path"] = upset_path
    if performance_path is not None:
        kwargs["performance_path"] = performance_path
    reports = run_prediction_calibration(**kwargs)
    return {
        **_dump(reports),
        "warnings": sorted(
            {
                warning
                for report in reports["agent_performance"]
                for warning in report.warnings
            }
        ),
        "entertainment_disclaimer": ENTERTAINMENT_DISCLAIMER,
    }


__all__ = [
    "get_arena_calibration",
    "get_arena_leaderboard",
    "get_arena_match",
    "lock_arena_match",
    "publish_arena_card",
    "run_arena_match",
    "settle_arena_match",
]
