import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_role
from app.core.errors import AppError
from app.db.models import Request, VerificationCheck, StaffUser
from app.db.session import get_db
from app.audit.logger import log_audit_event
from app.policy.loader import get_policy
from app.tools.gateway import ToolGateway
from app.workflow.missing_info import missing_verification_items, required_level
from app.workflow.state_machine import transition_state

router = APIRouter(prefix="/requests/{id}/verification", tags=["Identity Verification"])
OTP_TTL_MIN = 10
VERIFIABLE = ("NEW", "AWAITING_INFO", "VERIFICATION_PENDING", "VERIFICATION_FAILED")


class VerificationInput(BaseModel):
    name: str
    email: Optional[str] = None
    account_id: Optional[str] = None
    otp: Optional[str] = None
    authorization_on_file: Optional[bool] = False


def _req(db, id) -> Request:
    r = db.query(Request).filter(Request.id == id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    return r


def _last(db, id) -> Optional[VerificationCheck]:
    return db.query(VerificationCheck).filter(VerificationCheck.request_id == id) \
        .order_by(VerificationCheck.at.desc(), VerificationCheck.id.desc()).first()


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


@router.get("")
def get_verification_state(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    r = _req(db, id)
    checks = db.query(VerificationCheck).filter(VerificationCheck.request_id == id).order_by(VerificationCheck.at.asc()).all()
    last = _last(db, id)
    outbox = None
    if last and last.otp_sent and user.role in ("analyst", "approver") and r.status in VERIFIABLE:
        outbox = {"recipient": r.requester_email, "channel": "SIMULATED SMS/E-MAIL", "otp_code": last.otp_sent,
                  "note": "Mock outbox for evaluation only; no message is actually sent."}
    return {"required_level": required_level(r.type), "missing_verification": missing_verification_items(db, r),
            "locked": bool(last and last.locked), "otp_attempts": last.otp_attempts if last else 0, "outbox": outbox,
            "checks": [{"id": c.id, "level": c.level, "result": c.result, "failed_fields": c.failed_fields,
                        "otp_attempts": c.otp_attempts, "performed_by": c.performed_by, "at": c.at.isoformat() if c.at else None}
                       for c in checks]}


@router.post("/send-otp")
def send_mock_otp(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["analyst"]))):
    r = _req(db, id)
    if required_level(r.type) < 2:
        raise AppError("A one-time code is only used for Level 2 (correction/deletion) verification.", "OTP_NOT_REQUIRED", 400, ["POL-ID-2"])
    if r.status not in VERIFIABLE:
        raise AppError(f"Cannot send a code in status {r.status}.", "INVALID_STATE", 409)
    last = _last(db, id)
    if last and last.locked:
        raise AppError("Verification is LOCKED; an Approver must unlock it first.", "VERIFICATION_LOCKED", 403, ["POL-ID-2"])
    code = f"{secrets.randbelow(900000) + 100000}"
    db.add(VerificationCheck(id=f"vc_{uuid.uuid4().hex[:12]}", request_id=id, level=2, result="PENDING", failed_fields=[],
                             otp_sent=code, otp_attempts=last.otp_attempts if last else 0, locked=False, performed_by=user.id))
    log_audit_event(db, user.id, user.role, "VERIFICATION_OTP_SENT", "verification_checks",
                    {"destination": r.requester_email, "simulated": True}, r.correlation_id, id)   # the code itself is never logged
    db.commit()
    return {"message": "Simulated one-time code dispatched.",
            "simulated_outbox": {"recipient": r.requester_email, "channel": "SIMULATED SMS/E-MAIL", "otp_code": code,
                                 "disclaimer": "Mock outbox for evaluation only."}}


