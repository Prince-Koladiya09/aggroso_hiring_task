"""Tool Gateway - the single choke point for ALL data access (SRS 5.3, 9.2).

Checks, in order: tool registered -> caller allowed -> role allowed -> state allowed ->
verification level satisfied -> (write tools) approved action + valid approval + policy re-check +
subject ownership -> rate/row caps -> execute -> log.  Any failure logs `tool_call.denied`.
"""
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.logging import log_tool_call
from app.db.models import Request, ToolCall, VerificationCheck, ProposedAction
from app.tools.registry import TOOL_REGISTRY
from app.tools.adapters.profiles import ProfileAdapter
from app.tools.adapters.tickets import TicketAdapter
from app.tools.adapters.activity import ActivityLogAdapter
from app.audit.logger import log_audit_event
from app.policy.loader import get_policy
from app.policy.engine import PolicyEngine
from app.approvals.validation import (
    ApprovalInvalidError, get_valid_approval, scope_actions,
)

ANONYMIZED_PROFILE_TOKEN = "[DELETED_SUBJECT]"


class ToolPermissionDeniedError(Exception):
    def __init__(self, message: str, reason: str, rule_ids: Optional[List[str]] = None):
        self.reason = reason
        self.rule_ids = rule_ids or []
        super().__init__(message)


def required_verification_level(req_type: str) -> int:
    policy = get_policy()
    t = (req_type or "").upper()
    if t == "CORRECTION":
        return policy.verification.correction.level
    if t == "DELETION":
        return policy.verification.deletion.level
    return policy.verification.access.level


def has_verified_subject(db: Session, req: Request) -> bool:
    if not req.subject_profile_id:
        return False
    need = required_verification_level(req.type)
    check = db.query(VerificationCheck).filter(
        VerificationCheck.request_id == req.id, VerificationCheck.result == "PASSED",
        VerificationCheck.level >= need).first()
    return check is not None


