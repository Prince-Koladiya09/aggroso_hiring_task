<policy>
{policy_rules_json}
</policy>

<interpretation>
{interpretation_json}
</interpretation>

<records>
{records_xml}
</records>

Task:
Examine each retrieved record. Classify relevance to the data subject:
- RELEVANT: Belonging to the subject.
- UNRELATED: Matched search query by coincidence or belongs to someone else.
- UNCERTAIN: Needs human triage.

Propose an initial handling decision for each record:
- INCLUDE: Candidate for export or action.
- REDACT: Contains sensitive/third-party fields requiring masking.
- EXCLUDE_RETENTION: Prohibited from modification/deletion due to retention or legal hold policies (cite POL-RET-1, POL-RET-2, POL-RET-3).
- EXCLUDE_UNRELATED: Not the subject's record.
- NEEDS_REVIEW: Uncertain, human must decide.

Respond ONLY with JSON: {"classified": [{"record_id": "...", "relevance": "RELEVANT|UNRELATED|UNCERTAIN", "note": "..."}]}.
You may only make handling MORE cautious (e.g. mark UNCERTAIN); deterministic policy exclusions are applied by the system and cannot be overridden.
