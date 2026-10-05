import hashlib
import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_role
from app.approvals.validation import get_valid_approval, ApprovalInvalidError
from app.core.errors import AppError
from app.db.models import Request, Export, InventoryItem, Approval, StaffUser, Profile, Ticket
from app.db.session import get_db
from app.redaction.engine import RedactionEngine
from app.tools.gateway import ToolGateway, ToolPermissionDeniedError
from app.workflow.state_machine import transition_state
from app.audit.logger import log_audit_event

router = APIRouter(prefix="/requests/{id}/export", tags=["Redacted Export"])


class ReleaseExportInput(BaseModel):
    reason: str = Field(min_length=5)


def _req(db, id) -> Request:
    r = db.query(Request).filter(Request.id == id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    return r


def _third_party_context(db: Session, req: Request, items):
    """Names/e-mails of everybody who is NOT the subject: other profiles, support agents, staff, ticket authors."""
    pid = req.subject_profile_id
    names, emails = set(), set()
    for p in db.query(Profile).filter(Profile.profile_id != pid).all():
        names.add(p.full_name)
        emails.add(p.email)
    for (agent,) in db.query(Ticket.assigned_agent).distinct().all():
        if agent:
            names.add(agent)
    for u in db.query(StaffUser).all():
        names.add(u.full_name)
    return sorted(names), sorted(emails)


@router.post("")
def generate_export(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["analyst"]))):
    req = _req(db, id)
    if req.type != "ACCESS":
        raise AppError("Exports are generated only for ACCESS requests.", "INVALID_REQUEST_TYPE", 400)
    if req.status != "EXPORT_REVIEW":
        raise AppError(f"An export can only be generated after the plan is approved (status: {req.status}).", "INVALID_STATE", 409, ["POL-APR-1"])
    try:
        get_valid_approval(db, req, "PLAN")
    except ApprovalInvalidError as e:
        raise AppError(str(e), e.code, 403, e.rule_ids)

    ToolGateway(db).invoke("generate_export", {"inventory_version": req.inventory_version}, user.id, user.role,
                           caller="SYSTEM", request_id=id, correlation_id=req.correlation_id)

    items = db.query(InventoryItem).filter(InventoryItem.request_id == id, InventoryItem.inventory_version == req.inventory_version,
                                           InventoryItem.decision.in_(["INCLUDE", "REDACT"]), InventoryItem.relevance == "RELEVANT").all()
    if not items:
        raise AppError("No approved inventory items are available for export.", "NO_ITEMS", 400)
    data = [{"source": i.source, "record_id": i.record_id, "classification": i.classification, "raw_data": i.raw_data_json} for i in items]

    prof = next((i.raw_data_json for i in items if i.source == "profiles"), None) or \
        (db.query(Profile).filter(Profile.profile_id == req.subject_profile_id).first() and
         {"email": req.requester_email, "full_name": req.requester_name})
    prof = prof if isinstance(prof, dict) else {"email": req.requester_email, "full_name": req.requester_name}
    subject_values = [prof.get(k) for k in ("email", "phone", "address", "full_name", "account_id")]
    names, _emails = _third_party_context(db, req, items)
    engine = RedactionEngine(subject_email=prof.get("email") or req.requester_email, subject_name=prof.get("full_name") or req.requester_name,
                             subject_values=subject_values, known_third_party_names=names)
    result = engine.build_export(data)

    exp = Export(id=f"exp_{uuid.uuid4().hex[:12]}", request_id=id, inventory_version=req.inventory_version,
                 content_json=result["exported_records"], html_content=result["html_view"],
                 redaction_report_json=result["redaction_report"], leak_scan_result=result["leak_scan"])
    db.add(exp)
    log_audit_event(db, user.id, user.role, "EXPORT_GENERATED", "exports", {
        "export_id": exp.id, "records": len(result["exported_records"]), "redactions": result["redaction_report"]["total_redactions"],
        "leak_scan_passed": result["leak_scan"]["passed"], "inventory_version": req.inventory_version}, req.correlation_id, id)
    db.commit()
    return {"export_id": exp.id, "records_count": len(result["exported_records"]), "redaction_report": result["redaction_report"],
            "leak_scan": result["leak_scan"]}


