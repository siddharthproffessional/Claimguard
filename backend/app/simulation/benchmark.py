"""Reproducible benchmark: baseline scrubber vs ClaimGuard on the same seeded synthetic dataset.

All numbers are computed from this run against the dataset's ground-truth labels. They describe
behaviour on synthetic data only and say nothing about real payer rejection rates.
"""
import asyncio
import json
import os
import time
from pathlib import Path
import uuid
from collections import Counter

from app.config import ROOT, settings
from app.database import db as database
from app.models import models as m
from app.services.events import Recorder, bus
from app.simulation.seed import generate_dataset, load_dataset
from app.validation.engine import run_rules
from app.validation.refdata import RefData

# The baseline represents a conventional claim scrubber: field, format and arithmetic checks on the
# claim itself. It does not consult policies, documents, authorizations, payer rules or other claims
# (beyond an exact control-number match) and proposes no corrections.
BASELINE_RULES = ["COMP-001", "ELIG-001", "COD-001", "COD-002", "BILL-001", "DUP-001"]

ASSUMPTIONS = [
    "Dataset is fully synthetic and generated from a fixed seed; issue mix is designed, not sampled from real claims.",
    "Ground-truth labels come from the generator. ClaimGuard's rules were written against the same issue taxonomy, so "
    "deterministic recall on this dataset is an upper bound, not a field estimate.",
    "Three labelled issues exist only in free-text notes and can only be found by the Documentation Agent's LLM reading; "
    "with AI disabled they are counted as missed.",
    f"Baseline = scrubber running {len(BASELINE_RULES)} claim-level rules ({', '.join(BASELINE_RULES)}), no cross-record checks, no corrections.",
    "'READY' means all configured deterministic checks pass. It is not payer approval.",
    "Manual effort minutes are configured synthetic assumptions (EFFORT_MINUTES), not measurements.",
    "Processing time is wall-clock on this machine and includes LLM latency when AI is enabled.",
]


def clear_data(db):
    """Remove all demo data but keep saved simulation runs."""
    for table in reversed(database.Base.metadata.sorted_tables):
        if table.name != "simulation_runs":
            db.execute(table.delete())
    db.commit()


def load_demo(db, seed=42):
    clear_data(db)
    ds = generate_dataset(seed)
    load_dataset(db, ds)
    bus.reset_status()
    Recorder(db).audit("dataset_loaded", "system", "system", f"Loaded {len(ds['claims'])} synthetic claims (seed {seed})",
                       {"seed": seed, "claims": len(ds["claims"])})
    db.commit()
    bus.publish("dataset_loaded", seed=seed, claims=len(ds["claims"]))
    return ds


def _detection(truth, detected_by_claim, flagged):
    """Score detections against ground truth. detected_by_claim: claim_id -> set(rule ids)."""
    labelled = detected = 0
    by_cat = {}
    fp_claims = fn_claims = tp_claims = extra_flags = 0
    for cid, gt in truth.items():
        det = detected_by_claim.get(cid, set())
        want = {i["rule"] for i in gt["issues"]}
        for i in gt["issues"]:
            labelled += 1
            c = by_cat.setdefault(i["category"], {"labelled": 0, "detected": 0})
            c["labelled"] += 1
            if i["rule"] in det:
                detected += 1
                c["detected"] += 1
        extra_flags += len(det - want)
        is_flagged = cid in flagged
        if gt["clean"] and is_flagged:
            fp_claims += 1
        elif not gt["clean"] and is_flagged:
            tp_claims += 1
        elif not gt["clean"]:
            fn_claims += 1
    return {"labelled_issues": labelled, "issues_detected": detected, "issues_missed": labelled - detected,
            "issue_recall": round(detected / labelled, 4) if labelled else None, "by_category": by_cat,
            "claims_flagged": len(flagged), "true_positive_claims": tp_claims, "false_positive_claims": fp_claims,
            "claims_with_issue_not_flagged": fn_claims, "flags_without_matching_label": extra_flags}


def run_baseline(ref):
    t0 = time.perf_counter()
    det, flagged = {}, set()
    for c in ref.claims:
        fails = {r.rule_id for r in run_rules(c, ref, BASELINE_RULES) if r.status == "fail"}
        det[c["claim_id"]] = fails
        if fails:
            flagged.add(c["claim_id"])
    return det, flagged, round((time.perf_counter() - t0) * 1000, 2)


