"""Deterministic claim validation engine.

This module is the sole authority on whether mandatory requirements pass. No LLM output is consulted
here. Every rule returns one RuleResult per claim with evidence and a suggested next action.

`resolution` on a failed rule says how it can be cleared:
  correctable     - a specific correction can be proposed from evidence already on file
  external_action - billing staff must obtain something from outside the system
  human_review    - needs professional judgment (coder, clinician, supervisor)
"""
from dataclasses import asdict, dataclass, field

RULES = [
    {"rule_id": "COMP-001", "name": "Mandatory claim fields complete", "dimension": "compliance", "severity": "high", "agent": "intake",
     "description": "Patient, provider, payer, service date, place of service and at least one coded line are present."},
    {"rule_id": "COMP-002", "name": "Claim dates are logical", "dimension": "compliance", "severity": "medium", "agent": "intake",
     "description": "Service date is not after the submission date."},
    {"rule_id": "ELIG-001", "name": "Patient identifiers present", "dimension": "eligibility", "severity": "high", "agent": "eligibility",
     "description": "Member ID and date of birth are present on the claim."},
    {"rule_id": "ELIG-002", "name": "Policy identifier matches registry", "dimension": "eligibility", "severity": "high", "agent": "eligibility",
     "description": "Policy number on the claim matches a policy held by the patient with the billed payer."},
    {"rule_id": "ELIG-003", "name": "Coverage active on date of service", "dimension": "eligibility", "severity": "critical", "agent": "eligibility",
     "description": "Policy dates are valid and cover the date of service."},
    {"rule_id": "ELIG-004", "name": "Patient details match registry", "dimension": "eligibility", "severity": "high", "agent": "eligibility",
     "description": "Member ID and date of birth on the claim agree with the patient registry."},
    {"rule_id": "DOC-001", "name": "Required documents attached", "dimension": "documentation", "severity": "high", "agent": "documentation",
     "description": "Every document type the payer rule requires for the billed service is attached."},
    {"rule_id": "DOC-002", "name": "Documents consistent with claim", "dimension": "documentation", "severity": "critical", "agent": "documentation",
     "description": "Attached documents belong to the patient and name the billed procedure."},
    {"rule_id": "COD-001", "name": "Diagnosis codes valid", "dimension": "coding", "severity": "high", "agent": "coding",
     "description": "Every diagnosis code exists in the synthetic reference dataset."},
    {"rule_id": "COD-002", "name": "Procedure codes valid", "dimension": "coding", "severity": "high", "agent": "coding",
     "description": "Every procedure code exists in the synthetic reference dataset."},
    {"rule_id": "COD-003", "name": "Diagnosis supports procedure", "dimension": "coding", "severity": "high", "agent": "coding",
     "description": "At least one diagnosis on each line is listed as compatible with the procedure in the reference rules."},
    {"rule_id": "AUTH-001", "name": "Authorization present when required", "dimension": "authorization", "severity": "critical", "agent": "authorization",
     "description": "Claims for procedures the payer lists as requiring prior authorization reference one."},
    {"rule_id": "AUTH-002", "name": "Authorization valid for service", "dimension": "authorization", "severity": "critical", "agent": "authorization",
     "description": "Referenced authorization exists, matches patient and procedure, and covers the date of service."},
    {"rule_id": "DUP-001", "name": "Claim control number unique", "dimension": "billing", "severity": "critical", "agent": "fraud_duplicate",
     "description": "No earlier claim carries the same control number."},
    {"rule_id": "DUP-002", "name": "Billing combination unique", "dimension": "billing", "severity": "critical", "agent": "fraud_duplicate",
     "description": "No earlier claim has the same patient, provider, service date, procedures and total."},
    {"rule_id": "BILL-001", "name": "Billing arithmetic consistent", "dimension": "billing", "severity": "medium", "agent": "fraud_duplicate",
     "description": "Line amounts equal units x unit price and the claim total equals the sum of lines."},
    {"rule_id": "BILL-002", "name": "Units within reference limit", "dimension": "billing", "severity": "high", "agent": "fraud_duplicate",
     "description": "Billed units do not exceed the per-claim maximum in the reference dataset."},
    {"rule_id": "COV-001", "name": "Procedure covered by plan", "dimension": "compliance", "severity": "critical", "agent": "compliance",
     "description": "Billed procedures are not on the plan's exclusion list."},
]
RULE_META = {r["rule_id"]: r for r in RULES}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class RuleResult:
    rule_id: str
    claim_id: str
    status: str  # pass | fail | warning | not_applicable
    severity: str
    dimension: str
    explanation: str
    evidence: list = field(default_factory=list)
    next_action: str = ""
    resolution: str | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _ev(kind, ref, detail):
    return {"type": kind, "ref": ref, "detail": detail}


