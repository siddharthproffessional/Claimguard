"""Structured contracts for agent communication."""
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentKey = Literal["orchestrator", "intake", "eligibility", "documentation", "coding", "authorization",
                   "fraud_duplicate", "compliance", "recovery", "independent_reviewer"]


class Evidence(BaseModel):
    type: str
    ref: str | None = None
    detail: str = ""


class Finding(BaseModel):
    code: str  # rule id for deterministic findings, AI-* / ADV-* for advisories
    status: Literal["pass", "fail", "warning", "not_applicable"]
    severity: str = "medium"
    explanation: str
    evidence: list[Evidence] = Field(default_factory=list)
    next_action: str = ""
    source: Literal["deterministic", "ai", "agent_advisory"] = "deterministic"
    escalate: bool = False  # advisory that should send the claim to human review


class ReviewRequest(BaseModel):
    to_agent: str
    reason: str
    context: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    agent: str
    claim_id: str
    iteration: int = 1
    status: Literal["completed", "warning", "failed"] = "completed"
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    review_requests: list[ReviewRequest] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    ai_used: bool = False
    ai_note: str = ""
    acknowledged_peers: list[str] = Field(default_factory=list)

    def failed(self, code):
        return any(f.code == code and f.status == "fail" for f in self.findings)

    def passed(self, code):
        return any(f.code == code and f.status == "pass" for f in self.findings)


class Conflict(BaseModel):
    id: str
    agents: list[str]
    topic: str
    description: str
    status: Literal["open", "resolved", "escalated"] = "open"
    resolution: str = ""


class SpecialistReasoning(BaseModel):
    """Shape Claude must return for a specialist agent."""
    summary: str = ""
    additional_concerns: list[dict[str, Any]] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    request_review_from: list[dict[str, Any]] = Field(default_factory=list)


class Synthesis(BaseModel):
    assessment_summary: str = ""
    key_risks: list[str] = Field(default_factory=list)
    conflict_adjudication: list[dict[str, Any]] = Field(default_factory=list)
    recommended_status: Literal["READY", "REQUIRES_CORRECTION", "HUMAN_REVIEW"]
    unsupported_items: list[str] = Field(default_factory=list)


class IndependentReview(BaseModel):
    verdict: Literal["concur", "challenge", "needs_more_evidence"]
    recommended_status: Literal["READY", "REQUIRES_CORRECTION", "HUMAN_REVIEW"]
    challenges: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    rationale: str = ""
