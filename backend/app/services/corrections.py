"""Proposal-and-approval workflow. Nothing changes a claim except a human approving a proposal that
passes deterministic dry-run validation. Every decision is written to the audit trail."""
from app.models import models as m
from app.services.claims import CorrectionError, apply_patch, snapshot, write_snapshot
from app.services.events import Recorder, bus
from app.services.workflow import revalidate
from app.validation.engine import validate_claim
from app.validation.refdata import RefData

# which proposal classes each role may decide
ROLE_SCOPE = {
    "viewer": set(),
    "billing_operator": {"billing_operator"},
    "certified_coder": {"billing_operator", "certified_coder"},
    "supervisor": {"billing_operator", "certified_coder", "supervisor"},
}


class WorkflowError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code, self.message = status_code, message


def proposal_dict(p: m.CorrectionProposal):
    return {"id": p.id, "claim_id": p.claim_id, "claim_version": p.claim_version, "rule_id": p.rule_id, "op": p.op,
            "field": p.field, "line_no": p.line_no, "original_value": p.original_value, "proposed_value": p.proposed_value,
            "problem": p.problem, "evidence": p.evidence, "agent": p.agent, "confidence_note": p.confidence_note,
            "requires_role": p.requires_role, "status": p.status, "projected_status": p.projected_status,
            "validation_note": p.validation_note, "created_at": p.created_at.isoformat() if p.created_at else None}


def _load(db, claim_id, proposal_id, role):
    claim = db.get(m.Claim, claim_id)
    if claim is None:
        raise WorkflowError(404, f"Claim {claim_id} not found")
    p = db.get(m.CorrectionProposal, proposal_id)
    if p is None or p.claim_id != claim_id:
        raise WorkflowError(404, f"Correction {proposal_id} not found for claim {claim_id}")
    if role not in ROLE_SCOPE:
        raise WorkflowError(403, f"Unknown role '{role}'")
    if p.requires_role not in ROLE_SCOPE[role]:
        raise WorkflowError(403, f"Role '{role}' may not decide this correction; it requires '{p.requires_role}'")
    if p.status != "pending":
        raise WorkflowError(409, f"Correction {proposal_id} is {p.status}, not pending")
    return claim, p


def approve(db, claim_id, proposal_id, actor="operator", role="billing_operator", edited_value=None, note=None, ref=None):
    claim, p = _load(db, claim_id, proposal_id, role)
    rec = Recorder(db, claim_id)
    value = edited_value if edited_value is not None else p.proposed_value
    if value is None:
        raise WorkflowError(422, "This correction has no proposed value; supply edited_value")
    ref = ref or RefData.from_session(db)
    snap = snapshot(claim)
    ref.replace_claim(snap)
    try:
        patched = apply_patch(snap, p.op, p.field, value, p.line_no, ref)
    except CorrectionError as e:
        rec.audit("correction_invalid", actor, "human", f"Proposal #{p.id} refused: {e}", {"proposal_id": p.id, "value": value})
        db.commit()
        raise WorkflowError(422, str(e))
    before = {r.rule_id for r in validate_claim(snap, ref) if r.status == "fail"}
    after = {r.rule_id for r in validate_claim(patched, ref) if r.status == "fail"}
    if after - before:
        rec.audit("correction_invalid", actor, "human",
                  f"Proposal #{p.id} refused: dry-run validation introduced {sorted(after - before)}",
                  {"proposal_id": p.id, "value": value, "new_failures": sorted(after - before)})
        db.commit()
        raise WorkflowError(422, f"Correction refused: it would introduce new validation failures {sorted(after - before)}")
    old_status, old_score, old_version = claim.status, claim.readiness_score, claim.version
    version = write_snapshot(db, claim, patched, f"correction #{p.id} approved ({p.rule_id})", actor)
    p.status = "approved"
    edited = edited_value is not None and edited_value != p.proposed_value
    db.add(m.CorrectionApproval(proposal_id=p.id, claim_id=claim_id, action="approved", actor=actor, role=role,
                                edited_value=value if edited else None, note=note))
    rec.audit("correction_approved", actor, "human",
              f"Proposal #{p.id} approved{' with manual edit' if edited else ''}: {p.field} {p.original_value!r} -> {value!r}",
              {"proposal_id": p.id, "rule_id": p.rule_id, "field": p.field, "line_no": p.line_no, "before": p.original_value,
               "after": value, "edited": edited, "role": role, "note": note, "version_from": old_version, "version_to": version,
               "proposed_by": p.agent, "evidence": p.evidence})
    results, status, score, _ = revalidate(db, claim, ref, rec, actor)
    db.commit()
    bus.publish("claim_status", claim_id=claim_id, status=status, readiness_score=score, issue_count=claim.issue_count)
    return {"proposal": proposal_dict(p), "claim_id": claim_id, "version": version,
            "before": {"status": old_status, "readiness_score": old_score},
            "after": {"status": status, "readiness_score": score},
            "remaining_failures": [r.rule_id for r in results if r.status == "fail"]}


def reject(db, claim_id, proposal_id, actor="operator", role="billing_operator", note=None):
    claim, p = _load(db, claim_id, proposal_id, role)
    p.status = "rejected"
    db.add(m.CorrectionApproval(proposal_id=p.id, claim_id=claim_id, action="rejected", actor=actor, role=role, note=note))
    Recorder(db, claim_id).audit("correction_rejected", actor, "human", f"Proposal #{p.id} rejected: {p.field} left unchanged",
                                 {"proposal_id": p.id, "rule_id": p.rule_id, "role": role, "note": note})
    db.commit()
    return {"proposal": proposal_dict(p), "claim_id": claim_id, "status": claim.status}
