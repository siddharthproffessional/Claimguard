"""REST API."""
import asyncio
from collections import Counter

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func

from app.agents.base import BaseAgent
from app.agents.orchestrator import process_claim
from app.agents.recovery import RecoveryAgent
from app.agents.specialists import SPECIALISTS
from app.ai import providers
from app.config import settings
from app.database.db import get_db
from app.models import models as m
from app.schemas.api import AnalyzeRequest, ApproveBody, ClaimCreate, LoadRequest, RejectBody, SimulationRequest
from app.services import corrections
from app.services.claims import SNAPSHOT_FIELDS, original_snapshot, snapshot
from app.services.events import Recorder, bus
from app.simulation import benchmark
from app.validation.engine import RULE_META, RULES

router = APIRouter(prefix="/api")
_running: set = set()
INSTANCE = __import__("uuid").uuid4().hex[:8]


def actor_headers(x_actor: str | None = Header(default=None), x_role: str | None = Header(default=None)):
    return {"actor": (x_actor or "operator")[:60], "role": (x_role or "billing_operator")[:40]}


def _claim_row(c: m.Claim):
    return {"id": c.id, "seq": c.seq, "control_number": c.control_number, "patient_id": c.patient_id,
            "provider_id": c.provider_id, "provider": c.provider.name if c.provider else None, "payer_id": c.payer_id,
            "payer": c.payer.name if c.payer else None, "service_date": c.service_date, "total_amount": c.total_amount,
            "status": c.status, "readiness_score": c.readiness_score, "issue_count": c.issue_count,
            "assigned_agent": c.assigned_agent, "initial_status": c.initial_status, "initial_score": c.initial_score,
            "version": c.version, "procedures": [l.procedure_code for l in c.lines],
            "updated_at": c.updated_at.isoformat() if c.updated_at else None}


def _get_claim(db, claim_id):
    c = db.get(m.Claim, claim_id)
    if c is None:
        raise HTTPException(404, f"Claim {claim_id} not found")
    return c


def _validation(db, c):
    rows = db.query(m.ValidationResult).filter_by(claim_id=c.id, run_id=c.latest_validation_run).all() if c.latest_validation_run else []
    order = [r["rule_id"] for r in RULES]
    rows.sort(key=lambda r: order.index(r.rule_id))
    return [{"rule_id": r.rule_id, "name": RULE_META[r.rule_id]["name"], "claim_id": r.claim_id, "claim_version": r.claim_version,
             "status": r.status, "severity": r.severity, "dimension": r.dimension, "resolution": r.resolution,
             "explanation": r.explanation, "evidence": r.evidence, "next_action": r.next_action,
             "agent": RULE_META[r.rule_id]["agent"]} for r in rows]


@router.get("/health")
def health():
    return {"status": "ok", "instance": INSTANCE, "serverless": settings.serverless, "claude_configured": settings.claude_enabled, "openai_configured": settings.openai_enabled,
            "ai_depth": settings.effective_depth(), "claude_model": settings.claude_model_orchestrator,
            "openai_model": settings.openai_model or None}


@router.get("/events")
def events(after: int = 0):
    """Polling fallback for hosts without WebSockets (e.g. Vercel functions)."""
    evs = [e for e in bus.recent if e["seq"] > after]
    return {"instance": INSTANCE, "agent_status": list(bus.agent_status.values()), "events": evs[-3000:],
            "last": bus.recent[-1]["seq"] if bus.recent else after}


@router.post("/demo/load")
def load(body: LoadRequest, db=Depends(get_db)):
    if _running:
        raise HTTPException(409, "A simulation is running")
    ds = benchmark.load_demo(db, body.seed)
    return {"seed": body.seed, "claims": len(ds["claims"])}


