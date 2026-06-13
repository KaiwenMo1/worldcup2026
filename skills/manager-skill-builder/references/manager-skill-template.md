# Generated Manager Skill Template

Each generated manager directory contains:

```text
data/manager_distillation/generated_skills/{manager_id}/
├── SKILL.md
├── manager_skill_draft.json
├── manager_skill.preview.json
└── validation_report.md
```

## SKILL.md

The human-readable skill should include:

- tactical identity
- core tactical models
- decision heuristics
- low-confidence heuristics
- player archetype preferences
- anti-patterns
- expression DNA
- honest boundaries
- evidence sources

## Draft JSON

`manager_skill_draft.json` is the complete intermediate contract. It preserves validation details, evidence IDs, source IDs, match IDs, confidence, and downgraded claims.

## Tactical JSON

`manager_skill.preview.json` is constrained to the existing app tactical schema. Only supported condition codes become executable decision rules. An existing `data/manager_skills/{manager_id}.json` is replaced only with explicit `--apply`.

The exporter may be pointed at `SKILL.md`, but it deliberately reads the sibling `manager_skill_draft.json` as the structured source of truth. Human-readable prose is never parsed directly into executable tactics.

## Review Checklist

- Validation is PASS or an intentionally accepted WARN.
- Core claims have multiple sources or matches.
- Decision-rule parameters use the supported vocabulary.
- Low-confidence claims remain visibly downgraded.
- Honest boundaries and sources are present.
- The app-compatible JSON validates before application.
