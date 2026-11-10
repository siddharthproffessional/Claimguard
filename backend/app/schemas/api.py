from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LineCreate(BaseModel):
    procedure_code: str = Field(min_length=1, max_length=20)
    diagnosis_codes: list[str] = Field(min_length=1)
    units: int = Field(ge=1, le=999)
    unit_price: float = Field(ge=0)
    amount: float = Field(ge=0)


class ClaimCreate(BaseModel):
    control_number: str = Field(min_length=1, max_length=40)
    patient_id: str
    provider_id: str
    payer_id: str
    policy_number: str | None = None
    member_id: str | None = None
    patient_dob: str | None = None
    service_date: str
    submitted_date: str
    place_of_service: str | None = None
    claim_type: str = "professional"
    total_amount: float = Field(ge=0)
    authorization_number: str | None = None
    attached_document_ids: list[str] = Field(default_factory=list)
    lines: list[LineCreate] = Field(min_length=1)

    @field_validator("service_date", "submitted_date", "patient_dob")
    @classmethod
    def iso_date(cls, v):
        if v is None:
            return v
        from datetime import date
        date.fromisoformat(v)
        return v


class ApproveBody(BaseModel):
    edited_value: Any = None
    note: str | None = Field(default=None, max_length=500)


class RejectBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class SimulationRequest(BaseModel):
    seed: int = Field(default=42, ge=0, le=10 ** 9)
    ai_depth: Literal["none", "synthesis", "full"] | None = None
    # manual: proposals wait for the operator. simulated_approve: a labelled simulated operator approves
    # every proposal that passed deterministic dry-run validation (for the benchmark only).
    operator_mode: Literal["manual", "simulated_approve"] = "manual"


class LoadRequest(BaseModel):
    seed: int = Field(default=42, ge=0, le=10 ** 9)


class AnalyzeRequest(BaseModel):
    ai_depth: Literal["none", "synthesis", "full"] | None = None
