"""Database models. Dates are ISO-8601 strings (YYYY-MM-DD) so they compare lexicographically
and serialise without conversion. All data is synthetic."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Payer(Base):
    __tablename__ = "payers"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)


class Provider(Base):
    __tablename__ = "providers"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    npi = Column(String, index=True)
    specialty = Column(String)


class Patient(Base):
    __tablename__ = "patients"
    id = Column(String, primary_key=True)  # synthetic reference, e.g. PT-0001
    first_name = Column(String)
    last_name = Column(String)
    dob = Column(String)
    gender = Column(String)
    member_id = Column(String, index=True)
    policies = relationship("InsurancePolicy", back_populates="patient")


class InsurancePolicy(Base):
    __tablename__ = "insurance_policies"
    id = Column(String, primary_key=True)
    policy_number = Column(String, index=True, nullable=False)
    patient_id = Column(String, ForeignKey("patients.id"), index=True)
    payer_id = Column(String, ForeignKey("payers.id"), index=True)
    plan_name = Column(String)
    effective_date = Column(String)
    termination_date = Column(String)
    status = Column(String)
    excluded_procedures = Column(JSON, default=list)
    patient = relationship("Patient", back_populates="policies")


class Claim(Base):
    __tablename__ = "claims"
    id = Column(String, primary_key=True)  # CLM-0001
    seq = Column(Integer, index=True)  # submission order
    control_number = Column(String, index=True)
    patient_id = Column(String, ForeignKey("patients.id"), index=True)
    provider_id = Column(String, ForeignKey("providers.id"), index=True)
    payer_id = Column(String, ForeignKey("payers.id"), index=True)
    policy_number = Column(String)
    member_id = Column(String)
    patient_dob = Column(String)
    service_date = Column(String, index=True)
    submitted_date = Column(String)
    place_of_service = Column(String)
    claim_type = Column(String)
    total_amount = Column(Float)
    authorization_number = Column(String)
    attached_document_ids = Column(JSON, default=list)
    # workflow state
    version = Column(Integer, default=1)
    status = Column(String, default="NEW", index=True)  # NEW|PROCESSING|READY|REQUIRES_CORRECTION|HUMAN_REVIEW
    readiness_score = Column(Float)
    issue_count = Column(Integer, default=0)
    assigned_agent = Column(String)
    initial_status = Column(String)
    initial_score = Column(Float)
    escalations = Column(JSON, default=list)  # non-deterministic reasons for HUMAN_REVIEW
    assessment = Column(JSON)  # final explainable assessment from the orchestrator
    latest_validation_run = Column(String)
    # benchmark-only label; never passed to agents or the validation engine
    ground_truth = Column(JSON)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    lines = relationship("ClaimLineItem", back_populates="claim", cascade="all, delete-orphan",
                         order_by="ClaimLineItem.line_no")
    patient = relationship("Patient")
    provider = relationship("Provider")
    payer = relationship("Payer")


class ClaimLineItem(Base):
    __tablename__ = "claim_line_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String, ForeignKey("claims.id"), index=True)
    line_no = Column(Integer)
    procedure_code = Column(String, index=True)
    diagnosis_codes = Column(JSON, default=list)
    units = Column(Integer, default=1)
    unit_price = Column(Float)
    amount = Column(Float)
    claim = relationship("Claim", back_populates="lines")


class ClaimVersion(Base):
    """Immutable snapshots. Version 1 is the original claim and is never modified."""
    __tablename__ = "claim_versions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String, ForeignKey("claims.id"), index=True)
    version = Column(Integer)
    snapshot = Column(JSON)
    reason = Column(String)
    actor = Column(String)
    created_at = Column(DateTime, default=utcnow)


class ClinicalDocument(Base):
    __tablename__ = "clinical_documents"
    id = Column(String, primary_key=True)
    patient_id = Column(String, ForeignKey("patients.id"), index=True)
    provider_id = Column(String)
    doc_type = Column(String, index=True)
    service_date = Column(String)
    content = Column(Text)
    extracted = Column(JSON, default=dict)  # {"procedure_code":..., "diagnosis_codes":[...]}


class AuthorizationRecord(Base):
    __tablename__ = "authorization_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    auth_number = Column(String, unique=True, index=True)
    patient_id = Column(String, ForeignKey("patients.id"), index=True)
    payer_id = Column(String)
    procedure_code = Column(String)
    valid_from = Column(String)
    valid_to = Column(String)
    status = Column(String)


class PayerRule(Base):
    __tablename__ = "payer_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    payer_id = Column(String, ForeignKey("payers.id"), index=True)
    rule_type = Column(String, index=True)  # required_documents | authorization_required
    key = Column(String)  # procedure category or procedure code
    value = Column(JSON)
    description = Column(String)


class CodingReference(Base):
    __tablename__ = "coding_references"
    code = Column(String, primary_key=True)
    code_type = Column(String, index=True)  # diagnosis | procedure
    description = Column(String)
    category = Column(String)
    unit_price = Column(Float)
    max_units = Column(Integer)
    compatible_diagnoses = Column(JSON)


class ValidationRule(Base):
    __tablename__ = "validation_rules"
    rule_id = Column(String, primary_key=True)
    name = Column(String)
    dimension = Column(String)
    severity = Column(String)
    agent = Column(String)
    description = Column(String)
    enabled = Column(Boolean, default=True)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True)
    claim_id = Column(String, ForeignKey("claims.id"), index=True)
    claim_version = Column(Integer)
    rule_id = Column(String, index=True)
    status = Column(String)  # pass | fail | warning | not_applicable
    severity = Column(String)
    dimension = Column(String)
    resolution = Column(String)
    explanation = Column(Text)
    evidence = Column(JSON)
    details = Column(JSON)
    next_action = Column(String)
    created_at = Column(DateTime, default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String, index=True)
    simulation_id = Column(String, index=True)
    agent = Column(String, index=True)
    iteration = Column(Integer, default=1)
    status = Column(String)  # working | completed | warning | failed
    ai_used = Column(Boolean, default=False)
    ai_note = Column(String)
    output = Column(JSON)
    error = Column(Text)
    duration_ms = Column(Float)
    started_at = Column(DateTime, default=utcnow)


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_run_id = Column(Integer, ForeignKey("agent_runs.id"), index=True)
    claim_id = Column(String, index=True)
    agent = Column(String)
    tool = Column(String)
    args = Column(JSON)
    result_summary = Column(Text)
    ok = Column(Boolean, default=True)
    duration_ms = Column(Float)
    created_at = Column(DateTime, default=utcnow)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String, index=True)
    simulation_id = Column(String, index=True)
    sender = Column(String)
    recipient = Column(String)
    msg_type = Column(String)
    content = Column(Text)
    payload = Column(JSON)
    created_at = Column(DateTime, default=utcnow)


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String, index=True)
    simulation_id = Column(String, index=True)
    agent = Column(String, index=True)
    description = Column(String)
    status = Column(String, default="assigned")
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime)


class CorrectionProposal(Base):
    __tablename__ = "correction_proposals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String, ForeignKey("claims.id"), index=True)
    claim_version = Column(Integer)
    rule_id = Column(String)
    op = Column(String)  # set_field | set_line_field | attach_document
    field = Column(String)
    line_no = Column(Integer)
    original_value = Column(JSON)
    proposed_value = Column(JSON)
    problem = Column(Text)
    evidence = Column(JSON)
    agent = Column(String)
    confidence_note = Column(Text)
    requires_role = Column(String, default="billing_operator")
    status = Column(String, default="pending", index=True)  # pending|approved|rejected|superseded|invalid
    projected_status = Column(String)  # dry-run outcome if only this proposal were applied
    validation_note = Column(Text)
    created_at = Column(DateTime, default=utcnow)


class CorrectionApproval(Base):
    __tablename__ = "correction_approvals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    proposal_id = Column(Integer, ForeignKey("correction_proposals.id"), index=True)
    claim_id = Column(String, index=True)
    action = Column(String)  # approved | rejected
    actor = Column(String)
    role = Column(String)
    edited_value = Column(JSON)
    note = Column(Text)
    created_at = Column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String, index=True)
    simulation_id = Column(String, index=True)
    event_type = Column(String, index=True)
    actor = Column(String)
    actor_type = Column(String)  # agent | human | system | model
    summary = Column(Text)
    details = Column(JSON)
    created_at = Column(DateTime, default=utcnow, index=True)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    id = Column(String, primary_key=True)
    seed = Column(Integer)
    status = Column(String, default="running")
    config = Column(JSON)
    progress = Column(JSON)
    results = Column(JSON)
    error = Column(Text)
    started_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime)


Index("ix_valres_claim_run", ValidationResult.claim_id, ValidationResult.run_id)
Index("ix_claim_dup", Claim.patient_id, Claim.provider_id, Claim.service_date)
