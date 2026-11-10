"""The seven investigating specialist agents. Each runs logged tools against the shared claim context,
reports structured findings, and can ask a peer agent to review something outside its remit."""
from app.agents.base import BaseAgent
from app.schemas.agents import Evidence, Finding, ReviewRequest
from app.validation import engine as E


def peer_from(peer, key):
    """Return the peer message from `key`, if the orchestrator forwarded one."""
    return next((p for p in (peer or {}).get("all", []) if p.get("from") == key), None)


class IntakeAgent(BaseAgent):
    key, name = "intake", "Claim Intake Agent"
    responsibility = "Receive and parse claims, validate mandatory fields, classify the claim and route it."
    tools = ["parse_claim", "run_validation_rules", "classify_claim"]
    rule_ids = ["COMP-001", "COMP-002"]

    def investigate(self, ctx, run, out, peer):
        c, ref = ctx.claim, ctx.ref

        def parse():
            if not isinstance(c.get("lines"), list):
                raise ValueError("claim has no line items")
            return {"lines": len(c["lines"]), "fields_present": sum(1 for k, v in c.items() if v not in (None, "", []))}

        out.data["parsed"] = ctx.rec.tool(self.key, run, "parse_claim", parse, claim_id=c["claim_id"])
        res = self.rules(ctx, run, out)

        def classify():
            cats = sorted({(ref.procedure(l["procedure_code"]) or {}).get("category", "unknown") for l in c["lines"]})
            flags = []
            if (c.get("total_amount") or 0) >= 1000:
                flags.append("high_value")
            if E.procs_needing_auth(c, ref):
                flags.append("authorization_required")
            if len(c["lines"]) > 1:
                flags.append("multi_line")
            if "unknown" in cats:
                flags.append("unrecognised_procedure_code")
            return {"claim_type": c.get("claim_type"), "service_categories": cats, "risk_flags": flags}

        out.data["classification"] = ctx.rec.tool(self.key, run, "classify_claim", classify)
        out.data["missing_mandatory_fields"] = res["COMP-001"].details.get("missing", [])
        out.data["route"] = ["eligibility", "documentation", "coding", "authorization", "fraud_duplicate", "compliance"]
        out.summary = (f"Classified as {', '.join(out.data['classification']['service_categories'])}; "
                       f"{len(out.data['missing_mandatory_fields'])} mandatory field(s) missing")


class EligibilityAgent(BaseAgent):
    key, name = "eligibility", "Eligibility Agent"
    responsibility = "Check synthetic patient and policy records: identifiers, policy status and coverage dates."
    tools = ["lookup_patient", "lookup_policy", "run_validation_rules"]
    rule_ids = ["ELIG-001", "ELIG-002", "ELIG-003", "ELIG-004"]

    def investigate(self, ctx, run, out, peer):
        c, ref = ctx.claim, ctx.ref
        pat = ctx.rec.tool(self.key, run, "lookup_patient", lambda: ref.patients.get(c["patient_id"]), patient_id=c["patient_id"])
        pol, exact = ctx.rec.tool(self.key, run, "lookup_policy", lambda: E.policy_for(c, ref), patient_id=c["patient_id"],
                                  payer_id=c["payer_id"], policy_number=c.get("policy_number"))
        res = self.rules(ctx, run, out)
        active = res["ELIG-003"].status == "pass"
        out.data.update({"patient_found": bool(pat), "policy": pol, "policy_exact_match": exact,
                         "eligibility_status": "active" if active else ("inactive_on_service_date" if res["ELIG-003"].status == "fail" else "undetermined")})
        if res["ELIG-003"].status == "fail":
            out.review_requests.append(ReviewRequest(
                to_agent="authorization", reason="Coverage is not active on the date of service; any authorization on file "
                "should not be treated as sufficient.", context={"finding": "ELIG-003", "explanation": res["ELIG-003"].explanation}))
        out.summary = f"Eligibility {out.data['eligibility_status']}; policy match {'exact' if exact else 'not exact'}"


