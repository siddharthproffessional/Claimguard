"""Claim snapshots, patches and versioning.

The relational claim row always holds the *current* working state. Every state is also stored as an
immutable ClaimVersion snapshot; version 1 is the original submission and is never rewritten.
"""
import copy

from app.models import models as m

SNAPSHOT_FIELDS = ["control_number", "patient_id", "provider_id", "payer_id", "policy_number", "member_id",
                   "patient_dob", "service_date", "submitted_date", "place_of_service", "claim_type", "total_amount",
                   "authorization_number", "attached_document_ids"]
LINE_FIELDS = ["line_no", "procedure_code", "diagnosis_codes", "units", "unit_price", "amount"]
# Only administrative fields may be changed through the correction workflow.
EDITABLE_FIELDS = {"policy_number": str, "member_id": str, "patient_dob": str, "place_of_service": str,
                   "total_amount": (int, float), "authorization_number": str}
EDITABLE_LINE_FIELDS = {"procedure_code": str, "diagnosis_codes": list, "units": int, "amount": (int, float)}


class CorrectionError(ValueError):
    pass


def snapshot(claim: m.Claim) -> dict:
    snap = {f: copy.deepcopy(getattr(claim, f)) for f in SNAPSHOT_FIELDS}
    snap["attached_document_ids"] = list(snap["attached_document_ids"] or [])
    snap["claim_id"] = claim.id
    snap["seq"] = claim.seq
    snap["lines"] = [{f: copy.deepcopy(getattr(ln, f)) for f in LINE_FIELDS} for ln in claim.lines]
    return snap


def apply_patch(snap: dict, op: str, field: str | None, value, line_no: int | None = None, ref=None) -> dict:
    """Return a patched copy of a snapshot. Raises CorrectionError for anything outside the allow-list."""
    new = copy.deepcopy(snap)
    if op == "set_field":
        if field not in EDITABLE_FIELDS:
            raise CorrectionError(f"Field '{field}' cannot be changed through a correction")
        if value is None or value == "" or isinstance(value, bool) or not isinstance(value, EDITABLE_FIELDS[field]):
            raise CorrectionError(f"Invalid value for '{field}'")
        new[field] = value
    elif op == "set_line_field":
        if field not in EDITABLE_LINE_FIELDS:
            raise CorrectionError(f"Line field '{field}' cannot be changed through a correction")
        line = next((l for l in new["lines"] if l["line_no"] == line_no), None)
        if line is None:
            raise CorrectionError(f"Claim has no line {line_no}")
        if value is None or isinstance(value, bool) or not isinstance(value, EDITABLE_LINE_FIELDS[field]):
            raise CorrectionError(f"Invalid value for line field '{field}'")
        if field == "diagnosis_codes" and (not value or not all(isinstance(v, str) and v for v in value)):
            raise CorrectionError("diagnosis_codes must be a non-empty list of codes")
        line[field] = value
    elif op == "attach_document":
        if not isinstance(value, str):
            raise CorrectionError("attach_document needs a document id")
        if ref is not None:
            doc = ref.documents.get(value)
            if not doc:
                raise CorrectionError(f"Document {value} does not exist in the repository")
            if doc["patient_id"] != snap["patient_id"]:
                raise CorrectionError(f"Document {value} belongs to a different patient")
        if value not in new["attached_document_ids"]:
            new["attached_document_ids"].append(value)
    else:
        raise CorrectionError(f"Unknown correction operation '{op}'")
    return new


def write_snapshot(db, claim: m.Claim, snap: dict, reason: str, actor: str):
    """Persist a new working state as version n+1. Earlier versions are left untouched."""
    for f in SNAPSHOT_FIELDS:
        setattr(claim, f, copy.deepcopy(snap[f]))
    existing = {ln.line_no: ln for ln in claim.lines}
    for l in snap["lines"]:
        row = existing.get(l["line_no"])
        if row is None:
            claim.lines.append(m.ClaimLineItem(**l))
        else:
            for f in LINE_FIELDS:
                setattr(row, f, copy.deepcopy(l[f]))
    claim.version = (claim.version or 1) + 1
    stored = copy.deepcopy(snap)
    db.add(m.ClaimVersion(claim_id=claim.id, version=claim.version, snapshot=stored, reason=reason, actor=actor))
    db.flush()
    return claim.version


def original_snapshot(db, claim_id: str) -> dict | None:
    v = db.query(m.ClaimVersion).filter_by(claim_id=claim_id, version=1).first()
    return v.snapshot if v else None