def _res(rule_id, claim, status, explanation, evidence=None, next_action="", resolution=None, details=None):
    meta = RULE_META[rule_id]
    return RuleResult(rule_id, claim["claim_id"], status, meta["severity"], meta["dimension"], explanation,
                      evidence or [], next_action, resolution if status == "fail" else None, details or {})


def policy_for(claim, ref):
    """Return (policy, exact_match). Falls back to the patient's policy with the billed payer."""
    pols = ref.policies_by_patient.get(claim.get("patient_id"), [])
    for p in pols:
        if p["policy_number"] == claim.get("policy_number") and p["payer_id"] == claim.get("payer_id"):
            return p, True
    same_payer = [p for p in pols if p["payer_id"] == claim.get("payer_id")]
    return (same_payer[0], False) if len(same_payer) == 1 else (None, False)


def attached_docs(claim, ref):
    return [ref.documents[d] for d in claim.get("attached_document_ids") or [] if d in ref.documents]


def documented_codes(claim, ref):
    """Codes stated in the structured extract of attached documents (used to support corrections)."""
    procs, dxs = [], []
    for d in attached_docs(claim, ref):
        ex = d.get("extracted") or {}
        if ex.get("procedure_code") and ref.procedure(ex["procedure_code"]):
            procs.append({"code": ex["procedure_code"], "document_id": d["id"]})
        for dx in ex.get("diagnosis_codes") or []:
            if ref.diagnosis(dx):
                dxs.append({"code": dx, "document_id": d["id"]})
    return {"procedures": procs, "diagnoses": dxs}


# ---------------------------------------------------------------- rules
def comp_001(c, ref):
    missing = [f for f in ("patient_id", "provider_id", "payer_id", "service_date", "place_of_service") if not c.get(f)]
    if not c.get("lines"):
        missing.append("lines")
    for ln in c.get("lines") or []:
        if not ln.get("procedure_code"):
            missing.append(f"line {ln['line_no']} procedure_code")
        if not ln.get("diagnosis_codes"):
            missing.append(f"line {ln['line_no']} diagnosis_codes")
    if missing:
        return _res("COMP-001", c, "fail", f"Mandatory field(s) missing: {', '.join(missing)}.",
                    [_ev("claim_field", f, "empty on claim") for f in missing],
                    "Enter the missing value(s) from the source encounter record.", "correctable", {"missing": missing})
    return _res("COMP-001", c, "pass", "All mandatory claim fields are present.")


def comp_002(c, ref):
    sd, sub = c.get("service_date"), c.get("submitted_date")
    if not sd or not sub:
        return _res("COMP-002", c, "not_applicable", "Dates unavailable.")
    if sd > sub:
        return _res("COMP-002", c, "fail", f"Service date {sd} is after submission date {sub}.",
                    [_ev("claim_field", "service_date", sd), _ev("claim_field", "submitted_date", sub)],
                    "Confirm the correct date of service with the provider.", "human_review")
    return _res("COMP-002", c, "pass", "Service date precedes submission date.")


