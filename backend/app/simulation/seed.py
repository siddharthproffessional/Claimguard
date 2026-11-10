"""Deterministic synthetic dataset generator for OPERATION ZERO REJECTION.

Everything here is invented. Diagnosis codes follow ICD-10-CM formatting; procedure codes are
SYNTHETIC ("SP" prefix) and deliberately not CPT/HCPCS. The compatibility table, payer rules and
prices are demo assumptions, not official coding or payer policy. See docs/DATA_ASSUMPTIONS.md.
"""
import copy
import random
from datetime import date, timedelta

PAYERS = [
    {"id": "PAY-MER", "name": "Meridian Health Plan (synthetic)"},
    {"id": "PAY-NOR", "name": "Northgate Mutual (synthetic)"},
    {"id": "PAY-SOL", "name": "Solara Care (synthetic)"},
]
PROVIDERS = [
    {"id": "PRV-001", "name": "Harbourview Orthopaedic Clinic", "npi": "9000000011", "specialty": "Orthopaedics"},
    {"id": "PRV-002", "name": "Cedar Park Family Practice", "npi": "9000000022", "specialty": "Family Medicine"},
    {"id": "PRV-003", "name": "Lakeshore Diagnostic Imaging", "npi": "9000000033", "specialty": "Radiology"},
    {"id": "PRV-004", "name": "Summit Surgical & Specialty Centre", "npi": "9000000044", "specialty": "Multi-specialty"},
]
DIAGNOSES = {
    "E11.9": "Type 2 diabetes mellitus without complications",
    "I10": "Essential hypertension",
    "J45.909": "Asthma, unspecified, uncomplicated",
    "M54.50": "Low back pain, unspecified",
    "M17.11": "Primary osteoarthritis, right knee",
    "M17.12": "Primary osteoarthritis, left knee",
    "R51.9": "Headache, unspecified",
    "S83.511A": "Sprain of anterior cruciate ligament, right knee, initial encounter",
    "K21.9": "Gastro-oesophageal reflux disease without oesophagitis",
    "R07.9": "Chest pain, unspecified",
    "Z00.00": "General adult medical examination without abnormal findings",
    "N39.0": "Urinary tract infection, site not specified",
    "H25.11": "Age-related nuclear cataract, right eye",
    "G47.33": "Obstructive sleep apnoea",
}
ALL_DX = list(DIAGNOSES)
# code: (description, category, unit_price, max_units, compatible diagnoses)
PROCEDURES = {
    "SP1001": ("Office visit, established patient", "evaluation", 140.0, 1, ALL_DX),
    "SP1002": ("Preventive adult examination", "evaluation", 210.0, 1, ["Z00.00"]),
    "SP2001": ("MRI knee without contrast", "imaging", 980.0, 1, ["M17.11", "M17.12", "S83.511A"]),
    "SP2002": ("CT head without contrast", "imaging", 760.0, 1, ["R51.9"]),
    "SP2003": ("Chest X-ray, two views", "imaging", 95.0, 1, ["R07.9", "J45.909"]),
    "SP3001": ("Knee arthroscopy", "surgery", 4200.0, 1, ["M17.11", "M17.12", "S83.511A"]),
    "SP3002": ("Cataract extraction with lens implant", "surgery", 3100.0, 1, ["H25.11"]),
    "SP4001": ("Physical therapy session", "therapy", 85.0, 4, ["M54.50", "M17.11", "M17.12", "S83.511A"]),
    "SP5001": ("HbA1c laboratory test", "lab", 38.0, 1, ["E11.9"]),
    "SP5002": ("Urinalysis", "lab", 22.0, 1, ["N39.0"]),
    "SP6001": ("Overnight sleep study", "diagnostic", 1350.0, 1, ["G47.33"]),
    "SP6002": ("Upper GI endoscopy", "diagnostic", 1650.0, 1, ["K21.9"]),
    "SP7001": ("Spirometry", "diagnostic_minor", 70.0, 1, ["J45.909"]),
    "SP7002": ("Electrocardiogram", "diagnostic_minor", 55.0, 1, ["R07.9", "I10"]),
}
REQUIRED_DOCS = {
    "evaluation": ["clinical_note"],
    "imaging": ["clinical_note", "imaging_order"],
    "surgery": ["operative_report"],
    "therapy": ["therapy_plan"],
    "lab": ["clinical_note"],
    "diagnostic": ["procedure_report"],
    "diagnostic_minor": ["clinical_note"],
}
AUTH_ALL_PAYERS = ["SP2001", "SP2002", "SP3001", "SP3002", "SP6001", "SP6002"]
AUTH_EXTRA = {"PAY-MER": ["SP4001"]}
POS_BY_CATEGORY = {"evaluation": "11", "imaging": "22", "surgery": "24", "therapy": "11", "lab": "81",
                   "diagnostic": "22", "diagnostic_minor": "11"}
