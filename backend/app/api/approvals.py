from typing import List
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_role
from app.approvals.service import ApprovalService
from app.db.models import Approval, Request, StaffUser
from app.db.session import get_db

router = APIRouter(tags=["Approvals"])


class ApprovalInput(BaseModel):
    scope: str      # PLAN | CORRECTION | DELETION | EXTENSION   (export release: /export/{id}/release)
    decision: str   # APPROVED | REJECTED
    reason: str


def _row(a: Approval):
    return {"id": a.id, "scope": a.scope, "decision": a.decision, "approver_id": a.approver_id, "reason": a.reason,
            "action_set_hash": a.action_set_hash, "inventory_version": a.inventory_version,
            "created_at": a.created_at.isoformat() if a.created_at else None}


@router.get("/requests/{id}/approvals")
def list_request_approvals(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    return [_row(a) for a in db.query(Approval).filter(Approval.request_id == id).order_by(Approval.created_at.desc(), Approval.id.desc()).all()]


@router.post("/requests/{id}/approvals")
def submit_approval(id: str, payload: ApprovalInput, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["approver"]))):
    appr = ApprovalService(db).submit_approval(id, payload.scope, payload.decision, payload.reason, user.id, user.role)
    req = db.query(Request).filter(Request.id == id).first()
    return {**_row(appr), "request_status": req.status}


@router.get("/approvals/queue")
def get_approvals_queue(db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["approver"]))):
    labels = {"PLAN_REVIEW": "Plan approval", "AWAITING_ACTION_APPROVAL": "Action approval", "EXPORT_REVIEW": "Export release"}
    reqs = db.query(Request).filter((Request.status.in_(list(labels))) | (Request.extension_pending == True)).order_by(Request.due_at).all()  # noqa: E712
    out = []
    for r in reqs:
        needs = labels.get(r.status, "")
        if r.extension_pending:
            needs = (needs + " + " if needs else "") + "Extension decision"
        out.append({"id": r.id, "type": r.type, "status": r.status, "needs": needs, "requester_name": r.requester_name,
                    "requester_email": r.requester_email, "created_by": r.created_by, "plan_initiated_by": r.plan_initiated_by,
                    "own_initiated": user.id in {r.created_by, r.plan_initiated_by},
                    "due_at": r.due_at.isoformat() if r.due_at else None})
    return out
