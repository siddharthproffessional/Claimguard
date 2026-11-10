"""The 20 required scenarios (numbered as in the build brief), plus API checks."""
import json

import httpx
import pytest

from app.agents.orchestrator import process_claim
from app.ai import providers
from app.config import settings
from app.models import models as m
from app.services import corrections
from app.services.claims import original_snapshot, snapshot
from app.validation.engine import RuleResult, determine_outcome, readiness_score, validate_claim
from app.validation.refdata import RefData
from tests.conftest import claim_where, has_rule, only_rule


def fails(db, claim):
    ref = RefData.from_session(db)
    return {r.rule_id: r for r in validate_claim(snapshot(claim), ref) if r.status == "fail"}


def proposals(db, cid, status="pending"):
    return db.query(m.CorrectionProposal).filter_by(claim_id=cid, status=status).all()


# ---------- fake LLM HTTP layer -------------------------------------------------------------
def fake_post(claude=None, openai=None):
    """claude/openai: callables(system, user) -> dict, or an Exception to raise."""
    calls = []

    async def _post(url, headers, payload):
        if "anthropic" in url:
            calls.append(("claude", payload))
            if isinstance(claude, Exception):
                raise claude
            body = claude(payload["system"], payload["messages"][0]["content"])
            return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(body)}]})
        calls.append(("openai", payload))
        if isinstance(openai, Exception):
            raise openai
        body = openai(payload["messages"][0]["content"], payload["messages"][1]["content"])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

    _post.calls = calls
    return _post


def quiet_claude(system, user):
    if "Orchestrator" in system:
        return {"assessment_summary": "Consistent with findings.", "key_risks": [], "conflict_adjudication": [],
                "recommended_status": json.loads(user)["engine_status"], "unsupported_items": []}
    return {"summary": "No additional concerns.", "additional_concerns": [], "uncertainty": [], "request_review_from": []}


def concur(system, user):
    st = json.loads(user)["assessment_under_review"]["status_after_gate"]
    return {"verdict": "concur", "recommended_status": st, "challenges": [], "missing_evidence": [], "rationale": "Supported."}


# 1
def test_01_valid_claim_is_ready(db, run):
    c = claim_where(db, lambda gt: gt.get("clean"))
    a = run(process_claim(db, c.id))
    assert a["status"] == "READY" and a["blocking_issues"] == [] and a["readiness_score"] == 100.0
    assert proposals(db, c.id) == []
    assert "not a guarantee" in a["disclaimer"]


# 2
def test_02_missing_patient_information(db, run):
    c = claim_where(db, only_rule("ELIG-001"))
    f = fails(db, c)
    assert set(f) == {"ELIG-001"}
    run(process_claim(db, c.id))
    assert c.status == "REQUIRES_CORRECTION"
    (p,) = proposals(db, c.id)
    assert p.field in ("member_id", "patient_dob") and p.proposed_value == {"member_id": c.patient.member_id,
                                                                            "patient_dob": c.patient.dob}[p.field]
    assert p.evidence, "proposal must cite the registry record"


# 3
def test_03_invalid_policy_dates(db, run):
    c = claim_where(db, lambda gt: gt.get("clean"))
    pol = db.query(m.InsurancePolicy).filter_by(patient_id=c.patient_id).first()
    pol.effective_date, pol.termination_date = "2026-12-31", "2026-01-01"
    db.commit()
    f = fails(db, c)
    assert f["ELIG-003"].resolution == "human_review" and "invalid" in f["ELIG-003"].explanation
    # lapsed coverage from the dataset
    lapsed = claim_where(db, has_rule("ELIG-003"))
    run(process_claim(db, lapsed.id))
    assert lapsed.status == "HUMAN_REVIEW"


