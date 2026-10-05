from helpers import *
from app.policy.engine import PolicyEngine
from app.db.models import InventoryItem, ProposedAction


def engine(policy): return PolicyEngine(policy)


def test_legal_hold_blocks_delete_and_correct(policy):
    e = engine(policy)
    rec = {"legal_hold": True}
    assert e.check_can_delete("tickets", rec)[:2] == (False, ["POL-RET-1"])
    assert e.check_can_correct("profiles", rec, "phone")[:2] == (False, ["POL-RET-1"])


def test_billing_blocks_delete_only(policy):
    e = engine(policy)
    assert e.check_can_delete("tickets", {"retention_class": "billing"})[:2] == (False, ["POL-RET-2"])


def test_security_audit_blocks_delete(policy):
    assert engine(policy).check_can_delete("activity_logs", {"retention_class": "security_audit"})[:2] == (False, ["POL-RET-3"])


def test_only_editable_fields_correctable(policy):
    e = engine(policy)
    for bad in ("account_id", "risk_score", "password_hash", "legal_hold", "profile_id"):
        ok, rules, _ = e.check_can_correct("profiles", {}, bad)
        assert not ok and rules == ["POL-COR-1"]
    for good in policy.editable_subject_fields:
        assert e.check_can_correct("profiles", {}, good)[0]


def test_unknown_rule_ids_are_dropped(policy):
    assert engine(policy).validate_rule_ids(["POL-RET-1", "POL-FAKE-9", "POL-RET-1"]) == ["POL-RET-1"]


def test_s4_plan_excludes_hold_billing_and_security_audit(client, auth):
    rid = planned(client, auth, "michael", "DELETION", "Please delete all my accounts, support records, and activity logs permanently.")
    inv = {i["record_id"]: i for i in client.get(f"/api/requests/{rid}/inventory", headers=auth["analyst"]).json()}
    assert inv["TCK-1006"]["decision"] == "EXCLUDE_RETENTION" and inv["TCK-1006"]["rule_ids"] == ["POL-RET-1"]
    assert inv["TCK-1007"]["decision"] == "EXCLUDE_RETENTION" and inv["TCK-1007"]["rule_ids"] == ["POL-RET-2"]
    assert inv["LOG-1039"]["decision"] == "EXCLUDE_RETENTION" and inv["LOG-1039"]["rule_ids"] == ["POL-RET-3"]
    targets = {a["record_id"] for a in client.get(f"/api/requests/{rid}/plan", headers=auth["analyst"]).json()["proposed_actions"]}
    assert not targets & {"TCK-1006", "TCK-1007", "LOG-1039"}
    assert "TCK-1008" in targets


def test_activity_logs_are_anonymised_not_hard_deleted(client, auth):
    rid = planned(client, auth, "michael", "DELETION", "Please delete all my accounts and activity logs")
    acts = client.get(f"/api/requests/{rid}/plan", headers=auth["analyst"]).json()["proposed_actions"]
    assert {a["strategy"] for a in acts if a["source"] == "activity_logs"} == {"ANONYMIZE"}
    assert {a["strategy"] for a in acts if a["source"] == "tickets"} == {"HARD_DELETE"}


def test_override_cannot_weaken_deterministic_exclusion(client, auth):
    rid = planned(client, auth, "michael", "DELETION", "Please delete all my accounts and records")
    inv = {i["record_id"]: i for i in client.get(f"/api/requests/{rid}/inventory", headers=auth["analyst"]).json()}
    for rec, rule in (("TCK-1006", "POL-RET-1"), ("TCK-1007", "POL-RET-2"), ("LOG-1039", "POL-RET-3")):
        r = client.patch(f"/api/requests/{rid}/inventory/{inv[rec]['id']}", json={"decision": "INCLUDE", "reason": "I really want this deleted"},
                         headers=auth["analyst"])
        assert r.status_code == 400 and r.json()["error"]["code"] == "RETENTION_VIOLATION" and rule in r.json()["error"]["rule_ids"]
    # and an analyst cannot forge EXCLUDE_RETENTION onto a normal record either
    r = client.patch(f"/api/requests/{rid}/inventory/{inv['TCK-1008']['id']}", json={"decision": "EXCLUDE_RETENTION", "reason": "pretend hold"},
                     headers=auth["analyst"])
    assert r.status_code == 400


def test_override_requires_reason(client, auth):
    rid = planned(client, auth, "michael", "DELETION", "Please delete all my accounts and records")
    inv = client.get(f"/api/requests/{rid}/inventory", headers=auth["analyst"]).json()
    item = next(i for i in inv if i["record_id"] == "TCK-1008")
    r = client.patch(f"/api/requests/{rid}/inventory/{item['id']}", json={"decision": "EXCLUDE_UNRELATED", "reason": ""}, headers=auth["analyst"])
    assert r.status_code == 400 and r.json()["error"]["code"] == "REASON_REQUIRED"


def test_excluding_item_blocks_its_action_and_bumps_inventory_version(client, auth, db_session):
    rid = planned(client, auth, "michael", "DELETION", "Please delete all my accounts and records")
    inv = client.get(f"/api/requests/{rid}/inventory", headers=auth["analyst"]).json()
    item = next(i for i in inv if i["record_id"] == "TCK-1008")
    r = client.patch(f"/api/requests/{rid}/inventory/{item['id']}", json={"decision": "EXCLUDE_UNRELATED", "reason": "Keep: open complaint"},
                     headers=auth["analyst"])
    assert r.status_code == 200 and r.json()["inventory_version"] == 2
    pa = db_session.query(ProposedAction).filter(ProposedAction.request_id == rid, ProposedAction.record_id == "TCK-1008").one()
    assert pa.status == "BLOCKED"
    assert all(i["inventory_version"] == 2 for i in client.get(f"/api/requests/{rid}/inventory", headers=auth["analyst"]).json())


def test_correction_of_non_editable_field_rejected_by_plan_validation(client, auth):
    rid = verified_request(client, auth, "robert", "CORRECTION", "Please update my risk_score to 0 and my phone to +1-555-099-7788")
    plan = run_agent(client, auth, rid)
    assert plan.status_code == 200
    acts = client.get(f"/api/requests/{rid}/plan", headers=auth["analyst"]).json()["proposed_actions"]
    assert {a["field"] for a in acts} == {"phone"}
