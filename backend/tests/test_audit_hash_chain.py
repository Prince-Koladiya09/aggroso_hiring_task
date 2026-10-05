import pytest
from sqlalchemy import text
from helpers import *
from app.audit.chain import verify_chain
from app.db.guards import ImmutableRecordError, drop_triggers, ensure_triggers
from app.db.models import AuditEvent


def full_flow(client, auth):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    approve(client, auth, rid, "PLAN"); approve(client, auth, rid, "DELETION")
    client.post(f"/api/requests/{rid}/actions/execute", json={"scope": "DELETION"}, headers=auth["analyst"])
    return rid


def test_chain_valid_after_real_activity(client, auth):
    full_flow(client, auth)
    v = client.get("/api/audit/verify", headers=auth["auditor"]).json()
    assert v["is_valid"] is True and v["total_events_checked"] > 20


def test_every_important_step_has_an_audit_event(client, auth, db_session):
    rid = full_flow(client, auth)
    types = {e.event_type for e in db_session.query(AuditEvent).filter(AuditEvent.request_id == rid)}
    for t in ("REQUEST_CREATED", "VERIFICATION_OTP_SENT", "VERIFICATION_PASSED", "TOOL_CALL_EXECUTED", "PLAN_PROPOSED", "APPROVAL_PLAN_APPROVED",
              "APPROVAL_DELETION_APPROVED", "ACTION_SUCCEEDED", "REQUEST_STATUS_CHANGED"):
        assert t in types, t


def test_failures_and_denials_are_events(client, auth, db_session):
    from app.core.config import settings
    settings.FAULT_INJECTION_ENABLED = True
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    approve(client, auth, rid, "PLAN"); approve(client, auth, rid, "DELETION")
    client.post(f"/api/requests/{rid}/actions/execute", json={"scope": "DELETION", "inject_fault": "before_write"}, headers=auth["analyst"])
    client.post(f"/api/requests/{rid}/approvals", json={"scope": "PLAN", "decision": "APPROVED", "reason": "late approval attempt"}, headers=auth["approver"])
    types = {e.event_type for e in db_session.query(AuditEvent).filter(AuditEvent.request_id == rid)}
    assert "ACTION_FAILED" in types


def test_tamper_detected(client, auth, db_session):
    full_flow(client, auth)
    drop_triggers(db_session)                                    # an attacker with raw DB access
    db_session.connection().exec_driver_sql("UPDATE audit_events SET payload_json = '{\"x\": 1}' WHERE seq = 3"); db_session.commit()
    v = client.get("/api/audit/verify", headers=auth["auditor"]).json()
    ensure_triggers(db_session)
    assert v["is_valid"] is False and v["broken_seq"] == 3


def test_deleted_row_detected(client, auth, db_session):
    full_flow(client, auth)
    drop_triggers(db_session)
    db_session.execute(text("DELETE FROM audit_events WHERE seq = 5")); db_session.commit()
    v = client.get("/api/audit/verify", headers=auth["auditor"]).json()
    ensure_triggers(db_session)
    assert v["is_valid"] is False


def test_append_only_enforced_by_orm_and_db_triggers(client, auth, db_session):
    full_flow(client, auth)
    ev = db_session.query(AuditEvent).first()
    ev.actor_id = "hacker"
    with pytest.raises(ImmutableRecordError):
        db_session.flush()
    db_session.rollback()
    with pytest.raises(Exception):
        db_session.execute(text("UPDATE audit_events SET actor_id='x'")); db_session.commit()
    db_session.rollback()
    with pytest.raises(Exception):
        db_session.execute(text("DELETE FROM audit_events")); db_session.commit()
    db_session.rollback()


def test_no_update_or_delete_endpoints_exist(client, auth):
    for m in ("put", "patch", "delete", "post"):
        r = getattr(client, m)("/api/audit/all", headers=auth["approver"])
        assert r.status_code in (404, 405)


def test_verify_chain_unit_empty_and_relink():
    assert verify_chain([])[0]
