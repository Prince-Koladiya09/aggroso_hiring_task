"""Staged, schema-constrained agent workflow (SRS 9.1). The LLM proposes; deterministic code disposes."""
import hashlib
import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.agent.fallback_planner import FallbackPlanner
from app.agent.llm_client import get_llm_client
from app.agent.prompts import render, records_to_xml
from app.agent.schemas import (
    InterpretationSchema, PlanSchema, SourcesSchema, ClassifySchema, NarrativeSchema,
)
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import log_llm_run
from app.db.models import Request, Plan, InventoryItem, ProposedAction, LLMRun
from app.policy.engine import PolicyEngine
from app.policy.loader import get_policy
from app.tools.gateway import ToolGateway, ToolPermissionDeniedError
from app.tools.registry import get_llm_exposed_tools
from app.workflow.missing_info import missing_verification_items
from app.workflow.state_machine import transition_state
from app.audit.logger import log_audit_event

ALL_SOURCES = ["profiles", "tickets", "activity_logs"]
READ_TOOL_NAMES = {t["name"] for t in get_llm_exposed_tools()}


class PlanningError(AppError):
    def __init__(self, message: str, code: str = "PLANNING_ERROR", status_code: int = 400):
        super().__init__(message, code, status_code)


class AgentOrchestrator:
    def __init__(self, db: Session):
        self.db = db
        self.gateway = ToolGateway(db)
        self.policy = get_policy()
        self.engine = PolicyEngine(self.policy)
        self.llm_client = get_llm_client()
        self.llm_failures = 0
        self.fallbacks_used: List[str] = []

    # =================================================================== public
    def interpret_only(self, request_id: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
        """FR-205: interpret + deterministic missing-info check; no data-source access (allowed pre-verification)."""
        req = self._get(request_id)
        if req.status not in ("NEW", "AWAITING_INFO", "VERIFICATION_PENDING", "VERIFICATION_FAILED", "VERIFIED"):
            raise PlanningError(f"Interpretation is not available in status {req.status}.", "INVALID_STATE", 409)
        interp = self._stage_interpret(req)
        log_audit_event(self.db, actor_id, actor_role, "AGENT_INTERPRETED", "requests",
                        {"request_type": interp["request_type"], "type_matches_form": interp["type_matches_form"],
                         "missing": [m["item"] for m in interp["missing_verification"]]},
                        req.correlation_id, req.id)
        self.db.commit()
        return interp

    def run_planning_workflow(self, request_id: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
        req = self._get(request_id)
        if req.status not in ("VERIFIED", "PLANNING_FAILED", "PLAN_REVIEW"):
            raise PlanningError(f"Cannot run agent planning in status {req.status}. The request must be VERIFIED first.",
                                "INVALID_STATE", 409)
        if req.type == "UNSUPPORTED":
            raise PlanningError("UNSUPPORTED request types are routed to manual triage (SRS 1.4).", "UNSUPPORTED_REQUEST_TYPE", 422)

        req.plan_initiated_by = actor_id
        transition_state(req, "PLANNING", actor_id, actor_role, "Agent planning workflow started.", self.db)
        self.db.commit()

        try:
            interp = self._stage_interpret(req)
            if interp["request_type"] == "UNSUPPORTED":
                raise PlanningError("The description asks for an unsupported right (portability/objection/restriction); manual triage required.",
                                    "UNSUPPORTED_REQUEST_TYPE", 422)
            sources = self._stage_sources(req, interp)
            retrieved = self._stage_search(req, sources, actor_id, actor_role)
            inventory = self._stage_classify(req, interp, retrieved)
            plan_data, discarded = self._stage_plan(req, interp, sources, inventory)
            plan_source = "FALLBACK" if self.fallbacks_used else "LLM"
            return self._persist(req, interp, inventory, plan_data, discarded, plan_source, actor_id, actor_role)
        except Exception as e:
            self.db.rollback()
            req = self._get(request_id)
            if req.status == "PLANNING":
                transition_state(req, "PLANNING_FAILED", actor_id, actor_role, f"Planning failed: {e}", self.db)
                log_audit_event(self.db, actor_id, actor_role, "PLANNING_FAILED", "requests",
                                {"error": str(e), "error_class": type(e).__name__}, req.correlation_id, req.id)
                self.db.commit()
            raise

    def draft_narrative(self, req: Request, summary: Dict[str, Any]) -> Tuple[str, str]:
        """Returns (text, source). LLM-drafted when possible; the caller requires human confirmation (FR-1003)."""
        try:
            data = self._llm_stage(req, "narrative", NarrativeSchema, {"summary": summary},
                                   render("narrative", request_json=summary, execution_summary_json=summary))
            text = data["narrative"]
            if not text.lower().startswith("ai-drafted"):
                text = "AI-drafted, reviewed by human: " + text
            return text, "AI_DRAFTED"
        except Exception:
            return "", "DETERMINISTIC"

    # =================================================================== llm plumbing
    def _get(self, request_id: str) -> Request:
        req = self.db.query(Request).filter(Request.id == request_id).first()
        if not req:
            raise PlanningError(f"Request {request_id} not found", "NOT_FOUND", 404)
        return req

    def _llm_stage(self, req: Request, stage: str, schema, payload: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """Call the LLM with retries + backoff, validate with Pydantic, log every attempt (FR-309)."""
        system = render("system")
        input_hash = hashlib.sha256((system + prompt).encode()).hexdigest()
        last_err = None
        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            t0 = time.time()
            try:
                res = self.llm_client.generate_json(system, prompt, stage, payload)
                parsed = schema(**res.data)
                self._record_llm_run(req.id, stage, res.model, input_hash, res.data, True, None, t0,
                                     res.tokens_in, res.tokens_out, attempt)
                return parsed.model_dump()
            except Exception as ex:
                last_err = ex
                self.llm_failures += 1
                self._record_llm_run(req.id, stage, getattr(self.llm_client, "model_name", "unknown"), input_hash,
                                     None, False, f"{type(ex).__name__}: {ex}", t0, 0, 0, attempt)
                if attempt < settings.LLM_MAX_RETRIES and settings.LLM_RETRY_BACKOFF_SECONDS > 0:
                    time.sleep(settings.LLM_RETRY_BACKOFF_SECONDS * (2 ** attempt))
        raise RuntimeError(f"LLM stage '{stage}' failed after {settings.LLM_MAX_RETRIES + 1} attempts: {last_err}")

    def _record_llm_run(self, request_id, stage, model, input_hash, output, valid, error, t0, tin, tout, retries):
        latency = round((time.time() - t0) * 1000.0, 2)
        self.db.add(LLMRun(id=f"llm_{uuid.uuid4().hex[:12]}", request_id=request_id, stage=stage, model=model,
                           prompt_version=settings.PROMPT_VERSION, input_hash=input_hash, output_json=output,
                           valid=valid, error=error, tokens_in=tin, tokens_out=tout, latency_ms=latency))
        log_llm_run(stage=stage, prompt_version=settings.PROMPT_VERSION, model=model, input_hash=input_hash[:16],
                    valid_output=valid, retries=retries, fallback_used=False, tokens=tin + tout, latency_ms=latency,
                    request_id=request_id, error=error)
        self.db.commit()

    def _fallback(self, req: Request, stage: str, reason: str) -> None:
        self.fallbacks_used.append(stage)
        log_audit_event(self.db, "system", "system", "LLM_FALLBACK_USED", "llm_runs",
                        {"stage": stage, "reason": reason[:300]}, req.correlation_id, req.id)
        log_llm_run(stage=stage, fallback_used=True, request_id=req.id, prompt_version=settings.PROMPT_VERSION,
                    model="deterministic-fallback", input_hash="", valid_output=True, retries=settings.LLM_MAX_RETRIES,
                    tokens=0, latency_ms=0)
        self.db.commit()

    def _request_payload(self, req: Request) -> Dict[str, Any]:
        return {"type": req.type, "requester_name": req.requester_name, "requester_email": req.requester_email,
                "account_id": req.account_id, "relationship": req.relationship,
                "description": (req.description or "")[: self.policy.llm.max_description_chars]}

    # =================================================================== stage 1
    def _stage_interpret(self, req: Request) -> Dict[str, Any]:
        rp = self._request_payload(req)
        prompt = render("interpret", policy_rules_json=self._policy_rules_json(), request_type=rp["type"],
                        requester_name=rp["requester_name"], requester_email=rp["requester_email"],
                        account_id=rp["account_id"] or "None", relationship=rp["relationship"],
                        description=rp["description"])
        try:
            interp = self._llm_stage(req, "interpret", InterpretationSchema, {"request": rp}, prompt)
        except Exception as e:
            self._fallback(req, "interpret", str(e))
            interp = FallbackPlanner.interpret(req, self.policy)
            interp = InterpretationSchema(**interp).model_dump()

        # --- deterministic cross-checks (code wins on disagreement)
        agent_missing = {m["item"] for m in interp.get("missing_verification", [])}
        det = missing_verification_items(self.db, req)
        det_names = {m["item"] for m in det}
        interp["missing_verification"] = det
        interp["agent_disagreed_on_missing_info"] = sorted(agent_missing ^ det_names) if agent_missing else []
        interp["type_matches_form"] = interp["request_type"] == req.type
        interp["subject"] = {"name": req.requester_name, "email": req.requester_email, "account_id": req.account_id}
        # only editable fields can be requested changes
        ok, dropped = [], []
        for ch in interp.get("requested_changes", []):
            (ok if ch["field"] in self.policy.editable_subject_fields and str(ch.get("new_value", "")).strip() else dropped).append(ch)
        interp["requested_changes"] = ok
        for ch in dropped:
            interp.setdefault("ambiguities", []).append(
                f"Requested change to '{ch['field']}' dropped: not a subject-editable field or no value given (POL-COR-1).")
        return interp

    def _policy_rules_json(self) -> str:
        return json.dumps({k: v.description for k, v in self.policy.rules.items()}, indent=1)

    # =================================================================== stage 2
    def _stage_sources(self, req: Request, interp: Dict[str, Any]) -> List[Dict[str, str]]:
        prompt = render("sources", policy_rules_json=self._policy_rules_json(), interpretation_json=interp)
        try:
            llm = self._llm_stage(req, "sources", SourcesSchema, {"request": self._request_payload(req)}, prompt)["sources_considered"]
        except Exception as e:
            self._fallback(req, "sources", str(e))
            llm = FallbackPlanner.sources(req)
        # code filters by allowlist and enforces the minimum sources per request type
        chosen: Dict[str, Dict[str, str]] = {}
        for s in llm:
            if s["source"] in ALL_SOURCES and s["source"] not in chosen:
                chosen[s["source"]] = {"source": s["source"], "decision": "SEARCH" if s["decision"].upper() == "SEARCH" else "SKIP", "reason": s["reason"]}
        required = set(ALL_SOURCES) if req.type in ("ACCESS", "DELETION") else {"profiles"}
        for src in ALL_SOURCES:
            if src not in chosen:
                chosen[src] = {"source": src, "decision": "SEARCH" if src in required else "SKIP",
                               "reason": "Added by deterministic source check." if src in required else "Not proposed; not required."}
            elif src in required and chosen[src]["decision"] != "SEARCH":
                chosen[src] = {"source": src, "decision": "SEARCH",
                               "reason": f"Overridden by deterministic source check (required for {req.type}). Agent said: {chosen[src]['reason']}"}
        return [chosen[s] for s in ALL_SOURCES]

    # =================================================================== stage 3
    def _stage_search(self, req: Request, sources: List[Dict[str, str]], actor_id: str, actor_role: str) -> Dict[str, List[Dict[str, Any]]]:
        wanted = {s["source"] for s in sources if s["decision"] == "SEARCH"}
        tools = {"profiles": "search_profiles", "tickets": "search_tickets", "activity_logs": "search_activity_logs"}
        out: Dict[str, List[Dict[str, Any]]] = {k: [] for k in ALL_SOURCES}
        for src in ALL_SOURCES:
            if src not in wanted:
                continue
            try:
                res = self.gateway.invoke(tools[src], {"purpose": f"Locate {src} for the verified subject"}, actor_id, actor_role,
                                          caller="AGENT", request_id=req.id, correlation_id=req.correlation_id)
                out[src] = res["data"] or []
            except ToolPermissionDeniedError as e:
                raise PlanningError(f"Search of {src} was denied by the Tool Gateway: {e}", "TOOL_DENIED", 403)
        if not out["profiles"] and "profiles" in wanted:
            raise PlanningError("No profile was found for the verified subject.", "NO_PROFILE", 404)
        return out

    # =================================================================== stage 4
    def _stage_classify(self, req: Request, interp: Dict[str, Any], retrieved: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        pid = req.subject_profile_id
        subject_email = next((p["email"] for p in retrieved["profiles"] if p["profile_id"] == pid), req.requester_email).lower()
        subject_name = next((p["full_name"] for p in retrieved["profiles"] if p["profile_id"] == pid), req.requester_name)
        inv: List[Dict[str, Any]] = []

        for prf in retrieved["profiles"]:
            own = prf["profile_id"] == pid
            rel, dec, rules, why = self.engine.classify_record_decision("profiles", prf, req.type, own)
            inv.append(self._inv("profiles", prf["profile_id"], "SUBJECT_PERSONAL", rel, dec, rules, why, prf, own, False))
        for t in retrieved["tickets"]:
            own = t.get("requester_profile_id") == pid or (t.get("requester_email") or "").lower() == subject_email
            mentions = (not own) and subject_name.lower() in (t.get("body", "") + " " + t.get("subject", "")).lower()
            if own:
                rel, dec, rules, why = self.engine.classify_record_decision("tickets", t, req.type, True)
                cls = "SUBJECT_PERSONAL"
            elif mentions:
                cls = "THIRD_PARTY_CONTENT"
                rel = "RELEVANT"
                if req.type == "ACCESS":
                    dec, rules, why = "REDACT", ["POL-RED-1"], "Ticket authored by someone else but mentions the subject; included only with the author's personal data redacted."
                else:
                    dec, rules, why = "EXCLUDE_UNRELATED", ["POL-RED-1"], "Ticket authored by another person that merely mentions the subject; it is not the subject's record and is not modified."
            else:
                rel, dec, rules, why = self.engine.classify_record_decision("tickets", t, req.type, False)
                cls = "SUBJECT_PERSONAL"
            inv.append(self._inv("tickets", t["ticket_id"], cls, rel, dec, rules, why, t, own, mentions))
        for lg in retrieved["activity_logs"]:
            own = lg.get("profile_id") == pid
            rel, dec, rules, why = self.engine.classify_record_decision("activity_logs", lg, req.type, own)
            inv.append(self._inv("activity_logs", lg["log_id"], "SUBJECT_PERSONAL", rel, dec, rules, why, lg, own, False))

        # LLM labelling may only make handling MORE cautious
        payload_records = [{"record_id": i["record_id"], "owned_by_subject": i["_own"], "mentions_subject": i["_mentions"]} for i in inv]
        prompt = render("classify", policy_rules_json=self._policy_rules_json(), interpretation_json=interp,
                        records_xml=records_to_xml(inv, self.policy.llm.excerpt_chars))
        try:
            labels = self._llm_stage(req, "classify", ClassifySchema, {"records": payload_records}, prompt)["classified"]
        except Exception as e:
            self._fallback(req, "classify", str(e))
            labels = []
        by_id = {l["record_id"]: l for l in labels}
        for i in inv:
            lab = by_id.get(i["record_id"])
            if lab and lab["relevance"].upper() == "UNCERTAIN" and i["decision"] in ("INCLUDE", "REDACT"):
                i["relevance"], i["decision"] = "UNCERTAIN", "NEEDS_REVIEW"
                i["reason"] = f"Agent is uncertain: {lab.get('note') or 'needs human triage'}"
            elif lab and lab["relevance"].upper() == "UNRELATED" and i["decision"] in ("INCLUDE", "REDACT") and not i["_own"] and not i["_mentions"]:
                i["relevance"], i["decision"] = "UNRELATED", "EXCLUDE_UNRELATED"
        for i in inv:
            i.pop("_own"), i.pop("_mentions")
            i["rule_ids"] = self.engine.validate_rule_ids(i["rule_ids"])
            i["suggested_strategy"] = self.engine.strategy_for(i["source"])
        return inv

    @staticmethod
    def _inv(source, rid, cls, rel, dec, rules, why, raw, own, mentions):
        return {"source": source, "record_id": rid, "classification": cls, "relevance": rel, "decision": dec,
                "rule_ids": rules, "reason": why, "raw_data": raw, "_own": own, "_mentions": mentions}

    # =================================================================== stage 5
    def _stage_plan(self, req: Request, interp: Dict[str, Any], sources: List[Dict[str, str]],
                    inventory: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        slim = [{"source": i["source"], "record_id": i["record_id"], "decision": i["decision"], "rule_ids": i["rule_ids"],
                 "suggested_strategy": i["suggested_strategy"],
                 "current_values": {k: v for k, v in i["raw_data"].items() if k in self.policy.editable_subject_fields}}
                for i in inventory]
        prompt = render("plan", policy_rules_json=self._policy_rules_json(), interpretation_json=interp,
                        inventory_xml=records_to_xml(inventory, self.policy.llm.excerpt_chars),
                        tool_list=sorted(READ_TOOL_NAMES))
        payload = {"request": {"type": req.type}, "interpretation": interp, "inventory": slim, "sources_considered": sources}
        try:
            plan = self._llm_stage(req, "plan", PlanSchema, payload, prompt)
        except Exception as e:
            self._fallback(req, "plan", str(e))
            plan = FallbackPlanner.build_plan(req, interp, inventory, self.policy)
            plan = PlanSchema(**plan).model_dump()
        return self._validate_plan(req, plan, interp, sources, inventory)

    def _validate_plan(self, req, plan, interp, sources, inventory):
        """Deterministic validation (FR-303/306/308): tools exist, rule IDs real, actions derive from the
        request AND reference real, eligible inventory records. Everything else is discarded and recorded."""
        discarded: List[Dict[str, Any]] = []
        steps = []
        for s in plan.get("steps", []):
            if s["tool"] not in READ_TOOL_NAMES:
                discarded.append({"what": "step", "tool": s["tool"], "reason": "Tool is not an LLM-exposed read tool (FR-305)."})
                continue
            s["policy_rules"] = self.engine.validate_rule_ids(s.get("policy_rules", []))
            steps.append(s)
        for i, s in enumerate(steps, 1):
            s["order"] = i

        scope = req.type if req.type in ("CORRECTION", "DELETION") else None
        inv_by_key = {(i["source"], i["record_id"]): i for i in inventory}
        changes = {c["field"]: c for c in interp.get("requested_changes", [])}
        actions: List[Dict[str, Any]] = []
        seen = set()
        for a in plan.get("proposed_actions", []):
            key = (a["source"], a["record_id"])
            why = None
            if scope is None or a["kind"] != scope:
                why = f"Action kind {a['kind']} is not derived from a {req.type} request (POL-APR-2)."
            elif key not in inv_by_key:
                why = "Target record is not in the inventory (hallucinated or injected)."
            elif inv_by_key[key]["decision"] != "INCLUDE":
                why = f"Inventory decision for the target is {inv_by_key[key]['decision']}: {inv_by_key[key]['reason']}"
            elif scope == "CORRECTION":
                if a.get("field") not in changes:
                    why = "Correction does not match any change requested by the data subject."
                elif a["source"] != "profiles":
                    why = "Only profile fields can be corrected (POL-COR-1)."
            if why:
                discarded.append({"what": "action", "kind": a["kind"], "source": a["source"], "record_id": a["record_id"], "reason": why})
                continue
            if scope == "DELETION":
                a.update(field="*", before="existing_record", after=None, strategy=self.engine.strategy_for(a["source"]))
                sig = key
            else:
                ch = changes[a["field"]]
                a.update(after=str(ch["new_value"]), before=str(inv_by_key[key]["raw_data"].get(a["field"])), strategy="IN_PLACE_UPDATE")
                sig = key + (a["field"],)
            if sig in seen:
                continue
            seen.add(sig)
            a["policy_rules"] = self.engine.validate_rule_ids(a.get("policy_rules", []) + (["POL-APR-3"] if scope == "DELETION" else ["POL-COR-1"]))
            actions.append(a)

        # completeness: the inventory is authoritative - eligible items the model missed are added and flagged
        notes = []
        if scope == "DELETION":
            for k, i in inv_by_key.items():
                if i["decision"] == "INCLUDE" and k not in seen:
                    strat = self.engine.strategy_for(i["source"])
                    actions.append({"kind": "DELETION", "source": i["source"], "record_id": i["record_id"], "field": "*", "before": "existing_record",
                                    "after": None, "strategy": strat, "risk": f"Added by deterministic completeness check: permanent {strat} of {i['record_id']}.",
                                    "policy_rules": ["POL-APR-2", "POL-APR-3"]})
                    notes.append(f"{i['record_id']} added by completeness check")
        elif scope == "CORRECTION":
            for k, i in inv_by_key.items():
                if i["source"] == "profiles" and i["decision"] == "INCLUDE":
                    for f, ch in changes.items():
                        if k + (f,) not in seen:
                            actions.append({"kind": "CORRECTION", "source": "profiles", "record_id": i["record_id"], "field": f,
                                            "before": str(i["raw_data"].get(f)), "after": str(ch["new_value"]), "strategy": "IN_PLACE_UPDATE",
                                            "risk": f"Added by completeness check: overwrites '{f}'.", "policy_rules": ["POL-COR-1", "POL-APR-2"]})
                            notes.append(f"{f} correction added by completeness check")
        plan["steps"], plan["proposed_actions"] = steps, actions
        plan["sources_considered"] = sources
        plan["overall_risks"] = plan.get("overall_risks", []) + ([f"Deterministic checks: {'; '.join(notes)}."] if notes else [])
        if discarded:
            plan["overall_risks"].append(f"{len(discarded)} agent proposal(s) were discarded by deterministic validation and are listed under 'discarded_proposals'.")
        if not interp.get("type_matches_form", True):
            plan["overall_risks"].append(f"TYPE MISMATCH: the description reads as {interp['request_type']} but the form says {req.type}. Actions follow the form type; confirm with the requester.")
        plan["discarded_proposals"] = discarded
        return plan, discarded

    # =================================================================== persistence
    def _persist(self, req, interp, inventory, plan, discarded, plan_source, actor_id, actor_role):
        has_old = self.db.query(InventoryItem).filter(InventoryItem.request_id == req.id).count() > 0
        if has_old:
            req.inventory_version += 1                       # FR-503: a re-plan is a new inventory version
        prev = self.db.query(Plan).filter(Plan.request_id == req.id).order_by(Plan.version.desc()).first()
        version = (prev.version + 1) if prev else 1
        self.db.query(Plan).filter(Plan.request_id == req.id).update({"status": "SUPERSEDED"})
        self.db.query(ProposedAction).filter(ProposedAction.request_id == req.id, ProposedAction.status.in_(
            ["PROPOSED", "APPROVED", "BLOCKED"])).update({"status": "SUPERSEDED"}, synchronize_session=False)

        plan_id = f"pln_{uuid.uuid4().hex[:12]}"
        self.db.add(Plan(id=plan_id, request_id=req.id, version=version, interpretation_json=interp, plan_json=plan,
                         source=plan_source, prompt_version=settings.PROMPT_VERSION, status="ACTIVE"))
        self.db.flush()
        for it in inventory:
            self.db.add(InventoryItem(
                id=f"inv_{uuid.uuid4().hex[:12]}", request_id=req.id, inventory_version=req.inventory_version,
                source=it["source"], record_id=it["record_id"], classification=it["classification"], relevance=it["relevance"],
                decision=it["decision"], reason=it["reason"], rule_ids=it["rule_ids"], raw_data_json=it["raw_data"]))
        for a in plan["proposed_actions"]:
            self.db.add(ProposedAction(
                id=f"pact_{uuid.uuid4().hex[:12]}", request_id=req.id, plan_id=plan_id, kind=a["kind"], source=a["source"],
                record_id=a["record_id"], field=a.get("field"), before_value=None if a.get("before") is None else str(a["before"]),
                after_value=None if a.get("after") is None else str(a["after"]), strategy=a.get("strategy") or "HARD_DELETE",
                risk_text=a.get("risk") or "Proposed modification.", rule_ids=a.get("policy_rules", []), status="PROPOSED"))
        # blocked/excluded records are shown to the reviewer with their rule IDs, not as actions
        if discarded:
            log_audit_event(self.db, actor_id, actor_role, "PLAN_PROPOSAL_DISCARDED", "plans",
                            {"plan_id": plan_id, "discarded": discarded}, req.correlation_id, req.id)
        log_audit_event(self.db, actor_id, actor_role, "PLAN_PROPOSED", "plans",
                        {"plan_id": plan_id, "version": version, "source": plan_source, "inventory_version": req.inventory_version,
                         "inventory_count": len(inventory), "actions": len(plan["proposed_actions"]), "discarded": len(discarded)},
                        req.correlation_id, req.id)
        transition_state(req, "PLAN_REVIEW", actor_id, actor_role, "Plan and inventory ready. Awaiting human review.", self.db)
        self.db.commit()
        return {"status": "PLAN_REVIEW", "plan_id": plan_id, "plan_version": version, "fallback_used": plan_source == "FALLBACK",
                "fallback_stages": self.fallbacks_used, "inventory_count": len(inventory),
                "inventory_version": req.inventory_version, "proposed_actions_count": len(plan["proposed_actions"]),
                "discarded_count": len(discarded)}