@router.post("/claims", status_code=201)
def create_claim(body: ClaimCreate, db=Depends(get_db)):
    for ref_id, model in ((body.patient_id, m.Patient), (body.provider_id, m.Provider), (body.payer_id, m.Payer)):
        if db.get(model, ref_id) is None:
            raise HTTPException(422, f"Unknown reference {ref_id}")
    seq = (db.query(func.max(m.Claim.seq)).scalar() or 0) + 1
    cid = f"CLM-{seq:04d}"
    data = body.model_dump()
    lines = data.pop("lines")
    claim = m.Claim(id=cid, seq=seq, status="NEW", version=1, escalations=[], ground_truth=None, **data)
    for i, ln in enumerate(lines, 1):
        claim.lines.append(m.ClaimLineItem(line_no=i, **ln))
    db.add(claim)
    db.flush()
    db.add(m.ClaimVersion(claim_id=cid, version=1, snapshot=snapshot(claim), reason="original submission", actor="api"))
    Recorder(db, cid).audit("claim_created", "api", "system", f"Claim {cid} received", {"control_number": body.control_number})
    db.commit()
    return _claim_row(claim)


@router.get("/claims")
def list_claims(db=Depends(get_db), status: str | None = None, q: str | None = None, payer: str | None = None,
                limit: int = Query(200, le=1000), offset: int = 0):
    qry = db.query(m.Claim)
    if status:
        qry = qry.filter(m.Claim.status == status)
    if payer:
        qry = qry.filter(m.Claim.payer_id == payer)
    if q:
        like = f"%{q}%"
        qry = qry.filter((m.Claim.id.ilike(like)) | (m.Claim.patient_id.ilike(like)) | (m.Claim.control_number.ilike(like)))
    total = qry.count()
    rows = qry.order_by(m.Claim.seq).offset(offset).limit(limit).all()
    return {"total": total, "items": [_claim_row(c) for c in rows]}


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str, db=Depends(get_db)):
    c = _get_claim(db, claim_id)
    docs = db.query(m.ClinicalDocument).filter(m.ClinicalDocument.id.in_(c.attached_document_ids or [])).all()
    versions = db.query(m.ClaimVersion).filter_by(claim_id=claim_id).order_by(m.ClaimVersion.version).all()
    runs = db.query(m.AgentRun).filter_by(claim_id=claim_id).order_by(m.AgentRun.id).all()
    msgs = db.query(m.AgentMessage).filter_by(claim_id=claim_id).order_by(m.AgentMessage.id).all()
    return {**_claim_row(c), "current": snapshot(c), "original": original_snapshot(db, claim_id),
            "patient": {"id": c.patient.id, "dob": c.patient.dob, "member_id": c.patient.member_id} if c.patient else None,
            "documents": [{"id": d.id, "doc_type": d.doc_type, "service_date": d.service_date, "content": d.content,
                           "extracted": d.extracted} for d in docs],
            "assessment": c.assessment, "escalations": c.escalations, "validation": _validation(db, c),
            "versions": [{"version": v.version, "reason": v.reason, "actor": v.actor,
                          "created_at": v.created_at.isoformat() if v.created_at else None} for v in versions],
            "agent_runs": [{"id": r.id, "agent": r.agent, "iteration": r.iteration, "status": r.status, "ai_used": r.ai_used,
                            "ai_note": r.ai_note, "duration_ms": r.duration_ms, "output": r.output, "error": r.error}
                           for r in runs],
            "messages": [{"id": x.id, "sender": x.sender, "recipient": x.recipient, "msg_type": x.msg_type,
                          "content": x.content, "created_at": x.created_at.isoformat()} for x in msgs]}


async def _analyze(db, claim_id, depth, reason, actor):
    _get_claim(db, claim_id)
    if claim_id in _running:
        raise HTTPException(409, f"{claim_id} is already being processed")
    _running.add(claim_id)
    try:
        return await process_claim(db, claim_id, None, depth, reason=reason, actor=actor)
    finally:
        _running.discard(claim_id)


@router.post("/claims/{claim_id}/analyze")
async def analyze(claim_id: str, body: AnalyzeRequest | None = None, who=Depends(actor_headers), db=Depends(get_db)):
    return await _analyze(db, claim_id, body.ai_depth if body else None, "analysis", who["actor"])


