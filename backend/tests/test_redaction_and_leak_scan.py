from helpers import *
from app.redaction.engine import RedactionEngine
from app.redaction.leak_scan import scan_for_data_leaks


def eng(**kw):
    base = dict(subject_email="emily.davis@example.com", subject_name="Emily Davis",
                subject_values=["emily.davis@example.com", "+1-555-010-1006"], known_third_party_names=["Rachel Green"])
    base.update(kw)
    return RedactionEngine(**base)


PROFILE = {"profile_id": "prf_006", "full_name": "Emily Davis", "email": "emily.davis@example.com", "phone": "+1-555-010-1006",
           "password_hash": "$2b$xx", "risk_score": 9.0, "fraud_flag": False, "internal_notes": "VIP", "legal_hold": False}
TICKET = {"ticket_id": "TCK-1010", "requester_email": "emily.davis@example.com", "assigned_agent": "Rachel Green", "agent_id": "AGT-009",
          "internal_notes": "n", "retention_class": "standard",
          "subject": "Vendor audit",
          "body": "Please grant access to our external compliance officer Marcus Vance (email: marcus.vance@partner.org, mobile: 555-019-2834, SSN reference: 992-12-8811)."}
LOG = {"log_id": "L1", "profile_id": "prf_006", "event_type": "LOGIN", "details": "Login from home", "ip_address": "10.0.0.1", "user_agent": "UA", "risk_signal": "HIGH"}


def test_restricted_fields_removed_by_classification():
    out, reds = eng().process_record(PROFILE)
    for f in ("password_hash", "risk_score", "fraud_flag", "internal_notes", "legal_hold"):
        assert f not in out
    assert {r["rule"] for r in reds} == {"POL-RED-3", "POL-RED-2"}
    out, _ = eng().process_record(LOG)
    assert "risk_signal" not in out and out["ip_address"] == "10.0.0.1"          # IP is subject data (SRS 8.1)
    out, _ = eng().process_record(TICKET)
    assert "assigned_agent" not in out and "agent_id" not in out and "internal_notes" not in out


def test_third_party_name_email_phone_ssn_masked_in_ticket():
    out, reds = eng().process_record(TICKET)
    b = out["body"]
    for leak in ("Marcus Vance", "marcus.vance@partner.org", "555-019-2834", "992-12-8811"):
        assert leak not in b
    assert b.count("[REDACTED_") >= 4 and {r["rule"] for r in reds if r.get("field") == "body"} == {"POL-RED-1"}


def test_subject_own_values_are_kept():
    rec = {"details": "Contact me at emily.davis@example.com or +1-555-010-1006, Emily Davis"}
    out, reds = eng().process_record(rec)
    assert out["details"] == rec["details"] and reds == []


def test_known_directory_names_are_masked_case_insensitively():
    out, _ = eng().redact_text("handled by rachel green yesterday")
    assert "rachel green" not in out.lower()


def test_llm_suggestions_only_add_redactions():
    base, _ = eng().redact_text("Our contact Zed Quill called")
    plus, _ = eng(suggested_terms=["Quill"]).redact_text("Our contact Zed Quill called")
    assert plus.count("[REDACTED_") >= base.count("[REDACTED_")
    assert "Quill" not in plus
    # a suggestion naming the subject can't *remove* anything either: output is a superset of the baseline masks
    same, _ = eng(suggested_terms=[]).redact_text("Rachel Green")
    assert "[REDACTED_" in same


def test_redaction_diff_labels_each_change_with_rule():
    res = eng().build_export([{"source": "tickets", "record_id": "TCK-1010", "classification": "SUBJECT_PERSONAL", "raw_data": TICKET}])
    d = res["redaction_report"]["diff"]
    body = next(x for x in d if x["field"] == "body")
    assert "Marcus Vance" in body["original"] and "Marcus Vance" not in body["exported"] and body["rules"] == ["POL-RED-1"]
    assert any(x["field"] == "internal_notes" and x["rules"] == ["POL-RED-2"] for x in d)
    assert res["leak_scan"]["passed"]


def test_leak_scan_blocks_deliberately_leaky_export():
    leaky = [{"password_hash": "x", "body": "reach marcus.vance@partner.org, SSN 992-12-8811, Marcus Vance"}]
    bad, found = scan_for_data_leaks(leaky, ["emily.davis@example.com"], ["Marcus Vance"])
    assert bad and len(found) >= 4
    assert any("POL-RED-3" in f for f in found) and any("SSN" in f for f in found) and any("e-mail" in f for f in found)


