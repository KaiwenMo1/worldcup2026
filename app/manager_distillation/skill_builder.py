"""Distill structured evidence into transparent manager tactical claims."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

from app.manager_distillation.schemas import (
    ClaimType,
    ClaimValidation,
    DistillationSource,
    DistilledClaim,
    DistilledManagerSkill,
    DistilledTacticalIdentity,
    EvidenceDocument,
    EvidenceRecord,
)


HONEST_BOUNDARIES = [
    "Public information may be incomplete.",
    "Press conferences may be strategic rather than complete descriptions of intent.",
    "Tactical articles may be secondhand interpretation.",
    "Private fitness and training data are unavailable.",
    "Recent injuries or camp dynamics may override historical patterns.",
]
TACTICAL_MODEL_TYPES = {
    ClaimType.TACTICAL_IDENTITY,
    ClaimType.PREFERRED_FORMATION,
    ClaimType.BUILD_UP_RULE,
    ClaimType.DEFENSIVE_SHAPE_RULE,
    ClaimType.IN_POSSESSION_RULE,
    ClaimType.OUT_OF_POSSESSION_RULE,
    ClaimType.TRANSITION_RULE,
    ClaimType.PRESSING_TRIGGER,
    ClaimType.SET_PIECE_TENDENCY,
    ClaimType.SUBSTITUTION_PATTERN,
}


def _distill_claim(rows: list[EvidenceRecord]) -> DistilledClaim:
    first = rows[0]
    sources = sorted({row.source_id for row in rows})
    reliable_sources = sorted({row.source_id for row in rows if row.reliability_score >= 0.6})
    matches = sorted({row.match_id for row in rows if row.match_id})
    recurrence = len(reliable_sources) >= 2 or len(matches) >= 2
    predictive = all(row.predictive_power for row in rows)
    distinctive = all(row.distinctive for row in rows)
    consistent = all(
        (
            row.claim_type,
            row.claim_text,
            row.normalized_value,
            row.condition_code,
            row.parameters,
            row.match_state,
            row.minute_window,
        )
        == (
            first.claim_type,
            first.claim_text,
            first.normalized_value,
            first.condition_code,
            first.parameters,
            first.match_state,
            first.minute_window,
        )
        for row in rows
    )
    core = recurrence and predictive and distinctive and consistent
    confidence = mean(row.reliability_score for row in rows)
    if not core:
        confidence = min(confidence, 0.49)
    failed = []
    if not recurrence:
        failed.append("cross-match recurrence")
    if not predictive:
        failed.append("predictive power")
    if not distinctive:
        failed.append("distinctiveness")
    if not consistent:
        failed.append("claim consistency")
    return DistilledClaim(
        claim_id=first.claim_id,
        claim_type=first.claim_type,
        claim_text=first.claim_text,
        normalized_value=first.normalized_value,
        condition_code=first.condition_code,
        parameters=first.parameters,
        match_state=first.match_state,
        minute_window=first.minute_window,
        evidence_ids=sorted({row.evidence_id for row in rows}),
        source_ids=sources,
        match_ids=matches,
        confidence=round(confidence, 3),
        validation=ClaimValidation(
            cross_match_recurrence=recurrence,
            predictive_power=predictive,
            distinctiveness=distinctive,
            distinct_matches=len(matches),
            distinct_sources=len(sources),
            status="core" if core else "low_confidence",
            reason="Passed all three validation rules." if core else f"Downgraded because it failed: {', '.join(failed)}.",
        ),
    )


def _first_value(claims: list[DistilledClaim], claim_type: ClaimType, fallback: str) -> str:
    claim = next((item for item in claims if item.claim_type == claim_type), None)
    return (claim.normalized_value or claim.claim_text) if claim else fallback


def _sources(records: list[EvidenceRecord], documents: list[EvidenceDocument]) -> list[DistillationSource]:
    grouped: defaultdict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        grouped[record.source_id].append(record)
    output = [
        DistillationSource(
            source_id=source_id,
            title=rows[0].title,
            url=next((row.url for row in rows if row.url), None),
            observed_at=max((row.observed_at for row in rows if row.observed_at), default=None),
            categories=sorted({row.category for row in rows}, key=str),
        )
        for source_id, rows in grouped.items()
    ]
    known = {source.source_id for source in output}
    for document in documents:
        if document.document_id not in known:
            output.append(
                DistillationSource(
                    source_id=document.document_id,
                    title=document.title,
                    categories=[document.category],
                )
            )
            known.add(document.document_id)
    return sorted(output, key=lambda source: source.source_id)


def build_manager_skill(
    *,
    manager_id: str,
    manager_name: str,
    team: str,
    records: list[EvidenceRecord],
    documents: list[EvidenceDocument] | None = None,
    version: str = "0.1",
) -> DistilledManagerSkill:
    relevant = [record for record in records if record.manager_id == manager_id]
    grouped: defaultdict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in relevant:
        grouped[record.claim_id].append(record)
    claims = [_distill_claim(rows) for _, rows in sorted(grouped.items())]
    core = [claim for claim in claims if claim.validation.status == "core"]
    low = [claim for claim in claims if claim.validation.status == "low_confidence"]
    tactical = [claim for claim in core if claim.claim_type in TACTICAL_MODEL_TYPES]
    decisions = [claim for claim in core if claim.condition_code is not None]
    formations = [
        claim.normalized_value or claim.claim_text
        for claim in tactical
        if claim.claim_type == ClaimType.PREFERRED_FORMATION
    ]
    pressing = _first_value(tactical, ClaimType.PRESSING_TRIGGER, "insufficient_evidence")
    return DistilledManagerSkill(
        manager_id=manager_id,
        manager_name=manager_name,
        team=team,
        version=version,
        generated_at=datetime.now(timezone.utc),
        tactical_identity=DistilledTacticalIdentity(
            primary_style=_first_value(tactical, ClaimType.TACTICAL_IDENTITY, "insufficient_evidence"),
            preferred_formations=formations or ["insufficient_evidence"],
            build_up=_first_value(tactical, ClaimType.BUILD_UP_RULE, "insufficient_evidence"),
            defensive_shape=_first_value(tactical, ClaimType.DEFENSIVE_SHAPE_RULE, "insufficient_evidence"),
            pressing=pressing,
            transition=_first_value(tactical, ClaimType.TRANSITION_RULE, "insufficient_evidence"),
            set_pieces=_first_value(tactical, ClaimType.SET_PIECE_TENDENCY, "insufficient_evidence"),
        ),
        core_tactical_models=tactical,
        decision_heuristics=decisions,
        low_confidence_heuristics=low,
        player_archetype_preferences=[
            claim.claim_text for claim in core if claim.claim_type == ClaimType.PLAYER_ARCHETYPE_PREFERENCE
        ],
        anti_patterns=[claim.claim_text for claim in core if claim.claim_type == ClaimType.ANTI_PATTERN],
        expression_dna=[claim.claim_text for claim in core if claim.claim_type == ClaimType.EXPRESSION_DNA],
        timeline_notes=[claim.claim_text for claim in claims if claim.claim_type == ClaimType.TIMELINE_NOTE],
        honest_boundaries=list(HONEST_BOUNDARIES),
        sources=_sources(relevant, documents or []),
        evidence_notes=[f"{claim.claim_id}: {claim.validation.reason}" for claim in low],
    )