# 4
def test_04_missing_documentation(db, run):
    fixable = claim_where(db, lambda gt: only_rule("DOC-001")(gt) and gt["issues"][0]["resolvable_in_system"])
    missing = claim_where(db, lambda gt: only_rule("DOC-001")(gt) and not gt["issues"][0]["resolvable_in_system"])
    assert fails(db, fixable)["DOC-001"].resolution == "correctable"
    assert fails(db, missing)["DOC-001"].resolution == "external_action"
    run(process_claim(db, fixable.id))
    run(process_claim(db, missing.id))
    assert [p.op for p in proposals(db, fixable.id)] == ["attach_document"]
    assert proposals(db, missing.id) == [], "no proposal may be invented when the document does not exist"
    assert missing.status == "REQUIRES_CORRECTION"


# 5
def test_05_invalid_synthetic_code(db, run):
    dx = claim_where(db, has_rule("COD-001"))
    px = claim_where(db, has_rule("COD-002"))
    assert "COD-001" in fails(db, dx) and "COD-002" in fails(db, px)
    run(process_claim(db, dx.id))
    for p in proposals(db, dx.id):
        assert p.requires_role == "certified_coder" and "NOT a coding determination" in p.confidence_note


# 6
def test_06_coding_mismatch(db, run):
    c = claim_where(db, has_rule("COD-003"))
    assert fails(db, c)["COD-003"].resolution == "human_review"
    run(process_claim(db, c.id))
    assert c.status == "HUMAN_REVIEW" and proposals(db, c.id) == []


# 7
def test_07_missing_authorization(db, run):
    on_file = claim_where(db, lambda gt: only_rule("AUTH-001")(gt) and gt["issues"][0]["resolvable_in_system"])
    never = claim_where(db, lambda gt: only_rule("AUTH-001")(gt) and not gt["issues"][0]["resolvable_in_system"])
    run(process_claim(db, on_file.id))
    run(process_claim(db, never.id))
    (p,) = proposals(db, on_file.id)
    assert p.field == "authorization_number" and p.proposed_value.startswith("AUTH-")
    assert proposals(db, never.id) == [] and never.status == "REQUIRES_CORRECTION"


# 8
def test_08_expired_authorization(db, run):
    c = claim_where(db, has_rule("AUTH-002"))
    f = fails(db, c)["AUTH-002"]
    assert "not valid on the date of service" in f.explanation and f.resolution == "external_action"


# 9
def test_09_duplicate_claim(db, run):
    dup = claim_where(db, has_rule("DUP-002"))
    f = fails(db, dup)
    orig_id = f["DUP-002"].details["matches"][0]
    orig = db.get(m.Claim, orig_id)
    assert orig.seq < dup.seq and "DUP-002" not in fails(db, orig)
    a = run(process_claim(db, dup.id))
    assert dup.status == "HUMAN_REVIEW"
    assert all("fraud" not in i["explanation"].lower() for i in a["blocking_issues"])
    msgs = db.query(m.AgentMessage).filter_by(claim_id=dup.id, sender="fraud_duplicate", recipient="compliance").count()
    assert msgs >= 1


# 10
def test_10_conflicting_agent_findings(db, run):
    lapsed = [x for x in db.query(m.Claim) if any(i["rule"] == "ELIG-003" for i in (x.ground_truth or {}).get("issues", []))
              and x.authorization_number]
    c = lapsed[0]
    a = run(process_claim(db, c.id))
    conf = {x["id"]: x for x in a["conflicts"]}
    assert "authorization-vs-eligibility" in conf
    assert conf["authorization-vs-eligibility"]["status"] == "resolved" and a["iterations"] >= 2
    rerun = db.query(m.AgentRun).filter_by(claim_id=c.id, agent="authorization", iteration=2).one()
    assert rerun.output["data"]["auth_status"] == "on_file_but_not_sufficient"
    assert a["status"] != "READY"
    assert db.query(m.AuditEvent).filter_by(claim_id=c.id, event_type="conflict_detected").count() >= 1


# 11
def test_11_openai_review_failure(db, run, ai_on, monkeypatch):
    post = fake_post(quiet_claude, httpx.ConnectTimeout("reviewer timed out"))
    monkeypatch.setattr(providers, "_post", post)
    c = claim_where(db, only_rule("ELIG-002"))
    a = run(process_claim(db, c.id, depth="synthesis"))
    assert a["status"] == "REQUIRES_CORRECTION" == a["engine_status"]
    assert a["ai"]["openai"].startswith("unavailable") and a["ai"]["claude"].startswith("ok")
    assert db.query(m.AuditEvent).filter_by(claim_id=c.id, event_type="ai_provider_failure").count() == 1
    run_ = db.query(m.AgentRun).filter_by(claim_id=c.id, agent="independent_reviewer").one()
    assert run_.status == "failed" and not run_.ai_used, "a failed review must never be shown as completed"