def elig_001(c, ref):
    missing = [f for f in ("member_id", "patient_dob") if not c.get(f)]
    pat = ref.patients.get(c.get("patient_id"))
    if not pat:
        return _res("ELIG-001", c, "fail", "Patient reference not found in the registry.",
                    [_ev("claim_field", "patient_id", str(c.get("patient_id")))], "Verify patient registration.", "human_review")
    if missing:
        reg = {"member_id": pat["member_id"], "patient_dob": pat["dob"]}
        return _res("ELIG-001", c, "fail", f"Patient identifier(s) missing on claim: {', '.join(missing)}.",
                    [_ev("patient_registry", pat["id"], f"registry holds {f} = {reg[f]}") for f in missing],
                    "Populate from the patient registry.", "correctable", {"missing": missing, "registry": reg})
    return _res("ELIG-001", c, "pass", "Member ID and date of birth are present.")


def elig_002(c, ref):
    pol, exact = policy_for(c, ref)
    if not c.get("policy_number"):
        cand = [pol["policy_number"]] if pol else []
        return _res("ELIG-002", c, "fail", "Policy number is missing on the claim.",
                    [_ev("policy_registry", pol["id"], f"patient holds policy {pol['policy_number']}")] if pol else [],
                    "Populate the policy number from the registry.", "correctable" if cand else "human_review",
                    {"claim_policy_number": None, "registry_policy_numbers": cand})
    if exact:
        return _res("ELIG-002", c, "pass", f"Policy {c['policy_number']} matches the registry.",
                    [_ev("policy_registry", pol["id"], f"{pol['policy_number']} / {pol['plan_name']}")])
    if pol:
        return _res("ELIG-002", c, "fail",
                    f"Policy number {c['policy_number']} on the claim does not match the patient's registered policy "
                    f"{pol['policy_number']} with this payer.",
                    [_ev("claim_field", "policy_number", c["policy_number"]),
                     _ev("policy_registry", pol["id"], f"registered policy {pol['policy_number']}")],
                    "Replace with the registered policy number.", "correctable",
                    {"claim_policy_number": c["policy_number"], "registry_policy_numbers": [pol["policy_number"]]})
    return _res("ELIG-002", c, "fail", "No policy with the billed payer is registered for this patient.",
                [_ev("claim_field", "policy_number", c["policy_number"])], "Verify insurance details with the patient.",
                "human_review", {"claim_policy_number": c["policy_number"], "registry_policy_numbers": []})


def elig_003(c, ref):
    pol, _ = policy_for(c, ref)
    if not pol or not c.get("service_date"):
        return _res("ELIG-003", c, "not_applicable", "No policy record available to check coverage dates.")
    eff, term, dos = pol["effective_date"], pol["termination_date"], c["service_date"]
    ev = [_ev("policy_registry", pol["id"], f"effective {eff}, terminates {term or 'open'}, status {pol['status']}"),
          _ev("claim_field", "service_date", dos)]
    if eff and term and eff > term:
        return _res("ELIG-003", c, "fail", f"Policy dates are invalid (effective {eff} after termination {term}).", ev,
                    "Have eligibility staff confirm the policy period with the payer.", "human_review")
    if (eff and dos < eff) or (term and dos > term):
        return _res("ELIG-003", c, "fail", f"Coverage was not active on the date of service {dos} "
                    f"(policy period {eff} to {term or 'open'}).", ev,
                    "Confirm coverage with the payer or identify other insurance before submitting.", "human_review")
    return _res("ELIG-003", c, "pass", f"Coverage active on {dos}.", ev)


def elig_004(c, ref):
    pat = ref.patients.get(c.get("patient_id"))
    if not pat:
        return _res("ELIG-004", c, "not_applicable", "Patient not in registry.")
    diffs = []
    if c.get("member_id") and c["member_id"] != pat["member_id"]:
        diffs.append(("member_id", c["member_id"], pat["member_id"]))
    if c.get("patient_dob") and c["patient_dob"] != pat["dob"]:
        diffs.append(("patient_dob", c["patient_dob"], pat["dob"]))
    if diffs:
        return _res("ELIG-004", c, "fail", "Claim and registry disagree on: " + ", ".join(d[0] for d in diffs) + ".",
                    [_ev("patient_registry", pat["id"], f"{f}: claim {a} vs registry {b}") for f, a, b in diffs],
                    "Verify patient identity before submission.", "human_review", {"differences": diffs})
    return _res("ELIG-004", c, "pass", "Patient details agree with the registry.")