FIRST = ["Amira", "Jonas", "Leila", "Mateo", "Priya", "Tomas", "Ingrid", "Kofi", "Hana", "Lucas", "Noor", "Elena",
         "Ravi", "Sofia", "Omar", "Mei", "Daniel", "Zara", "Felix", "Anika"]
LAST = ["Halloran", "Okafor", "Lindqvist", "Marchetti", "Devlin", "Sorensen", "Abara", "Castellan", "Whitlock",
        "Nakamura", "Rosales", "Varga", "Ellery", "Bancroft", "Tennant", "Quillon"]
PLANS = ["Essential", "Plus", "Premier"]
DOC_TITLES = {"clinical_note": "Clinical note", "imaging_order": "Imaging order", "operative_report": "Operative report",
              "therapy_plan": "Therapy plan of care", "procedure_report": "Procedure report"}


def auth_required(payer_id, proc):
    return proc in AUTH_ALL_PAYERS or proc in AUTH_EXTRA.get(payer_id, [])


def _doc_text(doc_type, patient_id, provider_name, dos, proc, dx, narrative=None):
    pdesc = PROCEDURES[proc][0] if proc in PROCEDURES else proc
    ddesc = "; ".join(f"{DIAGNOSES.get(d, 'unlisted')} ({d})" for d in dx)
    body = narrative or f"Service documented: {pdesc} ({proc}). Patient tolerated the service; no complications recorded."
    return (f"[SYNTHETIC DOCUMENT - NOT A REAL MEDICAL RECORD]\n{DOC_TITLES[doc_type]} | Patient ref {patient_id} | "
            f"{provider_name} | Date of service {dos}\nAssessment: {ddesc}.\n{body}")


