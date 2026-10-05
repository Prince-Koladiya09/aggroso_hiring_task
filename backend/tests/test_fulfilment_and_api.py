import pytest
from helpers import *
from app.db.models import FulfilmentRecord
from app.db.guards import ImmutableRecordError


def finish_deletion(client, auth, who="michael", fault=False):
    from app.core.config import settings
    settings.FAULT_INJECTION_ENABLED = fault
    rid = planned(client, auth, who, "DELETION", "Please delete all my accounts, support records and logs")
    approve(client, auth, rid, "PLAN", who="approver"); approve(client, auth, rid, "DELETION", who="approver2")
    r = client.post(f"/api/requests/{rid}/actions/execute", json={"scope": "DELETION", **({"inject_fault": "before_write"} if fault else {})}, headers=auth["analyst"]).json()
    if fault:
        for a in r["actions"]:
            client.post(f"/api/actions/{a['action_id']}/retry", headers=auth["analyst"])
            client.post(f"/api/actions/{a['action_id']}/retry", headers=auth["analyst"])      # duplicate click
    return rid


def test_record_has_all_required_sections(client, auth):
    rid = finish_deletion(client, auth, fault=True)
    draft = client.get(f"/api/requests/{rid}/fulfilment-record/draft", headers=auth["analyst"]).json()
    assert draft["source"] == "AI_DRAFTED" and draft["narrative"].startswith("AI-drafted, reviewed by human")
    r = client.post(f"/api/requests/{rid}/fulfilment-record", json={"narrative": draft["narrative"], "narrative_source": "AI_DRAFTED", "confirm_narrative": True},
                    headers=auth["analyst"])
    assert r.status_code == 200, r.text
    c = r.json()["content"]
    for k in ("request", "verification", "plan", "inventory", "approvals", "actions", "failures", "export", "tool_calls", "llm_runs", "timeline", "disclaimer", "policy_version", "sla_outcome"):
        assert k in c, k
    assert c["verification"]["level"] == 2 and c["request"]["deadline_outcome"] == "ON_TIME"
    assert {e["rule_ids"][0] for e in c["inventory"]["exclusions"] if e["decision"] == "EXCLUDE_RETENTION"} == {"POL-RET-1", "POL-RET-2", "POL-RET-3"}
    assert c["actions"]["executed"] == c["actions"]["proposed"] and c["actions"]["duplicates_executed"] == 0 and c["actions"]["duplicates_suppressed"] >= 1
    assert c["actions"]["retried"] >= 1 and len(c["failures"]) >= 1
    dele = next(a for a in c["approvals"] if a["scope"] == "DELETION")
    assert dele["differs_from_initiator"] is True and dele["action_set_hash"]
    assert "does not provide legal advice" in c["disclaimer"].lower()
    assert status_of(client, auth, rid) == "CLOSED"


