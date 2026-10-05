"""Deterministic missing-information checker (FR-205). It wins over any LLM output."""
from typing import Any, Dict, List
from sqlalchemy.orm import Session
from app.db.models import Request, VerificationCheck
from app.policy.loader import get_policy


def required_level(req_type: str) -> int:
    p = get_policy().verification
    t = (req_type or "").upper()
    return p.correction.level if t == "CORRECTION" else p.deletion.level if t == "DELETION" else p.access.level


def missing_verification_items(db: Session, req: Request) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if not (req.account_id or "").strip():
        items.append({"item": "account_id", "policy_rule": "POL-ID-1",
                      "reason": "Account ID is required to match the registered account (Level 1: name, e-mail and account ID)."})
    if req.relationship == "authorized_agent" and not req.authorization_on_file:
        items.append({"item": "authorization_on_file", "policy_rule": "POL-ID-3",
                      "reason": "Requests from an authorised agent need an authorisation-on-file flag."})
    level = required_level(req.type)
    if level >= 2:
        passed = db.query(VerificationCheck).filter(
            VerificationCheck.request_id == req.id, VerificationCheck.result == "PASSED",
            VerificationCheck.level >= level).first()
        if not passed:
            items.append({"item": "one_time_code", "policy_rule": "POL-ID-2",
                          "reason": "Correction and deletion need Level 2: Level 1 plus a one-time code."})
    return items
