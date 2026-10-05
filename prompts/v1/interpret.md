<policy>
{policy_rules_json}
</policy>

<request>
Form Type: {request_type}
Requester Name: {requester_name}
Requester Email: {requester_email}
Account ID: {account_id}
Relationship: {relationship}
Description:
{description}
</request>

Task:
Interpret the request, identify the true data subject, determine whether the stated form type matches the intent in the description (or if it should be reclassified or flagged for mismatch), and identify any specific changes requested (for corrections: target field and proposed new value).
List any verification information still missing for this request type under the organizational policy (such as missing account ID or OTP requirement).
Never guess identifiers or assume unverified claims.
Allowed request_type values: ACCESS, CORRECTION, DELETION, UNSUPPORTED (portability, objection, restriction -> UNSUPPORTED).
Respond ONLY with a JSON object matching InterpretationSchema.
