from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.audit.chain import verify_chain
from app.db.models import AuditEvent, StaffUser
from app.db.session import get_db

router = APIRouter(tags=["Audit Trail"])
# Read-only: there are deliberately NO update/delete endpoints (FR-901).


def _row(e: AuditEvent, with_request=False):
    d = {"id": e.id, "seq": e.seq, "event_type": e.event_type, "actor_id": e.actor_id, "actor_role": e.actor_role, "entity": e.entity,
         "payload": e.payload_json, "prev_hash": e.prev_hash, "hash": e.hash, "correlation_id": e.correlation_id,
         "timestamp": e.at.isoformat() if e.at else None}
    if with_request:
        d["request_id"] = e.request_id
    return d


@router.get("/requests/{id}/audit")
def get_request_audit_trail(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    return [_row(e) for e in db.query(AuditEvent).filter(AuditEvent.request_id == id).order_by(AuditEvent.seq.asc()).all()]


@router.get("/audit/all")
def get_all_audit_events(limit: int = Query(200, le=1000), db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    return [_row(e, True) for e in db.query(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit).all()]


@router.get("/audit/verify")
def verify_audit_hash_chain(db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    events = db.query(AuditEvent).order_by(AuditEvent.seq.asc()).all()
    ok, error, broken = verify_chain(events)
    return {"is_valid": ok, "total_events_checked": len(events), "error": error, "broken_seq": broken, "verified_by_role": user.role}
