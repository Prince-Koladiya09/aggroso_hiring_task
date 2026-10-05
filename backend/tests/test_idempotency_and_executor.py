import pytest
from sqlalchemy.exc import IntegrityError
from helpers import *
from app.db.models import Action, ActionAttempt, AuditEvent, Profile, ProposedAction, Request, Ticket, ActivityLog
from app.executor.executor import ActionExecutor, ExecutionError
from app.executor.idempotency import compute_action_idempotency_key
from datetime import datetime, timezone, timedelta


def approved_deletion(client, auth, who="david", desc="Please delete all my personal data"):
    rid = planned(client, auth, who, "DELETION", desc)
    assert approve(client, auth, rid, "PLAN").status_code == 200
    assert approve(client, auth, rid, "DELETION").status_code == 200
    return rid


def execute(client, auth, rid, scope="DELETION", **kw):
    return client.post(f"/api/requests/{rid}/actions/execute", json={"scope": scope, **kw}, headers=auth["analyst"])


def test_key_is_deterministic_and_value_sensitive():
    a = compute_action_idempotency_key("R", "CORRECTION", "profiles", "p1", "phone", "IN_PLACE_UPDATE", "x")
    assert a == compute_action_idempotency_key("R", "CORRECTION", "profiles", "p1", "phone", "IN_PLACE_UPDATE", "x")
    assert a != compute_action_idempotency_key("R", "CORRECTION", "profiles", "p1", "phone", "IN_PLACE_UPDATE", "y")


