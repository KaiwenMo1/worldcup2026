# Manager Extraction Framework

This framework adapts Nuwa-style perspective distillation to football management. The objective is not imitation. It is a reviewable model of recurring tactical decisions.

## Six Research Streams

| Stream | Useful evidence | Main risk |
|---|---|---|
| `tactical_reports` | match analysis, previews, tactical breakdowns | secondhand interpretation |
| `press_conferences` | direct explanations, interviews | strategic or incomplete answers |
| `expression_dna` | repeated priorities, certainty, public framing | words may not match behavior |
| `external_views` | analyst, journalist, opponent observations | bias and generic narratives |
| `decision_records` | lineups, substitutions, formation switches | context may explain exceptions |
| `timeline` | career evolution and recent tactical changes | old behavior may be stale |

Use Markdown for full research notes. Use structured CSV only for claims intended for automated validation.

## Evidence CSV Contract

Required columns:

```text
evidence_id,manager_id,category,source_id,title,claim_id,claim_type,claim_text,reliability_score,predictive_power,distinctive
```

Optional columns:

```text
url,observed_at,match_id,normalized_value,condition_code,parameters_json,match_state,minute_window,notes
```

Repeated rows with the same `claim_id` provide independent support for one claim.

## Validation

Core promotion requires:

1. **Recurrence**: at least two distinct matches or two distinct sources.
2. **Predictive power**: every supporting row marks the claim as useful for predicting future behavior.
3. **Distinctiveness**: every supporting row marks it as manager-specific.

The builder downgrades claims that fail any check. A human reviewer may improve the evidence, but should not edit the generated validation result.

## Executable Conditions

Only condition codes supported by `app/tactics/schemas.py` may become app decision rules:

```text
opponent_high_line
opponent_high_press
opponent_midfield_control
leading_after_minute
trailing_after_minute
tied_after_minute
knockout_match
```

Use `parameters_json` only for supported structured parameters. Free-form conditions remain explanatory evidence.
