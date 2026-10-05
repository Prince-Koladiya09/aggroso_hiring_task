import requests, threading, sqlite3
B="http://localhost:8000/api"
def tok(u,p): return {"Authorization":"Bearer "+requests.post(B+"/auth/login",json={"username":u,"password":p}).json()["access_token"]}
A=tok("alex.analyst","analyst_password123!"); J=tok("jordan.approver","approver_password123!")
p=lambda path,h,j=None: requests.post(B+path,headers=h,json=j)
r=p("/requests",A,dict(type="DELETION",requester_name="David Wilson",requester_email="david.wilson@example.com",account_id="ACC-1005",description="Please delete all my personal data")).json()["id"]
o=p(f"/requests/{r}/verification/send-otp",A).json()["simulated_outbox"]["otp_code"]
p(f"/requests/{r}/verification",A,dict(name="David Wilson",email="david.wilson@example.com",account_id="ACC-1005",otp=o)); p(f"/requests/{r}/agent/run",A)
p(f"/requests/{r}/approvals",J,dict(scope="PLAN",decision="APPROVED",reason="plan ok fine")); p(f"/requests/{r}/approvals",J,dict(scope="DELETION",decision="APPROVED",reason="deletion ok"))
res=[]
def go(): res.append(p(f"/requests/{r}/actions/execute",A,dict(scope="DELETION")))
ts=[threading.Thread(target=go) for _ in range(4)]; [t.start() for t in ts]; [t.join() for t in ts]
print("HTTP codes:",sorted(x.status_code for x in res))
for x in res:
    if x.status_code!=200: print("  ",x.status_code,x.json()["error"]["code"])
c=sqlite3.connect("data/app.db")
print("actions rows:",c.execute("select count(*) from actions").fetchone()[0],"| SUCCEEDED attempts:",c.execute("select count(*) from action_attempts where outcome='SUCCEEDED'").fetchone()[0],"| distinct keys:",c.execute("select count(distinct idempotency_key) from actions").fetchone()[0])
print("dup/unexpected statuses:",c.execute("select status,count(*) from actions group by status").fetchall())
print("request status:",requests.get(B+f"/requests/{r}",headers=A).json()["status"])
