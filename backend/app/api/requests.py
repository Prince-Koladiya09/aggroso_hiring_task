import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_role
from app.approvals.service import ApprovalService
from app.core.errors import AppError
from app.db.models import Request, StaffUser, AuditEvent, Approval
from app.db.session import get_db
from app.policy.loader import get_policy
from app.workflow.deadline import compute_deadline_state, calculate_initial_due_date
from app.workflow.missing_info import missing_verification_items
from app.workflow.state_machine import transition_state, TERMINAL_STATES
from app.audit.logger import log_audit_event

router = APIRouter(prefix="/requests", tags=["Requests"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CreateRequestInput(BaseModel):
    type: str = Field(description="ACCESS, CORRECTION, DELETION, UNSUPPORTED")
    requester_name: str = Field(min_length=2, max_length=128)
    requester_email: str
    account_id: Optional[str] = None
    relationship: str = "self"
    description: str = Field(min_length=5, max_length=4000)
    received_at: Optional[datetime] = None
    authorization_on_file: bool = False

    @field_validator("type")
    @classmethod
    def _t(cls, v):
        v = v.upper()
        if v not in ("ACCESS", "CORRECTION", "DELETION", "UNSUPPORTED"):
            raise ValueError("must be ACCESS, CORRECTION, DELETION or UNSUPPORTED")
        return v

    @field_validator("relationship")
    @classmethod
    def _r(cls, v):
        if v not in ("self", "authorized_agent"):
            raise ValueError("must be 'self' or 'authorized_agent'")
        return v

    @field_validator("requester_email")
    @classmethod
    def _e(cls, v):
        if not EMAIL_RE.match(v.strip()):
            raise ValueError("must be a valid e-mail address")
        return v.strip().lower()


class SupplyInfoInput(BaseModel):
    account_id: Optional[str] = None
    authorization_on_file: Optional[bool] = None
    description: Optional[str] = None


class ReasonInput(BaseModel):
    reason: str = Field(min_length=5)


def _summary(r: Request, policy, now) -> dict:
    dl = compute_deadline_state(r.received_at, r.due_at, r.status, policy, now)
    return {"id": r.id, "type": r.type, "status": r.status, "requester_name": r.requester_name,
            "requester_email": r.requester_email, "account_id": r.account_id, "relationship": r.relationship,
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "due_at": r.due_at.isoformat() if r.due_at else None, "extended": r.extended,
            "extension_pending": r.extension_pending, "inventory_version": r.inventory_version,
            "correlation_id": r.correlation_id, "created_by": r.created_by, "deadline": dl}


def _next_id(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    nums = [int(m.group(1)) for (rid,) in db.query(Request.id).all()
            if (m := re.match(rf"^REQ-{year}-(\d+)$", rid))]
    return f"REQ-{year}-{(max(nums) + 1 if nums else 1):04d}"


@router.get("")
def list_requests(status_filter: Optional[str] = Query(None, alias="status"), type_filter: Optional[str] = Query(None, alias="type"),
                  deadline_filter: Optional[str] = Query(None, alias="deadline"), sort: str = "created",
                  db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    q = db.query(Request)
    if status_filter:
        q = q.filter(Request.status == status_filter)
    if type_filter:
        q = q.filter(Request.type == type_filter)
    policy, now = get_policy(), datetime.now(timezone.utc)
    rows = [_summary(r, policy, now) for r in q.all()]
    if deadline_filter:
        rows = [r for r in rows if r["deadline"]["deadline_status"] == deadline_filter]
    rows.sort(key=(lambda r: r["due_at"] or "") if sort == "due" else (lambda r: r["received_at"] or ""), reverse=(sort != "due"))
    return rows


@router.post("", status_code=status.HTTP_201_CREATED)
def create_request(payload: CreateRequestInput, db: Session = Depends(get_db),
                   user: StaffUser = Depends(require_role(["analyst"]))):
    policy, now = get_policy(), datetime.now(timezone.utc)
    received = payload.received_at or now
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    if received > now:
        raise AppError("Received date cannot be in the future.", "VALIDATION_ERROR", 422,
                       fields=[{"field": "received_at", "message": "cannot be in the future"}])
    corr = f"corr-{uuid.uuid4().hex[:8]}"
    req = Request(id=_next_id(db), type=payload.type, status="NEW", requester_name=payload.requester_name.strip(),
                  requester_email=payload.requester_email, account_id=(payload.account_id or "").strip() or None,
                  relationship=payload.relationship, description=payload.description.strip(), received_at=received,
                  due_at=calculate_initial_due_date(received, policy), extended=False, correlation_id=corr,
                  created_by=user.id, authorization_on_file=payload.authorization_on_file)
    db.add(req)
    db.flush()
    missing = [m for m in missing_verification_items(db, req) if m["item"] != "one_time_code"]
    if missing:
        transition_state(req, "AWAITING_INFO", user.id, user.role,
                         "Required identifiers missing: " + ", ".join(m["item"] for m in missing), db)
    log_audit_event(db, user.id, user.role, "REQUEST_CREATED", "requests",
                    {"request_id": req.id, "type": req.type, "requester_email": req.requester_email,
                     "received_at": received.isoformat(), "due_at": req.due_at.isoformat(),
                     "missing": [m["item"] for m in missing]}, corr, req.id)
    db.commit()
    db.refresh(req)
    return {**_summary(req, policy, now), "missing_verification": missing_verification_items(db, req)}


@router.get("/{id}")
def get_request_detail(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    r = db.query(Request).filter(Request.id == id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    policy, now = get_policy(), datetime.now(timezone.utc)
    events = db.query(AuditEvent).filter(AuditEvent.request_id == id).order_by(AuditEvent.seq.asc()).all()
    timeline = [{"seq": e.seq, "event_type": e.event_type, "actor_id": e.actor_id, "actor_role": e.actor_role,
                 "timestamp": e.at.isoformat() if e.at else None, "payload": e.payload_json}
                for e in events if e.event_type in ("REQUEST_STATUS_CHANGED", "REQUEST_CREATED", "DEADLINE_EXTENDED", "EXTENSION_REQUESTED",
                                                    "VERIFICATION_PASSED", "VERIFICATION_FAILED", "FULFILMENT_RECORD_GENERATED")
                or e.event_type.startswith("APPROVAL_")]
    return {**_summary(r, policy, now), "description": r.description, "extension_reason": r.extension_reason,
            "extension_request_reason": r.extension_request_reason, "subject_profile_id": r.subject_profile_id,
            "authorization_on_file": r.authorization_on_file, "plan_initiated_by": r.plan_initiated_by,
            "missing_verification": missing_verification_items(db, r), "timeline": timeline, "disclaimer": policy.disclaimer}


@router.patch("/{id}/info")
def supply_missing_info(id: str, payload: SupplyInfoInput, db: Session = Depends(get_db),
                        user: StaffUser = Depends(require_role(["analyst"]))):
    """AWAITING_INFO -> VERIFICATION_PENDING once the missing identifiers are supplied (FR-205)."""
    r = db.query(Request).filter(Request.id == id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    if r.status not in ("NEW", "AWAITING_INFO"):
        raise AppError(f"Information can only be supplied before verification (status: {r.status}).", "INVALID_STATE", 409)
    if payload.account_id is not None:
        r.account_id = payload.account_id.strip() or None
    if payload.authorization_on_file is not None:
        r.authorization_on_file = payload.authorization_on_file
    if payload.description:
        r.description = payload.description.strip()
    missing = [m for m in missing_verification_items(db, r) if m["item"] != "one_time_code"]
    log_audit_event(db, user.id, user.role, "REQUEST_INFO_SUPPLIED", "requests",
                    {"still_missing": [m["item"] for m in missing]}, r.correlation_id, r.id)
    if not missing and r.status == "AWAITING_INFO":
        transition_state(r, "VERIFICATION_PENDING", user.id, user.role, "Missing information supplied.", db)
    db.commit()
    return {"status": r.status, "missing_verification": missing_verification_items(db, r)}


@router.post("/{id}/reject")
def reject_request(id: str, payload: ReasonInput, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["analyst"]))):
    r = db.query(Request).filter(Request.id == id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    transition_state(r, "REJECTED", user.id, user.role, f"Closed by analyst after failed verification: {payload.reason}", db)
    db.commit()
    return {"status": r.status}


@router.post("/{id}/cancel")
def cancel_request(id: str, payload: ReasonInput, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["analyst"]))):
    r = db.query(Request).filter(Request.id == id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    transition_state(r, "CANCELLED", user.id, user.role, f"Cancelled: {payload.reason}", db)
    db.commit()
    return {"status": r.status}


@router.post("/{id}/extension")
def request_or_decide_extension(id: str, payload: dict, db: Session = Depends(get_db),
                                user: StaffUser = Depends(require_role(["analyst", "approver"]))):
    """Analyst/Approver requests (`{"reason": ...}`); Approver decides (`{"decision": "APPROVED|REJECTED", "reason": ...}`)."""
    svc = ApprovalService(db)
    reason = str(payload.get("reason", ""))
    if payload.get("decision"):
        if user.role != "approver":
            raise HTTPException(status_code=403, detail="Only an Approver can decide an extension.")
        decision = str(payload["decision"]).upper()
        if decision not in ("APPROVED", "REJECTED"):
            raise AppError("decision must be APPROVED or REJECTED", "VALIDATION_ERROR", 422)
        if len(reason.strip()) < 5:
            raise AppError("A justification is required.", "REASON_REQUIRED", 422)
        a = svc.decide_extension(id, decision, reason.strip(), user.id, user.role)
        r = db.query(Request).filter(Request.id == id).first()
        return {"decision": a.decision, "extended": r.extended, "new_due_at": r.due_at.isoformat()}
    r = svc.request_extension(id, reason, user.id, user.role)
    return {"message": "Extension requested; awaiting Approver decision.", "extension_pending": r.extension_pending}
