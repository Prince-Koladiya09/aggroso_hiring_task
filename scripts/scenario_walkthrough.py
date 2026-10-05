import requests, json
B="http://localhost:8000/api"
def tok(u,p): return {"Authorization":"Bearer "+requests.post(B+"/auth/login",json={"username":u,"password":p}).json()["access_token"]}
A=tok("alex.analyst","analyst_password123!"); J=tok("jordan.approver","approver_password123!"); M=tok("morgan.approver","approver_password123!"); S=tok("sam.auditor","auditor_password123!")
def post(p,h,j=None): return requests.post(B+p,headers=h,json=j)
def get(p,h): return requests.get(B+p,headers=h).json()
def mk(t,name,email,acc,desc,**k): 
    r=post("/requests",A,dict(type=t,requester_name=name,requester_email=email,account_id=acc,description=desc,**k)); assert r.status_code==201,r.text; return r.json()["id"]
def ver(rid,name,email,acc,l2=False):
    b=dict(name=name,email=email,account_id=acc)
    if l2: b["otp"]=post(f"/requests/{rid}/verification/send-otp",A).json()["simulated_outbox"]["otp_code"]
    return post(f"/requests/{rid}/verification",A,b).json()
st=lambda r:get(f"/requests/{r}",A)["status"]
print("S9 dashboard:",[(r["id"],r["deadline"]["deadline_status"]) for r in get("/requests",A)])
# S1
r=mk("ACCESS","John Doe","john.doe@example.com","ACC-1001","Please provide a copy of all my data"); print("S1 verify",ver(r,"John Doe","john.doe@example.com","ACC-1001")["result"]); post(f"/requests/{r}/agent/run",A); post(f"/requests/{r}/approvals",J,dict(scope="PLAN",decision="APPROVED",reason="Plan reviewed ok"))
e=post(f"/requests/{r}/export",A).json(); print("S1 leak",e["leak_scan"]["passed"],e["redaction_report"]["total_redactions"]); print("S1 release",post(f"/requests/{r}/export/{e['export_id']}/release",J,dict(reason="diff reviewed")).status_code)
print("S1 record",post(f"/requests/{r}/fulfilment-record",A,dict(narrative_override="Access export released after redaction review.")).status_code, st(r))
# S2 missing info
r2=post("/requests",A,dict(type="DELETION",requester_name="Jane Smith",requester_email="jane.smith@example.com",description="Please erase all my data")).json()["id"]
print("S2",st(r2),[ (m["item"],m["policy_rule"]) for m in get(f"/requests/{r2}",A)["missing_verification"]])
# S3
r3=mk("CORRECTION","Robert Taylor","robert.taylor@example.com","ACC-1003","Please update my phone number to +1-555-099-7788"); print("S3 verify",ver(r3,"Robert Taylor","robert.taylor@example.com","ACC-1003",True)["result"])
post(f"/requests/{r3}/agent/run",A); print("S3 diff",[(a["field"],a["before_value"],a["after_value"]) for a in get(f"/requests/{r3}/plan",A)["proposed_actions"]])
print("S3 exec before approval:",post(f"/requests/{r3}/actions/execute",A,dict(scope="CORRECTION")).json()["error"]["code"])
post(f"/requests/{r3}/approvals",J,dict(scope="PLAN",decision="APPROVED",reason="Plan ok fine")); print("S3 exec after plan-only:",post(f"/requests/{r3}/actions/execute",A,dict(scope="CORRECTION")).json()["error"]["code"])
post(f"/requests/{r3}/approvals",J,dict(scope="CORRECTION",decision="APPROVED",reason="Correction approved")); x=post(f"/requests/{r3}/actions/execute",A,dict(scope="CORRECTION")).json(); print("S3 exec",x["all_succeeded"]); print("S3 double-click suppressed:",post(f"/requests/{r3}/actions/execute",A,dict(scope="CORRECTION")).json()["actions"][0].get("duplicate_suppressed"))
# S4/S5
requests.post(B+"/system/toggle-fault-injection?enabled=true",headers=A)
r4=mk("DELETION","Michael Brown","michael.brown@example.com","ACC-1004","Please delete all my accounts, support records, and activity logs permanently."); ver(r4,"Michael Brown","michael.brown@example.com","ACC-1004",True); post(f"/requests/{r4}/agent/run",A)
post(f"/requests/{r4}/approvals",J,dict(scope="PLAN",decision="APPROVED",reason="Plan ok fine")); print("S4 4-eyes (analyst-initiated; approver differs):",post(f"/requests/{r4}/approvals",M,dict(scope="DELETION",decision="APPROVED",reason="Exclusions confirmed")).status_code)
x=post(f"/requests/{r4}/actions/execute",A,dict(scope="DELETION")).json(); print("S5 first run (fault on first action):",[a["status"] for a in x["actions"]][:3],x["request_status"])
f=[a for a in x["actions"] if a["status"]=="FAILED"]
for a in f: rr=post(f"/actions/{a['action_id']}/retry",A).json(); 
print("S5 retry ->",rr["status"],"attempt",rr["attempt"],"| dup retry:",post(f"/actions/{f[0]['action_id']}/retry",A).json().get("duplicate_suppressed"),"| state",st(r4))
requests.post(B+"/system/toggle-fault-injection?enabled=false",headers=A)
# S6
r6=mk("ACCESS","Emily Davis","emily.davis@example.com","ACC-1007","Export my support communications and logs."); ver(r6,"Emily Davis","emily.davis@example.com","ACC-1007"); post(f"/requests/{r6}/agent/run",A); post(f"/requests/{r6}/approvals",J,dict(scope="PLAN",decision="APPROVED",reason="Plan ok fine"))
e=post(f"/requests/{r6}/export",A).json(); txt=json.dumps(get(f"/requests/{r6}/export/{e['export_id']}",A)["content"]); print("S6 Marcus leaked?",any(x in txt for x in ("Marcus Vance","marcus.vance@","992-12-8811")),"leak scan",e["leak_scan"]["passed"])
# S7
r7=mk("DELETION","Carlos Gomez","carlos.gomez@example.com","ACC-1008","Erase my account details."); ver(r7,"Carlos Gomez","carlos.gomez@example.com","ACC-1008",True); post(f"/requests/{r7}/agent/run",A); a7=get(f"/requests/{r7}/plan",A); print("S7 actions",{a['source'] for a in a7['proposed_actions']},"discarded",len(a7['plan'].get('discarded_proposals',[])))
# S8
r8=mk("ACCESS","Alex Green","alex.green.work@corp.com","ACC-1009","Export all records for Alex Green."); print("S8",post(f"/requests/{r8}/verification",A,dict(name="Alex Green")).json()["failed_fields"])
# S10
requests.post(B+"/system/toggle-llm-outage?enabled=true",headers=A)
r10=mk("CORRECTION","Robert Taylor","robert.taylor@example.com","ACC-1003","Please update my phone number to +1-555-011-2233"); ver(r10,"Robert Taylor","robert.taylor@example.com","ACC-1003",True); x=post(f"/requests/{r10}/agent/run",A).json(); print("S10 fallback_used",x["fallback_used"],get(f"/requests/{r10}/plan",A)["source"])
requests.post(B+"/system/toggle-llm-outage?enabled=false",headers=A)
print("audit chain:",get("/audit/verify",S))
