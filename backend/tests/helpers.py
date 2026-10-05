"""Flow helpers shared by the API-level tests."""
PEOPLE = {
    "john": ("John Doe", "john.doe@example.com", "ACC-1001"),
    "robert": ("Robert Taylor", "robert.taylor@example.com", "ACC-1003"),
    "michael": ("Michael Brown", "michael.brown@example.com", "ACC-1004"),
    "david": ("David Wilson", "david.wilson@example.com", "ACC-1005"),
    "emily": ("Emily Davis", "emily.davis@example.com", "ACC-1007"),
    "carlos": ("Carlos Gomez", "carlos.gomez@example.com", "ACC-1008"),
}


def create(client, auth, who, rtype, description, **extra):
    name, email, acc = PEOPLE[who]
    body = {"type": rtype, "requester_name": name, "requester_email": email, "account_id": acc, "relationship": "self",
            "description": description}
    body.update(extra)
    r = client.post("/api/requests", json=body, headers=auth["analyst"])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def verify(client, auth, req_id, who, level2=False, otp=None):
    name, email, acc = PEOPLE[who]
    body = {"name": name, "email": email, "account_id": acc}
    if level2:
        sent = client.post(f"/api/requests/{req_id}/verification/send-otp", headers=auth["analyst"])
        assert sent.status_code == 200, sent.text
        body["otp"] = otp or sent.json()["simulated_outbox"]["otp_code"]
    r = client.post(f"/api/requests/{req_id}/verification", json=body, headers=auth["analyst"])
    return r


def verified_request(client, auth, who, rtype, description):
    rid = create(client, auth, who, rtype, description)
    r = verify(client, auth, rid, who, level2=rtype != "ACCESS")
    assert r.status_code == 200 and r.json()["result"] == "PASSED", r.text
    return rid


def run_agent(client, auth, rid):
    return client.post(f"/api/requests/{rid}/agent/run", headers=auth["analyst"])


def approve(client, auth, rid, scope, who="approver", decision="APPROVED", reason="Reviewed and approved per policy."):
    return client.post(f"/api/requests/{rid}/approvals", json={"scope": scope, "decision": decision, "reason": reason},
                       headers=auth[who])


def status_of(client, auth, rid):
    return client.get(f"/api/requests/{rid}", headers=auth["analyst"]).json()["status"]


def planned(client, auth, who, rtype, description):
    rid = verified_request(client, auth, who, rtype, description)
    r = run_agent(client, auth, rid)
    assert r.status_code == 200, r.text
    return rid