# 12
def test_12_claude_api_failure(db, run, ai_on, monkeypatch):
    monkeypatch.setattr(providers, "_post", fake_post(httpx.ConnectError("api down"), concur))
    c = claim_where(db, only_rule("ELIG-002"))
    a = run(process_claim(db, c.id, depth="full"))
    assert a["engine_status"] == "REQUIRES_CORRECTION" and a["ai"]["claude"].startswith("unavailable")
    runs = db.query(m.AgentRun).filter_by(claim_id=c.id).all()
    assert all(r.status != "failed" for r in runs if r.agent != "independent_reviewer")
    assert not any(r.ai_used for r in runs if r.agent not in ("independent_reviewer",))
    assert len(proposals(db, c.id)) == 1, "deterministic workflow still produces the correction"


# 13
def test_13_invalid_correction_proposal(db, run):
    c = claim_where(db, only_rule("ELIG-002"))
    run(process_claim(db, c.id))
    (p,) = proposals(db, c.id)
    v0 = c.version
    with pytest.raises(corrections.WorkflowError) as e:  # wrong value would not clear the rule... and keeps failing
        corrections.approve(db, c.id, p.id, edited_value=12345)
    assert e.value.status_code == 422
    bad = m.CorrectionProposal(claim_id=c.id, claim_version=c.version, rule_id="X", op="set_field", field="patient_id",
                               proposed_value="PT-0002", status="pending", requires_role="billing_operator", evidence=[])
    db.add(bad)
    db.commit()
    with pytest.raises(corrections.WorkflowError):
        corrections.approve(db, c.id, bad.id)
    assert c.version == v0 and c.patient_id != "PT-0002"
    assert db.query(m.AuditEvent).filter_by(claim_id=c.id, event_type="correction_invalid").count() == 2
    # role enforcement
    dx = claim_where(db, lambda gt: only_rule("COD-001")(gt) and gt["issues"][0]["resolvable_in_system"])
    run(process_claim(db, dx.id))
    (cp,) = proposals(db, dx.id)
    with pytest.raises(corrections.WorkflowError) as e:
        corrections.approve(db, dx.id, cp.id, role="billing_operator")
    assert e.value.status_code == 403


# 14
def test_14_correction_approval(db, run):
    c = claim_where(db, only_rule("ELIG-002"))
    original_policy = c.policy_number
    run(process_claim(db, c.id))
    (p,) = proposals(db, c.id)
    out = corrections.approve(db, c.id, p.id, actor="dana", role="billing_operator")
    assert out["before"]["status"] == "REQUIRES_CORRECTION" and out["after"]["status"] == "READY"
    assert c.version == 2 and c.policy_number == p.proposed_value
    assert original_snapshot(db, c.id)["policy_number"] == original_policy, "version 1 is immutable"
    appr = db.query(m.CorrectionApproval).filter_by(proposal_id=p.id).one()
    assert appr.action == "approved" and appr.actor == "dana"
    with pytest.raises(corrections.WorkflowError) as e:
        corrections.approve(db, c.id, p.id)
    assert e.value.status_code == 409


# 15
def test_15_correction_rejection(db, run):
    c = claim_where(db, only_rule("ELIG-002"))
    run(process_claim(db, c.id))
    (p,) = proposals(db, c.id)
    before = (c.version, c.policy_number, c.status)
    corrections.reject(db, c.id, p.id, actor="dana", note="checking with patient")
    assert (c.version, c.policy_number, c.status) == before
    assert db.get(m.CorrectionProposal, p.id).status == "rejected"
    assert db.query(m.AuditEvent).filter_by(claim_id=c.id, event_type="correction_rejected").count() == 1


