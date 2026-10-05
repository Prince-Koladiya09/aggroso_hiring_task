from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_role
from app.approvals.validation import active_plan
from app.core.config import settings
from app.core.crypto import unseal
from app.db.models import Request, ProposedAction, Action, StaffUser, ActionAttempt
from app.db.session import get_db
from app.executor.executor import ActionExecutor

router = APIRouter(tags=["Actions Execution"])


class ExecuteScopeInput(BaseModel):
    scope: str
    inject_fault: Optional[str] = None   # before_write | after_write_before_commit  (only honoured when FAULT_INJECTION_ENABLED)


@router.get("/requests/{id}/actions")
def list_request_actions(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    plan = active_plan(db, id)
    if not plan:
        return []
    out = []
    for pa in db.query(ProposedAction).filter(ProposedAction.plan_id == plan.id).order_by(ProposedAction.created_at, ProposedAction.id).all():
        act = db.query(Action).filter(Action.proposed_action_id == pa.id).first()
        attempts = []
        if act:
            attempts = [{"attempt_no": a.attempt_no, "outcome": a.outcome, "error": a.error,
                         "started_at": a.started_at.isoformat() if a.started_at else None}
                        for a in db.query(ActionAttempt).filter(ActionAttempt.action_id == act.id).order_by(ActionAttempt.attempt_no, ActionAttempt.started_at).all()]
        out.append({
            "proposed_action_id": pa.id, "kind": pa.kind, "source": pa.source, "record_id": pa.record_id, "field": pa.field,
            "before_value": pa.before_value, "after_value": pa.after_value, "strategy": pa.strategy, "risk_text": pa.risk_text,
            "rule_ids": pa.rule_ids, "proposed_status": pa.status, "action_id": act.id if act else None,
            "action_status": act.status if act else "NOT_STARTED", "attempts": act.attempts if act else 0,
            "attempt_history": attempts, "idempotency_key": act.idempotency_key if act else None,
            # pre-image: Approver and Auditor only (FR-707), unsealed server-side
            "pre_image": unseal(act.pre_image) if act and user.role in ("approver", "auditor") else None,
            "result": act.result_json if act else None, "last_error": act.last_error if act else None})
    return out


@router.post("/requests/{id}/actions/execute")
def execute_scope_actions(id: str, payload: ExecuteScopeInput, db: Session = Depends(get_db),
                          user: StaffUser = Depends(require_role(["analyst"]))):
    fault = payload.inject_fault if settings.FAULT_INJECTION_ENABLED else None
    return ActionExecutor(db).execute_scope_actions(id, payload.scope.upper(), user.id, user.role, inject_fault=fault)


@router.post("/actions/{action_id}/retry")
def retry_action(action_id: str, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["analyst"]))):
    return ActionExecutor(db).retry_action(action_id, user.id, user.role)