@router.get("")
def list_exports(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    req = _req(db, id)
    return [{"export_id": e.id, "inventory_version": e.inventory_version, "stale": e.inventory_version != req.inventory_version,
             "leak_scan_passed": e.leak_scan_result.get("passed"), "released": e.released_by is not None,
             "released_at": e.released_at.isoformat() if e.released_at else None}
            for e in db.query(Export).filter(Export.request_id == id).order_by(Export.id.desc()).all()]


@router.get("/{export_id}")
def get_export_preview(id: str, export_id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    req = _req(db, id)
    e = db.query(Export).filter(Export.id == export_id, Export.request_id == id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Export not found")
    return {"export_id": e.id, "is_released": e.released_by is not None, "released_by": e.released_by,
            "released_at": e.released_at.isoformat() if e.released_at else None, "inventory_version": e.inventory_version,
            "stale": e.inventory_version != req.inventory_version, "redaction_report": e.redaction_report_json,
            "leak_scan": e.leak_scan_result, "content": e.content_json, "html_preview": e.html_content}


@router.post("/{export_id}/release")
def release_export(id: str, export_id: str, payload: ReleaseExportInput, db: Session = Depends(get_db),
                   user: StaffUser = Depends(require_role(["approver"]))):
    req = _req(db, id)
    e = db.query(Export).filter(Export.id == export_id, Export.request_id == id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Export not found")
    if e.released_by:
        raise AppError("This export has already been released.", "ALREADY_RELEASED", 409)
    if req.status != "EXPORT_REVIEW":
        raise AppError(f"Export release requires status EXPORT_REVIEW (current: {req.status}).", "INVALID_STATE", 409)
    if e.inventory_version != req.inventory_version:
        raise AppError("The inventory changed after this export was generated; generate a new export.", "EXPORT_STALE", 409, ["POL-APR-1"])
    if not e.leak_scan_result.get("passed", False):      # FR-605
        raise AppError("Export release BLOCKED by the post-redaction leak scan: " + "; ".join(e.leak_scan_result.get("leaks_found", [])),
                       "LEAK_SCAN_FAILED", 422, ["POL-RED-1", "POL-RED-2", "POL-RED-3"])
    digest = hashlib.sha256(json.dumps(e.content_json, sort_keys=True, default=str).encode()).hexdigest()
    db.add(Approval(id=f"appr_{uuid.uuid4().hex[:12]}", request_id=id, scope="EXPORT", decision="APPROVED", approver_id=user.id,
                    reason=payload.reason.strip(), action_set_hash=digest, inventory_version=req.inventory_version))
    e.released_by, e.released_at = user.id, datetime.now(timezone.utc)
    transition_state(req, "COMPLETED_PENDING_RECORD", user.id, user.role, f"Export released: {payload.reason}", db)
    log_audit_event(db, user.id, user.role, "APPROVAL_EXPORT_APPROVED", "exports",
                    {"export_id": e.id, "content_sha256": digest, "reason": payload.reason}, req.correlation_id, id)
    log_audit_event(db, user.id, user.role, "EXPORT_RELEASED", "exports", {"export_id": e.id}, req.correlation_id, id)
    db.commit()
    return {"message": "Export released.", "export_id": e.id}


@router.get("/{export_id}/download")
def download_export(id: str, export_id: str, format: str = "json", db: Session = Depends(get_db),
                    user: StaffUser = Depends(require_role(["analyst", "approver"]))):
    e = db.query(Export).filter(Export.id == export_id, Export.request_id == id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Export not found")
    if not e.released_by:
        raise AppError("Export cannot be downloaded before explicit Approver release (FR-604).", "NOT_RELEASED", 403)
    req = _req(db, id)
    log_audit_event(db, user.id, user.role, "EXPORT_DOWNLOADED", "exports", {"export_id": e.id, "format": format}, req.correlation_id, id)
    db.commit()
    if format.lower() == "html":
        return Response(content=e.html_content, media_type="text/html")
    return Response(content=json.dumps({"request_id": id, "records": e.content_json}, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{id}-export.json"'})
