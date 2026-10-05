"""Deterministic policy engine. The LLM is never the sole enforcer (SRS section 3).
Retention parameters (rule IDs, blocked operations) come from the YAML policy."""
from typing import Any, Dict, List, Tuple
from app.policy.loader import PolicyModel


class PolicyEngine:
    def __init__(self, policy: PolicyModel):
        self.policy = policy

    # ---------------------------------------------------------------- helpers
    def validate_rule_ids(self, rule_ids: List[str]) -> List[str]:
        valid = set(self.policy.rules.keys())
        seen, out = set(), []
        for r in rule_ids or []:
            if isinstance(r, str) and r in valid and r not in seen:
                seen.add(r)
                out.append(r)
        return out

    def rule_text(self, rule_id: str) -> str:
        r = self.policy.rules.get(rule_id)
        return r.description if r else ""

    def _retention_hit(self, record: Dict[str, Any], operation: str) -> Tuple[bool, List[str], str]:
        ret = self.policy.retention
        if record.get("legal_hold") is True and operation in ret.legal_hold.blocks:
            return True, [ret.legal_hold.rule_id], f"Record is under legal hold and cannot be {'deleted' if operation == 'delete' else 'altered'} ({ret.legal_hold.rule_id})."
        if record.get("retention_class") == "billing" and operation in ret.billing.blocks:
            return True, [ret.billing.rule_id], f"Billing and invoice records are retained for {ret.billing.years} years and excluded from deletion ({ret.billing.rule_id})."
        if record.get("retention_class") == "security_audit" and operation in ret.security_audit.blocks:
            return True, [ret.security_audit.rule_id], f"Security audit events must be retained and cannot be deleted ({ret.security_audit.rule_id})."
        return False, [], ""

    # ---------------------------------------------------------------- checks
    def check_can_delete(self, source: str, record: Dict[str, Any]) -> Tuple[bool, List[str], str]:
        hit, rules, reason = self._retention_hit(record, "delete")
        if hit:
            return False, rules, reason
        return True, [], "Record is eligible for deletion."

    def check_can_correct(self, source: str, record: Dict[str, Any], field: str) -> Tuple[bool, List[str], str]:
        hit, rules, reason = self._retention_hit(record, "correct")
        if hit:
            return False, rules, reason
        if source != "profiles":
            return False, ["POL-COR-1"], f"Corrections are only supported on profile fields, not on '{source}'."
        if field not in self.policy.editable_subject_fields:
            return False, ["POL-COR-1"], f"Field '{field}' is not a subject-editable field (POL-COR-1)."
        return True, [], "Field is eligible for correction."

    def classify_record_decision(self, source: str, record: Dict[str, Any], request_type: str,
                                 is_subject: bool) -> Tuple[str, str, List[str], str]:
        """Returns (relevance, decision, rule_ids, reason)."""
        if not is_subject:
            return "UNRELATED", "EXCLUDE_UNRELATED", [], "Record does not belong to the data subject."
        t = request_type.upper()
        if t == "DELETION":
            ok, rules, reason = self.check_can_delete(source, record)
            if not ok:
                return "RELEVANT", "EXCLUDE_RETENTION", rules, reason
            return "RELEVANT", "INCLUDE", ["POL-APR-2"], "Record identified for deletion; requires separate DELETION approval."
        if t == "CORRECTION":
            hit, rules, reason = self._retention_hit(record, "correct")
            if hit:
                return "RELEVANT", "EXCLUDE_RETENTION", rules, reason
            if source != "profiles":
                return "RELEVANT", "EXCLUDE_UNRELATED", ["POL-COR-1"], "Not a correction target: only profile fields can be corrected."
            return "RELEVANT", "INCLUDE", ["POL-APR-2"], "Profile identified for correction; requires separate CORRECTION approval."
        if t == "ACCESS":
            return "RELEVANT", "INCLUDE", ["POL-RED-1", "POL-RED-2", "POL-RED-3"], \
                "Record included in access export subject to redaction (POL-RED-1/2/3)."
        return "UNCERTAIN", "NEEDS_REVIEW", [], "Request type is not supported; manual triage required."

    def strategy_for(self, source: str) -> str:
        return self.policy.deletion_strategies.get(source, "HARD_DELETE")