def cov_001(c, ref):
    pol, _ = policy_for(c, ref)
    if not pol:
        return _res("COV-001", c, "not_applicable", "No policy record available.")
    excluded = [ln["procedure_code"] for ln in c["lines"] if ln["procedure_code"] in (pol.get("excluded_procedures") or [])]
    if excluded:
        return _res("COV-001", c, "fail", f"Plan '{pol['plan_name']}' excludes billed procedure(s): {', '.join(excluded)}.",
                    [_ev("policy_registry", pol["id"], f"exclusions: {pol['excluded_procedures']}")],
                    "Review benefits with the payer; consider patient responsibility.", "human_review", {"excluded": excluded})
    return _res("COV-001", c, "pass", "No billed procedure is on the plan exclusion list.")


def required_doc_types(c, ref):
    types = []
    for ln in c["lines"]:
        p = ref.procedure(ln["procedure_code"])
        if p:
            for t in ref.required_docs.get((c["payer_id"], p["category"]), []):
                if t not in types:
                    types.append(t)
    return types


def doc_001(c, ref):
    need = required_doc_types(c, ref)
    if not need:
        return _res("DOC-001", c, "not_applicable", "No document requirement could be determined for the billed codes.")
    docs = attached_docs(c, ref)
    have = {d["doc_type"] for d in docs if d["patient_id"] == c["patient_id"]}
    missing = [t for t in need if t not in have]
    if not missing:
        return _res("DOC-001", c, "pass", f"Required documents attached: {', '.join(need)}.",
                    [_ev("document", d["id"], d["doc_type"]) for d in docs])
    billed = {ln["procedure_code"] for ln in c["lines"]}
    available = {}
    for d in ref.docs_by_patient.get(c["patient_id"], []):
        if (d["doc_type"] in missing and d["service_date"] == c["service_date"]
                and d["id"] not in c["attached_document_ids"] and d["doc_type"] not in available
                and (d["extracted"] or {}).get("procedure_code") in billed):
            available[d["doc_type"]] = d["id"]
    all_found = all(t in available for t in missing)
    ev = [_ev("payer_rule", c["payer_id"], f"requires {', '.join(need)}")]
    ev += [_ev("document_repository", i, f"unattached {t} for this patient and date") for t, i in available.items()]
    return _res("DOC-001", c, "fail", f"Missing required document(s): {', '.join(missing)}.", ev,
                "Attach the document found in the repository." if all_found else "Request the missing document from the provider.",
                "correctable" if all_found else "external_action", {"missing_types": missing, "available": available})


def doc_002(c, ref):
    docs = attached_docs(c, ref)
    if not docs:
        return _res("DOC-002", c, "not_applicable", "No documents attached.")
    billed = [ln["procedure_code"] for ln in c["lines"]]
    problems, ev = [], []
    for d in docs:
        if d["patient_id"] != c["patient_id"]:
            problems.append(f"{d['id']} belongs to another patient")
            ev.append(_ev("document", d["id"], f"patient {d['patient_id']}"))
        dp = (d.get("extracted") or {}).get("procedure_code")
        if dp and all(ref.procedure(b) for b in billed) and dp not in billed:
            problems.append(f"{d['id']} ({d['doc_type']}) documents {dp}, claim bills {', '.join(billed)}")
            ev.append(_ev("document", d["id"], f"documents procedure {dp}"))
    if problems:
        return _res("DOC-002", c, "fail", "Document and claim disagree: " + "; ".join(problems) + ".", ev,
                    "Have a qualified coder reconcile the documentation with the billed service.", "human_review",
                    {"problems": problems})
    return _res("DOC-002", c, "pass", "Attached documents agree with the billed procedure(s).",
                [_ev("document", d["id"], d["doc_type"]) for d in docs])


