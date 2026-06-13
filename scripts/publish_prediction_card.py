#!/usr/bin/env python3
"""Publish the latest saved Prediction Arena version for one match."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.prediction_arena.public_card_renderer import (  # noqa: E402
    build_public_card_from_records,
    publish_public_prediction_card,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-id", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    card = build_public_card_from_records(args.match_id)
    path = publish_public_prediction_card(card)
    print(f"Published {path}")


if __name__ == "__main__":
    main()
