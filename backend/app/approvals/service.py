import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.errors import AppError
from app.core.logging import log_approval
from app.db.models import Request, Approval, ProposedAction, InventoryItem
from app.workflow.state_machine import transition_state, TERMINAL_STATES
from app.workflow.deadline import calculate_extended_due_date
from app.audit.logger import log_audit_event
from app.policy.loader import get_policy
from app.policy.engine import PolicyEngine
from app.approvals.validation import (
    compute_action_set_hash, active_plan, scope_actions, approval_actions, initiators, INACTIVE_ACTION_STATUSES,
)

__all__ = ["ApprovalService", "ApprovalValidationError", "compute_action_set_hash"]

VALID_DECISIONS = {"INCLUDE", "REDACT", "EXCLUDE_RETENTION", "EXCLUDE_UNRELATED", "NEEDS_REVIEW"}
POST_PLAN_STATES = ["PLAN_APPROVED", "AWAITING_ACTION_APPROVAL", "EXPORT_REVIEW"]


class ApprovalValidationError(AppError):
    STATUS = {"FOUR_EYES_VIOLATION": 403, "ROLE_REQUIRED": 403, "INVALID_STATE": 409, "NOT_FOUND": 404}

    def __init__(self, message: str, code: str = "APPROVAL_VALIDATION_ERROR", rule_ids: Optional[List[str]] = None):
        super().__init__(message, code, self.STATUS.get(code, 400), rule_ids)


def reset_actions_to_proposed(db: Session, req: Request) -> None:
    plan = active_plan(db, req.id)
    if not plan:
        return
    for pa in db.query(ProposedAction).filter(ProposedAction.plan_id == plan.id,
                                              ProposedAction.status == "APPROVED").all():
        pa.status = "PROPOSED"


