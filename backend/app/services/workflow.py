"""Deterministic validation persistence and claim status updates shared by the orchestrator and the
correction workflow."""
import uuid

from app.config import settings
from app.models import models as m
from app.services.claims import snapshot
from app.validation.engine import RULE_META, SEVERITY_ORDER, determine_outcome, readiness_score, validate_claim


def persist_validation(db, claim: m.Claim, results) -> str:
    run_id = uuid.uuid4().hex[:12]
    for r in results:
        db.add(m.ValidationResult(run_id=run_id, claim_id=claim.id, claim_version=claim.version, rule_id=r.rule_id,
                                  status=r.status, severity=r.severity, dimension=r.dimension, resolution=r.resolution,
                                  explanation=r.explanation, evidence=r.evidence, details=r.details, next_action=r.next_action))
    claim.latest_validation_run = run_id
    return run_id


def responsible_agent(results):
    fails = sorted((r for r in results if r.status == "fail"), key=lambda r: SEVERITY_ORDER.get(r.severity, 9))
    return RULE_META[fails[0].rule_id]["agent"] if fails else None


def apply_status(claim: m.Claim, results, escalations):
    score, dims = readiness_score(results, settings.scoring_weights)
    status = determine_outcome(results, escalations)
    claim.status = status
    claim.readiness_score = score
    claim.issue_count = sum(1 for r in results if r.status == "fail") + len(
        [e for e in escalations if e.get("source") not in ("conflict",)])
    claim.assigned_agent = responsible_agent(results) or (escalations[0].get("agent") if escalations else None)
    claim.escalations = list(escalations)
    if claim.initial_status is None:
        claim.initial_status, claim.initial_score = status, score
    return status, score, dims


def revalidate(db, claim: m.Claim, ref, rec, actor="system"):
    """Re-run only the deterministic engine on the current claim state (no agents, no AI).
    Existing non-deterministic escalations are kept: only a full reassessment can clear them."""
    snap = snapshot(claim)
    ref.replace_claim(snap)
    results = validate_claim(snap, ref)
    run_id = persist_validation(db, claim, results)
    before = claim.status
    status, score, dims = apply_status(claim, results, claim.escalations or [])
    rec.audit("validation_run", actor, "system", f"Deterministic validation: {before} -> {status}, readiness {score}",
              {"run_id": run_id, "claim_version": claim.version, "failed": [r.rule_id for r in results if r.status == "fail"]},
              claim_id=claim.id)
    return results, status, score, dims
