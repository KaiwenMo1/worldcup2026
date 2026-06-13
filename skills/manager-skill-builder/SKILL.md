---
name: manager-skill-builder
description: Distills public football-manager evidence into reviewable tactical skills and app-compatible manager JSON. Use when creating, updating, validating, or exporting a manager tactical profile from match reports, press conferences, decision records, or other public evidence.
---

# Manager Skill Builder

Build a manager skill as a public-evidence hypothesis, never as simulated private intent.

## Workflow

1. Identify the manager using `data/managers.csv`.
2. Create an evidence directory using the contract in [references/manager-extraction-framework.md](references/manager-extraction-framework.md).
3. Collect evidence across the six research streams:
   - tactical reports
   - press conferences
   - expression DNA
   - external views
   - decision records
   - timeline
4. Normalize executable claims into CSV. Keep free-form Markdown as source context only.
5. Run:

```bash
python scripts/create_manager_skill.py \
  --manager-id france_deschamps \
  --manager-name "Didier Deschamps" \
  --team France \
  --evidence-dir data/manager_distillation/raw_evidence/france_deschamps
```

6. Inspect `SKILL.md` and `validation_report.md`.
7. Validate again with `python scripts/validate_manager_skill.py --manager-id france_deschamps`.
8. Export a preview with `python scripts/export_manager_skill_json.py --manager-id france_deschamps`.
9. Use `--apply` only after reviewing the preview and evidence.

## Promotion Rules

A claim becomes core only when it passes all three:

- recurring across multiple matches or reliable sources
- predictive of future manager behavior
- distinctive rather than generic football advice

Failed claims remain low-confidence heuristics. Never manually promote them by editing generated output.

## Boundaries

- Do not let free-form text become executable logic.
- Do not overwrite existing app manager skills without `--apply`.
- Do not treat press conferences as complete truth.
- Preserve source IDs and honest boundaries.
- Do not claim the skill knows private fitness, training, or camp dynamics.

See [references/manager-skill-template.md](references/manager-skill-template.md) for expected outputs.