# 16
def test_16_human_review_escalation(db, run, ai_on, monkeypatch):
    narrative = claim_where(db, has_rule("AI-NARRATIVE"))

    def doc_reader(system, user):
        if "Documentation Agent" in system and json.loads(user)["claim"]["claim_id"] == narrative.id:
            return {"summary": "Note contradicts billed service.", "additional_concerns": [
                {"title": "Service may not have been rendered as billed", "explanation": "The note text contradicts the claim.",
                 "evidence_refs": narrative.attached_document_ids[:1], "confidence": "medium"}],
                "uncertainty": [], "request_review_from": []}
        return quiet_claude(system, user)

    monkeypatch.setattr(providers, "_post", fake_post(doc_reader, concur))
    assert fails(db, narrative) == {}, "rules alone see nothing wrong"
    a = run(process_claim(db, narrative.id, depth="synthesis"))
    assert a["engine_status"] == "READY" and a["status"] == "HUMAN_REVIEW"
    assert any(e["source"] == "ai_concern" and e["agent"] == "documentation" for e in a["escalations"])

    # ...and the model can never promote a failing claim to READY
    def says_ready(system, user):
        r = quiet_claude(system, user)
        if "Orchestrator" in system:
            r["recommended_status"] = "READY"
        return r

    monkeypatch.setattr(providers, "_post", fake_post(says_ready, concur))
    bad = claim_where(db, only_rule("ELIG-002"))
    a = run(process_claim(db, bad.id, depth="synthesis"))
    assert a["status"] == "REQUIRES_CORRECTION"
    assert any(d["between"][0] == "claude_orchestrator" for d in a["disagreements"])


# 17
def test_17_reassessment_after_correction(db, run):
    c = claim_where(db, lambda gt: only_rule("DOC-001")(gt) and gt["issues"][0]["resolvable_in_system"])
    run(process_claim(db, c.id))
    (p,) = proposals(db, c.id)
    corrections.approve(db, c.id, p.id)
    a = run(process_claim(db, c.id, reason="reassessment"))
    assert a["status"] == "READY" and a["claim_version"] == 2 and proposals(db, c.id) == []


# 18
def test_18_reproducible_benchmark(db, run):
    from app.database import db as database
    from app.simulation import benchmark

    def strip(r):
        r = json.loads(json.dumps(r))
        r.pop("simulation_id")
        for k in ("processing_ms", "avg_ms_per_claim"):
            r["baseline"].pop(k, None)
            r["claimguard"].pop(k, None)
        return r

    out = []
    for _ in range(2):
        sim = benchmark.new_simulation(db, 7, "none", "simulated_approve")
        out.append(strip(run(benchmark.run_simulation(sim.id, 7, "none", "simulated_approve"))))
    assert out[0] == out[1]
    s = database.SessionLocal()
    assert s.query(m.SimulationRun).filter_by(status="completed").count() >= 2
    s.close()
    cg, base = out[0]["claimguard"], out[0]["baseline"]
    assert cg["false_positive_claims"] == 0 and cg["issues_detected"] > base["issues_detected"]


# 19
def test_19_audit_log_creation(db, run):
    c = claim_where(db, only_rule("ELIG-002"))
    run(process_claim(db, c.id))
    (p,) = proposals(db, c.id)
    corrections.approve(db, c.id, p.id, actor="dana")
    kinds = {e.event_type for e in db.query(m.AuditEvent).filter_by(claim_id=c.id)}
    assert {"analysis_started", "correction_proposed", "assessment_completed", "correction_approved", "validation_run"} <= kinds
    ev = db.query(m.AuditEvent).filter_by(claim_id=c.id, event_type="correction_approved").one()
    assert ev.actor_type == "human" and ev.details["before"] != ev.details["after"] and ev.details["evidence"]
    assert db.query(m.ToolInvocation).filter_by(claim_id=c.id).count() > 10


