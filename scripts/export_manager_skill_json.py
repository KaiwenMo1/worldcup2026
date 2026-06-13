#!/usr/bin/env python3
"""Export a generated draft into the tactical engine ManagerSkill contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.manager_distillation import export_tactical_json, load_distilled_skill, validate_manager_skill  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a manager skill draft to app tactical JSON.")
    parser.add_argument("--manager-id")
    parser.add_argument("--draft", type=Path)
    parser.add_argument(
        "--skill-md",
        type=Path,
        help="Use a generated SKILL.md; the sibling manager_skill_draft.json remains the structured source of truth.",
    )
    parser.add_argument("--apply", action="store_true", help="Allow replacement of an existing app manager skill.")
    args = parser.parse_args()
    if not args.manager_id and not args.draft and not args.skill_md:
        parser.error("provide --manager-id, --draft, or --skill-md")
    draft = (
        args.draft
        or (args.skill_md.parent / "manager_skill_draft.json" if args.skill_md else None)
        or ROOT / "data" / "manager_distillation" / "generated_skills" / args.manager_id / "manager_skill_draft.json"
    )
    skill = load_distilled_skill(draft)
    report = validate_manager_skill(skill)
    if report.status == "FAIL":
        raise SystemExit("Refusing export because manager skill validation status is FAIL.")
    output = export_tactical_json(skill, apply=args.apply)
    print(f"Exported tactical manager skill to {output} ({report.status})")


if __name__ == "__main__":
    main()