class DocumentationAgent(BaseAgent):
    key, name = "documentation", "Documentation Agent"
    responsibility = ("Inspect claim documentation, identify missing documents, and compare claim information against "
                      "the attached synthetic documents.")
    tools = ["get_required_documents", "list_attached_documents", "search_document_repository", "run_validation_rules",
             "extract_documented_codes"]
    rule_ids = ["DOC-001", "DOC-002"]
    ai_in_synthesis = True  # free-text notes can only be read by the model

    def investigate(self, ctx, run, out, peer):
        c, ref = ctx.claim, ctx.ref
        need = ctx.rec.tool(self.key, run, "get_required_documents", lambda: E.required_doc_types(c, ref), payer_id=c["payer_id"])
        docs = ctx.rec.tool(self.key, run, "list_attached_documents",
                            lambda: [{"id": d["id"], "doc_type": d["doc_type"], "extracted": d["extracted"]} for d in E.attached_docs(c, ref)],
                            claim_id=c["claim_id"])
        res = self.rules(ctx, run, out)
        if res["DOC-001"].status == "fail":
            found = ctx.rec.tool(self.key, run, "search_document_repository", lambda: res["DOC-001"].details.get("available", {}),
                                 patient_id=c["patient_id"], service_date=c["service_date"], types=res["DOC-001"].details["missing_types"])
            out.data["repository_matches"] = found
        out.data.update({"required": need, "attached": docs, "missing": res["DOC-001"].details.get("missing_types", []),
                         "completeness": "complete" if res["DOC-001"].status in ("pass", "not_applicable") else "incomplete"})
        if res["DOC-002"].status == "fail":
            out.review_requests.append(ReviewRequest(
                to_agent="coding", reason="An attached document names a different procedure from the one billed.",
                context={"finding": "DOC-002", "explanation": res["DOC-002"].explanation}))
        if peer_from(peer, "coding"):
            codes = ctx.rec.tool(self.key, run, "extract_documented_codes", lambda: E.documented_codes(c, ref), claim_id=c["claim_id"])
            out.data["documented_codes"] = codes
            out.acknowledged_peers.append("coding")
            n = len(codes["procedures"]) + len(codes["diagnoses"])
            out.findings.append(Finding(
                code="ADV-DOC-CODES", status="pass" if n else "warning", severity="low", source="agent_advisory",
                explanation=(f"Reply to Coding Agent: attached documentation states {n} valid code(s): "
                             + ", ".join(x["code"] for x in codes["procedures"] + codes["diagnoses"])) if n else
                "Reply to Coding Agent: attached documentation does not state a valid replacement code.",
                evidence=[Evidence(type="document", ref=x["document_id"], detail=f"states {x['code']}") for x in codes["procedures"] + codes["diagnoses"]]))
        out.summary = f"Documentation {out.data['completeness']}; {len(out.data['missing'])} missing"

    def ai_payload(self, ctx, out):
        return [{"id": d["id"], "doc_type": d["doc_type"], "text": d["content"]} for d in E.attached_docs(ctx.claim, ctx.ref)]

    def uses_ai(self, ctx):
        return super().uses_ai(ctx) and bool(ctx.claim.get("attached_document_ids"))


class CodingAgent(BaseAgent):
    key, name = "coding", "Medical Coding Agent"
    responsibility = ("Validate diagnosis and procedure code fields against the supplied synthetic reference dataset and "
                      "its explicit compatibility rules. Never certify a code; refer to a qualified coder when unsure.")
    tools = ["lookup_code_reference", "run_validation_rules"]
    rule_ids = ["COD-001", "COD-002", "COD-003"]

    def investigate(self, ctx, run, out, peer):
        c, ref = ctx.claim, ctx.ref
        codes = sorted({l["procedure_code"] for l in c["lines"] if l["procedure_code"]} | {d for l in c["lines"] for d in l["diagnosis_codes"] or []})
        looked = ctx.rec.tool(self.key, run, "lookup_code_reference",
                              lambda: {k: (ref.coding[k]["description"] if k in ref.coding else None) for k in codes}, codes=codes)
        res = self.rules(ctx, run, out)
        out.data.update({"codes": looked, "reference": "synthetic demo reference dataset (not official coding guidance)"})
        if res["COD-001"].status == "fail" or res["COD-002"].status == "fail":
            out.review_requests.append(ReviewRequest(
                to_agent="documentation", reason="A billed code is not in the reference dataset. Does the attached documentation "
                "state a valid code?", context={"finding": "COD-001/COD-002"}))
            out.uncertainty.append("Replacement codes come from the document extract and must be confirmed by a certified coder.")
        if (p := peer_from(peer, "documentation")):
            out.acknowledged_peers.append("documentation")
            out.findings.append(Finding(
                code="ADV-COD-REVIEW", status="warning", severity="high", source="agent_advisory", escalate=True,
                explanation="Revised position after Documentation Agent's evidence: the billed code pair is consistent in the "
                            "reference table, but the documentation names a different procedure. Code selection needs a "
                            "qualified coder.",
                next_action="Qualified coder review.", evidence=[Evidence(type="agent_finding", ref="documentation:DOC-002", detail=p.get("reason", ""))]))
        out.summary = "Codes checked against synthetic reference; " + ("issues found" if any(f.status == "fail" for f in out.findings) else "consistent")


