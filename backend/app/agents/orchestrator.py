"""ClaimGuard Orchestrator.

Coordinates the specialists for one claim: assigns tasks, relays agent-to-agent review requests,
detects conflicting positions, runs bounded reassessment loops, invokes the deterministic validation
engine, coordinates correction proposals, asks Claude for a synthesis and OpenAI for an independent
review, and writes an explainable final assessment. The engine's result is authoritative; model
output can only escalate a claim to human review.
"""
import asyncio
import time

from app.agents.base import ClaimContext
from app.agents.recovery import RecoveryAgent
from app.agents.specialists import BY_KEY
from app.ai import prompts, providers
from app.config import settings
from app.models import models as m
from app.schemas.agents import Conflict, IndependentReview, Synthesis
from app.services.claims import snapshot
from app.services.events import Recorder, bus
from app.services.workflow import apply_status, persist_validation
from app.validation.engine import determine_outcome, validate_claim
from app.validation.refdata import RefData

PARALLEL = ["eligibility", "documentation", "coding", "authorization", "fraud_duplicate", "compliance"]
DISCLAIMER = ("Administrative decision support on synthetic data. READY means all configured deterministic checks pass; "
              "it is not a guarantee of payer approval and not a clinical or coding determination.")
_recovery = RecoveryAgent()


def detect_conflicts(outputs) -> list[Conflict]:
    """Find agents holding incompatible positions about the same claim."""
    found = []
    auth, elig, comp = outputs.get("authorization"), outputs.get("eligibility"), outputs.get("compliance")
    cod, doc = outputs.get("coding"), outputs.get("documentation")
    if auth and auth.data.get("auth_status") == "valid":
        if elig and elig.failed("ELIG-003"):
            found.append(Conflict(id="authorization-vs-eligibility", agents=["authorization", "eligibility"], topic="authorization",
                                  description="Authorization Agent reports a valid authorization; Eligibility Agent reports coverage "
                                              "was not active on the date of service."))
        if comp and comp.failed("COV-001"):
            found.append(Conflict(id="authorization-vs-compliance", agents=["authorization", "compliance"], topic="coverage",
                                  description="Authorization Agent reports a valid authorization; Compliance Agent reports the plan "
                                              "excludes the billed procedure."))
    if cod and doc and doc.failed("DOC-002") and cod.passed("COD-003") and "documentation" not in cod.acknowledged_peers:
        found.append(Conflict(id="coding-vs-documentation", agents=["coding", "documentation"], topic="procedure_code",
                              description="Coding Agent finds the billed codes consistent; Documentation Agent finds the attached "
                                          "document names a different procedure."))
    for key, out in outputs.items():
        ai = [f for f in out.findings if f.source == "ai"]
        if ai and not any(f.status == "fail" and f.source == "deterministic" for f in out.findings):
            found.append(Conflict(id=f"ai-vs-rules-{key}", agents=[key, "validation_engine"], topic="ai_concern",
                                  description=f"{BY_KEY[key].name} (AI reasoning) raised a concern that the deterministic rules "
                                              f"did not: {ai[0].explanation[:220]}"))
    return found


def _public(out):
    d = out.model_dump()
    d["findings"] = [f for f in d["findings"] if f["status"] != "pass" or f["source"] != "deterministic"] or d["findings"][:1]
    return d