def test_leak_scan_catches_cue_based_name_without_directory():
    bad, found = scan_for_data_leaks([{"body": "ask our officer Jane Doeson"}], [], [], {"emily"})
    assert bad and any("Doeson" in f for f in found)


def test_html_view_is_escaped():
    res = eng().build_export([{"source": "tickets", "record_id": "T", "classification": "X",
                               "raw_data": {"subject": "<script>alert(1)</script>", "body": "hi"}}])
    assert "<script>alert" not in res["html_view"]


def test_s6_export_through_api_masks_marcus_vance(client, auth):
    rid = planned(client, auth, "emily", "ACCESS", "Please provide a copy of all my personal data.")
    approve(client, auth, rid, "PLAN")
    g = client.post(f"/api/requests/{rid}/export", headers=auth["analyst"])
    assert g.status_code == 200 and g.json()["leak_scan"]["passed"]
    text = str(client.get(f"/api/requests/{rid}/export/{g.json()['export_id']}", headers=auth["approver"]).json()["content"])
    for leak in ("Marcus Vance", "marcus.vance@partner.org", "992-12-8811", "password_hash", "risk_score", "internal_notes", "Rachel Green"):
        assert leak not in text


def test_export_excludes_other_peoples_records(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of all my personal data.")
    approve(client, auth, rid, "PLAN")
    g = client.post(f"/api/requests/{rid}/export", headers=auth["analyst"]).json()
    content = client.get(f"/api/requests/{rid}/export/{g['export_id']}", headers=auth["analyst"]).json()["content"]
    ids = {c["record_id"] for c in content}
    assert "prf_001" in ids and "prf_002" not in ids and "TCK-1004" not in ids


def test_export_requires_approved_plan_and_state(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of all my personal data.")
    r = client.post(f"/api/requests/{rid}/export", headers=auth["analyst"])
    assert r.status_code == 409                                              # plan not approved yet: unapproved items never appear


def test_download_forbidden_until_released_then_allowed(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of all my personal data.")
    approve(client, auth, rid, "PLAN")
    eid = client.post(f"/api/requests/{rid}/export", headers=auth["analyst"]).json()["export_id"]
    assert client.get(f"/api/requests/{rid}/export/{eid}/download", headers=auth["analyst"]).status_code == 403
    assert client.post(f"/api/requests/{rid}/export/{eid}/release", json={"reason": "Redactions verified"}, headers=auth["analyst"]).status_code == 403
    assert client.post(f"/api/requests/{rid}/export/{eid}/release", json={"reason": "Redactions verified"}, headers=auth["approver"]).status_code == 200
    assert client.get(f"/api/requests/{rid}/export/{eid}/download", headers=auth["analyst"]).status_code == 200
    assert client.get(f"/api/requests/{rid}/export/{eid}/download?format=html", headers=auth["approver"]).headers["content-type"].startswith("text/html")
    assert client.get(f"/api/requests/{rid}/export/{eid}/download", headers=auth["auditor"]).status_code == 403
    assert client.post(f"/api/requests/{rid}/export/{eid}/release", json={"reason": "second release"}, headers=auth["approver"]).status_code == 409


def test_leaky_export_release_is_blocked(client, auth, db_session):
    from app.db.models import Export
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of all my personal data.")
    approve(client, auth, rid, "PLAN")
    eid = client.post(f"/api/requests/{rid}/export", headers=auth["analyst"]).json()["export_id"]
    e = db_session.get(Export, eid)
    e.leak_scan_result = {"passed": False, "leaks_found": ["seeded leak"]}; db_session.commit()
    r = client.post(f"/api/requests/{rid}/export/{eid}/release", json={"reason": "please release"}, headers=auth["approver"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "LEAK_SCAN_FAILED"
    assert client.get(f"/api/requests/{rid}/export/{eid}/download", headers=auth["analyst"]).status_code == 403


def test_inventory_change_makes_export_stale(client, auth):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of all my personal data.")
    approve(client, auth, rid, "PLAN")
    eid = client.post(f"/api/requests/{rid}/export", headers=auth["analyst"]).json()["export_id"]
    inv = client.get(f"/api/requests/{rid}/inventory", headers=auth["analyst"]).json()
    client.patch(f"/api/requests/{rid}/inventory/{inv[0]['id']}", json={"decision": "EXCLUDE_UNRELATED", "reason": "Not the subject's"}, headers=auth["analyst"])
    assert status_of(client, auth, rid) == "PLAN_REVIEW"
    assert client.get(f"/api/requests/{rid}/export/{eid}", headers=auth["analyst"]).json()["stale"] is True
