"""Render and publish concise public markdown cards from Prediction Arena runs."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.ingestion.normalizers import safe_read_csv, safe_write_csv
from app.prediction_arena.public_ledger import PRE_MATCH_PREDICTIONS_PATH, load_predictions
from app.prediction_arena.risk_guardrails import (
    ensure_entertainment_disclaimer,
    reject_betting_advice_language,
)
from app.prediction_arena.schemas import (
    ENTERTAINMENT_DISCLAIMER,
    FinalForecast,
    PredictionRecord,
    PredictionStage,
    PredictionTarget,
    PublicPredictionCard,
    TargetPick,
)

if TYPE_CHECKING:
    from app.prediction_arena.prediction_runner import PredictionArenaRun


ROOT = Path(__file__).resolve().parents[2]
CARDS_DIR = ROOT / "data" / "prediction_arena" / "cards"
PUBLIC_CARDS_LEDGER_PATH = ROOT / "data" / "prediction_arena" / "ledgers" / "public_prediction_cards.csv"
PUBLIC_CARD_FIELDS = [
    "card_id",
    "prediction_id",
    "match_id",
    "team_a",
    "team_b",
    "stage",
    "card_path",
    "published_at",
    "status",
    "entertainment_disclaimer",
]


def _inline(value: str) -> str:
    return " ".join(value.replace("|", r"\|").split())


def _filename(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-.")
    return name or "match"


def _bullets(values: list[str], fallback: str) -> str:
    rows = values or [fallback]
    return "\n".join(f"- {_inline(value)}" for value in rows)


def build_public_prediction_card(run: "PredictionArenaRun") -> PublicPredictionCard:
    final_record = next(
        record for record in run.prediction_records if record.agent_name == "Final Forecast Agent"
    )
    return PublicPredictionCard(
        card_id=f"{final_record.prediction_id}-card",
        prediction_id=final_record.prediction_id,
        match_id=run.match_id,
        team_a=run.team_a,
        team_b=run.team_b,
        stage=run.stage,
        final_forecast=run.final_forecast,
        kevin_take=f"{run.kevin.bold_pick}. {run.kevin.core_reason}",
        expert_view=run.expert.expected_match_shape,
        upset_path=run.upset.upset_path,
        published_at=datetime.now(timezone.utc),
    )


def _record_target(record: PredictionRecord) -> PredictionTarget:
    qualification = (
        TargetPick(pick=record.qualification_pick, confidence=record.confidence)
        if record.qualification_pick
        else None
    )
    return PredictionTarget(
        regular_time_90=TargetPick(
            pick=record.regular_time_pick,
            score=record.regular_time_score,
            confidence=record.confidence,
        ),
        after_extra_time=qualification,
        qualification=qualification,
        penalty_shootout_probability=record.penalty_probability,
    )


def build_public_card_from_records(
    match_id: str,
    *,
    ledger_path: Path = PRE_MATCH_PREDICTIONS_PATH,
) -> PublicPredictionCard:
    """Reconstruct a publishable card from the latest persisted arena version."""
    records = [record for record in load_predictions(ledger_path) if record.match_id == match_id]
    finals = [record for record in records if record.agent_name == "Final Forecast Agent"]
    if not finals:
        raise ValueError(f"No Final Forecast Agent prediction exists for match {match_id!r}.")
    final_record = max(finals, key=lambda record: record.version)
    version_records = {record.agent_name: record for record in records if record.version == final_record.version}
    missing = [name for name in ("Kevin Agent", "Expert Agent", "Upset Agent") if name not in version_records]
    if missing:
        raise ValueError(f"Latest arena version is missing required records: {', '.join(missing)}")
    kevin = version_records["Kevin Agent"]
    expert = version_records["Expert Agent"]
    upset = version_records["Upset Agent"]
    final = FinalForecast(
        match_id=final_record.match_id,
        team_a=final_record.team_a,
        team_b=final_record.team_b,
        stage=final_record.stage,
        final_prediction=_record_target(final_record),
        final_confidence=min(0.75, final_record.confidence),
        top_reasons=[final_record.core_reason],
        fragile_assumptions=final_record.fragile_assumptions,
        what_to_watch=[expert.core_reason, upset.core_reason],
    )
    return PublicPredictionCard(
        card_id=f"{final_record.prediction_id}-card",
        prediction_id=final_record.prediction_id,
        match_id=match_id,
        team_a=final_record.team_a,
        team_b=final_record.team_b,
        stage=final_record.stage,
        final_forecast=final,
        kevin_take=kevin.core_reason,
        expert_view=expert.core_reason,
        upset_path=upset.core_reason,
        published_at=datetime.now(timezone.utc),
    )


def render_public_card_markdown(card: PublicPredictionCard) -> str:
    """Render a compact public card with prediction targets kept explicit."""
    safe_card = ensure_entertainment_disclaimer(card)
    reject_betting_advice_language(safe_card)
    prediction = safe_card.final_forecast.final_prediction
    regular = prediction.regular_time_90
    lines = [
        f"# {_inline(card.team_a)} vs {_inline(card.team_b)}",
        "",
        f"**Match:** `{_inline(card.match_id)}` | **Stage:** {_inline(card.stage.value.title())}",
        "",
        "## Final Forecast",
        "",
        f"**90 minutes:** {_inline(regular.pick)} | **Score:** `{regular.score or 'unavailable'}` | "
        f"**Confidence:** {safe_card.final_forecast.final_confidence:.0%}",
    ]
    if prediction.qualification:
        lines.extend(
            [
                "",
                f"**Qualification:** {_inline(prediction.qualification.pick)} | "
                f"**Confidence:** {prediction.qualification.confidence:.0%}",
            ]
        )
    if prediction.penalty_shootout_probability is not None:
        lines.append(f"**Penalty shootout probability:** {prediction.penalty_shootout_probability:.0%}")
    lines.extend(
        [
            "",
            "## Arena Views",
            "",
            f"**Kevin Agent:** {_inline(safe_card.kevin_take)}",
            "",
            f"**Expert Agent:** {_inline(safe_card.expert_view)}",
            "",
            f"**Upset path:** {_inline(safe_card.upset_path)}",
            "",
            "## Fragile Assumptions",
            "",
            _bullets(safe_card.final_forecast.fragile_assumptions, "No fragile assumptions were recorded."),
            "",
            "## What To Watch",
            "",
            _bullets(safe_card.final_forecast.what_to_watch, "No additional watch items were recorded."),
            "",
            "---",
            "",
            safe_card.entertainment_disclaimer,
            "",
        ]
    )
    markdown = "\n".join(lines)
    reject_betting_advice_language(markdown)
    return markdown


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _append_card_receipt(card: PublicPredictionCard, path: Path, ledger_path: Path) -> None:
    existing = safe_read_csv(ledger_path, PUBLIC_CARD_FIELDS)
    if any(row.get("card_id") == card.card_id for row in existing.rows):
        return
    row: dict[str, Any] = {
        "card_id": card.card_id,
        "prediction_id": card.prediction_id,
        "match_id": card.match_id,
        "team_a": card.team_a,
        "team_b": card.team_b,
        "stage": card.stage.value,
        "card_path": str(path),
        "published_at": card.published_at.isoformat() if card.published_at else "",
        "status": "published",
        "entertainment_disclaimer": card.entertainment_disclaimer,
    }
    result = safe_write_csv(ledger_path, [row], PUBLIC_CARD_FIELDS, append=True)
    if not result.ok:
        raise ValueError("; ".join(issue.problem for issue in result.issues))


def publish_public_prediction_card(
    card: PublicPredictionCard,
    *,
    cards_dir: Path | None = None,
    ledger_path: Path | None = None,
) -> Path:
    """Publish one markdown card and append an idempotent publication receipt."""
    safe_card = ensure_entertainment_disclaimer(card)
    path = (cards_dir or CARDS_DIR) / f"{_filename(safe_card.match_id)}.md"
    _atomic_write_text(path, render_public_card_markdown(safe_card))
    _append_card_receipt(safe_card, path, ledger_path or PUBLIC_CARDS_LEDGER_PATH)
    return path


def publish_run_card(
    run: "PredictionArenaRun",
    *,
    cards_dir: Path | None = None,
    ledger_path: Path | None = None,
) -> Path:
    return publish_public_prediction_card(
        build_public_prediction_card(run),
        cards_dir=cards_dir,
        ledger_path=ledger_path,
    )


__all__ = [
    "CARDS_DIR",
    "PUBLIC_CARDS_LEDGER_PATH",
    "build_public_card_from_records",
    "build_public_prediction_card",
    "publish_public_prediction_card",
    "publish_run_card",
    "render_public_card_markdown",
]
