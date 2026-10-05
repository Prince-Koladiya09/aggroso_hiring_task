"""Idempotent Action Executor (SRS 7.8, 11.1, 11.2).

Guarantees
 * an action runs at most once: deterministic idempotency key + UNIQUE constraint + atomic claim;
 * duplicate / concurrent calls never write twice (suppressed result or 409);
 * FAILED actions are retried only by explicit user action, after a reconciliation read;
 * the write and the SUCCEEDED marker commit in ONE transaction (same DB engine, see SRS section 15).
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import update, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.crypto import seal
from app.core.errors import AppError
from app.core.logging import log_action
from app.db.models import Request, ProposedAction, Action, ActionAttempt
from app.executor.idempotency import compute_action_idempotency_key
from app.approvals.validation import (
    ApprovalInvalidError, get_valid_approval, scope_actions, compute_action_set_hash,
)
from app.tools.gateway import ToolGateway, ToolPermissionDeniedError, ANONYMIZED_PROFILE_TOKEN
from app.workflow.state_machine import transition_state
from app.audit.logger import log_audit_event

LEASE_MINUTES = 5
SUCCESS = ("SUCCEEDED", "SUCCEEDED_RECONCILED")


class ExecutionError(AppError):
    def __init__(self, message: str, code: str = "EXECUTION_ERROR", status_code: int = 400, rule_ids=None):
        super().__init__(message, code, status_code, rule_ids)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class ActionExecutor:
    def __init__(self, db: Session):
        self.db = db
        self.gateway = ToolGateway(db)

    # ============================================================ scope execution
    def execute_scope_actions(self, request_id: str, scope: str, actor_id: str, actor_role: str,
                              inject_fault: Optional[str] = None) -> Dict[str, Any]:
        req = self.db.query(Request).filter(Request.id == request_id).first()
        if not req:
            raise ExecutionError(f"Request {request_id} not found", "NOT_FOUND", 404)
        if scope not in ("CORRECTION", "DELETION"):
            raise ExecutionError("Scope must be CORRECTION or DELETION.", "INVALID_SCOPE", 422)
        if req.type != scope:
            raise ExecutionError(f"A {req.type} request cannot execute {scope} actions.", "SCOPE_MISMATCH", 403, ["POL-APR-2"])
        if req.status not in ("EXECUTING", "PARTIALLY_FAILED", "COMPLETED_PENDING_RECORD", "CLOSED"):
            raise ExecutionError(
                f"Actions cannot be executed in status {req.status}: a separate {scope} approval is required first (POL-APR-2).",
                "APPROVAL_MISSING", 403, ["POL-APR-2"])

        self._require_valid_approval(req, scope)
        actions = scope_actions(self.db, request_id, scope)
        if not actions:
            raise ExecutionError(f"No approved {scope} actions exist for this request.", "NO_ACTIONS", 400)

        results: List[Dict[str, Any]] = []
        fault_for_first = settings.FAULT_INJECTION_ENABLED and inject_fault is None
        for idx, pa in enumerate(actions):
            fault = inject_fault
            if fault_for_first and idx == 0:
                fault = "before_write"          # demo toggle: first attempt of first action fails (S5)
            res = self._execute_one(req, pa, actor_id, actor_role, inject_fault=fault, explicit_retry=False)
            results.append(res)

        all_ok = all(self._is_success(r) for r in results)
        self._advance_request_state(req, all_ok, actor_id, actor_role, scope)
        self.db.commit()
        return {"request_id": request_id, "scope": scope, "all_succeeded": all_ok, "actions": results,
                "request_status": req.status}

    def execute_single_proposed_action(self, proposed_action_id: str, actor_id: str, actor_role: str,
                                       inject_fault: Optional[str] = None) -> Dict[str, Any]:
        pa = self.db.query(ProposedAction).filter(ProposedAction.id == proposed_action_id).first()
        if not pa:
            raise ExecutionError("Proposed action not found", "NOT_FOUND", 404)
        req = self.db.query(Request).filter(Request.id == pa.request_id).first()
        return self._execute_one(req, pa, actor_id, actor_role, inject_fault=inject_fault, explicit_retry=False)

    # ============================================================ explicit retry
    def retry_action(self, action_id: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
        action = self.db.query(Action).filter(Action.id == action_id).first()
        if not action:
            raise ExecutionError("Action not found", "NOT_FOUND", 404)
        pa = self.db.query(ProposedAction).filter(ProposedAction.id == action.proposed_action_id).first()
        req = self.db.query(Request).filter(Request.id == pa.request_id).first()
        self._require_valid_approval(req, pa.kind)

        if action.status in SUCCESS:   # retry after success -> no write (idempotent)
            return self._execute_one(req, pa, actor_id, actor_role, explicit_retry=True)
        if req.status == "PARTIALLY_FAILED":
            transition_state(req, "EXECUTING", actor_id, actor_role, f"Retrying failed action {action.id}", self.db)

        res = self._execute_one(req, pa, actor_id, actor_role, explicit_retry=True)

        if req.status == "EXECUTING":
            statuses = self._scope_statuses(req, pa.kind)
            self._advance_request_state(req, all(s in SUCCESS for s in statuses), actor_id, actor_role, pa.kind)
        self.db.commit()
        res["request_status"] = req.status
        return res

    # ============================================================ internals
    def _require_valid_approval(self, req: Request, scope: str) -> None:
        try:
            get_valid_approval(self.db, req, scope)
        except ApprovalInvalidError as e:
            log_audit_event(self.db, "system", "system", "EXECUTION_REFUSED", "actions",
                            {"scope": scope, "code": e.code, "message": str(e)}, req.correlation_id, req.id)
            self.db.commit()
            raise ExecutionError(str(e), e.code, 403, e.rule_ids)

    @staticmethod
    def _is_success(res: Dict[str, Any]) -> bool:
        return res.get("status") in SUCCESS

    def _scope_statuses(self, req: Request, scope: str) -> List[str]:
        out = []
        for pa in scope_actions(self.db, req.id, scope):
            a = self.db.query(Action).filter(Action.proposed_action_id == pa.id).first()
            out.append(a.status if a else "PENDING")
        return out

    def _advance_request_state(self, req: Request, all_ok: bool, actor_id: str, actor_role: str, scope: str) -> None:
        if req.status in ("COMPLETED_PENDING_RECORD", "CLOSED"):
            return                                        # duplicate click after completion: nothing to move
        if all_ok:
            if req.status == "PARTIALLY_FAILED":
                transition_state(req, "EXECUTING", actor_id, actor_role, "Retry of failed actions", self.db)
            transition_state(req, "COMPLETED_PENDING_RECORD", actor_id, actor_role,
                             f"All {scope} actions executed successfully.", self.db)
        elif req.status == "EXECUTING":
            transition_state(req, "PARTIALLY_FAILED", actor_id, actor_role,
                             f"Some {scope} actions failed. Explicit retry required.", self.db)

    def _read_target(self, req: Request, pa: ProposedAction, actor_id: str, actor_role: str):
        res = self.gateway.invoke("get_record", {"source": pa.source, "record_id": pa.record_id}, actor_id, actor_role,
                                  caller="EXECUTOR", request_id=req.id, correlation_id=req.correlation_id)
        return res.get("data")

    @staticmethod
    def _post_state_reached(pa: ProposedAction, current: Optional[Dict[str, Any]]) -> bool:
        if pa.kind == "DELETION":
            if pa.strategy == "ANONYMIZE":
                return current is not None and current.get("profile_id") == ANONYMIZED_PROFILE_TOKEN
            return current is None
        if pa.kind == "CORRECTION":
            if current is None:
                return False
            val = current.get(pa.field)
            if isinstance(val, bool):
                return str(val).lower() == str(pa.after_value).strip().lower() or \
                    val == (str(pa.after_value).strip().lower() in ("1", "true", "yes", "y", "on"))
            return str(val) == str(pa.after_value)
        return False

    @staticmethod
    def _matches_pre_image(current: Optional[Dict[str, Any]], pre: Optional[Dict[str, Any]], pa: ProposedAction) -> bool:
        if pre is None or current is None:
            return current is None and pre is None
        if pa.kind == "CORRECTION" and pa.field:
            return str(current.get(pa.field)) == str(pre.get(pa.field))
        return current == pre

    def _record_attempt(self, action_id: str, attempt_no: int, started: datetime, outcome: str, error: Optional[str]):
        self.db.add(ActionAttempt(id=f"att_{uuid.uuid4().hex[:12]}", action_id=action_id, attempt_no=attempt_no,
                                  started_at=started, ended_at=datetime.now(timezone.utc), outcome=outcome, error=error))

    def _audit(self, req, actor_id, actor_role, event, payload):
        log_audit_event(self.db, actor_id, actor_role, event, "actions", payload, req.correlation_id, req.id)

    def _fail(self, req, action, pa, actor_id, actor_role, attempt_no, started, message, code="ACTION_FAILED"):
        action.status = "FAILED"
        action.last_error = message
        action.lease_expires_at = None
        self._record_attempt(action.id, attempt_no, started, "FAILED", message)
        self._audit(req, actor_id, actor_role, "ACTION_FAILED",
                    {"action_id": action.id, "attempt": attempt_no, "error": message, "code": code,
                     "source": pa.source, "record_id": pa.record_id})
        log_action(outcome="failed", action_id=action.id, attempt=attempt_no, request_id=req.id, error=message)
        self.db.commit()
        return {"action_id": action.id, "proposed_action_id": pa.id, "status": "FAILED", "attempt": attempt_no,
                "error": message, "code": code}

    def _get_or_create_action(self, pa: ProposedAction, key: str, now: datetime) -> Action:
        action = self.db.query(Action).filter(Action.idempotency_key == key).first()
        if action:
            return action
        try:
            with self.db.begin_nested():
                action = Action(id=f"act_{uuid.uuid4().hex[:12]}", proposed_action_id=pa.id, idempotency_key=key,
                                status="PENDING", attempts=0, created_at=now)
                self.db.add(action)
                self.db.flush()
            return action
        except IntegrityError:                          # a concurrent caller inserted the same key first
            return self.db.query(Action).filter(Action.idempotency_key == key).one()

    def _execute_one(self, req: Request, pa: ProposedAction, actor_id: str, actor_role: str,
                     inject_fault: Optional[str] = None, explicit_retry: bool = False) -> Dict[str, Any]:
        key = compute_action_idempotency_key(req.id, pa.kind, pa.source, pa.record_id, pa.field, pa.strategy,
                                             pa.after_value)
        now = datetime.now(timezone.utc)
        action = self._get_or_create_action(pa, key, now)
        self.db.refresh(action)

        # ---- already done: return stored result, NO write
        if action.status in SUCCESS:
            self._audit(req, actor_id, actor_role, "ACTION_DUPLICATE_SUPPRESSED",
                        {"action_id": action.id, "idempotency_key": key})
            log_action(outcome="duplicate_suppressed", action_id=action.id, request_id=req.id)
            self.db.commit()
            return {"action_id": action.id, "proposed_action_id": pa.id, "status": action.status,
                    "duplicate_suppressed": True, "attempt": action.attempts, "result": action.result_json}

        # ---- someone else is running it
        lease = _aware(action.lease_expires_at)
        if action.status == "IN_PROGRESS" and lease and lease > now:
            raise ExecutionError("Action is IN_PROGRESS under an active lease; concurrent call refused.",
                                 "CONCURRENT_CONFLICT", 409)

        # ---- failed earlier: only an explicit retry may re-run it
        if action.status == "FAILED" and not explicit_retry:
            return {"action_id": action.id, "proposed_action_id": pa.id, "status": "FAILED",
                    "attempt": action.attempts, "error": action.last_error, "requires_explicit_retry": True}

        # ---- reconcile before any retry (expired lease or FAILED retry)
        if action.status in ("FAILED", "IN_PROGRESS") and action.attempts > 0:
            try:
                current = self._read_target(req, pa, actor_id, actor_role)
            except ToolPermissionDeniedError as e:
                return self._fail(req, action, pa, actor_id, actor_role, action.attempts, now, f"Reconciliation read denied: {e}")
            if self._post_state_reached(pa, current):
                action.status = "SUCCEEDED_RECONCILED"
                action.lease_expires_at = None
                action.last_error = None
                pa.status = "EXECUTED"
                self._record_attempt(action.id, action.attempts + 1, now, "SUCCEEDED", "reconciled: target already in post-state")
                self._audit(req, actor_id, actor_role, "ACTION_RECONCILED",
                            {"action_id": action.id, "reason": "Target already in post-state; no write performed."})
                log_action(outcome="reconciled", action_id=action.id, request_id=req.id)
                self.db.commit()
                return {"action_id": action.id, "proposed_action_id": pa.id, "status": "SUCCEEDED_RECONCILED",
                        "reconciled": True, "attempt": action.attempts}
            from app.core.crypto import unseal
            if not self._matches_pre_image(current, unseal(action.pre_image), pa):
                return self._fail(req, action, pa, actor_id, actor_role, action.attempts, now,
                                  "STATE_DRIFT: target changed since the pre-image was captured; human review required.",
                                  code="STATE_DRIFT")

        # ---- atomic claim (conditional UPDATE: only one caller can win)
        claimed = self.db.execute(
            update(Action).where(Action.id == action.id,
                                 or_(Action.status.in_(("PENDING", "FAILED")),
                                     (Action.status == "IN_PROGRESS") & (Action.lease_expires_at < now)))
            .values(status="IN_PROGRESS", lease_expires_at=now + timedelta(minutes=LEASE_MINUTES),
                    attempts=Action.attempts + 1))
        if claimed.rowcount != 1:
            self.db.rollback()
            raise ExecutionError("Action was claimed by a concurrent caller.", "CONCURRENT_CONFLICT", 409)
        self.db.refresh(action)
        attempt_no = action.attempts

        if action.pre_image is None:
            try:
                action.pre_image = seal(self._read_target(req, pa, actor_id, actor_role))
            except ToolPermissionDeniedError:
                pass
        self.db.commit()

        if inject_fault == "before_write":
            return self._fail(req, action, pa, actor_id, actor_role, attempt_no, now,
                              "Simulated pre-write system failure (fault injection).", code="FAULT_BEFORE_WRITE")

        # ---- the write (flushed, NOT committed) + status update in one transaction
        try:
            if pa.kind == "CORRECTION":
                res = self.gateway.invoke("apply_correction",
                                          {"proposed_action_id": pa.id, "source": pa.source, "record_id": pa.record_id,
                                           "field": pa.field, "new_value": pa.after_value},
                                          actor_id, actor_role, caller="EXECUTOR", request_id=req.id,
                                          correlation_id=req.correlation_id)
            elif pa.kind == "DELETION":
                res = self.gateway.invoke("delete_record",
                                          {"proposed_action_id": pa.id, "source": pa.source, "record_id": pa.record_id,
                                           "strategy": pa.strategy},
                                          actor_id, actor_role, caller="EXECUTOR", request_id=req.id,
                                          correlation_id=req.correlation_id)
            else:
                raise ValueError(f"Unknown action kind '{pa.kind}'")

            if inject_fault == "after_write_before_commit":
                # Crash simulation: the write is durable but the SUCCEEDED marker never lands.
                self.db.commit()
                return self._fail(req, action, pa, actor_id, actor_role, attempt_no, now,
                                  "Simulated crash after write, before the action row was marked SUCCEEDED "
                                  "(retry will reconcile).", code="FAULT_AFTER_WRITE")

            action.status = "SUCCEEDED"
            action.result_json = res.get("data")
            action.lease_expires_at = None
            action.last_error = None
            pa.status = "EXECUTED"
            self._record_attempt(action.id, attempt_no, now, "SUCCEEDED", None)
            self._audit(req, actor_id, actor_role, "ACTION_SUCCEEDED",
                        {"action_id": action.id, "attempt": attempt_no, "kind": pa.kind, "source": pa.source,
                         "record_id": pa.record_id})
            log_action(outcome="succeeded", action_id=action.id, attempt=attempt_no, request_id=req.id)
            self.db.commit()
            return {"action_id": action.id, "proposed_action_id": pa.id, "status": "SUCCEEDED", "attempt": attempt_no,
                    "result": res.get("data")}
        except ToolPermissionDeniedError as e:
            self.db.rollback()
            action = self.db.query(Action).filter(Action.id == action.id).one()
            return self._fail(req, action, pa, actor_id, actor_role, attempt_no, now, f"Denied by gateway: {e}",
                              code=e.reason)
        except Exception as e:                           # write failed: roll back the partial write, record failure
            self.db.rollback()
            action = self.db.query(Action).filter(Action.id == action.id).one()
            return self._fail(req, action, pa, actor_id, actor_role, attempt_no, now, str(e))
