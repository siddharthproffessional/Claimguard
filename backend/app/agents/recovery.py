"""Recovery and Optimization Agent: consolidates findings, prioritises them, and drafts correction
proposals. It never writes to a claim. Every proposal is dry-run through the deterministic engine and
waits for a human decision."""
from app.agents.base import BaseAgent
from app.config import settings
from app.schemas.agents import Evidence, Finding
from app.services.claims import EDITABLE_FIELDS, CorrectionError, apply_patch
from app.validation.engine import SEVERITY_ORDER, determine_outcome, validate_claim


def build_proposals(claim, results):
    """Draft proposals from failed, correctable rule results. Pure function of deterministic evidence."""
    props = []

    def add(rule, op, field, value, original, problem, evidence, agent, note, line_no=None, role="billing_operator"):
        props.append({"rule_id": rule.rule_id, "op": op, "field": field, "line_no": line_no, "original_value": original,
                      "proposed_value": value, "problem": problem, "evidence": evidence, "agent": agent,
                      "confidence_note": note, "requires_role": role})

    for r in results:
        if r.status != "fail":
            continue
        d = r.details
        if r.rule_id == "ELIG-001" and d.get("registry"):
            for f in d["missing"]:
                add(r, "set_field", f, d["registry"][f], claim.get(f), r.explanation,
                    [e for e in r.evidence if f in e["detail"]], "eligibility",
                    "Value copied from the synthetic patient registry record for this patient reference.")
        elif r.rule_id == "ELIG-002" and len(d.get("registry_policy_numbers", [])) == 1:
            add(r, "set_field", "policy_number", d["registry_policy_numbers"][0], claim.get("policy_number"), r.explanation,
                r.evidence, "eligibility", "Exactly one policy is registered for this patient with the billed payer.")
        elif r.rule_id == "DOC-001":
            for t, doc_id in d.get("available", {}).items():
                add(r, "attach_document", "attached_document_ids", doc_id, list(claim["attached_document_ids"]),
                    f"Required {t} is not attached.", [e for e in r.evidence if e["ref"] in (doc_id, claim["payer_id"])],
                    "documentation", "Document found in the repository for the same patient, date of service and procedure.")
        elif r.rule_id in ("COD-001", "COD-002"):
            for inv in d.get("invalid", []):
                if not inv["suggested"]:
                    continue
                line = next(l for l in claim["lines"] if l["line_no"] == inv["line_no"])
                ev = [e for e in r.evidence if e["ref"] in (inv["code"], inv["source_document"])]
                note = ("Code taken from the structured extract of the attached document. This is NOT a coding determination; "
                        "a certified coder must confirm it.")
                if r.rule_id == "COD-001":
                    new = [inv["suggested"] if x == inv["code"] else x for x in line["diagnosis_codes"]]
                    add(r, "set_line_field", "diagnosis_codes", new, list(line["diagnosis_codes"]), r.explanation, ev, "coding",
                        note, inv["line_no"], "certified_coder")
                else:
                    add(r, "set_line_field", "procedure_code", inv["suggested"], line["procedure_code"], r.explanation, ev,
                        "coding", note, inv["line_no"], "certified_coder")
        elif r.rule_id == "AUTH-001" and d.get("on_file"):
            add(r, "set_field", "authorization_number", d["on_file"][0], claim.get("authorization_number"), r.explanation,
                r.evidence, "authorization", "An approved authorization for this patient, payer, procedure and date is on file.")
        elif r.rule_id == "BILL-001":
            for fx in d.get("line_fixes", []):
                add(r, "set_line_field", "amount", fx["expected"], fx["actual"], r.explanation,
                    [e for e in r.evidence if e["type"] == "claim_line" and e["ref"] == str(fx["line_no"])], "fraud_duplicate",
                    "Recalculated as units x unit price.", fx["line_no"])
            if d.get("total_off"):
                add(r, "set_field", "total_amount", d["expected_total"], claim.get("total_amount"), r.explanation,
                    [e for e in r.evidence if e["ref"] == "total_amount"], "fraud_duplicate", "Recalculated as the sum of line amounts.")
        elif r.rule_id == "COMP-001":
            for f in d.get("missing", []):
                if f in EDITABLE_FIELDS:
                    add(r, "set_field", f, None, None, r.explanation, r.evidence, "intake",
                        "No evidence on file for the correct value. The operator must enter it manually from the encounter record.")
    return props


