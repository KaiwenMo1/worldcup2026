"""Language and disclaimer guardrails for public Prediction Arena outputs."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from app.prediction_arena.schemas import ENTERTAINMENT_DISCLAIMER


DISALLOWED_RECOMMENDATION_TERMS = (
    "stake",
    "bankroll",
    "guaranteed profit",
    "risk-free",
    "lock bet",
    "arbitrage",
    "sure bet",
)


class PredictionArenaGuardrailError(ValueError):
    """Raised when an arena output violates a public-safety contract."""


def _as_text(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, default=str)


def reject_betting_advice_language(text_or_obj: Any) -> Any:
    """Return the input when safe; raise when recommendation language is present."""
    text = _as_text(text_or_obj).casefold()
    found = [
        term
        for term in DISALLOWED_RECOMMENDATION_TERMS
        if re.search(rf"\b{re.escape(term)}\b", text)
    ]
    if found:
        raise PredictionArenaGuardrailError(
            f"Prediction Arena outputs cannot contain betting-advice language: {', '.join(found)}"
        )
    return text_or_obj


def ensure_entertainment_disclaimer(text_or_obj: Any) -> Any:
    """Attach the required disclaimer while preserving the input's practical shape."""
    reject_betting_advice_language(text_or_obj)
    if isinstance(text_or_obj, str):
        return (
            text_or_obj
            if ENTERTAINMENT_DISCLAIMER.casefold() in text_or_obj.casefold()
            else f"{text_or_obj.rstrip()} {ENTERTAINMENT_DISCLAIMER}"
        )
    if isinstance(text_or_obj, BaseModel):
        if "entertainment_disclaimer" not in type(text_or_obj).model_fields:
            raise PredictionArenaGuardrailError(
                "Structured public outputs must define entertainment_disclaimer."
            )
        return text_or_obj.model_copy(update={"entertainment_disclaimer": ENTERTAINMENT_DISCLAIMER})
    if isinstance(text_or_obj, dict):
        return {**text_or_obj, "entertainment_disclaimer": ENTERTAINMENT_DISCLAIMER}
    raise PredictionArenaGuardrailError(
        f"Unsupported disclaimer target type: {type(text_or_obj).__name__}"
    )