def _code_rule(rule_id, c, ref, kind):
    invalid = []
    doc_codes = documented_codes(c, ref)
    for ln in c["lines"]:
        if kind == "diagnosis":
            present = set(ln["diagnosis_codes"] or [])
            for dx in ln["diagnosis_codes"] or []:
                if not ref.diagnosis(dx):
                    proc = ref.procedure(ln["procedure_code"])
                    sug = next((d for d in doc_codes["diagnoses"] if d["code"] not in present and
                                (not proc or d["code"] in (proc["compatible_diagnoses"] or []))), None)
                    invalid.append({"line_no": ln["line_no"], "code": dx, "suggested": sug["code"] if sug else None,
                                    "source_document": sug["document_id"] if sug else None})
        else:
            if ln["procedure_code"] and not ref.procedure(ln["procedure_code"]):
                billed = {l["procedure_code"] for l in c["lines"]}
                sug = next((p for p in doc_codes["procedures"] if p["code"] not in billed), None)
                invalid.append({"line_no": ln["line_no"], "code": ln["procedure_code"], "suggested": sug["code"] if sug else None,
                                "source_document": sug["document_id"] if sug else None})
    if not invalid:
        return _res(rule_id, c, "pass", f"All {kind} codes exist in the synthetic reference dataset.")
    supported = all(i["suggested"] for i in invalid)
    ev = [_ev("coding_reference", i["code"], f"line {i['line_no']}: not in reference dataset") for i in invalid]
    ev += [_ev("document", i["source_document"], f"documents {kind} code {i['suggested']}") for i in invalid if i["suggested"]]
    return _res(rule_id, c, "fail",
                f"Invalid {kind} code(s): " + ", ".join(f"{i['code']} (line {i['line_no']})" for i in invalid) + ".", ev,
                "A certified coder should confirm the code documented in the attached record." if supported
                else "Refer to a certified coder; documentation does not state a valid code.",
                "correctable" if supported else "human_review", {"invalid": invalid})


def cod_001(c, ref):
    return _code_rule("COD-001", c, ref, "diagnosis")


def cod_002(c, ref):
    return _code_rule("COD-002", c, ref, "procedure")


def cod_003(c, ref):
    bad, checked = [], 0
    for ln in c["lines"]:
        proc = ref.procedure(ln["procedure_code"])
        valid_dx = [d for d in ln["diagnosis_codes"] or [] if ref.diagnosis(d)]
        if not proc or not valid_dx:
            continue
        checked += 1
        if not any(d in (proc["compatible_diagnoses"] or []) for d in valid_dx):
            bad.append({"line_no": ln["line_no"], "procedure": ln["procedure_code"], "diagnoses": valid_dx})
    if not checked:
        return _res("COD-003", c, "not_applicable", "No line has both a valid procedure and a valid diagnosis to compare.")
    if bad:
        return _res("COD-003", c, "fail", "Diagnosis does not support procedure under the reference rules: " +
                    "; ".join(f"line {b['line_no']} {b['procedure']} with {', '.join(b['diagnoses'])}" for b in bad) + ".",
                    [_ev("coding_reference", b["procedure"], f"compatible diagnoses: {ref.procedure(b['procedure'])['compatible_diagnoses']}") for b in bad],
                    "Refer to a certified coder to review diagnosis selection against the documentation.", "human_review", {"mismatches": bad})
    return _res("COD-003", c, "pass", "Each line has a diagnosis the reference rules list as compatible.")


def procs_needing_auth(c, ref):
    return [ln["procedure_code"] for ln in c["lines"] if (c["payer_id"], ln["procedure_code"]) in ref.auth_required]


def usable_auths(c, ref, procs):
    dos = c.get("service_date") or ""
    return [a for a in ref.auths_by_patient.get(c["patient_id"], [])
            if a["procedure_code"] in procs and a["payer_id"] == c["payer_id"] and a["status"] == "approved"
            and a["valid_from"] <= dos <= a["valid_to"]]


