"""Deterministic, fixture-driven mock LLM (NFR-6). Reads the structured `payload` the orchestrator passes
alongside the text prompt - it never hardcodes IDs or subjects - so tests and demos exercise the same
validation path as the real model."""
import re
from typing import Any, Dict, List, Optional

PHONE_RE = re.compile(r"\+?\d[\d\-\s().]{8,}\d")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]*\w")

DELETE_WORDS = ("delete", "erase", "erasure", "remove all", "forget me", "wipe")
CORRECT_WORDS = ("update my", "correct", "change my", "fix my", "rectif", "wrong", "incorrect", "new phone", "new email")
ACCESS_WORDS = ("copy of", "export", "access to my", "what data", "all personal data", "provide a copy", "data held")
UNSUPPORTED_WORDS = ("portab", "restrict processing", "object to", "stop processing")


class MockLLMClient:
    model_name = "mock-llm-v1"
    is_mock = True

    def __init__(self):
        self.simulate_failure = False
        self.simulate_invalid_json = False
        self.fail_times = 0   # fail the first N calls, then succeed (retry test)

    def generate_json(self, system_prompt: str, prompt: str, stage: str, payload: Optional[Dict[str, Any]] = None):
        from app.agent.llm_client import LLMResult, LLMUnavailableError
        from app.core.config import settings
        if settings.SIMULATE_LLM_OUTAGE or self.simulate_failure:
            raise LLMUnavailableError("Simulated LLM upstream outage (502)")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMUnavailableError("Transient mock failure")
        if self.simulate_invalid_json:
            return LLMResult({"malformed_output": True}, self.model_name, 10, 5)
        payload = payload or {}
        fn = {"interpret": self._interpret, "sources": self._sources, "classify": self._classify,
              "plan": self._plan, "narrative": self._narrative}.get(stage)
        data = fn(payload) if fn else {}
        return LLMResult(data, self.model_name, len(prompt) // 4, len(str(data)) // 4)

    # ------------------------------------------------------------------ stages
    def _interpret(self, p: Dict[str, Any]) -> Dict[str, Any]:
        req = p["request"]
        desc = (req.get("description") or "").lower()
        form_type = req["type"]
        detected = form_type
        if any(w in desc for w in UNSUPPORTED_WORDS):
            detected = "UNSUPPORTED"
        elif any(w in desc for w in DELETE_WORDS):
            detected = "DELETION"
        elif any(w in desc for w in CORRECT_WORDS):
            detected = "CORRECTION"
        elif any(w in desc for w in ACCESS_WORDS):
            detected = "ACCESS"
        changes: List[Dict[str, str]] = []
        ambiguities: List[str] = []
        if detected == "CORRECTION":
            text = req.get("description") or ""
            if "phone" in desc or "mobile" in desc or "number" in desc:
                m = PHONE_RE.search(text)
                if m:
                    changes.append({"field": "phone", "new_value": m.group(0).strip(), "source_hint": "profiles"})
                else:
                    ambiguities.append("A phone change was requested but no new number was stated.")
            if "email" in desc:
                emails = [e for e in EMAIL_RE.findall(text) if e.lower() != (req.get("requester_email") or "").lower()]
                if emails:
                    changes.append({"field": "email", "new_value": emails[0], "source_hint": "profiles"})
                else:
                    ambiguities.append("An e-mail change was requested but no new address was stated.")
            if "unsubscribe" in desc or "opt out" in desc or "opt-out" in desc:
                changes.append({"field": "marketing_opt_in", "new_value": "false", "source_hint": "profiles"})
            if not changes and not ambiguities:
                ambiguities.append("A correction was requested but no specific field/value could be identified.")
        return {
            "request_type": detected, "type_matches_form": detected == form_type,
            "subject": {"name": req["requester_name"], "email": req["requester_email"], "account_id": req.get("account_id")},
            "scope_summary": f"{detected.title()} request for {req['requester_name']} across profiles, support tickets and activity logs.",
            "requested_changes": changes, "ambiguities": ambiguities, "missing_verification": [],
        }

    def _sources(self, p: Dict[str, Any]) -> Dict[str, Any]:
        t = p["request"]["type"]
        base = [{"source": "profiles", "decision": "SEARCH", "reason": "Primary store of the subject's personal data."}]
        if t == "CORRECTION":
            base += [{"source": "tickets", "decision": "SKIP", "reason": "Corrections only change profile fields (POL-COR-1)."},
                     {"source": "activity_logs", "decision": "SKIP", "reason": "Activity logs are not correctable (POL-COR-1)."}]
        else:
            base += [{"source": "tickets", "decision": "SEARCH", "reason": "Support correspondence may hold the subject's data."},
                     {"source": "activity_logs", "decision": "SEARCH", "reason": "Event/IP history is linked to the subject's profile."}]
        return {"sources_considered": base}

    def _classify(self, p: Dict[str, Any]) -> Dict[str, Any]:
        out = []
        for r in p.get("records", []):
            out.append({"record_id": r["record_id"], "relevance": "RELEVANT" if r["owned_by_subject"] or r["mentions_subject"] else "UNRELATED",
                        "note": "Authored by the subject." if r["owned_by_subject"] else "Mentions the subject but was authored by someone else."})
        return {"classified": out}

    def _plan(self, p: Dict[str, Any]) -> Dict[str, Any]:
        req_type = p["request"]["type"]
        interp = p.get("interpretation", {})
        steps = [
            {"order": 1, "tool": "search_profiles", "purpose": "Confirm the held profile fields of the verified subject.", "risk": "Read-only lookup.", "policy_rules": ["POL-ID-1"]},
            {"order": 2, "tool": "search_tickets", "purpose": "Locate tickets authored by, or mentioning, the subject.", "risk": "Tickets may contain other people's data and must be redacted in exports.", "policy_rules": ["POL-RED-1"]},
            {"order": 3, "tool": "search_activity_logs", "purpose": "Locate activity events linked to the subject.", "risk": "Security-audit events must be retained.", "policy_rules": ["POL-RET-3"]},
        ]
        actions: List[Dict[str, Any]] = []
        for it in p.get("inventory", []):
            if it["decision"] != "INCLUDE":
                continue
            if req_type == "DELETION":
                actions.append({"kind": "DELETION", "source": it["source"], "record_id": it["record_id"], "field": "*",
                                "before": "existing_record", "after": None, "strategy": it["suggested_strategy"],
                                "risk": f"Irreversible {it['suggested_strategy']} of {it['record_id']} in {it['source']}; removes history held there.",
                                "policy_rules": ["POL-APR-2", "POL-APR-3"]})
            elif req_type == "CORRECTION" and it["source"] == "profiles":
                for ch in interp.get("requested_changes", []):
                    actions.append({"kind": "CORRECTION", "source": "profiles", "record_id": it["record_id"], "field": ch["field"],
                                    "before": it.get("current_values", {}).get(ch["field"]), "after": ch["new_value"],
                                    "strategy": "IN_PLACE_UPDATE", "risk": f"Overwrites '{ch['field']}' on the profile; the previous value is kept only in the sealed pre-image.",
                                    "policy_rules": ["POL-COR-1", "POL-APR-2"]})
        excluded = [i for i in p.get("inventory", []) if i["decision"] == "EXCLUDE_RETENTION"]
        risks = ["No modification may run without the separate human approval required by POL-APR-2."]
        if excluded:
            risks.append(f"{len(excluded)} record(s) are excluded by retention rules and will remain: " +
                         ", ".join(f"{e['record_id']} ({'/'.join(e['rule_ids'])})" for e in excluded))
        qs = ["Confirm the inventory is complete and that every exclusion is understood."]
        if not interp.get("type_matches_form", True):
            qs.insert(0, f"The description suggests {interp.get('request_type')} but the form says {req_type}. Confirm the intended request type.")
        return {"steps": steps, "sources_considered": p.get("sources_considered", []), "proposed_actions": actions,
                "overall_risks": risks, "questions_for_reviewer": qs}

    def _narrative(self, p: Dict[str, Any]) -> Dict[str, Any]:
        s = p["summary"]
        return {"narrative": (f"AI-drafted, reviewed by human: {s['type']} request {s['request_id']} was received {s['received']} and verified at "
                              f"Level {s['level']}. {s['total']} records were inventoried; {s['excluded']} were excluded"
                              f"{(' (' + ', '.join(s['exclusion_rules']) + ')') if s['exclusion_rules'] else ''}. "
                              f"{s['approvals']} approval(s) were recorded and {s['executed']} action(s) executed. "
                              "This summary documents handling per the organisational policy and is not legal advice.")}