# 20
def test_20_readiness_calculation(db):
    def rr(rule, status, sev, dim):
        return RuleResult(rule, "C", status, sev, dim, "")

    w = {"eligibility": 50, "billing": 50}
    assert readiness_score([rr("A", "pass", "high", "eligibility"), rr("B", "pass", "high", "billing")], w)[0] == 100.0
    assert readiness_score([rr("A", "fail", "high", "eligibility"), rr("A2", "pass", "high", "eligibility"),
                            rr("B", "pass", "high", "billing")], w)[0] == 75.0
    crit = [rr("A", "fail", "critical", "eligibility"), rr("A2", "pass", "high", "eligibility"),
            rr("A3", "pass", "high", "eligibility"), rr("A4", "pass", "high", "eligibility"), rr("B", "pass", "high", "billing")]
    assert readiness_score(crit, w)[0] == 50.0
    crit[0].resolution = "correctable"
    assert determine_outcome(crit) == "REQUIRES_CORRECTION", "a blocking failure is never READY whatever the score"
    assert determine_outcome([rr("B", "pass", "high", "billing")], [{"source": "ai_concern"}]) == "HUMAN_REVIEW"
    assert sum(settings.scoring_weights.values()) == 100


# ---------- API --------------------------------------------------------------------------------
def test_api_end_to_end(db):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as cl:
        assert cl.get("/api/health").json()["status"] == "ok"
        items = cl.get("/api/claims").json()
        assert items["total"] == 100
        c = claim_where(db, only_rule("ELIG-002"))
        a = cl.post(f"/api/claims/{c.id}/analyze").json()
        assert a["status"] == "REQUIRES_CORRECTION"
        v = cl.get(f"/api/claims/{c.id}/validation").json()
        assert {r["rule_id"] for r in v["results"] if r["status"] == "fail"} == {"ELIG-002"}
        (p,) = cl.get(f"/api/claims/{c.id}/corrections").json()
        assert cl.post(f"/api/claims/{c.id}/corrections/{p['id']}/approve", headers={"X-Role": "viewer"}).status_code == 403
        r = cl.post(f"/api/claims/{c.id}/corrections/{p['id']}/approve", json={"note": "verified"}, headers={"X-Actor": "dana"})
        assert r.status_code == 200 and r.json()["after"]["status"] == "READY"
        assert cl.get("/api/claims/CLM-9999").status_code == 404
        assert cl.post(f"/api/claims/{c.id}/corrections/999999/reject").status_code == 404
        assert cl.post("/api/claims", json={"control_number": "x"}).status_code == 422
        for path in ("/api/agents", "/api/agents/activity", "/api/analytics", "/api/audit", "/api/rules", "/api/simulation"):
            assert cl.get(path).status_code == 200, path
        with cl.websocket_connect("/ws/claimguard") as ws:
            assert ws.receive_json()["type"] == "hello"


def test_api_create_claim(db):
    from fastapi.testclient import TestClient

    from app.main import app
    src = claim_where(db, lambda gt: gt.get("clean"))
    body = {**{k: v for k, v in snapshot(src).items() if k not in ("claim_id", "seq", "lines")},
            "control_number": "CCN-NEW-1",
            "lines": [{k: v for k, v in l.items() if k != "line_no"} for l in snapshot(src)["lines"]]}
    with TestClient(app) as cl:
        r = cl.post("/api/claims", json=body)
        assert r.status_code == 201
        a = cl.post(f"/api/claims/{r.json()['id']}/analyze").json()
        assert a["status"] == "HUMAN_REVIEW" and any(i["rule_id"] == "DUP-002" for i in a["blocking_issues"])


def test_agent_crash_escalates_instead_of_crashing(db, run, monkeypatch):
    from app.agents.specialists import BY_KEY

    def boom(*a, **k):
        raise RuntimeError("coding reference unavailable")

    monkeypatch.setattr(BY_KEY["coding"], "investigate", boom)
    c = claim_where(db, lambda gt: gt.get("clean"))
    a = run(process_claim(db, c.id))
    assert a["status"] == "HUMAN_REVIEW", "a clean claim whose coding check never ran must not be READY"
    assert any(e["source"] == "agent_failure" and e["agent"] == "coding" for e in a["escalations"])
    assert db.query(m.AgentRun).filter_by(claim_id=c.id, agent="coding", status="failed").count() == 1