def auth_001(c, ref):
    need = procs_needing_auth(c, ref)
    if not need:
        return _res("AUTH-001", c, "not_applicable", "Payer rules do not require prior authorization for the billed procedures.")
    ev = [_ev("payer_rule", c["payer_id"], f"authorization required for {', '.join(need)}")]
    if c.get("authorization_number"):
        return _res("AUTH-001", c, "pass", f"Authorization {c['authorization_number']} referenced.", ev)
    on_file = usable_auths(c, ref, need)
    ev += [_ev("authorization_record", a["auth_number"], f"approved for {a['procedure_code']}, {a['valid_from']} to {a['valid_to']}") for a in on_file]
    return _res("AUTH-001", c, "fail", f"Prior authorization is required for {', '.join(need)} but none is referenced.", ev,
                "Link the approved authorization found on file." if on_file else "Obtain prior authorization from the payer before submission.",
                "correctable" if on_file else "external_action", {"required_for": need, "on_file": [a["auth_number"] for a in on_file]})


def auth_002(c, ref):
    an = c.get("authorization_number")
    if not an:
        return _res("AUTH-002", c, "not_applicable", "No authorization referenced.")
    a = ref.auths_by_number.get(an)
    if not a:
        return _res("AUTH-002", c, "fail", f"Authorization {an} is not in the authorization records.",
                    [_ev("claim_field", "authorization_number", an)], "Verify the authorization number with the payer.", "external_action")
    ev = [_ev("authorization_record", an, f"{a['status']} for {a['procedure_code']}, {a['valid_from']} to {a['valid_to']}")]
    problems = []
    if a["patient_id"] != c["patient_id"]:
        problems.append("issued for a different patient")
    need = procs_needing_auth(c, ref)
    if need and a["procedure_code"] not in [ln["procedure_code"] for ln in c["lines"]]:
        problems.append(f"issued for {a['procedure_code']}, not a billed procedure")
    dos = c.get("service_date") or ""
    if not (a["valid_from"] <= dos <= a["valid_to"]) or a["status"] != "approved":
        problems.append(f"not valid on the date of service {dos} (valid {a['valid_from']} to {a['valid_to']}, status {a['status']})")
    if problems:
        return _res("AUTH-002", c, "fail", f"Authorization {an} " + "; ".join(problems) + ".", ev,
                    "Request a renewed or corrected authorization from the payer.", "external_action", {"problems": problems})
    return _res("AUTH-002", c, "pass", f"Authorization {an} is valid for the service.", ev)


def _earlier(c, ref):
    return [o for o in ref.claims if o["claim_id"] != c["claim_id"] and (o.get("seq") or 0) < (c.get("seq") or 10 ** 9)]


def dup_001(c, ref):
    if not c.get("control_number"):
        return _res("DUP-001", c, "not_applicable", "No control number.")
    hits = [o for o in _earlier(c, ref) if o.get("control_number") == c["control_number"]]
    if hits:
        return _res("DUP-001", c, "fail", f"Control number {c['control_number']} was already used by {', '.join(h['claim_id'] for h in hits)}.",
                    [_ev("claim", h["claim_id"], f"same control number, submitted {h['submitted_date']}") for h in hits],
                    "Potential duplicate: investigate before submitting.", "human_review", {"matches": [h["claim_id"] for h in hits]})
    return _res("DUP-001", c, "pass", "Control number is unique.")


def _combo(c):
    return (c.get("patient_id"), c.get("provider_id"), c.get("service_date"),
            tuple(sorted(l["procedure_code"] or "" for l in c["lines"])), round(float(c.get("total_amount") or 0), 2))


def dup_002(c, ref):
    key = _combo(c)
    hits = [o for o in _earlier(c, ref) if _combo(o) == key]
    if hits:
        return _res("DUP-002", c, "fail", "Same patient, provider, service date, procedures and total as " +
                    ", ".join(h["claim_id"] for h in hits) + ".",
                    [_ev("claim", h["claim_id"], f"identical billing combination, control number {h['control_number']}") for h in hits],
                    "Potential duplicate: investigate whether this is a resubmission.", "human_review", {"matches": [h["claim_id"] for h in hits]})
    return _res("DUP-002", c, "pass", "No earlier claim has the same billing combination.")


