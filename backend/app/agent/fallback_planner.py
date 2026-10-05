"""Deterministic rule-based planner used when the LLM fails/unavailable (FR-307, S10).
Contains NO hardcoded subject values: everything derives from the request and the inventory."""
import re
from typing import Any, Dict, List
from app.db.models import Request
from app.policy.loader import PolicyModel
from app.redaction.rules import EMAIL_PATTERN

PHONE_RE = re.compile(r"\+?\d[\d\-\s().]{8,}\d")


class FallbackPlanner:
    @staticmethod
    def interpret(req: Request, policy: PolicyModel) -> Dict[str, Any]:
        t = req.type.upper()
        t = t if t in ("ACCESS", "CORRECTION", "DELETION") else "UNSUPPORTED"
        desc, low = req.description or "", (req.description or "").lower()
        changes: List[Dict[str, str]] = []
        ambiguities: List[str] = []
        if t == "CORRECTION":
            if "phone" in low or "mobile" in low:
                m = PHONE_RE.search(desc)
                if m:
                    changes.append({"field": "phone", "new_value": m.group(0).strip(), "source_hint": "profiles"})
                else:
                    ambiguities.append("Phone change requested but no new value was found in the description.")
            if "email" in low:
                others = [e for e in EMAIL_PATTERN.findall(desc) if e.lower() != req.requester_email.lower()]
                if others:
                    changes.append({"field": "email", "new_value": others[0], "source_hint": "profiles"})
                else:
                    ambiguities.append("E-mail change requested but no new address was found in the description.")
            if not changes and not ambiguities:
                ambiguities.append("No specific field/value could be extracted; reviewer must specify the correction.")
        return {
            "request_type": t, "type_matches_form": True,
            "subject": {"name": req.requester_name, "email": req.requester_email, "account_id": req.account_id},
            "scope_summary": f"Deterministic fallback interpretation of a {t} request.",
            "requested_changes": changes, "ambiguities": ambiguities, "missing_verification": [],
        }

    @staticmethod
    def sources(req: Request) -> List[Dict[str, str]]:
        t = req.type.upper()
        out = [{"source": "profiles", "decision": "SEARCH", "reason": "Subject profile store."}]
        if t == "CORRECTION":
            out += [{"source": "tickets", "decision": "SKIP", "reason": "Corrections only change profile fields (POL-COR-1)."},
                    {"source": "activity_logs", "decision": "SKIP", "reason": "Not correctable (POL-COR-1)."}]
        else:
            out += [{"source": "tickets", "decision": "SEARCH", "reason": "Support communications store."},
                    {"source": "activity_logs", "decision": "SEARCH", "reason": "Interaction log store."}]
        return out

    @staticmethod
    def build_plan(req: Request, interpretation: Dict[str, Any], inventory: List[Dict[str, Any]],
                   policy: PolicyModel) -> Dict[str, Any]:
        t = req.type.upper()
        steps = [
            {"order": 1, "tool": "search_profiles", "purpose": "Retrieve the verified subject's profile", "risk": "Read-only lookup", "policy_rules": ["POL-ID-1"]},
            {"order": 2, "tool": "search_tickets", "purpose": "Find tickets by or mentioning the subject", "risk": "Read-only; may contain third-party data", "policy_rules": ["POL-RED-1"]},
            {"order": 3, "tool": "search_activity_logs", "purpose": "Find activity logs for the subject profile", "risk": "Read-only; security audit logs must be preserved", "policy_rules": ["POL-RET-3"]},
        ]
        actions: List[Dict[str, Any]] = []
        for it in inventory:
            if it["decision"] != "INCLUDE":
                continue
            if t == "DELETION":
                strat = policy.deletion_strategies.get(it["source"], "HARD_DELETE")
                actions.append({"kind": "DELETION", "source": it["source"], "record_id": it["record_id"], "field": "*",
                                "before": "existing_record", "after": None, "strategy": strat,
                                "risk": f"Permanent {strat} of {it['record_id']} in {it['source']}.",
                                "policy_rules": ["POL-APR-2", "POL-APR-3"]})
            elif t == "CORRECTION" and it["source"] == "profiles":
                for ch in interpretation.get("requested_changes", []):
                    actions.append({"kind": "CORRECTION", "source": "profiles", "record_id": it["record_id"], "field": ch["field"],
                                    "before": (it.get("raw_data") or {}).get(ch["field"]), "after": ch["new_value"],
                                    "strategy": "IN_PLACE_UPDATE", "risk": f"Overwrites profile field '{ch['field']}'.",
                                    "policy_rules": ["POL-COR-1", "POL-APR-2"]})
        return {"steps": steps, "sources_considered": FallbackPlanner.sources(req), "proposed_actions": actions,
                "overall_risks": ["Generated by the deterministic fallback planner.",
                                  "All actions require separate human approval (POL-APR-1, POL-APR-2)."],
                "questions_for_reviewer": ["Review the inventory and confirm no additional exclusions apply."]}