@router.post("/claims/{claim_id}/reassess")
async def reassess(claim_id: str, body: AnalyzeRequest | None = None, who=Depends(actor_headers), db=Depends(get_db)):
    Recorder(db, claim_id).audit("reassessment_requested", who["actor"], "human", f"Reassessment of {claim_id} requested")
    db.commit()
    return await _analyze(db, claim_id, body.ai_depth if body else None, "reassessment", who["actor"])


@router.get("/claims/{claim_id}/validation")
def validation(claim_id: str, db=Depends(get_db)):
    c = _get_claim(db, claim_id)
    return {"claim_id": claim_id, "claim_version": c.version, "run_id": c.latest_validation_run, "status": c.status,
            "readiness_score": c.readiness_score, "results": _validation(db, c)}


@router.get("/claims/{claim_id}/corrections")
def list_corrections(claim_id: str, db=Depends(get_db), include_superseded: bool = False):
    _get_claim(db, claim_id)
    q = db.query(m.CorrectionProposal).filter_by(claim_id=claim_id)
    if not include_superseded:
        q = q.filter(m.CorrectionProposal.status != "superseded")
    return [corrections.proposal_dict(p) for p in q.order_by(m.CorrectionProposal.id)]


@router.get("/corrections")
def all_corrections(db=Depends(get_db), status: str = "pending"):
    q = db.query(m.CorrectionProposal).filter_by(status=status).order_by(m.CorrectionProposal.claim_id, m.CorrectionProposal.id)
    return [corrections.proposal_dict(p) for p in q.limit(500)]


@router.post("/claims/{claim_id}/corrections/{correction_id}/approve")
def approve(claim_id: str, correction_id: int, body: ApproveBody | None = None, who=Depends(actor_headers), db=Depends(get_db)):
    body = body or ApproveBody()
    try:
        return corrections.approve(db, claim_id, correction_id, who["actor"], who["role"], body.edited_value, body.note)
    except corrections.WorkflowError as e:
        raise HTTPException(e.status_code, e.message)


@router.post("/claims/{claim_id}/corrections/{correction_id}/reject")
def reject(claim_id: str, correction_id: int, body: RejectBody | None = None, who=Depends(actor_headers), db=Depends(get_db)):
    try:
        return corrections.reject(db, claim_id, correction_id, who["actor"], who["role"], (body or RejectBody()).note)
    except corrections.WorkflowError as e:
        raise HTTPException(e.status_code, e.message)


@router.post("/simulation/run", status_code=202)
async def run_simulation(body: SimulationRequest, db=Depends(get_db)):
    if _running:
        raise HTTPException(409, "A simulation or analysis is already running")
    sim = benchmark.new_simulation(db, body.seed, body.ai_depth, body.operator_mode)
    _running.add(sim.id)

    async def go():
        try:
            await benchmark.run_simulation(sim.id, body.seed, body.ai_depth, body.operator_mode)
        except Exception:
            pass
        finally:
            _running.discard(sim.id)

    if settings.serverless:
        # No background work survives the response on serverless hosts, so run to completion here.
        await go()
        db.expire_all()
        done = db.get(m.SimulationRun, sim.id)
        return {"simulation_id": sim.id, "status": done.status, "config": sim.config, "error": done.error}
    asyncio.create_task(go())
    return {"simulation_id": sim.id, "status": "running", "config": sim.config}


@router.get("/simulation")
def list_simulations(db=Depends(get_db)):
    sims = db.query(m.SimulationRun).order_by(m.SimulationRun.started_at.desc()).limit(20).all()
    return [{"id": s.id, "seed": s.seed, "status": s.status, "config": s.config, "progress": s.progress,
             "started_at": s.started_at.isoformat() if s.started_at else None,
             "completed_at": s.completed_at.isoformat() if s.completed_at else None} for s in sims]