def bill_001(c, ref):
    fixes, ev = [], []
    for ln in c["lines"]:
        if ln.get("units") is None or ln.get("unit_price") is None:
            continue
        exp = round(ln["units"] * ln["unit_price"], 2)
        if ln.get("amount") is None or abs(ln["amount"] - exp) > 0.005:
            fixes.append({"line_no": ln["line_no"], "expected": exp, "actual": ln.get("amount")})
            ev.append(_ev("claim_line", str(ln["line_no"]), f"{ln['units']} x {ln['unit_price']} = {exp}, billed {ln.get('amount')}"))
    line_sum = round(sum(f["expected"] if (f := next((x for x in fixes if x["line_no"] == ln["line_no"]), None)) else (ln.get("amount") or 0)
                         for ln in c["lines"]), 2)
    total_off = c.get("total_amount") is None or abs(c["total_amount"] - line_sum) > 0.005
    if total_off:
        ev.append(_ev("claim_field", "total_amount", f"lines sum to {line_sum}, claim total {c.get('total_amount')}"))
    if fixes or total_off:
        return _res("BILL-001", c, "fail", "Billing arithmetic is inconsistent" +
                    (f": claim total {c.get('total_amount')} but lines sum to {line_sum}." if total_off else " on one or more lines."), ev,
                    "Recalculate from units and unit price.", "correctable",
                    {"line_fixes": fixes, "expected_total": line_sum, "total_off": total_off})
    return _res("BILL-001", c, "pass", "Line amounts and claim total are consistent.")


def bill_002(c, ref):
    over = []
    for ln in c["lines"]:
        p = ref.procedure(ln["procedure_code"])
        if p and p["max_units"] and (ln.get("units") or 0) > p["max_units"]:
            over.append({"line_no": ln["line_no"], "procedure": ln["procedure_code"], "units": ln["units"], "max": p["max_units"]})
    if over:
        return _res("BILL-002", c, "fail", "Units exceed the reference limit: " +
                    "; ".join(f"line {o['line_no']} {o['procedure']} billed {o['units']}, limit {o['max']}" for o in over) + ".",
                    [_ev("coding_reference", o["procedure"], f"max units {o['max']}") for o in over],
                    "Unusual billing pattern: confirm units against the treatment record.", "human_review", {"over": over})
    return _res("BILL-002", c, "pass", "Units are within reference limits.")


RULE_FUNCS = {"COMP-001": comp_001, "COMP-002": comp_002, "ELIG-001": elig_001, "ELIG-002": elig_002, "ELIG-003": elig_003,
              "ELIG-004": elig_004, "DOC-001": doc_001, "DOC-002": doc_002, "COD-001": cod_001, "COD-002": cod_002,
              "COD-003": cod_003, "AUTH-001": auth_001, "AUTH-002": auth_002, "DUP-001": dup_001, "DUP-002": dup_002,
              "BILL-001": bill_001, "BILL-002": bill_002, "COV-001": cov_001}


def run_rules(claim: dict, ref, rule_ids=None) -> list[RuleResult]:
    return [RULE_FUNCS[r](claim, ref) for r in (rule_ids or RULE_FUNCS)]


def validate_claim(claim: dict, ref) -> list[RuleResult]:
    return run_rules(claim, ref)


def readiness_score(results, weights) -> tuple[float, dict]:
    """Weighted administrative readiness indicator 0-100. NOT a probability of payer approval."""
    points = {"pass": 1.0, "warning": 0.5, "fail": 0.0}
    dims = {}
    for dim in weights:
        rs = [r for r in results if r.dimension == dim and r.status in points]
        if any(r.status == "fail" and r.severity == "critical" for r in rs):
            dims[dim] = 0.0  # a critical failure empties its dimension
        else:
            dims[dim] = round(sum(points[r.status] for r in rs) / len(rs), 3) if rs else 1.0
    total = sum(weights.values()) or 1
    return round(sum(dims[d] * w for d, w in weights.items()) * 100 / total, 1), dims


def determine_outcome(results, escalations=()) -> str:
    """READY only when no deterministic rule fails and nothing has escalated the claim."""
    fails = [r for r in results if r.status == "fail"]
    if any(r.resolution == "human_review" for r in fails) or escalations:
        return "HUMAN_REVIEW"
    if fails:
        return "REQUIRES_CORRECTION"
    return "READY"