class ApprovalService:
    def __init__(self, db: Session):
        self.db = db
        self.policy = get_policy()
        self.engine = PolicyEngine(self.policy)

    # ------------------------------------------------------------------ approvals
    def submit_approval(self, request_id: str, scope: str, decision: str, reason: str,
                        approver_id: str, approver_role: str) -> Approval:
        scope, decision = (scope or "").upper(), (decision or "").upper()
        if approver_role != "approver":
            raise ApprovalValidationError("Only staff with the Approver role can grant approvals.", "ROLE_REQUIRED")
        if scope not in ("PLAN", "CORRECTION", "DELETION", "EXTENSION"):
            raise ApprovalValidationError(
                "Scope must be PLAN, CORRECTION, DELETION or EXTENSION (export release has its own endpoint).",
                "INVALID_SCOPE")
        if decision not in ("APPROVED", "REJECTED"):
            raise ApprovalValidationError("Decision must be APPROVED or REJECTED.", "INVALID_DECISION")
        if not reason or len(reason.strip()) < 5:
            raise ApprovalValidationError("A meaningful justification (min. 5 characters) is required.", "REASON_REQUIRED")

        req = self.db.query(Request).filter(Request.id == request_id).first()
        if not req:
            raise ApprovalValidationError(f"Request {request_id} not found", "NOT_FOUND")

        if scope == "EXTENSION":
            return self.decide_extension(request_id, decision, reason.strip(), approver_id, approver_role)

        self._check_state_for_scope(req, scope)

        if scope == "DELETION" and decision == "APPROVED" and approver_id in initiators(req):
            raise ApprovalValidationError(
                "Four-eyes violation (POL-APR-3): the approver of a deletion must differ from the analyst who initiated it.",
                "FOUR_EYES_VIOLATION", ["POL-APR-3"])

        actions = approval_actions(self.db, request_id, scope)
        if decision == "APPROVED":
            self._check_approvable(req, scope, actions)
        action_hash = compute_action_set_hash(actions)

        approval = Approval(
            id=f"appr_{uuid.uuid4().hex[:12]}", request_id=request_id, scope=scope, decision=decision,
            approver_id=approver_id, reason=reason.strip(), action_set_hash=action_hash,
            inventory_version=req.inventory_version)
        self.db.add(approval)
        self.db.flush()

        if decision == "REJECTED":
            if scope == "PLAN":
                transition_state(req, "REJECTED", approver_id, approver_role, f"Plan rejected: {reason}", self.db)
            else:
                reset_actions_to_proposed(self.db, req)
                transition_state(req, "PLAN_REVIEW", approver_id, approver_role,
                                 f"{scope} approval denied: {reason}", self.db)
        else:
            if scope == "PLAN":
                transition_state(req, "PLAN_APPROVED", approver_id, approver_role, f"Plan approved: {reason}", self.db)
                target = "EXPORT_REVIEW" if req.type == "ACCESS" else "AWAITING_ACTION_APPROVAL"
                transition_state(req, target, approver_id, approver_role, f"Proceeding to {target}", self.db)
            else:
                for pa in actions:
                    pa.status = "APPROVED"
                transition_state(req, "EXECUTING", approver_id, approver_role,
                                 f"{scope} actions approved: {reason}", self.db)

        log_audit_event(self.db, approver_id, approver_role, f"APPROVAL_{scope}_{decision}", "approvals", {
            "approval_id": approval.id, "scope": scope, "decision": decision, "reason": reason.strip(),
            "action_set_hash": action_hash, "inventory_version": req.inventory_version,
            "action_count": len(actions)}, req.correlation_id, req.id)
        log_approval(scope=scope, decision=decision, request_id=req.id, approver=approver_id)
        self.db.commit()
        return approval

    def _plan_actions(self, req: Request) -> List[ProposedAction]:
        plan = active_plan(self.db, req.id)
        if not plan:
            return []
        return self.db.query(ProposedAction).filter(
            ProposedAction.plan_id == plan.id, ~ProposedAction.status.in_(INACTIVE_ACTION_STATUSES)).all()

    def _check_state_for_scope(self, req: Request, scope: str) -> None:
        if scope == "PLAN" and req.status != "PLAN_REVIEW":
            raise ApprovalValidationError(f"Plan can only be decided in PLAN_REVIEW (current: {req.status}).", "INVALID_STATE")
        if scope in ("CORRECTION", "DELETION"):
            if req.status != "AWAITING_ACTION_APPROVAL":
                raise ApprovalValidationError(
                    f"{scope} approval requires status AWAITING_ACTION_APPROVAL (current: {req.status}). "
                    "An approved plan alone does not authorise modifications (POL-APR-2).", "INVALID_STATE", ["POL-APR-2"])
            if req.type != scope:
                raise ApprovalValidationError(
                    f"A {req.type} request cannot be approved with a {scope} approval (POL-APR-2).",
                    "SCOPE_MISMATCH", ["POL-APR-2"])

    def _check_approvable(self, req: Request, scope: str, actions: List[ProposedAction]) -> None:
        if scope == "PLAN":
            plan = active_plan(self.db, req.id)
            if not plan:
                raise ApprovalValidationError("No active plan exists to approve.", "NO_PLAN")
            if (plan.interpretation_json or {}).get("request_type") == "UNSUPPORTED":
                raise ApprovalValidationError(
                    "This request type is UNSUPPORTED and is routed to manual triage; reject the plan instead.",
                    "UNSUPPORTED_REQUEST_TYPE")
            pending = self.db.query(InventoryItem).filter(
                InventoryItem.request_id == req.id, InventoryItem.inventory_version == req.inventory_version,
                InventoryItem.decision == "NEEDS_REVIEW").count()
            if pending:
                raise ApprovalValidationError(
                    f"{pending} inventory item(s) are NEEDS_REVIEW; a human must decide each before plan approval.",
                    "INVENTORY_UNRESOLVED", ["POL-APR-1"])
            if req.type in ("CORRECTION", "DELETION") and not actions:
                raise ApprovalValidationError(
                    "The plan contains no actionable items (everything is excluded or nothing was derived). "
                    "Reject the plan or request changes.", "NO_ACTIONABLE_ITEMS")
        else:
            if not actions:
                raise ApprovalValidationError(f"There are no {scope} actions to approve.", "NO_ACTIONS")

    # ------------------------------------------------------------------ inventory override
    def override_inventory_item(self, request_id: str, item_id: str, new_decision: str, reason: str,
                                actor_id: str, actor_role: str) -> InventoryItem:
        new_decision = (new_decision or "").upper()
        if actor_role not in ("analyst", "approver"):
            raise ApprovalValidationError("Only Analysts and Approvers can override inventory decisions.", "ROLE_REQUIRED")
        if new_decision not in VALID_DECISIONS:
            raise ApprovalValidationError(f"Decision must be one of {sorted(VALID_DECISIONS)}.", "INVALID_DECISION")
        if not reason or len(reason.strip()) < 5:
            raise ApprovalValidationError("A justification reason (min. 5 characters) is required to override.", "REASON_REQUIRED")

        req = self.db.query(Request).filter(Request.id == request_id).first()
        if not req:
            raise ApprovalValidationError("Request not found", "NOT_FOUND")
        if req.status not in ["PLAN_REVIEW"] + POST_PLAN_STATES:
            raise ApprovalValidationError(
                f"Inventory can only be changed during plan review (current status: {req.status}).", "INVALID_STATE")

        item = self.db.query(InventoryItem).filter(
            InventoryItem.request_id == request_id, InventoryItem.id == item_id,
            InventoryItem.inventory_version == req.inventory_version).first()
        if not item:
            raise ApprovalValidationError("Inventory item not found in the current inventory version.", "NOT_FOUND")

        # Overrides can never weaken a deterministic exclusion (FR-502).
        raw = item.raw_data_json or {}
        if req.type in ("DELETION", "CORRECTION") and new_decision in ("INCLUDE", "REDACT"):
            _, det_decision, rules, why = self.engine.classify_record_decision(item.source, raw, req.type, True)
            if det_decision == "EXCLUDE_RETENTION":
                raise ApprovalValidationError(
                    f"Override refused: {why}", "RETENTION_VIOLATION", rules)
        if new_decision == "EXCLUDE_RETENTION":
            _, det_decision, rules, why = self.engine.classify_record_decision(item.source, raw, req.type or "DELETION", True)
            if det_decision != "EXCLUDE_RETENTION":
                raise ApprovalValidationError(
                    "EXCLUDE_RETENTION can only be set by deterministic policy; choose EXCLUDE_UNRELATED instead.",
                    "INVALID_DECISION")

        old_decision = item.decision
        item.decision = new_decision
        item.override_by = actor_id
        item.override_reason = reason.strip()
        item.rule_ids = self.engine.validate_rule_ids((item.rule_ids or []) + ["POL-APR-1"])

        self._sync_actions_for_item(req, item)

        # FR-503: any inventory change creates a new inventory version and voids earlier approvals.
        req.inventory_version += 1
        for it in self.db.query(InventoryItem).filter(InventoryItem.request_id == req.id,
                                                      InventoryItem.inventory_version == req.inventory_version - 1).all():
            it.inventory_version = req.inventory_version

        reset_actions_to_proposed(self.db, req)
        if req.status in POST_PLAN_STATES:
            transition_state(req, "PLAN_REVIEW", actor_id, actor_role,
                             "Inventory was modified after plan approval; approvals void, returned to PLAN_REVIEW.", self.db)

        log_audit_event(self.db, actor_id, actor_role, "INVENTORY_OVERRIDE", "inventory_items", {
            "item_id": item.id, "source": item.source, "record_id": item.record_id,
            "old_decision": old_decision, "new_decision": new_decision, "reason": reason.strip(),
            "new_inventory_version": req.inventory_version}, req.correlation_id, request_id)
        self.db.commit()
        return item

    def _sync_actions_for_item(self, req: Request, item: InventoryItem) -> None:
        """Keep the proposed-action set consistent with reviewer overrides."""
        if req.type not in ("DELETION", "CORRECTION"):
            return
        plan = active_plan(self.db, req.id)
        if not plan:
            return
        scope = req.type
        existing = self.db.query(ProposedAction).filter(
            ProposedAction.plan_id == plan.id, ProposedAction.source == item.source,
            ProposedAction.record_id == item.record_id, ProposedAction.kind == scope).all()
        if item.decision == "INCLUDE":
            if existing:
                for pa in existing:
                    if pa.status in ("BLOCKED", "REJECTED"):
                        pa.status = "PROPOSED"
            elif scope == "DELETION":
                strategy = self.engine.strategy_for(item.source)
                self.db.add(ProposedAction(
                    id=f"pact_{uuid.uuid4().hex[:12]}", request_id=req.id, plan_id=plan.id, kind="DELETION",
                    source=item.source, record_id=item.record_id, field="*", before_value="existing_record",
                    after_value=None, strategy=strategy,
                    risk_text=f"Added by reviewer override: permanent {strategy} of {item.record_id} in {item.source}.",
                    rule_ids=["POL-APR-2"], status="PROPOSED"))
        else:
            for pa in existing:
                if pa.status in ("PROPOSED", "APPROVED"):
                    pa.status = "BLOCKED"
                    pa.rule_ids = self.engine.validate_rule_ids((pa.rule_ids or []) + (item.rule_ids or []))

    # ------------------------------------------------------------------ extension (POL-SLA-2)
    def request_extension(self, request_id: str, reason: str, actor_id: str, actor_role: str) -> Request:
        if actor_role not in ("analyst", "approver"):
            raise ApprovalValidationError("Only Analysts and Approvers can request an extension.", "ROLE_REQUIRED")
        req = self.db.query(Request).filter(Request.id == request_id).first()
        if not req:
            raise ApprovalValidationError("Request not found", "NOT_FOUND")
        if req.status in TERMINAL_STATES or req.status in ("COMPLETED_PENDING_RECORD",):
            raise ApprovalValidationError("An extension cannot be requested for a finished request.", "INVALID_STATE")
        if req.extended:
            raise ApprovalValidationError("Only one extension is allowed (POL-SLA-2).", "EXTENSION_ALREADY_USED", ["POL-SLA-2"])
        if req.extension_pending:
            raise ApprovalValidationError("An extension request is already awaiting Approver decision.", "EXTENSION_PENDING")
        if not reason or len(reason.strip()) < 5:
            raise ApprovalValidationError("A justification is required to request an extension.", "REASON_REQUIRED")
        req.extension_pending = True
        req.extension_request_reason = reason.strip()
        req.extension_requested_by = actor_id
        log_audit_event(self.db, actor_id, actor_role, "EXTENSION_REQUESTED", "requests",
                        {"reason": reason.strip()}, req.correlation_id, req.id)
        self.db.commit()
        return req

    def decide_extension(self, request_id: str, decision: str, reason: str, approver_id: str,
                         approver_role: str) -> Approval:
        if approver_role != "approver":
            raise ApprovalValidationError("Only Approvers can decide extensions.", "ROLE_REQUIRED")
        req = self.db.query(Request).filter(Request.id == request_id).first()
        if not req:
            raise ApprovalValidationError("Request not found", "NOT_FOUND")
        if req.extended:
            raise ApprovalValidationError("Only one extension is allowed (POL-SLA-2).", "EXTENSION_ALREADY_USED", ["POL-SLA-2"])
        if not req.extension_pending:
            raise ApprovalValidationError("No extension request is pending for this request.", "NO_PENDING_EXTENSION")
        old_due = req.due_at
        if decision == "APPROVED":
            req.due_at = calculate_extended_due_date(req.due_at, self.policy)
            req.extended = True
            req.extension_reason = req.extension_request_reason
        req.extension_pending = False
        appr = Approval(id=f"appr_{uuid.uuid4().hex[:12]}", request_id=req.id, scope="EXTENSION", decision=decision,
                        approver_id=approver_id, reason=reason, action_set_hash=None, inventory_version=req.inventory_version)
        self.db.add(appr)
        log_audit_event(self.db, approver_id, approver_role, f"APPROVAL_EXTENSION_{decision}", "approvals", {
            "approval_id": appr.id, "old_due_at": old_due.isoformat() if old_due else None,
            "new_due_at": req.due_at.isoformat(), "reason": reason}, req.correlation_id, req.id)
        self.db.commit()
        return appr