class AuthorizationAgent(BaseAgent):
    key, name = "authorization", "Prior Authorization Agent"
    responsibility = "Inspect synthetic payer authorization requirements and verify authorization records."
    tools = ["get_authorization_requirements", "lookup_authorization", "search_authorizations_on_file", "run_validation_rules"]
    rule_ids = ["AUTH-001", "AUTH-002"]

    def investigate(self, ctx, run, out, peer):
        c, ref = ctx.claim, ctx.ref
        need = ctx.rec.tool(self.key, run, "get_authorization_requirements", lambda: E.procs_needing_auth(c, ref), payer_id=c["payer_id"])
        rec_ = None
        if c.get("authorization_number"):
            rec_ = ctx.rec.tool(self.key, run, "lookup_authorization", lambda: ref.auths_by_number.get(c["authorization_number"]),
                                auth_number=c["authorization_number"])
        res = self.rules(ctx, run, out)
        if res["AUTH-001"].status == "fail":
            out.data["on_file"] = ctx.rec.tool(self.key, run, "search_authorizations_on_file",
                                               lambda: res["AUTH-001"].details.get("on_file", []), patient_id=c["patient_id"], procedures=need)
        if not need:
            status = "not_required"
        elif res["AUTH-001"].status == "fail":
            status = "missing_but_on_file" if res["AUTH-001"].details.get("on_file") else "missing"
        elif res["AUTH-002"].status == "fail":
            status = "invalid"
        else:
            status = "valid"
        for p in (peer or {}).get("all", []):
            src = p.get("from")
            if status == "valid" and src in ("eligibility", "compliance"):
                why = ("coverage was not active on the date of service" if src == "eligibility"
                       else "the plan excludes the billed procedure")
                status = "on_file_but_not_sufficient"
                out.acknowledged_peers.append(src)
                out.findings.append(Finding(
                    code="ADV-AUTH-NOTE", status="warning", severity="high", source="agent_advisory",
                    explanation=f"Revised position after {src.title()} Agent's evidence: authorization {c.get('authorization_number')} "
                                f"is on file, but {why}, so it does not make the claim submittable.",
                    next_action="Resolve the coverage issue before relying on this authorization.",
                    evidence=[Evidence(type="agent_finding", ref=f"{src}", detail=p.get("reason", ""))]))
        out.data.update({"required_for": need, "authorization_record": rec_, "auth_status": status})
        out.summary = f"Authorization status: {status}"


