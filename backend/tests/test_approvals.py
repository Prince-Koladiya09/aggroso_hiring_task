from helpers import *
from app.db.models import ProposedAction, Request, Approval


def test_only_approver_role_can_approve(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    assert approve(client, auth, rid, "PLAN", who="analyst").status_code == 403
    assert approve(client, auth, rid, "PLAN", who="auditor").status_code == 403


def test_reason_is_mandatory(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    r = approve(client, auth, rid, "PLAN", reason="ok")
    assert r.status_code == 400 and r.json()["error"]["code"] == "REASON_REQUIRED"


def test_plan_approval_does_not_authorise_actions(client, auth):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    assert approve(client, auth, rid, "PLAN").status_code == 200
    assert status_of(client, auth, rid) == "AWAITING_ACTION_APPROVAL"
    ex = client.post(f"/api/requests/{rid}/actions/execute", json={"scope": "DELETION"}, headers=auth["analyst"])
    assert ex.status_code == 403 and ex.json()["error"]["code"] == "APPROVAL_MISSING"
    assert client.get(f"/api/requests/{rid}/actions", headers=auth["analyst"]).json()[0]["action_status"] == "NOT_STARTED"


def test_correction_approval_does_not_authorise_deletion(client, auth):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    approve(client, auth, rid, "PLAN")
    r = approve(client, auth, rid, "CORRECTION")
    assert r.status_code == 400 and r.json()["error"]["code"] == "SCOPE_MISMATCH"
    ex = client.post(f"/api/requests/{rid}/actions/execute", json={"scope": "CORRECTION"}, headers=auth["analyst"])
    assert ex.status_code == 403


def test_deletion_approval_cannot_run_corrections(client, auth):
    rid = planned(client, auth, "robert", "CORRECTION", "Please update my phone number to +1-555-099-7788")
    approve(client, auth, rid, "PLAN")
    assert approve(client, auth, rid, "DELETION").status_code == 400


def test_cannot_approve_actions_before_plan_approval(client, auth):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    r = approve(client, auth, rid, "DELETION")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"


def test_four_eyes_same_user_cannot_approve_own_deletion(client, auth, db_session):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    approve(client, auth, rid, "PLAN")
    # make the approver the initiator (a dual-role / mis-assigned case)
    req = db_session.query(Request).filter(Request.id == rid).first()
    req.plan_initiated_by = "usr_staff_approver1"; db_session.commit()
    r = approve(client, auth, rid, "DELETION", who="approver")
    assert r.status_code == 403 and r.json()["error"]["code"] == "FOUR_EYES_VIOLATION" and "POL-APR-3" in r.json()["error"]["rule_ids"]
    assert approve(client, auth, rid, "DELETION", who="approver2").status_code == 200       # a different approver is fine


def test_four_eyes_checked_again_at_execution(client, auth, db_session):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    approve(client, auth, rid, "PLAN"); approve(client, auth, rid, "DELETION", who="approver")
    req = db_session.query(Request).filter(Request.id == rid).first()
    req.created_by = "usr_staff_approver1"; db_session.commit()                      # initiator changed after approval
    ex = client.post(f"/api/requests/{rid}/actions/execute", json={"scope": "DELETION"}, headers=auth["analyst"])
    assert ex.status_code == 403 and ex.json()["error"]["code"] == "FOUR_EYES_VIOLATION"


def test_tampered_action_set_voids_approval(client, auth, db_session):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    approve(client, auth, rid, "PLAN"); approve(client, auth, rid, "DELETION")
    pa = db_session.query(ProposedAction).filter(ProposedAction.request_id == rid, ProposedAction.source == "tickets").first()
    pa.record_id = "TCK-1001"; db_session.commit()                                       # swap the target after approval
    ex = client.post(f"/api/requests/{rid}/actions/execute", json={"scope": "DELETION"}, headers=auth["analyst"])
    assert ex.status_code == 403 and ex.json()["error"]["code"] == "ACTION_SET_TAMPERED"
    from app.db.models import Ticket
    assert db_session.query(Ticket).filter(Ticket.ticket_id == "TCK-1001").first() is not None      # nothing was deleted


def test_tampered_correction_value_voids_approval(client, auth, db_session):
    rid = planned(client, auth, "robert", "CORRECTION", "Please update my phone number to +1-555-099-7788")
    approve(client, auth, rid, "PLAN"); approve(client, auth, rid, "CORRECTION")
    pa = db_session.query(ProposedAction).filter(ProposedAction.request_id == rid).first()
    pa.after_value = "+1-999-999-9999"; db_session.commit()
    ex = client.post(f"/api/requests/{rid}/actions/execute", json={"scope": "CORRECTION"}, headers=auth["analyst"])
    assert ex.status_code == 403 and ex.json()["error"]["code"] == "ACTION_SET_TAMPERED"


def test_inventory_change_after_plan_approval_resets_approval(client, auth):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    approve(client, auth, rid, "PLAN")
    inv = client.get(f"/api/requests/{rid}/inventory", headers=auth["analyst"]).json()
    item = next(i for i in inv if i["source"] == "tickets")
    r = client.patch(f"/api/requests/{rid}/inventory/{item['id']}", json={"decision": "EXCLUDE_UNRELATED", "reason": "Reviewer keeps this ticket"},
                     headers=auth["analyst"])
    assert r.status_code == 200 and r.json()["request_status"] == "PLAN_REVIEW"
    assert approve(client, auth, rid, "DELETION").status_code == 409                    # plan must be re-approved first


def test_inventory_change_after_action_approval_voids_it(client, auth):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    approve(client, auth, rid, "PLAN"); approve(client, auth, rid, "DELETION")
    assert status_of(client, auth, rid) == "EXECUTING"
    inv = client.get(f"/api/requests/{rid}/inventory", headers=auth["analyst"]).json()
    item = next(i for i in inv if i["source"] == "tickets")
    # inventory edits are not allowed once execution has started
    r = client.patch(f"/api/requests/{rid}/inventory/{item['id']}", json={"decision": "EXCLUDE_UNRELATED", "reason": "late change"}, headers=auth["analyst"])
    assert r.status_code == 409


def test_rejecting_deletion_returns_to_plan_review(client, auth):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    approve(client, auth, rid, "PLAN")
    assert approve(client, auth, rid, "DELETION", decision="REJECTED", reason="Need legal check first").status_code == 200
    assert status_of(client, auth, rid) == "PLAN_REVIEW"


def test_rejecting_plan_rejects_request(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    assert approve(client, auth, rid, "PLAN", decision="REJECTED", reason="Requester unclear").status_code == 200
    assert status_of(client, auth, rid) == "REJECTED"


def test_unresolved_needs_review_blocks_plan_approval(client, auth, db_session):
    from app.db.models import InventoryItem
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    it = db_session.query(InventoryItem).filter(InventoryItem.request_id == rid).first()
    it.decision = "NEEDS_REVIEW"; db_session.commit()
    r = approve(client, auth, rid, "PLAN")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVENTORY_UNRESOLVED"


def test_approval_expires(client, auth, db_session):
    from datetime import datetime, timezone, timedelta
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    approve(client, auth, rid, "PLAN"); approve(client, auth, rid, "DELETION")
    a = db_session.query(Approval).filter(Approval.request_id == rid, Approval.scope == "DELETION").one()
    a.created_at = datetime.now(timezone.utc) - timedelta(hours=100); db_session.commit()
    ex = client.post(f"/api/requests/{rid}/actions/execute", json={"scope": "DELETION"}, headers=auth["analyst"])
    assert ex.status_code == 403 and ex.json()["error"]["code"] == "APPROVAL_EXPIRED"


def test_extension_workflow_is_once_only(client, auth):
    rid = "REQ-2026-0001"
    r1 = client.post(f"/api/requests/{rid}/extension", json={"reason": "Complex multi-system search"}, headers=auth["analyst"])
    assert r1.status_code == 200
    assert client.post(f"/api/requests/{rid}/extension", json={"reason": "again please"}, headers=auth["analyst"]).status_code == 400   # already pending
    before = client.get(f"/api/requests/{rid}", headers=auth["analyst"]).json()["due_at"]
    d = client.post(f"/api/requests/{rid}/extension", json={"decision": "APPROVED", "reason": "Justified by volume"}, headers=auth["approver"])
    assert d.status_code == 200 and d.json()["extended"] is True
    after = client.get(f"/api/requests/{rid}", headers=auth["analyst"]).json()
    assert after["due_at"] > before and after["extended"]
    second = client.post(f"/api/requests/{rid}/extension", json={"reason": "yet another extension"}, headers=auth["analyst"])
    assert second.status_code == 400 and second.json()["error"]["code"] == "EXTENSION_ALREADY_USED"
    assert client.post(f"/api/requests/{rid}/extension", json={"decision": "APPROVED", "reason": "x" * 6}, headers=auth["analyst"]).status_code == 403
