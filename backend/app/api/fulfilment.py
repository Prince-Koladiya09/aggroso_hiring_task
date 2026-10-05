from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_role
from app.db.models import FulfilmentRecord, StaffUser
from app.db.session import get_db
from app.records.fulfilment import FulfilmentRecordGenerator

router = APIRouter(prefix="/requests/{id}/fulfilment-record", tags=["Fulfilment Record"])


class GenerateRecordInput(BaseModel):
    narrative_override: Optional[str] = None     # human-written narrative
    narrative: Optional[str] = None              # the AI draft being confirmed
    narrative_source: Optional[str] = None       # AI_DRAFTED | DETERMINISTIC | HUMAN_EDITED
    confirm_narrative: bool = False


def _out(rec: FulfilmentRecord):
    return {"id": rec.id, "request_id": rec.request_id, "content": rec.content_json, "narrative": rec.narrative,
            "narrative_source": rec.narrative_source, "narrative_confirmed_by": rec.narrative_confirmed_by,
            "generated_at": rec.generated_at.isoformat() if rec.generated_at else None, "policy_version": rec.policy_version, "immutable": True}


@router.get("/draft")
def draft_narrative(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["analyst"]))):
    return FulfilmentRecordGenerator(db).draft_narrative(id)


@router.post("")
def generate_fulfilment_record(id: str, payload: Optional[GenerateRecordInput] = None, db: Session = Depends(get_db),
                               user: StaffUser = Depends(require_role(["analyst"]))):
    p = payload or GenerateRecordInput()
    if p.narrative_override:
        narrative, source = p.narrative_override, "HUMAN_EDITED"
    else:
        narrative, source = p.narrative, p.narrative_source
    rec, created = FulfilmentRecordGenerator(db).generate_record(id, user.id, user.role, narrative, source, p.confirm_narrative)
    return {**_out(rec), "created": created}


class AddendumInput(BaseModel):
    text: str


@router.post("/addendum")
def add_addendum(id: str, payload: AddendumInput, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["analyst", "approver"]))):
    """FR-1002: the record itself is immutable; later notes are separate, hash-chained audit events."""
    from app.core.errors import AppError
    from app.audit.logger import log_audit_event
    from app.db.models import Request
    rec = db.query(FulfilmentRecord).filter(FulfilmentRecord.request_id == id).first()
    if not rec:
        raise AppError("No fulfilment record exists yet; an addendum needs a generated record.", "NO_RECORD", 409)
    if len(payload.text.strip()) < 5:
        raise AppError("Addendum text is required (min. 5 characters).", "VALIDATION_ERROR", 422)
    req = db.query(Request).filter(Request.id == id).first()
    ev = log_audit_event(db, user.id, user.role, "FULFILMENT_ADDENDUM", "fulfilment_records",
                         {"record_id": rec.id, "text": payload.text.strip()}, req.correlation_id, id)
    db.commit()
    return {"addendum_event_seq": ev.seq, "record_unchanged": True}


@router.get("")
def get_fulfilment_record(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    rec = db.query(FulfilmentRecord).filter(FulfilmentRecord.request_id == id).first()
    if not rec:
        return {"record": None, "message": "Fulfilment record has not yet been generated for this request."}
    from app.db.models import AuditEvent
    adds = db.query(AuditEvent).filter(AuditEvent.request_id == id, AuditEvent.event_type == "FULFILMENT_ADDENDUM").order_by(AuditEvent.seq).all()
    return {**_out(rec), "addenda": [{"seq": a.seq, "by": a.actor_id, "at": a.at.isoformat(), "text": a.payload_json.get("text")} for a in adds]}
