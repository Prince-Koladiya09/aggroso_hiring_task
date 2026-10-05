from typing import Set, Dict, Optional
from sqlalchemy.orm import Session
from app.db.models import Request
from app.audit.logger import log_audit_event

class InvalidStateTransitionError(Exception):
    def __init__(self, current_status: str, target_status: str, message: Optional[str] = None):
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(message or f"Illegal state transition from {current_status} to {target_status}")

# Valid state machine transitions per PRD Section 6.1
ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    "NEW": {"AWAITING_INFO", "VERIFICATION_PENDING", "CANCELLED"},
    "AWAITING_INFO": {"VERIFICATION_PENDING", "CANCELLED"},
    "VERIFICATION_PENDING": {"VERIFIED", "VERIFICATION_FAILED"},
    "VERIFICATION_FAILED": {"VERIFICATION_PENDING", "REJECTED", "CANCELLED"},
    "VERIFIED": {"PLANNING"},
    "PLANNING": {"PLAN_REVIEW", "PLANNING_FAILED"},
    "PLANNING_FAILED": {"PLANNING"},
    "PLAN_REVIEW": {"PLANNING", "PLAN_APPROVED", "REJECTED"},
    "PLAN_APPROVED": {"EXPORT_REVIEW", "AWAITING_ACTION_APPROVAL", "PLAN_REVIEW"},
    "AWAITING_ACTION_APPROVAL": {"EXECUTING", "PLAN_REVIEW"},
    "EXECUTING": {"COMPLETED_PENDING_RECORD", "PARTIALLY_FAILED"},
    "PARTIALLY_FAILED": {"EXECUTING"},
    "EXPORT_REVIEW": {"COMPLETED_PENDING_RECORD", "PLAN_REVIEW"},   # PLAN_REVIEW: inventory changed (FR-503)
    "COMPLETED_PENDING_RECORD": {"CLOSED"},
    "REJECTED": set(),
    "CANCELLED": set(),
    "CLOSED": set()
}

TERMINAL_STATES = {"CLOSED", "REJECTED", "CANCELLED"}

def can_transition(current_status: str, target_status: str) -> bool:
    return target_status in ALLOWED_TRANSITIONS.get(current_status, set())

def transition_state(
    request: Request,
    target_status: str,
    actor_id: str,
    actor_role: str,
    reason: str,
    db: Session
) -> Request:
    if not can_transition(request.status, target_status):
        raise InvalidStateTransitionError(request.status, target_status)

    old_status = request.status
    request.status = target_status

    log_audit_event(
        db=db,
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="REQUEST_STATUS_CHANGED",
        entity="requests",
        payload={
            "request_id": request.id,
            "old_status": old_status,
            "new_status": target_status,
            "reason": reason
        },
        correlation_id=request.correlation_id,
        request_id=request.id
    )

    return request