class _Gen:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.patients, self.policies, self.documents, self.auths, self.claims = [], [], [], [], []
        self.n_doc = self.n_auth = 0
        self.ccns = set()

    def patient(self):
        n = len(self.patients) + 1
        r = self.rng
        pid = f"PT-{n:04d}"
        p = {"id": pid, "first_name": r.choice(FIRST), "last_name": r.choice(LAST),
             "dob": date(r.randint(1948, 2004), r.randint(1, 12), r.randint(1, 28)).isoformat(),
             "gender": r.choice(["F", "M"]), "member_id": f"MBR-{r.randint(100000, 999999)}"}
        payer = r.choice(PAYERS)["id"]
        pol = {"id": f"POL-{n:04d}", "policy_number": f"{payer[-3:]}-{r.randint(1000000, 9999999)}", "patient_id": pid,
               "payer_id": payer, "plan_name": r.choice(PLANS), "effective_date": "2026-01-01",
               "termination_date": "2026-12-31", "status": "active", "excluded_procedures": []}
        self.patients.append(p)
        self.policies.append(pol)
        return p, pol

    def doc(self, patient_id, provider, doc_type, dos, proc, dx, narrative=None):
        self.n_doc += 1
        d = {"id": f"DOC-{self.n_doc:05d}", "patient_id": patient_id, "provider_id": provider["id"], "doc_type": doc_type,
             "service_date": dos, "content": _doc_text(doc_type, patient_id, provider["name"], dos, proc, dx, narrative),
             "extracted": {"procedure_code": proc, "diagnosis_codes": list(dx)}}
        self.documents.append(d)
        return d

    def auth(self, patient_id, payer_id, proc, dos):
        self.n_auth += 1
        d0 = date.fromisoformat(dos)
        a = {"auth_number": f"AUTH-{self.n_auth:05d}", "patient_id": patient_id, "payer_id": payer_id, "procedure_code": proc,
             "valid_from": (d0 - timedelta(days=20)).isoformat(), "valid_to": (d0 + timedelta(days=40)).isoformat(),
             "status": "approved"}
        self.auths.append(a)
        return a

    def ccn(self):
        while True:
            c = f"CCN-{self.rng.randint(100000, 999999)}"
            if c not in self.ccns:
                self.ccns.add(c)
                return c

    def claim(self, proc=None, dx=None, patient=None, policy=None, provider=None, dos=None, second_line=None, units=None):
        r = self.rng
        if patient is None:
            patient, policy = self.patient()
        provider = provider or r.choice(PROVIDERS)
        proc = proc or r.choice(["SP1001"] * 5 + ["SP1002", "SP2003", "SP4001", "SP4001", "SP5001", "SP5002",
                                               "SP7001", "SP7002", "SP2001", "SP2002", "SP3001", "SP6001", "SP6002", "SP3002"])
        pdesc, cat, price, max_units, compat = PROCEDURES[proc]
        dx = dx or r.choice(compat)
        units = units or (r.randint(1, 4) if proc == "SP4001" else 1)
        dos = dos or (date(2026, 9, 1) + timedelta(days=r.randint(0, 60))).isoformat()
        lines = [{"line_no": 1, "procedure_code": proc, "diagnosis_codes": [dx], "units": units, "unit_price": price,
                  "amount": round(units * price, 2)}]
        if second_line is None:
            second_line = proc == "SP1001" and r.random() < 0.3
        if second_line:
            p2 = r.choice(["SP5001", "SP5002", "SP2003", "SP7001", "SP7002"])
            d2 = r.choice(PROCEDURES[p2][4])
            lines.append({"line_no": 2, "procedure_code": p2, "diagnosis_codes": [d2], "units": 1,
                          "unit_price": PROCEDURES[p2][2], "amount": PROCEDURES[p2][2]})
        docs, seen = [], set()
        for ln in lines:
            for t in REQUIRED_DOCS[PROCEDURES[ln["procedure_code"]][1]]:
                if t not in seen:
                    seen.add(t)
                    docs.append(self.doc(patient["id"], provider, t, dos, ln["procedure_code"], ln["diagnosis_codes"]))
        auth_no = None
        for ln in lines:
            if auth_required(policy["payer_id"], ln["procedure_code"]):
                auth_no = self.auth(patient["id"], policy["payer_id"], ln["procedure_code"], dos)["auth_number"]
        c = {"control_number": self.ccn(), "patient_id": patient["id"], "provider_id": provider["id"],
             "payer_id": policy["payer_id"], "policy_number": policy["policy_number"], "member_id": patient["member_id"],
             "patient_dob": patient["dob"], "service_date": dos,
             "submitted_date": (date.fromisoformat(dos) + timedelta(days=r.randint(2, 9))).isoformat(),
             "place_of_service": POS_BY_CATEGORY[cat], "claim_type": "professional",
             "total_amount": round(sum(l["amount"] for l in lines), 2), "authorization_number": auth_no,
             "attached_document_ids": [d["id"] for d in docs], "lines": lines,
             "ground_truth": {"clean": True, "issues": []}, "_policy": policy, "_patient": patient, "_provider": provider}
        return c

    def label(self, c, category, rule, resolvable, detectable="deterministic"):
        c["ground_truth"]["clean"] = False
        c["ground_truth"]["issues"].append({"category": category, "rule": rule, "detectable": detectable,
                                            "resolvable_in_system": resolvable})

    def docs_of(self, c):
        ids = set(c["attached_document_ids"])
        return [d for d in self.documents if d["id"] in ids]


