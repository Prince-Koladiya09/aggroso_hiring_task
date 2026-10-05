import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.models import AuditEvent
from app.audit.chain import compute_audit_hash
from app.core.logging import logger

GENESIS = "0" * 64


def log_audit_event(
    db: Session,
    actor_id: str,
    actor_role: str,
    event_type: str,
    entity: str,
    payload: Dict[str, Any],
    correlation_id: str,
    request_id: Optional[str] = None,
) -> AuditEvent:
    """Append-only audit event with hash chaining. Caller commits the transaction."""
    now = datetime.now(timezone.utc)
    last_seq = db.query(func.max(AuditEvent.seq)).scalar() or 0
    prev_hash = GENESIS
    if last_seq:
        prev_hash = db.query(AuditEvent.hash).filter(AuditEvent.seq == last_seq).scalar() or GENESIS
    next_seq = last_seq + 1
    current_hash = compute_audit_hash(prev_hash, next_seq, event_type, payload, now,
                                      actor_id=actor_id, request_id=request_id)
    event = AuditEvent(
        id=f"aud_{uuid.uuid4().hex[:12]}", seq=next_seq, request_id=request_id, actor_id=actor_id,
        actor_role=actor_role, event_type=event_type, entity=entity, payload_json=payload,
        prev_hash=prev_hash, hash=current_hash, correlation_id=correlation_id, at=now,
    )
    db.add(event)
    db.flush()
    logger.info("audit_event", component="audit", audit_event=event_type, request_id=request_id,
                actor=actor_id, correlation_id=correlation_id, seq=next_seq)
    return event