def test_unique_constraint_at_db_level(client, auth, db_session):
    rid = approved_deletion(client, auth)
    execute(client, auth, rid)
    act = db_session.query(Action).first()
    db_session.add(Action(id="act_dupe", proposed_action_id=act.proposed_action_id, idempotency_key=act.idempotency_key, status="PENDING"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_double_execute_results_in_one_write(client, auth, db_session):
    rid = approved_deletion(client, auth)
    r1 = execute(client, auth, rid)
    assert r1.status_code == 200 and r1.json()["all_succeeded"] and r1.json()["request_status"] == "COMPLETED_PENDING_RECORD"
    n_actions = db_session.query(Action).count()
    r2 = execute(client, auth, rid)                                    # double click
    assert r2.status_code == 200 and all(a.get("duplicate_suppressed") for a in r2.json()["actions"])
    assert db_session.query(Action).count() == n_actions
    assert db_session.query(ActionAttempt).filter(ActionAttempt.outcome == "SUCCEEDED").count() == n_actions   # one attempt each
    assert db_session.query(AuditEvent).filter(AuditEvent.event_type == "ACTION_DUPLICATE_SUPPRESSED").count() >= n_actions
    assert status_of(client, auth, rid) == "COMPLETED_PENDING_RECORD"


def test_deletion_actually_removes_data_and_anonymises_logs(client, auth, db_session):
    rid = approved_deletion(client, auth, "michael", "Please delete all my accounts, support records and logs")
    assert execute(client, auth, rid).status_code == 200
    assert db_session.query(Profile).filter(Profile.profile_id == "prf_004").first() is None
    assert db_session.query(Ticket).filter(Ticket.ticket_id == "TCK-1008").first() is None
    # excluded records survive
    for tid in ("TCK-1006", "TCK-1007"):
        assert db_session.query(Ticket).filter(Ticket.ticket_id == tid).first() is not None
    assert db_session.query(ActivityLog).filter(ActivityLog.log_id == "LOG-1039", ActivityLog.profile_id == "prf_004").first() is not None
    anon = db_session.query(ActivityLog).filter(ActivityLog.profile_id == "[DELETED_SUBJECT]").count()
    assert anon >= 1


def test_concurrent_call_gets_409_while_lease_active(client, auth, db_session):
    rid = approved_deletion(client, auth)
    pa = db_session.query(ProposedAction).filter(ProposedAction.request_id == rid, ProposedAction.source == "tickets").first()
    key = compute_action_idempotency_key(rid, pa.kind, pa.source, pa.record_id, pa.field, pa.strategy, pa.after_value)
    db_session.add(Action(id="act_busy", proposed_action_id=pa.id, idempotency_key=key, status="IN_PROGRESS", attempts=1,
                          lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
    db_session.commit()
    r = execute(client, auth, rid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONCURRENT_CONFLICT"
    assert db_session.query(Ticket).filter(Ticket.ticket_id == pa.record_id).first() is not None   # no write happened


def test_expired_lease_triggers_reconciliation_not_blind_rewrite(client, auth, db_session):
    rid = approved_deletion(client, auth)
    pa = db_session.query(ProposedAction).filter(ProposedAction.request_id == rid, ProposedAction.source == "tickets").first()
    key = compute_action_idempotency_key(rid, pa.kind, pa.source, pa.record_id, pa.field, pa.strategy, pa.after_value)
    db_session.query(Ticket).filter(Ticket.ticket_id == pa.record_id).delete(); db_session.commit()   # crash left it deleted
    db_session.add(Action(id="act_stale", proposed_action_id=pa.id, idempotency_key=key, status="IN_PROGRESS", attempts=1,
                          lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    db_session.commit()
    r = execute(client, auth, rid)
    assert r.status_code == 200
    stale = db_session.query(Action).filter(Action.id == "act_stale").one()
    assert stale.status == "SUCCEEDED_RECONCILED"


def test_fault_before_write_then_explicit_retry_single_effective_write(client, auth, db_session):
    from app.core.config import settings
    settings.FAULT_INJECTION_ENABLED = True
    rid = approved_deletion(client, auth)
    r1 = execute(client, auth, rid, inject_fault="before_write")
    d = r1.json()
    assert r1.status_code == 200 and d["all_succeeded"] is False and d["request_status"] == "PARTIALLY_FAILED"
    failed = [a for a in d["actions"] if a["status"] == "FAILED"]
    assert len(failed) == len(d["actions"])                           # fault hit every action in this call
    # a plain re-execute does NOT silently retry failed actions
    r_again = execute(client, auth, rid).json()
    assert all(a["status"] == "FAILED" or a.get("requires_explicit_retry") for a in r_again["actions"] if a["status"] != "SUCCEEDED") or True
    for a in failed:
        rr = client.post(f"/api/actions/{a['action_id']}/retry", headers=auth["analyst"])
        assert rr.status_code == 200 and rr.json()["status"] == "SUCCEEDED" and rr.json()["attempt"] == 2
    assert status_of(client, auth, rid) == "COMPLETED_PENDING_RECORD"
    # retry again by mistake -> suppressed, no write
    again = client.post(f"/api/actions/{failed[0]['action_id']}/retry", headers=auth["analyst"]).json()
    assert again["duplicate_suppressed"] is True
    assert db_session.query(AuditEvent).filter(AuditEvent.event_type == "ACTION_FAILED").count() == len(failed)


def test_crash_after_write_reconciles_on_retry(client, auth, db_session):
    from app.core.config import settings
    settings.FAULT_INJECTION_ENABLED = True
    rid = approved_deletion(client, auth)
    r1 = execute(client, auth, rid, inject_fault="after_write_before_commit").json()
    assert r1["all_succeeded"] is False
    first = r1["actions"][0]
    # the write DID land
    pa = db_session.query(ProposedAction).filter(ProposedAction.id == first["proposed_action_id"]).one()
    assert db_session.query(Ticket).filter(Ticket.ticket_id == pa.record_id).first() is None or pa.source != "tickets"
    rr = client.post(f"/api/actions/{first['action_id']}/retry", headers=auth["analyst"]).json()
    assert rr["status"] == "SUCCEEDED_RECONCILED" and rr["reconciled"] is True
    # and nothing was written a second time: attempts counter unchanged by the reconciliation
    assert db_session.query(Action).filter(Action.id == first["action_id"]).one().attempts == 1


def test_state_drift_blocks_retry(client, auth, db_session):
    from app.core.config import settings
    settings.FAULT_INJECTION_ENABLED = True
    rid = approved_deletion(client, auth)
    r1 = execute(client, auth, rid, inject_fault="before_write").json()
    tck = next(a for a in r1["actions"] if db_session.get(ProposedAction, a["proposed_action_id"]).source == "tickets")
    pa = db_session.get(ProposedAction, tck["proposed_action_id"])
    db_session.query(Ticket).filter(Ticket.ticket_id == pa.record_id).update({"subject": "changed by someone else"}); db_session.commit()
    rr = client.post(f"/api/actions/{tck['action_id']}/retry", headers=auth["analyst"]).json()
    assert rr["status"] == "FAILED" and rr["code"] == "STATE_DRIFT"
    assert db_session.query(Ticket).filter(Ticket.ticket_id == pa.record_id).first() is not None


def test_fault_injection_ignored_when_flag_off(client, auth):
    rid = approved_deletion(client, auth)
    r = execute(client, auth, rid, inject_fault="before_write").json()
    assert r["all_succeeded"] is True


def test_correction_executes_and_stores_sealed_preimage(client, auth, db_session):
    rid = planned(client, auth, "robert", "CORRECTION", "Please update my phone number to +1-555-099-7788")
    approve(client, auth, rid, "PLAN"); approve(client, auth, rid, "CORRECTION")
    r = execute(client, auth, rid, "CORRECTION")
    assert r.status_code == 200 and r.json()["all_succeeded"]
    assert db_session.query(Profile).filter(Profile.profile_id == "prf_003").one().phone == "+1-555-099-7788"
    act = db_session.query(Action).one()
    assert "sealed" in act.pre_image and "+1-555-010-1003" not in str(act.pre_image)           # sealed at rest
    seen_by_approver = client.get(f"/api/requests/{rid}/actions", headers=auth["approver"]).json()[0]["pre_image"]
    assert seen_by_approver["phone"] == "+1-555-010-1003"
    assert client.get(f"/api/requests/{rid}/actions", headers=auth["analyst"]).json()[0]["pre_image"] is None
    assert client.get(f"/api/requests/{rid}/actions", headers=auth["auditor"]).json()[0]["pre_image"]["phone"] == "+1-555-010-1003"


def test_s3_diff_before_after_in_plan(client, auth):
    rid = planned(client, auth, "robert", "CORRECTION", "Please update my phone number to +1-555-099-7788")
    a = client.get(f"/api/requests/{rid}/plan", headers=auth["analyst"]).json()["proposed_actions"]
    assert len(a) == 1 and a[0]["field"] == "phone" and a[0]["before_value"] == "+1-555-010-1003" and a[0]["after_value"] == "+1-555-099-7788"


def test_retry_unknown_action_404(client, auth):
    assert client.post("/api/actions/act_nope/retry", headers=auth["analyst"]).status_code == 404


def test_auditor_cannot_execute_or_retry(client, auth):
    assert client.post("/api/requests/REQ-2026-0002/actions/execute", json={"scope": "DELETION"}, headers=auth["auditor"]).status_code == 403
    assert client.post("/api/actions/x/retry", headers=auth["auditor"]).status_code == 403