def generate_dataset(seed: int = 42) -> dict:
    g = _Gen(seed)
    r = g.rng
    AUTH_PROCS = ["SP2001", "SP2002", "SP3001", "SP6001", "SP6002", "SP3002"]
    out = []

    # ---- clean claims (34 ordinary + 2 "bait" claims that look like duplicates but are not)
    clean = [g.claim() for _ in range(34)]
    out += clean
    for orig in r.sample([c for c in clean if c["lines"][0]["procedure_code"] == "SP1001" and len(c["lines"]) == 1], 2):
        out.append(g.claim(proc="SP7002", dx="I10", patient=orig["_patient"], policy=orig["_policy"],
                           provider=orig["_provider"], dos=orig["service_date"], second_line=False))

    # ---- missing documentation (10): 6 where the document exists in the repository, 4 where it does not
    for i in range(10):
        c = g.claim(proc=r.choice(["SP2001", "SP2003", "SP3001", "SP4001", "SP1001", "SP6002"]), second_line=False)
        victim = c["attached_document_ids"][-1]
        c["attached_document_ids"].remove(victim)
        if i < 6:
            g.label(c, "missing_documentation", "DOC-001", True)
            if i < 3:  # multi-issue claims: also a claim total that does not match its lines
                c["total_amount"] = round(c["total_amount"] + r.choice([25.0, 40.0, 100.0]), 2)
                g.label(c, "billing_inconsistency", "BILL-001", True)
        else:
            g.documents[:] = [d for d in g.documents if d["id"] != victim]
            g.label(c, "missing_documentation", "DOC-001", False)
        out.append(c)

    # ---- eligibility (10)
    for i in range(10):
        c = g.claim()
        if i < 4:  # transposed policy number
            pn = c["policy_number"]
            c["policy_number"] = pn[:-2] + pn[-1] + pn[-2] if pn[-1] != pn[-2] else pn[:-1] + "0"
            if c["policy_number"] == pn:
                c["policy_number"] = pn[:-1] + "1"
            g.label(c, "eligibility_mismatch", "ELIG-002", True)
        elif i < 7:  # coverage ended before the date of service
            c["_policy"]["termination_date"] = (date.fromisoformat(c["service_date"]) - timedelta(days=r.randint(5, 40))).isoformat()
            c["_policy"]["status"] = "terminated"
            g.label(c, "eligibility_mismatch", "ELIG-003", False)
        elif i < 9:
            c["member_id"] = None
            g.label(c, "eligibility_mismatch", "ELIG-001", True)
        else:
            c["patient_dob"] = None
            g.label(c, "eligibility_mismatch", "ELIG-001", True)
        out.append(c)

    # ---- authorization (10): 4 on file but not referenced, 3 never obtained, 3 expired
    for i in range(10):
        c = g.claim(proc=r.choice(AUTH_PROCS))
        an = c["authorization_number"]
        rec = next(a for a in g.auths if a["auth_number"] == an)
        if i < 4:
            c["authorization_number"] = None
            g.label(c, "authorization_issue", "AUTH-001", True)
        elif i < 7:
            c["authorization_number"] = None
            g.auths.remove(rec)
            g.label(c, "authorization_issue", "AUTH-001", False)
        else:
            d0 = date.fromisoformat(c["service_date"])
            rec["valid_from"] = (d0 - timedelta(days=120)).isoformat()
            rec["valid_to"] = (d0 - timedelta(days=r.randint(3, 30))).isoformat()
            rec["status"] = "expired"
            g.label(c, "authorization_issue", "AUTH-002", False)
        out.append(c)

    # ---- coding (10): 4 invalid diagnosis, 3 invalid procedure, 3 diagnosis/procedure mismatch
    for i in range(10):
        if i < 4:
            c = g.claim(second_line=False)
            c["lines"][0]["diagnosis_codes"] = [c["lines"][0]["diagnosis_codes"][0] + "Z"]
            supported = i < 3
            if not supported:
                for d in g.docs_of(c):
                    d["extracted"]["diagnosis_codes"] = []
            g.label(c, "coding_inconsistency", "COD-001", supported)
        elif i < 7:
            c = g.claim(proc=r.choice(["SP1001", "SP2003", "SP5001", "SP7001"]), second_line=False)
            good = c["lines"][0]["procedure_code"]
            c["lines"][0]["procedure_code"] = good[:4] + "9X"
            supported = i < 6
            if not supported:
                for d in g.docs_of(c):
                    d["extracted"]["procedure_code"] = None
            g.label(c, "coding_inconsistency", "COD-002", supported)
        else:
            proc = r.choice(["SP2003", "SP5001", "SP5002", "SP7001", "SP1002"])
            bad = r.choice([d for d in ALL_DX if d not in PROCEDURES[proc][4]])
            c = g.claim(proc=proc, dx=bad, second_line=False)
            g.label(c, "coding_inconsistency", "COD-003", False)
        out.append(c)

    # ---- coverage exclusions (5): the plan excludes the billed procedure
    for i in range(5):
        c = g.claim(proc=r.choice(["SP6001", "SP3002", "SP4001", "SP6002", "SP2001"]))
        c["_policy"]["excluded_procedures"] = [c["lines"][0]["procedure_code"]]
        g.label(c, "coverage_problem", "COV-001", False)
        out.append(c)

    # ---- billing (2 over the unit limit; total mismatches were added to 3 documentation claims plus 3 here)
    for i in range(5):
        if i < 3:
            c = g.claim()
            c["total_amount"] = round(c["total_amount"] + r.choice([-20.0, 15.0, 60.0]), 2)
            g.label(c, "billing_inconsistency", "BILL-001", True)
        else:
            c = g.claim(proc="SP4001", units=r.choice([7, 9]))
            g.label(c, "billing_inconsistency", "BILL-002", False)
        out.append(c)

    # ---- conflicting information (6): 3 structured (document names a different procedure),
    #      3 narrative-only (free text contradicts the claim; only an LLM reading the note can see it)
    for i, (billed, documented) in enumerate([("SP2001", "SP2002"), ("SP3001", "SP2001"), ("SP6002", "SP1001")]):
        c = g.claim(proc=billed)
        d = g.docs_of(c)[0]
        d["extracted"]["procedure_code"] = documented
        d["content"] = _doc_text(d["doc_type"], c["patient_id"], c["_provider"]["name"], c["service_date"], documented,
                                 c["lines"][0]["diagnosis_codes"])
        g.label(c, "conflicting_information", "DOC-002", False)
        out.append(c)
    narratives = [
        ("SP2001", "M17.11", "Examination and imaging performed on the LEFT knee. Left knee MRI without contrast "
                             "completed; right knee not examined at this visit."),
        ("SP1001", None, "Patient did not attend the scheduled appointment. No examination was performed and no "
                         "service was rendered. Visit to be rescheduled."),
        ("SP6002", "K21.9", "Procedure was cancelled before sedation because of elevated blood pressure. Endoscopy "
                            "was not performed. Patient referred back to primary care."),
    ]
    for proc, dx, text in narratives:
        c = g.claim(proc=proc, dx=dx, second_line=False)
        d = g.docs_of(c)[0]
        d["content"] = _doc_text(d["doc_type"], c["patient_id"], c["_provider"]["name"], c["service_date"], proc,
                                 c["lines"][0]["diagnosis_codes"], narrative=text)
        g.label(c, "conflicting_information", "AI-NARRATIVE", False, detectable="ai_only")
        out.append(c)

    # ---- incomplete mandatory fields (2)
    for _ in range(2):
        c = g.claim()
        c["place_of_service"] = None
        g.label(c, "incomplete_fields", "COMP-001", True)
        out.append(c)

    # Make two of the coverage-lapsed claims carry a valid authorization (cross-agent conflict scenario).
    lapsed = [c for c in out if any(i["rule"] == "ELIG-003" for i in c["ground_truth"]["issues"])]
    for c in lapsed[:2]:
        ln = c["lines"][0]
        ln.update({"procedure_code": "SP2002", "diagnosis_codes": ["R51.9"], "units": 1, "unit_price": 760.0, "amount": 760.0})
        c["lines"] = [ln]
        c["total_amount"] = 760.0
        c["place_of_service"] = "22"
        g.documents[:] = [d for d in g.documents if d["id"] not in c["attached_document_ids"]]
        docs = [g.doc(c["patient_id"], c["_provider"], t, c["service_date"], "SP2002", ["R51.9"])
                for t in REQUIRED_DOCS["imaging"]]
        c["attached_document_ids"] = [d["id"] for d in docs]
        g.auths[:] = [a for a in g.auths if a["auth_number"] != c["authorization_number"]]
        c["authorization_number"] = g.auth(c["patient_id"], c["payer_id"], "SP2002", c["service_date"])["auth_number"]

    # ---- order, then insert duplicates after their originals (6: 2 reuse the control number, 4 are re-keyed)
    r.shuffle(out)
    originals = r.sample([c for c in clean], 6)
    for i, orig in enumerate(originals):
        dup = copy.deepcopy({k: v for k, v in orig.items() if not k.startswith("_")})
        dup.update({"_policy": orig["_policy"], "_patient": orig["_patient"], "_provider": orig["_provider"]})
        dup["submitted_date"] = (date.fromisoformat(orig["submitted_date"]) + timedelta(days=r.randint(1, 6))).isoformat()
        dup["ground_truth"] = {"clean": True, "issues": []}
        if i < 2:
            g.label(dup, "duplicate_submission", "DUP-001", False)
        else:
            dup["control_number"] = g.ccn()
        g.label(dup, "duplicate_submission", "DUP-002", False)
        pos = r.randint(out.index(orig) + 1, len(out))
        out.insert(pos, dup)

    claims = []
    for n, c in enumerate(out, start=1):
        c = {k: v for k, v in c.items() if not k.startswith("_")}
        c["id"] = f"CLM-{n:04d}"
        c["seq"] = n
        claims.append(c)

    coding = [{"code": k, "code_type": "diagnosis", "description": v, "category": None, "unit_price": None,
               "max_units": None, "compatible_diagnoses": None} for k, v in DIAGNOSES.items()]
    coding += [{"code": k, "code_type": "procedure", "description": v[0] + " (synthetic code)", "category": v[1],
                "unit_price": v[2], "max_units": v[3], "compatible_diagnoses": v[4]} for k, v in PROCEDURES.items()]
    rules = []
    for p in PAYERS:
        for cat, docs in REQUIRED_DOCS.items():
            rules.append({"payer_id": p["id"], "rule_type": "required_documents", "key": cat, "value": docs,
                          "description": f"{cat} claims must attach: {', '.join(docs)}"})
        for proc in AUTH_ALL_PAYERS + AUTH_EXTRA.get(p["id"], []):
            rules.append({"payer_id": p["id"], "rule_type": "authorization_required", "key": proc, "value": True,
                          "description": f"Prior authorization required for {proc}"})
    return {"seed": seed, "payers": PAYERS, "providers": PROVIDERS, "patients": g.patients, "policies": g.policies,
            "documents": g.documents, "authorizations": g.auths, "payer_rules": rules, "coding_references": coding,
            "claims": claims}