def claimguard_detection(db):
    det, flagged = {}, set()
    for c in db.query(m.Claim):
        fails = {r.rule_id for r in db.query(m.ValidationResult).filter_by(claim_id=c.id, run_id=c.latest_validation_run)
                 if r.status == "fail"}
        if any(e.get("source") == "ai_concern" and e.get("agent") == "documentation" for e in (c.escalations or [])):
            fails.add("AI-NARRATIVE")
        det[c.id] = fails
        if c.status != "READY":
            flagged.add(c.id)
    return det, flagged


def status_counts(db):
    cnt = Counter(c.status for c in db.query(m.Claim))
    return {k: cnt.get(k, 0) for k in ("READY", "REQUIRES_CORRECTION", "HUMAN_REVIEW")}


def unresolved_blocking(db):
    n = 0
    for c in db.query(m.Claim):
        n += db.query(m.ValidationResult).filter_by(claim_id=c.id, run_id=c.latest_validation_run, status="fail").count()
    return n


def mean_score(db):
    vals = [c.readiness_score for c in db.query(m.Claim) if c.readiness_score is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


async def run_simulation(sim_id: str, seed: int = 42, depth: str | None = None, operator_mode: str = "manual"):
    from app.agents.orchestrator import process_claim
    from app.ai import providers
    from app.services import corrections

    db = database.SessionLocal()
    sim = db.get(m.SimulationRun, sim_id)
    try:
        depth = settings.effective_depth(depth)
        ds = load_demo(db, seed)
        truth = {c["id"]: c["ground_truth"] for c in ds["claims"]}
        total = len(truth)
        ref = RefData.from_session(db)
        rec = Recorder(db, None, sim_id)
        rec.audit("simulation_started", "system", "system", f"Operation Zero Rejection started (seed {seed}, AI depth {depth}, "
                  f"operator {operator_mode})", {"seed": seed, "ai_depth": depth, "operator_mode": operator_mode})
        bus.publish("simulation", simulation_id=sim_id, phase="baseline", processed=0, total=total)

        b_det, b_flag, b_ms = run_baseline(ref)
        baseline = _detection(truth, b_det, b_flag)
        baseline.update({"processing_ms": b_ms, "rules": BASELINE_RULES, "correction_proposals": 0,
                         "claims_passed_to_submission": total - len(b_flag),
                         "claims_passed_with_known_issue": sum(1 for cid, gt in truth.items() if not gt["clean"] and cid not in b_flag)})

        calls0, fails0 = providers.stats.calls, providers.stats.failures
        sem = asyncio.Semaphore(max(1, settings.claim_concurrency))
        done = 0
        t0 = time.perf_counter()

        async def one(cid):
            nonlocal done
            async with sem:
                await process_claim(db, cid, sim_id, depth, ref)
                done += 1
                sim.progress = {"processed": done, "total": total}
                bus.publish("simulation", simulation_id=sim_id, phase="claimguard", processed=done, total=total)
                await asyncio.sleep(0)

        ids = [c["id"] for c in ds["claims"]]
        await asyncio.gather(*(one(cid) for cid in ids))
        cg_ms = round((time.perf_counter() - t0) * 1000, 1)
        db.commit()

        det, flagged = claimguard_detection(db)
        cg = _detection(truth, det, flagged)
        props = db.query(m.CorrectionProposal).filter(m.CorrectionProposal.status != "superseded").all()
        conflicts = [c for cl in db.query(m.Claim) for c in (cl.assessment or {}).get("conflicts", [])]
        initial = status_counts(db)
        projected_ready = sum(1 for cl in db.query(m.Claim)
                              if cl.status == "READY" or (cl.assessment or {}).get("projected_status_if_approved") == "READY")
        cg.update({
            "processing_ms": cg_ms, "avg_ms_per_claim": round(cg_ms / total, 1),
            "status_initial": initial, "unresolved_blocking_initial": unresolved_blocking(db),
            "mean_readiness_initial": mean_score(db),
            "proposals": {"drafted": len(props), "validated": sum(1 for p in props if p.status == "pending" and p.proposed_value is not None),
                          "needs_manual_value": sum(1 for p in props if p.proposed_value is None),
                          "failed_dry_run": sum(1 for p in props if p.status == "invalid")},
            "projected_ready_if_all_validated_proposals_approved": projected_ready,
            "conflicts": {"detected": len(conflicts), "resolved": sum(1 for c in conflicts if c["status"] == "resolved"),
                          "escalated": sum(1 for c in conflicts if c["status"] == "escalated")},
            "estimated_manual_minutes": sum((cl.assessment or {}).get("estimated_manual_minutes") or 0 for cl in db.query(m.Claim)),
            "agent_runs": db.query(m.AgentRun).count(), "tool_invocations": db.query(m.ToolInvocation).count(),
            "agent_messages": db.query(m.AgentMessage).count(),
            "ai": {"depth": depth, "claude_configured": settings.claude_enabled, "openai_configured": settings.openai_enabled,
                   "calls": providers.stats.calls - calls0, "failures": providers.stats.failures - fails0},
        })

        approvals = 0
        if operator_mode == "simulated_approve":
            bus.publish("simulation", simulation_id=sim_id, phase="simulated_operator", processed=total, total=total)
            for p in db.query(m.CorrectionProposal).filter_by(status="pending").order_by(m.CorrectionProposal.id).all():
                if p.proposed_value is None:
                    continue
                try:
                    corrections.approve(db, p.claim_id, p.id, actor="simulated-operator", role="supervisor",
                                        note="benchmark: simulated operator approves validated proposals", ref=ref)
                    approvals += 1
                except corrections.WorkflowError:
                    pass
        final = status_counts(db)
        cg.update({"operator_mode": operator_mode, "approvals_applied": approvals, "status_final": final,
                   "unresolved_blocking_final": unresolved_blocking(db), "mean_readiness_final": mean_score(db),
                   "human_review_claims": final["HUMAN_REVIEW"],
                   "human_decisions_required": cg["proposals"]["validated"] + cg["proposals"]["needs_manual_value"] + initial["HUMAN_REVIEW"]})

        cats = Counter(i["category"] for gt in truth.values() for i in gt["issues"])
        results = {"simulation_id": sim_id, "seed": seed,
                   "dataset": {"claims": total, "clean": sum(1 for g in truth.values() if g["clean"]),
                               "with_issues": sum(1 for g in truth.values() if not g["clean"]),
                               "labelled_issues": sum(cats.values()), "by_category": dict(cats),
                               "ai_only_issues": sum(1 for g in truth.values() for i in g["issues"] if i["detectable"] == "ai_only")},
                   "baseline": baseline, "claimguard": cg, "assumptions": ASSUMPTIONS}
        sim.results, sim.status, sim.completed_at = results, "completed", m.utcnow()
        rec.audit("simulation_completed", "system", "system",
                  f"Simulation complete: baseline detected {baseline['issues_detected']}/{baseline['labelled_issues']} labelled issues, "
                  f"ClaimGuard {cg['issues_detected']}/{cg['labelled_issues']}", {"simulation_id": sim_id})
        db.commit()
        out = Path(os.getenv("CLAIMGUARD_RESULTS_DIR", ROOT / "demo" / "results"))
        out.mkdir(parents=True, exist_ok=True)
        (out / f"simulation_{sim_id}.json").write_text(json.dumps(results, indent=2))
        bus.publish("simulation", simulation_id=sim_id, phase="completed", processed=total, total=total)
        return results
    except Exception as e:
        db.rollback()
        sim = db.get(m.SimulationRun, sim_id)
        if sim:
            sim.status, sim.error, sim.completed_at = "failed", f"{type(e).__name__}: {e}", m.utcnow()
            db.commit()
        bus.publish("simulation", simulation_id=sim_id, phase="failed", error=str(e))
        raise
    finally:
        db.close()


def new_simulation(db, seed, depth, operator_mode):
    sim = m.SimulationRun(id=uuid.uuid4().hex[:10], seed=seed, status="running",
                          config={"seed": seed, "ai_depth": settings.effective_depth(depth), "operator_mode": operator_mode,
                                  "scoring_weights": settings.scoring_weights, "baseline_rules": BASELINE_RULES},
                          progress={"processed": 0, "total": 0})
    db.add(sim)
    db.commit()
    return sim
