<policy>
{policy_rules_json}
</policy>

<interpretation>
{interpretation_json}
</interpretation>

Task:
Decide which of the three data sources (profiles, tickets, activity_logs) must be searched to fulfil this request.
Return JSON: {"sources_considered": [{"source": "...", "decision": "SEARCH" | "SKIP", "reason": "..."}]}
Only these three sources exist. Cite policy rule IDs in the reason where a rule drives the decision.
You cannot choose identifiers or write queries: searches are always scoped to the verified subject by the system.