@router.post("")
def run_verification(id: str, payload: VerificationInput, db: Session = Depends(get_db),
                     user: StaffUser = Depends(require_role(["analyst"]))):
    r = _req(db, id)
    policy = get_policy()
    if r.status not in VERIFIABLE:
        raise AppError(f"Verification cannot be run in status {r.status}.", "INVALID_STATE", 409)
    level = required_level(r.type)
    last = _last(db, id)
    if last and last.locked:
        raise AppError("Verification is LOCKED after 3 incorrect one-time codes. An Approver must unlock it (POL-ID-2).",
                       "VERIFICATION_LOCKED", 403, ["POL-ID-2"])

    # info supplied alongside the check
    if payload.account_id and not r.account_id:
        r.account_id = payload.account_id.strip()
    if payload.authorization_on_file:
        r.authorization_on_file = True

    # missing identifiers -> AWAITING_INFO, no data-source access at all (FR-205/206)
    missing = [m for m in missing_verification_items(db, r) if m["item"] != "one_time_code"]
    if missing:
        if r.status == "NEW":
            transition_state(r, "AWAITING_INFO", user.id, user.role, "Missing: " + ", ".join(m["item"] for m in missing), db)
        db.commit()
        return {"result": "AWAITING_INFO", "level": level, "failed_fields": [m["item"] for m in missing],
                "missing_verification": missing, "request_status": r.status, "subject_profile_id": None}

    if r.status in ("NEW", "AWAITING_INFO", "VERIFICATION_FAILED"):
        transition_state(r, "VERIFICATION_PENDING", user.id, user.role, "Verification started.", db)
        db.commit()

    gateway = ToolGateway(db)
    res = gateway.invoke("lookup_profile_for_verification",
                         {"email": payload.email, "account_id": payload.account_id, "name": payload.name},
                         user.id, user.role, caller="SYSTEM", request_id=id, correlation_id=r.correlation_id)
    matches = res.get("data", [])
    failed: List[str] = []
    matched = None
    norm = lambda s: "".join((s or "").lower().split())

    if len(matches) > 1:
        failed.append("ambiguous_match")                       # FR-204: never auto-pick
    elif not matches:
        failed.append("profile_lookup")
    else:
        matched = matches[0]
        if norm(matched["full_name"]) != norm(payload.name):
            failed.append("name")
        if (payload.email or "").strip().lower() != matched["email"].lower() or r.requester_email.lower() != matched["email"].lower():
            failed.append("email")
        if not payload.account_id or payload.account_id.strip() != matched["account_id"] or (r.account_id or "") != matched["account_id"]:
            failed.append("account_id")
    if r.relationship == "authorized_agent" and not r.authorization_on_file:
        failed.append("authorization_on_file")                # POL-ID-3

    attempts = last.otp_attempts if last else 0
    otp_sent = last.otp_sent if last else None
    sent_row = db.query(VerificationCheck).filter(VerificationCheck.request_id == id, VerificationCheck.result == "PENDING") \
        .order_by(VerificationCheck.at.desc(), VerificationCheck.id.desc()).first()
    otp_sent_at = _aware(sent_row.at) if sent_row else None
    locked = False
    if level >= 2 and not failed:
        if not payload.otp:
            failed.append("otp_missing")
        elif not otp_sent or payload.otp.strip() != otp_sent or (
                otp_sent_at and otp_sent_at < datetime.now(timezone.utc) - timedelta(minutes=OTP_TTL_MIN)):
            failed.append("otp_invalid")
            attempts += 1
            locked = attempts >= policy.rules["POL-ID-2"].parameters.get("max_otp_attempts", 3)

    passed = not failed
    check = VerificationCheck(id=f"vc_{uuid.uuid4().hex[:12]}", request_id=id, level=level,
                              result="PASSED" if passed else ("LOCKED" if locked else "FAILED"), failed_fields=failed,
                              otp_sent=otp_sent, otp_attempts=attempts, locked=locked, performed_by=user.id)
    db.add(check)
    if passed:
        r.subject_profile_id = matched["profile_id"]
        transition_state(r, "VERIFIED", user.id, user.role, f"Level {level} verification passed.", db)
        log_audit_event(db, user.id, user.role, "VERIFICATION_PASSED", "verification_checks",
                        {"level": level, "subject_profile_id": matched["profile_id"]}, r.correlation_id, id)
    else:
        transition_state(r, "VERIFICATION_FAILED", user.id, user.role, f"Verification failed: {', '.join(failed)}", db)
        log_audit_event(db, user.id, user.role, "VERIFICATION_FAILED", "verification_checks",
                        {"level": level, "failed_fields": failed, "locked": locked}, r.correlation_id, id)   # field NAMES only
    db.commit()
    if locked:
        raise AppError("3 incorrect one-time codes: verification is now LOCKED. An Approver must unlock it (POL-ID-2).",
                       "VERIFICATION_LOCKED", 403, ["POL-ID-2"])
    return {"check_id": check.id, "level": level, "result": check.result, "failed_fields": failed,
            "request_status": r.status, "subject_profile_id": r.subject_profile_id}


@router.post("/unlock")
def unlock_verification(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["approver"]))):
    r = _req(db, id)
    last = _last(db, id)
    if not last or not last.locked:
        raise AppError("Verification is not locked.", "NOT_LOCKED", 409)
    db.add(VerificationCheck(id=f"vc_{uuid.uuid4().hex[:12]}", request_id=id, level=last.level, result="UNLOCKED", failed_fields=[],
                             otp_sent=None, otp_attempts=0, locked=False, performed_by=user.id))
    log_audit_event(db, user.id, user.role, "VERIFICATION_UNLOCKED", "verification_checks", {"request_id": id}, r.correlation_id, id)
    db.commit()
    return {"message": "Verification unlocked. A new one-time code must be sent."}