@router.get("/simulation/{simulation_id}")
def get_simulation(simulation_id: str, db=Depends(get_db)):
    s = db.get(m.SimulationRun, simulation_id)
    if s is None:
        raise HTTPException(404, "Simulation not found")
    return {"id": s.id, "seed": s.seed, "status": s.status, "config": s.config, "progress": s.progress, "results": s.results,
            "error": s.error, "started_at": s.started_at.isoformat() if s.started_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None}


AGENT_INFO = [("orchestrator", "ClaimGuard Orchestrator", "Assigns tasks, relays reviews, detects conflicts, runs validation, synthesises the assessment.",
               ["validation_engine.validate_claim"])]
AGENT_INFO += [(a.key, a.name, a.responsibility, a.tools) for a in SPECIALISTS]
AGENT_INFO += [("recovery", RecoveryAgent.name, RecoveryAgent.responsibility, RecoveryAgent.tools),
               ("independent_reviewer", "Independent Reviewer (OpenAI)", "Tests the final assessment for unsupported conclusions and missing evidence.",
                ["openai.chat.completions"])]


@router.get("/agents")
def agents(db=Depends(get_db)):
    stats = {r[0]: r for r in db.query(m.AgentRun.agent, func.count(m.AgentRun.id), func.avg(m.AgentRun.duration_ms),
                                         func.sum(func.iif(m.AgentRun.status == "failed", 1, 0)),
                                         func.sum(func.iif(m.AgentRun.ai_used, 1, 0)),
                                         func.sum(func.iif(m.AgentRun.iteration > 1, 1, 0))).group_by(m.AgentRun.agent)}
    tools = dict(db.query(m.ToolInvocation.agent, func.count(m.ToolInvocation.id)).group_by(m.ToolInvocation.agent).all())
    out = []
    for key, name, resp, tl in AGENT_INFO:
        s = stats.get(key)
        out.append({"key": key, "name": name, "responsibility": resp, "tools": tl, "live": bus.agent_status.get(key),
                    "runs": s[1] if s else 0, "avg_ms": round(s[2], 2) if s and s[2] else 0, "failures": s[3] if s else 0,
                    "ai_runs": s[4] if s else 0, "reassessments": s[5] if s else 0, "tool_calls": tools.get(key, 0)})
    return out


@router.get("/agents/activity")
def activity(db=Depends(get_db), claim_id: str | None = None, limit: int = Query(200, le=2000)):
    mq = db.query(m.AgentMessage)
    tq = db.query(m.ToolInvocation)
    rq = db.query(m.AgentRun)
    if claim_id:
        mq, tq, rq = mq.filter_by(claim_id=claim_id), tq.filter_by(claim_id=claim_id), rq.filter_by(claim_id=claim_id)
    items = [{"kind": "message", "id": x.id, "claim_id": x.claim_id, "agent": x.sender, "to": x.recipient, "type": x.msg_type,
              "text": x.content, "ts": x.created_at.isoformat()} for x in mq.order_by(m.AgentMessage.id.desc()).limit(limit)]
    items += [{"kind": "tool", "id": x.id, "claim_id": x.claim_id, "agent": x.agent, "type": x.tool, "ok": x.ok,
               "text": x.result_summary, "duration_ms": x.duration_ms, "ts": x.created_at.isoformat()}
              for x in tq.order_by(m.ToolInvocation.id.desc()).limit(limit)]
    items += [{"kind": "run", "id": x.id, "claim_id": x.claim_id, "agent": x.agent, "type": x.status, "iteration": x.iteration,
               "ai_used": x.ai_used, "text": (x.output or {}).get("summary") if isinstance(x.output, dict) else None,
               "duration_ms": x.duration_ms, "ts": x.started_at.isoformat()} for x in rq.order_by(m.AgentRun.id.desc()).limit(limit)]
    items.sort(key=lambda i: (i["ts"], i["kind"], i["id"]), reverse=True)
    return items[:limit]


