#!/usr/bin/env python3
"""Write the current Prediction Arena calibration reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.calibration import run_prediction_calibration  # noqa: E402


def main() -> None:
    report = run_prediction_calibration()
    print(
        json.dumps(
            {
                key: [row.model_dump(mode="json") for row in rows]
                for key, rows in report.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
