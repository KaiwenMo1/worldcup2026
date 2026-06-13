#!/usr/bin/env python3
"""Download and normalize a public penalty-kick dataset from Kaggle."""

from __future__ import annotations

import argparse
import csv
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from penalty_model import KICK_COLUMNS, PENALTY_KICKS_PATH, normalize_row


DEFAULT_DATASET = "rodrigoarede2003/penalty-kick-dataset-20202025"


def first_csv(path: Path) -> Path:
    candidates = sorted(path.rglob("*.csv"))
    if not candidates:
        raise SystemExit("Kaggle dataset did not contain a CSV file.")
    return candidates[0]


def normalize_penalty_csv(input_path: Path, output_path: Path) -> int:
    with input_path.open(newline="", encoding="utf-8") as handle:
        rows = [normalize_row({**row, "source": "kaggle_penalty_kick_dataset"}) for row in csv.DictReader(handle)]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=KICK_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in KICK_COLUMNS} for row in rows)
    return len(rows)


def download_dataset(dataset: str, output: Path) -> int:
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ModuleNotFoundError as exc:
        raise SystemExit("Install the kaggle package or run pip install -r requirements.txt.") from exc

    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        api = KaggleApi()
        api.authenticate()
        api.dataset_download_files(dataset, path=temp_path, quiet=False)
        zip_path = next(temp_path.glob("*.zip"), None)
        if zip_path:
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(temp_path)
        return normalize_penalty_csv(first_csv(temp_path), output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and normalize Kaggle penalty kick data.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=PENALTY_KICKS_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = download_dataset(args.dataset, args.output)
    print(f"Saved {rows} penalty kicks to {args.output}")


if __name__ == "__main__":
    main()
