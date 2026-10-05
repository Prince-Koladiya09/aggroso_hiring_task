from helpers import *
from app.db.models import ToolCall


def test_level1_pass(client, auth):
    rid = create(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    r = verify(client, auth, rid, "john")
    assert r.json()["result"] == "PASSED" and r.json()["subject_profile_id"] == "prf_001"
    assert status_of(client, auth, rid) == "VERIFIED"


def test_level1_mismatch_reports_field_names_not_stored_values(client, auth):
    rid = create(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    r = client.post(f"/api/requests/{rid}/verification", json={"name": "Wrong Name", "email": "john.doe@example.com", "account_id": "ACC-1001"},
                    headers=auth["analyst"])
    d = r.json()
    assert d["result"] == "FAILED" and d["failed_fields"] == ["name"]
    assert "John Doe" not in r.text and "ACC-1001" not in str(d["failed_fields"])
    assert status_of(client, auth, rid) == "VERIFICATION_FAILED"


def test_failed_then_retry_then_pass(client, auth):
    rid = create(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    client.post(f"/api/requests/{rid}/verification", json={"name": "X Y", "email": "john.doe@example.com", "account_id": "ACC-1001"}, headers=auth["analyst"])
    assert verify(client, auth, rid, "john").json()["result"] == "PASSED"


def test_failed_verification_can_be_closed_by_analyst(client, auth):
    rid = create(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    client.post(f"/api/requests/{rid}/verification", json={"name": "X Y", "email": "john.doe@example.com", "account_id": "ACC-1001"}, headers=auth["analyst"])
    assert client.post(f"/api/requests/{rid}/reject", json={"reason": "Identity not established"}, headers=auth["analyst"]).status_code == 200
    assert status_of(client, auth, rid) == "REJECTED"


def test_level2_requires_otp(client, auth):
    rid = create(client, auth, "robert", "CORRECTION", "Please update my phone number to +1-555-099-7788")
    client.post(f"/api/requests/{rid}/verification/send-otp", headers=auth["analyst"])
    r = client.post(f"/api/requests/{rid}/verification", json={"name": "Robert Taylor", "email": "robert.taylor@example.com", "account_id": "ACC-1003"},
                    headers=auth["analyst"])
    assert r.json()["result"] == "FAILED" and "otp_missing" in r.json()["failed_fields"]


def test_level2_pass_with_correct_otp(client, auth):
    rid = create(client, auth, "robert", "CORRECTION", "Please update my phone number to +1-555-099-7788")
    assert verify(client, auth, rid, "robert", level2=True).json()["result"] == "PASSED"


def test_three_wrong_otps_lock_and_approver_can_unlock(client, auth):
    rid = create(client, auth, "david", "DELETION", "Please delete my data")
    client.post(f"/api/requests/{rid}/verification/send-otp", headers=auth["analyst"])
    body = {"name": "David Wilson", "email": "david.wilson@example.com", "account_id": "ACC-1005"}
    for code in ("000000", "111111"):
        r = client.post(f"/api/requests/{rid}/verification", json={**body, "otp": code}, headers=auth["analyst"])
        assert r.status_code == 200 and r.json()["result"] == "FAILED"
    third = client.post(f"/api/requests/{rid}/verification", json={**body, "otp": "222222"}, headers=auth["analyst"])
    assert third.status_code == 403 and third.json()["error"]["code"] == "VERIFICATION_LOCKED"
    # even the right code is refused while locked
    sent = client.get(f"/api/requests/{rid}/verification", headers=auth["analyst"]).json()
    assert sent["locked"] is True
    assert client.post(f"/api/requests/{rid}/verification/unlock", headers=auth["analyst"]).status_code == 403   # analyst cannot unlock
    assert client.post(f"/api/requests/{rid}/verification/unlock", headers=auth["approver"]).status_code == 200
    assert verify(client, auth, rid, "david", level2=True).json()["result"] == "PASSED"


def test_ambiguous_name_stops_and_never_auto_picks(client, auth):
    rid = client.post("/api/requests", json={"type": "ACCESS", "requester_name": "Alex Green", "requester_email": "alex.green.work@corp.com",
                                             "account_id": "ACC-1009", "description": "Please give me a copy of my data"}, headers=auth["analyst"]).json()["id"]
    r = client.post(f"/api/requests/{rid}/verification", json={"name": "Alex Green"}, headers=auth["analyst"])
    d = r.json()
    assert d["result"] == "FAILED" and "ambiguous_match" in d["failed_fields"] and d["subject_profile_id"] is None


def test_authorized_agent_requires_authorization_flag(client, auth):
    rid = create(client, auth, "john", "ACCESS", "Acting on behalf of John, please send a copy of his data", relationship="authorized_agent")
    d = client.get(f"/api/requests/{rid}", headers=auth["analyst"]).json()
    assert any(m["policy_rule"] == "POL-ID-3" for m in d["missing_verification"]) and d["status"] == "AWAITING_INFO"
    r = verify(client, auth, rid, "john")
    assert r.json()["result"] == "AWAITING_INFO" and "authorization_on_file" in r.json()["failed_fields"]
    ok = client.post(f"/api/requests/{rid}/verification", json={"name": "John Doe", "email": "john.doe@example.com", "account_id": "ACC-1001",
                                                               "authorization_on_file": True}, headers=auth["analyst"])
    assert ok.json()["result"] == "PASSED"


def test_missing_account_id_goes_to_awaiting_info_with_rule_id(client, auth):
    rid = client.post("/api/requests", json={"type": "ACCESS", "requester_name": "Jane Smith", "requester_email": "jane.smith@example.com",
                                             "description": "Please export my profile and history."}, headers=auth["analyst"]).json()["id"]
    d = client.get(f"/api/requests/{rid}", headers=auth["analyst"]).json()
    assert d["status"] == "AWAITING_INFO"
    assert d["missing_verification"][0]["item"] == "account_id" and d["missing_verification"][0]["policy_rule"] == "POL-ID-1"
    # no data-source tool was touched while information is missing (FR-206)
    r = client.post(f"/api/requests/{rid}/verification", json={"name": "Jane Smith", "email": "jane.smith@example.com"}, headers=auth["analyst"])
    assert r.json()["result"] == "AWAITING_INFO"
    # supply the info
    assert client.patch(f"/api/requests/{rid}/info", json={"account_id": "ACC-1002"}, headers=auth["analyst"]).json()["status"] == "VERIFICATION_PENDING"
    ok = client.post(f"/api/requests/{rid}/verification", json={"name": "Jane Smith", "email": "jane.smith@example.com", "account_id": "ACC-1002"},
                     headers=auth["analyst"])
    assert ok.json()["result"] == "PASSED"


def test_verification_for_someone_elses_details_fails(client, auth):
    rid = create(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    r = client.post(f"/api/requests/{rid}/verification", json={"name": "Jane Smith", "email": "jane.smith@example.com", "account_id": "ACC-1002"},
                    headers=auth["analyst"])
    assert r.json()["result"] == "FAILED" and "email" in r.json()["failed_fields"]   # request email != profile email


def test_otp_value_never_logged_in_audit(client, auth):
    rid = create(client, auth, "robert", "CORRECTION", "Please update my phone number to +1-555-099-7788")
    otp = client.post(f"/api/requests/{rid}/verification/send-otp", headers=auth["analyst"]).json()["simulated_outbox"]["otp_code"]
    audit = client.get(f"/api/requests/{rid}/audit", headers=auth["analyst"]).text
    assert otp not in audit


def test_agent_interpretation_lists_missing_info_and_deterministic_checker_wins(client, auth):
    rid = client.post("/api/requests", json={"type": "DELETION", "requester_name": "David Wilson", "requester_email": "david.wilson@example.com",
                                             "description": "Please erase all my data"}, headers=auth["analyst"]).json()["id"]
    r = client.post(f"/api/requests/{rid}/agent/interpret", headers=auth["analyst"])
    assert r.status_code == 200
    items = {m["item"]: m["policy_rule"] for m in r.json()["missing_verification"]}
    assert items == {"account_id": "POL-ID-1", "one_time_code": "POL-ID-2"}