@router.get("/analytics")
def analytics(db=Depends(get_db)):
    claims = db.query(m.Claim).all()
    vr, critical = {}, set()
    for c in claims:
        if c.latest_validation_run:
            for r in db.query(m.ValidationResult).filter_by(claim_id=c.id, run_id=c.latest_validation_run, status="fail"):
                vr[r.rule_id] = vr.get(r.rule_id, 0) + 1
                if r.severity == "critical":
                    critical.add(c.id)
    first_runs = {}
    for r in db.query(m.ValidationResult).filter_by(status="fail").order_by(m.ValidationResult.id):
        first_runs.setdefault(r.claim_id, r.run_id)
    detected = Counter(r.rule_id for r in db.query(m.ValidationResult).filter_by(status="fail")
                       if first_runs.get(r.claim_id) == r.run_id)
    runs = db.query(m.AgentRun.agent, func.count(m.AgentRun.id), func.avg(m.AgentRun.duration_ms)).group_by(m.AgentRun.agent).all()
    durations = [c.assessment["duration_ms"] for c in claims if c.assessment and "duration_ms" in c.assessment]
    sims = db.query(m.SimulationRun).filter_by(status="completed").order_by(m.SimulationRun.completed_at.desc()).first()
    proposals = Counter(p.status for p in db.query(m.CorrectionProposal))
    resolved = sum(1 for a in db.query(m.AuditEvent).filter_by(event_type="correction_approved"))
    return {
        "claims": len(claims),
        "high_priority_claims": len(critical),
        "processed": sum(1 for c in claims if c.status not in ("NEW", "PROCESSING")),
        "status_now": dict(Counter(c.status for c in claims)),
        "status_initial": dict(Counter(c.initial_status for c in claims if c.initial_status)),
        "issues_detected_initial": [{"rule_id": k, "name": RULE_META[k]["name"], "dimension": RULE_META[k]["dimension"], "count": v}
                                    for k, v in detected.most_common()],
        "issues_open_now": [{"rule_id": k, "name": RULE_META[k]["name"], "count": v} for k, v in sorted(vr.items(), key=lambda x: -x[1])],
        "by_dimension": dict(Counter(RULE_META[k]["dimension"] for k, v in detected.items() for _ in range(v))),
        "escalation_sources": dict(Counter(e.get("source") for c in claims for e in (c.escalations or []))),
        "avg_claim_ms": round(sum(durations) / len(durations), 1) if durations else None,
        "agent_workload": [{"agent": a, "runs": n, "avg_ms": round(ms or 0, 2)} for a, n, ms in runs],
        "proposals": dict(proposals), "corrections_applied": resolved,
        "mean_readiness_initial": round(sum(c.initial_score for c in claims if c.initial_score is not None) /
                                        max(1, sum(1 for c in claims if c.initial_score is not None)), 1),
        "mean_readiness_now": round(sum(c.readiness_score for c in claims if c.readiness_score is not None) /
                                    max(1, sum(1 for c in claims if c.readiness_score is not None)), 1),
        "ai_stats": {"calls": providers.stats.calls, "failures": providers.stats.failures, "by_provider": providers.stats.by_provider},
        "latest_simulation": {"id": sims.id, "results": sims.results} if sims else None,
    }


@router.get("/audit")
def audit(db=Depends(get_db), claim_id: str | None = None, event_type: str | None = None, actor_type: str | None = None,
          limit: int = Query(300, le=5000)):
    q = db.query(m.AuditEvent)
    if claim_id:
        q = q.filter_by(claim_id=claim_id)
    if event_type:
        q = q.filter_by(event_type=event_type)
    if actor_type:
        q = q.filter_by(actor_type=actor_type)
    return [{"id": e.id, "claim_id": e.claim_id, "simulation_id": e.simulation_id, "event_type": e.event_type, "actor": e.actor,
             "actor_type": e.actor_type, "summary": e.summary, "details": e.details, "ts": e.created_at.isoformat()}
            for e in q.order_by(m.AuditEvent.id.desc()).limit(limit)]


@router.get("/rules")
def rules():
    return {"rules": RULES, "scoring_weights": settings.scoring_weights, "effort_minutes": settings.effort_minutes,
            "baseline_rules": benchmark.BASELINE_RULES, "assumptions": benchmark.ASSUMPTIONS}