def test_ai_narrative_requires_human_confirmation(client, auth):
    rid = finish_deletion(client, auth)
    draft = client.get(f"/api/requests/{rid}/fulfilment-record/draft", headers=auth["analyst"]).json()
    r = client.post(f"/api/requests/{rid}/fulfilment-record", json={"narrative": draft["narrative"], "narrative_source": "AI_DRAFTED"}, headers=auth["analyst"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "NARRATIVE_CONFIRMATION_REQUIRED"
    assert status_of(client, auth, rid) == "COMPLETED_PENDING_RECORD"
    assert client.post(f"/api/requests/{rid}/fulfilment-record", json={"narrative_override": "Written by me after review."}, headers=auth["analyst"]).status_code == 200


def test_record_is_immutable(client, auth, db_session):
    rid = finish_deletion(client, auth)
    first = client.post(f"/api/requests/{rid}/fulfilment-record", json={"narrative_override": "First narrative."}, headers=auth["analyst"]).json()
    second = client.post(f"/api/requests/{rid}/fulfilment-record", json={"narrative_override": "Overwrite attempt!"}, headers=auth["analyst"]).json()
    assert second["created"] is False and second["narrative"] == "First narrative." and second["id"] == first["id"]
    assert client.put(f"/api/requests/{rid}/fulfilment-record", json={}, headers=auth["analyst"]).status_code == 405
    rec = db_session.query(FulfilmentRecord).one()
    rec.narrative = "tampered"
    with pytest.raises(ImmutableRecordError):
        db_session.flush()
    db_session.rollback()


def test_record_cannot_be_generated_early(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of all my data")
    r = client.post(f"/api/requests/{rid}/fulfilment-record", json={"narrative_override": "too early please"}, headers=auth["analyst"])
    assert r.status_code == 409


def test_s1_full_access_happy_path(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of all my data")
    assert approve(client, auth, rid, "PLAN").status_code == 200
    eid = client.post(f"/api/requests/{rid}/export", headers=auth["analyst"]).json()["export_id"]
    assert client.post(f"/api/requests/{rid}/export/{eid}/release", json={"reason": "Redaction diff reviewed"}, headers=auth["approver"]).status_code == 200
    r = client.post(f"/api/requests/{rid}/fulfilment-record", json={"narrative_override": "Access export released after review."}, headers=auth["analyst"])
    c = r.json()["content"]
    assert c["export"]["leak_scan_passed"] and c["export"]["total_redactions"] > 0 and c["export"]["redactions_by_rule"]["POL-RED-3"] >= 1
    assert client.get("/api/audit/verify", headers=auth["auditor"]).json()["is_valid"]


# ---------------------------------------------------------------- API contract
def test_unauthenticated_requests_get_401(client):
    for path in ("/api/requests", "/api/requests/REQ-2026-0001", "/api/audit/verify", "/api/policy"):
        r = client.get(path)
        assert r.status_code in (401, 200) and (r.status_code == 401 or path == "/api/policy")
    assert client.get("/api/requests").json()["error"]["code"] == "UNAUTHENTICATED"


def test_bad_token_401(client):
    assert client.get("/api/requests", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_validation_error_uses_standard_body(client, auth):
    r = client.post("/api/requests", json={"type": "ACCESS", "requester_name": "J", "requester_email": "nope", "description": "x"}, headers=auth["analyst"])
    assert r.status_code == 422
    e = r.json()["error"]
    assert e["code"] == "VALIDATION_ERROR" and e["correlation_id"].startswith("corr-") and {f["field"] for f in e["fields"]} >= {"requester_name", "requester_email", "description"}
    assert r.headers["X-Correlation-ID"] == e["correlation_id"]


def test_future_received_date_rejected(client, auth):
    r = client.post("/api/requests", json={"type": "ACCESS", "requester_name": "John Doe", "requester_email": "john.doe@example.com",
                                           "account_id": "ACC-1001", "description": "copy of data please", "received_at": "2099-01-01T00:00:00Z"}, headers=auth["analyst"])
    assert r.status_code == 422


def test_backdated_received_date_sets_due_date_and_badge(client, auth):
    from datetime import datetime, timezone, timedelta
    recv = (datetime.now(timezone.utc) - timedelta(days=26)).isoformat()
    r = client.post("/api/requests", json={"type": "ACCESS", "requester_name": "John Doe", "requester_email": "john.doe@example.com",
                                           "account_id": "ACC-1001", "description": "copy of data please", "received_at": recv}, headers=auth["analyst"]).json()
    assert r["deadline"]["deadline_status"] == "AT_RISK"


def test_role_matrix(client, auth):
    assert client.post("/api/requests", json={}, headers=auth["approver"]).status_code == 403
    assert client.post("/api/requests", json={}, headers=auth["auditor"]).status_code == 403
    assert client.post("/api/requests/REQ-2026-0003/agent/run", headers=auth["auditor"]).status_code == 403
    assert client.get("/api/approvals/queue", headers=auth["analyst"]).status_code == 403
    assert client.post("/api/system/reset-demo", headers=auth["analyst"]).status_code == 403
    assert client.get("/api/requests", headers=auth["auditor"]).status_code == 200


def test_404_and_unknown_api_route(client, auth):
    assert client.get("/api/requests/REQ-NOPE", headers=auth["analyst"]).status_code == 404
    assert client.get("/api/requests/REQ-NOPE", headers=auth["analyst"]).json()["error"]["code"] == "NOT_FOUND"


def test_dashboard_filters_and_s9_badges(client, auth):
    rows = client.get("/api/requests", headers=auth["analyst"]).json()
    by = {r["id"]: r["deadline"]["deadline_status"] for r in rows}
    assert by["REQ-2026-0001"] == "AT_RISK" and by["REQ-2026-0002"] == "OVERDUE" and by["REQ-2026-0003"] == "ON_TRACK"
    assert [r["id"] for r in client.get("/api/requests?deadline=OVERDUE", headers=auth["analyst"]).json()] == ["REQ-2026-0002"]
    assert all(r["type"] == "ACCESS" for r in client.get("/api/requests?type=ACCESS", headers=auth["analyst"]).json())
    due = [r["due_at"] for r in client.get("/api/requests?sort=due", headers=auth["analyst"]).json()]
    assert due == sorted(due)


def test_approval_queue_flags_own_initiated(client, auth):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my data")
    q = client.get("/api/approvals/queue", headers=auth["approver"]).json()
    assert any(x["id"] == rid and x["needs"] == "Plan approval" for x in q)


def test_tool_call_log_visible_to_all_roles(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    for role in ("analyst", "approver", "auditor"):
        assert len(client.get(f"/api/requests/{rid}/tool-calls", headers=auth[role]).json()) >= 3


def test_inventory_csv_download_and_no_restricted_values(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    r = client.get(f"/api/requests/{rid}/inventory/export?format=csv", headers=auth["analyst"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "record_id" in r.text
    inv = client.get(f"/api/requests/{rid}/inventory", headers=auth["analyst"]).text
    assert "mockHash" not in inv


def test_reset_demo_restores_seed(client, auth):
    create(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    assert client.post("/api/system/reset-demo", headers=auth["approver"]).status_code == 200
    from sqlalchemy.orm import Session
    token = client.post("/api/auth/login", json={"username": "alex.analyst", "password": "analyst_password123!"}).json()["access_token"]
    rows = client.get("/api/requests", headers={"Authorization": f"Bearer {token}"}).json()
    assert len(rows) == 3
    assert client.get("/api/audit/verify", headers={"Authorization": f"Bearer {token}"}).json()["is_valid"]


def test_test_accounts_listing(client):
    accts = client.get("/api/auth/test-accounts").json()
    assert {a["role"] for a in accts} == {"analyst", "approver", "auditor"}


def test_policy_endpoint_exposes_rules_and_disclaimer(client, auth):
    p = client.get("/api/policy", headers=auth["analyst"]).json()
    assert "POL-APR-3" in p["rules"] and "not provide legal advice" in p["disclaimer"]


def test_addendum_is_separate_audited_event_and_record_stays_unchanged(client, auth):
    rid = finish_deletion(client, auth)
    assert client.post(f"/api/requests/{rid}/fulfilment-record/addendum", json={"text": "Requester called to confirm."}, headers=auth["analyst"]).status_code == 409
    rec = client.post(f"/api/requests/{rid}/fulfilment-record", json={"narrative_override": "Original narrative text."}, headers=auth["analyst"]).json()
    a = client.post(f"/api/requests/{rid}/fulfilment-record/addendum", json={"text": "Requester called to confirm receipt."}, headers=auth["analyst"])
    assert a.status_code == 200 and a.json()["record_unchanged"]
    after = client.get(f"/api/requests/{rid}/fulfilment-record", headers=auth["auditor"]).json()
    assert after["narrative"] == rec["narrative"] and after["content"] == rec["content"]
    assert after["addenda"][0]["text"] == "Requester called to confirm receipt."
    assert client.post(f"/api/requests/{rid}/fulfilment-record/addendum", json={"text": "x"}, headers=auth["auditor"]).status_code == 403
