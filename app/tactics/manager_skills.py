"""Load and evaluate transparent manager tactical hypotheses."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import TypedDict

from pydantic import ValidationError

from app.tactics.schemas import (
    ConditionCode,
    DecisionRule,
    ManagerPlan,
    ManagerSkill,
    MatchContext,
    PlanConfidence,
    RuleEvaluation,
)


ROOT = Path(__file__).resolve().parents[2]
MANAGERS_PATH = ROOT / "data" / "managers.csv"
MANAGER_SKILLS_DIR = ROOT / "data" / "manager_skills"
MANAGER_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")


class ManagerSkillDataError(ValueError):
    """Raised when an existing manager data file cannot be validated."""


class RuleEvaluationResult(TypedDict):
    applied: list[RuleEvaluation]
    contingent: list[DecisionRule]


def load_manager_skill(manager_id: str) -> ManagerSkill | None:
    """Load one manager skill; return None only when the file is absent."""
    if not MANAGER_ID_PATTERN.fullmatch(manager_id):
        raise ManagerSkillDataError(f"Invalid manager_id: {manager_id!r}")

    path = MANAGER_SKILLS_DIR / f"{manager_id}.json"
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        skill = ManagerSkill.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ManagerSkillDataError(f"Invalid manager skill file {path}: {exc}") from exc

    if skill.manager_id != manager_id:
        raise ManagerSkillDataError(
            f"Manager skill file {path} declares manager_id={skill.manager_id!r}; expected {manager_id!r}"
        )
    return skill


def list_manager_skills() -> list[ManagerSkill]:
    """Load every available manager skill in deterministic order."""
    if not MANAGER_SKILLS_DIR.exists():
        return []
    skills = []
    for path in sorted(MANAGER_SKILLS_DIR.glob("*.json")):
        if not path.is_file():
            continue
        skill = load_manager_skill(path.stem)
        if skill is not None:
            skills.append(skill)
    return skills


def list_manager_registry() -> list[dict[str, str]]:
    """Load the current tournament manager registry without implying tactical evidence."""
    if not MANAGERS_PATH.exists():
        return []
    try:
        with MANAGERS_PATH.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise ManagerSkillDataError(f"Could not read managers file {MANAGERS_PATH}: {exc}") from exc


def load_team_manager_record(team: str) -> dict[str, str] | None:
    """Return the current registry row for a team even when no skill JSON exists."""
    return next((row for row in list_manager_registry() if row.get("team", "").casefold() == team.casefold()), None)


def load_team_manager_skill(team: str) -> ManagerSkill | None:
    """Resolve the configured manager for a team, returning None if unavailable."""
    if not MANAGERS_PATH.exists():
        return None

    try:
        with MANAGERS_PATH.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {"manager_id", "team"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ManagerSkillDataError(
                    f"Invalid managers file {MANAGERS_PATH}: required columns are {sorted(required)}"
                )
            row = next((item for item in reader if item.get("team", "").casefold() == team.casefold()), None)
    except OSError as exc:
        raise ManagerSkillDataError(f"Could not read managers file {MANAGERS_PATH}: {exc}") from exc

    if not row:
        return None

    manager_id = row.get("manager_id", "").strip()
    if not manager_id:
        raise ManagerSkillDataError(f"Invalid managers file {MANAGERS_PATH}: team {team!r} has no manager_id")

    skill = load_manager_skill(manager_id)
    if skill is not None and skill.team.casefold() != team.casefold():
        raise ManagerSkillDataError(
            f"Manager skill {skill.manager_id!r} belongs to {skill.team!r}, not configured team {team!r}"
        )
    return skill


def _rule_result(rule: DecisionRule, context: MatchContext) -> tuple[bool, str]:
    code = rule.condition_code
    parameters = rule.parameters

    if code == ConditionCode.OPPONENT_HIGH_LINE:
        if context.opponent_high_line is not True:
            return False, "opponent high line is not present in the supplied context"
        recovery_max = parameters.get("recovery_defender_score_max")
        if recovery_max is not None and context.opponent_recovery_defender_score is None:
            return False, "opponent recovery-defender score is required to evaluate this rule"
        if recovery_max is not None and context.opponent_recovery_defender_score > float(recovery_max):
            return False, "opponent recovery-defender score is above the rule threshold"
        return True, "supplied context reports an opponent high line with the required recovery profile"

    if code == ConditionCode.OPPONENT_HIGH_PRESS:
        return (
            context.opponent_high_press is True,
            "supplied context reports an opponent high press"
            if context.opponent_high_press is True
            else "opponent high press is not present in the supplied context",
        )

    if code == ConditionCode.OPPONENT_MIDFIELD_CONTROL:
        possession_min = float(parameters.get("possession_share_min", 1.0))
        by_flag = context.opponent_midfield_control is True
        by_possession = (
            context.opponent_possession_share is not None
            and context.opponent_possession_share >= possession_min
        )
        return (
            by_flag or by_possession,
            "supplied context reports opponent midfield control"
            if by_flag or by_possession
            else "opponent midfield-control threshold is not met",
        )

    if code == ConditionCode.KNOCKOUT_MATCH:
        return context.knockout, "match context is knockout" if context.knockout else "match context is not knockout"

    state_by_code = {
        ConditionCode.LEADING_AFTER_MINUTE: "leading",
        ConditionCode.TRAILING_AFTER_MINUTE: "trailing",
        ConditionCode.TIED_AFTER_MINUTE: "tied",
    }
    if code in state_by_code:
        required_state = state_by_code[code]
        required_minute = int(parameters["minute"])
        triggered = context.match_state == required_state and context.minute >= required_minute
        return (
            triggered,
            f"team is {required_state} at minute {context.minute}, after the minute {required_minute} threshold"
            if triggered
            else f"requires team to be {required_state} at or after minute {required_minute}",
        )

    return False, f"unsupported condition code: {code}"


def evaluate_decision_rules(manager_skill: ManagerSkill, match_context: MatchContext) -> RuleEvaluationResult:
    """Evaluate supported rule conditions and preserve all non-triggered rules."""
    applied: list[RuleEvaluation] = []
    contingent = []
    for rule in manager_skill.decision_rules:
        triggered, reason = _rule_result(rule, match_context)
        if triggered:
            applied.append(
                RuleEvaluation(
                    condition_code=rule.condition_code,
                    recommendation=rule.recommendation,
                    reason=reason,
                    evidence_confidence=rule.evidence_confidence,
                    source_refs=rule.source_refs,
                    parameters=rule.parameters,
                )
            )
        else:
            contingent.append(rule)
    return {"applied": applied, "contingent": contingent}


def _plan_confidence(skill: ManagerSkill, applied: list[RuleEvaluation]) -> PlanConfidence:
    relevant_scores = [rule.evidence_confidence for rule in applied] or [
        rule.evidence_confidence for rule in skill.decision_rules
    ]
    score = sum(relevant_scores) / len(relevant_scores) if relevant_scores else 0.2
    if skill.status == "manual_prototype":
        score = min(score, 0.55)
    level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
    return PlanConfidence(
        level=level,
        score=round(score, 3),
        meaning="confidence that the manager tends to use this plan in the supplied context; not outcome probability",
    )


def _fallback_plan(team: str, opponent: str) -> ManagerPlan:
    return ManagerPlan(
        team=team,
        opponent=opponent,
        manager_id=None,
        manager_name=None,
        base_plan="neutral_balanced_plan",
        expected_formation=None,
        in_possession=["use the available team profile and avoid unsupported manager-specific claims"],
        out_of_possession=["maintain balanced defensive spacing"],
        transition=["preserve defensive balance when possession changes"],
        set_pieces=["use existing team-level set-piece profile when available"],
        applied_rules=[],
        contingent_rules=[],
        substitution_patterns=[],
        confidence=PlanConfidence(
            level="low",
            score=0.0,
            meaning="no manager-specific evidence is available",
        ),
        source_refs=[],
        data_quality="fallback",
        fallback_used=True,
        fallback_note=f"No manager skill is available for {team}; returned a neutral analysis plan.",
    )


def generate_manager_plan(
    team: str,
    opponent: str,
    match_context: MatchContext | None = None,
) -> ManagerPlan:
    """Generate an inspectable manager plan without changing model predictions."""
    skill = load_team_manager_skill(team)
    if skill is None:
        return _fallback_plan(team, opponent)

    if match_context is None:
        applied: list[RuleEvaluation] = []
        contingent = list(skill.decision_rules)
    else:
        evaluation = evaluate_decision_rules(skill, match_context)
        applied = evaluation["applied"]
        contingent = evaluation["contingent"]

    identity = skill.tactical_identity
    relevant_substitutions = list(skill.substitution_patterns)
    if match_context is not None and match_context.match_state != "pre_match":
        relevant_substitutions = [
            pattern for pattern in skill.substitution_patterns if pattern.match_state == match_context.match_state
        ]

    return ManagerPlan(
        team=team,
        opponent=opponent,
        manager_id=skill.manager_id,
        manager_name=skill.manager_name,
        base_plan=identity.primary_style,
        expected_formation=identity.preferred_formations[0] if identity.preferred_formations else None,
        in_possession=identity.in_possession,
        out_of_possession=identity.out_of_possession,
        transition=identity.transition_actions,
        set_pieces=identity.set_piece_actions,
        applied_rules=applied,
        contingent_rules=contingent,
        substitution_patterns=relevant_substitutions,
        confidence=_plan_confidence(skill, applied),
        source_refs=skill.source_refs,
        data_quality=skill.status,
        fallback_used=False,
        fallback_note=None,
    )