def dry_run(claim, ref, results, proposals):
    """Validate each proposal against the engine without touching the claim. Returns projected status
    if every valid proposal with a value were approved."""
    failing = {r.rule_id for r in results if r.status == "fail"}
    combined = claim
    for p in proposals:
        if p["proposed_value"] is None:
            p["status"], p["validation_note"] = "pending", "Needs a manually entered value before it can be validated."
            continue
        try:
            patched = apply_patch(claim, p["op"], p["field"], p["proposed_value"], p["line_no"], ref)
        except CorrectionError as e:
            p["status"], p["validation_note"] = "invalid", f"Rejected by correction allow-list: {e}"
            continue
        after = {r.rule_id for r in validate_claim(patched, ref) if r.status == "fail"}
        new = after - failing
        if new:
            p["status"], p["validation_note"] = "invalid", f"Dry-run introduced new failures: {sorted(new)}"
            continue
        p["status"] = "pending"
        p["validation_note"] = ("Dry-run passed: rule " + p["rule_id"] + (" clears" if p["rule_id"] not in after else
                                " still needs the other proposals for this rule") + "; no new failures.")
        combined = apply_patch(combined, p["op"], p["field"], p["proposed_value"], p["line_no"], ref)
    proj_results = validate_claim(combined, ref) if combined is not claim else results
    return proj_results


class RecoveryAgent(BaseAgent):
    key, name = "recovery", "Recovery and Optimization Agent"
    responsibility = ("Consolidate findings from all specialists, prioritise corrections, draft a corrected-claim proposal, "
                      "and re-run validation on the proposal. Never change authoritative claim records.")
    tools = ["consolidate_findings", "draft_correction_proposals", "dry_run_validation", "estimate_effort"]

    def __init__(self):
        self.results, self.escalations = [], []
        self.proposals, self.projected_status = [], None

    def prepare(self, results, escalations):
        a = RecoveryAgent()
        a.results, a.escalations = results, escalations
        return a

    def investigate(self, ctx, run, out, peer):
        c, ref, results = ctx.claim, ctx.ref, self.results
        fails = ctx.rec.tool(self.key, run, "consolidate_findings", lambda: sorted(
            (r for r in results if r.status == "fail"), key=lambda r: SEVERITY_ORDER.get(r.severity, 9)))
        out.data["priority_order"] = [{"rule_id": r.rule_id, "severity": r.severity, "resolution": r.resolution,
                                       "next_action": r.next_action} for r in fails]
        self.proposals = ctx.rec.tool(self.key, run, "draft_correction_proposals", lambda: build_proposals(c, results),
                                      failing=[r.rule_id for r in fails])
        proj = ctx.rec.tool(self.key, run, "dry_run_validation", lambda: dry_run(c, ref, results, self.proposals),
                            proposals=len(self.proposals))
        self.projected_status = determine_outcome(proj, self.escalations)
        effort = ctx.rec.tool(self.key, run, "estimate_effort",
                              lambda: sum(settings.effort_minutes.get(r.rule_id, 10) for r in fails))
        valid = [p for p in self.proposals if p["status"] == "pending" and p["proposed_value"] is not None]
        out.data.update({"proposals_drafted": len(self.proposals), "proposals_validated": len(valid),
                         "projected_status_if_approved": self.projected_status,
                         "estimated_manual_minutes": effort,
                         "effort_basis": "configured synthetic assumption (EFFORT_MINUTES), not a measured figure",
                         "remaining_after_corrections": [r.rule_id for r in proj if r.status == "fail"]})
        for r in fails:
            if not any(p["rule_id"] == r.rule_id for p in self.proposals):
                out.findings.append(Finding(code=r.rule_id, status="fail", severity=r.severity, source="deterministic",
                                            explanation=f"No in-system correction available ({r.resolution}).",
                                            next_action=r.next_action, evidence=[Evidence(**e) for e in r.evidence[:2]]))
        out.summary = (f"{len(fails)} issue(s) consolidated; {len(valid)} validated proposal(s); projected "
                       f"{self.projected_status} if approved")