class FraudDuplicateAgent(BaseAgent):
    key, name = "fraud_duplicate", "Fraud and Duplicate Detection Agent"
    responsibility = ("Screen for potential duplicate submissions and unusual billing patterns using transparent rules. "
                      "Never label anyone fraudulent; say 'potential duplicate', 'suspicious pattern' or 'investigation required'.")
    tools = ["find_matching_claims", "run_validation_rules"]
    rule_ids = ["DUP-001", "DUP-002", "BILL-001", "BILL-002"]

    def investigate(self, ctx, run, out, peer):
        c, ref = ctx.claim, ctx.ref
        same_day = ctx.rec.tool(self.key, run, "find_matching_claims",
                                lambda: [o["claim_id"] for o in ref.claims if o["claim_id"] != c["claim_id"]
                                         and o["patient_id"] == c["patient_id"] and o["service_date"] == c["service_date"]],
                                patient_id=c["patient_id"], service_date=c["service_date"])
        res = self.rules(ctx, run, out)
        dup = res["DUP-001"].status == "fail" or res["DUP-002"].status == "fail"
        out.data.update({"same_patient_same_day_claims": same_day,
                         "screening": "potential duplicate - investigation required" if dup else
                         ("same-day claim(s) exist but differ in billed services" if same_day else "no matching claims")})
        if dup:
            out.review_requests.append(ReviewRequest(to_agent="compliance", reason="Potential duplicate submission; confirm it is "
                                                     "held from the ready queue pending investigation.", context={"finding": "DUP"}))
        out.summary = out.data["screening"]


class ComplianceAgent(BaseAgent):
    key, name = "compliance", "Compliance Agent"
    responsibility = ("Check the supplied synthetic payer rules and workflow requirements, flag unsupported recommendations, "
                      "and make sure no claim is marked ready while a mandatory requirement is unresolved.")
    tools = ["load_payer_rules", "run_validation_rules", "audit_correction_proposals", "readiness_gate"]
    rule_ids = ["COV-001", "COMP-001"]

    def investigate(self, ctx, run, out, peer):
        c, ref = ctx.claim, ctx.ref
        rules = ctx.rec.tool(self.key, run, "load_payer_rules", lambda: {
            "required_documents": {k[1]: v for k, v in ref.required_docs.items() if k[0] == c["payer_id"]},
            "authorization_required": sorted(p for (pay, p) in ref.auth_required if pay == c["payer_id"])}, payer_id=c["payer_id"])
        res = self.rules(ctx, run, out)
        out.data["payer_rules_scope"] = "synthetic rules for this demo payer only; not representative of any real insurer or jurisdiction"
        out.data["payer_rules"] = rules
        if res["COV-001"].status == "fail":
            out.review_requests.append(ReviewRequest(to_agent="authorization", reason="The plan excludes the billed procedure; an "
                                                     "authorization on file does not establish coverage.", context={"finding": "COV-001"}))
        if peer_from(peer, "fraud_duplicate"):
            out.acknowledged_peers.append("fraud_duplicate")
            out.findings.append(Finding(code="ADV-COMP-HOLD", status="warning", severity="high", source="agent_advisory",
                                        explanation="Acknowledged Fraud and Duplicate Agent: claim is held from the ready queue until "
                                                    "the potential duplicate is investigated by a person.",
                                        next_action="Supervisor to confirm whether this is a resubmission."))
        out.summary = "Payer rule check: " + ("coverage exclusion found" if res["COV-001"].status == "fail" else "no policy conflict")

    def final_gate(self, ctx, run, results, proposals, proposed_status, escalations):
        """Final check after validation and recovery. Returns (status, notes)."""
        notes = []

        def audit():
            bad = [p["id"] for p in proposals if p["status"] == "pending" and not p["evidence"] and p["proposed_value"] is not None]
            return {"proposals": len(proposals), "without_evidence": bad}

        a = ctx.rec.tool(self.key, run, "audit_correction_proposals", audit)
        if a["without_evidence"]:
            notes.append(f"Unsupported recommendation(s) flagged: {a['without_evidence']}")

        def gate():
            blocking = [r.rule_id for r in results if r.status == "fail"]
            if proposed_status == "READY" and (blocking or escalations):
                return {"allowed": False, "blocking": blocking}
            return {"allowed": True, "blocking": blocking}

        g = ctx.rec.tool(self.key, run, "readiness_gate", gate, proposed_status=proposed_status)
        status = proposed_status
        if not g["allowed"]:
            status = "HUMAN_REVIEW"
            notes.append("Readiness gate blocked a READY status with unresolved requirements.")
        return status, notes, a


SPECIALISTS = [IntakeAgent(), EligibilityAgent(), DocumentationAgent(), CodingAgent(), AuthorizationAgent(),
               FraudDuplicateAgent(), ComplianceAgent()]
BY_KEY = {a.key: a for a in SPECIALISTS}
