"""Final fulfilment record (SRS 7.10, Appendix A). Deterministic from stored data; immutable once generated."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.agent.orchestrator import AgentOrchestrator
from app.approvals.validation import active_plan
from app.core.errors import AppError
from app.db.models import (
    Request, FulfilmentRecord, VerificationCheck, InventoryItem, ProposedAction, Action, ActionAttempt, Approval,
    ToolCall, LLMRun, Export, StaffUser, AuditEvent,
)
from app.policy.loader import get_policy
from app.workflow.state_machine import transition_state
from app.audit.logger import log_audit_event


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


class FulfilmentRecordGenerator:
    def __init__(self, db: Session):
        self.db = db
        self.policy = get_policy()

    def _name(self, uid: Optional[str]) -> str:
        u = self.db.query(StaffUser).filter(StaffUser.id == uid).first() if uid else None
        return f"{u.full_name} ({u.role})" if u else (uid or "n/a")

    # ------------------------------------------------------------------ content
    def build_content(self, req: Request, now: datetime) -> Dict[str, Any]:
        db = self.db
        # verification
        passed = db.query(VerificationCheck).filter(VerificationCheck.request_id == req.id, VerificationCheck.result == "PASSED") \
            .order_by(VerificationCheck.at.desc()).first()
        failed = db.query(VerificationCheck).filter(VerificationCheck.request_id == req.id, VerificationCheck.result.in_(["FAILED", "LOCKED"])).count()
        verification = {"level": passed.level if passed else None, "result": "PASSED" if passed else "NOT_PERFORMED",
                        "performed_by": self._name(passed.performed_by) if passed else None,
                        "at": passed.at.isoformat() if passed and passed.at else None, "failed_attempts_before_pass": failed}
        # inventory
        items = db.query(InventoryItem).filter(InventoryItem.request_id == req.id, InventoryItem.inventory_version == req.inventory_version).all()
        incl = [i for i in items if i.decision in ("INCLUDE", "REDACT")]
        exc_ret = [i for i in items if i.decision == "EXCLUDE_RETENTION"]
        exc_unrel = [i for i in items if i.decision == "EXCLUDE_UNRELATED"]
        inventory = {"inventory_version": req.inventory_version, "total_found": len(items), "included": len(incl),
                     "excluded_retention": len(exc_ret), "excluded_unrelated": len(exc_unrel),
                     "overrides": [{"record_id": i.record_id, "by": self._name(i.override_by), "reason": i.override_reason, "decision": i.decision}
                                   for i in items if i.override_by],
                     "exclusions": [{"source": i.source, "record_id": i.record_id, "decision": i.decision, "rule_ids": i.rule_ids, "reason": i.reason}
                                    for i in exc_ret + exc_unrel]}
        # plan
        plan = active_plan(db, req.id)
        plan_summary = ({"version": plan.version, "source": plan.source, "prompt_version": plan.prompt_version,
                         "type_matches_form": (plan.interpretation_json or {}).get("type_matches_form"),
                         "steps": len((plan.plan_json or {}).get("steps", [])),
                         "discarded_proposals": len((plan.plan_json or {}).get("discarded_proposals", [])),
                         "summary": (plan.interpretation_json or {}).get("scope_summary")} if plan else None)
        # approvals
        appr = db.query(Approval).filter(Approval.request_id == req.id).order_by(Approval.created_at, Approval.id).all()
        approvals = [{"scope": a.scope, "decision": a.decision, "approver": self._name(a.approver_id), "at": a.created_at.isoformat() if a.created_at else None,
                      "reason": a.reason, "action_set_hash": a.action_set_hash, "inventory_version": a.inventory_version,
                      "differs_from_initiator": (a.approver_id not in {req.created_by, req.plan_initiated_by}) if a.scope == "DELETION" else None}
                     for a in appr]
        # actions
        pas = db.query(ProposedAction).filter(ProposedAction.request_id == req.id, ProposedAction.plan_id == (plan.id if plan else "")).all()
        details, failures, dup_suppressed = [], [], 0
        executed = retried = 0
        for pa in pas:
            act = db.query(Action).filter(Action.proposed_action_id == pa.id).first()
            if not act:
                details.append({"kind": pa.kind, "source": pa.source, "record_id": pa.record_id, "field": pa.field, "status": pa.status, "attempts": 0})
                continue
            atts = db.query(ActionAttempt).filter(ActionAttempt.action_id == act.id).order_by(ActionAttempt.attempt_no, ActionAttempt.started_at).all()
            if act.status in ("SUCCEEDED", "SUCCEEDED_RECONCILED"):
                executed += 1
            if act.attempts > 1:
                retried += 1
            for a in atts:
                if a.outcome == "FAILED":
                    failures.append({"action_id": act.id, "record_id": pa.record_id, "attempt": a.attempt_no, "error": a.error})
            details.append({"action_id": act.id, "kind": pa.kind, "source": pa.source, "record_id": pa.record_id, "field": pa.field,
                            "strategy": pa.strategy, "status": act.status, "attempts": act.attempts, "idempotency_key": act.idempotency_key})
        dup_suppressed = db.query(AuditEvent).filter(AuditEvent.request_id == req.id, AuditEvent.event_type == "ACTION_DUPLICATE_SUPPRESSED").count()
        actions = {"proposed": len(pas), "executed": executed, "retried": retried, "duplicates_suppressed": dup_suppressed,
                   "duplicates_executed": 0, "details": details}
        # export
        exp = db.query(Export).filter(Export.request_id == req.id, Export.released_by.isnot(None)).order_by(Export.released_at.desc()).first()
        export = None
        if exp:
            rep = exp.redaction_report_json or {}
            by_rule: Dict[str, int] = {}
            for r in rep.get("redactions", []):
                by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1
            export = {"export_id": exp.id, "released_by": self._name(exp.released_by), "released_at": exp.released_at.isoformat() if exp.released_at else None,
                      "records": len(exp.content_json or []), "total_redactions": rep.get("total_redactions", 0), "redactions_by_rule": by_rule,
                      "leak_scan_passed": exp.leak_scan_result.get("passed")}
        # tools / llm
        calls = db.query(ToolCall).filter(ToolCall.request_id == req.id).all()
        runs = db.query(LLMRun).filter(LLMRun.request_id == req.id).all()
        fallbacks = db.query(AuditEvent).filter(AuditEvent.request_id == req.id, AuditEvent.event_type == "LLM_FALLBACK_USED").count()
        # timeline
        tl = [{"at": e.at.isoformat() if e.at else None, "event": e.event_type, "actor": e.actor_id,
               "detail": (e.payload_json or {}).get("new_status") or (e.payload_json or {}).get("reason")}
              for e in db.query(AuditEvent).filter(AuditEvent.request_id == req.id, AuditEvent.event_type.in_(
                  ["REQUEST_CREATED", "REQUEST_STATUS_CHANGED", "DEADLINE_EXTENDED"])).order_by(AuditEvent.seq).all()]
        due = _aware(req.due_at)
        on_time = now <= due
        return {
            "request_id": req.id, "policy": self.policy.title, "policy_version": self.policy.policy_version,
            "request": {"type": req.type, "requester_name": req.requester_name, "requester_email": req.requester_email,
                        "account_id": req.account_id, "relationship": req.relationship,
                        "received_at": req.received_at.isoformat(), "due_at": req.due_at.isoformat(), "extended": req.extended,
                        "closed_at": now.isoformat(), "deadline_outcome": "ON_TIME" if on_time else "LATE"},
            "sla_outcome": "ON_TIME" if on_time else "LATE",
            "verification": verification, "plan": plan_summary, "inventory": inventory, "approvals": approvals,
            "actions": actions, "failures": failures, "export": export,
            "tool_calls": {"total": len(calls), "denied": sum(1 for c in calls if c.status == "DENIED"), "errors": sum(1 for c in calls if c.status == "ERROR")},
            "llm_runs": {"total": len(runs), "invalid": sum(1 for r in runs if not r.valid), "fallbacks": fallbacks},
            "timeline": tl, "disclaimer": self.policy.disclaimer,
        }

    def deterministic_narrative(self, c: Dict[str, Any]) -> str:
        inv, rules = c["inventory"], sorted({r for e in c["inventory"]["exclusions"] for r in (e["rule_ids"] or [])})
        return (f"{c['request']['type'].title()} request {c['request_id']} (received {c['request']['received_at'][:10]}, "
                f"{'on time' if c['sla_outcome'] == 'ON_TIME' else 'late'}) was verified at Level {c['verification']['level']}. "
                f"{inv['total_found']} records were inventoried: {inv['included']} included, {inv['excluded_retention']} excluded by retention "
                f"{('(' + ', '.join(rules) + ')') if rules else ''}, {inv['excluded_unrelated']} unrelated. "
                f"{len([a for a in c['approvals'] if a['decision'] == 'APPROVED'])} approval(s) recorded; {c['actions']['executed']} action(s) executed. "
                "This record documents handling per the organisational policy and is not legal advice.")

    def draft_narrative(self, request_id: str) -> Dict[str, Any]:
        req = self.db.query(Request).filter(Request.id == request_id).first()
        if not req:
            raise AppError("Request not found", "NOT_FOUND", 404)
        c = self.build_content(req, datetime.now(timezone.utc))
        summary = {"request_id": req.id, "type": req.type, "received": c["request"]["received_at"][:10], "level": c["verification"]["level"],
                   "total": c["inventory"]["total_found"], "excluded": c["inventory"]["excluded_retention"] + c["inventory"]["excluded_unrelated"],
                   "exclusion_rules": sorted({r for e in c["inventory"]["exclusions"] for r in (e["rule_ids"] or [])}),
                   "approvals": len(c["approvals"]), "executed": c["actions"]["executed"]}
        text, source = AgentOrchestrator(self.db).draft_narrative(req, summary)
        if not text:
            text, source = self.deterministic_narrative(c), "DETERMINISTIC"
        return {"narrative": text, "source": source, "requires_confirmation": source == "AI_DRAFTED"}

    # ------------------------------------------------------------------ generate
    def generate_record(self, request_id: str, actor_id: str, actor_role: str, narrative: Optional[str] = None,
                        narrative_source: Optional[str] = None, confirm_narrative: bool = False) -> Tuple[FulfilmentRecord, bool]:
        req = self.db.query(Request).filter(Request.id == request_id).first()
        if not req:
            raise AppError(f"Request {request_id} not found", "NOT_FOUND", 404)
        existing = self.db.query(FulfilmentRecord).filter(FulfilmentRecord.request_id == request_id).first()
        if existing:
            return existing, False                        # immutable: never regenerate/overwrite
        if req.status != "COMPLETED_PENDING_RECORD":
            raise AppError(f"A fulfilment record can only be generated when work is complete (status: {req.status}).", "INVALID_STATE", 409)

        now = datetime.now(timezone.utc)
        content = self.build_content(req, now)
        if narrative is None:
            d = self.draft_narrative(request_id)
            narrative, narrative_source = d["narrative"], d["source"]
        narrative_source = narrative_source or "HUMAN_EDITED"
        if narrative_source == "AI_DRAFTED" and not confirm_narrative:
            raise AppError("The AI-drafted narrative must be confirmed by a human before the request can be closed (FR-1003).",
                           "NARRATIVE_CONFIRMATION_REQUIRED", 409)
        content["narrative_source"] = narrative_source
        label = {"AI_DRAFTED": f"AI-drafted, reviewed by human (confirmed by {self._name(actor_id)})",
                 "HUMAN_EDITED": f"Written by {self._name(actor_id)}", "DETERMINISTIC": "Generated deterministically from stored data"}[narrative_source]
        content["narrative_label"] = label

        rec = FulfilmentRecord(id=f"ful_{uuid.uuid4().hex[:12]}", request_id=req.id, content_json=content, narrative=narrative,
                               narrative_source=narrative_source, narrative_confirmed_by=actor_id if confirm_narrative or narrative_source != "AI_DRAFTED" else None,
                               generated_at=now, policy_version=self.policy.policy_version)
        self.db.add(rec)
        transition_state(req, "CLOSED", actor_id, actor_role, "Fulfilment record generated. Request closed.", self.db)
        log_audit_event(self.db, actor_id, actor_role, "FULFILMENT_RECORD_GENERATED", "fulfilment_records",
                        {"record_id": rec.id, "sla_outcome": content["sla_outcome"], "narrative_source": narrative_source},
                        req.correlation_id, req.id)
        self.db.commit()
        return rec, True