async def process_claim(db, claim_id: str, simulation_id=None, depth=None, ref=None, reason="analysis", actor="system") -> dict:
    t0 = time.perf_counter()
    claim = db.get(m.Claim, claim_id)
    if claim is None:
        raise KeyError(claim_id)
    depth = settings.effective_depth(depth)
    rec = Recorder(db, claim_id, simulation_id)
    ref = ref or RefData.from_session(db)
    snap = snapshot(claim)
    ref.replace_claim(snap)
    ctx = ClaimContext(db, snap, ref, rec, depth)
    claim.status = "PROCESSING"
    orch = rec.run_start("orchestrator")
    rec.audit("analysis_started", actor, "system", f"{reason.capitalize()} started for {claim_id} (v{claim.version}, AI depth {depth})",
              {"claim_version": claim.version, "ai_depth": depth})
    bus.publish("claim_status", claim_id=claim_id, status="PROCESSING")
    escalations, conflicts, notes = [], [], []
    iterations = 1

    # 1. intake
    task = rec.task("intake", "Parse, validate mandatory fields and classify the claim")
    rec.message("orchestrator", "intake", "task_assignment", "Receive and classify this claim.")
    intake = await BY_KEY["intake"].run(ctx)
    rec.task_done(task, intake.status)
    rec.message("intake", "orchestrator", "finding_report", intake.summary)

    # 2. specialists in parallel
    tasks = {}
    for key in PARALLEL:
        tasks[key] = rec.task(key, BY_KEY[key].responsibility)
        rec.message("orchestrator", key, "task_assignment", f"Investigate {claim_id} within your remit and report findings.")
    outs = await asyncio.gather(*(BY_KEY[k].run(ctx) for k in PARALLEL))
    for key, out in zip(PARALLEL, outs):
        rec.task_done(tasks[key], out.status)
        rec.message(key, "orchestrator", "finding_report", out.summary, {"findings": [f.code for f in out.findings if f.status != "pass"]})

    # 3. review requests, conflict detection and bounded reassessment
    handled = set()

    def pending_requests():
        reqs = []
        for o in ctx.state.outputs.values():
            for rr in o.review_requests:
                if (o.agent, rr.to_agent) not in handled and rr.to_agent in BY_KEY and rr.to_agent != "intake":
                    reqs.append((o.agent, rr))
        return reqs

    conflicts = detect_conflicts(ctx.state.outputs)
    for c in conflicts:
        bus.publish("conflict", claim_id=claim_id, conflict=c.model_dump())
        rec.status(c.agents[0], "conflict_detected")
        rec.audit("conflict_detected", "orchestrator", "agent", c.description, c.model_dump())
        if c.id.startswith("ai-vs-rules"):
            c.status, c.resolution = "escalated", "AI concern cannot be verified by rules; sent to human review."
    reqs = pending_requests()
    while (reqs or any(c.status == "open" for c in conflicts)) and iterations < settings.max_iterations:
        iterations += 1
        targets = {}
        for sender, rr in reqs:
            handled.add((sender, rr.to_agent))
            rec.message(sender, rr.to_agent, "review_request", rr.reason, rr.context)
            targets.setdefault(rr.to_agent, []).append({"from": sender, "reason": rr.reason})
        for c in conflicts:
            if c.status == "open" and not any(p["from"] == c.agents[1] for p in targets.get(c.agents[0], [])):
                handled.add((c.agents[1], c.agents[0]))
                targets.setdefault(c.agents[0], []).append({"from": c.agents[1], "reason": c.description})
        if not targets:
            break
        for key, peers in targets.items():
            rec.message("orchestrator", key, "reassessment_request",
                        f"Reassess with evidence from {', '.join(p['from'] for p in peers)} (iteration {iterations}).")
        keys = list(targets)
        reruns = await asyncio.gather(*(BY_KEY[k].run(ctx, iterations, {"all": targets[k]}) for k in keys))
        for key, out in zip(keys, reruns):
            for p in targets[key]:
                rec.message(key, p["from"], "review_response", out.summary)
        still = {c.id for c in detect_conflicts(ctx.state.outputs)}
        for c in conflicts:
            if c.status == "open" and c.id not in still:
                c.status = "resolved"
                c.resolution = (f"{BY_KEY[c.agents[0]].name} revised its position after reviewing the "
                                f"{BY_KEY[c.agents[1]].name}'s evidence (iteration {iterations}).")
                rec.audit("conflict_resolved", "orchestrator", "agent", c.resolution, c.model_dump())
                bus.publish("conflict", claim_id=claim_id, conflict=c.model_dump())
        reqs = pending_requests()
    for c in conflicts:
        if c.status == "open":
            c.status, c.resolution = "escalated", f"Unresolved after {iterations} iteration(s); sent to human review."
            rec.audit("conflict_escalated", "orchestrator", "agent", c.resolution, c.model_dump())
        if c.status == "escalated":
            escalations.append({"source": "conflict", "agent": c.agents[0], "code": c.id, "reason": c.description})

    for o in ctx.state.outputs.values():
        if o.status == "failed":
            escalations.append({"source": "agent_failure", "agent": o.agent, "code": "AGENT-FAILED", "reason": o.summary})
        for f in o.findings:
            if f.escalate and f.source == "ai":
                escalations.append({"source": "ai_concern", "agent": o.agent, "code": f.code, "reason": f.explanation})

    # 4. deterministic validation (authoritative)
    rec.message("orchestrator", "validation_engine", "tool_request", "Run all deterministic rules on the current claim state.")
    results = rec.tool("orchestrator", orch, "validation_engine.validate_claim", lambda: validate_claim(snap, ref), claim_id=claim_id)
    run_id = persist_validation(db, claim, results)

    # 5. recovery: correction proposals + dry-run validation
    rtask = rec.task("recovery", "Consolidate findings and draft validated correction proposals")
    rec.message("orchestrator", "recovery", "task_assignment", "Draft corrections for correctable findings and dry-run them.")
    recovery = _recovery.prepare(results, escalations)
    rout = await recovery.run(ctx)
    rec.task_done(rtask, rout.status)
    rec.message("recovery", "orchestrator", "finding_report", rout.summary)
    db.query(m.CorrectionProposal).filter_by(claim_id=claim_id, status="pending").update({"status": "superseded"})
    rows = []
    for p in recovery.proposals:
        row = m.CorrectionProposal(claim_id=claim_id, claim_version=claim.version, projected_status=recovery.projected_status, **p)
        db.add(row)
        rows.append(row)
    db.flush()
    for row in rows:
        rec.audit("correction_proposed", row.agent, "agent", f"Proposal #{row.id}: {row.op} {row.field} ({row.rule_id}) - {row.status}",
                  {"proposal_id": row.id, "original": row.original_value, "proposed": row.proposed_value, "validation": row.validation_note})
    proposals = [{"id": r.id, "rule_id": r.rule_id, "op": r.op, "field": r.field, "line_no": r.line_no,
                  "original_value": r.original_value, "proposed_value": r.proposed_value, "evidence": r.evidence,
                  "agent": r.agent, "status": r.status, "requires_role": r.requires_role} for r in rows]

    # 6. status from the engine, then compliance gate
    status, score, dims = apply_status(claim, results, escalations)
    engine_status = determine_outcome(results)  # rules only, before any escalation
    grun = rec.run_start("compliance")  # final readiness gate: a distinct check, not a reassessment
    try:
        status, gate_notes, gate_audit = BY_KEY["compliance"].final_gate(ctx, grun, results, proposals, status, escalations)
        notes += gate_notes
        rec.run_finish(grun, "completed", {"summary": "Final readiness gate passed" if not gate_notes else "; ".join(gate_notes),
                                           "audit": gate_audit})
    except Exception as e:
        rec.run_finish(grun, "failed", None, error=str(e))
        escalations.append({"source": "agent_failure", "agent": "compliance", "code": "GATE-FAILED", "reason": str(e)})
    rec.message("compliance", "orchestrator", "gate_result", f"Readiness gate: {status}")

    # 7. model synthesis and independent review (advisory; failures are contained)
    flagged = status != "READY" or bool(escalations)
    want_ai = depth == "full" or (depth == "synthesis" and flagged)
    val_payload = [{"rule_id": r.rule_id, "status": r.status, "severity": r.severity, "explanation": r.explanation,
                    "evidence": r.evidence, "resolution": r.resolution} for r in results if r.status != "not_applicable"]
    agent_payload = {k: _public(o) for k, o in ctx.state.outputs.items()}
    synthesis, review, disagreements = None, None, []
    ai = {"depth": depth, "claude": "not_requested", "openai": "not_requested"}
    if depth != "none" and want_ai:
        s_sys, s_user = prompts.synthesis(snap, agent_payload, val_payload, [c.model_dump() for c in conflicts], proposals, engine_status)
        sres = await providers.claude_json(s_sys, s_user, settings.claude_model_orchestrator, Synthesis)
        if sres.ok:
            synthesis, ai["claude"] = sres.data, f"ok ({sres.model}, {sres.latency_ms} ms)"
            rec.message("orchestrator", "orchestrator", "synthesis", synthesis["assessment_summary"][:500])
            if synthesis["recommended_status"] != engine_status:
                d = {"between": ["claude_orchestrator", "validation_engine"], "claude": synthesis["recommended_status"],
                     "engine": engine_status, "note": "Engine status stands; difference preserved for audit."}
                disagreements.append(d)
                rec.audit("model_disagreement", settings.claude_model_orchestrator, "model",
                          f"Claude recommends {d['claude']}; engine determined {engine_status}", d)
                if engine_status == "READY":
                    escalations.append({"source": "ai_concern", "agent": "orchestrator", "code": "AI-SYNTHESIS",
                                        "reason": "Claude synthesis did not support READY: " + "; ".join(synthesis["key_risks"][:3])})
        else:
            ai["claude"] = f"unavailable: {sres.error}"
            if sres.error != "not_configured":
                rec.audit("ai_provider_failure", "claude", "model", f"Claude synthesis failed: {sres.error}", {"error": sres.error})

        rrun = rec.run_start("independent_reviewer")
        rec.message("orchestrator", "independent_reviewer", "review_request", "Independently test this assessment; do not simply agree.")
        r_sys, r_user = prompts.independent_review(snap, agent_payload, val_payload, proposals,
                                                   {"engine_status": engine_status, "status_after_gate": status,
                                                    "escalations": escalations, "claude_synthesis": synthesis})
        rres = await providers.openai_json(r_sys, r_user, IndependentReview)
        if rres.ok:
            review, ai["openai"] = rres.data, f"ok ({rres.model}, {rres.latency_ms} ms)"
            rec.run_finish(rrun, "completed", {"summary": f"{review['verdict']}: {review['rationale'][:300]}", **review}, True,
                           f"{rres.model} in {rres.latency_ms} ms")
            rec.message("independent_reviewer", "orchestrator", "review_response", f"{review['verdict']}: {review['rationale'][:400]}")
            if review["verdict"] != "concur" or review["recommended_status"] != status:
                d = {"between": ["openai_reviewer", "claimguard_assessment"], "reviewer_verdict": review["verdict"],
                     "reviewer_status": review["recommended_status"], "assessment_status": status,
                     "challenges": review["challenges"], "missing_evidence": review["missing_evidence"]}
                disagreements.append(d)
                rec.audit("model_disagreement", rres.model, "model",
                          f"Independent reviewer: {review['verdict']} (recommends {review['recommended_status']}, assessment {status})", d)
                if status == "READY" and settings.reviewer_can_escalate:
                    escalations.append({"source": "independent_review", "agent": "independent_reviewer", "code": "REVIEW-CHALLENGE",
                                        "reason": review["rationale"][:300]})
        else:
            ai["openai"] = f"unavailable: {rres.error}"
            rec.run_finish(rrun, "failed", {"summary": f"Independent review unavailable: {rres.error}"}, False, "", error=rres.error,
                           live_status="idle" if rres.error == "not_configured" else "failed")
            if rres.error != "not_configured":
                rec.audit("ai_provider_failure", "openai", "model", f"Independent review failed: {rres.error}", {"error": rres.error})
                notes.append("Independent AI review was unavailable; assessment rests on deterministic validation and agent findings.")
        if escalations != (claim.escalations or []):
            status, score, dims = apply_status(claim, results, escalations)

    claim.status = status
    fails = [r for r in results if r.status == "fail"]
    assessment = {
        "claim_id": claim_id, "claim_version": claim.version, "status": status, "engine_status": engine_status,
        "readiness_score": score, "dimension_scores": dims, "validation_run": run_id,
        "blocking_issues": [{"rule_id": r.rule_id, "severity": r.severity, "explanation": r.explanation, "resolution": r.resolution,
                             "next_action": r.next_action, "agent": BY_KEY_AGENT(r.rule_id)} for r in fails],
        "warnings": [f.model_dump() for o in ctx.state.outputs.values() for f in o.findings if f.status == "warning"],
        "passed_checks": sum(1 for r in results if r.status == "pass"),
        "conflicts": [c.model_dump() for c in conflicts], "escalations": escalations, "notes": notes,
        "proposals": len(proposals), "projected_status_if_approved": recovery.projected_status,
        "estimated_manual_minutes": rout.data.get("estimated_manual_minutes"),
        "synthesis": synthesis, "independent_review": review, "disagreements": disagreements, "ai": ai,
        "iterations": iterations, "shared_state_version": ctx.state.version, "state_history": ctx.state.history,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 1), "disclaimer": DISCLAIMER,
    }
    claim.assessment = assessment
    rec.run_finish(orch, "warning" if status != "READY" else "completed",
                   {"summary": f"{status} (readiness {score}); {len(fails)} blocking, {len(conflicts)} conflict(s), {len(proposals)} proposal(s)"},
                   bool(synthesis), ai["claude"], live_status="idle")
    for k in list(BY_KEY) + ["recovery", "independent_reviewer"]:
        if bus.agent_status[k]["claim_id"] == claim_id and bus.agent_status[k]["status"] not in ("failed",):
            rec.status(k, "idle")
    rec.audit("assessment_completed", "orchestrator", "agent", f"{claim_id}: {status}, readiness {score}",
              {"status": status, "engine_status": engine_status, "failed_rules": [r.rule_id for r in fails],
               "escalations": escalations, "disagreements": len(disagreements)})
    db.commit()
    bus.publish("claim_status", claim_id=claim_id, status=status, readiness_score=score, issue_count=claim.issue_count)
    return assessment


def BY_KEY_AGENT(rule_id):
    from app.validation.engine import RULE_META
    return RULE_META[rule_id]["agent"]