def load_dataset(db, ds: dict):
    """Insert a generated dataset. Version 1 of every claim is stored as an immutable snapshot."""
    from app.models import models as m
    from app.services.claims import SNAPSHOT_FIELDS
    from app.validation.engine import RULES

    for p in ds["payers"]:
        db.add(m.Payer(**p))
    for p in ds["providers"]:
        db.add(m.Provider(**p))
    for p in ds["patients"]:
        db.add(m.Patient(**p))
    for p in ds["policies"]:
        db.add(m.InsurancePolicy(**p))
    for d in ds["documents"]:
        db.add(m.ClinicalDocument(**d))
    for a in ds["authorizations"]:
        db.add(m.AuthorizationRecord(**a))
    for r in ds["payer_rules"]:
        db.add(m.PayerRule(**r))
    for c in ds["coding_references"]:
        db.add(m.CodingReference(**c))
    for r in RULES:
        db.add(m.ValidationRule(**r))
    db.flush()
    for c in ds["claims"]:
        claim = m.Claim(id=c["id"], seq=c["seq"], ground_truth=c["ground_truth"], status="NEW", version=1,
                        escalations=[], **{f: c[f] for f in SNAPSHOT_FIELDS})
        for ln in c["lines"]:
            claim.lines.append(m.ClaimLineItem(**ln))
        db.add(claim)
        snap = {f: c[f] for f in SNAPSHOT_FIELDS}
        snap.update({"claim_id": c["id"], "seq": c["seq"], "lines": copy.deepcopy(c["lines"])})
        db.add(m.ClaimVersion(claim_id=c["id"], version=1, snapshot=snap, reason="original submission", actor="system"))
    db.commit()