class ToolGateway:
    def __init__(self, db: Session):
        self.db = db
        self.policy = get_policy()
        self.engine = PolicyEngine(self.policy)

    # ------------------------------------------------------------------ public
    def invoke(self, tool_name: str, args: Dict[str, Any], actor_id: str, actor_role: str,
               caller: str = "AGENT", request_id: Optional[str] = None,
               correlation_id: Optional[str] = None) -> Dict[str, Any]:
        start = time.time()
        corr = correlation_id or f"corr-tool-{uuid.uuid4().hex[:8]}"
        args = args or {}

        def deny(reason_code: str, message: str, rules: Optional[List[str]] = None):
            self._record_denied(tool_name, args, f"{message}", caller, actor_id, actor_role, request_id, corr,
                                (time.time() - start) * 1000.0, reason_code, rules)
            raise ToolPermissionDeniedError(message, reason_code, rules)

        # 1. registered
        tool = TOOL_REGISTRY.get(tool_name)
        if not tool:
            deny("UNREGISTERED_TOOL", f"Unknown tool '{tool_name}' is not registered in the Tool Registry.")

        # 2. caller allowlist (LLM/agent can never reach write tools)
        if caller not in tool.allowed_callers:
            code = "DIRECT_WRITE_FORBIDDEN" if tool.tool_type == "write" else "CALLER_NOT_PERMITTED"
            msg = (f"Write tool '{tool_name}' cannot be called by the {caller}; only the Action Executor may call it."
                   if tool.tool_type == "write" else f"Caller '{caller}' may not invoke tool '{tool_name}'.")
            deny(code, msg)

        # 3. role
        if actor_role not in tool.allowed_roles and "ANY" not in tool.allowed_roles:
            deny("ROLE_NOT_PERMITTED", f"Role '{actor_role}' is not authorized to invoke tool '{tool_name}'.")

        req = self.db.query(Request).filter(Request.id == request_id).first() if request_id else None
        if request_id and not req:
            deny("REQUEST_NOT_FOUND", f"Request '{request_id}' does not exist.")

        # 4. state
        if "ANY" not in tool.allowed_states:
            if not req:
                deny("REQUEST_REQUIRED", f"Tool '{tool_name}' requires a request context.")
            if req.status not in tool.allowed_states:
                deny("INVALID_STATE_FOR_TOOL", f"Tool '{tool_name}' cannot be invoked in request state '{req.status}'.")

        # 5. verification level (FR-206)
        if tool.requires_verification:
            if not req or not has_verified_subject(self.db, req):
                deny("UNVERIFIED_SUBJECT",
                     f"Access denied: required Level {required_verification_level(req.type if req else 'ACCESS')} "
                     f"identity verification has not been completed.", ["POL-ID-1", "POL-ID-2"])

        # 6. write-tool authorisation
        pa: Optional[ProposedAction] = None
        if tool.tool_type == "write":
            pa = self._authorise_write(tool_name, tool.write_scope, args, req, deny)

        # 7. caps
        if caller == "AGENT" and req:
            made = self.db.query(ToolCall).filter(ToolCall.request_id == req.id, ToolCall.caller == "AGENT",
                                                  ToolCall.status == "OK").count()
            if made >= settings.MAX_AGENT_TOOL_CALLS_PER_REQUEST:
                deny("RATE_CAP_EXCEEDED", "Per-request tool-call cap reached for the agent.")

        # 8. execute + log
        try:
            data, rows, summary = self._execute_tool(tool_name, args, req, pa)
            if isinstance(data, list) and len(data) > settings.MAX_ROWS_PER_CALL:
                data = data[: settings.MAX_ROWS_PER_CALL]
                rows = len(data)
            duration = round((time.time() - start) * 1000.0, 2)
            self._record_call("OK", tool_name, args, None, summary, rows, duration, caller, actor_id, actor_role,
                              request_id, corr)
            return {"status": "OK", "data": data, "rows": rows, "duration_ms": duration}
        except Exception as e:
            duration = round((time.time() - start) * 1000.0, 2)
            self._record_call("ERROR", tool_name, args, str(e), f"Execution error: {e}", 0, duration, caller,
                              actor_id, actor_role, request_id, corr)
            raise

    # ------------------------------------------------------------------ write authorisation
    def _authorise_write(self, tool_name, scope, args, req, deny) -> ProposedAction:
        pa_id = args.get("proposed_action_id")
        pa = self.db.query(ProposedAction).filter(ProposedAction.id == pa_id).first() if pa_id else None
        if not pa or not req or pa.request_id != req.id:
            deny("NO_APPROVED_ACTION", "Write tools require an approved proposed action for this request.", ["POL-APR-2"])
        if pa.kind != scope:
            deny("SCOPE_MISMATCH", f"Action kind '{pa.kind}' cannot be executed with tool '{tool_name}'.", ["POL-APR-2"])
        if pa.status != "APPROVED":
            deny("ACTION_NOT_APPROVED", f"Proposed action is in status '{pa.status}', not APPROVED.", ["POL-APR-2"])
        if pa.id not in [a.id for a in scope_actions(self.db, req.id, scope)]:
            deny("ACTION_NOT_IN_ACTIVE_SET", "Proposed action is not part of the active, approved action set.", ["POL-APR-2"])
        try:
            get_valid_approval(self.db, req, scope)
        except ApprovalInvalidError as e:
            deny(e.code, str(e), e.rule_ids)
        # arguments must match exactly what was approved
        mismatch = (args.get("source") != pa.source or args.get("record_id") != pa.record_id or
                    (scope == "CORRECTION" and (args.get("field") != pa.field or str(args.get("new_value")) != str(pa.after_value))) or
                    (scope == "DELETION" and (args.get("strategy") or "HARD_DELETE") != (pa.strategy or "HARD_DELETE")))
        if mismatch:
            deny("ARGS_DIFFER_FROM_APPROVAL", "Write arguments differ from the approved action.", ["POL-APR-2"])
        # defence in depth: deterministic policy re-check at write time
        current = self._read_record(pa.source, pa.record_id)
        if current is not None:
            if not self._owned_by_subject(pa.source, current, req):
                deny("NOT_SUBJECT_RECORD", "Target record does not belong to the verified data subject.", ["POL-RED-1"])
            if scope == "DELETION":
                ok, rules, reason = self.engine.check_can_delete(pa.source, current)
                if not ok:
                    deny("POLICY_EXCLUSION", reason, rules)
            else:
                ok, rules, reason = self.engine.check_can_correct(pa.source, current, pa.field or "")
                if not ok:
                    deny("POLICY_EXCLUSION", reason, rules)
        return pa

    @staticmethod
    def _owned_by_subject(source: str, record: Dict[str, Any], req: Request) -> bool:
        pid = req.subject_profile_id
        if source == "profiles":
            return record.get("profile_id") == pid
        if source == "tickets":
            return record.get("requester_profile_id") == pid
        if source == "activity_logs":
            return record.get("profile_id") in (pid,)
        return False

    def _read_record(self, source: str, record_id: str) -> Optional[Dict[str, Any]]:
        if source == "profiles":
            return ProfileAdapter.get_by_id(self.db, record_id)
        if source == "tickets":
            return TicketAdapter.get_by_id(self.db, record_id)
        if source == "activity_logs":
            return ActivityLogAdapter.get_by_id(self.db, record_id)
        return None

    # ------------------------------------------------------------------ execution
    def _execute_tool(self, tool_name: str, args: Dict[str, Any], req: Optional[Request],
                      pa: Optional[ProposedAction]) -> Tuple[Any, int, str]:
        if tool_name == "lookup_profile_for_verification":
            profiles = ProfileAdapter.lookup_for_verification(
                self.db, email=args.get("email"), account_id=args.get("account_id"), name=args.get("name"))
            return profiles, len(profiles), f"Found {len(profiles)} candidate profile(s) for verification"

        if tool_name == "search_profiles":
            # scope = verified identifiers of the matched subject; never LLM-supplied values
            profiles = ProfileAdapter.search_by_identifier(self.db, profile_id=req.subject_profile_id)
            return profiles, len(profiles), f"Found {len(profiles)} profile record(s)"

        if tool_name == "search_tickets":
            subject = ProfileAdapter.get_by_id(self.db, req.subject_profile_id)
            subject_email = (subject or {}).get("email") or req.requester_email
            subject_name = (subject or {}).get("full_name")
            tickets = TicketAdapter.search(self.db, email=subject_email, profile_id=req.subject_profile_id,
                                           mention_query=subject_name, limit=settings.MAX_ROWS_PER_CALL)
            return tickets, len(tickets), f"Found {len(tickets)} support ticket(s) (own + mentions of verified name)"

        if tool_name == "search_activity_logs":
            logs = ActivityLogAdapter.search_by_profile_id(self.db, req.subject_profile_id, limit=settings.MAX_ROWS_PER_CALL)
            return logs, len(logs), f"Found {len(logs)} activity log(s)"

        if tool_name == "get_record":
            source, rid = args.get("source"), args.get("record_id")
            record = self._read_record(source, rid)
            return record, 1 if record else 0, f"Retrieved record {rid} from {source}" if record else f"Record {rid} not found in {source}"

        if tool_name == "check_policy":
            rule_id = args.get("rule_id")
            rule = self.policy.rules.get(rule_id)
            return (rule.model_dump() if rule else None), 1 if rule else 0, f"Checked policy rule {rule_id}"

        if tool_name == "generate_export":
            return {"inventory_version": args.get("inventory_version")}, 1, "Export artifact generation authorised"

        if tool_name == "apply_correction":
            if pa.source != "profiles":
                raise ValueError(f"Correction not supported on source '{pa.source}'")
            updated = ProfileAdapter.update_field(self.db, pa.record_id, pa.field, pa.after_value)
            return updated, 1, f"Corrected {pa.field} on profile {pa.record_id}"

        if tool_name == "delete_record":
            strategy = pa.strategy or "HARD_DELETE"
            if pa.source == "profiles":
                ok = ProfileAdapter.delete(self.db, pa.record_id)
                return {"deleted": ok}, 1, f"Deleted profile {pa.record_id}"
            if pa.source == "tickets":
                ok = TicketAdapter.delete(self.db, pa.record_id)
                return {"deleted": ok}, 1, f"Deleted ticket {pa.record_id}"
            if pa.source == "activity_logs":
                if strategy == "ANONYMIZE":
                    anon = ActivityLogAdapter.anonymize(self.db, pa.record_id)
                    return anon, 1, f"Anonymized activity log {pa.record_id}"
                ok = ActivityLogAdapter.delete(self.db, pa.record_id)
                return {"deleted": ok}, 1, f"Deleted activity log {pa.record_id}"
            raise ValueError(f"Deletion not supported on source '{pa.source}'")

        raise ValueError(f"No execution handler for tool '{tool_name}'")

    # ------------------------------------------------------------------ logging
    def _safe_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in (args or {}).items() if k not in ("password", "otp")}

    def _record_call(self, status, tool, args, error, summary, rows, duration, caller, actor_id, actor_role,
                     request_id, corr):
        self.db.add(ToolCall(
            id=f"tc_{uuid.uuid4().hex[:12]}", request_id=request_id, tool=tool, args_json=self._safe_args(args),
            status=status, denial_reason=error, result_summary=summary, rows=rows, duration_ms=duration,
            caller=caller, correlation_id=corr))
        log_audit_event(self.db, actor_id, actor_role,
                        "TOOL_CALL_EXECUTED" if status == "OK" else "TOOL_CALL_ERROR", "tool_calls",
                        {"tool": tool, "caller": caller, "rows": rows, "duration_ms": duration, "summary": summary,
                         **({"error": error} if error else {})}, corr, request_id)
        log_tool_call(tool=tool, status=status, rows=rows, duration_ms=duration, request_id=request_id,
                      caller=caller, correlation_id=corr)

    def _record_denied(self, tool, args, reason, caller, actor_id, actor_role, request_id, corr, duration,
                       code="DENIED", rules=None):
        self.db.add(ToolCall(
            id=f"tc_{uuid.uuid4().hex[:12]}", request_id=request_id if request_id and
            self.db.query(Request.id).filter(Request.id == request_id).first() else None,
            tool=tool, args_json=self._safe_args(args), status="DENIED", denial_reason=f"[{code}] {reason}",
            result_summary=f"Access Denied: {reason}", rows=0, duration_ms=round(duration, 2), caller=caller,
            correlation_id=corr))
        log_audit_event(self.db, actor_id, actor_role, "TOOL_CALL_DENIED", "tool_calls",
                        {"tool": tool, "caller": caller, "reason": reason, "code": code, "rule_ids": rules or []},
                        corr, request_id if request_id and
                        self.db.query(Request.id).filter(Request.id == request_id).first() else None)
        log_tool_call(tool=tool, status="DENIED", code=code, request_id=request_id, caller=caller, correlation_id=corr)
        self.db.commit()
