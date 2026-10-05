import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_role
from app.approvals.service import ApprovalService
from app.core.redaction_view import minimal_view
from app.db.models import InventoryItem, Request, StaffUser
from app.db.session import get_db

router = APIRouter(prefix="/requests/{id}/inventory", tags=["Data Inventory"])


class OverrideInput(BaseModel):
    decision: str
    reason: str


def _current(db, id):
    req = db.query(Request).filter(Request.id == id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req, db.query(InventoryItem).filter(InventoryItem.request_id == id, InventoryItem.inventory_version == req.inventory_version) \
        .order_by(InventoryItem.source, InventoryItem.record_id).all()


def _public_raw(raw):
    from app.redaction.rules import RESTRICTED_SECURITY_FIELDS
    return {k: ("[withheld]" if k in RESTRICTED_SECURITY_FIELDS else v) for k, v in (raw or {}).items()}


def _row(i):
    return {"id": i.id, "source": i.source, "record_id": i.record_id, "classification": i.classification, "relevance": i.relevance,
            "decision": i.decision, "reason": i.reason, "rule_ids": i.rule_ids, "override_by": i.override_by,
            "override_reason": i.override_reason, "inventory_version": i.inventory_version, "summary": minimal_view(i.source, i.raw_data_json),
            "raw_data": _public_raw(i.raw_data_json)}


@router.get("")
def get_inventory(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    req, items = _current(db, id)
    return [_row(i) for i in items]


@router.get("/export")
def export_inventory(id: str, format: str = "json", db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    """FR-504: internal-review inventory download (NOT subject-facing; restricted values withheld)."""
    req, items = _current(db, id)
    rows = [{k: (", ".join(v) if isinstance(v, list) else v) for k, v in _row(i).items() if k not in ("raw_data", "summary")} | {"summary": _row(i)["summary"]} for i in items]
    if format.lower() == "csv":
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return Response(content=buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{id}-inventory-v{req.inventory_version}.csv"'})
    return {"request_id": id, "inventory_version": req.inventory_version, "internal_use_only": True, "items": [_row(i) | {"raw_data": None} for i in items]}


@router.patch("/{item_id}")
def override_item_decision(id: str, item_id: str, payload: OverrideInput, db: Session = Depends(get_db),
                           user: StaffUser = Depends(require_role(["analyst", "approver"]))):
    item = ApprovalService(db).override_inventory_item(id, item_id, payload.decision, payload.reason, user.id, user.role)
    req = db.query(Request).filter(Request.id == id).first()
    return {"id": item.id, "decision": item.decision, "override_by": item.override_by, "override_reason": item.override_reason,
            "inventory_version": req.inventory_version, "request_status": req.status}
