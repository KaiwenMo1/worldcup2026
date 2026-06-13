#!/usr/bin/env python3
"""Smoke-test explicit game-state branching and hypothetical-event quarantine."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.simulation import (  # noqa: E402
    attach_game_state_paths,
    example_game_state_paths,
    validate_no_unobserved_event_cascade,
)


def main() -> None:
    main_prediction = {
        "match": "France vs Brazil",
        "regular_time_90": {"pick": "France", "score": "1-0", "confidence": 0.44},
    }
    paths = example_game_state_paths("France", "Brazil")
    branched = attach_game_state_paths(main_prediction, paths)
    safe = validate_no_unobserved_event_cascade(branched)
    unsafe = validate_no_unobserved_event_cascade(
        {
            "main_prediction": main_prediction,
            "assumed_event": {
                "event_type": "yellow_card",
                "probability": 0.24,
                "is_observed": False,
                "allowed_to_cascade": True,
                "impact_if_occurs": "France attacks the booked defender.",
            },
        }
    )

    assert branched["main_prediction"] == main_prediction
    assert len(paths) == 4
    assert safe.valid
    assert not unsafe.valid
    assert unsafe.skeptic_warnings
    print(
        "Hypothetical event quarantine smoke test passed: "
        f"branches={len(paths)}, safe_warnings={len(safe.skeptic_warnings)}, "
        f"unsafe_warnings={len(unsafe.skeptic_warnings)}"
    )


if __name__ == "__main__":
    main()
