"""Read-only lookup tables the validation engine and agent tools work against."""
from collections import defaultdict

from app.models import models as m


def _row(obj, fields):
    return {f: getattr(obj, f) for f in fields}


class RefData:
    def __init__(self):
        self.patients, self.providers, self.payers = {}, {}, {}
        self.policies_by_patient = defaultdict(list)
        self.documents, self.docs_by_patient = {}, defaultdict(list)
        self.auths_by_number, self.auths_by_patient = {}, defaultdict(list)
        self.coding = {}
        self.required_docs = {}  # (payer_id, category) -> [doc types]
        self.auth_required = set()  # (payer_id, procedure_code)
        self.claims = []  # current snapshots of every claim (for duplicate screening)

    @classmethod
    def from_session(cls, db):
        from app.services.claims import snapshot
        r = cls()
        for p in db.query(m.Patient):
            r.patients[p.id] = _row(p, ["id", "first_name", "last_name", "dob", "gender", "member_id"])
        for p in db.query(m.Provider):
            r.providers[p.id] = _row(p, ["id", "name", "npi", "specialty"])
        for p in db.query(m.Payer):
            r.payers[p.id] = _row(p, ["id", "name"])
        for p in db.query(m.InsurancePolicy):
            r.policies_by_patient[p.patient_id].append(_row(p, [
                "id", "policy_number", "patient_id", "payer_id", "plan_name", "effective_date", "termination_date",
                "status", "excluded_procedures"]))
        for d in db.query(m.ClinicalDocument):
            row = _row(d, ["id", "patient_id", "provider_id", "doc_type", "service_date", "content", "extracted"])
            r.documents[d.id] = row
            r.docs_by_patient[d.patient_id].append(row)
        for a in db.query(m.AuthorizationRecord):
            row = _row(a, ["auth_number", "patient_id", "payer_id", "procedure_code", "valid_from", "valid_to", "status"])
            r.auths_by_number[a.auth_number] = row
            r.auths_by_patient[a.patient_id].append(row)
        for c in db.query(m.CodingReference):
            r.coding[c.code] = _row(c, ["code", "code_type", "description", "category", "unit_price", "max_units",
                                        "compatible_diagnoses"])
        for pr in db.query(m.PayerRule):
            if pr.rule_type == "required_documents":
                r.required_docs[(pr.payer_id, pr.key)] = list(pr.value or [])
            elif pr.rule_type == "authorization_required":
                r.auth_required.add((pr.payer_id, pr.key))
        r.claims = [snapshot(c) for c in db.query(m.Claim).order_by(m.Claim.seq)]
        return r

    def replace_claim(self, snap):
        self.claims = [snap if c["claim_id"] == snap["claim_id"] else c for c in self.claims]
        if not any(c["claim_id"] == snap["claim_id"] for c in self.claims):
            self.claims.append(snap)

    # convenience
    def procedure(self, code):
        r = self.coding.get(code)
        return r if r and r["code_type"] == "procedure" else None

    def diagnosis(self, code):
        r = self.coding.get(code)
        return r if r and r["code_type"] == "diagnosis" else None
