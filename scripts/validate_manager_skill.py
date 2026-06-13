#!/usr/bin/env python3
"""Validate one generated manager skill draft."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.manager_distillation import load_distilled_skill, render_validation_report, validate_manager_skill  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a generated manager skill draft.")
    parser.add_argument("--manager-id")
    parser.add_argument("--draft", type=Path)
    args = parser.parse_args()
    if not args.manager_id and not args.draft:
        parser.error("provide --manager-id or --draft")
    draft = args.draft or ROOT / "data" / "manager_distillation" / "generated_skills" / args.manager_id / "manager_skill_draft.json"
    skill = load_distilled_skill(draft)
    report = validate_manager_skill(skill)
    report_path = draft.parent / "validation_report.md"
    report_path.write_text(render_validation_report(report), encoding="utf-8")
    print(render_validation_report(report), end="")
    raise SystemExit(1 if report.status == "FAIL" else 0)


if __name__ == "__main__":
    main()
