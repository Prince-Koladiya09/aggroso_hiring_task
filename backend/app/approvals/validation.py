"""Approval validity (SRS 11.4) - shared by Approval Service, Action Executor and Tool Gateway.

An approval is valid only if:
  scope matches, decision is APPROVED, action_set_hash equals the current hash of the active
  actions in that scope, inventory_version equals the request's current inventory version,
  it has not expired, and (for DELETION) the approver differs from every initiator (POL-APR-3).
"""
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Set
from sqlalchemy.orm import Session
from app.db.models import Approval, Plan, ProposedAction, Request

INACTIVE_ACTION_STATUSES = ("BLOCKED", "REJECTED", "SUPERSEDED")


class ApprovalInvalidError(Exception):
    def __init__(self, message: str, code: str, rule_ids: Optional[List[str]] = None):
        self.code = code
        self.rule_ids = rule_ids or []
        super().__init__(message)


def compute_action_set_hash(actions: List[ProposedAction]) -> str:
    """Deterministic hash over the exact action set (kind, target, field, strategy, after-value)."""
    parts = []
    for a in sorted(actions, key=lambda a: (a.kind, a.source, a.record_id, a.field or "")):
        after_h = hashlib.sha256((a.after_value or "").encode()).hexdigest()
        parts.append(f"{a.kind}:{a.source}:{a.record_id}:{a.field or '*'}:{a.strategy}:{after_h}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def active_plan(db: Session, request_id: str) -> Optional[Plan]:
    return db.query(Plan).filter(Plan.request_id == request_id, Plan.status == "ACTIVE") \
        .order_by(Plan.version.desc()).first()


def scope_actions(db: Session, request_id: str, scope: str) -> List[ProposedAction]:
    """Actions of the ACTIVE plan in a scope that are eligible for approval/execution."""
    plan = active_plan(db, request_id)
    if not plan:
        return []
    return db.query(ProposedAction).filter(
        ProposedAction.request_id == request_id,
        ProposedAction.plan_id == plan.id,
        ProposedAction.kind == scope,
        ~ProposedAction.status.in_(INACTIVE_ACTION_STATUSES),
    ).order_by(ProposedAction.created_at, ProposedAction.id).all()


def approval_actions(db: Session, request_id: str, scope: str) -> List[ProposedAction]:
    """The exact action set an approval of `scope` is bound to. PLAN binds to every live action in the plan."""
    if scope == "PLAN":
        plan = active_plan(db, request_id)
        if not plan:
            return []
        return db.query(ProposedAction).filter(
            ProposedAction.plan_id == plan.id, ~ProposedAction.status.in_(INACTIVE_ACTION_STATUSES)).all()
    return scope_actions(db, request_id, scope)


def initiators(req: Request) -> Set[str]:
    return {u for u in (req.created_by, req.plan_initiated_by) if u}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_valid_approval(db: Session, req: Request, scope: str, ttl_hours: Optional[int] = None) -> Approval:
    """Return the latest valid approval for `scope` or raise ApprovalInvalidError."""
    if ttl_hours is None:
        from app.policy.loader import get_policy
        ttl_hours = get_policy().approvals.ttl_hours
    latest = db.query(Approval).filter(Approval.request_id == req.id, Approval.scope == scope) \
        .order_by(Approval.created_at.desc(), Approval.id.desc()).first()
    if latest is None or latest.decision != "APPROVED":
        raise ApprovalInvalidError(f"No valid {scope} approval exists for this request.", "APPROVAL_MISSING",
                                   ["POL-APR-2"])
    if _aware(latest.created_at) < datetime.now(timezone.utc) - timedelta(hours=ttl_hours):
        raise ApprovalInvalidError(f"The {scope} approval has expired; a fresh approval is required.",
                                   "APPROVAL_EXPIRED", ["POL-APR-2"])
    if latest.inventory_version != req.inventory_version:
        raise ApprovalInvalidError("Inventory changed after approval; approval is void (FR-503).",
                                   "INVENTORY_CHANGED", ["POL-APR-1"])
    current_hash = compute_action_set_hash(approval_actions(db, req.id, scope))
    if latest.action_set_hash != current_hash:
        raise ApprovalInvalidError("Action set changed since approval; approval is void (FR-703).",
                                   "ACTION_SET_TAMPERED", ["POL-APR-2"])
    if scope == "DELETION" and latest.approver_id in initiators(req):
        raise ApprovalInvalidError("Deletion approver must differ from the initiating analyst (POL-APR-3).",
                                   "FOUR_EYES_VIOLATION", ["POL-APR-3"])
    return latest
