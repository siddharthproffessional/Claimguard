"""Agent base class and shared claim context."""
import asyncio

from app.ai import prompts, providers
from app.config import settings
from app.schemas.agents import AgentOutput, Evidence, Finding, ReviewRequest, SpecialistReasoning
from app.validation.engine import run_rules

VALID_REVIEW_TARGETS = {"eligibility", "documentation", "coding", "authorization", "fraud_duplicate", "compliance"}


class SharedState:
    """Versioned shared claim state. Every agent output bumps the version."""

    def __init__(self, claim_version):
        self.version = 0
        self.claim_version = claim_version
        self.outputs: dict[str, AgentOutput] = {}
        self.history: list[dict] = []
        self.conflicts = []

    def put(self, out: AgentOutput):
        self.version += 1
        self.outputs[out.agent] = out
        self.history.append({"state_version": self.version, "agent": out.agent, "iteration": out.iteration, "status": out.status})


class ClaimContext:
    def __init__(self, db, claim: dict, ref, rec, depth="none"):
        self.db, self.claim, self.ref, self.rec, self.depth = db, claim, ref, rec, depth
        self.state = SharedState(claim.get("_version", 1))


def finding_from_rule(r) -> Finding:
    return Finding(code=r.rule_id, status=r.status, severity=r.severity, explanation=r.explanation,
                   evidence=[Evidence(**e) for e in r.evidence], next_action=r.next_action, source="deterministic")


class BaseAgent:
    key = "base"
    name = "Base Agent"
    responsibility = ""
    tools: list[str] = []
    rule_ids: list[str] = []
    ai_in_synthesis = False  # whether this agent calls Claude at depth "synthesis"

    def uses_ai(self, ctx):
        if not settings.claude_enabled:
            return False
        return ctx.depth == "full" or (ctx.depth == "synthesis" and self.ai_in_synthesis)

    def investigate(self, ctx, run, out: AgentOutput, peer: dict | None):
        """Deterministic tool work. Override per agent."""
        raise NotImplementedError

    def rules(self, ctx, run, out):
        """Invoke this agent's deterministic validation rules as a logged tool call."""
        results = ctx.rec.tool(self.key, run, "run_validation_rules", lambda: run_rules(ctx.claim, ctx.ref, self.rule_ids),
                               rules=self.rule_ids)
        for r in results:
            out.findings.append(finding_from_rule(r))
        return {r.rule_id: r for r in results}

    def ai_payload(self, ctx, out):
        return None  # extra documents for the prompt

    async def reason(self, ctx, out: AgentOutput):
        """Optional Claude reasoning over tool results. AI concerns can only escalate to human review."""
        system, user = prompts.specialist(self.name, self.responsibility, ctx.claim, out.data,
                                          [f.model_dump() for f in out.findings], self.ai_payload(ctx, out))
        res = await providers.claude_json(system, user, settings.claude_model_specialist, SpecialistReasoning)
        if not res.ok:
            out.ai_note = f"Claude unavailable ({res.error}); deterministic tools only"
            out.uncertainty.append("AI reasoning was not available for this agent run.")
            return
        out.ai_used = True
        out.ai_note = f"{res.model} in {res.latency_ms} ms"
        data = res.data
        if data.get("summary"):
            out.summary = (out.summary + " | AI: " + data["summary"]).strip(" |")
        for c in data.get("additional_concerns", [])[:5]:
            out.findings.append(Finding(
                code=f"AI-{self.key.upper()}", status="warning", severity="high",
                explanation=f"{c.get('title', 'Concern')}: {c.get('explanation', '')} (AI confidence: {c.get('confidence', 'unstated')})",
                evidence=[Evidence(type="ai_cited_reference", ref=str(r), detail="cited by model") for r in c.get("evidence_refs", [])],
                next_action="Human review of this AI-raised concern.", source="ai", escalate=True))
        out.uncertainty += [str(u) for u in data.get("uncertainty", [])][:5]
        for rr in data.get("request_review_from", [])[:3]:
            if rr.get("agent") in VALID_REVIEW_TARGETS and rr.get("agent") != self.key:
                out.review_requests.append(ReviewRequest(to_agent=rr["agent"], reason=f"(AI) {rr.get('reason', '')}"))

    async def run(self, ctx, iteration=1, peer=None) -> AgentOutput:
        rec = ctx.rec
        run = rec.run_start(self.key, iteration)
        out = AgentOutput(agent=self.key, claim_id=ctx.claim["claim_id"], iteration=iteration)
        try:
            self.investigate(ctx, run, out, peer)
            if self.uses_ai(ctx):
                await asyncio.wait_for(self.reason(ctx, out), timeout=settings.agent_timeout_s)
            elif ctx.depth != "none" and not settings.claude_enabled:
                out.ai_note = "Claude not configured; deterministic tools only"
            has_issue = any(f.status in ("fail", "warning") for f in out.findings)
            out.status = "warning" if has_issue else "completed"
            if not out.summary:
                fails = [f.code for f in out.findings if f.status == "fail"]
                out.summary = (f"{len(fails)} blocking finding(s): {', '.join(fails)}" if fails else "No blocking findings")
            rec.run_finish(run, out.status, out.model_dump(), out.ai_used, out.ai_note)
        except Exception as e:  # an agent failure must never take the pipeline down
            out.status = "failed"
            out.summary = f"Agent failed: {type(e).__name__}: {e}"
            out.uncertainty.append("This agent did not complete; its domain needs human review.")
            rec.run_finish(run, "failed", out.model_dump(), out.ai_used, out.ai_note, error=str(e))
        ctx.state.put(out)
        return out
